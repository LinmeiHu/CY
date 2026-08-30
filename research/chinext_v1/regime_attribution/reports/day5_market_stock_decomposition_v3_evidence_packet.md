# EXP-D5D-003 structured evidence packet

## Question

Does stock-specific continuation, rather than contemporaneous 399102 movement, carry the already-known H-013 day-5 extreme-winner separation?

## Integrity

- Population/control complete: `295` / `284`.
- Component reconstruction error: `1.11e-16`.
- Timing: `DAY5_SESSION_15:30_ASIA_SHANGHAI`; action no earlier than `NEXT_VALID_SESSION_OR_LATER_ONLY; EXPLANATORY_TEST_AUTHORIZES_NO_ACTION`.

## Evidence

- Stock-specific raw/controlled: `0.223` / `0.283`.
- Market raw/controlled: `0.190` / `0.159`.
- Beta-adjusted raw/controlled: `0.055` / `0.132`.
- Decision: `REFINE` / `STOCK_SPECIFIC_COMPONENT_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION`.

## Boundary

No threshold, alternate landmark, hold/exit policy, entry filter, replay, or V1 modification was tested.

The HOLDOUT block has no endpoint variation; this is recorded as a failed temporal gate, not imputed or omitted evidence.
