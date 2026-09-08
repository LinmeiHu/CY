"""Small cash-account adapter for the frozen 70-row experiment, no production edits."""
import json,math,time,traceback
from collections import defaultdict
from pathlib import Path
import duckdb,numpy as np,pandas as pd
from .common import HERE,OUT,INV,dump,sha,scenarios,fee,quantity

class ExecutionGap(Exception):pass

def load_actions():
    invpath=INV/'QD-010-cninfo-actions-20260820.json';inv=json.loads(invpath.read_text());frames=[];bindings=[dict(path=str(invpath),sha256=sha(invpath))]
    for x in inv['files']:
        if not x['path'].endswith('.parquet'):continue
        p=Path(inv['root'])/x['path'];assert sha(p)==x['sha256']
        with duckdb.connect() as con:
            frames.append(con.execute("SELECT * FROM read_parquet(?) WHERE effective_date BETWEEN '2018-01-01' AND '2023-12-31'",[str(p)]).fetchdf())
        assert sha(p)==x['sha256'];bindings.append(dict(path=str(p),sha256=x['sha256']))
    d=pd.concat(frames,ignore_index=True)
    # Read-only official facts from completed shared-capital artifact; no strategy results consumed.
    back=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1/research/shared_capital_v1/output/corporate_action_official_backfill_facts.csv')
    for p in [back,HERE/'action_backfill.csv']:
        if p.exists():
            before=sha(p);f=pd.read_csv(p).set_index('action_id');assert sha(p)==before;bindings.append(dict(path=str(p),sha256=before))
            for i,r in d.iterrows():
                if r.event_id in f.index:
                    z=f.loc[r.event_id]
                    if pd.notna(z.get('tradable_date')):d.at[i,'share_credit_date']=pd.Timestamp(z.tradable_date)
                    if pd.notna(z.get('cash_payment_date')):d.at[i,'pay_date']=pd.Timestamp(z.cash_payment_date)
    assert not d.event_id.duplicated().any()
    d.attrs['input_bindings']=bindings
    return d

class Market:
    def __init__(self):
        ax=json.loads((OUT/'axes.json').read_text());self.dates=ax['dates'];self.symbols=ax['symbols'];self.boards=ax['boards'];self.industries=ax['industries'];self.sy={s[:6]:i for i,s in enumerate(self.symbols)}
        self.a={p.stem:np.load(p,mmap_mode='r') for p in OUT.glob('*.npy')}
        self.actions=load_actions();self.records=defaultdict(list);self.exdates=defaultdict(list)
        self.execution_binding=dict(actions=self.actions.attrs['input_bindings'],arrays=[dict(path=str(p),sha256=sha(p)) for p in sorted(OUT.glob('*.npy'))],axes=dict(path=str(OUT/'axes.json'),sha256=sha(OUT/'axes.json')))
        for r in self.actions.to_dict('records'):
            self.exdates[(r['symbol'],str(r['effective_date'].date()))].append(r)
            if pd.notna(r['record_date']) and r['symbol'] in self.sy:self.records[str(r['record_date'].date())].append(r)
    def val(self,f,t,j):return float(self.a[f][t,j])
    def legal(self,t,j,sell=False):
        a=self.a;o=a['open'][t,j]
        if not np.isfinite(o) or o<=0:return 'MISSING_OPEN'
        if a['trade_status'][t,j]!=1 or a['volume'][t,j]<=0:return 'SUSPENDED_OR_NO_TRADE'
        if a['sell_blocked_open' if sell else 'buy_blocked_open'][t,j]!=0:return 'LIMIT_OR_STATUS_BLOCK'
        limit=a['down_limit_price' if sell else 'up_limit_price'][t,j]
        if np.isfinite(limit) and ((sell and o<=limit+.000001) or (not sell and o>=limit-.000001)):return 'LIMIT_OPEN'
        if not sell and (a['hard_valid'][t,j]!=1 or a['corporate_action_blocking'][t,j]!=0 or np.nan_to_num(a['rights_ratio'][t,j],nan=0)!=0):return 'INVALID_EXECUTION_DATA'
        return ''

def select(frame,s):
    f=frame.copy();v=s['version'];rs=f.RS
    if v in ['B0','P','C','PC']:
        f['score']=rs if v=='B0' else .5*rs+.5*f.Path if v=='P' else .5*rs+.5*f.Consolidation if v=='C' else .5*rs+.25*f.Path+.25*f.Consolidation
    else:
        n4=.5*rs+.25*f.Path+.25*f.VCP
        if v=='N0':f['score']=rs
        else:
            f=f[f.medium if v=='N5' else f.long].copy()
            if v not in ['N1','N2']:f=f[f.VCP_GUARD].copy()
            if v=='N1':f['score']=f.RS
            elif v=='N2':f['score']=.5*f.RS+.5*f.Path
            elif v=='N3':f['score']=.5*f.RS+.5*f.VCP
            elif v=='N6':f['score']=.8*n4.loc[f.index]+.2*f.MR
            elif v=='N8':f['score']=.8*n4.loc[f.index]+.2*f.Volume
            elif v=='N9':f['score']=.6*n4.loc[f.index]+.2*f.MR+.2*f.Volume
            elif v=='N4_PLUS':f['score']=.8*n4.loc[f.index]+.2*f.Industry
            else:f['score']=n4.loc[f.index]
            if v in ['N7','N9']:f=f[f.market_gate]
            if s['module']=='INDUSTRY':f=f[f.Industry.notna()]
    return f.sort_values(['t','score','symbol'],ascending=[True,False,True])

def replay(m,s,frame):
    f=select(frame,s);schedule={int(t)+s['delay']:g.to_dict('records') for t,g in f.groupby('t')}
    cash=1e6;navprev=1e6;positions={};active=[];trades=[];orders=[];nav=[];audits=[];entitlements=[]
    fees=0.;slippage=0.;turnover=0.;nextlot=0
    def holding_value(t):
        total=0.
        for p in positions.values():
            px=m.val('close',t,p['j'])
            if np.isfinite(px) and px>0:p['mark']=px;p['stale']=0
            else:p['stale']+=1
            total+=(p['q']+p['pending'])*p['mark']
        return total
    def checkpoint(t):
        mv=holding_value(t);rec=sum(x['receivable'] for x in active)
        return cash+mv+rec-sum(x.get('tax_reserve',0.) for x in active),mv,rec
    for t,day in enumerate(m.dates):
        if day<'2020-01-01':continue
        # All pre-auction commitments use yesterday's available cash and yesterday NAV.
        priorcash=cash-sum(x.get('tax_reserve',0.) for x in active);priornav=navprev
        candidates=schedule.get(t,[]);chosen=[];free=10-len(positions)
        for r in candidates:
            j=int(r['j']);base=dict(t=t,signal_t=int(r['t']),symbol=r['symbol'],score=r['score'])
            if j in positions:orders.append(dict(base,status='HELD'));continue
            if len(chosen)>=free:orders.append(dict(base,status='SLOTS_OR_RANK'));continue
            chosen.append((r,base))
        commitments=[];reserved=0.
        caps=np.array([min(float(r['amount20'])*.01,priornav*.1 if s['mode']=='CAP10' else priorcash) for r,_ in chosen])
        budgets=np.zeros(len(chosen));remaining=priorcash
        # Equal division with deterministic pre-order redistribution of capacity slack.
        for _ in range(len(chosen)+1):
            eligible=np.where(caps-budgets>1e-8)[0]
            if not len(eligible) or remaining<1e-8:break
            extra=np.minimum(caps[eligible]-budgets[eligible],remaining/len(eligible));budgets[eligible]+=extra;remaining-=float(extra.sum())
        for ci,(r,base) in enumerate(chosen):
            j=int(r['j'])
            # Construct the order coordinate directly from pre-open information.
            # Never use coord_t / close_t: that cancellation fails after an invalid prior day.
            previous=m.val('coord',t-1,j);previous_close=m.val('close',t-1,j)
            multiplier=m.val('share_multiplier',t,j);cash_term=m.val('cash_per_share',t,j)
            reference=(previous_close-cash_term)/multiplier if np.isfinite(multiplier) and multiplier>0 else np.nan
            factor=previous/reference if np.isfinite(reference) and reference>0 else np.nan
            known=all(pd.notna(x['known_at']) and x['known_at']<=pd.Timestamp(day) for x in m.exdates.get((r['symbol'][:6],day),[]))
            if not np.isfinite(factor) or factor<=0 or not known:orders.append(dict(base,status='UNRESOLVED_PREOPEN_ACTION'));continue
            base['preopen_factor']=factor
            limit=math.floor(r['limit']*r['factor']/factor*100+1e-8)/100
            upper=m.val('up_limit_price',t,j)
            if np.isfinite(upper):limit=min(limit,upper)
            lower=m.val('down_limit_price',t,j)
            if limit<=0 or (np.isfinite(lower) and limit<lower-1e-8):
                orders.append(dict(base,status='FROZEN_LIMIT_BELOW_LEGAL_RANGE',frozen_limit=limit,legal_lower=lower));continue
            U=r['U']*r['factor']/factor
            budget=float(budgets[ci])
            q=quantity(budget,limit,day,m.boards[j],s['cost'])
            if q<=0:orders.append(dict(base,status='CASH_OR_CAPACITY',budget=budget));continue
            reserve=q*limit+fee(q*limit,day,mult=s['cost']);reserved+=reserve
            assert reserved<=priorcash+1e-7
            commitments.append((r,base,j,q,limit,U,reserve))
        # Date-effective entitlements are execution facts, never ranking information.
        for x in active:
            p=x['position'];a=x['action'];ex=str(a['effective_date'].date())
            if day==ex and not x['ex_done']:
                extra=x['baseq']*(float(a['share_multiplier'])-1)
                credited=math.floor(extra+1e-8)
                if extra-credited>1e-7:
                    audits.append(dict(day=day,symbol=p['symbol'],lot=p['lot'],type='FRACTIONAL_ALLOCATION_LOWER_BOUND',event_id=a['event_id'],theoretical_quantity=extra,credited_quantity=credited,unallocated_fraction=extra-credited,quantity_upper_bound=credited+1))
                x['credited_extra']=credited
                p['pending']+=credited;x['receivable']=x['baseq']*float(a['cash_per_share_gross'])
                x['tax_base']=x['baseq']*(float(a['cash_per_share_gross'])+float(a['bonus_share_ratio'] or 0.))
                x['tax_reserve']=x['tax_base']*.2;p['dividend_accrued']+=x['receivable']-x['tax_reserve']
                audits.append(dict(day=day,symbol=p['symbol'],lot=p['lot'],type='SHARE_EFFECTIVE',quantity=credited,event_id=a['event_id']))
                p['mark']=(p['mark']-float(a['cash_per_share_gross']))/float(a['share_multiplier']);x['ex_done']=True
                # original stop held in invariant causal coordinate, so no action-made trigger.
            if x['ex_done'] and not x.get('tax_settled',False):
                acquired=pd.Timestamp(m.dates[p['e']]);today=pd.Timestamp(day)
                rate=.2 if today<=acquired+pd.DateOffset(months=1) else .1 if today<=acquired+pd.DateOffset(years=1) else 0.
                liability=x['tax_base']*rate;p['dividend_accrued']+=x['tax_reserve']-liability;x['tax_reserve']=liability
            if pd.notna(a['share_credit_date']) and day>=str(a['share_credit_date'].date()) and x['ex_done'] and not x['shares_done']:
                extra=x['credited_extra'];p['pending']-=extra;p['q']+=extra;x['shares_done']=True;audits.append(dict(day=day,symbol=p['symbol'],lot=p['lot'],type='SHARE_TRADABLE',quantity=extra,event_id=a['event_id']))
            if pd.notna(a['pay_date']) and day>=str(a['pay_date'].date()) and x['ex_done'] and not x['paid']:
                audits.append(dict(day=day,symbol=p['symbol'],lot=p['lot'],type='DIVIDEND_PAYMENT',cash_delta=x['receivable'],event_id=a['event_id']))
                cash+=x['receivable'];p['dividend_net']+=x['receivable'];x['receivable']=0;x['paid']=True
        # Execute precommitted buys before sell credits; all checks preserve T+1.
        for r,base,j,q,limit,U,reserve in commitments:
            reason=m.legal(t,j);op=m.val('open',t,j);price=math.ceil(op*(1+.0005*s['cost'])*100-1e-8)/100 if np.isfinite(op) else np.nan
            if not reason and price>limit+1e-8:reason='OVER_LIMIT'
            if not reason and price>m.val('up_limit_price',t,j):reason='SLIPPAGE_EXCEEDS_LEGAL_PRICE'
            if reason:orders.append(dict(base,status=reason,limit=limit,opening=op,quantity=q));continue
            cost=fee(q*price,day,mult=s['cost']);debit=q*price+cost
            assert debit<=reserve+1e-7 and debit<=cash+1e-7
            cash-=debit;fees+=cost;slippage+=q*(price-op);turnover+=q*price;nextlot+=1
            p=dict(j=j,symbol=m.symbols[j],lot=nextlot,q=q,pending=0,e=t,signal_t=int(r['t']),entry=price,entry_cash=debit,initial_q=q,mark=price,stale=0,due=t+(40 if s['exit']=='TREND40' else 10),planned=t+(40 if s['exit']=='TREND40' else 10),exit_reason='MAX40' if s['exit']=='TREND40' else 'FIXED10',S0coord=r['S0']*r['factor'],dividend_net=0.,dividend_accrued=0.,sell_value=0.,sell_fees=0.,lowopen=op<U,industry=int(r['industry']),planned_risk=q*max(0,limit-r['S0']*r['factor']/base['preopen_factor']),nav_at_order=priornav,buy_day_breach=False,intraday_only=0)
            positions[j]=p;orders.append(dict(base,status='FILLED',limit=limit,opening=op,fill=price,quantity=q,reserved=reserve,debit=debit,lowopen=op<U,preauction_cash=priorcash))
        for j,p in list(positions.items()):
            if t<p['due'] or t<=p['e']:continue
            reason=m.legal(t,j,True)
            if reason:audits.append(dict(day=day,symbol=p['symbol'],type='EXIT_DEFERRED',reason=reason,due=p['due']));continue
            if p['q']<=0:continue
            op=m.val('open',t,j);price=math.floor(op*(1-.0005*s['cost'])*100+1e-8)/100
            if price<m.val('down_limit_price',t,j):audits.append(dict(day=day,symbol=p['symbol'],type='EXIT_DEFERRED',reason='SLIPPAGE_BELOW_LEGAL_PRICE',due=p['due']));continue
            q=p['q'];value=q*price;cost=fee(value,day,True,s['cost']);cash+=value-cost;p['sell_value']+=value;p['sell_fees']+=cost;p['q']=0
            fees+=cost;slippage+=q*(op-price);turnover+=value
            audits.append(dict(day=day,t=t,symbol=p['symbol'],lot=p['lot'],type='SELL_FILL',quantity=q,price=price,fee=cost,cash_delta=value-cost))
            if p['pending']==0:
                for x in active:
                    if x['position'] is p and x['ex_done'] and not x.get('tax_settled',False):
                        audits.append(dict(day=day,symbol=p['symbol'],lot=p['lot'],type='TAX_SETTLEMENT',cash_delta=-x['tax_reserve'],event_id=x['action']['event_id']))
                        cash-=x['tax_reserve'];x['tax_reserve']=0.;x['tax_settled']=True
                trades.append(dict(p,exit_t=t,exit_date=day,entry_date=m.dates[p['e']],exit_price=price,held_sessions=t-p['e'],exit_delay=t-p['planned'],pnl=p['sell_value']-p['sell_fees']+p['dividend_accrued']-p['entry_cash']))
                del positions[j]
        # Only known official record-date ownership activates future payout obligations.
        for a in m.records.get(day,[]):
            j=m.sy[a['symbol']]
            if j not in positions:continue
            p=positions[j]
            if a['event_type']=='rights_issue':
                audits.append(dict(day=day,symbol=p['symbol'],type='RIGHTS_NOT_SUBSCRIBED',event_id=a['event_id']));continue
            missing=[]
            if pd.isna(a['known_at']) or a['known_at']>pd.Timestamp(day)+pd.Timedelta(hours=15):missing.append('known_at')
            if float(a['share_multiplier'])>1 and pd.isna(a['share_credit_date']):missing.append('share_credit_date')
            if float(a['cash_per_share_gross'])>0 and pd.isna(a['pay_date']):missing.append('pay_date')
            if missing:
                entitlements.append(dict(scenario=s['id'],symbol=p['symbol'],action_id=a['event_id'],missing='|'.join(missing),record_date=day,effective_date=a['effective_date'],source_api=a['source_api'],response_sha256=a['response_sha256']))
                d=OUT/s['id'];d.mkdir(exist_ok=True);pd.DataFrame(entitlements).to_csv(d/'action_gaps.csv',index=False)
                raise ExecutionGap('HELD_ACTION_MISSING:'+a['event_id']+':'+','.join(missing))
            active.append(dict(action=a,position=p,baseq=p['q']+p['pending'],receivable=0.,ex_done=False,shares_done=False,paid=False))
            audits.append(dict(day=day,symbol=p['symbol'],type='RECORD_ENTITLEMENT',event_id=a['event_id'],quantity=p['q']+p['pending'],share_credit_date=a['share_credit_date'],pay_date=a['pay_date']))
        for p in positions.values():
            j=p['j'];cc=m.val('coord',t,j);lo=m.val('low',t,j)*m.val('factor',t,j);s0=p['S0coord']
            if lo<=s0 and cc>s0:p['intraday_only']+=1
            if t==p['e'] and lo<=s0:p['buy_day_breach']=True
            if s['exit']=='TREND40' and p['due']>t:
                reason='STRUCTURE' if cc<=s0 else 'SMA10' if t-p['e']>=5 and cc<m.val('ma10',t,j) else ''
                if reason:p['due']=t+1;p['planned']=t+1;p['exit_reason']=reason
        total,mv,rec=checkpoint(t)
        freecash=cash-sum(x.get('tax_reserve',0.) for x in active)
        assert freecash>=-1e-7 and total>0 and mv<=total+1e-7 and reserved<=priorcash+1e-7
        # Algebraic reconciliation plus independent daily cash-flow audit in finalize.
        nav.append(dict(date=day,t=t,cash=freecash,book_cash=cash,tax_reserve=cash-freecash,market_value=mv,receivable=rec,nav=total,return_daily=total/navprev-1,exposure=mv/total,holdings=len(positions),max_single=max([(p['q']+p['pending'])*p['mark']/total for p in positions.values()],default=0),fees_cum=fees,slippage_cum=slippage,turnover_cum=turnover,raw_signals=len(candidates),submitted=len(commitments),cash_no_signal=cash if not candidates else 0,cash_slots=cash if free==0 else 0,borrowed_cash=0,margin=0))
        navprev=total
    for r in f[f.t+s['delay']>=len(m.dates)].to_dict('records'):
        orders.append(dict(t=int(r['t'])+s['delay'],signal_t=int(r['t']),symbol=r['symbol'],score=r['score'],status='END_BOUNDARY_NO_ENTRY_SESSION'))
    return pd.DataFrame(nav),pd.DataFrame(trades),pd.DataFrame(orders),pd.DataFrame(audits),pd.DataFrame(positions.values())

def metrics(nav,trades):
    r=nav.return_daily.to_numpy();v=np.r_[1e6,nav.nav.to_numpy()];dd=v/np.maximum.accumulate(v)-1;i=int(dd.argmin());n=len(nav)
    return dict(net_return=v[-1]/1e6-1,cagr=(v[-1]/1e6)**(252/n)-1,maxdd=float(dd.min()),maxdd_date=nav.date.iloc[max(0,i-1)],volatility=float(np.std(r,ddof=1)*np.sqrt(252)),sharpe=float(np.mean(r)/np.std(r,ddof=1)*np.sqrt(252)) if np.std(r)>0 else 0,mean_exposure=nav.exposure.mean(),p95_exposure=nav.exposure.quantile(.95),max_single=nav.max_single.max(),trades=len(trades),mean_hold=trades.held_sessions.mean() if len(trades) else 0,deferred_trades=int((trades.exit_delay>0).sum()) if len(trades) else 0,fees=nav.fees_cum.iloc[-1],slippage=nav.slippage_cum.iloc[-1],turnover=nav.turnover_cum.iloc[-1]/nav.nav.mean(),end_open=int(nav.holdings.iloc[-1]))

def run():
    m=Market();dump(HERE/'execution_input_binding.json',m.execution_binding);summaries=[];frames={};start=time.time()
    for s in scenarios():
        row=dict(s,status='NOT_RUN_DATA_GATE',reason='',verified_reuse=False)
        if s['module'] in ['CATALYST','FUNDAMENTALS']:
            row['reason']='exact other-purpose announcement authorization' if s['module']=='CATALYST' else 'missing first-release revision history';summaries.append(row);continue
        family='N' if not s['group'].startswith('OLD') else f"OLD_{s['a']}_{s['w']}"
        if not (OUT/(family+'_signals.parquet')).exists():
            row.update(status='NOT_RUN_FEATURE_BUILD_PENDING',reason='shared cache still building');summaries.append(row);continue
        if family not in frames:frames[family]=pd.read_parquet(OUT/(family+'_signals.parquet'))
        d=OUT/s['id'];d.mkdir(exist_ok=True);stamp=time.time()
        try:
            nav,trades,orders,audit,openpos=replay(m,s,frames[family]);row.update(metrics(nav,trades),status='NEWLY_EXECUTED',output=str(d),started_at=stamp,ended_at=time.time())
            for name,data in [('nav',nav),('trades',trades),('orders',orders),('audit',audit),('open_positions',openpos)]:data.to_parquet(d/(name+'.parquet'),index=False)
            dump(d/'identity.json',dict(config=s,config_hash=s['config_hash'],source_hash=sha(Path(__file__)),input_hash=sha(HERE/'input_binding.json'),execution_input_hash=sha(HERE/'execution_input_binding.json'),features_hash=sha(OUT/(family+'_signals.parquet')),artifacts={p.name:sha(p) for p in d.glob('*.parquet')}))
        except ExecutionGap as e:row.update(status='BLOCKED_EXECUTION_FACT',reason=str(e),output=str(d))
        except Exception:
            traceback.print_exc();raise
        summaries.append(row);pd.DataFrame(summaries).to_csv(HERE/'scenario_summary.csv',index=False)
        print('SCENARIO',len(summaries),s['id'],row['status'],row.get('reason',''),round(time.time()-stamp,1),flush=True)
    pd.DataFrame(summaries).to_csv(HERE/'scenario_summary.csv',index=False)
    print('DONE',time.time()-start,flush=True)
if __name__=='__main__':run()
