# ChinNext V1 Phase 6 — Exit Lineage & Holding-Path Audit

Offline-only diagnostic; no replay, NAV, PIT rebuild, or counterfactual returns.

Trade count: 111; generic frozen reasons: 34

## Canonical exit distribution

- MARKET_EXIT_CONFIRMED: 77
- MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE: 34

## Frozen identity

strategy_sha256: dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a
pit_manifest_digest: 8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7
formal_replay_executions: 0
pit_rebuilt: NO
current_survivor_fallback: NO

## Top20 path summary

count: 20
holding_days: {'mean': 31.15, 'median': 33.5, 'p25': 13, 'p75': 34}
MFE: {'mean': 0.948670989272727, 'median': 0.7023181427731816, 'p25': 0.4737308146399055, 'p75': 0.9874476987447698}
MAE: {'mean': -0.02758861767541983, 'median': -0.011144323405618606, 'p25': -0.017073170731707332, 'p75': -0.007185628742515049}
giveback: {'mean': 0.3873911716877901, 'median': 0.34090760041285584, 'p25': 0.08636514505902271, 'p75': 0.44434648698527013}

## Remaining91 path summary

count: 91
holding_days: {'mean': 13.417582417582418, 'median': 10, 'p25': 7, 'p75': 17}
MFE: {'mean': 0.10164319985486901, 'median': 0.06343283582089532, 'p25': 0.028933333333333255, 'p75': 0.12409638554216862}
MAE: {'mean': -0.06820807574390668, 'median': -0.05841924398625431, 'p25': -0.10098039215686272, 'p75': -0.025936599423631246}
giveback: {'mean': 0.13069755943531045, 'median': 0.11413099784808092, 'p25': 0.08262516070278347, 'p75': 0.1613056589275613}

## Exit implementation evidence

Individual: `own_exit_signal` (MA30, two consecutive closes below MA30) in strategy/chinext_v1_exploratory.py:275-283; replay emits INDIVIDUAL_EXIT_SIGNAL at run_chinext_v1_smoke.py:824.
Market: `market_gate_state` (MA20, two consecutive closes below MA20; emergency flag) in strategy/chinext_v1_exploratory.py:289-307; replay clears desired set at run_chinext_v1_smoke.py:806-818.
Set-change removal is the desired-set transition (previous minus desired) on the same frozen signal date; no separate forced-exit retry event exists in this ledger.

## Market / individual / set-change roles

market exits: 77 (winners=37, losers=40, neutral=0); individual-confirmed-only canonical exits: 0; set-change-only canonical exits: 0; multiple-condition exits: 34.
The 34 generic episodes all have both individual and set-removal evidence on the frozen signal date, so they are not arbitrarily assigned to one source.

## Early loser audit

loser_count: 62
loser_holding_days: {'mean': 9.96774193548387, 'median': 9.0, 'p25': 7, 'p75': 12}
early_loser_thresholds: {"day10": {"mae_le_0.03pct": {"count": 6, "denominator": 24, "proportion": 0.25}, "mae_le_0.05pct": {"count": 11, "denominator": 24, "proportion": 0.4583333333333333}, "mae_le_0.08pct": {"count": 19, "denominator": 24, "proportion": 0.7916666666666666}}, "day20": {"mae_le_0.03pct": {"count": 1, "denominator": 3, "proportion": 0.3333333333333333}, "mae_le_0.05pct": {"count": 1, "denominator": 3, "proportion": 0.3333333333333333}, "mae_le_0.08pct": {"count": 2, "denominator": 3, "proportion": 0.6666666666666666}}, "day5": {"mae_le_0.03pct": {"count": 12, "denominator": 52, "proportion": 0.23076923076923078}, "mae_le_0.05pct": {"count": 21, "denominator": 52, "proportion": 0.40384615384615385}, "mae_le_0.08pct": {"count": 36, "denominator": 52, "proportion": 0.6923076923076923}}}
Thresholds are descriptive only; no stop-loss is introduced.

## Top20 milestones

[{"final_return": 1.247462435463448, "milestones": {"+100pct": {"date": "2024-11-05", "days_from_entry": 24}, "+10pct": {"date": "2024-09-26", "days_from_entry": 1}, "+20pct": {"date": "2024-09-27", "days_from_entry": 2}, "+30pct": {"date": "2024-09-27", "days_from_entry": 2}, "+50pct": {"date": "2024-09-30", "days_from_entry": 3}, "+5pct": {"date": "2024-09-26", "days_from_entry": 1}}, "symbol": "300033.SZ", "trade_id": "300033.SZ-001"}, {"final_return": 0.5362502665873453, "milestones": {"+100pct": null, "+10pct": {"date": "2024-09-27", "days_from_entry": 1}, "+20pct": {"date": "2024-09-30", "days_from_entry": 2}, "+30pct": {"date": "2024-10-08", "days_from_entry": 3}, "+50pct": {"date": "2024-10-23", "days_from_entry": 14}, "+5pct": {"date": "2024-09-26", "days_from_entry": 0}}, "symbol": "300128.SZ", "trade_id": "300128.SZ-001"}, {"final_return": 0.22023205536686066, "milestones": {"+100pct": null, "+10pct": {"date": "2024-09-27", "days_from_entry": 2}, "+20pct": {"date": "2024-09-30", "days_from_entry": 3}, "+30pct": {"date": "2024-09-30", "days_from_entry": 3}, "+50pct": null, "+5pct": {"date": "2024-09-27", "days_from_entry": 2}}, "symbol": "300182.SZ", "trade_id": "300182.SZ-001"}, {"final_return": 0.5177251096184149, "milestones": {"+100pct": null, "+10pct": {"date": "2024-09-27", "days_from_entry": 2}, "+20pct": {"date": "2024-09-30", "days_from_entry": 3}, "+30pct": {"date": "2024-09-30", "days_from_entry": 3}, "+50pct": {"date": "2024-10-08", "days_from_entry": 4}, "+5pct": {"date": "2024-09-27", "days_from_entry": 2}}, "symbol": "300324.SZ", "trade_id": "300324.SZ-001"}, {"final_return": 0.8856460904365097, "milestones": {"+100pct": {"date": "2024-10-16", "days_from_entry": 10}, "+10pct": {"date": "2024-09-27", "days_from_entry": 2}, "+20pct": {"date": "2024-09-30", "days_from_entry": 3}, "+30pct": {"date": "2024-09-30", "days_from_entry": 3}, "+50pct": {"date": "2024-10-08", "days_from_entry": 4}, "+5pct": {"date": "2024-09-26", "days_from_entry": 1}}, "symbol": "300348.SZ", "trade_id": "300348.SZ-001"}, {"final_return": 2.2669621966113853, "milestones": {"+100pct": {"date": "2024-10-09", "days_from_entry": 5}, "+10pct": {"date": "2024-09-27", "days_from_entry": 2}, "+20pct": {"date": "2024-09-27", "days_from_entry": 2}, "+30pct": {"date": "2024-09-30", "days_from_entry": 3}, "+50pct": {"date": "2024-09-30", "days_from_entry": 3}, "+5pct": {"date": "2024-09-26", "days_from_entry": 1}}, "symbol": "300377.SZ", "trade_id": "300377.SZ-001"}, {"final_return": 0.20610237640595816, "milestones": {"+100pct": null, "+10pct": {"date": "2024-09-27", "days_from_entry": 2}, "+20pct": {"date": "2024-09-30", "days_from_entry": 3}, "+30pct": {"date": "2024-10-08", "days_from_entry": 4}, "+50pct": {"date": "2024-10-08", "days_from_entry": 4}, "+5pct": {"date": "2024-09-27", "days_from_entry": 2}}, "symbol": "300442.SZ", "trade_id": "300442.SZ-001"}, {"final_return": 0.25154392397363423, "milestones": {"+100pct": null, "+10pct": {"date": "2024-09-27", "days_from_entry": 1}, "+20pct": {"date": "2024-09-30", "days_from_entry": 2}, "+30pct": {"date": "2024-09-30", "days_from_entry": 2}, "+50pct": {"date": "2024-10-08", "days_from_entry": 3}, "+5pct": {"date": "2024-09-27", "days_from_entry": 1}}, "symbol": "300459.SZ", "trade_id": "300459.SZ-001"}, {"final_return": 0.9563400998587125, "milestones": {"+100pct": {"date": "2024-10-18", "days_from_entry": 12}, "+10pct": {"date": "2024-09-26", "days_from_entry": 1}, "+20pct": {"date": "2024-09-27", "days_from_entry": 2}, "+30pct": {"date": "2024-09-27", "days_from_entry": 2}, "+50pct": {"date": "2024-09-30", "days_from_entry": 3}, "+5pct": {"date": "2024-09-26", "days_from_entry": 1}}, "symbol": "300803.SZ", "trade_id": "300803.SZ-001"}, {"final_return": 0.4532266916756712, "milestones": {"+100pct": null, "+10pct": {"date": "2025-02-17", "days_from_entry": 2}, "+20pct": {"date": "2025-02-19", "days_from_entry": 4}, "+30pct": {"date": "2025-03-04", "days_from_entry": 13}, "+50pct": {"date": "2025-03-21", "days_from_entry": 26}, "+5pct": {"date": "2025-02-13", "days_from_entry": 0}}, "symbol": "300779.SZ", "trade_id": "300779.SZ-001"}, {"final_return": 0.34269352956241406, "milestones": {"+100pct": null, "+10pct": {"date": "2025-06-09", "days_from_entry": 2}, "+20pct": {"date": "2025-06-10", "days_from_entry": 3}, "+30pct": {"date": "2025-06-10", "days_from_entry": 3}, "+50pct": {"date": "2025-06-11", "days_from_entry": 4}, "+5pct": {"date": "2025-06-09", "days_from_entry": 2}}, "symbol": "301141.SZ", "trade_id": "301141.SZ-001"}, {"final_return": 0.19052158888553075, "milestones": {"+100pct": null, "+10pct": {"date": "2025-08-13", "days_from_entry": 19}, "+20pct": {"date": "2025-08-25", "days_from_entry": 27}, "+30pct": {"date": "2025-09-01", "days_from_entry": 32}, "+50pct": null, "+5pct": {"date": "2025-07-28", "days_from_entry": 7}}, "symbol": "300357.SZ", "trade_id": "300357.SZ-002"}, {"final_return": 0.4693660282986508, "milestones": {"+100pct": null, "+10pct": {"date": "2025-08-12", "days_from_entry": 34}, "+20pct": {"date": "2025-08-18", "days_from_entry": 38}, "+30pct": {"date": "2025-08-18", "days_from_entry": 38}, "+50pct": {"date": "2025-08-22", "days_from_entry": 42}, "+5pct": {"date": "2025-07-16", "days_from_entry": 15}}, "symbol": "301165.SZ", "trade_id": "301165.SZ-001"}, {"final_return": 0.23697895351636222, "milestones": {"+100pct": null, "+10pct": {"date": "2025-09-01", "days_from_entry": 1}, "+20pct": {"date": "2025-09-05", "days_from_entry": 5}, "+30pct": {"date": "2025-09-12", "days_from_entry": 10}, "+50pct": {"date": "2025-09-26", "days_from_entry": 20}, "+5pct": {"date": "2025-08-29", "days_from_entry": 0}}, "symbol": "300457.SZ", "trade_id": "300457.SZ-001"}, {"final_return": 0.26863354370254067, "milestones": {"+100pct": null, "+10pct": {"date": "2025-09-26", "days_from_entry": 0}, "+20pct": {"date": "2025-09-29", "days_from_entry": 1}, "+30pct": null, "+50pct": null, "+5pct": {"date": "2025-09-26", "days_from_entry": 0}}, "symbol": "300490.SZ", "trade_id": "300490.SZ-001"}, {"final_return": 0.1894477275970783, "milestones": {"+100pct": null, "+10pct": {"date": "2025-09-05", "days_from_entry": 4}, "+20pct": {"date": "2025-09-05", "days_from_entry": 4}, "+30pct": {"date": "2025-09-05", "days_from_entry": 4}, "+50pct": null, "+5pct": {"date": "2025-09-03", "days_from_entry": 2}}, "symbol": "300763.SZ", "trade_id": "300763.SZ-001"}, {"final_return": 0.4026989734923595, "milestones": {"+100pct": null, "+10pct": {"date": "2025-09-01", "days_from_entry": 49}, "+20pct": {"date": "2025-09-23", "days_from_entry": 65}, "+30pct": {"date": "2025-09-24", "days_from_entry": 66}, "+50pct": null, "+5pct": {"date": "2025-08-26", "days_from_entry": 45}}, "symbol": "301093.SZ", "trade_id": "301093.SZ-001"}, {"final_return": 0.6493382854768993, "milestones": {"+100pct": null, "+10pct": {"date": "2025-11-07", "days_from_entry": 0}, "+20pct": {"date": "2025-11-07", "days_from_entry": 0}, "+30pct": {"date": "2025-11-10", "days_from_entry": 1}, "+50pct": {"date": "2025-11-11", "days_from_entry": 2}, "+5pct": {"date": "2025-11-07", "days_from_entry": 0}}, "symbol": "300437.SZ", "trade_id": "300437.SZ-001"}, {"final_return": 0.7808181171091552, "milestones": {"+100pct": null, "+10pct": {"date": "2025-11-07", "days_from_entry": 0}, "+20pct": {"date": "2025-11-11", "days_from_entry": 2}, "+30pct": {"date": "2025-11-13", "days_from_entry": 4}, "+50pct": {"date": "2025-11-13", "days_from_entry": 4}, "+5pct": {"date": "2025-11-07", "days_from_entry": 0}}, "symbol": "300497.SZ", "trade_id": "300497.SZ-001"}, {"final_return": 0.15360835805980702, "milestones": {"+100pct": null, "+10pct": {"date": "2025-11-13", "days_from_entry": 10}, "+20pct": null, "+30pct": null, "+50pct": null, "+5pct": {"date": "2025-11-06", "days_from_entry": 5}}, "symbol": "300938.SZ", "trade_id": "300938.SZ-001"}]

## September 2024 cohort

count: 10
300487.SZ 2024-09-24 -> 2024-10-31 MULTIPLE_EXIT_CONDITIONS_SAME_EPISODE return=0.1081; 300033.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=1.2475; 300128.SZ 2024-09-25 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.5363; 300182.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.2202; 300324.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.5177; 300348.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.8856; 300377.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=2.2670; 300442.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.2061; 300459.SZ 2024-09-25 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.2515; 300803.SZ 2024-09-24 -> 2024-11-19 MARKET_EXIT_CONFIRMED return=0.9563

## Interpretation

Market MA20×2 is the dominant proven portfolio-level exit source (77/111; 18/20 frozen Top20). Generic set-change/individual episodes are classified only when matching frozen events prove the lineage. Metrics are ex-post path diagnostics, not predictive features.

## Phase 7 candidates (not run)

- Individual-exit-disabled control only if separately pre-registered.
- Market-exit-disabled control only if separately pre-registered.
- Winner trailing control only if separately pre-registered.

PRIMARY_EXIT_RESEARCH_PROBLEM: MARKET_EXIT_DOMINATES
EVIDENCE_STRENGTH: MODERATE
