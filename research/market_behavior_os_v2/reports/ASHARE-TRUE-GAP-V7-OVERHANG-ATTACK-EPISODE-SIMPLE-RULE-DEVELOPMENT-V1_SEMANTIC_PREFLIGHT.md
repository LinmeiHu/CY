# ASHARE-TRUE-GAP-V7-OVERHANG-ATTACK-EPISODE-SIMPLE-RULE-DEVELOPMENT-V1 — Semantic preflight

Outcomes opened: **NO**.

## Economic sequence

1. former strong / leader-like stock
2. causal local true-gap cluster forms
3. historical inventory may or may not exist around [L,U]
4. post-gap turnover may preserve or replace that inventory
5. market / board / industry environment repairs or remains weak
6. stock approaches L
7. a distinct attack episode begins
8. the market accepts or rejects price inside the gap
9. causal completed-bar trigger
10. next legal one-minute-open entry
11. current attack reaches U, causally resets, or times out
12. position exits under its frozen policy
13. a later independent attack may create at most one retry signal

## Cause / state / trigger / outcome

- Cause: gap-birth systematic or idiosyncratic shock
- State: surviving overhead inventory proxy, support inventory below L proxy, environment repair, stock relative recovery, base / approach quality, prior attack history
- Trigger: causal completed-bar acceptance inside the current attack
- Outcome: current-attack U success, current-attack failure, timeout

## Chosen causal clocks

- gap_inventory_history: completed QD-004 bars no later than ATTACK_START_TIME for admission-state features
- environment_daily_state: completed sessions strictly before attack date
- minute_attack_state: completed minutes no later than each candidate decision timestamp
- entry: next legal minute open strictly after the trigger bar
- exit: next legal execution after completed failure information
- feature_rule: no feature may use a bar after its own decision timestamp

## Ambiguities retained

- historical volume is not identical to currently surviving inventory
- turnover may replace old holders
- low volume under a locked limit state is not absence of supply
- high attack volume may indicate demand or supply absorption
- a later successful attack must not validate an earlier failed attack
- high-overhang U breakout is a different strategy from gap repair
- old horizontal trading may be support, resistance, or both
- absolute percentage penetration and gap-width penetration differ
