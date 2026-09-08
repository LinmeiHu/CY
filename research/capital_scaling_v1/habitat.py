"""Post-hoc habitat descriptions, invoked only after the complete capital grid."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.shared_capital_v1.smv6_baseline import load_bounded
from .preflight import HERE, PARENT


def run(main):
    from .run import case_key, scenarios
    if len(main) != 90:
        raise ValueError('structural idle follows the full scaling grid')
    table = pd.read_csv(HERE/'output/scenario_summary.csv').fillna({'priority': ''})
    native, scaled = scenarios()
    if (len(table) != 132 or not table.validation.eq('PASS').all()
        or {case_key(r) for r in table.to_dict('records')} != {case_key(c) for c in native+scaled}):
        raise ValueError('structural idle requires all 132 registered validated cases')
    inputs = {k: Path(v) for k, v in json.loads((PARENT.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    daily, _, _ = load_bounded(inputs)
    anchor = daily['000852.SH']
    close = anchor.pre_adj_close
    forward = pd.DataFrame(index=close.index)
    for n in (5, 20):
        forward[f'index_forward_{n}d'] = close.shift(-n)/close-1
        cross = pd.DataFrame({s: frame.pre_adj_close.shift(-n)/frame.pre_adj_close-1 for s, frame in daily.items() if s != '000852.SH'})
        forward[f'etf_cross_median_forward_{n}d'] = cross.median(axis=1)
        forward[f'etf_cross_positive_share_{n}d'] = cross.gt(0).sum(axis=1)/cross.notna().sum(axis=1).replace(0, np.nan)
        forward[f'etf_cross_available_{n}d'] = cross.notna().sum(axis=1)
    state = pd.read_parquet(PARENT/'cache/atrdr/market.parquet').set_index('trade_date').sort_index()
    fields = ['market_regime', 'market_median_ret20', 'market_median_ret60', 'market_positive_ret20_share', 'market_positive_ret60_share', 'latest_source_timestamp']
    observable = state[fields].shift(1)
    observable['index_realized_vol20_prior'] = close.pct_change(fill_method=None).rolling(20).std().shift(1)*np.sqrt(252)
    observable['index_amount_prior'] = anchor.amount_cny.shift(1)
    demands = pd.read_csv(PARENT/'output/daily_capital_demand.csv')
    rows = []
    counts = []
    for r in main.loc[main.scope.eq('COMBINED') & main.target.eq('NATIVE')].itertuples(index=False):
        account = pd.read_parquet(Path(r.source)/'daily.parquet').set_index('trade_date')
        own = demands.loc[demands.gap.eq(r.gap) & demands.period.eq(r.period) & demands.mcb_mode.eq(r.mcb_mode) & demands.policy.eq('P0')]
        rejected = set(pd.to_datetime(own.loc[own.funded_notional.eq(0), 'timestamp']).dt.normalize())
        # Exact parent day definition; substantial cash is measured and reported,
        # not selected using a newly optimized cut point.
        idle = account.loc[(account.cash > 0) & ~account.index.isin(rejected)].copy()
        idle = idle.join(observable, how='left').join(forward, how='left')
        if idle.market_regime.isna().any() or (pd.to_datetime(idle.latest_source_timestamp) >= idle.index).any():
            raise ValueError('habitat state unavailable at decision time')
        idle['breadth_bucket'] = np.where(idle.market_positive_ret20_share >= .5, 'MAJORITY_POSITIVE_20D', 'MINORITY_POSITIVE_20D')
        idle['gross'] = idle.gross_exposure/idle.nav
        idle['cash_ratio'] = idle.cash/idle.nav
        counts.append(dict(gap=r.gap, mcb_mode=r.mcb_mode, period=r.period, structural_idle_days=len(idle), all_days=len(account),
                           fraction_of_all_days=len(idle)/len(account), min_idle_cash_ratio=float(idle.cash_ratio.min()),
                           median_idle_cash_ratio=float(idle.cash_ratio.median())))
        for (regime, breadth), group in idle.groupby(['market_regime', 'breadth_bucket']):
            row = dict(gap=r.gap, mcb_mode=r.mcb_mode, period=r.period, habitat=f'{regime}|{breadth}',
                       days=len(group), fraction_of_structural_idle_days=len(group)/len(idle),
                       average_account_gross=float(group.gross.mean()), average_cash_ratio=float(group.cash_ratio.mean()),
                       market_median_ret20_prior=float(group.market_median_ret20.mean()),
                       market_median_ret60_prior=float(group.market_median_ret60.mean()),
                       breadth20_prior=float(group.market_positive_ret20_share.mean()),
                       realized_vol20_prior=float(group.index_realized_vol20_prior.mean()),
                       index_amount_prior=float(group.index_amount_prior.mean()),
                       classification='POST-HOC HABITAT DIAGNOSTIC')
            row['active_strategy_day_fractions'] = json.dumps({s: float((group[s+'_exposure'] > 1e-8).mean()) for s in ('ATRDR', 'MCB', r.gap, 'SMV6')}, sort_keys=True)
            for c in forward:
                row[c+'_mean'] = float(group[c].mean())
                row[c+'_observations'] = int(group[c].notna().sum())
            for n in (5, 20):
                series = group[f'index_forward_{n}d'].dropna()
                row[f'index_forward_{n}d_positive_fraction'] = float(series.gt(0).mean())
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame.to_csv(HERE/'output/structural_idle_habitat.csv', index=False)
    pd.DataFrame(counts).to_csv(HERE/'output/structural_idle_day_coverage.csv', index=False)
    reference = frame.loc[frame.gap.eq('OGR') & frame.mcb_mode.eq('independent')].sort_values('days', ascending=False)
    habitats = reference.habitat.drop_duplicates().tolist()
    hypotheses = [
        dict(hypothesis='分散的缓慢趋势承接', economic_story='持续的市场或行业趋势可能没有触发冻结的 Demand、Gap 或 ETF 精确入场形态。',
             uncovered_habitat='BULL 与正收益广度占多数的结构闲置日', why_missed='当前五套规则要求特定事件和资格；市场方向可投资不等于已有原生入场事件。',
             security_type='已登记的宽基/行业ETF，或 MAIN+CHINEXT 股票', data_available='既有 PIT 日线、行业状态、固定 ETF 历史行情', holding_horizon='数周到数月，待经济假设验证',
             diversification='补充事件缺席时的持有窗口；必须检验与 Demand 家族的市场方向重合。', overfitting_risk='把事后牛市漂移误判为新 alpha，或重复已有 Bull beta。',
             minimum_first_experiment='只比较已登记状态下的宽基、等权和行业描述性收益及与现有事件重合，不选阈值、不定仓。'),
        dict(hypothesis='系统下跌后的分散修复', economic_story='广泛下跌后，市场可能出现集体修复，而个股未出现当前冻结母形态或真实 Gap。',
             uncovered_habitat='BEAR 与正收益广度占少数、随后出现修复的结构闲置日', why_missed='现有 Bear/Gap 需要特定个股路径，不能代表所有横截面修复。',
             security_type='已登记宽基ETF或分散股票篮子', data_available='PIT 日线、广度、行业状态、已有 ETF 行情', holding_horizon='数日到数周，待假设验证',
             diversification='覆盖缺少个股触发事件的系统性修复；需区分与现有 Bear 暴露的增量。', overfitting_risk='依据后验反弹挑日期，隐藏持续下跌中的尾部损失。',
             minimum_first_experiment='预先分开持续下跌与修复的描述性事件样本，比较现有家族是否缺席及最差路径，不建立交易规则。'),
        dict(hypothesis='低市场参与度中的相对强弱分化', economic_story='宽基表现平淡时，已登记行业/ETF 横截面仍可能存在方向分化。',
             uncovered_habitat='低广度或混合市场状态中的结构闲置日', why_missed='当前 MCB 要求跨板确认；其他家族不以持续的行业横截面分化为独立交易来源。',
             security_type='已有行业ETF和 MAIN+CHINEXT 行业篮子', data_available='既有行业状态、ETF 日线、PIT 股票行情', holding_horizon='数周，待经济假设验证',
             diversification='研究横截面而非共同市场方向；持仓重合和 Demand 相关性必须先核对。', overfitting_risk='用未来最强行业建立事后轮动规则，忽略切换成本和数据覆盖变化。',
             minimum_first_experiment='描述现有可观测行业状态与后续横截面分布，先做按时间固定的成本和重合审查，不训练排名器。'),
    ]
    for h in hypotheses:
        h['status'] = 'RESEARCH_HYPOTHESIS_ONLY_NOT_IMPLEMENTED'
        h['observed_habitat_inventory'] = '|'.join(habitats)
    pd.DataFrame(hypotheses).to_csv(HERE/'output/next_alpha_hypotheses.csv', index=False)
    from .report import markdown
    lines = ['# Structural Idle Habitat', '', 'POST-HOC HABITAT DIAGNOSTIC。只在资本缩放完整运行后计算，不构成实时过滤器，也未实现第六套策略。', '',
             '沿用父 P0 的“该日没有未资助合法请求”定义，保留正现金；同时报告实际现金比例，避免把定义中的结构闲置误说成可共享资金。市场状态在当日开盘前取前一完成日的登记值。自然的广度多数/少数（50%）仅作描述分组。', '',
             '指数和既有固定 ETF 横截面前瞻 5/20 个观测交易日收益只作后验描述；末端不足窗口保持缺失，未读取 2023 年后的结果。横截面统计并不证明当时每个 ETF 都符合某个新增策略，也不等同于可实现 alpha。', '',
             markdown(reference[['period', 'habitat', 'days', 'fraction_of_structural_idle_days', 'average_account_gross', 'index_forward_5d_mean', 'index_forward_20d_mean']]), '',
             '有正的后续市场收益，至多说明当前五套事件未覆盖全部可投资市场路径；不能单凭这一点认定新策略有超额收益。负均值或高尾部风险也不能证明这些时段全部无机会。上述三个假设只列经济故事与最小首轮实验，没有选阈值、训练模型或回测第六策略。', '']
    (HERE/'reports/structural_idle_habitat.md').write_text('\n'.join(lines))
