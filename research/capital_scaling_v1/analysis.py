"""Descriptive attribution and discrete frontiers; no allocation optimization."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .preflight import HERE, PARENT
from .metrics import ratio, drawdown_attribution

OUT = HERE/'output'
ORDER = ['NATIVE', 'G25', 'G50', 'G75', 'G100']
IDS = ['scope', 'strategy', 'gap', 'mcb_mode', 'period', 'target', 'grade', 'mechanic', 'priority']
BASE_KEYS = ['scope', 'strategy', 'gap', 'mcb_mode', 'period']


def save(name, rows):
    frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    frame.to_csv(OUT/f'{name}.csv', index=False)
    return frame


def read_daily(row):
    d = pd.read_parquet(Path(row.source)/'daily.parquet')
    state = json.loads((Path(row.source)/'account.json').read_text())
    for s in ('ATRDR', 'MCB', row.gap, 'SMV6'):
        for f in ('nav', 'cash', 'exposure'):
            if s+'_'+f not in d:
                d[s+'_'+f] = 0.
    d.attrs['initial_states'] = {s: state['initial_states'].get(s, dict(nav=0.)) for s in ('ATRDR', 'MCB', row.gap, 'SMV6')}
    d.attrs['initial_cash'] = state['initial_cash']
    return d


def base_key(row):
    return tuple(row[k] if isinstance(row, dict) else getattr(row, k) for k in BASE_KEYS)


def comparisons(table, main):
    native = {base_key(r): r for r in main.loc[main.target.eq('NATIVE')].itertuples(index=False)}
    incremental = []
    for r in table.itertuples(index=False):
        b = native[base_key(r)]
        row = {k: getattr(r, k) for k in IDS}
        for key in ('CAGR', 'MaxDD', 'CVaR5', 'capital_days', 'net_pnl', 'average_gross_exposure'):
            row['incremental_'+key] = getattr(r, key)-getattr(b, key)
        row['incremental_pnl_per_capital_day'], row['capital_day_denominator_status'] = ratio(row['incremental_net_pnl'], row['incremental_capital_days'])
        incremental.append(row)
    incremental = save('incremental_capital_efficiency', incremental)
    save('priority_scaling_diagnostics', incremental.loc[incremental.priority.ne('')])
    steps = []
    for keys, frame in main.groupby(BASE_KEYS, sort=True):
        values = frame.set_index('target')
        for left, right in zip(ORDER, ORDER[1:]):
            a, b = values.loc[left], values.loc[right]
            row = dict(zip(BASE_KEYS, keys), from_target=left, to_target=right)
            for key in ('CAGR', 'MaxDD', 'CVaR5', 'average_gross_exposure', 'capital_days', 'net_pnl'):
                row['delta_'+key] = b[key]-a[key]
            row['incremental_pnl_per_added_capital_day'], row['capital_day_denominator_status'] = ratio(row['delta_net_pnl'], row['delta_capital_days'])
            row['incremental_CAGR_per_incremental_MaxDD'], row['drawdown_denominator_status'] = ratio(row['delta_CAGR'], row['delta_MaxDD'])
            steps.append(row)
    save('marginal_frontier', steps)
    bands = []
    combined = main.loc[main.scope.eq('COMBINED')]
    for (gap, mode), frame in combined.groupby(['gap', 'mcb_mode']):
        for limit in (.05, .08, .10, .15):
            valid = [t for t in ORDER if len(frame.loc[frame.target.eq(t)]) == 2 and frame.loc[frame.target.eq(t), 'MaxDD'].max() <= limit]
            observed = [t for t in ORDER if len(frame.loc[frame.target.eq(t)]) == 2 and frame.loc[frame.target.eq(t), 'observed_completed_timestamp_MaxDD'].max() <= limit]
            bands.append(dict(gap=gap, mcb_mode=mode, risk_band=limit, admissible_targets='|'.join(valid),
                              highest_tested_target=valid[-1] if valid else 'NONE', risk_measure='DAILY_CLOSE_NAV_MAXDD',
                              completed_timestamp_admissible_targets='|'.join(observed),
                              highest_completed_timestamp_reference=observed[-1] if observed else 'NONE',
                              interpretation='HISTORICAL_REFERENCE_NOT_PRODUCTION'))
    save('risk_budget_reference', bands)
    mechanics = []
    for r in table.loc[table.mechanic.eq('ENTRY_ONLY')].itertuples(index=False):
        baseline = main.loc[(main.scope.eq('COMBINED')) & main.gap.eq(r.gap) & main.mcb_mode.eq(r.mcb_mode) & main.period.eq(r.period) & main.target.eq('G100')].iloc[0]
        row = {k: getattr(r, k) for k in IDS}
        for k in ('CAGR', 'MaxDD', 'turnover', 'max_single_security_weight', 'average_gross_exposure', 'capital_days'):
            row[k+'_full_book'] = baseline[k]
            row[k+'_entry_only'] = getattr(r, k)
            row['delta_'+k] = getattr(r, k)-baseline[k]
        row['interpretation'] = 'SCALING_MECHANICS_SENSITIVE' if any(abs(row['delta_'+k]) > 1e-10 for k in ('CAGR', 'MaxDD', 'turnover')) else 'EVIDENCE_INSUFFICIENT'
        mechanics.append(row)
    save('g100_scaling_mechanics_sensitivity', mechanics)
    ideal = table.loc[table.grade.eq('IDEALIZED_SCALING_BOUND')].merge(
        main.loc[main.target.eq('G100')], on=BASE_KEYS+['target', 'mechanic', 'priority'], suffixes=('_idealized', '_execution'), validate='one_to_one')
    for k in ('CAGR', 'MaxDD', 'CVaR5', 'capital_days', 'turnover', 'net_pnl'):
        ideal['delta_'+k] = ideal[k+'_execution']-ideal[k+'_idealized']
    ideal['interpretation'] = 'CAPACITY_NOT_MODELED'
    save('idealized_vs_execution_aware', ideal)
    return native, incremental


def attribute(table, main, native):
    route_rows, annual, drawdowns = [], [], []
    native_events = {}
    for key, row in native.items():
        native_events[key] = pd.read_csv(Path(row.source)/'event_attribution.csv')
    for r in table.itertuples(index=False):
        identity = {k: getattr(r, k) for k in IDS}
        events = pd.read_csv(Path(r.source)/'event_attribution.csv')
        baseline = native_events[base_key(r)]
        fields = ['strategy', 'route', 'symbol', 'entry_date']
        a = events.groupby(fields)[['pnl', 'capital_days']].sum()
        b = baseline.groupby(fields)[['pnl', 'capital_days']].sum()
        merged = a.join(b, how='outer', lsuffix='_scaled', rsuffix='_native').fillna(0.)
        merged['incremental_pnl'] = merged.pnl_scaled-merged.pnl_native
        merged['incremental_capital_days'] = merged.capital_days_scaled-merged.capital_days_native
        merged.reset_index().to_parquet(Path(r.source)/'native_vs_scaled_event_attribution.parquet', index=False)
        route = merged.groupby(['strategy', 'route']).sum().reset_index()
        for item in route.to_dict('records'):
            route_rows.append(dict(identity, attributed_strategy=item.pop('strategy'), **item))
        d = read_daily(r)
        returns = d.nav.pct_change()
        returns.iloc[0] = d.nav.iloc[0]/r.initial_nav-1
        for year in sorted(d.trade_date.dt.year.unique()):
            mask = d.trade_date.dt.year.eq(year)
            selected = d.loc[mask]
            ret = returns.loc[mask]
            first_index = selected.index[0]
            initial = d.nav.iloc[first_index-1] if first_index else r.initial_nav
            high = selected.nav.cummax().clip(lower=initial)
            annual.append(dict(identity, year=year, total_return=float((1+ret).prod()-1), MaxDD=float((1-selected.nav/high).max()),
                               CVaR5=float(ret.nsmallest(max(1, int(np.ceil(.05*len(ret))))).mean()),
                               Sharpe=float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)) if ret.std(ddof=1) else 0.,
                               average_gross=float((selected.gross_exposure/selected.nav).mean()), net_pnl=float(selected.nav.iloc[-1]-initial),
                               evidence='ANNUAL_DIAGNOSTIC_NOT_INDEPENDENT_TEST'))
        if r.priority == '' and r.mechanic == 'FULL_BOOK_NORMALIZATION':
            nd = read_daily(native[base_key(r)])
            metadata = {e.event_id: dict(symbol=e.symbol, strategy=e.strategy) for e in events.itertuples(index=False)}
            result = drawdown_attribution(r._asdict(), d, nd, metadata, ('ATRDR', 'MCB', r.gap, 'SMV6'))
            expected = sum(result[s+'_pnl'] for s in ('ATRDR', 'MCB', r.gap, 'SMV6'))
            peak = d.loc[d.trade_date.le(pd.Timestamp(result['peak_date']))]
            peak_nav = peak.nav.iloc[-1] if len(peak) else r.initial_nav
            trough_nav = d.loc[d.trade_date.eq(pd.Timestamp(result['trough_date'])), 'nav'].iloc[0]
            if abs(expected-(trough_nav-peak_nav)) > 1e-5:
                raise ValueError('peak-trough attribution mismatch')
            drawdowns.append(dict(identity, **result))
    save('scaling_trade_attribution', route_rows)
    save('capital_scaling_segment_results', annual)
    dd = save('worst_drawdown_attribution', drawdowns)
    save('single_strategy_g100_drawdowns', dd.loc[dd.scope.eq('SINGLE') & dd.target.eq('G100')])


def role_comparisons(main):
    combined = main.loc[main.scope.eq('COMBINED')]
    drawdowns = pd.read_csv(OUT/'worst_drawdown_attribution.csv').fillna({'priority': ''})
    fields = ['CAGR', 'MaxDD', 'CVaR5', 'net_pnl', 'capital_days', 'average_gross_exposure', 'max_single_security_weight', 'max_family_weight', 'demand_share']
    keys = ['gap', 'period', 'target']
    roles = combined.loc[combined.mcb_mode.eq('independent')].merge(combined.loc[combined.mcb_mode.eq('confirmation_tag')], on=keys, suffixes=('_independent', '_confirmation'), validate='one_to_one')
    matched = pd.read_csv(PARENT/'output/mcb_exact_confirmation_matches.csv')
    role_rows = []
    for r in roles.to_dict('records'):
        row = {k: r[k] for k in keys}
        for f in fields:
            row[f+'_independent'] = r[f+'_independent']
            row[f+'_confirmation'] = r[f+'_confirmation']
            row['delta_'+f] = r[f+'_independent']-r[f+'_confirmation']
        for mode, suffix in (('independent', 'independent'), ('confirmation_tag', 'confirmation')):
            folder = Path(r['source_'+suffix])
            daily = pd.read_parquet(folder/'daily.parquet')
            states = json.loads((folder/'account.json').read_text())['initial_states']
            returns = daily.nav.pct_change()
            returns.iloc[0] = daily.nav.iloc[0]/r['initial_nav_'+suffix]-1
            worst = returns.idxmin()
            contribution = daily.MCB_nav.diff()
            contribution.iloc[0] = daily.MCB_nav.iloc[0]-states['MCB']['nav']
            before_nav = daily.nav.iloc[worst-1] if worst else r['initial_nav_'+suffix]
            row['worst_day_'+suffix] = str(pd.Timestamp(daily.trade_date.iloc[worst]).date())
            row['worst_day_account_return_'+suffix] = float(returns.iloc[worst])
            row['MCB_worst_day_pnl_'+suffix] = float(contribution.iloc[worst])
            row['MCB_worst_day_portfolio_return_contribution_'+suffix] = float(contribution.iloc[worst]/before_nav)
            dd = drawdowns.loc[drawdowns.scope.eq('COMBINED') & drawdowns.gap.eq(r['gap'])
                & drawdowns.period.eq(r['period']) & drawdowns.target.eq(r['target'])
                & drawdowns.mcb_mode.eq(mode) & drawdowns.grade.eq('EXECUTION_AWARE_SCALING')
                & drawdowns.mechanic.eq('FULL_BOOK_NORMALIZATION') & drawdowns.priority.eq('')]
            if len(dd) != 1:
                raise ValueError('MCB worst-drawdown identity coverage')
            row['MCB_own_worst_drawdown_pnl_'+suffix] = float(dd.MCB_pnl.iloc[0])
        events = pd.read_csv(Path(r['source_independent'])/'event_attribution.csv')
        hits = matched.loc[matched.gap.eq(r['gap']) & matched.period.eq(r['period']) & matched.policy.eq('P0')].drop_duplicates(['mcb_event_id', 'atrdr_event_id'])
        hits = hits.loc[hits.mcb_event_id.isin(events.event_id) & hits.atrdr_event_id.isin(events.event_id)]
        mcb = events.loc[events.strategy.eq('MCB')]
        row.update(exact_overlap_events=len(hits), mcb_only_events=int((~mcb.event_id.isin(hits.mcb_event_id)).sum()),
                   duplicate_capital_days=float(mcb.loc[mcb.event_id.isin(hits.mcb_event_id), 'capital_days'].sum()),
                   MCB_attributed_pnl=float(mcb.pnl.sum()), incremental_account_MCB_pnl=row['delta_net_pnl'],
                   duplicate_definition='MCB_CAPITAL_DAYS_IN_ACTUALLY_FUNDED_EXACT_PAIRED_EVENTS; NOT_A_SIMULTANEOUS_HOLDING_TIME_INTEGRAL', classification='MCB_ROLE_SCALING_SENSITIVE')
        role_rows.append(row)
    save('mcb_scaling_role_comparison', role_rows)
    keys = ['mcb_mode', 'period', 'target']
    gaps = combined.loc[combined.gap.eq('OGR')].merge(combined.loc[combined.gap.eq('IFCGR')], on=keys, suffixes=('_OGR', '_IFCGR'), validate='one_to_one')
    gap_rows = []
    filter_eligible = set(pd.concat([pd.read_parquet(PARENT/'cache/ifcgr'/period/'signals.parquet', columns=['gap_id'])
                                    for period in ('2018_2021', '2022_2023')]).gap_id)
    for r in gaps.to_dict('records'):
        row = {k: r[k] for k in keys}
        for f in fields:
            row[f+'_OGR'], row[f+'_IFCGR'] = r[f+'_OGR'], r[f+'_IFCGR']
            row['delta_IFCGR_minus_OGR_'+f] = r[f+'_IFCGR']-r[f+'_OGR']
        e = pd.read_csv(Path(r['source_OGR'])/'event_attribution.csv')
        f = pd.read_csv(Path(r['source_IFCGR'])/'event_attribution.csv')
        missing_fills = e.loc[e.strategy.eq('OGR') & ~e.event_id.isin(f.event_id)]
        removed = e.loc[e.strategy.eq('OGR') & ~e.event_id.isin(filter_eligible)]
        row.update(issuer_filter_excluded_funded_events=len(removed), excluded_events_OGR_pnl=float(removed.pnl.sum()),
                   OGR_funded_events_not_funded_by_IFCGR=len(missing_fills),
                   funding_or_state_difference_events=int(missing_fills.event_id.isin(filter_eligible).sum()),
                   issuer_filter_grade='PIT_B', classification='KEEP_BOTH_AS_ALTERNATIVE_SHADOWS')
        gap_rows.append(row)
    save('gap_scaling_comparison', gap_rows)


def capacity(table):
    columns = IDS+['initial_nav', 'max_position_notional', 'max_position_notional_over_NAV', 'max_single_order_notional',
                  'max_physical_fill_notional', 'order_aggregation_basis', 'max_order_notional_over_completed_timestamp_NAV',
                  'max_order_over_initial_NAV', 'max_daily_traded_notional', 'max_same_symbol_daily_traded_notional',
                  'max_same_symbol_checkpoint_traded_notional', 'capacity_limited_order_count',
                  'capacity_limited_requested_notional', 'capacity_status']
    frame = table[columns].copy()
    frame['volume_participation_status'] = 'SMV6_LOCAL_PER_ORDER_CAP_ONLY; STOCK_CAPACITY_NOT_MODELED'
    frame['account_size_extrapolation'] = 'NOT_ESTIMABLE'
    save('capacity_diagnostics', frame)
    text = '''# 容量与执行假设

股票沿用父版本 raw 分数股研究账户、双边各 20bp 成本、登记停复牌和价格限制。本研究没有加入股票成交量冲击或市场容量函数，因此 `CAPACITY_NOT_MODELED`；不运行任意 1x/5x/10x 资金规模，也不能据 G100 宣称任意金额可成交。

SMV6 两种执行等级都保留冻结本地模型的 100 股手、2bp 佣金、单边 8bp 滑点、分钟量 50% 上限及原生时钟。现有源代码的上限是每次原生下单调用，不是一个已验证的原生平台同证券同 bar 聚合上限。本地模型与 SuperMind 原生等价性仍未验证，不能发明聚合规则。这一限制在理想边界中也没有被删除，因此两个等级可能完全一致。

额外股票调整使用登记的开盘报价；日内完成的退出观察之后，最早在随后有数据的分钟开盘调整。15:00 完成的目标触发等待下次合法开盘。缺失报价、停牌、涨跌停、当天买入和待到账股数会造成目标未达到。等待中的订单保留固定股数，不按每日价格漂移重新定仓。ETF CAP50_SET 的整数/成交量余量不会触发每日权重恢复。

订单名义额/NAV 使用订单所在完成时点的净 NAV；它与持仓权重不同。卖出费用、同一时点内的价格变化或多个原生调用，可以使成交名义额大于完成后的净 NAV，而不代表账户融资。最大物理 gross 和最低现金另由全部账户检查点验证。

capital-days 是实际市值对日历时间的积分，包含非交易日和有经济权利的 pending 股数；不是平均 gross 乘交易天数。最大证券金额、证券/NAV、策略与家族集中度使用全部已记录的完成时点，日末最大值另外保留；未观察到的时点不作推断。超过集中度阈值的天数仍为日末计数。最大原生订单金额按事件、证券、方向、时点及原因归并，避免虚拟附加手数拆分低估；它不是交易所订单 ID。物理成交分笔最大额、同证券同检查点与日合计也都保留，不能冒充完整的订单簿市场冲击模型。
'''
    (HERE/'reports/capacity_assumptions.md').write_text(text)


def run():
    table = pd.read_csv(OUT/'scenario_summary.csv').fillna({'priority': ''})
    if len(table) != 132 or table[IDS].duplicated().any() or not table.validation.eq('PASS').all():
        raise ValueError('complete unique validated scenario grid required')
    main = table.loc[table.grade.eq('EXECUTION_AWARE_SCALING') & table.mechanic.eq('FULL_BOOK_NORMALIZATION') & table.priority.eq('')].copy()
    if len(main) != 90:
        raise ValueError('five-target native/frontier coverage')
    main['target_order'] = main.target.map({t: i for i, t in enumerate(ORDER)})
    main = main.sort_values(BASE_KEYS+['target_order'])
    native, inc = comparisons(table, main)
    inc_fields = BASE_KEYS+['target', 'grade', 'mechanic', 'priority']
    main = main.merge(inc, on=inc_fields, validate='one_to_one')
    save('single_strategy_scaling_frontier', main.loc[main.scope.eq('SINGLE')])
    save('capital_scaling_frontier', main.loc[main.scope.eq('COMBINED')])
    extreme = table.loc[table.target.eq('G100') & table.mechanic.eq('FULL_BOOK_NORMALIZATION') & table.priority.eq('')]
    save('single_strategy_g100_results', extreme.loc[extreme.scope.eq('SINGLE')])
    save('combined_g100_results', extreme.loc[extreme.scope.eq('COMBINED')])
    save('target_attainment_diagnostics', table[IDS+['target_gross', 'average_gross_exposure', 'median_exposure',
        'p90_exposure', 'p95_exposure', 'max_exposure', 'observed_checkpoint_max_gross',
        'share_checkpoints_90pct_target', 'share_days_90pct_target', 'zero_actual_exposure_days',
        'pending_adjustments_at_end', 'normalization_weight_error_max', 'normalization_weight_error_p95',
        'normalization_weight_error_median', 'normalization_max_gross_overshoot', 'observed_completed_timestamp_MaxDD']])
    cols = IDS+['max_single_security_weight', 'observed_checkpoint_max_security_weight', 'max_strategy_exposure', 'max_family_weight',
                'daily_close_max_security_weight', 'daily_close_max_family_weight', 'daily_close_max_strategy_weight', 'concentration_observation_basis',
                'top_5_symbols_pnl', 'top_5_event_dates_pnl']+[c for c in table if c.startswith(('security_days_', 'security_fraction_', 'demand_days_', 'demand_fraction_'))]
    conc = save('concentration_diagnostics', main[cols])
    save('single_strategy_g100_concentration', conc.loc[conc.scope.eq('SINGLE') & conc.target.eq('G100')])
    frag_cols = IDS+['CAGR', 'MaxDD', 'net_pnl', 'top_5_symbols_pnl', 'top_5_events_pnl', 'top_5_symbols_pnl_fraction', 'top_5_events_pnl_fraction', 'fragility_grade']+[c for c in table if c.startswith(('best_', 'CAGR_excluding', 'MaxDD_excluding'))]
    save('return_concentration_diagnostics', main[frag_cols])
    attribute(table, main, native)
    role_comparisons(main)
    capacity(table)
    from .habitat import run as habitat
    habitat(main)
    from .report import run as report
    report(table, main)


if __name__ == '__main__':
    run()
