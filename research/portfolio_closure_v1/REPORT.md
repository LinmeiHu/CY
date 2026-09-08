# 五策略组合闭环：历史输入审计（已修复并被新研究替代）

TASK_STATUS: SUPERSEDED_BY_UNIFIED_OPPORTUNITY_RISK_V1

以下保留旧审计当时的边界，不代表当前阻塞。预资金请求、实际持仓路径、盘中P0与资本天已完成修复；后续固定multiplier研究由用户替换为统一机会池研究，最终完整结果见 ../unified_opportunity_risk_v1/REPORT.md。

旧审计当时尚未完成资本配置研究。按照用户“除非发现真正的数据/身份错误”的例外，在组合搜索前停止。没有冻结结果选择契约，没有执行联合网格，没有推荐 multiplier；不能将本次状态解释为 KEEP_CURRENT_NATIVE 或 NO_ROBUST_PORTFOLIO_IMPROVEMENT。

## 仍成立的事实

对权威连续账户的 106 笔 SMV6 BUY，独立使用 event_id 连接重放请求，并核对证券、执行时间、请求数量和请求金额，106 笔全部匹配。原始 producer 不缺失；旧 baseline 的 2023 截止不构成缺源证据。本次不撤销这项窄范围的 provenance 事实。

## 已确认的数据错误

1. `recover_smv6.py:opportunities` 将 BUY_SIGNAL、BUY_FILLED、REBALANCE_FILLED 和 NO_FILL 行合并为 200 个“机会”。同一信号及其成交阶段均入表，其中 24 行是负数量的减仓成交。随后 funded=True、filled=False 把这些卖出错误汇总成“已获资但未成交”。40/123/37 是该混合事件表的年度数量，不能作为合法 pre-capital population 计数。106 条重放买请求可核验，但也不能据其全部成交就证明所有未下单资格机会已经覆盖。
2. `continue_closure.py:shadow` 没有调用 shadow replay；直接将 `native_realized_return` 复制到 `shadow_native_return`，所有 MFE/MAE 都写入 NaN，未获资机会没有独立 Native 生命周期。5,390 行中 1,722 行收益缺失，5,390 行 MFE 和 MAE 均缺失。已有成交也只取最后一笔 SELL，不能据此宣称部分退出、费用和公司行为已逐生命周期对账。
3. `continue_closure.py:conflicts` 把当日收盘 cash 改名为 `cash_available_before_funding`，把 gross exposure 改名为 gross headroom。已逐行核对两组数值相等。这既不满足事前可见性，也不代表实际可用资金。
4. `priority_and_architecture` 直接写入 discovery_sample=0、NO_STABLE_CAUSAL_PRIORITY_RULE；报告的 KEEP_NATIVE 是固定字符串。它没有实施所声称的优先级检验。旧测试通过只能证明预设输出存在，不能支持“B–F 已完成”的经济结论。

我撤回上轮“完整恢复 200 条机会、B–F 完成、最终研究裁决 KEEP_NATIVE”的表述。保留所有历史文件；本报告和逐行证据对其可采信范围作版本化纠正。未发现缺少原始 SMV6 producer 的证据，未修改冻结策略经济规则。

## 对本次资本配置问题的影响

五策略 signal character、增量组合价值、Gap 选择、四档风险带候选、固定 multiplier、成本/集中度/容量稳健性均未完成验收，不能给出实证结论。没有执行新的策略优先级研究、regime router 或 Full Book scaling。

这不是一次“优化未能胜出”的结果，而是研究输入验收失败。实际账户保持现状仅是未实施变更，不表示 Native 已经被证明最优。

## 恢复执行所需的具体修复

使用权威连续 PhysicalPlatform 在 funding 前捕获 callback eligibility、desired、实际 request 与状态，用 request 身份连接 downstream fills；信号、请求、买成交、减仓成交分别记录。随后对完整合法机会回放 Native 生命周期，覆盖未获资样本、部分卖出、公司行为和截止日右删失，核验实获资样本身份。资金状态应来自决策/执行前 checkpoint。以上输入修复完成后，才能冻结本次 0/0.5/1/1.5/2 联合网格契约并执行既定组合闭环，不需要另设计历史优化问题。

证据见 output/audit_status.json、opportunity_semantic_errors.csv、native_buy_request_identity.csv 与 native_receipt_hash_verification.csv。原始账户 receipt 哈希验证范围列在 input_manifest.json；没有声称全仓库所有历史输入都已验证。
