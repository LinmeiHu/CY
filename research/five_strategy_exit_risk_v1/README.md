# Trade failure / exit research V2

本目录沿用已停止V1任务的位置。当前入口是 `reproduce_v2.sh` / `run_v2.py`，结论见 [REPORT.md](REPORT.md) 与 [decision_matrix.csv](decision_matrix.csv)。

- `engine.py`、`run_exit_risk_v1.py`、`structural_stop_preregistration.json` 是接管保留的历史来源。V2仅使用旧engine的哈希辅助函数，不使用旧盘中执行器；旧runner不是当前研究入口。
- 原件、旧结果快照、运行日志和大型路径表保留在 `input_config.json` 登记的外接盘目录。`takeover_inventory.json`、`experiment_version_index.json` 记录来源与版本。
- `research_contract.json` 固定窗口、时钟与预算；`objections_and_resolutions.md` 保留真实反证；`verification_results.json` 区分研究测试通过与生产ATRDR前缀失败。
- `source_input_fingerprints.json` 是截至2023、SQL屏蔽未来退出字段后的输入摘要哈希。`input_and_exposure_manifest.json`、`external_artifact_schemas.json` 定位外置结果；`completion_manifest.json` 锁定本次紧凑交付。
- `requirements_v2.txt` 记录实际运行库版本，当前Python为3.13.5。输入路径重映射模板是 `input_config.template.json`。

复跑当前已登记同一输入：

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-exit-risk-v1
bash research/five_strategy_exit_risk_v1/reproduce_v2.sh
```

该脚本实际重跑prepare、SMV6 callbacks、简单/机制事件、多状态信息、账户、诊断、验证、图表和报告，并保留追加实验记录。既有缓存只适用于同一冻结输入；改变输入时使用新的run_id和空的真实外接盘输出目录，不能给旧缓存重新归因。

本轮只提交研究文件，未改生产规则、未push。SHORTLIST=NONE；TASK_STATUS=PARTIAL_COMPLETE的唯一决策阻塞是ATRDR V29已入场持仓的生产完成门，不能绕过后直接进入共享资金优化。
