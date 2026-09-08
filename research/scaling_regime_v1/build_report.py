"""Publish the identity rejection without fabricating downstream results."""
import json
from pathlib import Path

import pandas as pd

from .audit import HERE, OUT, START_HEAD


def main():
    boundary = pd.read_csv(OUT / 'native_boundary_mismatch.csv')
    checks = pd.read_csv(OUT / 'rollforward_identity_audit.csv')
    hashes = pd.read_csv(OUT / 'input_hash_verification.csv')
    contract_hash = json.loads((HERE / 'contracts/freeze_receipt.json').read_text())['contract_sha256']
    table = ['|Gap|字段|父账户|滚动账户|差额|', '|---|---|---:|---:|---:|']
    for row in boundary.loc[boundary.field.isin(['SMV6_initial_cash', 'SMV6_nav', 'SMV6_exposure'])].itertuples(index=False):
        table.append(f'|{row.gap}|{row.field}|{row.parent_value:,.6f}|{row.rollforward_value:,.6f}|{row.difference:,.6f}|')
    top = checks[['rank', 'gap', 'mcb_mode', 'target']].drop_duplicates()
    top_text = '\n'.join(f'- #{r.rank}: {r.gap} / {r.mcb_mode} / {r.target}。身份门禁 FAIL。' for r in top.itertuples(index=False))
    questions = [
        '2024 亏损主要是 Native alpha 弱化还是缩放放大？', '2026 YTD 亏损主要来自哪一项？',
        '2025 为何产生大量缩放收益？', '2024 哪个策略和路线主导损失？', '2026 哪个策略和路线主导损失？',
        '2025 哪个策略和路线主导利润？', '各年 Full Book 调仓帮助还是伤害？',
        '2024/2026 是否类似 2018–2023 已有坏状态？', '2025 是否类似以前的好状态？',
        '哪些事前状态解释增量缩放 P&L？', '发现期与确认期方向是否稳定？',
        '是否存在简单 Native/G25 路由器？', '目前为什么不能给出路由决策？',
        '当前规模的 G25 容量是否可信？', '哪个策略构成 G25 主要容量负担？', '下一步研究优先级是什么？']
    answers = ['NOT_ESTIMABLE_IDENTITY_GATE：尚未在身份一致的账户上计算。'] * len(questions)
    answers[12] = '父契约与滚动图的初始化协议不同，MCB 运行时资格谓词也被替换；尚未进入状态归因，不能判定有或没有稳定路由器。'
    answers[15] = '先确定并冻结连续账户的权威协议，补足 MCB 行业快照证据，再重建全部 Native/G25 及必要机制对照。之后才是归因、容量与路由资格；本次没有新 alpha 依据。'
    pd.DataFrame([dict(question=i+1, text=q, answer=a) for i,(q,a) in enumerate(zip(questions,answers))]).to_csv(OUT / 'main_question_status.csv', index=False)
    report = f'''# CAPITAL SCALING REGIME ATTRIBUTION V1 — 身份门禁拒绝

TASK_STATUS: BLOCKED_ROLLFORWARD_IDENTITY_MISMATCH。经济归因、容量和路由资格研究未完成。不是“已完成全部研究”，也不是“没有稳定状态路由”的统计结论。

用户任务第 3 节明确规定："If any portfolio shown in the roll-forward differs from the frozen parent scaling rule: stop economic interpretation and report exact mismatch." 本次五个 Top 组合均触发此门禁，故在状态与收益联结前停止。未新增规则、阈值、策略、退出或融资，也未开启新的封存验证。

## 证据链与结论

父分支 research/five-strategy-capital-scaling-v1，父 HEAD `{START_HEAD}`。实际滚动图位于父工作区未提交的 `research/capital_scaling_v1/reports/continuous_rollforward_v2/研究报告.md`。其生产脚本和物理账户均已找到，不能说“源码不存在”。原文件路径、快照与哈希见 `evidence/source_inventory.json` 和 `input_manifest.json`。

{top_text}

五组都保留 2018–2021 CAGR 排名及对应 Gap、MCB 模式、gross 目标，使用同一 Full Book 引擎。直接比对各自 973 个历史日期的 NAV/cash/gross，均在绝对误差 1e-6 元内通过。冻结源文件和成本身份一致。共同截止日为 2026-09-04，2026 是 YTD。这些通过项不覆盖 2022 以后的初始化与运行时输入谓词。

### 1. 已证实：2022 边界协议改变

父经济契约的 `initial_states` 要求股票采用原生连续边界状态，SMV6 按每个父区间执行原生回调初始化。父 2022 年 SMV6 从 1,000,000 元、空仓以及重新初始化的 context 开始。

滚动生产器 `run_continuous_combinations.py` 仅调用一次 `replay(..., '2018-01-01', END, ...)`，沿用 2018 年初状态连续运行至 2026 年。它在 2022 年没有重新初始化 SMV6，缩放资金参照也来自这套连续 Native 的 timeline/home_before_funding。

以下为只读账户身份比对，`SMV6_initial_cash` 对比父 2022 初始现金与滚动 2021 年末现金；其余字段取 2022-01-04。单位元：

{chr(10).join(table)}

父 SMV6 当日实际持仓约 519,933.40 元，滚动 Native 为零；因此差异包含回调状态和持仓路径，并非只把资金单位等比例改大。两种 Gap 结构都出现这一差异，且五个 Top 的缩放生产器均使用相应连续 Native 资金参照。

连续运行可以是合理的另一个实验，历史原生区间初始化也不应被错误恢复成“每年强制清仓”。本审计不宣称连续账户本身经济上错误，更没有计算该差异究竟解释多少 2024/2026 损失。这里证实的是它不等于本次指定的父边界协议，不能静默合并两类结果。

股票请求对照另有 6 行：OGR/IFCGR 两个独立 Native 账户的 ATRDR、MCB、Gap 在父 2022–2023 全部请求身份及金额仍对齐，最大金额差低于 1e-6 元。不能把 SMV6 问题扩大为“所有原生信号或股票定仓都变了”。详见 `native_request_comparison.csv`。

### 2. 已证实谓词替换；效果等价性未证实

冻结 `mcb.build_v53` 需要 `d.industry_snapshot_id IS NOT NULL`。滚动 `build_rollforward_inputs.py:mcb_screens` 通过 `corrected_function` 改成 `d.causal_industry IS NOT NULL`。已读取 Parquet schema 验证：滚动合并面板有 causal_industry，没有 industry_snapshot_id。

行业名称存在不证明对应时点行业快照有可验证身份。两谓词在逻辑上不同；2018–2023 信号集合相等也不能证明新数据中的资格条件等价。这里没有断言替换已经改变某一笔后续信号或造成某个收益差，结论是原资格谓词改变且新窗口等价性未证。恢复身份需要逐时快照映射或明确冻结新的数据资格协议，不能靠相同股票总数或相同 Python 文件哈希消除这个差异。

## 停止范围

本次未运行年度损益分解、逐策略/路线/证券归因、Full Book 后续收益归因、Entry Only 重放、状态分桶收益、leave-year、router 或 G25 容量。`router_results.csv` 不生成；其他尚未计算的经济 CSV 也不写虚构数字或空壳 PASS。

`NO_STABLE_SCALING_REGIME_ROUTER` 与 `REGIME_EFFECT_EXISTS_BUT_NOT_ACTIONABLE` 都需要经济证据，当前均不能下结论。ROUTER_CANDIDATE_STATUS 为 NOT_EVALUATED_IDENTITY_GATE；G25 容量为 NOT_RUN_IDENTITY_GATE，既不是容量通过也不是已证明缺少成交额数据。

## 16 个问题的处理

''' + '\n\n'.join(f'{i+1}. {q}\n\n{a}' for i,(q,a) in enumerate(zip(questions,answers))) + f'''

## 冻结、测试与复现

状态契约在任何状态条件收益分析之前冻结；本次身份审计已看过父年度报告，因此后续只能声称事后诊断，不能称新封存验证。契约 SHA256：`{contract_hash}`。

当前 {len(hashes)} 个输入/来源文件全部哈希通过，覆盖 413 条父登记输入、136 个父缓存及 26 个冻结策略身份文件；多个角色可能指向同一文件，不能把角色数量相加当独立文件数。对未提交滚动来源只绑定观察到的字节；这不追认其为封存生产者。所有受 Git 跟踪的修改仅位于本工作树的 `research/scaling_regime_v1`；父回归测试另使用 Git 已忽略的 `research/shared_capital_v1/cache` 只读来源软链接。

测试结果见 `output/test_results.json`；确定性复跑见 `output/determinism.csv`。测试通过表示门禁能正确拒绝不一致账户，不表示被拒绝的经济研究通过。`requirement_test_coverage.csv` 明确列出 42 个任务章节与 18 个测试要求中哪些未运行，避免用身份测试冒充 P&L/容量测试。

复跑命令：`PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.scaling_regime_v1.audit`。身份拒绝预期返回 2；返回 2 不是执行故障或测试失败。报告入口：`PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.scaling_regime_v1.build_report`。精确步骤见 `REPRODUCTION_COMMANDS.md`。
'''
    (HERE / 'REPORT.md').write_text(report)
    report_names = ['2024_drawdown_anatomy', '2025_profit_anatomy', '2026_drawdown_anatomy',
                    'scaling_mechanics_attribution', 'regime_evidence', 'g25_capacity']
    for name in report_names:
        (HERE / 'reports' / (name + '.md')).write_text(f'# {name}\n\nNOT_RUN_IDENTITY_GATE。\n\n五个 Top 组合均与父冻结边界协议不一致，且 MCB 的行业快照谓词被替换。按任务第 3 节停止经济解释。本文件只记录未运行原因，不是已经完成的归因或容量报告。详见 [身份门禁报告](../REPORT.md) 和 [逐项审计](../output/rollforward_identity_audit.csv)。\n')
    names = ['权威父研究','主问题','滚动身份','年度分解','Native与缩放增量','策略贡献','年度回撤',
             'Full Book归因','机制对照','事前状态','状态条件增量','发现确认诊断顺序','简单状态族','年份禁作特征',
             '路由资格','影子路由','时间因果与prefix','路由评价','切换与滞后','G25容量','容量旗标','规模参照',
             '无新alpha','无新退出','无目标优化','小样本','leave-year','坏状态','2025好状态','ATRDR路线',
             'Demand家族','Gap家族','SMV6分散','状态转移','不过拟合','交付目录','契约冻结','测试','决策逻辑','16个问题','Git','最终响应']
    coverage = []
    for i,name in enumerate(names,1):
        state = 'NOT_RUN_IDENTITY_GATE'
        evidence = 'REPORT.md; user section 3 stop condition'
        if i in (1,3):
            state, evidence = 'AUDITED_FAIL_CLOSED', 'output/rollforward_identity_audit.csv'
        elif i in (12,13,14,16,17,23,24,25,35,37):
            state, evidence = 'CONTRACT_ONLY_OR_NO_ACTION; NO_ECONOMIC_VALIDATION', 'contracts/scaling_regime_attribution_v1.json'
        elif i in (36,38,39,40,41,42):
            state = 'IDENTITY_REJECTION_DELIVERABLE_ONLY'
        coverage.append(dict(kind='TASK_SECTION', requirement=i, name=name, status=state, evidence=evidence))
    test_names = ['冻结排名身份','2021后不重选','年份不作状态特征','状态时间戳','未来收益不入特征','年度PNL对账',
                  '策略PNL对账','路线PNL对账','调仓类别对账','EntryOnly同信号初态','状态总额对账','发现期prefix',
                  '候选仅冻结字段','仅Native/G25','容量确定性','路线确定性','冻结策略不修改','输出确定性']
    for i,name in enumerate(test_names,1):
        state = 'NOT_RUN_IDENTITY_GATE'
        evidence = 'No economic/state/router/capacity implementation after rejection'
        if i in (1,2,17):
            state, evidence = 'FOCUSED_TEST', 'tests/test_identity.py'
        elif i in (3,5,13,14):
            state, evidence = 'CONTRACT_CHECK_ONLY; NO_ROUTER_RUN', 'tests/test_identity.py; contracts/scaling_regime_attribution_v1.json'
        elif i == 18:
            state, evidence = 'IDENTITY_OUTPUT_RERUN_ONLY', 'output/determinism.csv'
        coverage.append(dict(kind='REQUESTED_TEST',requirement=i,name=name,status=state,evidence=evidence))
    pd.DataFrame(coverage).to_csv(OUT / 'requirement_test_coverage.csv', index=False)


if __name__ == '__main__':
    main()
