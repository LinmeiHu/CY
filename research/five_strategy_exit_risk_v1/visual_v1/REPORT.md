# 五策略视觉发现与风险优先复核交付

最新结论见[风险与现金复用报告](RISK_REPORT.md)：止损后的现金与名额再次交易已计入20组完整账户重放。存在能以明确收益代价缩小极端亏损的简单方案；无须先证明视觉预测足够准确，也不能将未来组合资金池可能的利润预先加进收益。

本轮视觉发现本身没有形成稳定的新增机制信息，见[视觉报告](VISUAL_REPORT.md)。这与保留简单风险研究候选并不矛盾。

| 验收字段 | 实际状态 |
|---|---|
| ENVIRONMENT_VALID | YES；正确工作树与实际挂载外接盘 |
| BRANCH | research/five-strategy-exit-risk-v1 |
| BASELINE_HEAD | 40d924ca718be40c6e891a64b3a9cac7f8d58f95 |
| START_HEAD | 1628f14a3949244998e0223cc0f419a00e66c856 |
| END_HEAD | 见最终交付消息中的本地提交；该提交包含本目录 |
| TASK_STATUS | 本轮多模态发现及风险偏好复核完成；ATRDR生产准入仍受已知缺陷隔离，不是五策略生产封箱完成 |
| WORKTREE_STATUS | 只提交本目录研究产物；最终Git状态见交付消息 |
| REUSED_PRIOR_WORK | 父V2同版完整机会、日线/状态、交易执行、账户与71个小型研究产物；旧独立结论保持可追溯 |
| PRIOR_RESULTS_EXPOSURE | RESULT_EXPOSED；没有全新独立盲验证 |
| ACTUAL_RESEARCH_WINDOWS | ATRDR/MCB：2014–2020发现、2021–2023已消费后段；OGR/IFCGR/SMV6主要窗口：2018–2021、2022–2023 |
| ATRDR_IDENTITY_VERIFIED | V29 Bull + V27 Bear子路线 + V29共享router；身份已核，完成状态过滤缺陷未消除 |
| FROZEN_PRODUCTION_RULES_MODIFIED | NO |
| NEW_SEALED_VALIDATION_OPENED | NO；没有读取2024+新结果 |
| NO_FINANCING_VALIDATION | PASS：20组新账户、40个板块分支，资金分解误差小于1e−9初始净值 |
| PREFIX_INVARIANCE | 新研究前缀/毒化测试PASS；既有ATRDR生产prefix缺陷仍为FAIL并隔离 |
| TEMPORAL_SPLIT_VALIDATION | 冻结、事件purge及训练期预处理检查PASS；数据阶段仍是已消费历史 |

无条件的研究shortlist：MCB已有盈利保护、OGR入场ATR×1；IFCGR继承OGR并保留PIT-B完整性限制。Fast固定5%是隔离的条件方案，不在已验证账户shortlist中。Bull列出强保护与较低代价的取舍，Slow和SMV6不新增退出。

43项测试通过，包含生产小型反例、视觉前缀/匹配/冻结、实际收费、共同账户终点和20组资金分解检查。唯一下一步是固定研究候选并先独立修复、封箱ATRDR基线，再安排后续验证；不把该缺陷带入资金池优化。

复跑命令和文件目录见[README](README.md)，样本与独立日期见[risk_sample_coverage.csv](risk_sample_coverage.csv)，所有失败尝试和修正保留在审计日志中。
