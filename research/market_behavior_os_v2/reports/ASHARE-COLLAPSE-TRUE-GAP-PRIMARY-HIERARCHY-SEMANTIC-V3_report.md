# A-share Collapse True-Gap Primary Hierarchy Semantic V3

## Scope

Outcome-blind semantic refinement only. The true-gap primitive remains
`High_t < Low_t-1`, interval `[High_t, Low_t-1]`. No return, PnL, entry,
strategy replay, or repository 2024+ security data was opened.

## Frozen hierarchy

The original impulsive collapse leg ends at the earliest >=30% peak-drawdown
candidate trough whose next 10 completed sessions contain neither a low more
than 5% below the trough nor a new MAJOR true gap. Gaps after that end remain
visible as `POST_COLLAPSE_LOCAL_GAP` but cannot become primary. MINOR gaps also
remain in the ledger but cannot become primary.

Active repair requires at least 10 completed sessions, a prior run of five
completed sessions with `High < L`, no full resolution, and a minute return
from below to `L`. Age <=60 is CORE, 61--90 BOUNDARY, and >90 STALE. These are
semantic memory bands, not alpha parameters.

## Population

- True gaps retained: 67,970
- In original impulsive collapse legs: 31,914
- In-leg MAJOR / SECONDARY / MINOR: 8,811 / 8,007 / 15,096
- Post-collapse local gaps: 35,838
- Unsegmented gaps retained but primary-ineligible: 218
- CORE / BOUNDARY candidates: 3,822 / 497
- STALE / MINOR / persistence / no-primary rejects: 1,620 / 4,673 / 4,680 / 34,738

## Frozen 30-chart regression

Positive references surviving as CORE/BOUNDARY: 7/9.
Known negative references rejected: 13/13.
Positive-reference rule failures are: TG2-010=REJECTED_INSUFFICIENT_PERSISTENCE; TG2-022=REJECTED_POST_COLLAPSE_LOCAL. They were not forced to
pass; each follows the preregistered segmentation/persistence rule.

TG2-010: `REJECTED_INSUFFICIENT_PERSISTENCE`; TG2-015: `REJECTED_POST_COLLAPSE_LOCAL`;
TG2-018: `REJECTED_STALE`; TG2-024: `CORE_CANDIDATE`.

## New blind pilot

Exactly 20 new outcome-blind charts were generated:
14 CORE, 6 BOUNDARY, 13 Main,
and 7 ChiNext. Every chart ends at the semantic first-return
marker and contains no post-event bars. Human review remains mandatory.

## Verdict

`TRUE_GAP_PRIMARY_HIERARCHY_PARTIALLY_ALIGNED`

Implementation invariants pass, but alignment cannot be declared before the
new 20-chart human review. No outcome discovery is authorized here.
