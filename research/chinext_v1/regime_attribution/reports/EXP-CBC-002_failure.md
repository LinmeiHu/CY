# EXP-CBC-002 invalid execution record

EXP-CBC-002 is permanently invalid because its reused LOYO helpers do not honor
the frozen 2020-2023 discovery-year universe.

The frozen contract requires exactly four omissions: 2020, 2021, 2022, and 2023.
The reused helpers instead emitted eight 2018-2025 omissions. Omitting an absent
year reproduces the full-sample estimate and can create impossible positive counts
above four; the completed output contains such counts. The controlled helper also
retains a fixed 180-row minimum from the prior 399-cycle experiment, making three
of the four actual omitted-year samples non-estimable despite pre-audited sizes of
155, 159, 183, and 163.

The defect was discovered only after CBC-002 wrote outputs and their values were
displayed. Therefore every CBC-002 estimate, gate, decision, report, and artifact
is downstream-invalid and cannot be accepted or cited as scientific evidence.
The invalid files are retained solely for audit provenance.

H-025 remains unresolved under its already-frozen scientific definitions. A
contract-exact continuation requires fresh CBC-003 identity/output paths, LOYO
keys restricted to the four observed discovery years, and an outcome-independent
minimum controlled sample fixed below all four pre-audited omission sizes. No
feature, outcome, weight, control, gate, expected direction, or interpretation
may change.
