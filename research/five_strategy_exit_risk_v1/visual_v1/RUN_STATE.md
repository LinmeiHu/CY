# RUN_STATE

Run：20260907_visual_v1_01。视觉主阶段、风险偏好修订、20组账户重放及反例复核完成。冻结生产代码/配置和父V2研究产物未改。图包74张，Astra实际查看39张；视觉主阶段70/35，风险补充4/4。另有两张汇总图作展示检查。

最新有效命令：

```sh
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/risk_review.py --resume
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/risk_finish.py --summary-only
/opt/anaconda3/bin/python3 research/five_strategy_exit_risk_v1/visual_v1/deliver.py
PYTHONPATH=src /opt/anaconda3/bin/python3 -m pytest -q tests/unit research/five_strategy_exit_risk_v1/test_v2.py research/five_strategy_exit_risk_v1/visual_v1/test_visual.py research/five_strategy_exit_risk_v1/visual_v1/test_risk_review.py
```

账户首次运行遇到OGR策略与基线末次退出日不同的共同终点归因错误，已改为仅在完全空仓时延伸到共同登记日历，并统一按成交现金计算交易收益。续跑中的OGR事件ID索引列检测错误也已修正；完成产物通过逐事件/EOD现金检查和独立终点归因。没有屏蔽断言、修改原成交价格或放松无融资要求。

视觉假说和翻译仍为17:06:03冻结版本，四条量化motif均未形成稳定增量；没有以放松风险政策验收回写信息检验。简单风险方案按用户随后明确的偏好另外登记，证据为已消费历史复核。

哈希见`completion_manifest.json`及外接盘`artifact_hash_index.json`。下一研究阶段需独立处理ATRDR生产完成状态过滤的已证实缺陷；本轮不修改生产、不扩展2024+数据、不启动资金池。
