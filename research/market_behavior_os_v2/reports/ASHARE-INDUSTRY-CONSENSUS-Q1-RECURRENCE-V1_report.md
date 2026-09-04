# Industry-Consensus Q1 h20 recurrence V1

Status: `GENERATION_REJECTED_VALIDATION_UNOPENED`.

The frozen refinement keeps an exact same-industry Q1 event only when at least one earlier accepted Q1 event occurred in the preceding 20 market sessions. Entry, pair, h20 exit, one-half event capital, costs, and execution remain unchanged.

## Generation

Recurrent 45 dates, mean 4.16%, severe 8.89%; isolated 7 dates, mean 0.85%, severe 7.14%; delta 3.31%.
Passed `False`; checks `{'minimum_recurrent_dates': True, 'minimum_isolated_dates': True, 'recurrent_mean_positive': True, 'recurrent_minus_isolated': True, 'severe_not_worse': False, 'positive_each_year': True}`.

This is post-hoc sequential optimization on consumed 2018-2023 history, not OOS or independent confirmation. Post-2023 outcomes and CY-011 were not read. No neighboring recurrence window or rescue rule was tested.
