# 2020–2023 行业缺口核验

## 结论

CY-006 在 2020–2023 标记 `industry_valid=false` 的 238 个代码，不构成主板/创业板在市股票的历史行业缺口：

- 211 个在 quant `security_master.parquet` 中状态为 `delisted`；
- 27 个在 `security_master.parquet` 中不存在，但代码全部属于 ETF/基金代码（159xxx、510xxx、511xxx、512xxx、515xxx、518xxx）；
- 因此本研究已冻结的非北交所、2023-12-29 仍有有效记录的 survivor universe 不需要使用当前快照行业回填。

## 证据输入

- 日线：`data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet`
- 证券主表：`/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet`
- 行业历史输入：`/Users/linmei/Downloads/workspace/quant/data/lake/meta/industry_daily.parquet`、`industry_events.parquet`

## 复核命令

```bash
python - <<'PY'
import duckdb
c=duckdb.connect()
d="'data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet'"
s="'/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet'"
print(c.sql(f'''WITH x AS (
  SELECT DISTINCT regexp_replace(symbol,'\\.(SZ|SH|BJ)$','') s
  FROM read_parquet({d})
  WHERE trade_date BETWEEN DATE '2020-01-01' AND DATE '2023-12-31'
    AND NOT industry_valid
)
SELECT coalesce(sm.status,'NO_MASTER'), count(*)
FROM x LEFT JOIN {s} sm ON x.s=sm.symbol
GROUP BY 1 ORDER BY 2 DESC''').fetchall())
PY
```

实际结果：`[('delisted', 211), ('NO_MASTER', 27)]`。NO_MASTER 代码为 ETF/基金代码，不进入本研究股票 universe。

## 研究决策

不生成行业当前快照回填 overlay，不把非 PIT 行业数据接入研究；保留原始 `industry_valid` 语义。退市样本按冻结规则排除并在最终报告披露 survivorship bias。下一步转向日线异常、公司行动和筹码状态迁移核验。
