# Research frontier

Updated after resume integrity reconciliation on 2026-08-30.

## Latest validated frontier

EXP-P5-001 and EXP-P6-001 answer the MFE-to-realized-return question without a
strategy replay. Breadth is most consistently associated with opportunity
formation: MFE rho is 0.218, MFE>=20% opportunity rho is 0.188, and false-breakout
rho is -0.147, each with 8/8 expected-direction LOYO signs. Terminal realized
return is much weaker at rho 0.073.

Within the fixed MFE>=20% opportunity set, the raw capture/giveback association
does not survive the one preregistered control design. After ranked MFE, holding
duration, time-to-MFE fraction, entry year, and exit-reason controls, capture rho
is -0.028, realized>=20% conversion rho is -0.068, and giveback rho is -0.088.
No endpoint passes its fixed magnitude/direction/LOYO gate. Breadth is therefore a
qualified entry-opportunity descriptor, not a demonstrated capture, exit-giveback,
timing, severe-loss, or exit-rule signal.

## Integrity stop

EXP-P7-003 is invalid. Its compatibility contract permits only the append-extended
registry to differ from legacy Gate C, while the same contract encounters a
non-registry `replay_engine` mismatch:

- legacy frozen hash: `9993b4ab03a437007eb056e530f786bff2e0fc7f90276aaac9db42cfced30797`;
- preregistered/current overlay hash: `3136edf9fc6a8a9f0a8d42487d8703943b0eaacaccdd188be18a6274cb4793e3`.

The current wrapper reproduces this failure before transient materialization.
Existing Phase 7 outputs are preserved but not trusted. Phase 8/9 and
`FINAL_REPORT.md` are downstream-invalid.

During this resume, the previously absent unowned directory
`research/chinext_v1/opportunity_conversion/` appeared with six files. It was
fingerprinted and left untouched. This live loss of workspace exclusivity is an
independent STOP condition.

## Current decision

`REJECT_H012_PIVOT_TO_POSTENTRY_LANDMARK_PATH`.

Breadth historical optimization is closed and H-004 is
`PROSPECTIVE_VALIDATION_PENDING`. EXP-WLA-001 rejects the stock-level
demand/compression transition, and EXP-ICD-001 rejects the industry-versus-stock
entry-strength decomposition. Frozen V1 remains authoritative and unchanged. No
threshold, overlay, entry adaptation, exit adaptation, neighbor substitution, or
production change is authorized.

## Highest-information unresolved question

When, after entry, does V1's right tail become distinguishable from ordinary
trades? The next minimum experiment should use only frozen observable holding
paths, condition explicitly on landmark availability, and test whether early
continuation adds information beyond pre-entry state, holding duration, and exit
lineage. It must remain mechanism description, not an exit or filter design.

## Exact next action

Persist/checkpoint EXP-ICD-001, then audit fixed 5/10/20-session landmark-path
coverage without reading outcome values. If adequate, preregister one early-path
emergence hypothesis with explicit survivor-selection and mechanical-overlap
limitations. EXP-P7-003 must never be silently repaired, rerun, or overwritten.
