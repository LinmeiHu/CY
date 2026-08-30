# Minute feature ledger

Every attempted minute representation remains recorded. Proposed entries are
not evidence and cannot be promoted before construction and outcome gates.

| ID | Scope | Representation | Role | Outcome access | Result/status | Next decision |
|---|---|---|---|---|---|---|
| MF-PRIOR-001 | signal session | signed 1m path efficiency | demand/path quality | yes, prior H-021 | weak/null component | preserve; no threshold search |
| MF-PRIOR-002 | signal session | fraction of time above full-session VWAP | acceptance | yes, prior H-021 | descriptive rho 0.095, composite failed | preserve; cannot promote alone |
| MF-PRIOR-003 | signal session | 10:00 retention from first-30m high | opening acceptance | yes, prior H-021 | null | preserve |
| MF-PRIOR-004 | signal session | equal-weight three-component acceptance composite | confirmation | yes, prior H-021 | rejected raw/controlled 0.012/-0.009 | exact representation rejected |
| MF-R2-001 | Day -5..Day -1 | downside-excursion and down-volume decay trajectory | supply exhaustion | none | DATA FEASIBILITY PASS | eligible for one outcome-blind composite freeze |
| MF-R2-002 | Day -5..Day -1 | time-below-VWAP and recovery progression | supply exhaustion / acceptance | none | DATA FEASIBILITY PASS | compress against MF-R2-001 and daily-bar state |
| MF-R2-003 | Day -5..Day -1 | late-day strength progression | demand strengthening | none | DATA FEASIBILITY PASS | eligible for one outcome-blind composite freeze |
| MF-R2-004 | Day -5..Day -1 | intraday-volatility and VWAP-deviation contraction | setup quality | none | DATA FEASIBILITY PASS | eligible for one outcome-blind composite freeze |
| MF-R2-005 | Day -5..Day -1 | close/low/high progression | accumulation/distribution proxy | none | DEFERRED | requires action-safe cross-day price coordinate |
| MF-R2-006 | Day -5..Day -1 | objective support penetration/recovery progression | support defense | none | DEFERRED | requires one frozen objective level and action-safe coordinate |

AUDIT-ROSV2-M001 produced 1,995 complete rows and 34 finite preview descriptors.
The strongest raw redundancy is VWAP recovery count versus crossing rate
(`rho=0.9957`), open-close return versus signed efficiency (`0.9838`), and
downside versus total realized volatility (`0.9376`). These pairs cannot be
treated as independent mechanisms.

No proposed row may be combined before outcome-blind coverage, stability, and
redundancy results identify distinct mechanism roles.
