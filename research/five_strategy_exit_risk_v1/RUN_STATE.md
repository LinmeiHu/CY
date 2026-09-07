# RUN_STATE

Run: 20260907_v2_01 / V2_REBUTTAL_CORRECTED
Stage: RESEARCH_OUTPUTS_FINALIZED
TASK_STATUS: PARTIAL_COMPLETE
SHORTLIST: NONE
Updated: 2026-09-07T16:12:15.127319+08:00

已完成接管、冻结登记、53,816状态、简单/ATR/时间基准、B0/B1/B2与删组、11组完整账户、单一MCB利润保护、执行/时间压力、独立只读反证、中文报告。32 tests passed。

阻塞：当前生产ATRDR Bull/Slow以未来COMPLETED筛掉8笔已入场事件；三路线共享router结果隔离。下一项应建立保留未成熟持仓后的因果账户配对证据，未启动资金池。生产src/config未改，未打开新的封存验证。

实际命令（各阶段已分别成功执行，不将启动当作完成）：

```bash
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/run_v2.py --stage prepare
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/run_v2.py --stage paths
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/run_v2.py --stage smv6
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/run_v2.py --stage simple
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/run_v2.py --stage information
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/run_v2.py --stage accounts
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/diagnostics_v2.py --minutes
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/validate_v2.py
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/figures_v2.py
PYTHONPATH=src /opt/anaconda3/bin/python3 -m pytest -q research/five_strategy_exit_risk_v1/test_v2.py tests/unit
PYTHONPATH=src /opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/report_v2.py
```

同输入MCB10%三项规范哈希一致；11组配对日期序列完全一致；最后检查包含schema、源输入指纹、图表人工视觉核查。源码冻结哈希22/22一致。

完整复跑入口：`bash research/five_strategy_exit_risk_v1/reproduce_v2.sh`。研究计算没有后台待完成阶段；下一步是独立处理上述生产缺陷证据。

核心产物SHA256：

- `research_contract.json`: `5f138e1b078e874e8984b0d61a429bfdb8c322c4c6b6d3c780c3072e5c72d7eb`
- `loss_anatomy.csv`: `82a3c3bd4323a2426bb7656091c5d614a8ab55f1bfffe800637fe87d7b4bb07e`
- `simple_exit_response.csv`: `0f1df8b513714e1b500908bfaf570f680a8c08c65884d3c17bcfe2f786e18b8c`
- `incremental_information.csv`: `2cf48045957e9215ca7f7140515ee33fc4b69a5dca03556d02b05f909bea6571`
- `policy_comparison.csv`: `0d9313883737c2b020d09e857701eb958256f90eb63450947e08702cb08623b8`
- `account_effects.csv`: `788320eca5d9d03126099df7e9518a162f765d98461fc8ab8d7cd52fd4725a08`
- `execution_and_no_financing_audit.csv`: `aa31720baca89a177318b6ba63cfdf8a57213bce6589d621db9bceccf684b8a2`
- `verification_results.json`: `d3036af6c99830480002aa084b5744a9799b9257b5635ab41993fc7beae4bf12`
