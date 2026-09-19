# INTERIM_DIAGNOSTIC_ONLY

- Generated: `2026-09-19T09:41:42.293495+08:00`
- Git: `codex/minute-ret5-multiscale-autonomous-v2` @ `2d6865f25324d5d2d6ac8532d4238af4e2693ed4`
- Training PID: `79238`; live: `True`
- RUN_STATE: `RELATION / 3e-06 / 24064/32000`
- Registered checkpoints covered: **11**; strict CONTROL/RELATION pairs: **5**

> These results did not alter training, formal selection, boundary extensions, or holdout use.

## Available diagnostics

| arm      |         lr |   steps |   Ret20_MSE | economic_metrics_status                                                    |
|:---------|-----------:|--------:|------------:|:---------------------------------------------------------------------------|
| CONTROL  | 0.00001000 |    8000 |  0.01365564 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| CONTROL  | 0.00001000 |   16000 |  0.01393955 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| CONTROL  | 0.00001000 |   32000 |  0.01385954 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| RELATION | 0.00001000 |    8000 |  0.01499459 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| RELATION | 0.00001000 |   16000 |  0.01565088 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| RELATION | 0.00001000 |   32000 |  0.01507717 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| CONTROL  | 0.00000300 |    8000 |  0.01404770 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| CONTROL  | 0.00000300 |   16000 |  0.01406051 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| CONTROL  | 0.00000300 |   32000 |  0.01407468 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| RELATION | 0.00000300 |    8000 |  0.01509573 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |
| RELATION | 0.00000300 |   16000 |  0.01545046 | UNAVAILABLE_NO_PREDICTION_CACHE_CPU_RECOMPUTE_INTERFERED_WITH_MPS_TRAINING |

## Strict paired MSE

|         lr |   steps | metric    |    CONTROL |   RELATION |   RELATION_minus_CONTROL | RELATION_wins   |
|-----------:|--------:|:----------|-----------:|-----------:|-------------------------:|:----------------|
| 0.00000300 |    8000 | Ret20_MSE | 0.01404770 | 0.01509573 |               0.00104803 | False           |
| 0.00000300 |   16000 | Ret20_MSE | 0.01406051 | 0.01545046 |               0.00138994 | False           |
| 0.00001000 |    8000 | Ret20_MSE | 0.01365564 | 0.01499459 |               0.00133895 | False           |
| 0.00001000 |   16000 | Ret20_MSE | 0.01393955 | 0.01565088 |               0.00171133 | False           |
| 0.00001000 |   32000 | Ret20_MSE | 0.01385954 | 0.01507717 |               0.00121762 | False           |

## Interpretation

- RELATION wins Ret20 MSE: **0/5**.
- RankIC, demeaned RankIC, Top10/Top50 economics, and leave-best diagnostics are **UNAVAILABLE** because no checkpoint prediction cache existed.
- A single-thread nice-19 CPU recomputation was stopped without output after main training throughput fell from about 4.0 to 2.1 steps/second. Continuing would violate the no-interference requirement.
- Therefore H1 versus H2 is **INCONCLUSIVE**. The only safe current fact is that RELATION has worse MSE on every available matched checkpoint.
- Complete MSE trajectories have their best point at 8k for 1e-5 CONTROL, 1e-5 RELATION, and 3e-6 CONTROL. Economic 8k->16k->32k behavior cannot be evaluated safely yet.
- Account replay was not run.

## Guardrails

- NO FORMAL SELECTION MADE
- NO GRID MODIFICATION
- NO BOUNDARY EXTENSION TRIGGERED
- CURRENT TRAINING LEFT RUNNING
- 2022/2023/2024-2026 NOT ACCESSED
