# V3实际验证过的复现与交付核验

工作目录：`/Users/linmei/Documents/CY-worktrees/usic-multichampion-ashare-v3-20260908`。以下命令使用现有授权输入及V3独立缓存；依赖清单、文件路径及SHA256见INPUT_MANIFEST、执行绑定和DELIVERY_SEAL。原始数据没有打入源码包。目录迁移后需显式适配common.py中的本机路径，并重新核验输入，不能直接声称异机运行通过。

这里区分实际账户重新回放、断点校验、测试与交付文件校验。生成配置/信号、单测通过或提交批处理都不是账户完成。SCENARIO_MANIFEST保留原附件的预登记PLANNED状态以保持身份不变；实际状态以scenario_summary.csv、RUN_CHECKPOINT及每个账户result.json为准。

## 已实际完成的全期账户

核心及Q5驱动先后完成全组执行和公司行动事实补齐后的重放；最后一批中断后，下面的续算命令真实执行成功：

```sh
cd /Users/linmei/Documents/CY-worktrees/usic-multichampion-ashare-v3-20260908
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.run --groups C,D,E,Q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.run_q
```

日志：外部输出目录的core_run.log、core_backfilled.log、core_final.log、core_resume_chunk.log、q_run.log、q_final.log、q_final_driver.log。最后状态为252个全期完成，44个事前条件门阻塞，没有运行中或bug失效槽位。每个完成目录有970行NAV及orders、trades、audit、holdings、open_positions。断点驱动会重新校验输入身份及六份产物的SHA256，命中后输出RESUME_VERIFIED；这不是新增运行次数。

## 已实际重复回放且66份产物逐字节一致

以下两条命令实际完成8个核心代表与3个分钟代表，均重新走账户引擎全期计算。结果与原运行的六份账户Parquet全部同SHA256，日志为repeat_core.log与repeat_q.log，各情景有repeat_checks.json和带_repeat后缀的真实文件。重复文件不会覆盖原六份权威账户产物。

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.run --repeat --ids A_D03_C_MAX_EST,A_H02_C_MAX_E10,A_D06_C_10_EST,D_D03_C_MAX_R_STAGE,E_P1_BALANCED_C_MAX_E10,E_P3_CORROBORATE_C_ONE_EST,B_D08_C_10_DELAY1,C_D06_C_MAX_G_RAMP
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.run_q --repeat --ids Q3_ENHANCED_C_MAX_EST,Q4_BASE_C_10_E1,Q4_ENHANCED_C_ONE_E3
```

重新运行驱动会刷新本地检查点时间；这会改变交付SHA256，故交付核验请先运行下一节的只读检查。若重放后要建立新的交付版，应重新分析、封存并提交，不能覆盖原封存哈希掩盖变化。

## 已实际完成的检查及分析

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -m unittest research.usic_multichampion_ashare_v3.test_v3 research.usic_multichampion_ashare_v3.test_tail -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -m research.usic_multichampion_ashare_v3.verify_core
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -m research.usic_multichampion_ashare_v3.verify_q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.analyze
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.event_analysis
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/linmei/Documents/CY/.venv/bin/python -u -m research.usic_multichampion_ashare_v3.execution_diagnostics
```

17项测试见tests_final.log；41项核心前缀/继承身份见PREFIX_CHECKS.json；53项分钟资格见Q_QUALIFICATION.json及verify_q.log。252账户独立对账见ACCOUNT_AUDIT.json和statistics/account_audit.csv。分析日志使用最终修正版analysis_verified.log、event_analysis_verified.log及execution_diagnostics_verified.log，早期失败日志保留，不冒充通过。

报告生成命令为`python -m research.usic_multichampion_ashare_v3.build_report`；图形使用既有V2 plot_runtime只读Python运行`python -m research.usic_multichampion_ashare_v3.plot_results`，配置缓存写入V3输出目录，不安装或修改V2环境。运行环境版本见RUNTIME.json。

## 交付文件的实际核验入口

```sh
cd /Users/linmei/Documents/CY-worktrees/usic-multichampion-ashare-v3-20260908
sh research/usic_multichampion_ashare_v3/reproduce.sh
```

该命令不运行策略、不更改已有账户，重新检查全部296个状态、252个全期账户、1512份原账户文件、66份重跑文件、当时绑定的原始输入和全部交付字节，并核对DELIVERY_SEAL。它仅把核验结果写入外部delivery_validation.json。此入口在交付时已经执行成功；真实结果与日志位于外部输出目录。

`--seal`仅用于当前交付作者首次形成封存，不是掩盖校验失败的修复方式。源码包由最终Git提交生成；END_HEAD、普通push结果、远端分支HEAD、报告/源码包SHA256和工作树状态在提交后写入外部DELIVERY_STATUS.json，避免Git哈希自引用。

完整计算尝试与公司行动补齐前后可比结果见RUN_ATTEMPTS.json。不存在可执行的Q1/Q2/Q6和I0—I7完整账户；这些槽位的恢复需要相应授权/数据/权威账户基线，不能靠命令开关或填零解除条件门。
