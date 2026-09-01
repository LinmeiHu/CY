#!/usr/bin/env python3
# ruff: noqa: E501
"""Build the artifact-only historical opposite-sign family audit.

This script does not read market outcomes or raw evaluation panels.  It serializes
the frozen, human-reviewed evidence extracted from tracked compact reports at the
starting checkpoint and validates the six-class governance contract.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

EXPERIMENT_ID = "ASHARE-HISTORICAL-OPPOSITE-SIGN-CLOSED-FAMILY-AUDIT-V1"
START_HEAD = "b6fb8974f38e3606633e23c7caed25428a45819b"
SPEC_REL = (
    "research/market_behavior_os_v2/experiments/"
    "ASHARE-HISTORICAL-OPPOSITE-SIGN-CLOSED-FAMILY-AUDIT-V1_spec.json"
)
LEDGER_REL = (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-HISTORICAL-OPPOSITE-SIGN-CLOSED-FAMILY-AUDIT-V1_ledger.csv"
)
CANDIDATE_REL = (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-HISTORICAL-OPPOSITE-SIGN-CLOSED-FAMILY-AUDIT-V1_candidates.csv"
)
RESULT_REL = (
    "research/market_behavior_os_v2/artifacts/"
    "ASHARE-HISTORICAL-OPPOSITE-SIGN-CLOSED-FAMILY-AUDIT-V1_result.json"
)
REPORT_REL = (
    "research/market_behavior_os_v2/reports/"
    "ASHARE-HISTORICAL-OPPOSITE-SIGN-CLOSED-FAMILY-AUDIT-V1_report.md"
)

CLASSES = {
    "TRUE_NULL",
    "CHRONOLOGICALLY_UNSTABLE",
    "STABLE_ADVERSE_ALREADY_USED",
    "STABLE_ADVERSE_LONG_CANDIDATE_NEEDS_ANATOMY",
    "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
    "SCIENTIFICALLY_UNRESOLVED",
}
CANDIDATE_LABEL = "POST_HOC_HYPOTHESIS_GENERATED_FROM_CONSUMED_DEVELOPMENT_HISTORY"

REFERENCE_ONLY_EXPERIMENTS = [
    "ASHARE-DOWNSIDE-RESILIENCE-DISCOVERY-V1",
    "ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1",
    "ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1.1",
    "ASHARE-POST-SHOCK-ADVERSE-RECOVERY-ANATOMY-V1",
    "ASHARE-POST-SHOCK-STRONG-RECOVERY-AVOIDANCE-ANATOMY-V1",
]


def family(
    family_id: str,
    family_name: str,
    experiment_ids: list[str],
    original_hypothesis: str,
    expected_sign: str,
    observed_evidence: str,
    consistency: str,
    decomposition: str,
    classification: str,
    reason: str,
    evidence_paths: list[str],
    *,
    priority: str = "NONE",
    next_anatomy: str = "NONE",
) -> dict[str, Any]:
    return {
        "family_id": family_id,
        "family_name": family_name,
        "experiment_ids": experiment_ids,
        "original_hypothesis": original_hypothesis,
        "expected_sign": expected_sign,
        "observed_evidence": observed_evidence,
        "consistency": consistency,
        "spread_decomposition": decomposition,
        "audit_classification": classification,
        "classification_reason": reason,
        "candidate_priority": priority,
        "candidate_label": CANDIDATE_LABEL if "NEEDS_ANATOMY" in classification else "NONE",
        "next_anatomy": next_anatomy,
        "evidence_paths": evidence_paths,
    }


FAMILIES = [
    family(
        "F01_PRICE_LIMIT_STABLE_ACCEPTANCE",
        "Price-limit stable/early acceptance",
        ["ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014"],
        "Earlier and more stable limit-up acceptance should identify durable demand.",
        "positive",
        "All lifecycle states had negative absolute returns. Early-stable h1/h3/h5 means were -2.181%/-2.732%/-3.144%; stable acceptance trailed failed acceptance by 1.884 pp at h3 and had 12.723 pp worse severe-loss incidence; stable also trailed reopen/reseal by 1.102 pp.",
        "Adverse at h1/h3/h5, in both fixed blocks, across early/mid/late state comparisons, and in mean/median/winner/severe-loss diagnostics; year anatomy was not reported.",
        "AVOIDANCE_ONLY: the favored stable/early states are intrinsically negative; failed/reseal comparators are less bad, not established long legs.",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "A broad and material negative lifecycle topology was closed as no useful positive signal without a dedicated negative-leg/event-baseline anatomy.",
        ["research/market_behavior_os_v2/reports/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_report.md"],
        priority="HIGH",
        next_anatomy="Using the frozen lifecycle states only, decompose each state against the all-event baseline by horizon/year and determine whether adverse economics are stable-state weakness or merely relative less-bad comparisons; no replay.",
    ),
    family(
        "F02_PRICE_LIMIT_LIQUIDITY_TRANSITIONS",
        "Price-limit liquidity transitions and reopen/reseal relative improvement",
        ["ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014"],
        "Dormant-to-active, rejection, recovery, or reopen/reseal transitions should positively identify continuation.",
        "positive",
        "Dormant-to-active matched h3 was only +0.040 pp with worse severe losses; activity-shock rejection was a +0.300 pp less-bad contrast while both legs were negative; liquidity recovery reversed from +0.200 pp early to -0.110 pp late. Reopen/reseal remained -1.152% at h5.",
        "Tiny or less-bad effects and a chronological reversal; no positive absolute reopen/reseal leg.",
        "LESS_BAD_ONLY_OR_NOISY",
        "TRUE_NULL",
        "The compact artifacts already show insufficient magnitude/coherence for an opposite long or avoidance hypothesis independent of the stable-acceptance family.",
        ["research/market_behavior_os_v2/reports/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_report.md"],
    ),
    family(
        "F03_MINUTE_LEADER_FOLLOWER",
        "Minute industry leader-to-follower propagation",
        ["ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013"],
        "Leader moves should causally propagate to followers after the decision timestamp.",
        "positive",
        "Matched future w1-3 payoff was +0.0294%, while the already-completed reverse window was +0.0403%; future-minus-reverse was -0.0110% with only 21.73% coverage.",
        "The apparent relationship is contemporaneous/simultaneous rather than forward; magnitude and coverage fail.",
        "NO_OPPOSITE_LEG",
        "TRUE_NULL",
        "The sign comparison rejects causal propagation but does not expose an economically meaningful opposite trade.",
        ["research/market_behavior_os_v2/reports/ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013_report.md"],
    ),
    family(
        "F04_LOW_RISK_DEFENSIVE_COMPLEX",
        "Low Idio / Low Vol-of-Vol / Low Skewness / Low-MAX defensive complex",
        [
            "ASHARE-DIVERSIFIED-CYCLE-002",
            "ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008",
            "ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009",
            "ASHARE-EVIDENCE-DEPTH-CYCLE-010",
            "ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012",
        ],
        "Lower lottery-like and lower unstable-risk characteristics should improve payoff quality.",
        "positive for low-risk orientation",
        "Low Idio, Low Skewness, Low Vol-of-Vol, and Low-MAX produced repeated defensive ordering. Independence audits found substantial redundancy (Low Vol-of-Vol vs Low Idio rank correlation 0.624; residual results unstable), while Low-MAX earned the frozen champion role.",
        "Repeated block/defensive evidence; incremental independence was mixed rather than a missed adverse sign.",
        "ALREADY_DECOMPOSED_AND_USED",
        "STABLE_ADVERSE_ALREADY_USED",
        "The economically useful adverse high-risk/high-MAX side was already preserved as defensive information or translated into Strategy A; Low Skewness standalone research was correctly closed.",
        [
            "research/market_behavior_os_v2/reports/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_report.md",
            "research/market_behavior_os_v2/reports/ASHARE-EVIDENCE-DEPTH-CYCLE-010_report.md",
            "research/market_behavior_os_v2/reports/ASHARE-LOW-MAX-CONFIRMATION-CYCLE-012_report.md",
        ],
    ),
    family(
        "F05_RS_ACCELERATION_VETO",
        "CHINEXT relative-strength acceleration veto",
        ["HAB-CHX-SELECTION-SCREEN-001", "HAB-CHX-DECISION-BATCH-001"],
        "Extreme relative-strength acceleration is overextension and should be excluded.",
        "adverse high acceleration",
        "The high-acceleration subgroup underperformed in 10 of 11 half-year episodes; the frozen veto improved the executable strategy in both development blocks.",
        "Stable episode and two-block executable evidence.",
        "ADVERSE_LEG_USED_AS_VETO",
        "STABLE_ADVERSE_ALREADY_USED",
        "The opposite-sign information was explicitly recognized and incorporated as a frozen admission component.",
        [
            "research/market_behavior_os_v2/reports/HAB-CHX-SELECTION-SCREEN-001_stock_selection_screen.md",
            "research/market_behavior_os_v2/reports/HAB-CHX-DECISION-BATCH-001_strategy_replay.md",
        ],
    ),
    family(
        "F06_CONFIRMED_BREAKDOWN_LIFECYCLE",
        "Confirmed-breakdown admission/exit lifecycle",
        [
            "ASHARE-SUPPORT-RECOVERY-CYCLE-007",
            "ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008",
            "ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020",
        ],
        "Confirmed objective support failure should identify avoidable downside or justify exit.",
        "negative after breakdown",
        "The screen found downside information, but the frozen admission mapping affected zero decisions. The later champion exit audit found positive post-breakdown h1/h3/h5 returns (+0.400%/+0.669%/+0.686%) and +1.572% remaining-lifecycle return, supporting retain/no exit.",
        "The executable lifecycle test was broad (1,020 actionable events) and remaining returns were stable across blocks.",
        "ADVERSE_SCREEN_TRANSLATED_AND_EXIT_REJECTED",
        "STABLE_ADVERSE_ALREADY_USED",
        "The signal received both natural admission and exit examinations; the resulting non-action is itself the proper scientific use.",
        [
            "research/market_behavior_os_v2/reports/ASHARE-SUPPORT-RECOVERY-CYCLE-007_report.md",
            "research/market_behavior_os_v2/reports/ASHARE-CHAMPION-BREAKDOWN-EXIT-CYCLE-020_report.md",
        ],
    ),
    family(
        "F07_MARKET_MINUTE_VOLATILITY_OVERLAY",
        "Market minute-volatility path risk overlay",
        ["HAB-CHX-MINVOLPATH-STRAT-001", "HAB-CHX-MINVOL-COST-001"],
        "Adverse market minute-volatility paths should identify risk periods for the strategy.",
        "adverse state",
        "The frozen veto improved both blocks before cost stress, but the effect became cost-sensitive: at 20 bps/side the block deltas were +0.269/+5.706 pp and at 30 bps/side -2.407/+4.811 pp.",
        "Directionally useful but not robust to plausible cost stress.",
        "ADVERSE_STATE_ALREADY_TESTED_AS_OVERLAY",
        "STABLE_ADVERSE_ALREADY_USED",
        "The information was explicitly tested in its natural risk role and correctly downgraded/closed for tuning.",
        [
            "research/market_behavior_os_v2/reports/HAB-CHX-MINVOLPATH-STRAT-001_strategy_translation.md",
            "research/market_behavior_os_v2/reports/HAB-CHX-MINVOL-COST-001_cost_stress.md",
        ],
    ),
    family(
        "F08_MOMENTUM_COMPLEX",
        "Canonical and revised medium-term momentum",
        [
            "ASHARE-INDEP-FUNNEL-001",
            "ASHARE-EXTERNAL-PRIOR-CYCLE-005",
            "ASHARE-EVIDENCE-DEPTH-CYCLE-010",
        ],
        "Medium-term winners should continue outperforming.",
        "positive",
        "Canonical formulations were adverse, but corrected/revised 6/9/12-month momentum was strongly positive in the early block and negative in the late block.",
        "The scientifically improved specification reverses chronologically across all tested canonical horizons.",
        "NO_STABLE_OPPOSITE_LEG",
        "CHRONOLOGICALLY_UNSTABLE",
        "Earlier adverse artifacts cannot be promoted after the corrected formulation demonstrated block reversal.",
        ["research/market_behavior_os_v2/reports/ASHARE-EVIDENCE-DEPTH-CYCLE-010_report.md"],
    ),
    family(
        "F09_MIXED_PUBLISHED_TECHNICAL_PRIORS",
        "52-week-high, industry momentum, and simple intraday reversal priors",
        ["ASHARE-EXTERNAL-PRIOR-CYCLE-005"],
        "Canonical published technical priors should transfer to the A-share long-only setting.",
        "positive",
        "The tested 52-week-high, industry-momentum, and intraday-reversal formulations were mixed or reversed across fixed blocks rather than stably adverse.",
        "Chronological sign instability dominates any pooled spread.",
        "NO_STABLE_OPPOSITE_LEG",
        "CHRONOLOGICALLY_UNSTABLE",
        "The batch provides no stable opposite-sign family after preserving exact formulations.",
        ["research/market_behavior_os_v2/reports/ASHARE-EXTERNAL-PRIOR-CYCLE-005_report.md"],
    ),
    family(
        "F10_RELATIVE_RANK_ACCELERATION",
        "Market-relative and industry-follower rank acceleration",
        ["ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009"],
        "Improving relative rank should forecast positive continuation.",
        "positive",
        "Market-relative rank acceleration had -1.260% excess (-0.337%/-2.055% by block), -1.190% selected mean, -3.393% median, and +12.293 pp severe-loss disadvantage. Industry-follower rank acceleration had -0.835% excess (-0.438%/-1.173%), -0.740% mean, -3.226% median, and +8.169 pp severe-loss disadvantage.",
        "Both related definitions are adverse in both blocks and in mean/median/severe-loss diagnostics; year and full-bucket decompositions are absent.",
        "AVOIDANCE_ONLY_PENDING_LEG_DECOMPOSITION",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "Two economically related rank-change priors produced material, distribution-broad adverse evidence, but the original audit stopped at favored-set versus date-control results.",
        ["research/market_behavior_os_v2/reports/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_report.md"],
        priority="HIGH",
        next_anatomy="Using the exact frozen rank-change scores, decompose coarse score buckets versus date/event baselines and by year to determine whether high acceleration is intrinsically adverse or whether low acceleration is a positive leg; no threshold or portfolio search.",
    ),
    family(
        "F11_SAME_MONTH_SEASONALITY",
        "Same-calendar-month return seasonality",
        ["ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009"],
        "Strong return in the same calendar month one year earlier should recur.",
        "positive",
        "The favored set had -1.841% excess (-2.073%/-1.682% by block), -1.250% absolute mean, -3.201% median, and +3.275 pp severe-loss disadvantage.",
        "Adverse in both blocks and across mean/median/severe-loss diagnostics; yearly and opposite-leg anatomy were not reported.",
        "AVOIDANCE_ONLY_PENDING_LEG_DECOMPOSITION",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "A canonical externally motivated prior failed with a sizeable and chronologically repeated adverse long leg, but the negative leg was not studied directly.",
        ["research/market_behavior_os_v2/reports/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_report.md"],
        priority="HIGH",
        next_anatomy="Hold the same-month score and horizon fixed; report all coarse buckets, each leg versus the date baseline, year stability, and whether the result is high-score underperformance versus a true low-score long leg.",
    ),
    family(
        "F12_FIP_GOOD_NEWS",
        "Frog-in-the-pan gradual good-news continuation",
        ["ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009"],
        "Positive residual return accumulated through many small moves should continue.",
        "positive",
        "The favored set had -0.786% excess (-0.173%/-1.334% by block), -0.630% absolute mean, -2.702% median, and +3.966 pp severe-loss disadvantage.",
        "Adverse in both blocks and distribution diagnostics, with weaker early magnitude; bucket and year anatomy absent.",
        "AVOIDANCE_ONLY_PENDING_LEG_DECOMPOSITION",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "The expected continuation leg appears intrinsically poor, but evidence is weaker than the top three and remains an unconfirmed post-hoc avoidance question.",
        ["research/market_behavior_os_v2/reports/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_report.md"],
        priority="MEDIUM",
        next_anatomy="Decompose the frozen information-discreteness score into coarse buckets and event baseline by block/year to determine whether gradual-good-news stocks are a stable avoidance leg.",
    ),
    family(
        "F13_OVERNIGHT_DAYTIME_AND_ATTENTION",
        "Overnight/daytime tug-of-war and low-turnover attention",
        ["ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009"],
        "Overnight/daytime disagreement and low attention should identify continuation quality.",
        "positive",
        "Overnight/daytime was near zero full-sample but +0.522% early and -0.468% late. Low-turnover attention was +0.076% full, -0.011% early, and +0.153% late.",
        "One reverses materially; the other is economically tiny.",
        "NO_STABLE_OPPOSITE_LEG",
        "CHRONOLOGICALLY_UNSTABLE",
        "No stable material adverse structure survives the fixed blocks.",
        ["research/market_behavior_os_v2/reports/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_report.md"],
    ),
    family(
        "F14_DOWNSIDE_UPSIDE_RESIDUAL_ASYMMETRY",
        "Downside/upside residual-risk asymmetry",
        ["ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008"],
        "Favorable downside/upside residual asymmetry should identify better stock quality.",
        "positive",
        "The favored set had -1.162% excess (-1.688%/-0.696% by block), -1.599% absolute mean, -2.427% median, and +7.801 pp severe-loss disadvantage.",
        "Adverse in both blocks and broad distribution diagnostics; it overlaps the subsequently audited downside-resilience research domain.",
        "AVOIDANCE_ONLY_WITH_FAMILY_OVERLAP",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "The historical artifact contains adverse information, but follow-up priority is low because later downside-resilience work was fully audited and closed.",
        ["research/market_behavior_os_v2/reports/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_report.md"],
        priority="LOW",
        next_anatomy="Only if the higher-priority candidates fail: establish whether the exact favored asymmetry leg is intrinsically adverse after reusing the existing coarse controls; do not reopen the broader downside-resilience family.",
    ),
    family(
        "F15_RESIDUAL_SHARPE",
        "Residual return-to-risk quality",
        ["ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008"],
        "Higher residual Sharpe should forecast superior payoff.",
        "positive",
        "Excess was only +0.222% and severe-loss incidence was 9.25 pp worse, without a coherent return/risk improvement.",
        "Small payoff and contradictory tail-risk evidence.",
        "NO_RELIABLE_OPPOSITE_STRUCTURE",
        "TRUE_NULL",
        "Neither the expected direction nor an adverse inversion has a coherent economic case.",
        ["research/market_behavior_os_v2/reports/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_report.md"],
    ),
    family(
        "F16_CLOSE_LOCATION_AND_GAP_ABSORPTION",
        "Close-location persistence and negative-gap absorption",
        ["ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008"],
        "Persistent strong closes or absorbed negative gaps should signal demand.",
        "positive",
        "Close-location persistence reversed from -0.671% early to +1.237% late; negative-gap absorption reversed from -0.476% early to +1.028% late.",
        "Both exact mechanisms reverse across fixed blocks.",
        "NO_STABLE_OPPOSITE_LEG",
        "CHRONOLOGICALLY_UNSTABLE",
        "The pooled results cannot support either direction without outcome-conditioned timing.",
        ["research/market_behavior_os_v2/reports/ASHARE-SKEW-BREAKDOWN-DISCOVERY-CYCLE-008_report.md"],
    ),
    family(
        "F17_OBJECTIVE_SUPPORT_RETEST",
        "Objective breakout-level retest / support-quality long",
        ["ASHARE-SUPPORT-RECOVERY-CYCLE-007"],
        "Holding or retesting a pre-existing objective support level should forecast continuation.",
        "positive",
        "Breakout-level retest had -1.031% excess (-0.768%/-1.244% by block), -1.279% mean, -1.999% median, and +11.062 pp severe-loss disadvantage. Other hold variants were weakly adverse or less bad.",
        "The strongest exact retest definition is adverse in both blocks and distribution diagnostics; the wider support family was extensively closed.",
        "AVOIDANCE_ONLY_PENDING_LEG_DECOMPOSITION",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "The exact retest leg contains adverse evidence, but repeated support research and failed breakdown translations leave little decision headroom.",
        ["research/market_behavior_os_v2/reports/ASHARE-SUPPORT-RECOVERY-CYCLE-007_report.md"],
        priority="LOW",
        next_anatomy="Only if higher-value work fails: decompose the frozen breakout-retest event against the all-event baseline by year; do not test new levels, windows, or support definitions.",
    ),
    family(
        "F18_STOCK_INTRADAY_DEMAND_ACCEPTANCE",
        "Stock-level intraday demand/acceptance suite",
        ["ASHARE-INTRADAY-INDEP-CYCLE-004"],
        "VWAP/closing acceptance, opening recovery, late demand, contraction, and relative intraday strength should forecast positive payoff.",
        "positive",
        "Six related favored states had negative excess in both blocks: VWAP acceptance -0.218%, closing acceptance -0.418%, opening weakness recovery -0.287%, late-volume demand -0.463%, intraday-volatility contraction -0.282%, and relative intraday strength -0.277%. Severe-loss disadvantages ranged roughly +1.27 to +6.89 pp.",
        "Repeated adverse signs across mechanisms, both blocks, and tail diagnostics; redundancy and leg decomposition remain unresolved.",
        "AVOIDANCE_ONLY_PENDING_REDUNDANCY_AND_LEG_DECOMPOSITION",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "The suite suggests a common adverse apparent-demand mechanism, but correlated descriptors and small individual returns make it secondary rather than a license for more minute-feature search.",
        ["research/market_behavior_os_v2/reports/ASHARE-INTRADAY-INDEP-CYCLE-004_report.md"],
        priority="MEDIUM",
        next_anatomy="Use only the frozen six descriptors to identify whether one common adverse leg drives the suite, then compare that leg with the event/date baseline by block/year; no new minute windows or composite optimization.",
    ),
    family(
        "F19_CHIP_STRUCTURAL_PRIORS",
        "Chip concentration / overhang-clearance / support-density priors",
        ["ASHARE-EXTERNAL-PRIOR-CYCLE-005"],
        "Concentrated cost structure, cleared overhang, and dense support should forecast positive payoff.",
        "positive",
        "Chip concentration, overhang clearance, and support density produced -1.023%, -1.955%, and -0.729% excess respectively, adverse in both blocks, with +5.757, +22.617, and +12.361 pp severe-loss disadvantages.",
        "Three related definitions, both blocks, and severe-loss diagnostics agree; leg/baseline and coordinate-specific interpretation remain incomplete.",
        "AVOIDANCE_ONLY_PENDING_LEG_DECOMPOSITION",
        "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
        "The adverse topology is material, but the family is secondary because the exact chip hypotheses were rejected and coordinate semantics constrain generalization.",
        ["research/market_behavior_os_v2/reports/ASHARE-EXTERNAL-PRIOR-CYCLE-005_report.md"],
        priority="MEDIUM",
        next_anatomy="Using the exact frozen chip scores only, separate intrinsically bad high-score legs from ordinary low-score controls and verify year stability; no new chip feature or threshold.",
    ),
    family(
        "F20_BREAKOUT_DEMAND_VOLUME_FORMATION_RISK",
        "Breakout/demand-volume failure and formation-depth tail risk",
        [
            "ASHARE-INDEP-FUNNEL-001",
            "MKT-BREAKOUT-ECON-001",
            "MKT-FORMDEPTH-ATTR-001",
            "MKT-FORMDEPTH-PROP-001",
            "MKT-FORMDEPTH-CLOSE-001",
            "HAB-CHX-FORMDEPTH-001",
        ],
        "Breakout and demand-volume strength should forecast positive continuation.",
        "positive",
        "The stock-level breakout screen was -2.710% with adverse direction in all six years; demand-volume shock was -0.840% and adverse in all six years. Later market-level formation-depth work explicitly attributed the resulting adverse topology to nonlocal tail-risk structure.",
        "Strong stock-level year/block/distribution evidence plus later independent representation and attribution work.",
        "ADVERSE_INFORMATION_ALREADY_MAPPED_AS_TAIL_RISK",
        "STABLE_ADVERSE_ALREADY_USED",
        "The adverse breakout information was not ignored: it was promoted into the market formation-depth/tail-risk research program rather than inverted into an unlicensed long strategy.",
        [
            "research/market_behavior_os_v2/reports/ASHARE-INDEP-FUNNEL-001_discovery.md",
            "research/market_behavior_os_v2/reports/MKT-BREAKOUT-ECON-001_response.md",
            "research/market_behavior_os_v2/reports/MKT-FORMDEPTH-ATTR-001_attribution.md",
            "research/market_behavior_os_v2/reports/MKT-FORMDEPTH-PROP-001_topology.md",
        ],
    ),
    family(
        "F21_INDUSTRY_ROTATION_TRANSLATION",
        "Industry-rotation 3x5 translation",
        ["ASHARE-DIVERSIFIED-CYCLE-002"],
        "Recent industry leadership should persist into a tradable stock portfolio.",
        "positive",
        "Full-period excess was -0.335%, but the fixed blocks were +0.478% and -1.039%.",
        "Material sign reversal across blocks.",
        "NO_STABLE_OPPOSITE_LEG",
        "CHRONOLOGICALLY_UNSTABLE",
        "The exact translation is closed and cannot support an inverse rotation rule.",
        ["research/market_behavior_os_v2/reports/ASHARE-DIVERSIFIED-CYCLE-002_report.md"],
    ),
    family(
        "F22_PRICE_VOLUME_AND_LIQUIDITY_RECOVERY",
        "Price-volume disagreement and liquidity-recovery priors",
        [
            "ASHARE-DIVERSIFIED-CYCLE-002",
            "ASHARE-INTRADAY-INDEP-CYCLE-004",
            "ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014",
        ],
        "Constructive price-volume disagreement or recovering liquidity should forecast continuation.",
        "positive",
        "Across daily, intraday, and price-limit implementations the effects were small, less-bad, or reversed by development block; no one exact definition supplied a stable material opposite leg.",
        "Definition and chronological instability dominate.",
        "NO_STABLE_OPPOSITE_LEG",
        "CHRONOLOGICALLY_UNSTABLE",
        "The family is closed; aggregation across unlike liquidity definitions would manufacture a signal.",
        [
            "research/market_behavior_os_v2/reports/ASHARE-DIVERSIFIED-CYCLE-002_report.md",
            "research/market_behavior_os_v2/reports/ASHARE-INTRADAY-INDEP-CYCLE-004_report.md",
            "research/market_behavior_os_v2/reports/ASHARE-PRICE-LIMIT-LIQUIDITY-CYCLE-014_report.md",
        ],
    ),
    family(
        "F23_DOWNSIDE_PARTICIPATION_VETO",
        "Market downside-participation admission veto",
        ["HAB-CHX-DOWNREV-STRAT-001"],
        "High downside participation should identify dates to avoid.",
        "adverse state",
        "The executable admission-veto delta was -11.3 pp in the early block and +10.23 pp in the late block.",
        "Large opposite signs across the two fixed blocks.",
        "NO_STABLE_OPPOSITE_ACTION",
        "CHRONOLOGICALLY_UNSTABLE",
        "Neither the veto nor its inversion is supported without outcome-conditioned timing.",
        ["research/market_behavior_os_v2/reports/HAB-CHX-DOWNREV-STRAT-001_strategy_translation.md"],
    ),
    family(
        "F24_CANDIDATE_RANK_MODELS",
        "Candidate information/rank-model translations",
        ["HAB-CHX-RANK-INFO-001", "HAB-CHX-RANK-MODEL-001"],
        "Registered candidate features should create stable cross-sectional ranking headroom.",
        "positive",
        "Information scans and bounded rank translations did not establish a stable, actionable ordering or gate.",
        "No robust favorable or opposite family-level structure survived the compact model comparisons.",
        "NO_RELIABLE_OPPOSITE_STRUCTURE",
        "TRUE_NULL",
        "A failed multivariate/ranking translation is not evidence for an inverted model.",
        [
            "research/market_behavior_os_v2/reports/HAB-CHX-RANK-INFO-001_information_scan.md",
            "research/market_behavior_os_v2/reports/HAB-CHX-RANK-MODEL-001_selection_report.md",
        ],
    ),
    family(
        "F25_QUIET_VWAP_EXECUTION",
        "Quiet VWAP Acceptance executable translation",
        ["ASHARE-INTRADAY-INDEP-CYCLE-004", "ASHARE-CA-REPLAY-003"],
        "Quiet VWAP acceptance may provide weak complementary stock-selection information.",
        "positive",
        "The cheap screen was weakly positive, but the canonical replay remained blocked by the long-suspension execution limitation.",
        "Information evidence exists; executable strategy economics were not scientifically completed.",
        "EXECUTION_STAGE_INCOMPLETE",
        "SCIENTIFICALLY_UNRESOLVED",
        "The correct status is unresolved executable translation, not null and not opposite-sign candidate.",
        [
            "research/market_behavior_os_v2/reports/ASHARE-INTRADAY-INDEP-CYCLE-004_report.md",
            "research/market_behavior_os_v2/reports/ASHARE-CA-REPLAY-003_report.md",
        ],
    ),
    family(
        "F26_CROSS_SECTIONAL_DISPERSION",
        "Cross-sectional Dispersion science and rank translation",
        ["MKT-DISP-ECON-001", "MKT-DISP-RANK-001", "MKT-DISP-RANK-002", "HAB-CHX-DISP-001"],
        "Dispersion may describe opportunity geometry and support a distinct Alpha translation.",
        "unresolved",
        "Economic-state evidence exists, but rank materialization/retry stopped at the resource gate; no completed opposite-sign or strategy conclusion exists.",
        "The outcome-bearing translation did not complete.",
        "RESOURCE_BLOCKED",
        "SCIENTIFICALLY_UNRESOLVED",
        "SCIENTIFICALLY_UNRESOLVED_RESOURCE_BLOCKED; it must remain on the frozen research frontier rather than be relabeled null.",
        [
            "research/market_behavior_os_v2/reports/MKT-DISP-ECON-001_dispersion_opportunity.md",
            "research/market_behavior_os_v2/reports/HAB-CHX-DISP-001_archaeology.md",
            "research/market_behavior_os_v2/experiments/MKT-DISP-RANK-001_spec.json",
            "research/market_behavior_os_v2/experiments/MKT-DISP-RANK-002_spec.json",
        ],
    ),
    family(
        "F27_PIT_FUNDAMENTALS",
        "PIT fundamental prior replication",
        ["ASHARE-FUNDAMENTAL-READINESS-CYCLE-006"],
        "Canonical value/quality/profitability/investment priors may transfer under PIT A-share semantics.",
        "unresolved",
        "No turnkey immutable-vintage PIT source with historical publication/restatement identity was available; no valid outcome experiment ran.",
        "Stopped before outcome research.",
        "DATA_BLOCKED",
        "SCIENTIFICALLY_UNRESOLVED",
        "PIT_FUNDAMENTALS remains DATA_BLOCKED_PARKED, not a scientific null.",
        ["research/market_behavior_os_v2/reports/ASHARE-FUNDAMENTAL-READINESS-CYCLE-006_report.md"],
    ),
    family(
        "F28_CANONICAL_IDIOSYNCRATIC_VOLATILITY",
        "Canonical factor-model idiosyncratic volatility",
        ["ASHARE-EVIDENCE-DEPTH-CYCLE-010"],
        "Canonical factor-residual IVOL should reproduce the low-risk prior.",
        "positive for low IVOL",
        "The exact canonical implementation was data-contract blocked; simpler proxy evidence must not substitute for it.",
        "Stopped before faithful canonical outcome research.",
        "DATA_BLOCKED",
        "SCIENTIFICALLY_UNRESOLVED",
        "The canonical prior remains scientifically unresolved even though proxy low-risk information is preserved separately.",
        ["research/market_behavior_os_v2/reports/ASHARE-EVIDENCE-DEPTH-CYCLE-010_report.md"],
    ),
]

TOP_CANDIDATES = [
    "F01_PRICE_LIMIT_STABLE_ACCEPTANCE",
    "F10_RELATIVE_RANK_ACCELERATION",
    "F11_SAME_MONTH_SEASONALITY",
]


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_families(families: list[dict[str, Any]], repo: Path) -> None:
    ids = [row["family_id"] for row in families]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate family_id")
    unknown = {row["audit_classification"] for row in families} - CLASSES
    if unknown:
        raise ValueError(f"unknown audit classifications: {sorted(unknown)}")
    missing = sorted(
        rel
        for row in families
        for rel in row["evidence_paths"]
        if not (repo / rel).is_file()
    )
    if missing:
        raise FileNotFoundError(f"missing evidence artifacts: {missing}")
    candidate_ids = {row["family_id"] for row in families if "NEEDS_ANATOMY" in row["audit_classification"]}
    if not set(TOP_CANDIDATES).issubset(candidate_ids):
        raise ValueError("top candidate is not classified NEEDS_ANATOMY")
    if len(TOP_CANDIDATES) > 3:
        raise ValueError("follow-up cap exceeded")


def inventory_experiment_ids(families: list[dict[str, Any]]) -> list[str]:
    return sorted({item for row in families for item in row["experiment_ids"]} | set(REFERENCE_ONLY_EXPERIMENTS))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            cooked = dict(row)
            for key, value in cooked.items():
                if isinstance(value, list):
                    cooked[key] = ";".join(value)
            writer.writerow({key: cooked.get(key, "") for key in fieldnames})


def render_report(result: dict[str, Any], families: list[dict[str, Any]]) -> str:
    by_class: dict[str, list[dict[str, Any]]] = {key: [] for key in sorted(CLASSES)}
    for row in families:
        by_class[row["audit_classification"]].append(row)

    lines = [
        "# A-Share Historical Opposite-Sign Closed-Family Audit V1",
        "",
        "## Executive conclusion",
        "",
        f"This artifact-only audit consolidated **{len(families)} families** from **{result['total_experiments_inventoried']} distinct experiment IDs**. "
        f"It found {result['class_counts']['TRUE_NULL']} true nulls, {result['class_counts']['CHRONOLOGICALLY_UNSTABLE']} chronologically unstable families, "
        f"{result['class_counts']['STABLE_ADVERSE_ALREADY_USED']} stable adverse families whose information was already used, "
        f"{result['stable_adverse_needs_anatomy_count']} stable adverse families that were under-analyzed, and "
        f"{result['class_counts']['SCIENTIFICALLY_UNRESOLVED']} unresolved families.",
        "",
        "No opposite-sign Alpha is established. The eight under-analyzed rows are avoidance questions, not demonstrated opposite long legs. Only three earn follow-up priority; all are labeled `POST_HOC_HYPOTHESIS_GENERATED_FROM_CONSUMED_DEVELOPMENT_HISTORY`.",
        "",
        "## Methodology correction",
        "",
        "A failed original hypothesis means the tested expected direction did not survive. A scientifically empty result requires more: no stable direction, no coherent adverse leg, and no unresolved blocker. Stable adverse information can support avoidance/risk anatomy even when it cannot support an opposite long strategy. Conversely, a negative spread does not prove that the opposite leg is profitable; leg-versus-baseline decomposition is mandatory.",
        "",
        "This audit read tracked compact artifacts only. It did not read raw outcome panels, post-2023 outcomes, or CY-011; it did not run new outcome aggregation, parameter rescue, or strategy replay.",
        "",
        "## Experiment ledger",
        "",
        f"The authoritative ledger is `{LEDGER_REL}`. Distinct experiment IDs include completed outcome work, blocked engineering attempts, and five shock/downside experiments inspected only as methodological references. Family consolidation prevents repeated implementations of one mechanism from inflating the scientific count.",
        "",
    ]
    headings = [
        ("TRUE_NULL", "TRUE_NULL families"),
        ("CHRONOLOGICALLY_UNSTABLE", "CHRONOLOGICALLY_UNSTABLE families"),
        ("STABLE_ADVERSE_ALREADY_USED", "STABLE_ADVERSE_ALREADY_USED"),
        ("STABLE_ADVERSE_LONG_CANDIDATE_NEEDS_ANATOMY", "STABLE_ADVERSE_LONG_CANDIDATE_NEEDS_ANATOMY"),
        ("STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY", "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY"),
        ("SCIENTIFICALLY_UNRESOLVED", "SCIENTIFICALLY_UNRESOLVED"),
    ]
    for key, heading in headings:
        lines.extend([f"## {heading}", ""])
        if not by_class[key]:
            lines.extend(["None.", ""])
            continue
        for row in by_class[key]:
            lines.append(f"- **{row['family_name']}** — {row['classification_reason']} Evidence: {row['observed_evidence']}")
        lines.append("")

    lines.extend(["## Named-family decisions", ""])
    lines.extend(
        [
            "- **Price-limit lifecycle:** stable/early acceptance is a post-hoc avoidance anatomy candidate; reopen/reseal is merely less bad and remains closed.",
            "- **Low Idio / Low Vol-of-Vol / Low Skewness:** adverse high-risk information was already preserved. Low Vol-of-Vol is partly redundant/industry-compositional; Low Skewness remains complementary defensive information.",
            "- **RS Acceleration veto:** stable adverse information was already used in the frozen admission component.",
            "- **Champion Confirmed Breakdown:** the no-exit decision is the completed scientific translation and remains closed.",
            "- **Minute leader/follower:** simultaneous co-movement only; true null for forward propagation.",
            "- **Cross-Sectional Dispersion:** `SCIENTIFICALLY_UNRESOLVED_RESOURCE_BLOCKED`, never null.",
            "",
            "## Top follow-up candidates",
            "",
        ]
    )
    lookup = {row["family_id"]: row for row in families}
    for rank, family_id in enumerate(TOP_CANDIDATES, 1):
        row = lookup[family_id]
        lines.extend(
            [
                f"### {rank}. {row['family_name']}",
                "",
                f"- Why: {row['classification_reason']}",
                f"- Existing evidence: {row['observed_evidence']}",
                f"- Still unknown: {row['spread_decomposition']}; the missing leg/year decomposition prevents any Alpha claim.",
                f"- Exact next anatomy: {row['next_anatomy']}",
                "- Estimated research cost: LOW (tracked compact artifacts; no full-market rebuild).",
                f"- Status label: `{CANDIDATE_LABEL}`.",
                "",
            ]
        )

    lines.extend(
        [
            "## Closed families that should remain closed",
            "",
            "Minute leader/follower, price-limit liquidity-transition variants, residual Sharpe, candidate rank models, revised momentum, 52-week-high/industry-momentum/intraday-reversal, overnight/daytime and low-turnover attention, close-location/gap absorption, industry-rotation 3x5, price-volume/liquidity recovery, downside-participation veto, and the fully audited downside/shock-recovery sequence should not be reopened. No neighboring thresholds, signs, horizons, filters, or alternative trading roles are authorized.",
            "",
            "The lower-priority adverse rows (FIP, residual asymmetry, support retest, intraday demand/acceptance, and chip structure) remain ledgered but do not earn immediate research capital. Their classification records information loss in the old binary pass/fail process; it does not mandate another experiment.",
            "",
            "## Next research recommendation",
            "",
            "Run one bounded **Price-limit stable-acceptance negative-leg anatomy** first. It has the broadest direct adverse topology and the clearest compact event evidence. If that anatomy shows only relative less-bad structure rather than intrinsic negative-leg information, do not cascade through all eight candidates: resume frozen Cross-Sectional Dispersion science. Relative-rank acceleration and same-month seasonality are the only reserve anatomies within the follow-up cap.",
            "",
            "## Governance conclusion",
            "",
            "The most important method gap was closing an original positive hypothesis on a spread without always recording each leg versus zero/event/date baseline and distinguishing an intrinsically bad favored leg from a genuinely profitable opposite leg. Future experiment templates should require that decomposition before a family is labeled economically null.",
            "",
        ]
    )
    return "\n".join(lines)


def build(repo: Path) -> dict[str, Any]:
    validate_families(FAMILIES, repo)
    spec_path = repo / SPEC_REL
    spec_hash = sha256_file(spec_path)
    counts = Counter(row["audit_classification"] for row in FAMILIES)
    experiment_ids = inventory_experiment_ids(FAMILIES)
    evidence_hashes = {
        rel: sha256_file(repo / rel)
        for rel in sorted({path for row in FAMILIES for path in row["evidence_paths"]})
    }
    result = {
        "experiment_id": EXPERIMENT_ID,
        "claim_boundary": "HISTORICAL_ARTIFACT_AUDIT_NOT_NEW_OUTCOME_RESEARCH_NOT_ALPHA_CONFIRMATION",
        "starting_checkpoint": START_HEAD,
        "frozen_spec_hash": spec_hash,
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "new_outcome_research_run": False,
        "raw_outcome_panel_read": False,
        "total_experiments_inventoried": len(experiment_ids),
        "experiment_ids": experiment_ids,
        "reference_only_experiment_ids": REFERENCE_ONLY_EXPERIMENTS,
        "total_families_audited": len(FAMILIES),
        "class_counts": {key: counts.get(key, 0) for key in sorted(CLASSES)},
        "stable_adverse_needs_anatomy_count": sum(
            counts.get(key, 0)
            for key in (
                "STABLE_ADVERSE_LONG_CANDIDATE_NEEDS_ANATOMY",
                "STABLE_ADVERSE_AVOIDANCE_CANDIDATE_NEEDS_ANATOMY",
            )
        ),
        "top_candidate_family_ids": TOP_CANDIDATES,
        "top_candidate_label": CANDIDATE_LABEL,
        "missed_opposite_sign_information_found": "YES_POST_HOC_AVOIDANCE_INFORMATION_NOT_CONFIRMED_ALPHA",
        "most_important_method_gap": "LEG_VERSUS_BASELINE_DECOMPOSITION_WAS_NOT_MANDATORY_BEFORE_ECONOMIC_NULL_CLOSURE",
        "next_recommended_research_direction": "ONE_PRICE_LIMIT_STABLE_ACCEPTANCE_NEGATIVE_LEG_ANATOMY_THEN_RESUME_FROZEN_DISPERSION_UNLESS_INTRINSIC_ADVERSE_LEG_IS_ESTABLISHED",
        "named_audits": {
            "price_limit_lifecycle": "STABLE_ACCEPTANCE_AVOIDANCE_CANDIDATE;_REOPEN_RESEAL_LESS_BAD_ONLY_CLOSED",
            "rs_acceleration_veto": "STABLE_ADVERSE_ALREADY_USED_PROMISING_ADMISSION_COMPONENT_FROZEN",
            "breakdown_exit": "STABLE_ADVERSE_ALREADY_USED_RETAIN_NO_EXIT_FROZEN",
            "minute_leader_follower": "TRUE_NULL_SIMULTANEOUS_COMOVEMENT_ONLY",
            "dispersion": "SCIENTIFICALLY_UNRESOLVED_RESOURCE_BLOCKED",
        },
        "evidence_artifact_hashes": evidence_hashes,
        "output_paths": {
            "spec": SPEC_REL,
            "ledger": LEDGER_REL,
            "candidate_table": CANDIDATE_REL,
            "report": REPORT_REL,
            "result": RESULT_REL,
        },
    }

    ledger_fields = [
        "family_id",
        "family_name",
        "experiment_ids",
        "original_hypothesis",
        "expected_sign",
        "observed_evidence",
        "consistency",
        "spread_decomposition",
        "audit_classification",
        "classification_reason",
        "candidate_priority",
        "candidate_label",
        "next_anatomy",
        "evidence_paths",
    ]
    write_csv(repo / LEDGER_REL, FAMILIES, ledger_fields)
    lookup = {row["family_id"]: row for row in FAMILIES}
    candidates = [dict(rank=index, **lookup[family_id]) for index, family_id in enumerate(TOP_CANDIDATES, 1)]
    write_csv(repo / CANDIDATE_REL, candidates, ["rank", *ledger_fields])
    report = render_report(result, FAMILIES)
    (repo / REPORT_REL).parent.mkdir(parents=True, exist_ok=True)
    (repo / REPORT_REL).write_text(report, encoding="utf-8")

    result["ledger_sha256"] = sha256_file(repo / LEDGER_REL)
    result["candidate_table_sha256"] = sha256_file(repo / CANDIDATE_REL)
    result["report_sha256"] = sha256_file(repo / REPORT_REL)
    result_path = repo / RESULT_REL
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(canonical_json_bytes(result))
    result["result_sha256"] = sha256_file(result_path)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = build(args.repo.resolve())
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
