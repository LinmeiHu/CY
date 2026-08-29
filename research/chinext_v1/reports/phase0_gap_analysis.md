# ChinNext V1 Phase 0 gap analysis

## Acceptance and evidence boundary

- Repository: `/Users/linmei/Documents/CY-supermind-v6`
- Branch: `research/chinext-v1`
- Accepted HEAD: `30e9bad169`
- Frozen source SHA256: `7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`
- Frozen source: Git tracked, 2677 lines, unmodified
- Phase: environment validation and design only; no strategy, optimization, or
  full-market backtest

Evidence abbreviations:

- `SRC`: frozen strategy, with line references.
- `V6-AUDIT`: `research/supermind_v6/reports/phase0_strategy_semantics_audit.md`.
- `REG`: `configs/data_asset_registry.json`.
- `CURR`: `research/supermind_v6/manifests/chinext_current_survivor_universe.json`.
- `CY006-SCHEMA`: read-only Parquet schema inspection of the registered CY-006
  2018 partition during Phase 0.

Only the four required status values are used below.

| Area | ETF V6 behavior | ChinNext requirement | Status | Evidence | Phase |
|---|---|---|---|---|---|
| Frozen source identity | One tracked 2677-line source file | Freeze path and SHA; never modify it | VERIFIED | `shasum -a 256`, `wc -l`, `git ls-files`, and empty path-specific status | Phase 0 |
| Ranking provenance | Original V6 `asset_balanced` unavailable; actual V5-style 20/60/120 RS fallback | Preserve the provenance statement; do not guess the missing source | VERIFIED | SRC 50-53, 1745-1816 | Phase 0 |
| Market entry role | CSI1000 MA15 controls new entry only | `399102.SZ` MA20 controls new entry only | NEEDS_CHANGE | SRC 90-96, 690-847, 1999-2036 | Phase 1 after anchor validation |
| Market exit role | HS300 ETF MA20 provides portfolio-level exit | Separate config role using `399102.SZ` | NEEDS_CHANGE | SRC 90-96, 690-847 | Phase 1 after anchor validation |
| Market anchor availability | `000852.SH` and `510300.SH` are source anchors | Prove `399102.SZ` symbol, history, availability, and adjustment | UNRESOLVED | No `399102` registered/local research evidence found; REG only lists `sz399006` in the inspected index asset | Phase 1 data gate |
| Normal risk-off | Weekly unbuffered HS300 ETF close below MA20 | Two consecutive `399102.SZ` closes below MA20 | NEEDS_CHANGE | SRC 735-812; requested V1 hypothesis | Phase 1 unit design |
| Emergency risk-off | Daily close below MA20 × 0.98 | Daily close below MA20 × 0.96 | NEEDS_CHANGE | SRC 755-812; requested V1 hypothesis | Phase 1 unit design |
| B60 | `C_t` strictly exceeds prior 60 closes | Preserve B60 | VERIFIED | SRC 1690-1703 | Baseline fixture |
| Candidate own MA | ETF `Close_t > MA20_t` | Preserve `Close_t > MA20_t` | VERIFIED | SRC 1705-1710 | Baseline fixture |
| FULL40 window | Prior 40 closes, signal day excluded | Preserve 40-day exclusion | VERIFIED | SRC 1451-1462 | Baseline fixture |
| FULL40 thresholds | width 0.125, dispersion 0.05, efficiency 0.40, vol ratio 0.90 | 0.20, 0.08, 0.45, 0.85 | NEEDS_CHANGE | SRC 106-109, 1464-1543 | Phase 1 unit design; no optimization |
| MINVOL location | Prior 30 days; signal-day volume excluded; location ≤ 0.50 | Preserve and add ratio gate | VERIFIED | SRC 1546-1687 | Baseline fixture |
| Minimum-volume ratio | Calculated for diagnostics but not used in `passed` | Require `minimum_volume_ratio <= 0.70` candidate | NEEDS_CHANGE | SRC 1594-1596, 1660-1687 | Phase 1 unit design |
| Breakout volume | Not an entry gate | Define signal-day/prior-20 ratio, threshold 1.20, OFF/SHADOW/HARD; first round SHADOW | NEEDS_CHANGE | No source implementation; requested V1 hypothesis | Phase 1 shadow field only |
| RS horizons | Cross-sectional 20/60/120 returns | Preserve horizons | VERIFIED | SRC 1749-1816 | Baseline fixture |
| RS weighting | Equal mean of r20/r60/r120 | 20%/50%/30% | NEEDS_CHANGE | SRC 1813-1816 | Phase 1 unit design |
| RS cross-section | Rank over all eligible names, not only breakouts | Rank over full PIT eligible ChiNext universe | VERIFIED | SRC 1797-1816, 2080-2090 | Baseline fixture after universe gate |
| Maximum holdings | 5 | 10 | NEEDS_CHANGE | SRC 98, 2028-2043 | Phase 1 unit design |
| Position cap | `min(50%, 1/N)` | `min(10%, 1/N)` | NEEDS_CHANGE | SRC 100-103, 526-536 | Phase 1 unit design |
| Cash with fewer names | CAP50 can retain cash only when N=1 | 10% cap deliberately retains cash whenever N<10 | NEEDS_CHANGE | SRC 526-536; requested V1 hypothesis | Phase 1 unit design |
| SET_CHANGE_ONLY | Rebalance only on membership/processed-set change | Preserve | VERIFIED | SRC 539-594, 2500-2554 | Baseline fixture |
| Partial-fill reconciliation | Marks target membership processed without checking filled weight | Reconcile actual shares/weights and explicit order states | NEEDS_CHANGE | SRC 2521-2554; V6-AUDIT sections 6.4 and 9.6 | Phase 1 execution ledger |
| Full-portfolio replacement | No rank replacement | Preserve as `NO_REPLACEMENT` baseline | VERIFIED | SRC 2048-2070 | Baseline fixture |
| Weekly hysteresis | Not present | Candidate: held percentile <0.50, new >0.90, full entry gate, max one/week | NEEDS_CHANGE | Requested V1 hypothesis | Design only; not Phase 0 implementation |
| Individual exit baseline | Two consecutive closes below MA40 | Preserve as baseline arm | VERIFIED | SRC 1717-1740 | Baseline fixture |
| Individual MA candidate | None | Two consecutive closes below MA30 | NEEDS_CHANGE | Requested V1 hypothesis | Design only |
| ATR trailing candidate | None | ATR20 / highest official close since entry / 3×ATR trail | NEEDS_CHANGE | Requested V1 hypothesis; adjustment details unresolved separately | Design only |
| Tail signal | 14:57 pseudo-close, sell-only queue | May be considered only with stock T+1, limit and auction gates | NEEDS_CHANGE | SRC 855-916, 1158-1415 | Phase 1 API probe/shadow |
| Tail callback causality | Assumes 14:57 bar open is causally visible; fallback uses 1m close | Prove bar interval, callback phase, and fallback visibility | UNRESOLVED | V6-AUDIT 9.2 | Phase 1 SuperMind probe |
| Closing auction | Queue at 14:57; API order submitted at 15:00 callback | Prove 14:57-15:00 order cutoff, accepted order type, fill and residual state | UNRESOLVED | SRC 1124-1415; no frozen SuperMind run log | Phase 1 SuperMind probe |
| `set_execution('close')` engine rule | Existing audit records official docs: current minute bar close matching | Preserve only as engine behavior, not proof of real fill | VERIFIED | SRC 83-88; V6-AUDIT 9.3 | Phase 0 evidence boundary |
| Know-close/get-close optimism | 15:00 callback submits after queue and engine matches current close | Must not assume one can know 15:00 close and still obtain that close | UNRESOLVED | SRC 1337-1415; V6-AUDIT 9.3 | Phase 1 probe; conservative no-fill until proven |
| Next-open buy | Official-close targets execute at next open/09:30 fallback | Preserve causal t-close to t+1 execution separation | VERIFIED | SRC 2367-2630; V6-AUDIT timeline 3.1 | Baseline fixture |
| Opening auction semantics | `open_auction()` plus 09:30 fallback | Prove callback availability, price, limit behavior and duplication guard in target engine | UNRESOLVED | SRC 2559-2592; V6-AUDIT 9.4 | Phase 1 SuperMind probe |
| Sticky exits | `force_exit_all` and `forced_sells` persist until holdings disappear | Preserve using actual positions and sellable ledger | VERIFIED | SRC 218-221, 503-510, 1825-1987 | Baseline fixture |
| Official-close fallback | Next open catches late crossing or incomplete tail exit | Preserve conservative fallback | VERIFIED | SRC 26-29, 1825-1987, 2399-2494 | Baseline fixture |
| PIT ChiNext universe | ETF list API intersects a fixed pool; static exception fallback is non-PIT | Date-effective ChiNext A-share universe; no current-list history backfill | UNRESOLVED | QD-007 is `DISCOVERY_ONLY` and blocks universe construction (REG 347-385) | Phase 1 data gate |
| Current survivor artifact | No stock equivalent in source V6 | Must never use the 1398-name current artifact as historical universe | VERIFIED | CURR says `NON_PIT_CURRENT_SURVIVOR; most legacy list_date values are absent` | Phase 0 exclusion |
| Listing date | ETF API path supplies active names; static fallback does not | Known listing date and at least 180 exchange sessions | UNRESOLVED | CY006-SCHEMA has no `list_date`; QD-007 is not materialized | Phase 1 data gate |
| ST / `*ST` / risk warning | No explicit ETF rule | Exclude every date-effective risk-warning state | UNRESOLVED | CY006-SCHEMA has `is_st`, but completeness for all risk-warning variants and SuperMind field semantics are not proven | Phase 1 data/API gate |
| Suspension/tradability | V6 relies largely on history/order engine; zero MINVOL fails | Explicit side/window tradability gate and no-fill state | UNRESOLVED | CY006 has `trade_status` and blocked-open fields; no frozen SuperMind stock execution evidence | Phase 1 data/API gate |
| 20-day liquidity | V6 mean turnover at least CNY 20m | Mean amount at least CNY 100m | NEEDS_CHANGE | SRC 164-165, 1421-1444; CY006 has `amount` | Phase 1 unit/data gate |
| Upper/lower limits | No explicit strategy-side check | Use date-effective high/low limit prices and block infeasible fills | UNRESOLVED | REG QD-002/QD-012 provide PIT-B limit fields; SuperMind order/fill semantics not proven | Phase 1 data/API gate |
| T+1 sellability | ETF source does not maintain a sellable-share ledger | Track total vs sellable shares; bought-today shares cannot tail-sell | UNRESOLVED | REG QD-012 states T+1 for supported A shares; no SuperMind portfolio-field probe | Phase 1 execution gate |
| Same-day buy then tail sell | Source can evaluate every current holding at 14:57 | Explicitly exclude day-t buys from day-t sellable inventory | NEEDS_CHANGE | Repository invariant and REG same-bar/T+1 blocks | Phase 1 ledger fixture |
| New-stock special stage | Not represented | Apply date-effective no-limit/changed-limit and tradability rules | UNRESOLVED | No inspected local asset proves complete ChiNext new-listing-stage rules or SuperMind handling | Phase 1 rules/API gate |
| Corporate actions / adjustment | `history(..., fq='pre')`; exact equivalence unresolved | Rebase indicators, entry/highest-close/ATR and share ledgers consistently | UNRESOLVED | SRC history calls; REG CY-006 action fields; V6-AUDIT 8 and 11 | Phase 1 data/API gate |
| `breakout_days` wiring | Context=60 but entry function hardcodes 60 | Make declared parameter operative or remove false configurability | NEEDS_CHANGE | SRC 104, 1690-1703 | Phase 1 unit fixture |
| `box_days` wiring | Context=40 but FULL40 hardcodes 40 | Wire all dependent windows consistently | NEEDS_CHANGE | SRC 105, 1451-1543 | Phase 1 unit fixture |
| `exit_confirm` wiring | Context=2 but exit function hardcodes two observations | Wire it or freeze/name the two-day rule | NEEDS_CHANGE | SRC 129, 1720-1740 | Phase 1 unit fixture |

## Directly preservable structure

B60, own Close>MA20, the causal FULL40/MINVOL window exclusions, full-cross-
section RS construction, SET_CHANGE_ONLY, NO_REPLACEMENT baseline, MA40×2 baseline,
sticky exits, official-close fallback, and official-close-to-next-open separation can
be retained as research structure. Their stock execution still depends on the gates
above.

## Required ChiNext changes

The universe and eligibility contract, both market anchors/regime thresholds,
portfolio size/cap/cash behavior, FULL40 thresholds, minimum-volume ratio gate,
breakout-volume shadow field, RS weights, optional replacement arm, exit candidates,
and stock-specific execution ledger all require new isolated code in a later phase.

## Primary unresolved blockers

1. No activated, date-effective PIT ChiNext security master with a proven listing-
   age and complete risk-warning contract.
2. `399102.SZ` source identity, history, availability, and adjustment are not locally
   proven.
3. SuperMind T+1 sellable inventory, limit/suspension events, auction callbacks,
   partial fills, and new-stock rule behavior lack frozen probe logs.
4. The 15:00 current-bar-close fill is an engine rule but remains an optimistic
   real-execution assumption.
5. Corporate-action equivalence and trailing-state rebasing are not proven.

## Phase 0 conclusion

The design scaffold is complete, but implementation and backtesting are gated.
Phase 1 should close data/API contracts and add small deterministic fixtures only.
It must not start parameter optimization or a full-market backtest.
