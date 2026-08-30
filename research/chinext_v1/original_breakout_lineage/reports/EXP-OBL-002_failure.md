# EXP-OBL-002 outcome-blind construction-gate failure

EXP-OBL-002 validly executed through in-memory lineage construction without
reading any future outcome. It wrote no artifact because one preregistered
construction gate failed.

Passing evidence:

- all 399 events covered and unique;
- overall lineage counts 92 / 112 / 96 / 99;
- maximum lineage fraction below 45%;
- fixed five-minute/base-neighbor exact assignment agreement 84.46%;
- all four lineages present in every year and block;
- no outcome column read.

Failed evidence:

- the frozen gate required at least two members of every lineage in every year;
- 2018 has only 11 accepted events, split 1 / 4 / 3 / 3;
- every 2019-2025 year has at least seven per lineage, and every temporal block
  has at least 20 per lineage.

Decision: `REFINE_OUTCOME_BLIND_TEMPORAL_FEASIBILITY`. EXP-OBL-002 remains an
unaccepted construction attempt and receives no lineage freeze ID. No outcome
was opened. A fresh EXP-OBL-003 may preserve every feature, score, split, lineage
ID, assignment, timing rule, and other gate while changing only the per-year
requirement from two to one, which tests presence rather than an infeasible
minimum in the 11-event first year.
