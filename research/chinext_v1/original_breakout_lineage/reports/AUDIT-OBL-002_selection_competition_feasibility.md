# AUDIT-OBL-002 — cross-sectional selection-competition feasibility

Decision: `FEASIBLE_WITH_FRESH_OUTCOME_BLIND_EVENT_REPLAYS`.

## Available causal state

The canonical replay engine hash is
`9993b4ab03a437007eb056e530f786bff2e0fc7f90276aaac9db42cfced30797`,
matching the frozen 2018-2021 replay contract. For each completed signal
session it emits:

- `ENTRY_SIGNAL_EVALUATED` with signal date, symbol, price-structure result,
  minimum-volume state, breakout-volume diagnostic, and the PIT RS score;
- `DESIRED_SET_CHANGED` with the previous and desired portfolio sets;
- individual and market exit events needed to interpret portfolio state.

The candidate set is exactly the noncommitted, non-forced-exit symbols passing
price structure and minimum-volume admission and present in the same-session RS
table. Frozen RS ordering and no-replacement capacity semantics are callable
from the unchanged engine.

## Data and block coverage

- 2018-2021: the frozen transient input materializer, historical membership,
  daily panel, calendar, market anchor, and exact replay engine remain available.
- 2022-2023: the bounded holdout membership and baseline replay inputs remain
  available under their consumed diagnostic status.
- 2024-2025: the bounded development membership and baseline replay inputs
  remain available.
- the accepted 399-cycle ledger supplies only projected identity keys for the
  final join; its future outcomes are forbidden during construction.

The autonomous worktree does not contain the original event ledgers, and their
paths point into the source worktree. They were not opened or used.

## Safe construction design

EXP-OBL-008 may run the unchanged engine as isolated subprocesses into fresh
temporary directories. It may read only `event_ledger.jsonl`; generated NAV,
execution, report, and summary files must remain unread and disappear with the
temporary directory. The final accepted population is joined from identity-only
columns of the 399-cycle ledger.

For each accepted signal, the exact neutral structure is:

- `candidate_count`: same-session eligible candidate count;
- `vacancies_before_selection`: maximum holdings minus surviving previous
  desired members;
- `selection_pressure`: candidate count divided by available vacancies;
- `selected_rank` and normalized selected rank in the frozen RS ordering;
- `CONTESTED` if candidates exceed vacancies, otherwise `UNCONTESTED`;
- RS margin to the first excluded candidate only where a contested cutoff
  exists.

The contested/uncontested boundary is the canonical capacity boundary, not a
tuned threshold. No outcome, performance file, age/price filter, V1 change, or
CY-011 access is authorized.
