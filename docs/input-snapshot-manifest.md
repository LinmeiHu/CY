# 输入快照清单契约

`configs/data_asset_registry.json` 是可发现、可审计的数据白名单，但登记不等于激活。每次数据加工、状态生成或研究运行都必须再提供一份不可变的输入快照清单，将抽象资产绑定到确定的文件、目录清单、哈希、时间范围和审计证据。

机器契约见 `configs/input_snapshot_manifest.schema.json`；目录清单契约见 `configs/file_inventory.schema.json`。运行时的失败关闭校验由 `cyq_game.data.registry.InputSnapshotManifest` 执行。当前没有生产研究清单，也没有任何真实研究或回测被激活。

## 字段语义

- `manifest_id`：本次冻结输入集合的永久 ID；内容变化必须产生新 ID。
- `registry_id`、`registry_sha256`：绑定注册表的身份与完整文件哈希。注册表变化后必须重新冻结，禁止自动追随最新版。
- `purpose`：只能是 `DATA_PREPARATION`、`SOFTWARE_TEST`、`CAUSAL_RESEARCH` 或 `STRICT_ARCHIVAL_RESEARCH`。
- `hard_valid`：整个快照是否满足其用途的强制数据条件；不是人工豁免开关。
- `scope.start/end`：该快照允许处理的唯一日期边界。构建 PIT 仓时必须精确相等，后续操作只能收窄，不能外扩。
- `bindings`：一个业务角色只能绑定一次。文件使用 `sha256`；目录使用独立的 `inventory_manifest` 与 `inventory_sha256`。路径必须位于相应注册资产的登记位置内。
- `source`：数据来源，不得写成含混的 `local` 或 `unknown`。
- `snapshot_id`：该物理输入快照的稳定身份；不是运行时随机值。
- `available_at_policy`：逐条记录的可得时间来源或确定性推导规则。不能把采集时间、交易日期或当前快照日期冒充历史披露时间。
- `audits`：覆盖率、重复、时间穿越、一致性、跨表一致性五项证据。研究状态生成要求全部 `PASS` 且证据非空。

审计证据必须写入冻结、追加式或内容寻址的文件；修改证据必须生成新的输入快照清单。生成的 SQLite、回测输出、状态表和报告永远不能反向登记为源数据。

## 目录 inventory 约束

目录绑定不能只冻结“来源清单”或目录名。`inventory_manifest` 必须列出本次实际允许读取的每个文件相对于绑定目录的路径、字节数和 SHA-256；运行时每次读取都会重新核验 inventory 本身的哈希，再核验所选文件的存在性、大小和内容哈希。未列出的文件即使位于该目录中也拒绝读取。

inventory 的 `root` 必须精确等于绑定目录，文件路径必须是目录内的相对路径，禁止绝对路径、`..` 和重复项。来源系统提供的 manifest 只属于来源血缘证据，不能替代 CYQ-GAME 的内容 inventory。inventory 或任一数据文件变化后，必须生成新的 inventory 哈希和新的输入快照清单身份。

## 用途约束

| purpose | 允许用途 | 关键限制 |
|---|---|---|
| `DATA_PREPARATION` | 结构探测、适配、规范化摄取 | 必须 `hard_valid=false`；不得生成策略状态或回测 |
| `SOFTWARE_TEST` | 合成/QA 数据的软件机制验证 | 必须显式传入软件测试授权；QA 资产不得驱动策略状态 |
| `CAUSAL_RESEARCH` | 免费数据可实现的因果研究 | 必须五项审计通过、`hard_valid=true` 且全局门禁开启 |
| `STRICT_ARCHIVAL_RESEARCH` | 严格归档 PIT 研究 | 还要求所有绑定资产达到 PIT A 级 |

即便快照本身合格，`backtest_authorized=false` 仍会独立阻止回测和鲁棒性运行。

## 结构示例（非激活清单）

```json
{
  "manifest_id": "example-preparation-001",
  "registry_id": "CYQ-DATA-BASELINE-20260820",
  "registry_sha256": "<64位注册表SHA-256>",
  "purpose": "DATA_PREPARATION",
  "hard_valid": false,
  "scope": {"start": "2018-01-01", "end": "2026-08-12"},
  "bindings": [
    {
      "role": "minute_bars",
      "asset_id": "QD-004",
      "path": "/absolute/registered/directory",
      "source": "quant canonical unadjusted 1m",
      "snapshot_id": "quant-1m-none-20260813",
      "available_at_policy": "bar close plus recorded ingestion latency",
      "inventory_manifest": "/absolute/registered/directory/manifest.json",
      "inventory_sha256": "<64位清单SHA-256>"
    }
  ],
  "audits": {
    "coverage": {"status": "NOT_RUN", "evidence": ""},
    "duplicates": {"status": "NOT_RUN", "evidence": ""},
    "time_travel": {"status": "NOT_RUN", "evidence": ""},
    "consistency": {"status": "NOT_RUN", "evidence": ""},
    "cross_table": {"status": "NOT_RUN", "evidence": ""}
  }
}
```

尖括号占位符必须换成真实哈希后才可使用；示例本身不能作为激活输入。
