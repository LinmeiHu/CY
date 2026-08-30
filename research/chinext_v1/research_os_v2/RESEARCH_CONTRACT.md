# CHINEXT V1 Research OS V2 contract

Frozen at program initialization on 2026-08-30. This program inherits the
repository `AGENTS.md` invariants and the accepted PIT, execution, corporate-
action, and ledger semantics of the prior CHINEXT V1 programs.

## Authority and isolation

- Program root: `research/chinext_v1/research_os_v2/`.
- Branch: `research/chinext-v1-research-os-v2`.
- Starting HEAD: `e34d8b88dfc47db375b458779c4cca87272cb8e6`.
- Canonical V1 remains frozen at SHA-256
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`.
- `regime_attribution/` and `original_breakout_lineage/` are immutable evidence
  sources. Their valid results, invalid attempts, and interpretation limits are
  preserved exactly.
- Existing 2018-2025 outcomes are consumed exploratory evidence. They are not
  untouched validation for a newly discovered mechanism or combination.
- CY-011 2024-2026 validation remains locked. No query or materialization of the
  locked range is authorized by this contract.

## Scientific identity rules

A failed experiment is not automatically a failed representation, hypothesis,
mechanism, or family. The permitted statuses are:

`REPRESENTATION_REJECTED`, `HYPOTHESIS_REJECTED`, `MECHANISM_UNSUPPORTED`,
`CONDITIONAL_EFFECT`, `SUPPORTED_EXPLORATORY`, `SUPPORTED`,
`FAMILY_UNDEREXPLORED`, `FAMILY_WEAK`, `FAMILY_CLOSED`, and
`PROSPECTIVE_VALIDATION_PENDING`.

`FAMILY_CLOSED` requires diverse economically independent representations,
conditions, trajectories, interactions, failure modes, and temporal portability.
Parameter variants of one formula do not satisfy that requirement.

## Three coordinate systems

Every important state concept must distinguish:

1. absolute state, comparable in economic units across years;
2. PIT historical normalization, using only observations available through the
   completed decision timestamp;
3. relative state, comparing the security or market with contemporaneous
   alternatives.

Relative ranks may not substitute for absolute state. Full-year or future-
informed percentiles are prohibited. Unknown lineage or insufficient causal
history produces missing state and fails closed; it is never imputed, clipped,
normalized away, or silently substituted.

## Event, timing, and execution

- Default state timestamp is the completed official close at `t`.
- A feature using close `t` is available no earlier than that completed close.
- A signal formed on `t` can first affect a causally valid later session, never
  a fill inside `t`.
- Canonical V1 T+1, trading-status, limit, suspension, lot, corporate-action,
  cash/share, and no-replacement semantics remain unchanged.
- Post-entry path features are explanatory outcomes at their declared landmark;
  they are not ex-ante entry signals and cannot authorize same-bar action.

## Research progression

Research proceeds from representation and phenomenology to mechanism,
independent representations, trajectory, conditional structure, interactions,
failure taxonomy, temporal portability, falsification, and only then validation.

Every outcome-bearing experiment must have a frozen ID and spec before its first
new feature/outcome association. Every tested combination must be registered,
including failures. Combination construction is mechanism-driven and begins with
two distinct roles. `BASELINE`, `A`, `B`, and `A+B` are compared before claiming
incrementality or synergy.

## Strategy boundary

Behavior discovery, mechanism evidence, combination discovery, candidate
structure, validation, and implementation are separate gates. This program does
not modify canonical V1 unless a later isolated candidate survives the required
right-tail, left-tail, temporal, neighboring-definition, execution, simplicity,
and governance gates. No current candidate exists.

## Stop boundary

Stop on workspace-integrity ambiguity, unknown required PIT lineage, required
locked-holdout access, unavailable indispensable data, production-schema or
canonical-strategy modification, destructive Git requirements, or unsafe
resource use. A failed hypothesis, experiment, representation, or research phase
is not by itself a stop condition.
