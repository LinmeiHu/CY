# A-share Collapse True-Gap Zone Semantic Fidelity V2

## Scope

Outcome-blind semantic reconstruction only. No return, PnL, executable entry,
target, stop, portfolio or 2024+ repository security path is read or produced.

## Identity

A true downward no-trade gap exists iff `High_t < Low_t-1`. Its exact interval
is `[High_t, Low_t-1]`. All 67,970 true gaps on the
53,028 detected main collapse episodes remain in the ledger.
Future depth deletes none of them.

Importance is descriptive only: 14,538 MAJOR, 16,048
SECONDARY and 37,384 MINOR. Separate gaps are never merged into a fake
continuous no-trade region. The primary semantic layer is the lowest MAJOR or
SECONDARY original-collapse gap.

## Lifecycle and candidates

After at least five completed sessions and five consecutive completed highs below
the true lower boundary, the event
marker is the first minute interaction with the primary true lower boundary
from below while the gap remains unresolved. This creates 4,782
semantic candidates: 1,046 single-gap and 3,736
multi-gap. It is not a trade signal.

## 600250.SH regression

All three true gaps are present: 2022-04-26, 2022-04-27, 2022-04-28. The selected
lowest relevant layer is `600250.SH|2022-04-27` and its first semantic
return is `2022-05-11 10:02:00`. The old V1 price 5.31 does not enter the
2022-04-26 true gap whose lower boundary is the gap-day high, approximately
5.45. A dedicated all-layer diagnostic chart is `/Volumes/quant/CY_quant_research/ashare_collapse_true_gap_zone_semantic_fidelity_v2/charts/diagnostic/TG2-REG-600250.png`.

## Blind pilot

The deterministic pilot contains 30 charts: 20
Main and 10 ChiNext. Every chart ends at the event marker,
contains no post-event bar, and displays every true gap in the collapse leg with
primary/importance/resolution distinctions. Human semantic review remains
required.

## Verdict

`TRUE_GAP_SEMANTICS_PARTIALLY_ALIGNED`

Implementation audits pass, but semantic acceptance requires the frozen 30-chart
human review. No profitability interpretation is permitted. If accepted, the
next independent experiment is
`ASHARE-COLLAPSE-TRUE-GAP-ZONE-OUTCOME-DISCOVERY-V2`.
