# A-share Oversold Reversal Ranking V1

This research lane asks whether drawdown depth, crash speed, and systematic versus
idiosyncratic decline distinguish rebound quality inside the predecessor study's frozen
PIT-safe LOW universe.

Run the study with:

```bash
python research/oversold_reversal_ranking/experiment.py
```

The final run validates registered CY-006 input identities and hashes all nine frozen data
partitions. Outputs are written to `reports/results.json`; the human interpretation is in
`reports/REPORT.md`.
