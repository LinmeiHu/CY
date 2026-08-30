# EXP-D5D-001 preregistration and engineering audit

H-022 asks whether stock-specific continuation or contemporaneous 399102 movement
carries the already-known H-013 day-5 extreme-winner separation. This is a
component-attribution experiment on an outcome-consumed holding path, not a new
entry predictor or a hold/exit rule.

## Frozen population and alignment

- Exactly 295 accepted EXP-PEL-001 day-5 survivors; 15 fixed extreme winners.
- Fixed-control-complete sample: 284; no missing value is imputed.
- Blocks: EXTENDED 137, HOLDOUT 59, DEVELOPMENT 99.
- Entry execution date and exact fifth held session are mapped through frozen
  exchange calendar SHA `1ccd72b9...`.
- Frozen 399102 anchor SHA `e096e4d5...` supplies all 295 entry-session opens and
  all 295 fifth-session closes; index dates and calendar dates are unique.
- The action-safe accepted stock return is not recomputed or replaced.

## Frozen components

- Stock log return: `log1p(accepted return_5d)`.
- Market log return: `log(399102 day5 close / 399102 entry-session open)`.
- Primary stock-specific excess: stock log return minus market log return.
- Fixed neighbors: entry-beta-adjusted log excess and simple-return excess.
- Exact component additivity reconstructs accepted `return_5d` to maximum
  absolute error `1.11e-16` before any outcome association.

## Timing and interpretation

`AVAILABLE_AT_TIMESTAMP = DAY5_SESSION_15:30_ASIA_SHANGHAI`.

`POTENTIAL_ACTION_TIMESTAMP = NEXT_VALID_SESSION_OR_LATER_ONLY`, but EXP-D5D-001
authorizes no action. Both components are post-entry, survivor-conditioned, and
arithmetically overlap terminal return. No causal or ex-ante claim may follow.

## Frozen identity

- Spec SHA-256: `756b4605ab00d21b6063c646e611b14da68ed32db9b9ffbdec1f0558238975ce`.
- Runner SHA-256: `8a68d68d87b764f214aa0ccf03e5eb9f31ecd932d0ccc925c77d97711c8e908a`.
- No component/outcome association was calculated or inspected before this freeze.
