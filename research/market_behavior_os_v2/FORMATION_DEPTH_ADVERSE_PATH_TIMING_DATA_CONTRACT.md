# Formation-depth adverse-path timing data contract

Frozen with the timing map before constructing or inspecting mapped future opens
or any response component. It inherits the exact CLOSE-DATA-001 event cohort,
partition identities, PIT/action coordinate, supported-action sequence, resource
guards, deterministic ordering, and no-tolerance semantics.

## Immutable source and coordinate

Use only the six bound pre-2024 CY-006 partitions and the accepted source-role-
correct coordinate builder. For each complete future step, retain raw open, low,
and close plus causal coordinate close. Construct:

- `mapped_open = coordinate_close * (raw_open / raw_close)`;
- `mapped_low = coordinate_close * (raw_low / raw_close)`.

The raw ratio is evaluated first. Required source OHLC, history validity,
coordinate-step validity, and positive finite values must pass. Unknown lineage,
missing steps, invalid actions, or changed hashes fail closed. No adjusted vendor
field, imputation, replacement session/security, raw-minute fallback, post-2023
partition, QD-004, CY-008, strategy artifact, or CY-011 access is allowed.

## Exact cohort and trough selection

Reuse exact t `cross20` membership and the complete next-five-supported-action
response cohort. For h in {1,3,5}, select the earliest exact minimum mapped low
among offsets 1..h. Retain the integer trough offset and the selected mapped open
and low. Closing accepted/rejected/equality counts must exactly match the bound
CLOSE-DATA-001 response counts and exhaust the crossing arm.

Canonical response components are the timing-map formulas. `ADVERSE_h` and
`TERMINAL_h` are bound to the existing response panel by immutable hash; this new
build does not attempt a cross-query binary-float reproduction gate. Component
ledgers contain deterministic count, sum, and mean for combined crossing,
accepted, and rejected arms. Equality retains counts and scalar cases only.

No rounding, clipping, normalization, epsilon, tolerance, equality reassignment,
or cross-query binary rescue is permitted. Scalar reconstruction must verify five
accepted, five rejected, and five equality securities across exact mapped-open,
mapped-low, trough-selection, adverse, terminal, and canonical-component fields.

## Adequacy and prohibited estimates

Retain at least the bound 11,272 closing-topology-complete cells, minimum 196
dates per view/denominator/year, and accepted/rejected response retention >=0.90.
The later economic join requires exactly 6,627 complete fixed-control rows and
minimum 826/cell unless a pre-estimate support audit freezes a scientific retry.

The data build may report only lineage, coordinate validity, integer arm
conservation, finite components, trough-offset counts, support, and scalar exact
reconstruction. It may not estimate formation-depth association, component
direction, timing classification, recovery meaning, executability, habitat,
strategy outcome, or a rule. Two full runs must reproduce every artifact
byte-for-byte.

Use one Python process/thread, 1.5 GiB DuckDB, 3 GiB RSS, 8 GiB headroom, 10 GiB
spill, 20 GiB reads, 20 minutes, and 100 MiB durable output. Passing establishes
only a valid response-component domain, not a market mechanism or usefulness.
