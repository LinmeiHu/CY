"""Independent per-opportunity native stock lifecycle execution."""
from dataclasses import replace
import json
from types import MethodType
import numpy as np
import pandas as pd
from research.shared_capital_v1 import stock_p0
from research.shared_capital_v1.shared_account.engine import PhysicalAccount
from .repair import OUT, END, load, write_json


def path_metrics(path, outlay, entry_at, exit_at):
    p=pd.DataFrame(path).drop_duplicates('timestamp',keep='last').sort_values('timestamp')
    pre=p.loc[p.timestamp.lt(exit_at)] if exit_at is not None else p
    if pre.empty:pre=p.iloc[:1]
    ret=pre.pnl/outlay
    hi=ret.idxmax();lo=ret.idxmin()
    days=(p.timestamp-p.timestamp.shift()).dt.total_seconds().fillna(0)/86400
    capital_days=float((days*p.exposure.shift().fillna(0)).sum())
    underwater_start=None;duration=0.
    for r in p.itertuples():
        if r.pnl < 0:
            if underwater_start is None:underwater_start=r.timestamp
            duration=max(duration,(r.timestamp-underwater_start).total_seconds()/86400)
        else:underwater_start=None
    final=float(p.pnl.iloc[-1])
    return dict(native_realized_return=final/outlay if exit_at is not None else None,
        native_realized_pnl=final if exit_at is not None else None,marked_pnl_at_cutoff=final,
        pre_exit_MFE=float(ret.loc[hi]),pre_exit_MAE=float(ret.loc[lo]),
        time_to_MFE=(pre.loc[hi,'timestamp']-entry_at).total_seconds()/86400,
        time_to_MAE=(pre.loc[lo,'timestamp']-entry_at).total_seconds()/86400,
        holding_days=((exit_at if exit_at is not None else p.timestamp.iloc[-1])-entry_at).total_seconds()/86400,
        capital_days=capital_days,peak_unrealized_return=float(ret.max()),
        giveback_from_peak_to_exit=float(ret.max()-final/outlay) if exit_at is not None else None,
        max_underwater_duration=duration,open_at_cutoff=exit_at is None,open_at_2026_cutoff=exit_at is None,
        pnl_normalized_1m=final/outlay*1e6,mark_convention='Native open / close / action / execution checkpoints')


def stock_shadow(request,entry,daily,actions):
    """Only target-native state: immutable signal coordinate and actual entry request.

    Stock exits read target position state and raw registered bars/actions; they
    never read other symbols, future membership, or future funding. Unrelated
    native active positions are therefore not required by this isolated clone.
    """
    s=request['strategy'];eid=request['event_id'];start=str(pd.Timestamp(request['funding_at']).date())
    # Sufficient cash for exact native execution; only reporting is normalized.
    seed=max(1e6,float(request['requested_increase_notional'])*100)
    account=PhysicalAccount('OGR',initial_cash=seed*4)
    account.strategies=(s,);account.initial_cash=account.cash=seed
    account.sleeve_cash={s:seed};account.realized={s:0.}
    def fund(self,intents,home,policy,when,**kwargs):
        for intent in intents:
            if intent.event_id!=eid:raise ValueError('unrelated shadow entry')
            exact=replace(intent,native_requested_quantity=request['native_requested_quantity'])
            if abs(exact.price-request['price'])>1e-9:raise ValueError('shadow raw entry price drift')
            self.validate_intents([exact],when)
            self._fill(exact,exact.native_requested_notional,'BASE',when)
    account.fund=MethodType(fund,account)
    actions=actions.loc[actions.symbol.eq(request['symbol'][:6])]
    stream,result=stock_p0.replay(s,entry,daily,start,END,physical=account,stream_only=True,action_registry=actions)
    path=[];entered=False;exit_at=None
    for event in stream:
        event.callback()
        if account.fills:entered=True
        if entered:
            path.append(dict(timestamp=pd.Timestamp(event.when),pnl=account.cash+account.exposure()-seed,exposure=account.exposure()))
            if not account.lots and not account.held_actions[s].active:
                exit_at=pd.Timestamp(event.when);break
    if not entered:raise ValueError('shadow expected executable native request produced no entry')
    fills=pd.DataFrame(account.fills);buys=fills.loc[fills.side.eq('BUY')];sells=fills.loc[fills.side.eq('SELL')]
    outlay=float(buys.funded_notional.sum());entry_at=pd.Timestamp(buys.entry.min())
    if len(sells) and exit_at is not None:exit_at=pd.Timestamp(sells.exit.max())
    row=dict(opportunity_id=eid,strategy=s,symbol=request['symbol'],entry_at=entry_at,exit_at=exit_at,
        exit_reason='|'.join(sells.reason.astype(str).drop_duplicates()) if len(sells) else '',entry_notional=outlay,
        fees=float(account.fees),corporate_actions=json.dumps(account.held_actions[s].audit,sort_keys=True,default=str),
        status='COMPLETED' if exit_at is not None else 'RIGHT_CENSORED',**path_metrics(path,outlay,entry_at,exit_at))
    return row,path,fills


def run(limit=None, tag=""):
    dest=OUT/'repair_accounts'/f'IFCGR__{END}'
    requests=pd.read_parquet(dest/'precapital.parquet')
    requests=requests.loc[requests.strategy.isin(['ATRDR','MCB'])].copy()
    # Native structural rejections are retained in the opportunity audit, but
    # must not be promoted into legally executable shadows.
    account=json.loads((dest/'account.json').read_text())
    requests=requests.loc[~requests.event_id.isin(account['native_failures'])]
    native=pd.read_parquet(dest/'fills.parquet')
    funded_ids=set(native.loc[native.side.eq('BUY'),'event_id'])
    requests=requests.loc[~requests.event_id.isin(funded_ids)]
    if limit:requests=requests.head(limit)
    data=load(END);rows=[];failures=[];identity=[];allpaths=[]
    required=['symbol','trade_date','open','close','coord_open','coord_close','coord_high','coordinate_factor','cal_idx','invalid_step_cum',
              'hard_valid','history_valid','current_valid','corporate_action_valid','current_day_data_tradable','market_rule_valid',
              'corporate_action_blocking','trade_status','down_limit_price','corporate_action_count','historical_identity_valid']
    for strategy in ['ATRDR','MCB']:
        e,d=data[strategy]
        byevent={eid:g for eid,g in e.groupby('event_id',sort=False)}
        bysymbol={symbol:g for symbol,g in d[required].groupby('symbol',sort=False)}
        data[strategy]=(byevent,bysymbol)
    del d,e
    print('SHADOW_INDEX_READY',len(requests),flush=True)
    native=pd.read_parquet(dest/'fills.parquet')
    for n,r in enumerate(requests.to_dict('records')):
        s=r['strategy'];entries,prices=data[s]
        e=entries[r['event_id']]
        d=prices[r['symbol']]
        d=d.loc[d.trade_date.ge(pd.Timestamp(r['funding_at']).normalize())]
        try:
            row,path,fills=stock_shadow(r,e,d,data['actions']);rows.append(row)
            allpaths.extend(dict(x,opportunity_id=r['event_id']) for x in path)
            nf=native.loc[native.event_id.eq(r['event_id']) | native.root_event_id.eq(r['event_id'])]
            if nf.side.eq('BUY').any():
                fields=['side','entry','exit','filled_quantity','price','exit_price','fee','pnl']
                fields=[c for c in fields if c in nf and c in fills]
                try:
                    pd.testing.assert_frame_equal(fills[fields].reset_index(drop=True),nf[fields].reset_index(drop=True),check_dtype=False,rtol=1e-10,atol=1e-6)
                    status='PASS';error=''
                except AssertionError as err:status='FAIL';error=str(err)
                identity.append(dict(opportunity_id=r['event_id'],status=status,error=error))
        except (ValueError,KeyError) as err:
            failures.append(dict(opportunity_id=r['event_id'],strategy=s,symbol=r['symbol'],error=str(err)))
        if n%50==0:print('SHADOW',n,'completed',len(rows),'failures',len(failures),flush=True)
        if failures:
            # Preserve exact error and continue other independent events; a
            # missing held-action fact cannot be replaced with a fabricated date.
            pd.DataFrame(failures).to_csv(OUT/('shadow_repair_failures'+tag+'.csv'),index=False)
    pd.DataFrame(rows).to_csv(OUT/('shadow_stock_lifecycle_v2'+tag+'.csv.gz'),index=False,compression={'method':'gzip','mtime':0})
    pd.DataFrame(identity).to_csv(OUT/('shadow_stock_identity_v2'+tag+'.csv'),index=False)
    pd.DataFrame(allpaths).to_csv(OUT/('shadow_stock_marked_paths_v2'+tag+'.csv.gz'),index=False,compression={'method':'gzip','mtime':0})
    print('SHADOW_RESULT',len(rows),len(failures),pd.DataFrame(identity).status.value_counts().to_dict() if identity else {},flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--limit',type=int);p.add_argument('--tag',default='');a=p.parse_args();run(a.limit,a.tag)
