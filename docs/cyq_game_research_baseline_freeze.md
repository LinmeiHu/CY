# CYQ-GAME 既有研究基线冻结

冻结时间：2026-08-21T14:31:42+08:00

## 结论

以下运行只作为不可改写的 PIT-B 因果研究基线，不是严格 PIT-A 结果，也不构成策略晋级或实盘授权。后续实现和数据升级必须使用新的运行 ID；不得覆盖、删除或重新命名这些目录。

| 运行 | 状态 | 冻结证据 | 结论 |
|---|---|---|---|
| `runs/pitb-final-all-20200102-20260812-u1` | 失败并保留 | `docs/pit-b-final-validation.md` 的失败实验记录 | 公司行动零碎股处理暴露缺口；不得作为完成结果 |
| `runs/pitb-final-all-20200102-20260812-u2` | 人工中止并保留 | `docs/pit-b-final-validation.md` 的失败实验记录 | 追加事件 O(n²) 性能问题；不得作为完成结果 |
| `runs/pitb-final-all-20200102-20260812-u3` | 完成、重放通过、经济晋级失败 | `manifest.json`、`replay_report.json`、`summary.json` | 仅作旧版 PIT-B 研究参考；不得标记为严格 PIT 或可交易策略 |

## U3 冻结指纹

| 文件 | 生成/修改时间 | SHA-256 |
|---|---|---|
| `runs/pitb-final-all-20200102-20260812-u3/manifest.json` | 2026-08-21T10:14:12+08:00 | `46e0b0cd42939db22ae808d458f73a051f8d390e0c5f396bd73286df45da12ec` |
| `runs/pitb-final-all-20200102-20260812-u3/summary.json` | 2026-08-21T10:14:03+08:00 | `29bac3e2219919b8ddca91e77ac7f2cd9a77e7ab0e78b3b64d4c1120abe570ea` |
| `runs/pitb-final-all-20200102-20260812-u3/replay_report.json` | 2026-08-21T10:15:08+08:00 | `b102dbc527882dda2cfbec047d45d1f26185bfd5619149ed1e2ae2a4791ecb02` |

`manifest.json` 已绑定并由重放验证以下大型产物，因此 G0 不重复读取约 15GB 的 `decisions.jsonl`：

| 受管产物 | manifest SHA-256 |
|---|---|
| `decisions.jsonl` | `58b56840cdce7b8764db230830c7a65af75b235369a0806df4ba1f71e9db2229` |
| `equity.csv` | `281bf43f5dce2ea51cd2272498f4c2f604d848f485947a92cfa3839fc54d178a` |
| `research_diagnostics.json` | `3a4c046e5870bc94eaa9eab0799f7385eae4bfd57cc6e9f2f2b4f82738c081f1` |
| `walk_forward.json` | `7ae49f038cf23eca9279eaab520ad30adbc181e0a77b81b253cf3309242f4df9` |

## 非严格原因

- 数据授权为 `CAUSAL_RESEARCH`，输入是 PIT-B，而非带完整官方历史版本链的 PIT-A。
- 公司行动缺少预案、修改、撤回到最终实施的完整公告版本链。
- 历史证券名称/ST、部分板块历史成分和历年交易规则缺少完整官方归档证明。
- U3 未使用当前已冻结的日线/分钟 V2 联合输入。
- U3 经济指标未通过晋级门槛，且最终留出集已经访问并污染。

本冻结动作不运行回测、报告生成或全市场下载。
