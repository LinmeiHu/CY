# Full-path excursion-order attribution

EXP-EOS-001 tests whether adversity-before-opportunity ordering distinguishes extreme winners from false breakouts after magnitude and path controls. It is descriptive full-path topology, not an entry or exit rule.

## Path audit

- Complete cycles: `399`; extreme winners / false breakouts: `15` / `213`.
- Same-session MFE/MAE ties / zero-duration cycles: `13` / `0`.
- Coordinate failures / post-exit rows / replays / rules tested: `0` / `0` / `0` / `0`.
- Positive normalized order means the first MAE occurs before the first MFE. Chronological first occurrence wins exact magnitude ties in the accepted Phase 1 path construction.

## Preregistered endpoints

All displayed rhos except `actual rho` are oriented so positive supports the endpoint-specific prediction.

| Endpoint | Actual raw rho | Oriented within-year | LOYO + | BH q | Controlled oriented rho | LOYO + | Raw/control/neighbor/falsification |
|---|---:|---:|---:|---:|---:|---:|---|
| extreme_winner | 0.263 | 0.150 | 8/8 | 0.000 | 0.076 | 8/8 | Y/N/Y/Y |
| false_breakout | -0.709 | 0.648 | 8/8 | 0.000 | 0.323 | 8/8 | Y/Y/Y/Y |

## Scientific decision

`REFINE` / `EXCURSION_SEQUENCE_SURVIVES_ONLY_FOR_FALSE_BREAKOUT`.

The model controls ranked MFE, adverse-excursion magnitude, holding duration, fixed pre-entry state, entry year, and canonical exit reason. A surviving result still describes a completed frozen path and cannot establish when or how to trade.

## Strategy candidate

None. No entry, exit, hold, stop, ranking, sizing, or production change was tested or authorized.
