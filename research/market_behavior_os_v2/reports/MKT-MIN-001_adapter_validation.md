# MKT-MIN-001 vector adapter validation

Decision: `PASS_REQUIRED_SCALE_APPROVED`.

## Semantic equivalence

- Frozen reference sessions: 1,200 across 2018-2023/four views.
- Descriptor fields: 34.
- Maximum optimized/reference difference: `4.99933427988708e-13`.
- Maximum relative opening-window difference: `0.0`.
- Maximum exact five-minute volume/amount conservation difference: `0.0`.
- Causal corporate-action sessions retained: 17.
- Two optimized descriptor hashes: `05b0a96602eb599d06561d1f977f54bb5dbdc23856cb6b952525be83cd4b85a3`.
- Two optimized opening hashes: `0a8d4586494dfa8ffe0c60bc568c99f962ba3a4daca1ae474416db7aa2472342`.

The adapter preserves the separate 09:30 auction, the 09:31..11:30 and
13:01..15:00 continuous grid, raw/unadjusted prices, shares/CNY units, causal
CY-006/CY-008 snapshot binding, Day t 15:30 availability, missing-session
rejection, and no same-bar action.

## Representative full-market scale

- Frozen dates: 2020-02-03 through 2020-02-28, 20 sessions.
- Raw rows: 18,201,043.
- Complete raw sessions: 75,442.
- Final causal descriptor sessions: 71,481.
- Daily market panel rows: 160.
- Minimum cross-section: 753.
- Minimum descriptor coverage: 0.9993297587.
- Opening rows reconciled: 428,886; maximum difference `0.0`.
- Two panel hashes: `ee274ca0c1cb2cd2c6fdd6427d01546aeebecee8e1c1c5c444e3af81a01d390c`.
- Two opening hashes: `9093a928e0bb47d0548e4b8b855e7f30c91837875035d1267efb7598553ab360`.
- Wall time: about eight seconds; peak RSS no more than 2.54 GiB.

## Boundary

This resolves the unsafe rowwise scale blocker. It is engineering validation,
not a representation freeze, mechanism, usefulness result, habitat, or strategy
claim. Required-scale outcome-blind construction remains next.
