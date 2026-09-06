# ASHARE-DEEP-DECLINE-INTRADAY-UNDERCUT-MARKET-STATE-EXIT-V2

Verdict: `DEVELOPMENT_GATE_FAIL_CLOSED`.

Market state uses only the completed signal close and prior observations. No future return, year label, later breadth, or full-sample percentile enters state construction. The first possible fill is the next legal open.

|Year|Completed|Mean net|Median net|Severe <=-10%|Hit >=4%|
|---:|---:|---:|---:|---:|---:|
|2014|63|2.42%|4.60%|11.11%|55.56%|
|2015|130|4.44%|9.60%|11.54%|77.69%|
|2016|134|0.46%|-0.19%|8.96%|38.81%|
|2017|307|-1.15%|-1.41%|6.19%|31.27%|
|2018|354|3.96%|9.60%|6.78%|66.38%|
|2019|322|3.04%|4.60%|5.59%|51.55%|
|2020|259|1.63%|4.60%|8.88%|52.12%|

Frozen state-routed exits: UP -> T15/H30; DOWN_SYSTEMIC -> T10/H20; DOWN_ORDINARY -> T5/H5. The parent signal and entry identities are unchanged.

2021 signal outcomes read: **FALSE**.
2022+ signal outcomes read: **FALSE**.
