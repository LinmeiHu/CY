# Five Strategy Standalone Final Closure V4

## Result

`TASK_STATUS = COMPLETE`. All five production chains are closed without frozen strategy intermediates:

- OGR: `FULL_END_TO_END_REPRODUCIBLE`
- IFCGR: `END_TO_END_REPRODUCIBLE_WITH_PIT_B`
- MCB: `FULL_END_TO_END_REPRODUCIBLE`
- ATRDR: `FULL_END_TO_END_REPRODUCIBLE`
- SMV6: `LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED`

No frozen strategy was modified and no sealed validation was opened.

## Actual results

OGR rebuilt V13 939, V27 470, V28 411, V28R1 397, and V28R2 370 signals. It produced 355 completed outcomes, accepted 255 trades, and materialized 2,883 board/account NAV rows. Signal, trade, accepted-position, cash, exposure, active-position, and NAV comparisons are exact; the only tolerated lower-layer difference is a V13 density representation delta below `2e-15`.

IFCGR regenerated that full 370-row OGR parent inside the same run, classified 13,338 PIT-B title facts, kept 362 parents and rejected the exact frozen eight. It produced 347 outcomes, accepted 248, and materialized 2,883 NAV rows. Trades, accepted quantities/outlays, cash, positions, and NAV match exactly. The evidence grade remains `PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE`.

MCB rebuilt V53 8,760, V64 2,112, V65 2,383, and V72 1,904 signals, accepted 1,021 trades, and produced 2,397 NAV rows. Its ending NAV is `1.9617491025224512`; all configured identities and values match exactly.

ATRDR's historical interval remains closed: OAI mother 3,433, Fast accepted 550, V27 Bear 1,174, Bull mother 2,877, combined sources 4,036, and accepted 2,119. The registered-input continuation is also closed. For 2024-2025 it regenerates 485 market dates, 151 Fast, 674 Slow, 11 accelerating-Bull, 112 decelerating-Bull, 917 routed trades, 397 accepted trades, and 541 NAV rows. For 2026YTD V1 it regenerates 147 market dates, 15 Fast, 38 Slow candidates (14 mature), 9 accelerating-Bull, 2 decelerating-Bull, 38 routed/accepted trades, and 147 NAV rows. All compared identities and values are exact; the final maximum absolute delta is zero. The first-difference forensic table and exact closure matrix are in `reports/atrdr_market_feature_forensics.csv` and `reports/atrdr_2024_2026_exact_closure.csv`.

SMV6 includes and executes the exact registered strategy bytes with SHA256 `7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`. The frozen callback compatibility run reproduces all 779 source events and all eight compared event fields exactly; `reports/smv6_event_comparison.csv` contains one exact row per event. The separate local execution emitted 1,081 events and 3,260 account rows while applying 100-share lots, 2bp commission, 8bp-per-side slippage, the source's sell-before-buy ordering, available cash, holding state, and the source's 50% minute-volume limit. Minimum cash was `4.513061951322015`, ending NAV was `2795610.471913912`, and hidden leverage was not used. The old fractional, zero-cost shadow NAV first differs on `2013-05-22`, as expected from the execution-contract change; it is not treated as the Gate B authority. Native SuperMind was not run, so platform equivalence is intentionally unverified.

## Production boundary

Installed runtime code is only under `src/`. It has no CY imports, Git-object calls, machine-specific paths, or frozen signal/trade/event/NAV inputs. Exact audited producer files under `original_sources/` are hash evidence and are excluded from the installed package. Golden references are optional comparison inputs and production succeeds without them.

## Commands

```bash
python -m pip install -e standalone/five_strategy_bundle --no-deps
python -m pytest -q standalone/five_strategy_bundle/tests/unit
python -m five_strategy_bundle.reproduce --strategy MCB --input-config /path/mcb-inputs.json --golden-config /path/mcb-golden.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy OGR --input-config /path/ogr-inputs.json --golden-config /path/ogr-golden.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy IFCGR --input-config /path/ifcgr-inputs.json --golden-config /path/ifcgr-golden.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy ATRDR --input-config /path/atrdr-inputs.json --golden-config /path/atrdr-golden.json --output-root /path/output
python -m five_strategy_bundle.reproduce --strategy SMV6 --input-config /path/smv6-inputs.json --golden-config /path/smv6-golden.json --output-root /path/output
```

ATRDR's command returns `FULL_END_TO_END_REPRODUCIBLE` after rebuilding both post-2023 V27 intervals from hash-pinned registered daily inputs. Frozen post-2023 ledgers are never production inputs.

## Split command

```bash
git subtree split --prefix=standalone/five_strategy_bundle -b five-strategy-standalone
```
