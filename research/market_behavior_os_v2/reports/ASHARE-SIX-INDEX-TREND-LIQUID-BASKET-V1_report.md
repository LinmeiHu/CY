# Six-index trend liquid-basket V1

Status: `GENERATION_REJECTED_VALIDATION_UNOPENED`.

At each calendar month-end, the frozen strategy invests only when the median 60-session return across the exact six MKT-TRND-001 indices is positive. It buys the 20 highest prior-20 amount stocks at the next legal open, uses available NAV without leverage, and exits at h20.

## Generation

Status `COMPLETE`.
Annualized -5.05%; total -13.95%; max drawdown -23.57%; Sharpe -0.160; severe trades 16.28%.
Signals 14; completed trades 258; entry coverage 92.14%.

MKT-TRND-001 established neighboring-horizon representation stability for trend direction, not strategy usefulness. This experiment is the first direct usefulness test of that frozen direction representation, and its adverse generation result does not rewrite the earlier representation result or reject the broader trend family. It uses consumed development history, not OOS or independent confirmation. Post-2023 outcomes and CY-011 were not read. No Trend-Breadth or Strategy-A combination was run.
