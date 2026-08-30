# EXP-CBC-001 invalid execution record

EXP-CBC-001 is permanently invalid because of an implementation-level function
call defect. The frozen runner called `controlled_loyo` without its required
keyword-only `extra_controls` argument and raised `TypeError`.

The failure occurred after an unprinted raw rank packet had been calculated in
memory, but before the controlled estimate, gate decision, output write, or any
result inspection. No estimate appeared in terminal output and all four frozen
output paths were absent after failure.

The spec and runner remain frozen at SHA-256 `e919e3b8...` and `ecb68f64...`.
H-025 remains scientifically unresolved. A valid continuation requires a fresh
experiment identity, fresh output paths, and the identical scientific contract;
the only permitted correction is passing the explicit empty
`extra_controls=()` argument to the already-intended controlled estimator.
