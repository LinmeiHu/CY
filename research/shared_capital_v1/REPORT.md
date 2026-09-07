# SHARED CAPITAL BASELINE CLOSURE V0.6

TASK_STATUS = PARTIAL_COMPLETE_ENGINEERING_INCOMPLETE

本次没有达到 BASELINE_CLOSURE_COMPLETE。600622 公司行动到账/可交易状态仍缺，ATRDR 两段连续初始状态无效；MCB 也有独立的 603368 阻塞。统一调度、合成公司行动与各策略可达初始状态已有实际实现和验证，但跨价格单位物理表示、共享级全退出/全入场阶段与共同 P0 多层对账仍存在工程欠项，不能只报告成数据缺失。

P0 OGR/IFCGR × 2018–2021/2022–2023 均 NOT_RUN_INITIAL_STATE_UNRESOLVED。实际共享场景 0；未运行 P1/P2/P3，未打开新封存验证，未更改冻结策略/政策/退出规则，未推送。

## 600622 的精确结论

现有 CNInfo p_sysapi1139 官方 JSON F025D = null，raw「股份到账日」与 normalized.share_credit_date 也为空，已核对原始 body/receipt/manifest/封存 producer SHA256。2017-06-23 公告、2017-06-29 登记、2017-06-30 除权及派息、转增 30%。available_at/known_at 为 2017-06-24 的日期精度保守知识时点，并非完整历史 revision 流。缺少独立到账、会计股份生效、可交易日期或唯一冻结转换规则。除权日/派息日不代替这些状态。

ATRDR_CORPORATE_ACTION_DATA_STATUS = DATA_INPUT_MISSING。MCB 的 603368.SH 2020-06-24 同样 F025D 为空；它的阻塞不归咎于 ATRDR。

## 独立基线及实际修正

MCB 2018 边界现金/NAV 1,312,987.896579233、空仓，已独立对比原生账户；2022 不可达。OGR/IFCGR 2018 为原生账户起点，2022 延续现金分别 1,110,169.4677651073 / 1,105,177.2081431411，回放证明空仓。SMV6 保留原生每段 init reset，初始现金 100 万、完整历史预热及实际 context。

发现并修正研究适配层遗漏：公司行动输入仍截断 2022-03-31。修正后首个后段 NAV 差异在 2022-04-29，002727.SZ 每股 0.3 现金分红此前被漏掉；后续 301326.SZ 2023-05-18 除权位于信号与入场之间，依原生规则拒绝该笔。OGR/IFCGR 后段重置控制由 45 笔变 44 笔，末值 1,007,359.4066154053 → 1,016,086.3188282596。这是 corrected company action，不是共同 P0 收益。旧控制和修正控制单独保存，不拟合旧 NAV。

OGR/IFCGR 原生连续至 2023 末 NAV 分别 1,128,256.951844012 / 1,123,173.430234658；与独立原生参考差小于 1e-6。OGR 真实 raw daily 截断至 2021-06-30 重建 360 个父信号，与未来扩展输入的历史父信号全字段相同；IFCGR 同一原始父信号+公告知识前缀重建 352 kept / 8 rejected，12,837 条分类事实与扩展输入相同。PIT-B revision 限制保留。SMV6 两段通过统一调度器仍与原生修正回调对账，原未来 close 扰动回归保持通过。

## 测试与剩余门

聚焦及原单元测试 106 passed；真实输入哈希及重跑层摘要见 v06_input_hash_verification.csv、v06_deterministic_rerun.csv。21 项用户要求及额外发现分行保存 requirement_test_coverage.csv，明确区分合成/独立账户通过和正式共同 P0 未运行。冻结策略和政策在本任务 START_HEAD ecb91d9af9d894f228cf3ce15f967e31660a5828 前后保持相同。

数据首阻塞是 600622 的 share_credit_date/F025D 与合法可交易状态。工程首欠项是不同原生价格/数量单位在共同证券下的物理表示，以及保留 SMV6 原生顺序的全退出/全入场整合；不能用 ATRDR 空仓替身绕过。待解决后仍须完整四套 P0 的独立多层比较才可关闭基线。

路径：reports/ca_600622_forensic.md、reports/native_state_closure.md、reports/common_scheduler_accounting.md。精确重跑及非零退出语义见 REPRODUCTION_COMMANDS.md。共享策略参数、HOME_BUDGET、原生费用/退出和 OGR/IFCGR 互斥均未修改。
