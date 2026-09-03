# V7 attack semantics — code facts

Line references are to the byte-exact source snapshot at commit `865bfa9ffb9e281438e10a60ca7f57dd3945658e`.

`V7` means `research/market_behavior_os_v2/scripts/run_ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1.py`; `V6` means `research/market_behavior_os_v2/scripts/run_ashare_true_gap_causal_cluster_v6_one_shot_discovery.py`.

## Source clock inherited from V6

V7 does not discover `ATTACK_1` by rescanning from gap formation. It reads the frozen V6 candidate ledger in `active_source` (V7 lines 809-826). V6 constructs that source as follows:

- True gap: daily `high < prev_low_raw`; interval `[high, prev_low_raw]` (V6 lines 119-206).
- Primary: lowest unresolved MAJOR/SECONDARY gap when the cluster can freeze (V6 lines 376-390).
- Pre-freeze exact interaction: `_touch` means prior close or current open is below L and current high reaches L; such a primary is rejected at freeze (V6 lines 248-250, 289-291, 389-394).
- Daily first return after freeze uses the same `_touch` predicate (V6 lines 306-340).
- Exact minute first return requires prior minute close/open below the raw threshold and current open/high at or above it, then takes event order 1; the day must have 241 rows (V6 lines 452-507).

## ATTACK_1 start

`ATTACK_1` starts at exactly `event.causal_first_return` (V7 line 1177). Its ID is `<gap_id>|ATTACK_1` (lines 1205-1209).

Therefore the numbering anchor in the executable V7 code is:

- gap formation: **NO**
- primary freeze: **NO**
- frozen V6 causal first return: **YES**

The V7 contract describes the generic start as previous completed minute coordinate close below L and current completed minute coordinate high at or above L, and explicitly says ATTACK_1 is the frozen V6 first return (V7 lines 439-455).

## ATTACK_1 end

`_attack_end` chooses the earliest timestamp, then uses priority within a tie (V7 lines 1091-1134):

1. `SUCCESS`: a minute at or after attack start has `coord_high >= U` (lines 1102-1105).
2. `HARD_STRUCTURAL_RESET`: a causally known lower MAJOR/SECONDARY true gap at its 15:00 formation clock or a lower cluster at its freeze clock (lines 1106-1117, with known clocks prepared at 1153-1161).
3. `BELOW_ZONE_RESET`: close of the second consecutive completed trading session whose coordinate high is below L (lines 1118-1123).
4. `TIME_RESET`: 15:00 at calendar index `attack_start_cal_idx + 10` (lines 1124-1128).
5. If none exists, `RIGHT_CENSORED_AT_FRESHNESS` (lines 1129-1132).

The priority order is encoded by the numeric second tuple element and stated in the frozen contract at lines 445-455.

## ATTACK_2 start and numbering

V7 creates a derived contact table at lines 1061-1073. A derived contact is:

`previous_coord_close < L AND coord_high >= L`

For attack number 2, the code requires:

- ATTACK_1 has an end;
- ATTACK_1 did not end in `SUCCESS`;
- the contact is strictly later than `previous_end`;
- it is the first such derived upward contact in timestamp order;
- its gap age is no more than 90 sessions.

These conditions are at lines 1182-1196. The ID is `<gap_id>|ATTACK_2` (1205-1209). The loop is fixed to `(1, 2)` and a post-build invariant rejects an attack number above two (1182, 1245-1249).

The code does not add a separate “cooldown” beyond the prior attack-end and new-contact requirements. A hard structural reset is an end reason but is not separately listed as a permanent bar on ATTACK_2; the next derived contact after that end remains eligible if age permits.

## Exact touch, wick touch, near touch and corridor touch

- Exact daily V6 touch: prior close/current open below L and current daily high at or above L (V6 248-250).
- Exact V6 minute event: prior minute close/open below raw L and current open/high at or above raw L (V6 452-481).
- V7 later contact: previous completed coordinate close below L and current coordinate high at or above L (V7 1061-1072).
- A wick high crossing L counts because the predicates use `high`; a close above L is not required for the attack start.
- No `near_touch` tolerance exists in the attack-numbering code.
- No price-corridor touch predicate exists in the attack-numbering code. VAP corridor bins are inventory measurements, not touch events.
- Pre-freeze exact touches are evaluated and rejected by the V6 generator. Sub-L near touches that never reach L are not counted by that predicate.
- Price approaches between primary freeze and exact V6 first return are not numbered as attacks unless they satisfy exact touch; the first exact return becomes ATTACK_1.

## Entry within an attack

The candidate path is restricted to `[attack_start_time, attack_end_time]` (V7 1673-1676). `_trigger_index` uses completed closes for Z0/Z25/Z50 and CLOSE/HOLD/RETEST_RECLAIM forms (1472-1494). The candidate fill index is `trigger_idx + 1`, then the first legal buy bar at or after that index (1693-1706). The entry row records a causality audit bit and rejects any same-or-earlier fill (1732, 1748-1749).

This separates wick-based attack start from close-based acceptance/entry translation.

## Current-attack success versus executable U exit

Semantic attack `SUCCESS` uses `coord_high >= U` before reset in `_attack_end` (1102-1105). The executable trade target is separately located by `_target_within_attack` (2013-2027), which requires:

- strictly after entry;
- no later than the current attack end;
- legal sell/T+1 state;
- coordinate high at or above U;
- an execution price not above the observed high.

`EVENTUAL_U_AFTER_FAILED_ATTACK` is computed only as a descriptive flag, and the current outcome row records `later_success_credited_to_earlier_attack=False` (2207-2211, 2235-2242, 2183-2196).

## Retry in L5 and L6

`choose_retry` compares `R0_NO_RETRY` using attack 1 with `R1_ONE_RETRY` using attacks 1 and 2 (3188-3227).

When R1 is selected, `run_hierarchical_walkforward` passes `(1,2)` to the full simple-rule panel, and both attacks independently pass `_admitted`; those selected rows are emitted as `L5_FULL_SIMPLE_RULE` (3330-3335). `L6_ONE_RETRY_INCREMENT` is then the attack-number-2 subset of that L5 frame (3336-3342).

Thus, as a code-flow fact:

- retry can enter L5 when R1 is selected;
- L6 is a diagnostic/incremental subset of L5, not the only place ATTACK_2 appears.

`_admitted` removes an ATTACK_2 whose entry is not strictly later than the latest selected ATTACK_1 exit for that gap (3049-3075). The portfolio also allows only one active symbol and one active `gap_id` (3469-3610).

## Fold containment and leakage guard

`fold_train_test` forms test by attack-start date, collects all test `gap_id` values, and excludes those gaps from train. It also applies the encoded outcome/purge condition `entry_cal_idx + 20 <= boundary_idx - 20` (2339-2359). Every attack of a test gap is therefore excluded from that fold's train frame. Violations raise.

## Focused tests present

The V7 targeted test verifies:

- bounded rule/entry/exit family (test lines 12-19);
- missing simple-rule values fail closed (22-35);
- same-gap exclusion and 20+20 encoded purge behavior (38-53);
- same-session sells are forbidden (56-66);
- replay enforces one active gap and no leverage (69-98).

These are the tests present in the exact snapshot; this inventory does not claim coverage beyond those assertions.
