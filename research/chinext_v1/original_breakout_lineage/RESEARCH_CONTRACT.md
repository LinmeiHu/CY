# Original-breakout lineage research contract

## 1. Authority and isolation

This is an independent program under
`research/chinext_v1/original_breakout_lineage/`. The historical
`regime_attribution/` program is read-only background. No file in that program is
overwritten.

The dedicated worktree is exclusively owned by this autonomous run. Any
unexpected mutation after experiment preregistration invalidates the active
experiment and is a fail-closed stop.

## 2. Frozen prior conclusions

- H-004 remains `PROSPECTIVE_VALIDATION_PENDING`; no historical breadth
  refinement, threshold, interaction, overlay, or exit use is permitted.
- H-023 keeps its authoritative descriptive/prospective status.
- H-024 and H-025 remain rejected.
- EXP-CBC-001/002 remain invalid engineering attempts; EXP-CBC-003 remains valid
  rejection evidence.
- CY-011 2024-2026 remains locked and is not opened, queried, or used.

## 3. Canonical event and execution

The event definition is inherited from canonical V1 code and cannot be altered
to improve later outcome separation. A completed signal session `t` must satisfy
all canonical eligibility, market, price-structure, MINVOL, and portfolio
selection semantics. A buy formed at `t` can first fill at an executable later
open; never within `t`.

## 4. Outcome-blind construction

During representation and lineage assignment, the process may use only:

- canonical event identity and predeclared population keys;
- daily facts with `available_at <= decision_at`, `hard_valid=true`, and known
  lineage;
- signal-session intraday bars completed no later than the declared timestamp;
- deterministic transformations frozen before outcomes are revealed.

It may not read, merge, select, rank, label, or tune with any post-decision
outcome. Outcome files remain outside the construction runner.

Feature metadata must state `AVAILABLE_AT_TIMESTAMP` and
`POTENTIAL_ACTION_TIMESTAMP`. Missing critical lineage or timing fails closed.

## 5. Lineage freeze

Before an outcome join, persist:

- population and eligibility;
- feature formulas and timing;
- construction/assignment algorithm and fixed number of classes;
- scaling, tie, and missing-data rules;
- lineage IDs with neutral, structural names;
- code and input hashes;
- population counts, key uniqueness, coverage, and assignment stability;
- a unique `LINEAGE_FREEZE_ID`.

The freeze is immutable. A scientific change requires a new experiment and new
freeze identity. Engineering failures remain recorded and cannot be overwritten.

## 6. Outcome reveal

Primary outcomes and gates are preregistered before the reveal. The reveal runner
may join frozen assignments to accepted outcome artifacts one-to-one. It may not
change the taxonomy, thresholds, horizons, controls, or interpretation after
inspection.

The discovery evidence is bounded PIT-B and historically outcome-consumed. CY-011
is not used. A development result cannot become a production claim.

## 7. Falsification

Promising separation is attacked for yearly/LOYO and block stability, industry
and security concentration, market context, size/beta/volatility/liquidity,
right-tail and severe-loss dependence, neighboring definitions, assignment
stability, timing leakage, bar-frequency dependence where intraday, baseline
redundancy, survivorship/censoring, and search-history risk.

## 8. Strategy gate and stop boundary

No canonical V1 modification, entry filter, exit rule, size rule, or overlay is
authorized. A fully surviving mechanism is frozen as a candidate. If genuine
locked validation is justified, set `CANDIDATE_READY_FOR_CY011: YES` and stop for
human authorization before any CY-011 access.
