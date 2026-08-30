# EXP-IBQ-001 execution failure

EXP-IBQ-001 is `INVALID` and has no scientific result.

The frozen runner completed all input-inventory, raw-session, CY-008, PIT,
timestamp, and feature-construction checks. At the first endpoint-count assertion,
before any correlation, partial-rank estimate, LOYO estimate, gate, result print,
or output write, it found 84 accepted `opportunity20` cycles rather than the
incorrectly recorded expected count of 80.

The accepted Phase-5 artifact and report have always defined 84 MFE>=20%
opportunities. The number 80 is the later Phase-6 breadth-control-complete subset,
not the H-021 endpoint population. False breakouts remain 213, overlap is zero,
and the correct disjoint primary count under the unchanged endpoint definitions
is 297.

The frozen EXP-IBQ-001 spec and runner are not repaired. No EXP-IBQ-001 output
artifact exists. A clean re-execution requires EXP-IBQ-002, fresh output paths,
and exact preservation of every scientific feature, endpoint definition,
control, metric, expected direction, falsification test, gate, and interpretation
boundary, changing only the experiment identity and the two count assertions.
