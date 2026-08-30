# CHINEXT V1 autonomous research handoff

## Status

`ENVIRONMENT_VALID_WORKSPACE_RECOVERED` on 2026-08-30.

The latest valid experiment is EXP-P6-001. EXP-P7-003 is invalidated, and Phase
8/9 plus `FINAL_REPORT.md` are downstream-invalid. Frozen V1 remains unchanged;
no strategy or production action is authorized. Workspace recovery is complete,
but no scientific experiment was started in the recovery turn.

## Recovered autonomous environment

- worktree: `/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830`;
- branch: `research/chinext-v1-autonomous-20260830`;
- source HEAD: `e361aa9fb98756becc09c76dd88552533f3762fe`;
- transferred authoritative files: 161;
- source/destination aggregate SHA-256 before destination-only recovery records:
  `4965f87b6129a865c102fbfe1a4d807499614ac831b34daa8bd9e3751c3f3942`;
- source tracked modifications transferred: none;
- external `opportunity_conversion/` files transferred: none;
- cache/bytecode files transferred: none.

The external source tree was still changing during recovery: it grew from the six
files originally observed to 38 files at a later classification snapshot. Because
ownership was explicitly external, the entire directory prefix was excluded; no
attempt was made to select from or interpret its changing contents.

The recovery commit contains the verified `regime_attribution` state plus the
destination-only ownership/recovery record. Use this worktree, not the original
source checkout, for the next autonomous launch.

## Checkout reconciliation

- working directory: `/Users/linmei/Documents/CY-supermind-v6`
- repository root: `/Users/linmei/Documents/CY-supermind-v6`
- branch: `research/chinext-v1`
- HEAD: `e361aa9fb98756becc09c76dd88552533f3762fe`
- short status at entry:
  - `M configs/data_asset_registry.json`
  - `M research/chinext_v1/scripts/run_chinext_v1_smoke.py`
  - `?? research/chinext_v1/regime_attribution/`
- additional status line that appeared during final reconciliation:
  - `?? research/chinext_v1/opportunity_conversion/`
- no destructive Git operation, checkout, reset, clean, rebase, or overwrite was
  performed;
- no other active Codex agent and no CHINEXT phase/replay process was observed,
  but the new directory proves another external writer touched the checkout.

The external directory was not read as research evidence and was left untouched.
Exact files and SHA-256 fingerprints are:

- `DATA_AUDIT.md`: `3d0e3731f46760166047776a8b68cd16c625ea956feb72f8cec352d909251a52`;
- `EXPERIMENT_REGISTRY.md`: `c4547325f910f9228feeee98704ba2da63d2192b662dddb93256617b4155d034`;
- `GOAL.md`: `e6f0636baa5ae72681300be6b137bf8344fd86ae59296a777890486a584c6044`;
- `HYPOTHESES.md`: `af4fc0a8b45e114063a613e92a401ecd0f977294266db1a174d4c709e0797d8d`;
- `RESEARCH_CONTRACT.md`: `7771f8386998fe28cf41729a75a0248745592da801ee254628af65f1dff0223e`;
- `STATE.md`: `a2dab72a53ed9cbb49b5aa5b168753a28a9a2a3ecb6ef42196d214accea3086d`.

This live workspace-integrity violation is an independent fail-closed reason to
stop, even if the historical EXP-P7-003 contradiction were absent.

## Exclusive-workspace and fingerprint evidence

A 203-file inventory covered the regime research tree, all manifest-bound
baseline/candidate ledgers, preregistered specs and runners, registry, strategy,
membership/security inputs, CY-006 partitions, calendar, and index inputs. It was
unchanged across the scoped Phase 5/6 validation:

- initial aggregate SHA-256:
  `6440a05514e3f6ed2d025ac915415d2e0ea0e5d1b8e384922e0a14169f189a5c`;
- final aggregate SHA-256:
  `6440a05514e3f6ed2d025ac915415d2e0ea0e5d1b8e384922e0a14169f189a5c`;
- changed files during that interval: zero.

Read-only input validators passed for EXP-P1, EXP-P2 direct inputs, EXP-P3-002,
EXP-P4-002, EXP-P5-001, EXP-P6-001, current Phase 7 registered identities and
bounded authorizations, and EXP-P8P9's 15 persisted ledger bundles. Phase 5/6
targeted tests pass `10 passed in 0.75s`.

## Exact blocker

EXP-P7-003 says the current registry may be projected back to the exact legacy
registry, but every non-registry legacy Gate C input must remain byte-exact. The
current registry projection passes. The next legacy Gate C binding does not:

- path: `research/chinext_v1/scripts/run_chinext_v1_smoke.py`;
- legacy Gate C role: `replay_engine`;
- legacy expected SHA-256:
  `9993b4ab03a437007eb056e530f786bff2e0fc7f90276aaac9db42cfced30797`;
- EXP-P7/current overlay SHA-256:
  `3136edf9fc6a8a9f0a8d42487d8703943b0eaacaccdd188be18a6274cb4793e3`;
- candidate wrapper SHA-256:
  `192c5929ac1f31aca990a909db931cda96a7bcd53303cb105fecb84caa2d3fcc`;
- EXP-P7-003 spec SHA-256:
  `620dbbcbde02fe1dae1867a7237dfa23eee85ad3d87b8b80c28d491db387911e`.

The current authorized wrapper's own compatibility validator raises
`Phase7Error` on this `replay_engine` mismatch before extended transient input
materialization. Consequently, the claim that the persisted 15 replays executed
under all frozen gates cannot be reconstructed. No file was rebound, repaired,
rerun, or deleted.

## Valid mechanism evidence

The requested MFE-to-realized-return frontier was already completed validly:

- 383 complete breadth observations among 399 frozen cycles;
- breadth/MFE rho 0.218, breadth/MFE>=20% rho 0.188, and breadth/false-breakout
  rho -0.147, all with 8/8 expected-direction LOYO signs;
- terminal realized-return rho only 0.073;
- low/middle/high breadth mean MFE 7.8%/17.0%/24.3%, while severe-loss rates are
  10.1%/11.0%/12.6%;
- within 80 complete MFE>=20% opportunities, fixed controls for MFE, holding
  duration, time-to-MFE fraction, entry year, and exit reason leave capture rho
  -0.028, conversion20 rho -0.068, and giveback rho -0.088; none passes;
- all 15 >=50% winners reached MFE late (median time-to-MFE fraction 0.79) and
  exited through market-MA20 lineage, but this is descriptive and not exit
  causality.

Decision at the valid frontier: breadth primarily describes opportunity
generation and right-tail availability. Capture efficiency, giveback, timing,
downside gating, and exit modification are not supported as independent breadth
mechanisms.

## Hypothesis status

- supported with qualification: H-001, H-002, H-004, H-008;
- rejected: H-003, H-005, breadth downside gating, controlled breadth conversion,
  and the prior winner-hold exit adaptation;
- ambiguous: H-006, H-007;
- unresolved because the experiment branch is invalid: H-009, H-010.

## Required next action

The next autonomous launch may proceed only from EXP-P6-001 and must ignore the
invalid candidate branch. The preferred scientific continuation is prospective
validation of the frozen breadth-opportunity hypothesis on future untouched
PIT-A-quality data, or one new registered causal data family with a single
preregistered incrementality test. Do not run another 2018-2025 threshold,
interaction, overlay, or exit optimization.

Human authorization remains necessary only if anyone proposes to investigate or
replace EXP-P7-003. It must not be repaired in place.
