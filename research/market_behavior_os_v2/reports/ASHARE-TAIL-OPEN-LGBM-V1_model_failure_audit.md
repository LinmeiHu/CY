# Tail-to-Open ML — Development-only model failure audit

Classification: `MODEL_TAIL_OVERFIT`.

Frozen objective: `regression_l1 (MAE; conditional-median target in raw label_net units)`.

| Profile | OOF Spearman IC | OOF Pearson IC | Top 1% net | Positive-score rows | Positive-score net |
|---|---:|---:|---:|---:|---:|
| shallow | 0.1745 | 0.2916 | -0.361% | 5,867 | -0.919% |
| medium | 0.1757 | 0.3042 | -0.363% | 5,127 | -0.832% |
| moderately_richer | 0.1788 | 0.3048 | -0.346% | 7,968 | -1.269% |

All fold-level train/OOF bucket curves, tail returns, prediction dispersion, leaf-support, label, and feature-overlap diagnostics are retained in the machine-readable artifact. Validation and Final OOS were not read.
