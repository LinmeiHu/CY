# EXP-RTD-002 pre-execution engineering audit

EXP-RTD-002 preserves every H-020 scientific field from EXP-RTD-001. The only
engineering correction is the provenance projection for `index_realized_vol20`.

- Intended source: accepted `pre_entry_transitions.csv` risk control.
- Daily source comparison: complete on 399/399 joined entries; maximum absolute
  difference `1.11e-16`, consistent with serialization precision.
- Daily projection in the corrected runner: the duplicate volatility column is
  not selected.
- Join keys: `trade_id` one-to-one for trades/controls; baseline block plus entry
  signal date to daily trade date many-to-one.
- Source rows/unique keys: trades 399/399, controls 399/399, daily 1,942/1,942.
- Final rows: 399; duplicate columns: zero.
- Final volatility columns: exactly `index_realized_vol20`; missing values: zero.
- PIT applicability: feature available on signal date and first applicable after
  signal but no later than T+1 execution for 399/399 rows.
- Frozen feature-complete/control-complete counts: 387/383.
- False-breakout labels: 213, unchanged. MFE source comparison differs by at most
  `2.22e-16`, consistent with serialization precision.
- Fresh result paths were absent before execution.

No suffix was chosen, no duplicate was silently dropped after merging, and no
population, feature, outcome, control, gate, or interpretation rule changed.
