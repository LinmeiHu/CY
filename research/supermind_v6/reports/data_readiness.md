# SuperMind V6 data readiness

Current dataset: `v6-market-data-qmt-v1`  
Current validation: `FAIL`  
Current conclusion: `V6_DATA_READY: NO`

This section supersedes the earlier Eastmoney partial-build record retained below.
No feature, signal, portfolio, performance or parameter experiment was run.

## Limited-window fail-closed execution treatment

The overall V6 acceptance remains `FAIL`; the following treatment does not
weaken it. A separate research-only availability layer now supports a bounded
fail-closed replay for 2025-08-28..2026-08-28:

- 2025-08-27 is excluded as a retention-boundary session; this removes 144
  systematic missing 09:30 keys from the evaluation window.
- The remaining 36,310 expected symbol-sessions contain 31 absent 09:30 bars
  and 785 observed but non-traded 09:30 bars. Both classes are `NO_FILL` in the
  primary policy; 09:30 executable coverage is 35,494/36,310 (97.752685%).
- There are 914 non-traded 14:57 bars. The primary policy does not synthesize a
  tail signal from them and waits for the official daily close path.
- There are 1,084 non-traded 15:00 bars. The primary policy records no close
  fill and retries on the next session.
- A bounded QMT full-minute audit found a later real bar for all 816 unavailable
  09:30 events. Of these, 668 first trade at 09:31; all 31 absent-bar cases first
  trade at 10:31. These are diagnostic sensitivity inputs only, not accepted
  exact SuperMind fills.
- No forward fill, price imputation, or silent substitution is used. Exact
  opening-auction and 09:30 fallback engine semantics remain unresolved.

The tracked audit contract is
`research/supermind_v6/manifests/v6_open_execution_availability.json`; large
availability and QMT diagnostic Parquets remain under the Git-ignored research
data root.

## Current QMT readiness answers

### 1. 是否完整解析了 frozen strategy 的 152 ETF？

是。AST 解析为 152 个唯一代码（87 SH、65 SZ），universe SHA-256 为
`0a647dba2e5ef80088c9ec9c9ebdb889b1744ddb1686d0e20867a9a7059f98c3`。

### 2. 日线数据源是什么？

152 ETF、`000852.SH` 和 `000300.SH` 均来自正在运行的国金 MiniQmt，使用
QMT XtData。每个分区同时保存 `dividend_type=none` 与 `front` 的 OHLC；正式
security master 仍来自上交所和深交所公开列表。

### 3. minute 数据源是什么？

QMT XtData `1m`。研究 artifact 只导出 `09:30`、`14:57`、`15:00` 三个关键
bar，明确标记为 `critical_execution_bars_only`，不是 full-1m dataset。

### 4. 数据覆盖起止日期？

- ETF daily：2005-02-23..2026-08-28。
- ETF critical minute：2025-08-27..2026-08-28（受当前 QMT 客户端/账户
  retention 限制）。
- Entry anchor `000852.SH`：2013-04-01..2026-08-28。
- Benchmark `000300.SH`：以 manifest 的 index coverage 为准，已覆盖到
  2026-08-28。

### 5. 152 ETF 中各有多少有完整覆盖？

- Daily partition：152/152。
- Daily rows：212,679，其中 VALID 212,504。
- Recent critical-minute partition：152/152。
- 从上市日起拥有完整 minute history：8/152；其余 144 只早于 QMT minute
  retention 起点上市，因此 full-history minute 不完整。
- 满足全部 V6 acceptance：0/152，因为 opening auction 与 SuperMind 前复权
  等价性仍未证明，且大多数标的缺早期 minute。

### 6. 哪些 ETF 有 gap？

Daily 缺失 symbol partition 为 0。Critical-minute symbol partition 为 0。
历史 minute 缺口标的 144 只，精确列表在 validation 的
`historical_minute_incomplete_symbols`。可用窗口内 `09:30` 共缺 175 个
symbol-date；`14:57` 与 `15:00` 各缺 0。

### 7. 是否严格 point-in-time？

上市日期 gate 为 PASS：152 个 exchange `list_date` 齐全，VALID 行早于
上市日为 0，未来上市 ETF 不会倒灌历史排名。它仍是 PIT-B：当前 master
不是完整 historical revision archive，QMT 历史响应也不是 PIT-A vendor
vintage。

### 8. list_date/delist_date 来源是什么？

SH 来自上交所 `FUND_LIST`，SZ 来自深交所 ETF fund-list workbook。152 只在
capture snapshot 中均为 listed，`delist_date` 为 null；若未来发现退市或代码
复用，必须加入 dated exchange revision，不能推断。

### 9. turnover 是否确认是人民币成交额？

是。SuperMind `turnover` 映射到 QMT `amount`，normalized 名为 `amount_cny`，
不映射换手率。`amount_cny/(raw_close*volume_raw)` 的 152-symbol 中位数检查
通过约 100 倍关系，验证 ETF `volume_raw` 为 100-share lots、amount 为 CNY。

### 10. daily price 使用什么复权方法？

同时保留 QMT `none` raw OHLC 与 QMT `front` OHLC，并保存
`adj_factor_close_ratio=pre_adj_close/raw_close` 诊断值。

`SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE: UNVERIFIED`

### 11. minute price 使用什么 price basis？

关键分钟 bar 同时保存 QMT `none` 和 QMT `front`，与 daily 使用相同 QMT
请求语义；没有用 daily ratio 合成 minute。

### 12. daily + 14:57 price 是否确认可直接拼接？

对 QMT 可用重叠窗口，内部 basis 检查为 PASS：15:00 raw close 对 daily raw
close 为 0 mismatch，15:00 front close 对 daily front close 也为 0 mismatch。
这只证明 QMT 内部一致，不证明 QMT `front` 等于 SuperMind `fq='pre'`。

### 13. 是否拥有 09:30 open？

部分拥有。可用 minute 窗口内覆盖 36,279/36,454 个预期 symbol-date，
99.519943%；175 个缺口保持缺失。

### 14. 是否拥有真正 opening auction price？

未证明。QMT `09:30` bar open、official daily open 和 opening-auction match 不
自动视为同一事实。

`OPEN_AUCTION_EXACT_REPLICATION: UNVERIFIED`

### 15. 是否拥有 14:57 OPEN？

是，在 QMT minute retention 窗口内覆盖 36,454/36,454，100%。保存和使用的
字段是 `raw_open/pre_adj_open`，不是 14:57 close。

### 16. 是否拥有 official close？

Daily official close 为 152/152。可用 minute 窗口内 final 15:00 bar 为
36,454/36,454，且与 daily close 完全对齐。

### 17. 交易日历来源是什么？

QMT legacy `get_trading_dates('SH')`（新 holiday control 在该国金客户端未
实现），1990-12-19..2026-08-28 共 8,714 个日期；与原 Sina/local calendar
在共同区间逐日一致。

### 18. weekly last trading day 能否可靠判断？

能。日历唯一、递增、覆盖 build end；weekly 边界按显式交易日集合确定，不
按 weekday 猜测。

### 19. 是否存在 duplicate rows？

Daily `(symbol,trade_date)` duplicate = 0；critical minute
`(symbol,qmt_index)` duplicate = 0；universe duplicate = 0。

### 20. 是否有被 forward-filled 的行情？

没有。QMT 获取使用 `fill_data=False`；normalizer 只保留 QMT 原始 key，不
reindex、不补 OHLCV、不补缺失关键 bar。

### 21. 全部数据占用多少空间？

Normalized QMT research dataset 为 27,226,025 bytes（约 25.96 MiB）。它只
包含 full daily 和 critical bars；QMT
专有 1m cache 位于 Windows MiniQmt 数据目录，不计入该 artifact。

### 22. manifest 在哪里？

`research/supermind_v6/manifests/v6_market_data_manifest.json`。Validation 为
`research/supermind_v6/manifests/v6_market_data_validation.json`。

### 23. validation 命令是什么？

```bash
cd /Users/linmei/Documents/CY-supermind-v6
python research/supermind_v6/scripts/finalize_qmt_v6_manifest.py --end-date 20260828
python research/supermind_v6/scripts/validate_qmt_v6_market_data.py
```

### 24. validation 是否通过？

否。Universe、security master、daily、上市日期 gate、turnover/CNY、无
forward-fill、trade calendar、recent critical minute、daily/minute QMT price
basis 均 PASS。失败项是：144-symbol historical-minute coverage、175 个
09:30 bar、opening-auction exact semantics、SuperMind pre-adjustment equivalence。

### 25. 是否达到“可以开始 V6 feature reconstruction”的标准？

否。Daily foundation 已完整，最近一年 critical execution layer 可做 bounded
QA，但在上述四个 fail-closed blockers 解决前不能正式进入 V6 feature
reconstruction 或策略对比实验。

## Current sample audit

2026-08-28 的确定性样本均同时拥有 daily、09:30、14:57 和 final close：

| symbol | raw close | volume_raw | amount_cny | 09:30 open | 14:57 open | final close |
|---|---:|---:|---:|---:|---:|---:|
| 510300.SH | 4.679 | 6,046,933 | 2,835,120,646 | 4.684 | 4.677 | 4.679 |
| 588000.SH | 1.756 | 27,537,424 | 4,903,064,585 | 1.781 | 1.755 | 1.756 |
| 512880.SH | 1.104 | 17,388,624 | 1,919,491,996 | 1.105 | 1.104 | 1.104 |
| 159915.SZ | 3.443 | 14,854,271 | 5,179,583,482 | 3.478 | 3.445 | 3.443 |
| 159516.SZ | 0.721 | 46,646,383 | 3,415,026,039 | 0.739 | 0.721 | 0.721 |

Corporate-action candidate `510300.SH` shows the QMT front/raw ratio changing
from 0.9746861494 on 2026-01-16 to 1.0 on 2026-01-19. This is evidence that the
adjusted series changes across an event; it is not SuperMind-equivalence proof.

## Current blockers

1. QMT only supplied about one year of 1m history; 144 ETF histories begin before
   the returned minute range.
2. The available minute window contains 175 missing `09:30` bar keys.
3. No direct evidence proves QMT `09:30` bar open is the exact opening-auction
   match used by SuperMind `open_auction()`.
4. No SuperMind reference artifact proves QMT `front` equals `fq='pre'` across ETF
   corporate actions.

`V6_DATA_READY: NO`

---

## Prior Eastmoney partial-build record (superseded)

Build snapshot: `v6-md-20260828T171816+0800`

Validation result: `FAIL`

The useful subsets are frozen and auditable, but the complete V6 foundation is
not ready. No feature panel, signal, portfolio return or parameter experiment was
computed.

## Required questions

### 1. 是否完整解析了 frozen strategy 的 152 ETF？

是。策略 AST 中 `context.pool_raw` 为 152 行、152 个唯一代码；87 SH、65 SZ。
Universe SHA-256 为
`0a647dba2e5ef80088c9ec9c9ebdb889b1744ddb1686d0e20867a9a7059f98c3`。

### 2. 日线数据源是什么？

ETF 候选日线为 Eastmoney ETF kline endpoint，逐 symbol 保存 raw 与 provider
qfq 原响应、请求参数、capture time 和 SHA-256；当前仅 18 只成功。`000852.SH`
和 `000300.SH` 为 Sina index daily 经 AkShare。现有 QD-001/QD-003 仅用于前置
inventory 和交叉核验，没有静默拼入本次 normalized partitions。

### 3. minute 数据源是什么？

没有可接受的历史 ETF 1m 来源。现有 QD-004 是 A 股股票库，对四个 ETF
样本为 0 行；BaoStock 在 VPN 下成功登录，但三个 ETF 的 daily/5m 均为 0 行；
AkShare/Eastmoney 1m 接口文档仅保留近五个交易日，且 bounded probe 失败。

### 4. 数据覆盖起止日期？

- ETF daily physical range: 2005-02-23..2026-08-27。
- `000852.SH`: 2014-10-17..2026-08-27，2,886 行。
- `000300.SH`: 2002-01-04..2026-08-27，5,980 行。
- ETF minute: 无。

### 5. 152 ETF 中各有多少有完整覆盖？

- 有 physical daily partition：18/152。
- 其中所有行均通过当前基础行级 validity：16；`510050.SH` 和 `510880.SH`
  分别有 123/53 个 provider qfq 非正价格行，已 fail closed。
- 134/152 无 partition。
- 达到完整 V6 acceptance（含 SuperMind adjustment equivalence 与 minute）：0/152。

### 6. 哪些 ETF 有 gap？

134 只完全缺失，精确列表在 manifest 的 `symbols_expected - symbols_present`
和 validation 的 `missing_daily_partitions`。缺失集合为：

```text
159141.SZ,159201.SZ,159206.SZ,159207.SZ,159209.SZ,159227.SZ,159235.SZ,
159259.SZ,159263.SZ,159307.SZ,159325.SZ,159326.SZ,159363.SZ,159387.SZ,
159399.SZ,159530.SZ,159562.SZ,159566.SZ,159583.SZ,159593.SZ,159601.SZ,
159611.SZ,159622.SZ,159623.SZ,159625.SZ,159638.SZ,159667.SZ,159680.SZ,
159692.SZ,159697.SZ,159732.SZ,159736.SZ,159755.SZ,159758.SZ,159766.SZ,
159781.SZ,159790.SZ,159796.SZ,159825.SZ,159837.SZ,159851.SZ,159852.SZ,
159859.SZ,159865.SZ,159869.SZ,159870.SZ,159876.SZ,159880.SZ,159883.SZ,
159901.SZ,159905.SZ,159928.SZ,159929.SZ,159938.SZ,159967.SZ,159980.SZ,
159992.SZ,159993.SZ,159997.SZ,159998.SZ,510150.SH,510180.SH,510210.SH,
510300.SH,510720.SH,510810.SH,512010.SH,512040.SH,512070.SH,512200.SH,
512290.SH,512400.SH,512660.SH,512670.SH,512690.SH,512710.SH,512760.SH,
512800.SH,512940.SH,512950.SH,512980.SH,515000.SH,515030.SH,515170.SH,
515180.SH,515210.SH,515220.SH,515230.SH,515300.SH,515400.SH,515450.SH,
515630.SH,515650.SH,515700.SH,515790.SH,515800.SH,515900.SH,515980.SH,
516130.SH,516150.SH,516160.SH,516350.SH,516510.SH,516570.SH,516650.SH,
516820.SH,516970.SH,560050.SH,560080.SH,560280.SH,560570.SH,560710.SH,
560860.SH,561360.SH,561380.SH,561420.SH,561550.SH,561580.SH,561980.SH,
562060.SH,562500.SH,562550.SH,562800.SH,562950.SH,563230.SH,563300.SH,
588000.SH,588020.SH,588220.SH,588460.SH,588790.SH,589070.SH,589680.SH,
589720.SH
```

在 18 个现有 partition 中，provider 相对 exchange calendar 还有 1–2 个
`MISSING_OR_SUSPENDED_UNRESOLVED` session：`159915.SZ(1)`、`510500.SH(2)`、
`512100.SH(1)`、`512170.SH(1)`、`512480.SH(1)`、`512890.SH(1)`；其余 12
只为 0。另有 `510050.SH(123)`、`510880.SH(53)` 个 qfq 非正价格状态。

### 7. 是否严格 point-in-time？

否。152 只的 exchange `list_date` 齐全，validation 证明没有 VALID 行早于
上市日期；daily completed-bar `available_at` 也保守落在次日零点。但是当前
master 是 capture-date current-listed snapshot，未保存完整历史 revision/delist
vintages；Eastmoney/Sina 历史响应也不是 archival PIT-A vendor vintages。

### 8. list_date/delist_date 来源是什么？

- SH：上海证券交易所 `FUND_LIST` public endpoint，87/87。
- SZ：深圳证券交易所 ETF fund-list workbook，65/65。
- 当前 152 只在 capture snapshot 中均为 listed，`delist_date` 为 null。
  这不是历史退市 revision 证据；若代码复用或退市事实出现，必须另建 dated
  exchange snapshots。

### 9. turnover 是否确认是人民币成交额？

对现有 18 个分区，是。normalized `amount_cny` 来自 provider `成交额`；
`amount_cny / (raw_close * volume_raw)` 的 per-symbol 中位数范围为
99.9213..100.1115，验证 native `volume_raw` 是 100-share lots、amount 是 CNY。
SuperMind `turnover` 只映射到 `amount_cny`，绝不映射 `turnover_rate_pct`。

### 10. daily price 使用什么复权方法？

同时保存 raw OHLC 和 Eastmoney provider qfq OHLC，并保存
`adj_factor_close_ratio = pre_adj_close/raw_close` 诊断值。该 ratio 不是官方
公司行为 factor。`510050.SH`/`510880.SH` 已出现 176 个 qfq 非正价格反例。

`SUPERMIND_PRE_ADJUSTMENT_EQUIVALENCE: UNVERIFIED`

### 11. minute price 使用什么 price basis？

无历史 minute 数据，因此无可接受 basis。

### 12. daily + 14:57 price 是否确认可直接拼接？

否。14:57 minute open 缺失，且没有 historical-date adjustment factor。禁止
用 qfq/raw 当前快照 ratio 擅自调整 minute。

### 13. 是否拥有 09:30 open？

否。历史覆盖 0/152。

### 14. 是否拥有真正 opening auction price？

否。覆盖 0/152；daily open 不作替代。

### 15. 是否拥有 14:57 OPEN？

否。历史覆盖 0/152；final close 不作替代。

### 16. 是否拥有 official close？

现有 18 只 ETF 有 daily official close，两个指数也有 daily close；但 134
只 ETF 缺失，且 15:00/final minute close 覆盖为 0。不能满足执行 contract。

### 17. 交易日历来源是什么？

Sina trade-date history 经 AkShare，截断至 2026-08-27，共 8,713 个唯一递增
日期；与 `/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet`
在同一截止日逐日完全一致。

### 18. weekly last trading day 能否可靠判断？

对 calendar 日期集合可以。周边界只按显式交易日集合分组，不按 weekday
猜测；calendar validation 为 PASS。行情覆盖不足仍会阻止策略计算。

### 19. 是否存在 duplicate rows？

normalized daily `(symbol,trade_date)` duplicates = 0；provider raw/qfq date
duplicates = 0；universe duplicate codes = 0。

### 20. 是否有被 forward-filled 的行情？

没有 builder 插入的行。Validator 将 normalized keys 与每个 frozen raw/qfq
响应的 key union 对比，`FORWARD_FILL_INSERTIONS = 0`。缺失 session 保持缺失。

### 21. 全部数据占用多少空间？

`9,623,163 bytes`（约 9.18 MiB），位于 Git-ignored research data 路径。
这只是 partial daily/master/calendar/index snapshot，不含 full minute。

### 22. manifest 在哪里？

`research/supermind_v6/manifests/v6_market_data_manifest.json`。
Validation 详情在
`research/supermind_v6/manifests/v6_market_data_validation.json`。

### 23. validation 命令是什么？

```bash
cd /Users/linmei/Documents/CY-supermind-v6
python research/supermind_v6/scripts/validate_v6_market_data.py
```

### 24. validation 是否通过？

否，`FAIL`。基础通过项：universe、152-row security master、上市日期 gate、
turnover/amount 单位、无 forward-fill、calendar。失败项：134 daily partitions、
`510300.SH` exit anchor、historical minute、opening auction、daily/minute basis、
SuperMind qfq equivalence。

### 25. 是否达到“可以开始 V6 feature reconstruction”的标准？

否。当前数据只可用于 downloader/contract/validator 迭代和 bounded QA；不得
计算 B60、FULL40、MINVOLLOC30、RS、MA signal 或绩效。

## Real sample audit

以下确定性样本满足 5 SH + 5 SZ。全部为 2026-08-27；`volume_raw` 单位为手，
`amount_cny` 为元。09:30、14:57、final-minute 三列均为 missing，不能伪造。

| symbol | raw close | qfq close | volume_raw | amount_cny | 09:30 open | 14:57 open | final minute close |
|---|---:|---:|---:|---:|---|---|---|
| 512880.SH | 1.106 | 1.106 | 24,453,917 | 2,689,721,813 | MISSING | MISSING | MISSING |
| 588200.SH | 1.203 | 1.203 | 32,096,338 | 3,806,059,416 | MISSING | MISSING | MISSING |
| 515880.SH | 0.678 | 0.678 | 54,034,927 | 3,627,662,861 | MISSING | MISSING | MISSING |
| 510500.SH | 7.973 | 7.973 | 4,170,215 | 3,303,724,225 | MISSING | MISSING | MISSING |
| 512890.SH | 1.183 | 1.183 | 9,277,138 | 1,094,747,351 | MISSING | MISSING | MISSING |
| 159915.SZ | 3.494 | 3.494 | 14,990,139 | 5,191,828,279.665 | MISSING | MISSING | MISSING |
| 159516.SZ | 0.743 | 0.743 | 46,675,366 | 3,417,587,305.232 | MISSING | MISSING | MISSING |
| 159995.SZ | 1.181 | 1.181 | 6,851,149 | 796,527,323.948 | MISSING | MISSING | MISSING |
| 159819.SZ | 1.753 | 1.753 | 2,818,163 | 489,402,880.319 | MISSING | MISSING | MISSING |
| 159949.SZ | 1.635 | 1.635 | 8,779,280 | 1,426,128,385.179 | MISSING | MISSING | MISSING |

Additional coverage samples:

- Early-listed `510050.SH`: physical 2005-02-23..2026-08-27; 5,230 rows,
  of which 123 qfq nonpositive rows are `NONFINITE`.
- Late-listed pool symbol `561420.SH`: exchange master list date present but daily
  partition missing.
- Exit anchor `510300.SH`: daily partition missing in this build.
- Entry anchor `000852.SH`: 2026-08-27 close 7,732.945.
- Benchmark `000300.SH`: 2026-08-27 close 4,630.277.

Corporate-action candidate `588200.SH` shows provider ratio changing from
0.3334275 on 2026-07-20 to 1.0 on 2026-07-21. It is a candidate discontinuity,
not official event proof. The 176 nonpositive qfq rows are stronger evidence that
provider qfq cannot be accepted as SuperMind-equivalent without an independent
factor/event reconstruction.

## Blockers

1. Acquire raw daily OHLCV+CNY amount for the missing 134 ETFs and `510300.SH`
   through a stable, immutable source; current Eastmoney path is blocked by the
   local proxy, and BaoStock has no ETF rows even through VPN.
2. Replace/audit provider qfq with a corporate-action factor method that never
   produces false B60/MA/momentum structure and prove SuperMind equivalence.
3. Acquire historical ETF 1m or an explicitly limited critical-bar dataset with
   true 09:30 open, 14:57 open and final close/volume.
4. Acquire true opening-auction match data or retain exact-replication status NO.
5. Prove daily/minute adjusted price-basis consistency at corporate actions.
6. Add dated security-master revisions if any delisting/code-reuse history is in
   scope; the current exchange snapshot is not archival PIT-A.

`V6_DATA_READY: NO`
