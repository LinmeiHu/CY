# EXP-D5D-002 implementation failure

EXP-D5D-002 is permanently `INVALIDATED_AFTER_PARTIAL_IN_MEMORY_EXECUTION`.

The clean runner correctly extracted scalar `rho` fields from structured block
packets, but then raised `DecompositionError` because the HOLDOUT block's rho is
`None`. The accepted 59-trade HOLDOUT survivor sample contains zero extreme
winners and therefore has no endpoint variation; a rank correlation cannot be
estimated.

No estimate was printed or inspected. No CSV, JSON, report, or evidence packet
was written. The full EXP-D5D-002 pre-execution manifest remained exact at the
failure.

The frozen temporal gate requires three estimable block rhos. Its scientifically
consistent handling is to fail that gate when a block is non-estimable, without
imputation, endpoint redefinition, block removal, threshold change, or softened
interpretation. EXP-D5D-003 may perform that exact handling under a fresh identity
and fresh output paths; every other H-022 scientific element remains unchanged.
