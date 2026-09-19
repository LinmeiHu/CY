# First divergence report

No score-chain divergence was found for 2020 or 2021. The frozen no-key NPY arrays were traced to the keyed `transfer_v1/daily` rows and were exactly equal to their `BRANCH_s*` columns. The reconstructed percentile, fixed3, gate and authoritative `SIGNALS.parquet` rows were also exact.

The 2020 fresh common-contract replay completed for S17, S29, S43 and fixed3. Every archived-versus-rebuilt NAV, order, lot fill, inventory, cashflow, lot inventory, inventory event, lot action, lot and planning value matched. There is no 2020 execution divergence.

One first attempt at S17 completed account execution but failed before RESULT write because the borrowed metric helper required an unrelated forward-label file. That output was preserved separately and never reused. The replay now computes return and MaxDD from fresh NAV only; all four arms were rerun in clean namespaces.
