# EXP-D5D-001 implementation failure

EXP-D5D-001 is permanently `INVALIDATED_AFTER_PARTIAL_IN_MEMORY_EXECUTION`.

The frozen runner completed input, population, calendar, price, action-safe-return,
component-additivity, primary/companion association, control, LOYO, tail,
security, and industry calculations in memory. It then raised `TypeError` while
constructing the temporal gate because `wla.safe_spearman` returns a structured
rank-association packet and the runner compared that packet directly with zero.
The scientifically intended block value is the packet's `rho` field.

No estimate was printed or inspected. No CSV, JSON, report, or evidence packet
was written. Every file in the preregistered input manifest remained exact after
the failure. The frozen spec and runner are preserved unchanged.

H-022 remains unresolved. A valid continuation requires fresh EXP-D5D-002
identity and output paths, with all scientific definitions, population, controls,
gates, expected directions, thresholds, interpretation boundaries, and inputs
inherited unchanged. The sole implementation correction is explicit extraction
of each block packet's `rho` scalar for the already-frozen temporal gate.
