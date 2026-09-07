"""Limited execution pressure, paired uncertainty and descriptive headroom."""
from pathlib import Path
import json
import math
import duckdb
import numpy as np
import pandas as pd
from state_v2 import HERE,read_bound,write_json


def minute_audit(config):
    ext=Path(config['external_root']);root=Path(config['inputs']['raw_minute_root'])
    paths=pd.read_parquet(ext/'candidate_position_paths.parquet',columns=['symbol','trade_date','open','down_limit_price','state_valid'])
    req=paths.drop_duplicates(['symbol','trade_date']).copy()
    # All eligible opportunity days, not only eventual losers or successful stops.
    pieces=[]
    cache=ext/'minute_open_execution_evidence.parquet'
    if cache.exists(): minute=pd.read_parquet(cache)
    else:
        for year,r in req.groupby(req.trade_date.dt.year):
            assert year<=2023
            p=root/f'{year}_day_parquet_none.parquet'
            con=duckdb.connect(config={'threads':1,'memory_limit':'1GB'});con.register('req',r)
            sql="""SELECT r.symbol,r.trade_date,r.open daily_open,r.down_limit_price,r.state_valid,
                      m.bar_end_time,m.open minute_open,m.volume minute_volume
                      FROM req r LEFT JOIN read_parquet(?) m ON m.qmt_code=r.symbol AND m.trade_date=r.trade_date
                         AND m.period='1m' AND m.adjust='none' AND CAST(m.bar_end_time AS TIME)<=TIME '09:31:00'
                      QUALIFY row_number() OVER (PARTITION BY r.symbol,r.trade_date ORDER BY m.bar_end_time)=1"""
            pieces.append(con.execute(sql,[str(p)]).fetchdf());con.close()
        minute=pd.concat(pieces,ignore_index=True);minute.to_parquet(cache,index=False)
    minute['has_open_bar']=minute.minute_open.notna()
    minute['positive_volume']=minute.minute_volume.gt(0)
    minute['price_matches_daily_tick']=(np.rint(minute.minute_open*100)==np.rint(minute.daily_open*100))
    minute['above_lower_limit']=np.rint(minute.minute_open*100)>np.rint(minute.down_limit_price*100)
    coverage=[]
    for year,g in minute.groupby(minute.trade_date.dt.year):
        coverage.append(dict(year=year,requested_security_days=len(g),has_open_bar=int(g.has_open_bar.sum()),
                             positive_volume=int(g.positive_volume.sum()),price_tick_match=int(g.price_matches_daily_tick.sum()),
                             selection='All candidate held-path days, both funded/unfunded, no return conditioning',features_added=0))
    pd.DataFrame(coverage).to_csv(HERE/'minute_execution_coverage.csv',index=False)
    t=pd.read_parquet(ext/'all_source_normalized.parquet',columns=['episode_id','symbol'])
    audit=[]
    for p in sorted(ext.glob('policy_*_events.parquet')):
        e=pd.read_parquet(p);e=e.loc[e.filled].merge(t,on='episode_id',validate='one_to_one')
        e['trade_date']=pd.to_datetime(e.exit_time_policy).dt.normalize()
        e=e.merge(minute,on=['symbol','trade_date'],how='left',validate='many_to_one')
        e['verified_model_open']=e.has_open_bar.fillna(False)&e.positive_volume.fillna(False)&e.price_matches_daily_tick.fillna(False)&e.above_lower_limit.fillna(False)
        accepted=pd.read_parquet(Path(str(p).replace('_events.parquet','_accepted.parquet')))
        shadow=accepted.loc[accepted.exit_reason.str.startswith('SHADOW',na=False)]
        key='gap_id' if 'gap_id' in shadow else 'event_id'
        assert set(shadow[key]).issubset(set(e.event_id))
        e['actual_account_exit']=e.event_id.isin(shadow[key])
        e['actual_verified_exit']=e.actual_account_exit&e.verified_model_open
        e['policy_file']=p.name
        audit.append(e[['policy_file','episode_id','symbol','trade_date','has_open_bar','positive_volume','price_matches_daily_tick','above_lower_limit','verified_model_open','actual_account_exit','actual_verified_exit']])
    pd.concat(audit,ignore_index=True).to_csv(HERE/'minute_fill_audit.csv',index=False)


def diagnostic_statistics(config):
    ext=Path(config['external_root']);states=pd.read_parquet(ext/'position_state_snapshots.parquet')
    losses=pd.read_parquet(ext/'loss_episodes.parquet');contract=json.loads((HERE/'research_contract.json').read_text())
    rows=[];transitions=[];matched=[];duration=[]
    for episode,g in states.sort_values('decision_at').groupby('episode_id',sort=False):
        underwater=g.current_pnl.lt(0)
        runs=underwater.groupby((~underwater).cumsum()).sum()
        below=g.anchor_distance.lt(0);first=np.flatnonzero(below.to_numpy())
        recovery=np.nan
        if len(first):
            after=g.iloc[first[0]+1:];back=after.loc[after.anchor_distance.ge(0)]
            if len(back):recovery=float(back.age.iloc[0]-g.age.iloc[first[0]])
        duration.append(dict(episode_id=episode,route=g.route.iloc[0],max_underwater_observed_sessions=int(runs.max()),
                             first_breach_recovery_sessions=recovery,recovery_status='RECOVERED_BEFORE_NATIVE' if np.isfinite(recovery) else 'NO_OBSERVED_RECOVERY_OR_NO_BREACH',
                             scope='Observable held-close states; invalid/final partial-day extrema not inferred'))
    pd.DataFrame(duration).to_csv(HERE/'path_duration_diagnostics.csv',index=False)
    for route,d in losses.groupby('route',sort=True):
        d=d.loc[d.mature];s=states.loc[states.route.eq(route)&states.state_valid&states.exit_filled]
        # Future-aware upper bound, a diagnostic only, not a training/policy feature.
        oracle=s.groupby('episode_id').exit_advantage_normalized.max().clip(lower=0)
        gains=s.groupby('episode_id').EXIT_ADVANTAGE_NET.max().clip(lower=0)
        severe=d.native_net_return.le(-.1);w=d.native_net_return.gt(0)
        rows.append(dict(route=route,mature_events=len(d),signal_dates=d.signal_date.nunique(),severe=int(severe.sum()),
                         severe_signal_dates=d.loc[severe,'signal_date'].nunique(),severe_symbols=d.loc[severe,'symbol'].nunique(),
                         winner_mae_median=d.loc[w,'mae_observed'].median(),winner_mae_p05=d.loc[w,'mae_observed'].quantile(.05),
                         losers_prior_mfe_median=d.loc[~w,'mfe_observed'].median(),
                         severe_never_profited5=int((severe&d.never_profited_5pct).sum()),severe_prior_profit5=int((severe&d.profit_giveback).sum()),
                         underwater_days_median=d.underwater_days.median(),breach_recovery_events=int(d.breached_then_recovered.sum()),
                         foresight_eligible_events=len(oracle),foresight_mean_best_normalized=oracle.mean(),foresight_sum_amount=gains.sum(),
                         headroom_label='PERFECT_FORESIGHT_DIAGNOSTIC; restricted to observed held closes and simulated next opens, excludes unobservable final intraday day'))
        s=states.loc[states.route.eq(route)].sort_values(['episode_id','decision_at']).copy()
        s['observable_state']=np.select([~s.state_valid,s.anchor_below_run.ge(2),s.current_pnl.lt(0)],['DATA_UNAVAILABLE','STRUCTURE_WEAK','UNDERWATER'],default='NONNEGATIVE')
        s['next_observable_state']=s.groupby('episode_id').observable_state.shift(-1)
        x=s.dropna(subset=['next_observable_state']).groupby(['observable_state','next_observable_state']).agg(position_transitions=('episode_id','size'),events=('episode_id','nunique')).reset_index()
        for r in x.to_dict('records'):transitions.append(dict(route=route,**r))
        # Sparse-case matching uses contemporaneous PnL/age/volatility bins, outcome read only afterwards.
        s=s.loc[s.state_valid&s.label_status.eq('MATURE')].copy()
        s['pnl_bin']=np.floor(s.current_pnl/.025);s['age_bin']=np.floor(s.age/3);s['atr_bin']=np.floor(s.atr_entry_frac/.025)
        s=s.sort_values('decision_at').drop_duplicates(['episode_id','pnl_bin','age_bin','atr_bin'])
        for key,g in s.groupby(['pnl_bin','age_bin','atr_bin']):
            broken=g.loc[g.anchor_below_run.ge(2)];normal=g.loc[g.anchor_below_run.lt(2)]
            if len(broken)>=3 and len(normal)>=3:
                matched.append(dict(route=route,pnl_bin=key[0],age_bin=key[1],atr_bin=key[2],broken_events=broken.episode_id.nunique(),normal_events=normal.episode_id.nunique(),broken_advantage=broken.exit_advantage_normalized.mean(),normal_advantage=normal.exit_advantage_normalized.mean(),interpretation='Descriptive matched states, repeated episodes across bins not independent, no parameter selection'))
    pd.DataFrame(rows).to_csv(HERE/'loss_anatomy_summary.csv',index=False)
    pd.DataFrame(transitions).to_csv(HERE/'state_transitions.csv',index=False)
    pd.DataFrame(matched).to_csv(HERE/'matched_state_checks.csv',index=False)
    ci=[]
    # Synchronous month blocks evaluate paired returns, not executable synthetic NAVs.
    for path in sorted(ext.glob('policy_*_nav.parquet')):
        label=path.name[len('policy_'):-len('_nav.parquet')]
        routes=['ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','ATRDR_BULL','IFCGR','MCB','OGR']
        route=next(r for r in routes if label.startswith(r+'_'))
        strategy='ATRDR' if route.startswith('ATRDR') else route
        segment='CONTINUOUS_2014_2023' if strategy in ['ATRDR','MCB'] else ('2022_2023' if '2022_2023' in label else '2018_2021')
        b=pd.read_parquet(ext/f'{strategy}_{segment}_nav.parquet').set_index('trade_date').nav
        n=pd.read_parquet(path).set_index('trade_date').nav
        frame=pd.concat([b.rename('native'),n.rename('policy')],axis=1,join='inner').sort_index()
        returns=frame.pct_change(fill_method=None).dropna()
        returns=returns.loc[returns.index>=pd.Timestamp(contract['splits'][route][2])]
        if returns.empty:continue
        diff=returns.policy-returns.native
        blocks=[g.to_numpy() for _,g in diff.groupby(diff.index.to_period('M'))]
        rng=np.random.default_rng(1729);means=[]
        for _ in range(1000):
            sampled=[blocks[i] for i in rng.integers(0,len(blocks),len(blocks))]
            means.append(np.concatenate(sampled).mean())
        ci.append(dict(account=label,blocks=len(blocks),n_days=len(diff),paired_mean_daily_difference=diff.mean(),ci025=np.quantile(means,.025),ci975=np.quantile(means,.975),repetitions=1000,
                       limitation='Frozen comparison only; no claim to remove selection bias; ATRDR account remains quarantined'))
    pd.DataFrame(ci).to_csv(HERE/'paired_month_block_intervals.csv',index=False)
    source=pd.read_parquet(ext/'all_source_normalized.parquet',columns=['event_id','episode_id'])
    paths=pd.read_parquet(ext/'candidate_position_paths.parquet')
    flow=pd.read_csv(HERE/'funded_flow_changes.csv');support=[]
    for row in flow.loc[flow.change.eq('NEWLY_FUNDED')].itertuples(index=False):
        ids=source.loc[source.event_id.eq(row.event_id),'episode_id'];g=paths.loc[paths.episode_id.isin(ids)]
        columns=['current_pnl'] if row.policy.startswith('fixed') else ['anchor_below_run','close_location'] if row.policy.startswith('H1') else ['current_pnl','down_volume_ratio','recovery_3']
        support.append(dict(route=row.route,segment=row.segment,policy=row.policy,event_id=row.event_id,
            matched_original_source_paths=bool(len(g)),state_rows=len(g),missing_required_states=int(g[columns].isna().any(axis=1).sum()) if len(g) else np.nan,
            model_domain='NOT_APPLICABLE_HAND_CODED_RULE_NO_PREDICTED_ORDER',
            missing_behavior='No rule trigger with missing required feature; native remains',
            note='Complete source path available; not restricted to baseline-funded episodes' if len(g) else 'Fast capacity-eligible path generated in upstream policy replay'))
    pd.DataFrame(support).to_csv(HERE/'new_funding_support.csv',index=False)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--minutes',action='store_true');args=p.parse_args()
    config=json.loads((HERE/'input_config.json').read_text())
    diagnostic_statistics(config)
    if args.minutes:minute_audit(config)
