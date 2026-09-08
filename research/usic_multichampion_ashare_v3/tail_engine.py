"""Frozen V3 entitlement replay with genuine morning exits and later 14:25 order decisions.
Derived mechanically from core engine; separately tested and hash bound for Q3/Q4 only."""
import json,math,time
from collections import defaultdict
import numpy as np
import pandas as pd
from .common import HERE,OUT,CACHE,sha,dump,parquet,fee,quantity
from .legacy_replay import load_actions,ExecutionGap,metrics


class Market:
    def __init__(self):
        ax=json.loads((CACHE/'axes.json').read_text());self.dates=ax['dates'];self.symbols=ax['symbols'];self.boards=ax['boards'];self.industries=ax['industries'];self.sy={s[:6]:i for i,s in enumerate(self.symbols)}
        self.a={p.stem:np.load(p,mmap_mode='r') for p in CACHE.glob('*.npy')}
        self.actions=load_actions();self.records=defaultdict(list);self.exdates=defaultdict(list)
        self.execution_binding=dict(actions=self.actions.attrs['input_bindings'],cache_manifest=sha(HERE/'INPUT_MANIFEST.json'))
        for r in self.actions.to_dict('records'):
            self.exdates[(r['symbol'],str(r['effective_date'].date()))].append(r)
            if pd.notna(r['record_date']) and r['symbol'] in self.sy:self.records[str(r['record_date'].date())].append(r)
        idx=pd.read_csv(CACHE/'market.csv')['index'];ma=idx.rolling(60).mean()
        self.state=np.where((idx>=ma)&(ma>=ma.shift(20)),'BULL',np.where((idx<ma)&(ma<ma.shift(20)),'BEAR','TRANSITION'))
        self.capacity=np.empty(self.a['amount'].shape)
        for j in range(len(self.symbols)):self.capacity[:,j]=pd.Series(self.a['amount'][:,j]).rolling(20).median().to_numpy()*.005
    def val(self,f,t,j):return float(self.a[f][t,j])
    def legal(self,t,j,sell=False):
        a=self.a;o=a['open'][t,j]
        if not np.isfinite(o) or o<=0:return 'MISSING_OPEN'
        if a['trade_status'][t,j]!=1 or a['volume'][t,j]<=0:return 'SUSPENDED_OR_NO_TRADE'
        if a['sell_blocked_open' if sell else 'buy_blocked_open'][t,j]!=0:return 'LIMIT_OR_STATUS_BLOCK'
        limit=a['down_limit_price' if sell else 'up_limit_price'][t,j]
        if np.isfinite(limit) and ((sell and o<=limit+1e-6) or (not sell and o>=limit-1e-6)):return 'LIMIT_OPEN'
        if not sell and a['hard_valid'][t,j]!=1:return 'INVALID_EXECUTION_DATA'
        return ''

def ordered_candidates(candidates,positions,s,nav,cash):
    if s.get('policy')!='P1_BALANCED':return candidates
    families=['D02','D03','D06','D09'];value={r:sum((p['q']+p['pending'])*p['mark'] for p in positions.values() if p['family']==r) for r in families}
    remaining=list(candidates);ordered=[];seen=set();slots=(1 if s['mode']=='C_ONE' else 10)-len(positions)
    available={r['j'] for r in remaining if r['j'] not in positions};n=min(slots,len(available));allocation=min(cash/max(n,1),nav*.1) if s['mode']=='C_10' else cash/max(n,1)
    while remaining:
        choices=[f for f in families if any(r['route']==f and r['j'] not in seen and r['j'] not in positions for r in remaining)]
        if not choices:break
        family=min(choices,key=lambda f:(value[f],families.index(f)))
        r=sorted((r for r in remaining if r['route']==family and r['j'] not in seen and r['j'] not in positions),key=lambda r:(-r['score'],r['symbol']))[0]
        ordered.append(r);seen.add(r['j']);value[family]+=allocation
        remaining=[r for r in remaining if r['j'] not in seen]
    return ordered+[r for r in candidates if r['j'] in positions]

def cash_budgets(caps,cash,mode):
    budgets=np.zeros(len(caps));remaining=max(0.,cash)
    if mode=='C_10':
        for i,cap in enumerate(caps):budgets[i]=min(cap,remaining);remaining-=budgets[i]
    else:
        for _ in range(len(caps)):
            eligible=np.flatnonzero(caps-budgets>1e-8)
            if not len(eligible) or remaining<=1e-8:break
            extra=np.minimum(caps[eligible]-budgets[eligible],remaining/len(eligible));budgets[eligible]+=extra;remaining-=float(extra.sum())
    return budgets

def replay(m,s,frame):
    f=frame.copy();schedule={int(t)+s['delay']:g.to_dict('records') for t,g in f.groupby('t')}
    cash=1e6;navprev=1e6;positions={};active=[];trades=[];orders=[];nav=[];audits=[];entitlements=[]
    fees=0.;slippage=0.;turnover=0.;nextlot=0;target=.25;holds=[];adds=defaultdict(list)
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
        for j,p in list(positions.items()):
            if t<p['due'] or t<=p['e']:continue
            reason=m.legal(t,j,True)
            if reason:audits.append(dict(day=day,symbol=p['symbol'],type='EXIT_DEFERRED',reason=reason,due=p['due']));continue
            if p['q']<=0:continue
            op=m.val('open',t,j);price=math.floor(op*(1-.0005*s['cost'])*100+1e-8)/100
            if price<m.val('down_limit_price',t,j):audits.append(dict(day=day,symbol=p['symbol'],type='EXIT_DEFERRED',reason='SLIPPAGE_BELOW_LEGAL_PRICE',due=p['due']));continue
            assert all(t>lot['e'] for lot in p['lots']), 'NEW_LOT_T1'
            q=p['q'];value=q*price;cost=fee(value,day,True,s['cost']);cash+=value-cost;p['sell_value']+=value;p['sell_fees']+=cost;p['q']=0
            fees+=cost;slippage+=q*(op-price);turnover+=value
            p['risk_used']=0. if p['pending']==0 else p['risk_used']*p['pending']/(q+p['pending'])
            p['add_pnl']+=sum(lot['q']*(price-lot['price']) for lot in p['lots'] if lot['role']=='ADD')
            audits.append(dict(day=day,t=t,symbol=p['symbol'],lot=p['lot'],type='SELL_FILL',quantity=q,price=price,fee=cost,cash_delta=value-cost))
            if p['pending']==0:
                for x in active:
                    if x['position'] is p and x['ex_done'] and not x.get('tax_settled',False):
                        audits.append(dict(day=day,symbol=p['symbol'],lot=p['lot'],type='TAX_SETTLEMENT',cash_delta=-x['tax_reserve'],event_id=x['action']['event_id']))
                        cash-=x['tax_reserve'];x['tax_reserve']=0.;x['tax_settled']=True
                trades.append(dict(p,exit_t=t,exit_date=day,entry_date=m.dates[p['e']],exit_price=price,held_sessions=t-p['e'],exit_delay=t-p['planned'],pnl=p['sell_value']-p['sell_fees']+p['dividend_accrued']-p['entry_cash']))
                del positions[j]
        # Opening exits have really settled. Mark surviving stock at the observable 14:25 price.
        mark_mv=0.
        for p in positions.values():
            px=m.mark1425(t,p['j'])
            if np.isfinite(px) and px>0:p['mark']=px
            else:audits.append(dict(day=day,symbol=p['symbol'],type='STALE_1425_MARK',price=p['mark']))
            mark_mv+=(p['q']+p['pending'])*p['mark']
        # Tail commitments may use actual morning proceeds, never future close proceeds.

        priorcash=cash-sum(x.get('tax_reserve',0.) for x in active);priornav=cash+mark_mv+sum(x['receivable']-x.get('tax_reserve',0.) for x in active)
        candidates=schedule.get(t,[])
        candidates=ordered_candidates(candidates,positions,s,priornav,priorcash)
        state=m.state[max(0,t-s['delay']-1)]
        overlay=s.get('overlay','NONE');risk=overlay in ['R_ONCE','R_STAGE']
        if overlay=='G_RAMP':target=min(1.,target+.25) if state=='BULL' else 0. if state=='BEAR' else max(0.,target-.25)
        allowed_cash=min(priorcash,max(0.,target*priornav-sum((p['q']+p['pending'])*p['mark'] for p in positions.values()))) if overlay=='G_RAMP' else priorcash
        if overlay=='G_DOWN' and state=='BEAR':allowed_cash=0.
        chosen=[];free=(1 if s['mode']=='C_ONE' else 10)-len(positions);seen=set()
        for r in candidates:
            j=int(r['j']);base=dict(t=t,signal_t=int(r['t']),symbol=r['symbol'],score=r['score'],setup_id=r['setup_id'],family=r['route'],decision_at=r['decision_at'])
            if j in seen:orders.append(dict(base,status='PHYSICAL_SECURITY_DEDUP'));continue
            seen.add(j)
            if j in positions:orders.append(dict(base,status='HELD'));continue
            if len(chosen)>=free:orders.append(dict(base,status='SLOTS_OR_RANK'));continue
            if allowed_cash<=0:orders.append(dict(base,status='MARKET_BUDGET_BLOCK' if overlay in ['G_DOWN','G_RAMP'] else 'NO_CASH'));continue
            chosen.append((r,base))
        commitments=[];reserved=0.;reserved_risk=0.;risk_existing=sum(p.get('risk_used',0.) for p in positions.values())
        prepared=[]
        for r,base in chosen:
            j=int(r['j']);factor=m.val('factor',t,j)
            known=all(pd.notna(x['known_at']) and x['known_at']<=pd.Timestamp(day) for x in m.exdates.get((r['symbol'][:6],day),[]))
            if not np.isfinite(factor) or factor<=0 or not known:orders.append(dict(base,status='UNRESOLVED_PREOPEN_ACTION'));continue
            limit=math.floor(r['limit']*r['factor']/factor*100+1e-8)/100
            upper=m.val('up_limit_price',t,j);lower=m.val('down_limit_price',t,j)
            if np.isfinite(upper):limit=min(limit,upper)
            if limit<=0 or (np.isfinite(lower) and limit<lower-1e-8):orders.append(dict(base,status='FROZEN_LIMIT_BELOW_LEGAL_RANGE',limit=limit));continue
            A=r['a0']*r['factor']/factor;S0=r['S0']*r['factor']/factor;unitrisk=max(limit-S0,.5*A)
            if risk and limit<=S0:orders.append(dict(base,status='INVALID_RISK_DIRECTION'));continue
            cap=m.capacity[t-1,j]
            if not np.isfinite(cap):orders.append(dict(base,status='MISSING_PRIOR_CAPACITY'));continue
            budget_cap=min(priorcash,priornav*.1 if s['mode']=='C_10' else priorcash,cap+fee(cap,day,mult=s['cost']))
            maxq=quantity(budget_cap,limit,day,m.boards[j],s['cost'],maxq=cap/limit)
            if risk:maxq=quantity(budget_cap,limit,day,m.boards[j],s['cost'],maxq=min(maxq,priornav*(.005 if overlay=='R_STAGE' else .01)/unitrisk,max(0.,priornav*.02-risk_existing-reserved_risk)/unitrisk))
            capcost=maxq*limit+fee(maxq*limit,day,mult=s['cost']) if maxq else 0.
            prepared.append((r,base,j,limit,r['U']*r['factor']/factor,unitrisk,maxq,capcost,cap))
        caps=np.array([r[7] for r in prepared]);budgets=cash_budgets(caps,allowed_cash,s['mode'])
        for ci,(r,base,j,limit,U,unitrisk,maxq,capcost,cap) in enumerate(prepared):
            if risk:maxq=min(maxq,int(max(0.,priornav*.02-risk_existing-reserved_risk)/unitrisk))
            q=quantity(float(budgets[ci]),limit,day,m.boards[j],s['cost'],maxq=maxq)
            if q<=0:orders.append(dict(base,status='RISK_OR_CASH_OR_CAPACITY',budget=float(budgets[ci])));continue
            reserve=q*limit+fee(q*limit,day,mult=s['cost']);reserved+=reserve;reserved_risk+=q*unitrisk if risk else 0.
            assert reserved<=allowed_cash+1e-7 and q*limit<=cap+1e-7
            commitments.append([r,base,j,q,limit,U,reserve,unitrisk,False])
        # Integer residual allocation is decided before seeing any opening outcome.
        if s['mode'] in ['C_MAX','C_ONE'] and not risk:
            leftover=allowed_cash-reserved
            for item in commitments:
                r,base,j,q,limit,U,reserve,unitrisk,isadd=item
                maxq=next(z[6] for z in prepared if z[2]==j)
                nq=quantity(reserve+leftover,limit,day,m.boards[j],s['cost'],maxq=maxq)
                newreserve=nq*limit+fee(nq*limit,day,mult=s['cost'])
                leftover-=newreserve-reserve;reserved+=newreserve-reserve;item[3]=nq;item[6]=newreserve
        # Add only the original winning security, with one separate acquisition lot.
        for r in adds.get(t,[]):
            j=int(r['j']);p=positions.get(j);base=dict(t=t,signal_t=t-1,symbol=r['symbol'],score=0.,setup_id=r['setup_id'],family=r['route'],decision_at=m.dates[t-1]+'T15:00:00+08:00',is_add=True)
            if p is None or p['due']<=t or p.get('added',False):orders.append(dict(base,status='ADD_EXIT_PRIORITY_OR_CLOSED'));continue
            factor=m.val('factor',t,j);limit=math.floor(r['limit']*r['factor']/factor*100+1e-8)/100;upper=m.val('up_limit_price',t,j)
            if np.isfinite(upper):limit=min(limit,upper)
            lower=m.val('down_limit_price',t,j)
            if limit<=0 or (np.isfinite(lower) and limit<lower):orders.append(dict(base,status='ADD_ILLEGAL_LIMIT'));continue
            S0=p['S0coord']/factor;A=p['Acoord']/factor;unitrisk=max(limit-S0,.5*A);cap=m.capacity[t-1,j]
            maxrisk=min(priornav*.005,max(0.,priornav*.01-p['risk_used']),max(0.,priornav*.02-risk_existing-reserved_risk))
            maxq=min(p['initial_q']/2,maxrisk/unitrisk,cap/limit)
            budget=priorcash-reserved
            if s['mode']=='C_10':budget=min(budget,max(0.,priornav*.1-(p['q']+p['pending'])*p['mark']))
            q=quantity(budget,limit,day,m.boards[j],s['cost'],maxq=maxq)
            if q<=0:orders.append(dict(base,status='ADD_BUDGET_BOUND',budget=budget,remaining_plan_risk=maxrisk));continue
            reserve=q*limit+fee(q*limit,day,mult=s['cost']);reserved+=reserve;reserved_risk+=q*unitrisk
            commitments.append([r,base,j,q,limit,r['U']*r['factor']/factor,reserve,unitrisk,True])
        assert reserved<=priorcash+1e-7
        # Execute precommitted buys before sell credits; all checks preserve T+1.
        for r,base,j,q,limit,U,reserve,unitrisk,isadd in commitments:
            reason,op,price,fill_clock=m.tail_fill(t,j,q,limit,s['cost'])
            if not reason and price>limit+1e-8:reason='OVER_LIMIT'
            if not reason and price>m.val('up_limit_price',t,j):reason='SLIPPAGE_EXCEEDS_LEGAL_PRICE'
            if reason:orders.append(dict(base,status=reason,limit=limit,opening=op,quantity=q));continue
            cost=fee(q*price,day,mult=s['cost']);debit=q*price+cost
            assert debit<=reserve+1e-7 and debit<=cash+1e-7
            cash-=debit;fees+=cost;slippage+=q*(price-op);turnover+=q*price;nextlot+=1
            p=dict(j=j,symbol=m.symbols[j],lot=nextlot,q=q,pending=0,e=t,signal_t=int(r['t']),entry=price,entry_cash=debit,initial_q=q,mark=price,stale=0,due=t+(40 if s['exit']=='TREND40' else s.get('fixed_holding',10)),planned=t+(40 if s['exit']=='TREND40' else s.get('fixed_holding',10)),exit_reason='MAX40' if s['exit']=='TREND40' else 'FIXED10',S0coord=r['S0']*r['factor'],dividend_net=0.,dividend_accrued=0.,sell_value=0.,sell_fees=0.,lowopen=op<U,industry=int(r['industry']),planned_risk=q*max(0,limit-r['S0']*r['factor']/m.val('factor',t,j)),nav_at_order=priornav,buy_day_breach=False,intraday_only=0)
            p.update(family=r['route'],Acoord=r['a0']*r['factor'],risk_used=q*max(price-r['S0']*r['factor']/m.val('factor',t,j),.5*r['a0']*r['factor']/m.val('factor',t,j)),added=False,lots=[dict(e=t,q=q,price=price,role='INITIAL')],add_pnl=0.)
            if isadd:
                old=positions[j];old['q']+=q;old['entry_cash']+=debit;old['risk_used']+=q*max(price-old['S0coord']/m.val('factor',t,j),.5*old['Acoord']/m.val('factor',t,j));old['added']=True;old['lots'].append(dict(e=t,q=q,price=price,role='ADD'));p=old
            else:positions[j]=p
            orders.append(dict(base,status='FILLED',limit=limit,opening=op,fill=price,quantity=q,reserved=reserve,debit=debit,lowopen=op<U,preauction_cash=priorcash,fill_clock=fill_clock,decision_nav=priornav,clock_grade='MINUTE_OHLC_PROXY'))
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
        active=[x for x in active if not (x.get('paid',False) and x.get('shares_done',False) and x.get('tax_settled',False))]
        for p in positions.values():
            j=p['j'];cc=m.val('coord',t,j);lo=m.val('low',t,j)*m.val('factor',t,j);s0=p['S0coord']
            if lo<=s0 and cc>s0:p['intraday_only']+=1
            if t==p['e'] and lo<=s0:p['buy_day_breach']=True
            if s['exit']=='TREND40' and p['due']>t:
                reason='STRUCTURE' if cc<=s0 else 'SMA10' if t-p['e']>=5 and cc<m.val('ma10',t,j) else ''
                if reason:p['due']=t+1;p['planned']=t+1;p['exit_reason']=reason
        if overlay=='R_STAGE':
            for p in positions.values():
                j=p['j'];factor=m.val('factor',t,j);A=p['Acoord'];initial=p['lots'][0];R=initial['price']-p['S0coord']/m.val('factor',p['e'],j)
                if t-p['e']<3 or p.get('add_attempted',False) or p['due']<=t+1 or R<=0:continue
                hh=m.a['high'][t-3:t,j]*m.a['factor'][t-3:t,j];ll=m.a['low'][t-3:t,j]*m.a['factor'][t-3:t,j];cc=m.val('coord',t,j)
                entry_coord=initial['price']*m.val('factor',p['e'],j);Rcoord=R*m.val('factor',p['e'],j)
                if cc>=entry_coord+Rcoord and np.max(hh)-np.min(ll)<=A and cc>np.max(hh):
                    p['add_attempted']=True
                    adds[t+1].append(dict(j=j,t=t,symbol=p['symbol'],route=p['family'],setup_id=f"ADD:{p['lot']}:{t}",factor=factor,U=np.max(hh)/factor,limit=(np.max(hh)+.5*A)/factor,S0=p['S0coord']/factor,a0=A/factor,industry=p['industry']))
        total,mv,rec=checkpoint(t)
        freecash=cash-sum(x.get('tax_reserve',0.) for x in active)
        assert freecash>=-1e-7 and total>0 and mv<=total+1e-7 and reserved<=priorcash+1e-7
        # Algebraic reconciliation plus independent daily cash-flow audit in finalize.
        nav.append(dict(date=day,t=t,cash=freecash,book_cash=cash,tax_reserve=cash-freecash,market_value=mv,receivable=rec,nav=total,return_daily=total/navprev-1,exposure=mv/total,holdings=len(positions),max_single=max([(p['q']+p['pending'])*p['mark']/total for p in positions.values()],default=0),fees_cum=fees,slippage_cum=slippage,turnover_cum=turnover,raw_signals=len(candidates),submitted=len(commitments),cash_no_signal=cash if not candidates else 0,cash_slots=cash if free==0 else 0,borrowed_cash=0,margin=0))
        for p in positions.values():holds.append(dict(date=day,t=t,j=p['j'],symbol=p['symbol'],family=p['family'],q=p['q'],pending=p['pending'],price=p['mark'],value=(p['q']+p['pending'])*p['mark'],risk_used=p['risk_used'],mark_risk=(p['q']+p['pending'])*max(0,p['mark']-p['S0coord']/m.val('factor',t,p['j'])),lot=p['lot'],industry=p['industry']))
        navprev=total
    for r in f[f.t+s['delay']>=len(m.dates)].to_dict('records'):
        orders.append(dict(t=int(r['t'])+s['delay'],signal_t=int(r['t']),symbol=r['symbol'],score=r['score'],status='END_BOUNDARY_NO_ENTRY_SESSION'))
    return pd.DataFrame(nav),pd.DataFrame(trades),pd.DataFrame(orders),pd.DataFrame(audits),pd.DataFrame(positions.values()),pd.DataFrame(holds)
