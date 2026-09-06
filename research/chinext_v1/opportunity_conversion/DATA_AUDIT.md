# Data and Lineage Audit

## Frozen sources

| Source | Intended use | Frozen check |
|---|---|---|
| `regime_attribution/artifacts/yearly_trades.csv` | authoritative completed cycles and causal entry stock features | 399 rows expected; dates, capital, return, P&L, exit lineage inherited |
| `regime_attribution/artifacts/trade_mechanism_attribution.csv` | prior breadth joins and inherited outcome flags | 399 rows expected; must one-to-one match trade IDs |
| `regime_attribution/artifacts/daily_regime_features.parquet` | completed-session market context | SHA256 `5fe1ec...7465bc6`; 1,942 sessions and 93 columns expected |
| independent replay event ledgers | candidate-supply semantics and reconciliation only | must be block-specific and exact; no chained NAV |
| PIT-B daily root | exact CA-adjusted holding and optional post-exit outcome paths | registered source required; no substitute |
| authoritative trading calendar | session offsets and T+1 joins | exact inherited calendar semantics required |

## Checks required before Phase 1 completion

- [x] source paths and SHA256 recorded;
- [x] strategy hash reverified;
- [x] prior report hashes reverified;
- [x] 399 unique trade IDs and one-to-one join confirmed;
- [x] three independent block/date boundaries confirmed;
- [x] entry/exit/P&L/return values reconcile exactly;
- [x] every in-hold symbol/date path resolves without fallback;
- [x] corporate-action-adjusted path matches inherited MFE/MAE exactly;
- [x] exit-session price restriction matches inherited implementation;
- [x] market feature joins are strictly completed-session/PIT compliant;
- [x] candidate-event semantics documented: on each non-market-exit
  evaluation session, final candidates are persisted entry evaluations with
  MINVOL admission passing and a non-missing frozen RS score; aggregate counts
  must equal engine `final_entry_candidate_count` for each block;
- [x] all downstream missingness and optional post-exit end-of-data coverage
  reported, never imputed: entry breadth 387/399, opportunity breadth 81/84,
  candidate fixed-horizon20 1,812/1,821, and post-exit20 398/399.

Phase 1 output manifest:
`artifacts/phase1_conversion_manifest.json`. Its reconciled artifacts contain
399 trade rows and 5,551 eligible in-hold path rows.

## Known epistemic boundary

These data can describe observed opportunities and outcomes. New decision
rules have no untouched evaluation block. Post-entry and post-exit path fields
are outcomes, not eligible entry-time predictors.
