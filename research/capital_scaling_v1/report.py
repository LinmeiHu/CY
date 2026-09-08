"""Chinese research report generated from the complete discrete result grid."""
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd

from five_strategy_bundle.io import sha256, write_json
from .preflight import HERE

OUT = HERE/'output'


def markdown(frame, percent=()):
    columns = list(frame)
    lines = ['| '+' | '.join(columns)+' |', '| '+' | '.join('---' for _ in columns)+' |']
    for values in frame.itertuples(index=False, name=None):
        cells = []
        for c, value in zip(columns, values):
            if value is None or (isinstance(value, (float, np.floating)) and np.isnan(value)):
                text = 'NA'
            elif isinstance(value, (float, np.floating)):
                text = f'{100*value:.2f}%' if c in percent else f'{value:.4g}'
            else:
                text = str(value)
            cells.append(text.replace('|', '/').replace('\n', ' '))
        lines.append('| '+' | '.join(cells)+' |')
    return '\n'.join(lines)


def decisions(main):
    rows = []
    for (gap, mode), group in main.loc[main.scope.eq('COMBINED')].groupby(['gap', 'mcb_mode']):
        native = group.loc[group.target.eq('NATIVE')].set_index('period')
        for target, frame in group.groupby('target'):
            both = frame.set_index('period')
            gain = both.CAGR-native.CAGR
            label = 'EVIDENCE_INSUFFICIENT'
            if target != 'NATIVE' and (gain > 0).all() and both.MaxDD.max() <= .15:
                label = 'GROSS_TARGET_SHADOW_CANDIDATE'
            elif target == 'G100':
                label = 'G100_ONLY_AS_EXTREME_BOUND'
            elif target != 'NATIVE' and both.MaxDD.max() > .15:
                label = 'RISK_LIMITED'
            elif target != 'NATIVE' and (gain <= 0).all():
                label = 'NATIVE_SIZING_REMAINS_PREFERRED'
            rows.append(dict(gap=gap, mcb_mode=mode, target=target, minimum_cross_period_CAGR_delta=float(gain.min()),
                              maximum_cross_period_MaxDD=float(both.MaxDD.max()),
                              maximum_security_weight=float(both.max_single_security_weight.max()),
                              historical_interpretation=label, capacity='CAPACITY_NOT_MODELED', production_authorized=False))
    matrix = pd.DataFrame(rows)
    matrix.to_csv(OUT/'final_scaling_decision_matrix.csv', index=False)
    return matrix


def plots():
    candidates = list(dict.fromkeys(x for x in (sys.executable, shutil.which('python'), shutil.which('python3')) if x))
    for python in candidates:
        result = subprocess.run([python, '-c', 'import matplotlib,pandas'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            subprocess.run([python, str(HERE/'plot.py'), str(HERE)], check=True)
            return
    raise RuntimeError('standalone frontier plot requires an installed matplotlib runtime')


def run(table, main):
    matrix = decisions(main)
    priority = pd.read_csv(OUT/'priority_scaling_diagnostics.csv')
    grouped_priority = priority.assign(priority_family=priority.priority.replace({'OGR': 'GAP_ALTERNATIVE', 'IFCGR': 'GAP_ALTERNATIVE'}),
                                       defined=priority.capital_day_denominator_status.eq('DEFINED'))
    ranks = grouped_priority.groupby('priority_family').agg(worst_incremental_efficiency=('incremental_pnl_per_capital_day', 'min'),
                                          total_incremental_pnl=('incremental_net_pnl', 'sum'),
                                          worst_incremental_MaxDD=('incremental_MaxDD', 'max'), slices=('priority', 'size'),
                                          defined_capital_day_slices=('defined', 'sum'))
    if len(ranks) != 4 or not ranks.slices.eq(4).all():
        raise ValueError('priority-family comparison requires four balanced Gap/period slices')
    ranks['efficiency_comparison_status'] = np.where(ranks.defined_capital_day_slices.eq(4), 'DEFINED', 'NOT_ESTIMABLE')
    ranks.to_csv(OUT/'priority_family_comparison.csv')
    known = ranks.loc[ranks.defined_capital_day_slices.eq(4)]
    best = known.worst_incremental_efficiency.idxmax() if len(known) else 'EVIDENCE_INSUFFICIENT'
    worst = ranks.worst_incremental_MaxDD.idxmax() if len(ranks) else 'EVIDENCE_INSUFFICIENT'
    headroom = matrix.target.isin(['G25', 'G50', 'G75']) & matrix.historical_interpretation.eq('GROSS_TARGET_SHADOW_CANDIDATE')
    final = 'CAPITAL_SCALING_HAS_HEADROOM' if headroom.any() else 'NATIVE_SIZING_REMAINS_PREFERRED'
    next_priority = 'G25 整本资本缩放的影子执行与容量证伪' if headroom.any() else '针对结构闲置主栖息地的新 alpha 家族证伪研究'
    reference = main.loc[main.scope.eq('COMBINED') & main.gap.eq('OGR') & main.mcb_mode.eq('independent')]
    g100 = reference.loc[reference.target.eq('G100')]
    bands = pd.read_csv(OUT/'risk_budget_reference.csv')
    mechanics = pd.read_csv(OUT/'g100_scaling_mechanics_sensitivity.csv')
    ideal = pd.read_csv(OUT/'idealized_vs_execution_aware.csv')
    habitat = pd.read_csv(OUT/'structural_idle_habitat.csv')
    dd = pd.read_csv(OUT/'worst_drawdown_attribution.csv')
    marginal = pd.read_csv(OUT/'marginal_frontier.csv')
    marginal = marginal.loc[marginal.scope.eq('COMBINED') & marginal.gap.eq('OGR') & marginal.mcb_mode.eq('independent')]
    steps = marginal.set_index(['period', 'to_target'])
    selection = dict(final_scaling_interpretation=final, next_research_priority=next_priority,
                     best_incremental_capital_user=best, worst_incremental_drawdown_source=worst,
                     mcb_role='MCB_ROLE_SCALING_SENSITIVE', gap_scaling_result='KEEP_BOTH_AS_ALTERNATIVE_SHADOWS',
                     capacity_status='CAPACITY_NOT_MODELED', production_authorized=False,
                     mechanics_status='SCALING_MECHANICS_SENSITIVE' if mechanics.interpretation.eq('SCALING_MECHANICS_SENSITIVE').any() else 'EVIDENCE_INSUFFICIENT')
    write_json(OUT/'decision.json', selection)
    rates = ['CAGR', 'MaxDD', 'CVaR5', 'average_gross_exposure', 'p95_exposure', 'max_single_security_weight', 'max_family_weight']
    lines = ['# 五策略资本、风险与代码最终研究 V1', '',
             f'计算完成：132/132 个规定切片，包含 18 Native、36 G100 双等级极限、54 中间档位、8 入场式 G100 和 16 单资金袖优先诊断。最终判断：**{final}**。唯一优先研究程序：**{next_priority}**。任何较强档位仅为影子研究候选，不授权生产缩放。', '',
             '全部 Native、G25、G50、G75、G100 都来自合法时序物理账户。没有新 alpha、止损、板块、股票池、绩效权重、杠杆或回撤门控；OGR 与 IFCGR 始终互斥。2018–2021 和 2022–2023 是两个历史段；2018–2023 年度表是诊断分解，不是六次独立验证。', '',
             '## 代码与基准（问题 1–5）', '',
             '新确认并修复了一处可影响资金实际使用的 P0 调度缺陷：同一原生回调中的合法卖出释放现金后，后续买单仍使用旧的已消耗预算。最小用例由只买到 200 股修正为可买 800 股，仍然不融资。SMV6 单独账户随后与封存父基准对齐。父基准账户数字未被强行覆盖；18 个 Native 切片均按现金、NAV、gross 和必要原生请求层对账。', '',
             '其他修复为 SMV6 上一交易/事件日元数据（含首次回调的历史数据）、空结果表列、缺失时间戳拒绝和按配置文件目录解析及按所选策略校验输入。冻结 alpha 源码不变；元数据修复不改变原生事件时钟。此前 ATRDR 完成状态前视和 SMV6 开盘未来收盘估值修复保留并重新测试。具体证据见 bug_hardening_report。', '',
             '实际极限运行还发现并修复了 ETF 恰好足额一手被浮点取整漏买，以及大额股票订单请求与实际含费账单运算顺序不一致的问题；后者曾使现金充足的 603348.SH 订单被错误拒绝。修补没有放宽容差或裁剪负现金，当前 132 场景全部由统一后的生产者生成。', '',
             '股票池：ATRDR/MCB/OGR 为精确父 MAIN+CHINEXT；ATRDR 路线资格和 MCB 同一完成收盘跨板确认保留；IFCGR 严格继承 OGR 后过滤、维持 PIT-B；SMV6 为冻结 152 ETF 与原生每日资格。没有新增 STAR、北京、ETF、ST 或上市年龄规则。SMV6 原生 SuperMind 等价性仍未验证，股票市场容量未建模。', '',
             '## 缩放定义与实际暴露', '',
             '原生 P0 预资金请求提供同一经济事件的原生目标金额，作为独立定仓参照；活跃持仓集合、现金、库存、公司行动与原生退出由实际缩放账户推进。每个合法集合变化点统一归一化整本有效目标。不是将旧 NAV 或已完成交易收益乘倍数。每段沿用父已验证实际初始股数和 NAV；不在段初人为平仓或把继承持仓追溯放大。', '',
             'G25/G50/G75 是调仓目标，价格漂移不会触发每日恢复；因此持有期间实际 gross 可以偏离对应目标。不能同时宣称“绝不因价格再平衡”和“每天恒等固定 gross”。100% 无融资约束始终对真实账户执行。缺失合法报价、当天买入及 pending 股数不能拿来假装完成减仓；目标达成率和末端未完成调整均保留。', '',
             '下文 MaxDD、CVaR5、Sharpe 和仓位分位数沿用日末账户口径；最大证券/家族权重则取全部已记录完成时点。target_attainment_diagnostics.csv 另列完成时点最大回撤、实际仓位、权重偏差及目标未达成情况。资本日是元乘日历日，不是交易日计数。', '',
             '## 单策略前沿与 G100（问题 6–11）', '']
    columns = ['period', 'target', 'CAGR', 'MaxDD', 'CVaR5', 'Sharpe', 'average_gross_exposure', 'capital_days', 'max_single_security_weight']
    single_notes = {
        'ATRDR': 'G100 的日末 MaxDD 为 35.28% / 17.08%，属于 RISK_LIMITED。G25 在较早段收益低于 Native 而回撤更高，说明整本定仓会改变资本分配路径，前沿不保证单调优于原生。',
        'MCB': 'G100 的日末 MaxDD 为 15.65% / 13.36%；G75 为 11.87% / 10.13%。它在组合的单资金袖优先诊断中具有最高的跨段最弱资本日效率，但这个事实不授权把独立 MCB 无条件推到 G100。',
        'OGR': 'G100 在较早段 CAGR 为 36.47%、MaxDD 为 17.60%；较晚段只有约 11.06% CAGR 而 MaxDD 达 26.16%，且前五事件净利润占比超过 100%。属于 CONCENTRATION_LIMITED 与 RISK_LIMITED。',
        'IFCGR': 'G100 在较早段 CAGR 为 30.82%、MaxDD 为 18.10%；较晚段风险几乎与 OGR 相同。发行人过滤没有消除满仓 Gap 的尾部损失，PIT-B 身份保持。',
        'SMV6': 'G100 平均 gross 仅 17.26% / 13.99%，CAGR 为 7.13% / 4.63%；较晚段低于 Native 的 5.07%。原生触发窗口与本地成交限制使提高目标难以转化成持续的实际暴露，不能据目标为 100% 就称其为全年满仓 ETF 策略。',
    }
    for strategy in ('ATRDR', 'MCB', 'OGR', 'IFCGR', 'SMV6'):
        lines += [f'### {strategy}', '', markdown(main.loc[main.scope.eq('SINGLE') & main.strategy.eq(strategy), columns], rates), '', single_notes[strategy], '']
    lines += ['单策略 G100 允许唯一有效证券接近全账户，不添加单名上限。上表同时展示由此承担的历史风险。完整最差月/季/21日/63日、最长回撤、恢复时间、换手、费用、头部/尾部事件均在 single_strategy_scaling_frontier.csv；G100 两个执行等级和峰谷归因另有专表。', '',
              '![单策略收益回撤前沿](reports/single_strategy_frontiers.png)', '', '## 组合前沿（问题 12–16）', '']
    columns = ['gap', 'mcb_mode', 'period', 'target', 'CAGR', 'MaxDD', 'CVaR5', 'Sharpe', 'average_gross_exposure', 'p95_exposure', 'capital_days', 'max_single_security_weight', 'max_family_weight']
    lines += [markdown(main.loc[main.scope.eq('COMBINED'), columns], rates), '', '![四种组合收益回撤前沿](reports/combined_frontiers.png)', '',
              '两段同时满足日末最大回撤上限的最高已测档位如下，另列全部已记录完成时点的参考，避免日内风险被日末统计隐藏。不插值、不增加新档位，也不将历史最大回撤当作未来保证。', '', markdown(bands, ['risk_band']), '',
              '## 额外资金、MCB 与 Gap（问题 17–20）', '',
              f'按四个 Gap/历史段切片中最弱的已定义增量 P&L/资本日作保守描述，额外资本使用者为 {best}；新增最大回撤最重者为 {worst}。这是结果排序，不是新的跨策略绩效配置权重。完整每段增量 CAGR、P&L、MaxDD、CVaR、资本日和分母状态如下。', '',
              markdown(priority[['gap', 'period', 'priority', 'incremental_CAGR', 'incremental_MaxDD', 'incremental_CVaR5', 'incremental_net_pnl', 'incremental_capital_days', 'incremental_pnl_per_capital_day', 'capital_day_denominator_status']]), '',
              'MCB 独立与确认标签的资本角色为 MCB_ROLE_SCALING_SENSITIVE；不因历史重合就自动删除独立资金。mcb_scaling_role_comparison.csv 对照精确重合、MCB-only、重复信号占用的资本日、归因收益、Demand 集中度、最差日和整体 MaxDD 变化。这里的重复资本日定义为实际成交精确配对事件中的 MCB 资本日；T+1 附加批次可能使两者的最终退出时点不同，故不将该数称为双资金袖逐时同时持仓的重叠积分。Gap 保留 KEEP_BOTH_AS_ALTERNATIVE_SHADOWS；gap_scaling_comparison.csv 将发行人过滤排除与资金/状态导致的未成交分别列明，IFCGR 的 PIT-B 等级没有提升。', '',
              '## G100 脆弱性与最深回撤（问题 21–24）', '',
              markdown(g100[['period', 'CAGR', 'MaxDD', 'max_single_security_weight', 'max_family_weight', 'best_1_day_pnl', 'best_5_day_pnl', 'CAGR_excluding_best_1_days', 'CAGR_excluding_best_5_days', 'top_5_symbols_pnl_fraction', 'top_5_events_pnl_fraction']]), '',
              '固定展示 OGR + MCB 独立切片，所有其他结构和单策略结果均保留在专表。移除最佳日只用于描述依赖程度，既不可执行，也没有据此添加过滤器。最高正收益事件、负收益事件、证券和事件日期均保留原始身份。', '',
              '较晚一段的 G100 对少数盈利日依赖更强：OGR 独立组合去掉最佳五日后的描述性 CAGR 约 11.64%，原值约 34.03%；前五个事件占净利润约 60.6%。这不能被两段总收益都为正掩盖。', '',
              markdown(dd.loc[dd.scope.eq('COMBINED') & dd.gap.eq('OGR') & dd.mcb_mode.eq('independent') & dd.target.eq('G100') & dd.grade.eq('EXECUTION_AWARE_SCALING'), ['period', 'peak_date', 'trough_date', 'recovery_date', 'ATRDR_pnl', 'MCB_pnl', 'OGR_pnl', 'SMV6_pnl', 'top_losing_securities', 'total_gross', 'cash']]), '',
              '每个目标的峰谷损失均由策略与证券贡献对账；native-equivalent 是相同峰谷窗口内 Native 账户贡献，incremental-scaled 是两者差值。调仓成本、资金竞争及真实持仓延迟也会进入增量，不能把全部损失机械地称作旧损失乘倍数。', '',
              'OGR 独立组合最深回撤的损失主要来自 ATRDR：2018-04-02 至 2018-10-17 约亏 150.73 万元，2022-04-06 至 2022-04-26 约亏 103.95 万元；后者另有 Gap 约亏 13.42 万元。该证据指向现有 Demand 尾部风险随资本放大，不能用没有融资替代风险判断。', '',
              markdown(mechanics[['gap', 'mcb_mode', 'period', 'CAGR_full_book', 'CAGR_entry_only', 'MaxDD_full_book', 'MaxDD_entry_only', 'delta_turnover', 'delta_max_single_security_weight', 'delta_average_gross_exposure', 'delta_capital_days', 'interpretation']]), '',
              '## 执行与容量（问题 25–27）', '',
              f'两种 G100 执行等级的最大 CAGR 差为 {ideal.delta_CAGR.abs().max():.12g}，最大 MaxDD 差为 {ideal.delta_MaxDD.abs().max():.12g}。两者都必须保留已验证的 SMV6 本地手数、成本和分钟量规则；股票没有额外容量模型，因此差值可以为零。差值为零不能证明不存在执行或规模限制。', '',
              'CAPACITY_NOT_MODELED。实际最大证券金额、成交分笔、日成交金额及同证券合计已计算；未从股票分数股研究账户推断任意规模都能交易。见 capacity_assumptions.md 与 capacity_diagnostics.csv。', '',
              '当前原始前沿主要受历史风险与集中度限制；两种执行等级没有差值，不能据此识别尚未建模的真实执行损耗。SMV6 单独 G100 仍有大量零实际暴露日（694/973、383/484），且原生调仓检查点达到至少 90% gross 的比例仅约 40.2% / 25.6%；本地分钟容量分别触发 113 / 42 次。因此其低平均仓位同时反映原生窗口稀少和已有本地执行限制。', '',
              '## 资本利用与边际补偿（问题 28–30）', '',
              'Native 组合约 14% 平均 gross 只描述已有账户。是否存在定仓空间，要同时看下列离散边际变化、跨段回撤预算和集中度，不能仅由剩余现金比例判断。缩放与父共享广度研究使用不同干预：前者改变现有目标尺寸，后者主要资助原先未获资金的原生请求。', '',
              '本次在 G25 看到有限的历史定仓空间：OGR 独立组合实际平均仓位约 20.76% / 21.07%，CAGR 约 12.92% / 8.43%，高于 Native 的 8.84% / 4.95%；代价是日末 MaxDD 从 4.19% / 3.05% 升至 7.77% / 4.40%。G50 的较早段已超过 15%，所以不把收益继续上升等同于可接受风险。相较父共享广度的 KEEP_FIXED_SLEEVES，有限缩放显示了更明确的收益增量；这仍不足以授权生产或认定 Native 定仓错误。', '',
              markdown(marginal[['period', 'from_target', 'to_target', 'delta_CAGR', 'delta_MaxDD', 'delta_CVaR5', 'delta_average_gross_exposure', 'delta_capital_days', 'delta_net_pnl', 'incremental_pnl_per_added_capital_day', 'incremental_CAGR_per_incremental_MaxDD', 'drawdown_denominator_status']]), '',
              f'边际补偿没有跨期一致的拐点：2022–2023 从 Native→G25 到 G25→G50，增量 P&L/资本日由 {steps.loc[("2022_2023", "G25"), "incremental_pnl_per_added_capital_day"]:.6f} 降至 {steps.loc[("2022_2023", "G50"), "incremental_pnl_per_added_capital_day"]:.6f}，新增 CAGR/新增 MaxDD 由 {steps.loc[("2022_2023", "G25"), "incremental_CAGR_per_incremental_MaxDD"]:.3f} 降至 {steps.loc[("2022_2023", "G50"), "incremental_CAGR_per_incremental_MaxDD"]:.3f}。2018–2021 则在 G75→G100 才同时低于前一步；对应增量 P&L/资本日为 {steps.loc[("2018_2021", "G100"), "incremental_pnl_per_added_capital_day"]:.6f}，此前为 {steps.loc[("2018_2021", "G75"), "incremental_pnl_per_added_capital_day"]:.6f}。因此拒绝高档位首先来自绝对回撤预算，不是声称每一步的风险补偿都下降。非正分母保留明确状态，没有拟合连续最优点。', '',
              '## 结构闲置与下一研究（问题 31–35）', '',
              markdown(habitat.loc[habitat.gap.eq('OGR') & habitat.mcb_mode.eq('independent'), ['period', 'habitat', 'days', 'fraction_of_structural_idle_days', 'average_account_gross', 'index_forward_5d_mean', 'index_forward_20d_mean']]), '',
              'POST-HOC HABITAT DIAGNOSTIC：状态取前一完成日，后续指数/ETF 分布只描述市场路径。它能区分当前规则没有触发与市场完全没有机会，却不能直接证明新的可交易超额收益。详见 structural_idle_habitat.md 和最多三个 next_alpha_hypotheses；本任务没有实现或回测这些假设。', '',
              '主栖息地为 BEAR + 低广度，占 OGR 独立组合结构闲置日的 44.0% / 40.0%，平均现金约 92.9% / 93.6%。其指数后续 20 日均值约 +0.72% / +0.04%，但既有 ETF 横截面中位数均值约 +0.84% / -1.03%；较晚一段 BULL + 高广度的指数后续 20 日均值反而约 -3.85%。因此既不能判定闲置全部无机会，也没有证据支持普遍、稳定、可直接填入资金的新增 alpha。下一美元研究优先验证 G25 缩放机制与成交约束，新家族暂保留证伪路线图。', '',
              f'最终缩放解释：{final}。下一美元研究预算的唯一优先方向：{next_priority}。这一步先检验资本缩放的经济结论是否能在真实支持的订单与容量语义中成立；G100 保留极限诊断身份，不等于生产配资批准。', '',
              '## 复现与审计', '',
              f'经济契约 SHA256：`{sha256(HERE/"contracts/capital_scaling_policy_v1.json")}`。输入、冻结源码、Native 基准、账户不融资、实际公司行动、场景唯一性、确定性重放和输出哈希均由运行器/收尾门禁核验。具体测试结果和 Git 发布状态见收尾证据；计算 COMPLETE 不替代提交与远端 HEAD 检查。', '',
              '复跑入口：`PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.capital_scaling_v1.run --stage all`。详细依赖、父缓存绑定和最终门禁命令见 REPRODUCTION_COMMANDS.md。', '']
    (HERE/'REPORT.md').write_text('\n'.join(lines))
    plots()
