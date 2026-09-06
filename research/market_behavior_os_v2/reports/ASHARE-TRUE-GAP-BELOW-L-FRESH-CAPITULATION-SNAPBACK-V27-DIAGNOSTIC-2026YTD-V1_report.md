# ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-V27-DIAGNOSTIC-2026YTD-V1

`V27_2026YTD_FAILS_MEAN_RETURN_AND_TAIL_ROBUSTNESS`

## Frozen scope

This is the true-gap-below-L fresh-capitulation snapback V27, not the market-regime router that also used the number V27. The M20/F14/R5 admission, prior-high reversal, next legal one-minute entry, A67 target, H20 time stop, 40 bp round-trip cost, K80 sleeve capacity and Main/ChiNext 50/50 allocation were not changed for 2026.

Data end is 2026-09-04. Only signals formed no later than 2026-08-03 are included, so every admitted entry has enough calendar tail for H20 and the next legal sell. Later signals are right-censored and excluded before outcomes are measured.

## 2026 result

|Population|Trades|Mean net|Median net|Win|Target hit|Severe10|Mean hold|
|---|---:|---:|---:|---:|---:|---:|---:|
|All executable|42|-1.60%|5.39%|69.05%|66.67%|16.67%|14.33|
|K80 portfolio accepted|41|-0.61%|5.46%|70.73%|68.29%|14.63%|13.10|

There were 43 selected signals across 140 observed signal sessions: 42 executable entries, one rejection for less than 5% net headroom to L, and one overlapping same-symbol trade skipped by portfolio construction. The accepted run rate is about 70.9 trades per 242 sessions, so frequency has not collapsed.

The combined portfolio returned -0.17% through the last exit on 2026-09-02, with -1.70% maximum drawdown and -0.260 Sharpe. The small portfolio loss despite poor trade mean reflects K80 sizing and only 2.26% average capital utilization, not a healthy edge.

## What broke

The median trade and target-hit rate still look good. The mean is destroyed by a small failure mode:

|Accepted subset|Trades|Mean net|Win|Target hit|Severe10|Mean hold|
|---|---:|---:|---:|---:|---:|---:|
|No later daily-lineage break|37|5.82%|78.38%|75.68%|5.41%|10.27|
|Later daily-lineage break|4|-60.07%|0.00%|0.00%|100.00%|39.25|

The four accepted lineage-break losses were 605081.SH -93.38%, 300290.SZ -59.99%, 000004.SZ -45.96%, and 603008.SH -40.95%. A second overlapping 603008.SH event lost -41.96% but was not accepted by the portfolio. This is not a causal filter: “no future lineage break” is known only after entry and must not be converted into a rule.

Target exits worked well: 28 accepted target hits averaged +9.57% in 6.82 sessions. The 13 H20 exits averaged -22.55% and actually took 26.62 sessions on average because suspensions/invalid trading states delayed the next legal sale. The strategy therefore has a negative-skew structural problem: frequent controlled wins finance rare, very large, hard-to-exit losses.

## Board and timing

|Board|Trades|Mean net|Median net|Win|Severe10|
|---|---:|---:|---:|---:|---:|
|Main|29|-1.95%|4.85%|65.52%|13.79%|
|ChiNext|12|2.61%|5.80%|83.33%|16.67%|

July-formed accepted signals were strong: 19 trades averaged +8.09%. March through June contained the tail failures; March -45.96% from one trade, April -8.62% across 11, May -19.77% from one, and June -35.29% across two. This concentration reinforces that one favorable month does not repair the left tail.

## Data and execution disclosure

QMT unadjusted one-minute data covered normal entries, targets and exits. For 000004.SZ and 605081.SH, a fresh QMT download returned positive minute volume but zero OHLC after 2026-04-10. Their target was not reached while the original coordinate lineage remained valid. For the H20 sale, the registered PIT CY-033 session open was used at the first valid session whose open was strictly above the down limit: 000004.SZ on 2026-04-14 at 3.19 and 605081.SH on 2026-06-09 at 0.44. Excluding these two fallback-resolved trades is a data sensitivity only: 39 accepted trades would average +2.93%, still below both the user's +4% objective and V27's historical level.

## Historical comparison

|Period|Accepted|Mean net|Win|Severe10|
|---|---:|---:|---:|---:|
|2017-2023|386|5.27%|84.97%|6.99%|
|2024|80|7.20%|86.25%|10.00%|
|2025|39|2.75%|79.49%|7.69%|
|2026 mature YTD|41|-0.61%|70.73%|14.63%|

## Interpretation

The economic core still appears in ordinary cases: after a fresh capitulation below a real overhead gap, a forceful demand reclaim often carries price back toward L. What V27 does not price is the chance that a distressed company becomes ST, suspends, or crosses a data/corporate-state discontinuity while the position is open. With no loss stop and a sell rule that waits for a fully legal open, this unmodeled hazard dominates the average return.

The 2026 result fails the mean-return objective and the positive portfolio-return check. Any improvement should be developed only on the pre-2022 sample, then locked and replayed on 2022-2026 together; deleting the four observed 2026 lineage-break trades would be look-ahead overfitting.
