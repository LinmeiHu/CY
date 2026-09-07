"""Economic reconciliation and immutable-input verification for the fixed closure."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from run_closure import HERE,PARENT,sha,write_json

def run():
    cfg=json.loads((HERE/'run_config.json').read_text());out=Path(cfg['external_root'])
    policies=['NATIVE']+[x['candidate_id'] for x in json.loads((HERE/'smv6_exit_candidate_contract.json').read_text())['candidates']]
    baseline=pd.read_parquet(out/'SMV6_NATIVE_trades.parquet').set_index('episode_id')
    bnav=pd.read_parquet(out/'SMV6_NATIVE_nav.parquet');base_terminal=float(bnav.nav.iloc[-1])
    audits=[];decomps=[]
    for name in policies:
        e=pd.read_parquet(out/f'SMV6_{name}_events.parquet')
        n=pd.read_parquet(out/f'SMV6_{name}_nav.parquet')
        states=pd.read_parquet(out/f'SMV6_{name}_event_states.parquet')
        trades=pd.read_parquet(out/f'SMV6_{name}_trades.parquet').set_index('episode_id')
        f=e.loc[e.filled_delta_qty.fillna(0).ne(0)].copy()
        expected_fee=f.filled_delta_qty.abs()*f.price_pre_adj*.0002
        expected_fill=f.market_price*(1+np.sign(f.filled_delta_qty)*.0008)
        fee_error=float((f.fee-expected_fee).abs().max());price_error=float((f.price_pre_adj-expected_fill).abs().max())
        used=f.groupby(['trade_date','symbol','stage']).agg(used=('filled_delta_qty',lambda x:x.abs().sum()),cap=('volume_cap_qty','max'))
        volume_violation=int(used.used.gt(used.cap).sum())
        risk=f.loc[f.risk_order]
        fill_at=pd.to_datetime(risk.trade_date)+pd.Timedelta(hours=9,minutes=30)
        pit_violations=int((fill_at<=pd.to_datetime(risk.risk_trigger_at)).sum())
        cash=1e6-(f.filled_delta_qty*f.price_pre_adj+f.fee).sum()
        reconciliation_error=float(cash-n.cash.iloc[-1])
        assert abs(reconciliation_error)<1e-7 and fee_error<1e-8 and price_error<1e-10
        assert volume_violation==0 and pit_violations==0
        assert f.filled_delta_qty.mod(100).eq(0).all()
        assert n.cash.min()>=-1e-8 and states.cash.min()>=-1e-8
        assert (n.gross_exposure-n.nav).max()<=1e-8 and states.gross_ratio.max()<=1+1e-10
        audits.append(dict(candidate=name,events=len(e),fills=len(f),account_days=len(n),missing_nav_days=int(n.nav.isna().sum()),
            missing_event_marks=int(states.nav.isna().sum()),min_cash=n.cash.min(),min_event_cash=states.cash.min(),
            max_gross_ratio=(n.gross_exposure/n.nav).max(),max_event_gross_ratio=states.gross_ratio.max(),
            lot_violations=int(f.filled_delta_qty.mod(100).ne(0).sum()),volume_violations=volume_violation,
            fee_error=fee_error,slippage_error=price_error,pit_violations=pit_violations,
            partial_sells=int(e.event_type.eq('SELL_PARTIAL').sum()),unfilled_sells=int(e.event_type.isin(['SELL_NO_FILL','RISK_SELL_NO_FILL']).sum()),
            cash_reconciliation_error=reconciliation_error,status='PASS_OBSERVABLE_STATES; TWO_EARLY_MARKS_MISSING'))
        common=trades.index.intersection(baseline.index);new=trades.index.difference(baseline.index);cancel=baseline.index.difference(trades.index)
        # All full-history episodes in current results are closed; fail rather than invent a mark.
        assert not trades.right_censored.any() and not baseline.right_censored.any()
        common_delta=(trades.loc[common,'pnl']-baseline.loc[common,'pnl']).sum()
        new_pnl=trades.loc[new,'pnl'].sum();cancel_pnl=-baseline.loc[cancel,'pnl'].sum()
        delta=float(n.nav.iloc[-1]-base_terminal)
        error=float(delta-common_delta-new_pnl-cancel_pnl)
        assert abs(error)<1e-7
        decomps.append(dict(candidate=name,period='ALL_AUTHORIZED',units='CNY_INITIAL_1000000',account_nav_delta=delta,
            common_episode_net_pnl_delta=common_delta,new_episode_realized_pnl=new_pnl,cancelled_episode_pnl_effect=cancel_pnl,
            added_episodes=len(new),cancelled_episodes=len(cancel),terminal_inventory_delta=0.,reconciliation_error=error,
            interpretation='Common component includes changed size/rebalances; added episode PnL is already in NAV, not pure separately identifiable cash-release alpha'))
    pd.DataFrame(audits).to_csv(HERE/'smv6_execution_audit.csv',index=False)
    pd.DataFrame(decomps).to_csv(HERE/'smv6_cashflow_decomposition.csv',index=False)
    # Raw episode intermediates sum known marks; official anatomy must expose
    # incomplete capital-days instead of silently treating missing marks as zero.
    anatomy=pd.read_csv(HERE/'smv6_native_trade_anatomy.csv')
    inv=pd.read_parquet(out/'SMV6_NATIVE_inventory.parquet')
    anatomy['capital_days_missing_marks']=0
    for i,row in anatomy.iterrows():
        held=inv.loc[inv.symbol.eq(row.symbol)&inv.entry_date.eq(pd.Timestamp(row.entry_date))]
        missing=int(held.price.isna().sum());anatomy.loc[i,'capital_days_missing_marks']=missing
        if missing:anatomy.loc[i,'capital_days']=np.nan
    anatomy.to_csv(HERE/'smv6_native_trade_anatomy.csv',index=False)
    checks=[]
    manifest=json.loads((HERE/'input_manifest.json').read_text())
    for item in manifest['protected']+manifest['inputs']:
        checks.append(dict(path=item['path'],expected=item['sha256'],actual=sha(item['path'])))
        if 'source' in item:checks.append(dict(path=item['source'],expected=item['source_sha256'],actual=sha(item['source'])))
    for item in json.loads((HERE/'reused_input_hashes.json').read_text()):
        checks.append(dict(path=item['path'],expected=item['sha256'],actual=sha(item['path'])))
    oldseal=json.loads((PARENT/'completion_manifest.json').read_text())
    for rel,meta in oldseal['research_files'].items():checks.append(dict(path=str(PARENT/rel),expected=meta['sha256'],actual=sha(PARENT/rel)))
    original=json.loads((PARENT/'input_and_exposure_manifest.json').read_text())
    for rel,meta in original['artifacts'].items():
        path=Path(cfg['old_root'])/rel
        checks.append(dict(path=str(path),expected=meta['sha256'],actual=sha(path)))
    visual=PARENT/'visual_v1';seal=json.loads((visual/'completion_manifest.json').read_text())
    for rel,meta in seal['research_files'].items():checks.append(dict(path=str(visual/rel),expected=meta['sha256'],actual=sha(visual/rel)))
    ext=Path(seal['external_root']);index=ext/'artifact_hash_index.json'
    checks.append(dict(path=str(index),expected=seal['external_index_sha256'],actual=sha(index)))
    for rel,meta in json.loads(index.read_text())['files'].items():
        checks.append(dict(path=str(ext/rel),expected=meta['sha256'],actual=sha(ext/rel)))
    mismatches=[x for x in checks if x['expected']!=x['actual']]
    write_json(HERE/'integrity_validation.json',dict(checks=len(checks),mismatches=mismatches,source_inputs_preserved=not mismatches,
        frozen_strategies_modified=False,old_parent_and_visual_seals_unchanged=not mismatches))
    assert not mismatches,mismatches
    write_json(out/'integrity_checked_files.json',checks)

if __name__=='__main__':run()
