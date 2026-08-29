# ChinNext V1 exploratory survivor-biased baseline

> **CURRENT SURVIVOR UNIVERSE / NOT POINT-IN-TIME / SURVIVORSHIP BIASED /
> NOT VALID FOR FINAL PERFORMANCE CLAIMS**

## Research boundary

This specification governs only the authorized small-sample smoke replay. It does
not weaken or replace `chinext_pit_universe_contract.md`. The current-survivor
manifest is projected backward solely to obtain a fast alpha/correctness diagnostic.
No result from this route is an unbiased historical performance estimate.

The baseline reads existing Mac assets:

- CY-006 daily stock facts under
  `/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily`;
- the explicit exchange calendar under
  `/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet`;
- the tracked current-survivor manifest;
- one bounded frozen QMT series for exact anchor `399102.SZ`.

No stock history is downloaded and only the selected sample is replayed.

## Frozen configuration

| Area | Baseline |
|---|---|
| Market | exact `399102.SZ`; entry `Close > MA20`; normal exit MA20 x 2; emergency `< MA20 * 0.96` |
| B60 | signal close strictly exceeds prior 60 completed closes |
| Own MA | signal close above MA20 |
| FULL40 | prior 40 closes, width 20%, prior-day MA dispersion 8%, direction efficiency 0.45, vol10/vol60 0.85 |
| MINVOL | t-30..t-1 only; location <= 0.50 and minimum/average volume <= 0.70 |
| Breakout volume | signal volume / prior-20 mean; threshold 1.20; `SHADOW` |
| RS | full basic-eligible sample cross section; 20/60/120 weights 20%/50%/30% |
| Portfolio | max 10; every desired member exactly 10%; remainder cash |
| Replacement | `OFF`; a full portfolio does not rotate on rank |
| Own exit | MA30 below for 2 consecutive completed closes |
| Execution | completed close t signal, later available open fill; no same-close fill |
| T+1 | acquisition date ledger; same-day exit signal logged and deferred |
| Costs | fixed 10 bps per side; 100-share buy lot |

`breakout_days`, `box_days`, and `exit_confirm` are consumed directly from the
configuration. They are not context-only labels hiding hard-coded windows.

## Universe and sampling

Daily basic eligibility requires at least 180 completed valid observations, a
contiguous 121-session price window, a contiguous last-20 amount window averaging
at least RMB 100 million, finite positive prices/volume, `hard_valid`, known daily
non-ST state, known tradability, and nonblocking corporate-action/market-rule facts.
Unknown or invalid facts create gaps; they are never fabricated or forward-filled
into signal windows.

Historical `is_st=true` rows are excluded, but inspected local evidence does not
prove that the field covers every historical risk-warning subtype. The baseline
therefore records this as an incomplete model rather than claiming full filtering.

The sample rule is deterministic and outcome-independent:

1. retain current survivors with at least 180 valid pre-start observations;
2. sort canonical symbols;
3. choose 50 equidistant indices including the endpoints;
4. fail closed per day when a selected symbol lacks required data.

Cross-sectional RS is computed over every basic-eligible symbol within this fixed
sample. It is explicitly not a full-1,398-stock RS.

## Portfolio and execution state

Membership changes only on entry, sticky own exit, or portfolio-level market exit.
Every membership change schedules 10% targets; ordinary price drift does not cause
daily rebalancing. Existing members are never replaced merely because an unheld
symbol has higher RS.

Orders carry their original signal date and reason. A failed open due to invalid
price, hard-invalid data, suspension/tradability, or open-limit blocking remains
pending. An unrelated later set change cannot relabel that pending order. Sells are
processed before buys. Any buy/top-up conservatively resets the minimal position
acquisition date for T+1.

The limit model is `PARTIAL`: CY-006 open-limit block flags, trade status,
tradability, hard validity, and finite positive opens are enforced. No order-book
queue, market impact, or broker-grade lot ledger is claimed.

## Corporate actions

On a valid, visible action date, held shares are multiplied by `share_multiplier`
and cash receives old shares times `cash_per_share`, matching existing repository
research replay semantics. Past closes are rebased by `(price - cash_per_share) /
share_multiplier` and past volume by the multiplier before the new raw observation
is appended. Null action numbers use explicit neutral values (1 for multiplier, 0
for cash/rights); NaN is never interpreted as a real rights event.

An unmodeled blocking or rights action affecting a held symbol aborts the replay.
It is not normalized, clipped, or ignored.

## Output interpretation

The tracked report and summary contain the fixed sample, dates, signal/fill counts,
portfolio diagnostics and hashes of Git-ignored event, execution and NAV ledgers.
Returns include open fills, fixed transaction costs, dividends and end-of-day
marking of open holdings. They remain exploratory survivor-biased small-sample
diagnostics only. No parameter was selected from the observed return.
