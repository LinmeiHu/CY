# WORKER-QA-001 frozen worker specification

- Lane: D, adversarial QA replication only.
- Base commit: `fc665b016e2df01e11047a64e88f53905ccdcfdf`.
- Branch/worktree: `research/osv23-qa-001` in the dedicated QA worktree.
- Inputs: only the compact bound panels, audits, results, reports, maps, specs,
  and primary-runner files required for hash verification for
  `MKT-FORMDEPTH-{ATTR,PROP,CLOSE,PATH,IMMED}-001`.
- Physical lineage note: ignored predecessor market-level control artifacts absent
  from a fresh worktree may be hash-verified read-only at the Director artifact
  store; the alternate physical root must be recorded and no values from those
  predecessor artifacts enter the response replay.
- Estimator: independently implemented average-rank OLS residualization,
  Pearson correlation of residuals, and raw-response/ranked-control PIT-tail
  residual gaps.
- Required checks: all response-audit rows, ATTR geometry rows, frozen bindings,
  clocks, support, gates, classifications, selected scalar cases, deterministic
  rerun, focused tests, lint, and resource telemetry.
- Claim boundary: replication/audit only. No new hypothesis, alpha search,
  strategy outcome, habitat, entry rule, or causal claim.
- Prohibited reads: raw QD-004/CY-008, CY-011, post-2023 data, minute scans, and
  strategy outcomes.
- Resource contract: one process, internal threads fixed to one, peak RSS at or
  below 1.5 GiB, compact durable output only.
- Disagreement policy: any mismatch beyond `5e-12`, hash mismatch, clock breach,
  or classification difference yields `QUARANTINE_DISAGREEMENT`.
