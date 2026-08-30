# MKT-SHOCK-001 preregistration

Status: `FROZEN_BEFORE_CONSTRUCTION_RESULT`.

Frozen spec SHA-256:
`98b4545eb8bf40eb13eb33861bf05a58e32c89e1dbbc4878437ab2276664cd4d`.

MKT-SHOCK-001 is an outcome-blind representation experiment. It uses the frozen
MKT-CLQ-001 and MKT-VOL-001 panels only. No strategy field, future return,
post-decision path, or CY-011 input is permitted.

The experiment explicitly does not reuse the rejected 3/5/10-session raw
liquidity-change family. Instead it constructs a causal, windowless episode from
the minimum of correlation, synchronization, and liquidity-activity historical
percentiles. A primary episode enters at 0.90, remains unresolved until the
score falls below 0.50, and calls the intervening decline `RELIEF`, not price
recovery. Activity in its bottom decile during relief is an activity-dry-up
descriptor, not proven impairment.

Permissive/strict threshold configurations, smooth aggregation shapes, and
10/60-session activity-level neighbors are frozen as robustness definitions.
They cannot replace a failed primary. Representation gates cover causal
coverage, score stability, denominator portability, view-year nondegeneracy,
onset/state agreement, relief-shape stability, and redundancy against frozen
volatility. Because the process is direction-neutral, a panic or reversal claim
is prohibited regardless of the result.
