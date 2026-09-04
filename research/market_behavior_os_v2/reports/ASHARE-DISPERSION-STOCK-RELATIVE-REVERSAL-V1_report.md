# A-share high-dispersion stock-relative reversal V1

This frozen information screen buys no portfolio and does not modify Strategy A or Industry-Consensus Q1.

Generation gate: **FAIL**.
Validation opened: **False**.
Final classification: **GENERATION_REJECTED_NO_VALIDATION_OR_REPLAY**.

## Frozen mechanism

On an accepted ALL_A/ALL_STATUS high-dispersion close, choose the one lowest same-session stock-minus-leave-one-out-industry return in every industry with at least six eligible names. The screen response starts at t+1 and spans three exact action-aware sessions, net of 20 bps per side.

## Generation

| Dates | Candidate net | Control net | Candidate-control | Opposite net | Candidate-opposite | Median event | Severe candidate/control | Retention |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 130 | -0.567% | -0.239% | -0.328% | -0.262% | -0.305% | -0.495% | 6.30%/3.98% | 97.90% |

## Chronology

| Period | Dates | Candidate net | Candidate-control | Candidate-opposite | Severe candidate/control |
|---|---:|---:|---:|---:|---:|
| generation 2020 | 32 | -0.391% | -0.276% | -0.017% | 5.41%/3.25% |
| generation 2021 | 98 | -0.625% | -0.345% | -0.398% | 6.59%/4.21% |

No next-open portfolio replay, Strategy A combination, post-2023 outcome, or CY-011 field was opened unless explicitly stated above.
