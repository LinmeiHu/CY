# V4 实际运行与复现

本轮从 V3 `9f3c146939fd48759b113a74086164acfabcfae2` 创建独立分支。以下为本机实际使用的运行入口；原始数据、V3缓存及公司行动依赖沿用已绑定路径。交付包提供代表账户的实际字节和输入身份，**不包含整个行情库，不能声称脱离已授权本机数据一键复现**。

```sh
cd /Users/linmei/Documents/CY-worktrees/usic-market-router-v4-20260908
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=.
```

运行器为 `/Users/linmei/Documents/CY/.venv/bin/python`，包前缀为 `research.usic_market_router_v4`。以下阶段入口均实际执行过，日志在 `/Volumes/quant/CY_quant_research/usic_market_router_v4`：

```sh
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.correct
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.states
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.maps
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.ranking
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.experiments --stage gates
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.correct_q3
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.experiments --stage route
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.recover
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.confirmation
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.repair_event_facts
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.attribution
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.explain
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.holding_attribution
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.verify_final
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.reproduce_one --id FIX_A_D09_C_MAX_E10
/Users/linmei/Documents/CY/.venv/bin/python -m research.usic_market_router_v4.build_report
```

这不是宣称上述阶段初次均成功的流水线：`correct.log`保留误收I4标签后的失败；该账户明确作废，正确依赖账户补完。11次事实阻塞分别由`recover`完成 `_CA` 版本。`repair_events.log`保留缺列错误，最终完成日志为`repair_events_final.log`。统计最终日志为`ranking_verified.log`、`explain_verified.log`；早期失败和警告日志不删除。官方事实查找还包括人工核对发行人实施公告，不能把网络查找脚本当作确定性复现步骤；冻结后的`action_backfill.csv`和原PDF才是执行事实输入。

缓存命中只校验身份，不计为新运行。重演优先用 `reproduce_one --id <已完成V4账户ID>`：读取冻结输入及所记录的引擎版本，在外接盘 `verification/<ID>_manual` 写六份文件并逐字节比较；本轮以上D09命令实际成功。`verify_final`另实际完成D08简单开关及过去信息账户全期重复、截断日历因果检查、全十二路线事件现金时钟校验，共26项通过。

基础及V4测试实际共20项通过，准确测试模块见`logs/tests_final.log`的每个用例；可用以下已验证入口：

```sh
/Users/linmei/Documents/CY/.venv/bin/python -m unittest research.usic_market_router_v4.test_v4 research.usic_multichampion_ashare_v3.test_v3 research.usic_multichampion_ashare_v3.test_tail -v
```

研究账户：48个纠错完成、48个新情景完成；54个原账户复用经哈希及现金审计；另4次验证性全期重演。11个历史阻塞尝试均有恢复版本，1个误派尝试作废。它们不合并成一个虚构的“账户运行数”。全部状态以`scenario_summary.csv`、`completion.json`和各`result.json`为准。

`ACCOUNT_ARTIFACT_MANIFEST.csv`给出所有完成/复用账户的真实路径、字节数及SHA256；`OMITTED_BYTES.csv`逐项列出未打包的外接盘研究产物。原始行情依赖另见`reference/INPUT_MANIFEST.json`和`FEATURE_MANIFEST.json`，没有复制或授权新封存样本。包内`PACKAGE_MANIFEST.json`覆盖除清单自身以外的每一个文件。真实提交和推送状态见外层`DELIVERY_STATUS.json`。
