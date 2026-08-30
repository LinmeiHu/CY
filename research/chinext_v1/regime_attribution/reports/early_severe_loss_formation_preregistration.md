# EXP-SLF-001 preregistration and coverage audit

H-023 asks when the accepted severe-loss path becomes distinguishable. It does
not test a stop, exit, or alternate strategy.

## Population

- All accepted cycles/severe losses: 399/44.
- Day-3 survivor primary/severe losses: 356/42.
- Day-3 fixed-control-complete: 342.
- Pre-Day3 exits/severe losses: 43/2; retained in the fixed Day-2 neighbor.
- Day-3 blocks are DEVELOPMENT 104/16, EXTENDED 173/20, and HOLDOUT 79/6;
  every block and entry year retains both endpoint levels.

## Exact path and market audit

- 1,744 permitted action-safe stock rows: 399 Day-2, 356 Day-3, and 295 Day-5
  paths, without reading beyond actual observability.
- Five early corporate-action cycles pass exact visible share/cash accounting.
- Accepted Day-5 returns reconstruct to maximum absolute error `2.55e-16`.
- Frozen calendar/index coverage is exact for 399 entry opens, 399 Day-2 closes,
  356 Day-3 closes, and 295 Day-5 closes.
- No post-exit price, counterfactual return, imputation, or strategy replay.

## Frozen design and timing

The sole primary is negative stock-minus-399102 log return through the third held
session. Day-2 all-cycle, Day-5 survivor, and Day-3 entry-beta-adjusted definitions
are fixed neighbors. AVAILABLE_AT is Day-3 15:30 Asia/Shanghai; any potential
action is next valid session or later, but this experiment authorizes no action.

- Spec SHA-256: `592f428988839b59a2f7232bc81088c8fe18ede318d90df406a064ea2b332e5d`.
- Runner SHA-256: `77a738c58cce11da0a9e25b616101621ef5a68b76e3b3029df9adb575a9179d4`.
- No early-path/outcome association was calculated or inspected before freeze.
