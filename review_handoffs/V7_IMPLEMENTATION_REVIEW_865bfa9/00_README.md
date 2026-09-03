# V7 implementation review handoff

This bundle is a mechanical, evidence-only snapshot of
`ASHARE-TRUE-GAP-V7-OVERHANG-ATTACK-EPISODE-SIMPLE-RULE-DEVELOPMENT-V1`.

- Source range: `df739d01617d1537dcfd395ac040ce24844262f6` → `865bfa9ffb9e281438e10a60ca7f57dd3945658e`.
- Source branch at handoff creation: `research/ashare-ultrashort-v1`.
- Handoff branch: `handoff/v7-implementation-review-865bfa9`.
- The source files in `09_EXACT_SOURCE_SNAPSHOT/` were extracted byte-for-byte with `git show` from the V7 end commit.
- This bundle adds review evidence only. It does not modify V7 code, contracts, tests, report, or result.
- No return analysis, feature computation, model training, strategy replay, or portfolio replay was run to create it.
- No repository data dated 2024 or later was opened.
- No `/Volumes/quant` content, raw market data, Parquet, model, cache, PDF, or image is included.

## Questions for independent review

Use the exact code and data-flow evidence in this bundle to determine, without relying on the report's conclusions:

1. Whether V7 actually implements the intended “clean discontinuity” event identity.
2. Whether `vacuum_score` examines only exact `[L,U]`, and what price corridor around the gap is or is not measured.
3. Whether VAP is normalized by price width, local traded volume, and/or free-float turnover.
4. Whether `overhang_support_ratio` combines economically distinct numerator and denominator concepts.
5. Whether missing or `NaN` values can be interpreted as clean/vacuum or otherwise pass a binding gate.
6. Whether `ATTACK_1` is truly the first post-formation approach, or instead starts from another frozen clock.
7. Whether near-touch behavior before freeze or before attack is represented or ignored.
8. Whether `ATTACK_2` can enter the main L5 strategy and how L6 is constructed.
9. Whether collapse duration and rapid-rise/rapid-fall semantics are binding gates in V7's executable path.
10. Whether formation-period distribution and common market decline are binding admission conditions.
11. Whether the implemented L0–L6 lanes match their stated decomposition.

The bundle intentionally states code facts and traceable locations, not a profitability or correctness verdict.

## Reading order

1. `01_MANIFEST.json`
2. `04_REVIEW_TARGETS.md`
3. `05_DATA_FLOW.md`
4. `06_RULE_BINDING_MATRIX.csv`
5. `07_ATTACK_SEMANTICS.md`
6. `08_VAP_AND_INVENTORY_SEMANTICS.md`
7. `09_EXACT_SOURCE_SNAPSHOT/`
8. `02_V7_FULL_DIFF.patch`
9. `10_SHA256SUMS.txt`

## Scope notes

`IMPLEMENTATION_SELF_CONTAINED_IN_V7_RUNNER: NO`

The V7 runner has one direct repo-local runtime import, whose import closure is included. The frozen V6 population generator and V6 predecessor generator are also included because V7 consumes artifacts they define. V5/V4/V3/V2 generator sources and contracts are retained as provenance closure: V6 validates and audits a V5 artifact, although V6 constructs the active V6 candidate population in its own forward state machine.

The small repository chart-index CSV is visible in the full commit-range diff but is not duplicated in the source snapshot. All external large artifacts referenced by code are deliberately excluded.
