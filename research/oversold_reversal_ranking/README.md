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

V2 freezes the V1 deep carrier and tests immediate entry against one-session delay and one
outcome-blind price-reversal trigger:

```bash
python research/oversold_reversal_ranking/v2_timing.py
```

Its outputs are `reports/v2_timing_results.json` and `reports/V2_TIMING_REPORT.md`; the
pre-broad-run policy freeze is recorded in `v2_timing_methodology.md`.
