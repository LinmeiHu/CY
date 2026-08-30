# Original-breakout lineage handoff

## Current status

Independent program initialized at autonomous branch start HEAD
`5309f2ef8a5ee6a57c7b63934acff77897faf1b3`. No outcome reveal has occurred in
this new program. CY-011 remains locked and unopened. EXP-OBL-003 has frozen
`LINEAGE-OBL-003-4193834A6A3A39BF` after two byte-identical full runs.

EXP-OBL-004 has now revealed outcomes and rejects H-OBL-003. Raw/controlled rhos
are 0.015/0.017 for MFE and 0.027/0.043 for non-false-breakout. Both earlier
blocks reverse the positive development block; all gates fail. The taxonomy and
its components may not be relabeled or promoted.

## Canonical original V1 breakout

At completed close `t`, `close_t` must strictly exceed the maximum of the prior
60 completed closes. FULL40 uses only prior 40 closes plus prior volatility
history; MINVOL uses only t-30..t-1. Own MA20, basic eligibility/liquidity,
market 399102 MA20 permission, cross-sectional RS ranking, portfolio capacity,
and no-replacement state also apply. Breakout-volume ratio is shadow-only. The
first executable buy is a later valid open, normally T+1.

## Available data

Registered CY-006 daily and QD-004/CY-008 minute PIT-B assets cover the historical
event range. Exact one-minute OHLCV/amount and deterministic five-minute/VWAP
features are feasible. Order books, ticks, bid/ask, and participant identity are
not available. Full signal-session features are available at 15:30 and can only
inform T+1 or later.

## Active experiment

EXP-OBL-001 is invalid due only to a one-character holdout-membership hash typo;
it stopped before reading a data row and produced no output. EXP-OBL-002 is the
clean identity with unchanged science and corrected binding. OBL-002 passed all
outcome-blind construction checks except the minimum-two-per-lineage/year gate:
2018 has only 11 events and split 1/4/3/3. It wrote no output. EXP-OBL-003 keeps
the exact taxonomy/assignments and changes only this gate to minimum one, testing
presence in every year. The runner projects only identity columns from the
accepted trade source; its explicit forbidden-column set blocks every future
outcome.

EXP-OBL-003 passes all construction gates. It covers 399 events, has lineage
counts 92/112/96/99, all four IDs in every year and block, 84.46% exact neighbor
agreement, 31,920 action-safe daily rows, 96,159 exact minute rows, and zero
forbidden outcome columns. H-OBL-002 decision: `FREEZE_LINEAGE`.

## Current frontier

The next independent question is repeated objective resistance testing. Freeze a
new outcome-blind artifact counting distinct prior-60 entries into the 2% zone
below the canonical reference, with 1%/3% neighbors, before any new association.
Zone duration, reference age, prebreakout distance, box width, V1 entry state,
market state, and H-004 breadth are controls, not new search dimensions. EXP-
OBL-005 is frozen before feature materialization. No candidate rule exists.

EXP-OBL-005 is now rejected before outcomes: 2%/1% episode-count rho is 0.604,
below the 0.65 neighboring gate; 2%/3% is 0.713. No artifact or outcome test is
accepted. Do not choose 3% or search other widths.

The next frontier is parameter-free prebreakout positioning. Freeze action-safe
log(t-1 close / canonical reference) with T-3 and T-5 temporal neighbors before
any association. Breakout margin and reference age are future controls. No
candidate rule exists and CY-011 remains locked.

EXP-OBL-006 is frozen before feature materialization. It binds the runner and
all PIT inputs, prohibits every future outcome, requires at least 300 primary
values, at least 0.60 rank agreement with both fixed temporal neighbors, and
positive neighbor direction in at least seven of eight years. The exact next
action is execution without outcomes, followed by deterministic reproduction if
all gates pass.

EXP-OBL-006 then stopped before writing any output. T-1/T-3 rho is 0.421 and
T-1/T-5 rho is 0.309, failing the frozen 0.60 robustness gate. No outcome was
read; H-OBL-005 is rejected and no horizon/threshold may be selected.

The current frontier is H-OBL-006: the already frozen exact number of sessions
since the most recent canonical reference close. It was not an assignment axis
of the rejected taxonomy and has 60 observed states with broad yearly coverage.
Preregister a continuous, unbinned outcome test with base-depth, positioning,
breakout-margin, V1-state, and market controls. CY-011 remains locked.

EXP-OBL-007 is now frozen before its first outcome join. It predicts positive
MFE and non-false-breakout associations, requires raw/controlled rhos of at
least 0.10/0.08 for both endpoints, and includes LOYO, blocks, tails, exact
zero/59 boundary removal, duration/exit, security, and industry attacks. Execute
the committed runner without changing gates or controls.

EXP-OBL-007 is complete and rejected. MFE raw/controlled rhos are
0.0005/0.0133; non-false-breakout raw/controlled rhos are -0.0544/0.0421. All
four gate families fail and two runs are byte-identical. Do not bin age or flip
the mechanism direction.

The next frontier is an outcome-blind feasibility audit of cross-sectional
selection competition. Reconstruct, if possible, each signal day's complete
eligible candidate set, RS order, portfolio vacancies, selection boundary, and
accepted mapping using only autonomous-workspace code and registered PIT data.
Do not bind or consume the original source worktree's output ledgers. CY-011
remains locked.

AUDIT-OBL-002 concludes this is feasible. The unchanged engine hash matches its
frozen contract and records evaluated-signal RS/min-volume state plus
previous/desired sets. EXP-OBL-008 should run all three bounded baseline blocks
in fresh temporary directories, read event ledgers only, project the 399-cycle
identity columns, and freeze exact contested/uncontested selection lineage plus
continuous pressure/rank context. Generated performance/execution/NAV files
must remain unread and temporary. No candidate rule exists.

EXP-OBL-008 is now committed before replay. It freezes the exact capacity
boundary and all input/runner hashes, prohibits outcome and temporary
performance-file access, and requires balanced multi-year neutral classes plus
exact identity/rank/cutoff reconstruction. Execute it from a clean tree, then
repeat the full freeze for byte identity before any separate reveal.

EXP-OBL-008 stopped without output after exact reconstruction: contested 48,
uncontested 351. Both classes have broad temporal presence, but minimum-size 50
and maximum-share 85% fail. No outcome/performance file was read. A fresh EXP-
OBL-009 may preserve all assignments and relax only the outcome-blind feasibility
gate to 40/90%; do not alter the capacity boundary or context fields.

EXP-OBL-009 is committed with fresh paths and runner hash. It preserves all
EXP-OBL-008 scientific definitions and changes only minimum class size 50 to 40
and maximum class share 85% to 90%. Execute from a clean tree, then repeat the
full three-block replay for byte identity before any outcome reveal.

EXP-OBL-009 passes twice byte-identically and freezes
`LINEAGE-OBL-009-2BECCEFAF46C1140`: contested 48, uncontested 351, exact 399
coverage, contested present in seven years. Parent access was event-ledger only;
no outcome, NAV, execution, summary, report, or source-worktree ledger was read.

The next experiment must be a separate outcome reveal with frozen positive
direction for contested selection on both MFE and non-false-breakout. Absolute
RS, V1 entry state, market/breadth, year, candidate/vacancy context, tails,
duration/exit, security/industry, and the late concentration of contested events
must be attacks or controls. CY-011 remains locked.

EXP-OBL-010 is committed before outcome access with contested-positive direction
for both MFE and non-false-breakout. Its primary controls include absolute RS and
the fixed V1/market/breadth state; its attacks include candidate/vacancy/rank,
2025 concentration, post-2021, tails, duration/exit, security, and industry.
Execute unchanged and apply the frozen gates literally.

EXP-OBL-010 completes as `REFINE_TEMPORAL_INSTABILITY`. Aggregate MFE and
non-false raw/controlled rhos are 0.139/0.096 and 0.118/0.087, but the holdout
block is negative/null and ex-2025 rhos are only 0.016/0.018. No binary lineage
rule or candidate is supported.

The exact next question is the already frozen continuous selection-pressure
ratio, explicitly labeled a post-secondary exploratory follow-up. Test it
without bins or thresholds against both co-primary endpoints, controlling
absolute RS, breadth, V1/market state, and year, with full temporal/tail/
concentration attacks. CY-011 remains locked.

EXP-OBL-011 is now committed for execution under fresh runner/output identities.
It controls binary contested selection in addition to absolute RS, breadth,
V1/market state, and year. Both endpoints must be positive in every frozen block,
with LOYO, ex-2025, post-2021, candidate/vacancy-component, tail, duration/exit,
security, and industry attacks. This is post-secondary evidence, not independent
confirmation. Execute unchanged, repeat for byte identity, and apply gates
literally. CY-011 remains locked.

## Governance

H-004 remains prospective-validation pending; H-023 preserved; H-024/H-025
rejected; CBC-001/002 invalid and CBC-003 valid. Canonical V1 is unchanged. No
candidate rule exists. `CANDIDATE_READY_FOR_CY011: NO`.
