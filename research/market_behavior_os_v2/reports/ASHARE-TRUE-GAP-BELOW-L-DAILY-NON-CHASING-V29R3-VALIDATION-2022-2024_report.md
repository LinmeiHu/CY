# V29R3 2022–2024 temporal challenge

Verdict: **rejected; do not promote**.

The frozen rule was V28R2 plus one condition: the signal-day stock return could not exceed the same-day conditional observed-row market median by more than 2 percentage points. This was one hash-bound Stage-B run after an immutable outcome-blind Stage-A cohort freeze. No issuer-title input or 2025-or-later row was opened.

| Signal year | Accepted | Mean net | Median net | Win | Severe loss ≤-10% | Mean hold |
|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 23 | 5.374% | 6.134% | 82.609% | 4.348% | 11.826 |
| 2023 | 5 | 1.199% | 2.353% | 60.000% | 0.000% | 11.800 |
| 2024 | 26 | 5.437% | 6.722% | 76.923% | 15.385% | 8.885 |
| **Overall** | **54** | **5.018%** | **5.794%** | **77.778%** | **9.259%** | **10.407** |

The strategy produced only 18 accepted trades per year, so it failed the required greater-than-50 frequency gate. Mean return and holding time passed in isolation, but that is not sufficient.

The more important falsification is relative quality. Frozen V28R2 had 106 accepted trades at 7.238% mean, 86.792% wins, 5.660% severe losses and 9.104 sessions. V29R3 retained 54 trades at only 5.018%, 77.778%, 9.259% and 10.407 sessions. Algebraically subtracting the exact subset from the parent aggregate gives 52 rejected trades at approximately 9.544% mean, 96.154% wins, 1.923% severe losses and 7.75 sessions. Thus the rule removed the stronger half of the parent cohort in this period; signal-day relative strength behaved more like confirmed demand than harmful chasing.

This complement is an aggregate identity calculation, not an unauthorized rejected-row outcome read. It is used to falsify V29R3, not to select a replacement threshold on 2022–2024.

There were 26 accepted signal dates. The largest date contributed 8 trades (14.815%); removing it and rerunning unchanged capacity left 46 trades, 5.038% mean and 11.109 sessions. Concentration was materially lower than in development, but frequency remained far below target.

The market reference is only the unweighted median of eligible rows physically present in each exact registered CY-033 partition. No current-universe or constituent filter was applied. Because QD-007 is unavailable, historical security-master completeness is unverified; this is not a complete-A-share or survivorship-free claim.

Further work must return to data no later than 2021-12-31 and pursue a genuinely different expansion mechanism. The consumed 2022–2024 period may diagnose this failure but may not be used for threshold, cohort, exit or rescue selection.
