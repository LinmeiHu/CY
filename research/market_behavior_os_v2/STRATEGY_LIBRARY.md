# Living strategy library

Only actual strategy families belong here. Search-space concepts remain in
`STRATEGY_ARCHETYPE_MAP.md` until the creation threshold is met.

## STRAT-INDUSTRY-CONSENSUS-Q1-V1

| Field | Value |
|---|---|
| STRATEGY_ID | `STRAT-INDUSTRY-CONSENSUS-Q1-V1` |
| ARCHETYPE | Industry-consensus event / concentrated breadth continuation |
| CORE MARKET MECHANISM | A weekly Industry Diffusion signal is more actionable when its two highest-intensity Low-MAX stock candidates come from the same PIT industry, indicating concentrated industry demand rather than diffuse ranking noise |
| MARKET HABITAT HYPOTHESIS | No market-timing habitat is accepted. Reused Absolute Market State was chronologically unstable for this candidate |
| SETUP | Unchanged frozen weekly Industry Diffusion plus prior-20-session Low-MAX Champion Top-10 |
| CONFIRMATION | Exact first two names by higher causal diffusion score, lower Low-MAX, symbol, and both names share the same signal-date PIT industry |
| TRIGGER | Completed weekly signal close; earliest entry at next legal open |
| VETO | No market veto. Do not trade when the exact Q1 pair spans two PIT industries; blocked names are not backfilled |
| EXIT LOGIC | Unchanged h20 due open plus legal-fill and QD-010 pre-effective handling; no stop or early exit |
| CAPITAL / WEIGHTING | Lesser of available cash and one-half pre-entry NAV per event, equal across executable pair, no leverage |
| TIME SCALE | Weekly episodic entry; 20-market-session lifecycle |
| DATA REQUIREMENTS | Registered PIT daily universe, historical PIT industry, causal diffusion score, exact Low-MAX, and accepted A-share execution/corporate-action facts |
| PIT STATUS | PIT-B development replay; post-2023 and CY-011 remain quarantined |
| CURRENT EVIDENCE | Consumed 2018--2023: 33.7037% annualized, 363.7225% total, -18.0468% drawdown, 1.4222 Sharpe; 99 event dates and 180 trades. Mean industry HHI 0.773 and p10 capacity CNY 9.46m are material risks |
| FAILED VARIANTS | Predeclared Top-5 intensity, earlier Q1 lifecycle exits, and Absolute Market State veto; two-industry pairs are not labeled adverse because their full mean remained positive |
| VALIDATION STATUS | `DEVELOPMENT_TARGET_ACHIEVED_NOT_INDEPENDENTLY_VALIDATED`; data-generated post-hoc candidate, exact rule frozen |
| TRANSFER STATUS | Unknown; untouched temporal confirmation required before live use |

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

The Industry-Consensus Q1 event crosses the development-candidate threshold but
not the independent-confirmation threshold.
