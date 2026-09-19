# First divergence report

No score-chain divergence was found for 2020 or 2021. The frozen no-key NPY arrays were traced to the keyed `transfer_v1/daily` rows and were exactly equal to their `BRANCH_s*` columns. The reconstructed percentile, fixed3, gate and authoritative `SIGNALS.parquet` rows were also exact.

Fresh account replay is deliberately pending while the primary MPS training process is active. Therefore there is not yet a fresh-versus-archived ledger divergence result. The first confirmed defect is outside execution/NAV: the old stock-level PnL diagnostic counted BUY/SELL cashflows twice.
