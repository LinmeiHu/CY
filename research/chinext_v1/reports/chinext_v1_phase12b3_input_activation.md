# ChinNext V1 Phase 12B3 — historical state and causal-input activation

Outcome-blind input audit only. Formal replay, strategy trades, NAV, PIT pilot materialization, and performance metrics are all zero/not run.

## Corporate actions

CY-006 resolves corporate actions through registered `QD-010` normalized distributions and rights inputs. The schema carries event identity, known/announcement/effective dates, share multiplier, cash per share, rights terms, and event type. The runner applies the causal transform `(past_price-cash_per_share)/share_multiplier` and multiplies past volume only after known/effective dates are visible.

QD-010 covers `2017-04-12 .. 2026-08-09`, with 2,384 events in the 2017 warmup window (541 GEM events). The deterministic adapter is implemented with fail-closed handling for future, unknown, duplicate, ambiguous, or rights-participation events.

The frozen overlap (`2018-01-02 .. 2018-12-28`) compares 176,414 rows / 738 symbols. OHLC, volume, amount, symbol normalization, and calendar rates are 100%. QD-010 has 635 GEM event keys while CY-006 marks 634; one cash-dividend key (`302132.SZ`, 2018-05-16) is unmatched. QD-001 lacks event/state fields, so causal rebased-path and event alignment are not fully proven. `CAN_REBASE_QD001_TO_CY006_CAUSAL_SEMANTICS=NO` and warmup readiness remains NO.

## Historical state capture

A manifest records the frozen CY-027 security-master artifact (1,440 exact GEM identities, 41 out-date rows), QD-002 historical state coverage (2018–2021 rows and ST/suspension counts), QD-007 discovery lineage, and QD-010 action lineage. It is explicitly a source capture, not a PIT universe. QD-007 has no authorized 2018–2021 immutable date-effective snapshots; current security master is not used as historical authority. Therefore capture readiness is PARTIAL and no extended-state authorization is issued.

## Decision

- `WARMUP_DATA_TECHNICALLY_READY=NO`
- `HISTORICAL_STATE_CAPTURE_READY=PARTIAL`
- `EXTENDED_STATE_AUTHORIZATION_READY=NO`
- `CAN_PROCEED_TO_PHASE12B4_8DATE_PILOT=NO`
- `CAN_PROCEED_TO_FULL_2018_2021_PIT_MATERIALIZATION=NO`
- `CAN_PROCEED_TO_2018_2021_FROZEN_REPLAY=NO`
- `FORMAL_REPLAY_AUTHORIZED=NO`

No 8-date pilot, 973-date materialization, strategy signal, or strategy outcome was created. QD-007 remains `DISCOVERY_ONLY`; existing Phase 1–12B2 artifacts and frozen strategy are unchanged.
