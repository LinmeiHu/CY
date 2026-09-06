# Living strategy library

Only actual strategy families belong here. Search-space concepts remain in
`STRATEGY_ARCHETYPE_MAP.md` until the creation threshold is met.

## STRAT-ASHARE-MAIN-CHINEXT-CONFIRMATION-BREAKOUT-V72

| Field | Value |
|---|---|
| REGISTERED NAME | `主创共振突破` |
| ENGLISH NAME | `Main-ChiNext Confirmation Breakout` |
| ALIASES | `V72`; `MCB-V72`; `主创共振`; `双板共振突破`; `跨板确认突破`; `Cross-Board Confirmation Breakout` |
| STRATEGY_ID | `STRAT-ASHARE-MAIN-CHINEXT-CONFIRMATION-BREAKOUT-V72` |
| EXPERIMENT_ID | `ASHARE-BULL-CROSS-BOARD-CONFIRMATION-V72` |
| ARCHETYPE | Long-only bull-diffusion first-pressure breakout quality profile |
| CORE MARKET MECHANISM | A frozen V65 first-pressure break is admitted only when qualified demand is simultaneously visible in Main and ChiNext at the same completed close, distinguishing cross-board bull diffusion from a local board or theme pulse. |
| FULL RULE IDENTITY | Exact frozen V65 candidate identity plus same-close `MAIN >= 1` and `CHINEXT >= 1`; no added numeric threshold |
| DECISION / ENTRY | Cross-board state known at the completed 15:00 signal close; enter first legal daily open strictly afterward and within three exchange sessions |
| EXIT | +15% standing target from executable entry; otherwise H15 then next legal sellable open; no failure stop |
| PORTFOLIO | Main/ChiNext isolated 50/50 sleeves, K30 per sleeve, at most 10 new positions per sleeve/date, no leverage or cross-sleeve transfer |
| COST | 20 bp per side |
| PIT / EXECUTION | Frozen V65 T+1, trading-status, limit, QD-010 corporate-action, lineage and fail-closed semantics |
| FROZEN COMMIT | `60970d7235b9ab7ad8da8d1a7fc5631f015462c9` |
| CONTRACT SHA-256 | `7b76833ee523d0329b4905910962abe0163cc370c3e0d8870a222dc43432cad0` |
| STATUS | Frozen high-confidence quality profile; strict subset of V65 and not an independent return stream |
| SCIENTIFIC WARNING | Do not double-count with V65 or tune on already observed years; 2024-current is non-pristine diagnostic evidence |
| CANONICAL REGISTRY | `STRATEGY_ALIAS_REGISTRY.json` |

## STRAT-ASHARE-ORDERLY-GAP-REPAIR-V28R2

| Field | Value |
|---|---|
| REGISTERED NAME | `有序缺口修复` |
| ENGLISH NAME | `Orderly Gap Repair` |
| ALIASES | `V28R2`; `OGR-V28R2`; `深跌缺口有序修复`; `缺口修复V28R2` |
| STRATEGY_ID | `STRAT-ASHARE-ORDERLY-GAP-REPAIR-V28R2` |
| EXPERIMENT_ID | `ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2` |
| ARCHETYPE | Long-only, event-driven deep-decline true-gap repair |
| CORE MARKET MECHANISM | A mature decline and fresh downward true gap create overhead repair space; buy the first forceful but non-locked and non-crowded demand recapture while price remains below the frozen gap lower edge. |
| FULL RULE IDENTITY | V13 prior-high reversal + V16 D30 + V27 M20/F14/R5 + V28 non-ST/liquidity-trap guard + V28R1 demand-not-locked + V28R2 orderly-amount gate |
| ENTRY | First legal buyable one-minute open strictly after the completed signal close, with at least 5% net headroom to frozen `L` |
| EXIT | `entry + 0.67*(L-entry)` target, otherwise H20 then next legal sellable open; no price stop |
| PORTFOLIO | Main/ChiNext 50/50, K80 per sleeve, 1/80 of sleeve NAV per accepted position, no leverage or cross-sleeve transfer |
| COST | 20 bp per side |
| PIT / EXECUTION | Frozen T+1, limit, suspension, QD-010 corporate-action, lineage and fail-closed semantics |
| CONTRACT SHA-256 | `5f3b681e0b18150a8e6aced9996fb48ed98a87b2f52710547f762fc7bf65cda6` |
| STATUS | Frozen development candidate with later roll-forward diagnostics; not pristine external validation and not the Industry Diffusion + Weekly Low-MAX champion |
| CANONICAL REGISTRY | `STRATEGY_ALIAS_REGISTRY.json` |

## STRAT-CHINEXT-V1

| Field | Value |
|---|---|
| STRATEGY_ID | `STRAT-CHINEXT-V1` |
| ARCHETYPE | Breakout / relative-strength selection |
| CORE MARKET MECHANISM | Hypothesized breakout continuation under favorable broad-market permission; actual economics depend heavily on rare right-tail outcomes |
| MARKET HABITAT HYPOTHESIS | Frozen direction/discovery describe denser opportunity formation without payoff synergy. Formation-depth adverse path localizes to objective-crossing securities after five fixed market controls, but HAB-CHX-FORMDEPTH-001 finds no incremental V1 candidate/cycle habitat transfer. No complete habitat is established. |
| SETUP | Frozen CHINEXT V1 pre-entry architecture |
| CONFIRMATION | Frozen V1 confirmation rules; no Research OS V2 addition |
| TRIGGER | Frozen signal close with causally later T+1 execution |
| VETO | Frozen market, eligibility, trading-state, limit, and capacity rules |
| EXIT LOGIC | Frozen V1 normal/emergency and execution semantics |
| TIME SCALE | Daily setup/trigger; multi-day hold |
| DATA REQUIREMENTS | Registered daily universe, exact market anchor, causal corporate-action and execution facts |
| PIT STATUS | PIT-B exploratory; strict PIT-A unavailable |
| CURRENT EVIDENCE | Reproducible seed; HAB-CHX-001 finds opportunity-density association, finite-vacancy pressure, adverse MAE association, and discovery/MFE opportunity without conversion. All are consumed exploratory evidence, not an overlay. |
| FAILED VARIANTS | Exact trend, rotation, RS/compression, intraday, chip, breadth-conversion, and breakout-lineage variants recorded in seed ledgers |
| VALIDATION STATUS | `VALIDATING`; 2018-2025 outcomes consumed, locked confirmation not used |
| TRANSFER STATUS | Not established outside its original universe/process |

## STRAT-SUPERMIND-V6

| Field | Value |
|---|---|
| STRATEGY_ID | `STRAT-SUPERMIND-V6` |
| ARCHETYPE | Consolidation breakout / relative-strength leadership |
| CORE MARKET MECHANISM | Multiple independent consolidation representations plus breakout and relative-strength selection seek latent supply contraction followed by demand release |
| MARKET HABITAT HYPOTHESIS | Trend-permissive market with orderly consolidation; not independently validated here |
| SETUP | Box width, MA dispersion, directional efficiency, and short/long volatility contraction |
| CONFIRMATION | Breakout/reference and minimum-volume-location roles |
| TRIGGER | Source strategy's daily executable trigger |
| VETO | Source strategy market and eligibility controls |
| EXIT LOGIC | Separate source strategy exits; not migrated into this program |
| TIME SCALE | Daily setup/trigger; swing hold |
| DATA REQUIREMENTS | Daily OHLCV, relative-strength comparison set, market anchors, causal execution facts |
| PIT STATUS | Source methodology inspected; program-level replay/PIT validation not performed |
| CURRENT EVIDENCE | Methodology example showing independent representation roles; not evidence that its thresholds or mechanism transfer |
| FAILED VARIANTS | Not yet reconstructed in this program |
| VALIDATION STATUS | `EXPLORATORY` within this library |
| TRANSFER STATUS | Unknown |

No proposed market-first family yet crosses the preliminary-evidence threshold.
