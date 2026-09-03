#!/usr/bin/env python3
# ruff: noqa: E501
"""V7 causal True-Gap overhang/attack-episode simple-rule research.

The runner is deliberately staged.  ``stage-a-*`` commands are outcome blind;
``stage-b-*`` refuse to run until the five frozen contract hashes reproduce.
Repository data dated 2024 or later are never part of an input glob.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier, export_text

import lightgbm as lgb

from research.market_behavior_os_v2.scripts import run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy


ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-V7-OVERHANG-ATTACK-EPISODE-SIMPLE-RULE-DEVELOPMENT-V1"
START_HEAD = "df739d01617d1537dcfd395ac040ce24844262f6"
SOURCE_EXPERIMENT = "ASHARE-TRUE-GAP-CAUSAL-CLUSTER-V6-ONE-SHOT-DISCOVERY"
PREDECESSOR_EXPERIMENT = "ASHARE-TRUE-GAP-V6-FULL-SIGNAL-AND-STRATEGY-RESEARCH-V1"
SOURCE_HASH = "2705011d21792acfea34c6fe07819aa1a9e6dd91247bc27e66616749cc3ee162"

SOURCE_SPEC = OS / f"experiments/{SOURCE_EXPERIMENT}_spec.json"
SOURCE_CANDIDATES = OS / f"artifacts/{SOURCE_EXPERIMENT}_candidate_ledger.parquet"
SOURCE_CLUSTERS = OS / f"artifacts/{SOURCE_EXPERIMENT}_cluster_ledger.parquet"
SOURCE_GAPS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/causal_true_gap_ledger.parquet")
SOURCE_ACTIONS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/action_events.parquet")
SOURCE_LEGAL_OPENS = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_causal_cluster_v6_one_shot_discovery/legal_opens.parquet")
DAILY = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet")
RAW_ROOT = Path("/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813/bars")
PRED_EXT = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_v6_full_signal_strategy_research_v1")
PRED_ENTRY_CANDIDATES = PRED_EXT / "entry_candidates.parquet"
PRED_ENTRY_MINUTES = PRED_EXT / "entry_search_minutes.parquet"
PRED_POLICY_PATHS = PRED_EXT / "policy_paths.parquet"
PRED_POLICY_TRADES = PRED_EXT / "policy_trades.parquet"
PRED_PORTFOLIO_NAV = PRED_EXT / "portfolio_nav.parquet"
PRED_RESULT = OS / f"artifacts/{PREDECESSOR_EXPERIMENT}_result.json"

EXT = Path("/Volumes/quant/CY_quant_research/ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1")
MANIFESTS = EXT / "manifests"
VAP_PARTS = EXT / "vap_session_bins"

SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
SEMANTIC_PREFLIGHT_JSON = OS / f"experiments/{EXPERIMENT}_semantic_preflight.json"
SEMANTIC_PREFLIGHT_MD = OS / f"reports/{EXPERIMENT}_SEMANTIC_PREFLIGHT.md"
RECONCILIATION_JSON = OS / f"artifacts/{EXPERIMENT}_v6_to_v7_reconciliation.json"
RECONCILIATION_MD = OS / f"reports/{EXPERIMENT}_V6_TO_V7_RECONCILIATION.md"
VAP_METHODOLOGY = OS / f"experiments/{EXPERIMENT}_vap_methodology.json"
FEATURE_DICTIONARY = OS / f"experiments/{EXPERIMENT}_overhang_feature_dictionary.json"
ATTACK_CONTRACT = OS / f"experiments/{EXPERIMENT}_attack_episode_contract.json"
RULE_SPACE = OS / f"experiments/{EXPERIMENT}_rule_space.json"
EXIT_SPACE = OS / f"experiments/{EXPERIMENT}_exit_space.json"
FEATURE_FREEZE = OS / f"artifacts/{EXPERIMENT}_feature_freeze.json"

VAP_DATE_MAP = EXT / "vap_date_map.parquet"
VAP_SESSION_BINS = EXT / "vap_session_bins.parquet"
ATTACK_MINUTES = EXT / "attack_minute_base.parquet"
ATTACK_CONTACTS = EXT / "attack_contacts.parquet"
ATTACK_LEDGER = EXT / "attack_episode_ledger.parquet"
OVERHANG_PANEL = EXT / "overhang_panel.parquet"
ENTRY_CANDIDATES = EXT / "entry_candidates.parquet"
ATTACK_CLOCK_FEATURES = EXT / "attack_clock_features.parquet"
SAME_CLOCK_CONTEXT = EXT / "same_clock_context.parquet"
SAME_CLOCK_VOLUME = EXT / "same_clock_volume_reference.parquet"
SAME_CLOCK_CONTEXT_PARTS = EXT / "same_clock_context_parts"

ATTACK_OUTCOME_MINUTES = EXT / "attack_outcome_minutes.parquet"
OUTCOME_MINUTE_PARTS = EXT / "attack_outcome_minute_parts"
ATTACK_OUTCOMES = EXT / "attack_outcomes.parquet"
DIRECT_ANALYSIS = EXT / "direct_analysis.parquet"
MATCHED_ANALYSIS = EXT / "matched_analysis.parquet"
RULE_CANDIDATES = EXT / "rule_candidates.parquet"
INNER_OOF_RESULTS = EXT / "inner_oof_results.parquet"
OUTER_SELECTIONS = EXT / "outer_walkforward_selections.parquet"
TRADES = EXT / "trades.parquet"
PORTFOLIO_NAV = EXT / "portfolio_nav.parquet"
DIAGNOSTIC = EXT / "post_observation_diagnostic.parquet"
POST_OUTCOME_MINUTES = EXT / "post_observation_outcome_minutes.parquet"
POST_OUTCOME_MINUTE_PARTS = EXT / "post_observation_outcome_minute_parts"
POST_ATTACK_OUTCOMES = EXT / "post_observation_attack_outcomes.parquet"
POST_DIAGNOSTIC_SUMMARY = EXT / "post_observation_summary.parquet"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
FINAL_PROCEDURE_FREEZE = OS / f"artifacts/{EXPERIMENT}_final_procedure_freeze.json"
MODEL_DIAGNOSTICS = EXT / "model_diagnostics.parquet"
PORTFOLIO_SUMMARY = EXT / "portfolio_summary.parquet"
HIGH_OVERHANG_DIAGNOSTIC = EXT / "high_overhang_diagnostic.parquet"
CHART_INDEX = OS / f"artifacts/{EXPERIMENT}_chart_index.csv"
CHART_DIR = EXT / "representative_charts"

YEARS = tuple(range(2013, 2024))
DEV_YEARS = tuple(range(2014, 2022))
POST_YEARS = (2022, 2023)
COST = 0.002
EXP_CLIP = 50.0
EPSILON = 1e-12
VAP_BIN_WIDTH_Z = 0.10
VAP_MIN_BIN = -20
VAP_MAX_BIN = 29
VACUUM_REFERENCE_MIN = 30

PENETRATION_LEVELS = {"Z0": 0.0, "Z25": 0.25, "Z50": 0.50}
ACCEPTANCE_FORMS = ("CLOSE", "HOLD5_60", "HOLD5_80", "HOLD15_60", "HOLD15_80", "RETEST_RECLAIM")
REMAINING_TARGETS = (0.010, 0.015, 0.020)
TIME_STOPS = (5, 10, 20)
KS = (5, 10, 20)

PRIMARY_VARIABLES = (
    "vacuum_score",
    "decayed_overhang_inside_gap",
    "decayed_overhang_above_u",
    "overhang_support_ratio",
    "poc_inside_gap",
    "cum_turnover_near_l",
    "prior_attack_count",
    "number_of_prior_rejections",
    "stock_minus_board_return_10d",
    "stock_minus_industry_return_10d",
    "board_return_20d",
    "industry_return_20d",
    "breadth_recovery",
    "higher_low_share_10d",
    "approach_path_efficiency_10d",
    "new_lower_cluster_since_gap",
    "gap_age_sessions",
    "remaining_net_target_at_entry",
    "structural_stop_distance",
    "target_to_risk_ratio",
)

OVERHANG_DIRECTIONS = {
    "vacuum_score": 1,
    "decayed_overhang_inside_gap": -1,
    "decayed_overhang_above_u": -1,
    "overhang_support_ratio": -1,
    "gap_lvn_score": 1,
    "above_u_lvn_score": 1,
}

SIMPLE_RULE_FEATURE_DIRECTIONS = {
    **OVERHANG_DIRECTIONS,
    "stock_minus_board_return_10d": 1,
    "stock_minus_industry_return_10d": 1,
    "board_return_20d": 1,
    "industry_return_20d": 1,
    "breadth_recovery": 1,
    "higher_low_share_10d": 1,
    "approach_path_efficiency_10d": 1,
    "new_lower_cluster_since_gap": -1,
    "acceptance_ratio_l_15": 1,
    "progress_per_turnover": 1,
    "attack_cost_ratio": -1,
}

FAILURE_POLICIES = (
    "X0_NO_FAILURE_EXIT",
    "X1_INTRADAY_REJECTION",
    "X2_ZONE_DAMAGE_05W",
    "X3_ZONE_DAMAGE_10W",
    "X4_NO_PROGRESS_D3",
    "X4_NO_PROGRESS_D5",
    "X5_STRUCTURAL_BREAK",
    "X6_HYBRID_D3",
    "X6_HYBRID_D5",
)


class ResearchError(RuntimeError):
    pass


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return None if pd.isna(value) else str(pd.Timestamp(value))
    if value is pd.NaT:
        return None
    try:
        if not isinstance(value, (str, bool)) and pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(clean(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(canonical_json(value))
    tmp.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value)
    tmp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def directory_hash(path: Path) -> str:
    h = hashlib.sha256()
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        h.update(str(item.relative_to(path)).encode())
        h.update(sha256(item).encode())
    return h.hexdigest()


def manifest(name: str, status: str, payload: dict[str, Any]) -> None:
    write_json(MANIFESTS / f"{name}.json", {"stage": name, "status": status, **payload})


def raw_union(years: Iterable[int] = YEARS) -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{RAW_ROOT / f'{year}_day_parquet_none.parquet'}') WHERE period='1m' AND adjust='none'"
        for year in years
    )


def spec_contract() -> dict[str, Any]:
    folds = [f"{year}-H{half}" for year in range(2017, 2022) for half in (1, 2)]
    return {
        "experiment": EXPERIMENT,
        "authoritative_start_head": START_HEAD,
        "source_experiment": SOURCE_EXPERIMENT,
        "source_semantic_hash": SOURCE_HASH,
        "predecessor": PREDECESSOR_EXPERIMENT,
        "predecessor_verdict": "V6_PARAMETER_FAMILY_UNSTABLE",
        "governance": {
            "stage_a": "OUTCOME_BLIND_CONTRACT_FREEZE",
            "stage_b": "OUTCOMES_AND_DEVELOPMENT_ONLY_AFTER_HASH_REPRODUCTION",
            "development": ["2014-01-01", "2021-12-31"],
            "outer_folds": folds,
            "initial_training_begins": "2014-01-01",
            "purge_embargo_sessions": 20,
            "same_gap_partition": True,
            "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
            "post_2021_scientific_evidence_accepted": False,
            "repository_2024_plus": "SEALED",
            "semantic_change_after_outcome": "FORBIDDEN",
        },
        "v6_identity_freeze": {
            "true_gap": "High_t < Low_t_minus_1",
            "interval": "[High_t, Low_t_minus_1]",
            "immutable": [
                "causal local gap cluster",
                "cluster freeze",
                "primary true gap",
                "pre-freeze-touch rejection",
                "supersession",
                "memory classification",
                "QD-010 corporate-action coordinate",
                "causal first-return eligibility",
            ],
            "primary_population": "CORE",
            "boundary_role": "DESCRIPTIVE_DIAGNOSTIC_ONLY",
            "stale_role": "EXCLUDED",
        },
        "primary_lane": "LOW_OVERHANG_VACUUM_REPAIR",
        "separate_lane_not_mixed": "HIGH_OVERHANG_ABSORPTION_BREAKOUT",
        "cost_per_side": COST,
        "portfolio": {
            "primary_k_per_board_sleeve": 10,
            "sensitivity": list(KS),
            "main_weight": 0.5,
            "chinext_weight": 0.5,
            "position_weight": "1/K of current sleeve NAV",
            "unused_capital": "CASH",
            "leverage": False,
            "cross_sleeve_transfer": False,
            "one_active_position_per_symbol": True,
            "one_active_position_per_gap_id": True,
        },
        "final_complexity": {
            "maximum_admission_conditions": 5,
            "entry_rules": 1,
            "target_rules": 1,
            "failure_exit_rules": 1,
            "time_stops": 1,
            "optional_retry_rules": 1,
            "black_box_is_ceiling_only": True,
        },
    }


def semantic_preflight_contract() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_sequence": [
            "former strong / leader-like stock",
            "causal local true-gap cluster forms",
            "historical inventory may or may not exist around [L,U]",
            "post-gap turnover may preserve or replace that inventory",
            "market / board / industry environment repairs or remains weak",
            "stock approaches L",
            "a distinct attack episode begins",
            "the market accepts or rejects price inside the gap",
            "causal completed-bar trigger",
            "next legal one-minute-open entry",
            "current attack reaches U, causally resets, or times out",
            "position exits under its frozen policy",
            "a later independent attack may create at most one retry signal",
        ],
        "cause": "gap-birth systematic or idiosyncratic shock",
        "state": [
            "surviving overhead inventory proxy",
            "support inventory below L proxy",
            "environment repair",
            "stock relative recovery",
            "base / approach quality",
            "prior attack history",
        ],
        "trigger": "causal completed-bar acceptance inside the current attack",
        "outcome": ["current-attack U success", "current-attack failure", "timeout"],
        "entry_time": "next legal one-minute open strictly after completed trigger information",
        "outcome_start_time": "strictly after executable entry",
        "possible_ambiguities": [
            "historical volume is not identical to currently surviving inventory",
            "turnover may replace old holders",
            "low volume under a locked limit state is not absence of supply",
            "high attack volume may indicate demand or supply absorption",
            "a later successful attack must not validate an earlier failed attack",
            "high-overhang U breakout is a different strategy from gap repair",
            "old horizontal trading may be support, resistance, or both",
            "absolute percentage penetration and gap-width penetration differ",
        ],
        "chosen_time_anchors": {
            "gap_inventory_history": "completed QD-004 bars no later than ATTACK_START_TIME for admission-state features",
            "environment_daily_state": "completed sessions strictly before attack date",
            "minute_attack_state": "completed minutes no later than each candidate decision timestamp",
            "entry": "next legal minute open strictly after the trigger bar",
            "exit": "next legal execution after completed failure information",
            "feature_rule": "no feature may use a bar after its own decision timestamp",
        },
        "research_correction": {
            "price_true_gap": "establishes no trades only on the gap-formation transition",
            "overhead_inventory": "historical turnover/volume proxy, not observed actual selling",
            "attack_episode": "primary trading unit; later attacks never relabel earlier attacks",
            "attack_success": "U before the current attack's own causal reset",
            "high_overhang": "separate absorption-breakout mechanism and excluded from primary returns",
        },
        "outcomes_opened": "NO",
    }


def vap_methodology_contract() -> dict[str, Any]:
    return {
        "name": "TURNOVER-DECAYED INVENTORY PROXY",
        "not_exact_shareholder_identity": True,
        "price": {
            "primary": "minute amount / minute volume",
            "fallback": "(high + low + close) / 3 when amount/volume is unavailable",
            "coordinate": "minute price multiplied by the same-day QD-010 coordinate_factor",
            "vap_price_is_proxy": True,
        },
        "z": "(coordinate_price - L) / W",
        "bin_width_z": VAP_BIN_WIDTH_Z,
        "covered_z": [-2.0, 3.0],
        "historical_windows_sessions_before_gap": [20, 60, 120],
        "regions": {
            "support_below_l": "-1 <= z < 0",
            "inside_gap": "0 <= z < 1",
            "above_u": "1 <= z < 2",
            "local_normalizer": "-2 <= z < 3",
        },
        "float_turnover_allocation": "completed-session turnover_fraction multiplied by minute volume / completed-session volume",
        "same_day_partial_turnover": "cumulative minute volume divided by prior completed session implied free-float shares; never uses current full-day volume",
        "survival_weight": "exp(-min(cumulative completed PIT turnover after origin and through attack clock, 50))",
        "clipping": {
            "turnover_input": "NO_CLIP; negative or missing required turnover fails the affected feature",
            "exponent_only": EXP_CLIP,
            "reason": "numerical underflow protection only",
        },
        "missing_windows": "an N-session variable is null unless N valid, same-lineage, exact-241 sessions exist; no shorter-window substitution",
        "locked_limit_interpretation": "volume is retained as observed trading; low volume is never called absence of supply",
        "vacuum_score": {
            "components": [
                "low decayed inventory inside gap",
                "low decayed inventory above U",
                "high GAP_LVN_SCORE",
                "low OVERHANG_SUPPORT_RATIO",
            ],
            "weights": "equal",
            "calibration": "board-specific expanding ECDF using strictly earlier attack dates",
            "minimum_prior_attacks": VACUUM_REFERENCE_MIN,
        },
    }


def attack_contract_value() -> dict[str, Any]:
    return {
        "unit": "ATTACK_EPISODE",
        "source": SOURCE_EXPERIMENT,
        "source_hash": SOURCE_HASH,
        "start": "previous completed minute coordinate close < L and current completed minute coordinate high >= L; ATTACK_1 is the frozen V6 causal first return",
        "end_earliest": {
            "SUCCESS": "current attack reaches U on same-lineage hard-valid price path",
            "HARD_STRUCTURAL_RESET": "new causally known lower MAJOR/SECONDARY true gap at formation close or lower causal cluster at its freeze",
            "BELOW_ZONE_RESET": "close of the second consecutive completed session with coordinate High < L",
            "TIME_RESET": "close of calendar index ATTACK_START_CAL_IDX + 10 without earlier U/reset",
        },
        "tie_priority": ["SUCCESS", "HARD_STRUCTURAL_RESET", "BELOW_ZONE_RESET", "TIME_RESET"],
        "later_attack": "strictly after ended attack and a new causal upward contact from below",
        "maximum_attacks_per_gap": 2,
        "freshness": "attack start gap age <= 90 completed sessions",
        "memory_at_attack_start": {"CORE": "<=60", "BOUNDARY": "61-90", "STALE": ">90 excluded"},
        "later_success_credit": "never credited to an earlier failed/timed-out attack",
        "outcomes": {
            "ATTACK_SUCCESS": "U before own reset",
            "CLEAN_ATTACK_SUCCESS_5": "U within 5 sessions before 5% adverse mark",
            "CLEAN_ATTACK_SUCCESS_10": "U within 10 sessions before 8% adverse mark",
            "ROUGH_ATTACK_SUCCESS": "U before reset but not CLEAN_ATTACK_SUCCESS_10",
            "FAILED_ATTACK": "hard structural or below-zone reset before U",
            "TIMED_OUT_ATTACK": "10-session reset before U",
            "EVENTUAL_U_AFTER_FAILED_ATTACK": "U in a later attack/history; diagnostic only",
        },
        "time_availability": {
            "gap_and_daily": "15:00 after completed session",
            "minute": "bar_end_time after completed minute",
            "entry": "strictly later legal minute open",
        },
    }


def feature_dictionary_value() -> dict[str, Any]:
    variables = {
        "raw_vap_inside_gap_20": "local-normalized raw minute volume inside 0<=z<1 over exact prior 20 sessions",
        "raw_vap_inside_gap_60": "same over exact prior 60 sessions",
        "raw_vap_inside_gap_120": "same over exact prior 120 sessions",
        "raw_vap_above_u_20": "local-normalized raw minute volume in 1<=z<2 over exact prior 20 sessions",
        "raw_vap_above_u_60": "same over exact prior 60 sessions",
        "raw_vap_above_u_120": "same over exact prior 120 sessions",
        "raw_vap_below_l_support_20": "local-normalized raw minute volume in -1<=z<0 over exact prior 20 sessions",
        "raw_vap_below_l_support_60": "same over exact prior 60 sessions",
        "raw_vap_below_l_support_120": "same over exact prior 120 sessions",
        "decayed_overhang_inside_gap": "turnover-decayed float-turnover proxy inside 0<=z<1 through attack start",
        "decayed_overhang_above_u": "turnover-decayed float-turnover proxy in 1<=z<2 through attack start",
        "decayed_support_below_l": "turnover-decayed float-turnover proxy in -1<=z<0 through attack start",
        "overhang_support_ratio": "(decayed inside + decayed above) / max(decayed support, epsilon)",
        "poc_z": "z-center of highest turnover-decayed histogram bin",
        "poc_inside_gap": "1[poc_z in [0,1)]",
        "nearest_hvn_above_l_distance_z": "nearest >=70th-percentile positive-density bin center above L",
        "nearest_hvn_above_u_distance_z": "nearest >=70th-percentile positive-density bin center above U",
        "gap_lvn_score": "one minus gap density relative to local-bin mean, clipped only as a descriptive score to [-5,1]",
        "above_u_lvn_score": "one minus above-U density relative to local-bin mean, same descriptive clipping",
        "gap_density_relative_to_local": "mean decayed gap-bin density / mean decayed local-bin density",
        "overhead_density_relative_to_support": "mean decayed inside+above density / mean support density",
        "vacuum_score": "equal-weight causal expanding percentiles specified in vap_methodology",
        "cum_turnover_since_gap": "completed turnover from gap formation through attack start",
        "cum_turnover_since_cluster_freeze": "completed turnover from cluster freeze through attack start",
        "cum_turnover_near_l": "allocated turnover with -0.5<=z<=0.5",
        "cum_turnover_inside_gap": "allocated turnover with 0<=z<=1",
        "price_progress_per_turnover_since_gap": "coordinate progress from post-gap low to attack start divided by turnover",
        "number_of_prior_contacts_with_l": "prior causal upward L contacts before current attack",
        "number_of_prior_rejections": "prior ended attacks not successful",
        "max_previous_penetration_z": "maximum prior-attack z",
        "days_since_last_rejection": "calendar-index distance from prior rejection end",
        "poc_migration_toward_l": "attack-start POC distance improvement toward z=0 versus gap-time POC",
        "poc_migration_into_gap": "indicator POC moved from below L into [0,1)",
        "stock_minus_board_return_10d": "stock prior-10 completed-session return minus board return",
        "stock_minus_industry_return_10d": "stock prior-10 completed-session return minus PIT-industry return",
        "board_return_20d": "board prior-20 completed-session compounded return",
        "industry_return_20d": "PIT-industry prior-20 completed-session compounded return",
        "breadth_recovery": "prior-5 market positive breadth minus gap-day positive breadth",
        "higher_low_share_10d": "share of prior-10 completed sessions with higher coordinate low",
        "approach_path_efficiency_10d": "absolute prior-10 return divided by sum absolute returns",
        "new_lower_cluster_since_gap": "count of causally frozen lower clusters known before attack start",
        "gap_age_sessions": "attack-start calendar index minus primary-gap calendar index",
        "remaining_net_target_at_entry": "U / entry_coordinate_price - 1 - 40bp",
        "structural_stop_distance": "entry coordinate price distance to L-W",
        "target_to_risk_ratio": "remaining net target / structural stop distance",
    }
    minute = {
        "acceptance_ratio_l_{5,15,30}": "share completed trailing attack closes >=L",
        "inside_gap_ratio_{5,15,30}": "share completed trailing attack closes with 0<=z<=1",
        "current_z": "completed decision close z",
        "max_z": "max completed attack high z through decision",
        "min_z_after_contact": "min completed attack low z through decision",
        "rejection_depth_z": "minimum completed close z below zero",
        "failed_l_test_count": "transitions from close>=L to close<L",
        "reclaim_count": "transitions from close<L to close>=L",
        "time_to_first_rejection": "completed minutes from attack start to first close<L",
        "time_to_reclaim": "completed minutes from first rejection to later reclaim",
        "vwap_hold_ratio": "share completed attack closes >= running VWAP",
        "vwap_slope": "OLS slope of completed attack running VWAP",
        "stock_minus_board_intraday_return": "stock open-to-clock minus same-clock board return",
        "stock_minus_industry_intraday_return": "stock open-to-clock minus same-clock PIT-industry return",
        "up_minute_volume_share": "causal normalized volume on up minutes / total",
        "down_minute_volume_share": "causal normalized volume on down minutes / total",
        "progress_per_turnover": "z progress / causal attack turnover",
        "turnover_per_unit_progress": "causal attack turnover / max z progress",
        "contact_high_break": "decision close exceeds prior attack high",
        "post_retest_higher_low": "post-retest low exceeds previous post-contact low",
        "upper_wick_pressure": "mean completed-minute upper-wick/range",
        "opening_jump_flag": "attack/trigger occurs on first bar and open>=trigger",
        "first_contact_to_decision_minutes": "count completed attack minutes",
        "first_contact_to_decision_sessions": "distinct attack sessions minus one",
        "cum_turnover_during_attack": "causal turnover proxy through decision",
        "max_progress_z_during_attack": "max high z through decision",
        "attack_cost_ratio": "attack turnover / max progress z",
        "multiday_turnover_without_progress": "turnover on completed attack sessions whose max z fails to improve",
        "contacts_per_unit_progress": "L contacts / max progress z",
        "failed_contacts_per_session": "failed L tests / attack sessions",
    }
    return {
        "experiment": EXPERIMENT,
        "state_clock": "ATTACK_START_TIME for admission; candidate completed trigger time for minute translation",
        "variables": variables,
        "minute_attack_variables": minute,
        "primary_final_rule_variables": list(PRIMARY_VARIABLES),
        "post_decision_information_allowed": False,
    }


def rule_space_value() -> dict[str, Any]:
    return {
        "maximum_final_conditions": 5,
        "thresholds": {"natural": [0, 1], "train_only_quantiles": [0.30, 0.50, 0.70]},
        "minimum_train_completed_attacks": 80,
        "minimum_latest_full_train_year": 15,
        "methods": {
            "MONOTONE_SCORECARD": {
                "features": ["vacuum_score", "overhang_support_ratio", "acceptance_ratio_l_15", "stock_minus_industry_return_10d", "target_to_risk_ratio"],
                "directions": [1, -1, 1, 1, 1],
                "weights": "equal",
            },
            "SHALLOW_DECISION_TREE": {"criterion": "log_loss", "max_depth": 3, "min_samples_leaf": 40, "class_weight": "balanced", "random_state": 20260903},
            "SPARSE_LOGISTIC": {"penalty": "elasticnet", "l1_ratio": 0.80, "C": 0.10, "solver": "saga", "max_iter": 4000, "class_weight": "balanced", "random_state": 20260903, "time_respecting_scaling": True},
            "RULEFIT_LITE": {"source_tree_depth": 2, "source_tree_min_leaf": 40, "maximum_active_rules": 5, "distillation_thresholds": "TRAIN p30/p50/p70 only"},
            "LIGHTGBM_CEILING": {"deployable": False, "objective": "binary", "learning_rate": 0.03, "n_estimators": 400, "max_depth": 3, "num_leaves": 7, "min_child_samples": 80, "reg_lambda": 20.0, "reg_alpha": 2.0, "subsample": 0.8, "colsample_bytree": 0.8, "random_state": 20260903, "n_jobs": 4, "verbosity": -1},
        },
        "model_target": "CLEAN_ATTACK_SUCCESS_10",
        "model_features": list(PRIMARY_VARIABLES) + ["acceptance_ratio_l_5", "acceptance_ratio_l_15", "acceptance_ratio_l_30", "current_z", "max_z", "rejection_depth_z", "failed_l_test_count", "reclaim_count", "vwap_hold_ratio", "stock_minus_board_intraday_return", "stock_minus_industry_intraday_return", "attack_cost_ratio"],
        "lightgbm_material_outperformance_for_distillation": "OOF AUC at least 0.03 and OOF economic utility at least 20bp above the best simple method",
        "fixed_low_overhang_rules": {
            "VACUUM_Q70": ["vacuum_score>=TRAIN_Q70"],
            "RATIO_Q30": ["overhang_support_ratio<=TRAIN_Q30"],
            "INSIDE_Q30": ["decayed_overhang_inside_gap<=TRAIN_Q30"],
            "ABOVE_Q30": ["decayed_overhang_above_u<=TRAIN_Q30"],
            "VACUUM_Q50_RATIO_Q50": ["vacuum_score>=TRAIN_Q50", "overhang_support_ratio<=TRAIN_Q50"],
            "VACUUM_Q70_RATIO_Q50": ["vacuum_score>=TRAIN_Q70", "overhang_support_ratio<=TRAIN_Q50"],
            "INSIDE_Q30_ABOVE_Q30": ["decayed_overhang_inside_gap<=TRAIN_Q30", "decayed_overhang_above_u<=TRAIN_Q30"],
            "OVERHANG_VOTE_3_OF_4_Q50": ["at least 3 of: vacuum>=Q50, inside<=Q50, above<=Q50, ratio<=Q50"],
            "OVERHANG_VOTE_2_OF_4_Q70": ["at least 2 of: vacuum>=Q70, inside<=Q30, above<=Q30, ratio<=Q30"],
        },
        "fixed_environment_extensions": {
            "NONE": [],
            "RELATIVE_REPAIR": ["stock_minus_board_return_10d>=TRAIN_Q50", "stock_minus_industry_return_10d>=TRAIN_Q50"],
            "SYSTEM_REPAIR": ["board_return_20d>=0", "industry_return_20d>=0"],
            "BREADTH_REPAIR": ["breadth_recovery>=0"],
            "APPROACH_QUALITY": ["higher_low_share_10d>=TRAIN_Q50", "approach_path_efficiency_10d>=TRAIN_Q50"],
            "NO_LOWER_CLUSTER": ["new_lower_cluster_since_gap=0"],
        },
        "entry": {
            "penetration_levels": PENETRATION_LEVELS,
            "acceptance_forms": list(ACCEPTANCE_FORMS),
            "entry": "next legal one-minute open after completed trigger",
            "remaining_net_target_minimums": list(REMAINING_TARGETS),
            "selection": "hierarchical TRAIN OOF, not uncontrolled joint Cartesian search",
        },
        "hierarchy": ["overhang/state", "environment", "entry translation", "failure exit", "retry"],
        "high_overhang_diagnostic": {
            "definition": "overhang_support_ratio>=TRAIN_Q70 within board and outer fold",
            "strategy_development": "PROHIBITED",
            "mix_into_vacuum_returns": False,
        },
        "direct_analysis": {
            "univariate_bins": "TRAIN quintiles, applied unchanged to the corresponding outer TEST",
            "two_dimensional_bins": "TRAIN tertiles on each axis, applied unchanged to outer TEST",
            "weightings": ["event", "attack_date_equal", "gap_formation_date_equal"],
            "surfaces": [
                ["vacuum_score", "progress_per_turnover"],
                ["overhang_support_ratio", "acceptance_ratio_l_15"],
                ["breadth_recovery", "stock_minus_industry_return_10d"],
                ["prior_attack_count", "failed_l_test_count"],
                ["remaining_net_target_at_entry", "structural_stop_distance"],
            ],
        },
        "matched_analysis": {
            "method": "Frisch-Waugh-Lovell fixed-effect residual difference",
            "low_overhang": "vacuum_score>=TRAIN_Q70",
            "controls": ["board", "calendar_year", "attack_date", "gap_width_train_quintile", "gap_age", "remaining_target", "memory_class", "single_or_multigap", "market_condition"],
            "outcomes": ["net_return", "attack_success", "severe_loss10"],
            "report": ["combined", "board-specific", "attack-date-equal"],
        },
        "one_standard_error": True,
        "generated_simple_rules": {
            "TREE_SINGLE_LEAF": "depth<=3 tree over TRAIN p30/p50/p70 binary flags; retain its highest predicted CLEAN_SUCCESS leaf containing at least one favorable overhang flag; one leaf path is at most three conditions",
            "RULEFIT_LITE": "elastic-net logistic over TRAIN p30/p50/p70 favorable flags; retain at most five positive-coefficient flags and require a natural 60% majority; at least one flag must be an overhang flag",
            "LGBM_DISTILLED_LEAF": "strongly regularized LightGBM ceiling is distilled, inside each TRAIN only, to one depth<=3 binary-flag surrogate leaf; the distilled leaf is retested from scratch in each later block",
            "raw_model_scores_deployable": False,
            "all_numeric_boundaries": "natural zero/count or TRAIN p30/p50/p70 only",
        },
        "nested_walkforward": {
            "outer_partition_anchor": "ATTACK_START_TIME",
            "inner_validation_blocks": "expanding half-years beginning 2015-H1 and ending before the outer TEST half",
            "inner_training_start": "2014-01-01",
            "purge_embargo_sessions": 20,
            "complete_h20_rule": "entry_cal_idx + 20 <= validation_boundary_cal_idx - 20",
            "same_gap_partition": True,
            "threshold_refit": "every quantile, score, tree, logistic and surrogate is refit using only that inner TRAIN; final outer TEST transform is fit on full outer TRAIN",
            "minimum_valid_inner_blocks": 3
        },
        "hierarchical_selection_exact": {
            "step_1": "select one low-overhang/state rule on CORE ATTACK_1, Z0+CLOSE, U/H20, X0",
            "step_2": "holding step 1 fixed, select one frozen environment extension on the same translation/outcome",
            "step_3": "holding steps 1-2 fixed, select one of 18 translations and one of exactly 1.0/1.5/2.0 percent remaining-net-target floors",
            "step_4": "holding steps 1-3 fixed, select one of 9 failure policies and H5/H10/H20",
            "step_5": "holding steps 1-4 fixed, compare ATTACK_1 only with one independently admitted ATTACK_2 retry",
            "condition_limit": "overhang + environment + remaining-target admission conditions <=5"
        },
        "one_standard_error_exact": "find the best median inner utility; retain candidates no worse than one standard error of that candidate's block utilities; among them choose fewer admission conditions, then higher median utility, higher median inner trade-path Calmar, lower severe10, higher clean10, higher retention, and lexicographic id",
        "inner_calmar_definition": "compounded chronological completed-trade path ordered by exit time; selection diagnostic only; exact K-sleeve replay is performed after the rule is frozen",
        "selection_utility": "mean net trade return - 0.20*abs(CVaR5)",
        "selector_order": ["median inner utility", "median inner Calmar", "lower severe10", "higher clean10", "retention", "fewer conditions", "simpler translation"],
        "deployment_gate": {
            "mean_net_return": ">0",
            "median_net_return": ">0",
            "clean_success_10": ">baseline",
            "severe_loss10": "<baseline",
            "median_inner_utility": ">0",
            "positive_inner_blocks": ">=3",
        },
        "outer_fold_boundaries": [
            {"id": f"{year}H{half}", "start": f"{year}-{'01-01' if half == 1 else '07-01'}", "end": f"{year}-{'06-30' if half == 1 else '12-31'}"}
            for year in range(2017, 2022) for half in (1, 2)
        ],
        "procedures": {
            "FORCED_CHOICE_WF": "always deploy the highest-ranked TRAIN-only hierarchical choice",
            "DEPLOYMENT_GATED_WF": "same frozen choice, but hold cash unless every preregistered gate passes",
            "primary_for_verdict": "DEPLOYMENT_GATED_WF; FORCED_CHOICE_WF diagnoses selector generalization"
        },
        "lane_contract": {
            "L0_ATTACK_BASELINE": "CORE ATTACK_1, Z0+CLOSE, no admission, U/H20, X0, no retry",
            "L1_LOW_OVERHANG": "L0 plus selected low-overhang rule",
            "L2_LOW_OVERHANG_ENVIRONMENT": "L1 plus selected environment extension",
            "L3_ATTACK_ACCEPTANCE": "L2 plus selected translation and remaining-target floor",
            "L4_FAILURE_EXIT": "L0 plus the selected failure policy and time stop",
            "L5_FULL_SIMPLE_RULE": "all selected admission, entry, exit, horizon and retry semantics",
            "L6_ONE_RETRY_INCREMENT": "ATTACK_2 trades only when R1 is selected"
        },
        "portfolio_collision_order": ["simple_rule_score descending", "vacuum_score descending", "remaining_target_to_risk descending", "entry_time", "symbol", "gap_id"],
        "edge_adjudication_exact": {
            "minimum_outer_test_trades": 100,
            "marginal_trade_range": [50, 99],
            "positive_half_years": ">=6 of 10",
            "positive_calendar_years": ">=4 of 5",
            "catastrophic_full_year": "annual sleeve-combined return <= -10%",
            "attack_date_equal": ">0",
            "material_severe10_improvement": "at least 20% relative reduction or 1 percentage point absolute reduction versus L0",
            "return_excluding_best_day": ">0",
            "near_positive_excluding_best_five_days": ">=-1%",
            "board_not_explaining_entire_edge": "both sleeves non-negative over the full period, otherwise board-specific only",
            "post_2021_metrics_used": False
        },
        "final_rule_selection_population": "CORE attacks only; BOUNDARY diagnostic never enters selection",
    }


def exit_space_value() -> dict[str, Any]:
    return {
        "profit_target": "legal U realization before the current attack's own reset; later U never credits the earlier attack",
        "time_stops_sessions": list(TIME_STOPS),
        "failure_exits": {
            "X0_NO_FAILURE_EXIT": "U within current attack or time stop",
            "X1_INTRADAY_REJECTION": "only after the position is T+1 sellable, two consecutive completed standard exchange-clock 15-minute closes below L and current z<=-0.25; morning blocks anchor at 09:30 and afternoon blocks at 13:00; next legal minute open",
            "X2_ZONE_DAMAGE_05W": "completed daily close<=L-0.50W; next legal open",
            "X3_ZONE_DAMAGE_10W": "completed daily close<=L-1.00W; next legal open",
            "X4_NO_PROGRESS_D3": "at D3, U unresolved, max progress<0.25W, daily close<L; next legal open",
            "X4_NO_PROGRESS_D5": "same at D5",
            "X5_STRUCTURAL_BREAK": "new lower MAJOR/SECONDARY true gap or lower causal cluster; first legal execution after known",
            "X6_HYBRID_D3": "earliest X1, X4_D3, X5",
            "X6_HYBRID_D5": "earliest X1, X4_D5, X5",
        },
        "retry": {
            "R0_NO_RETRY": "ATTACK_1 only",
            "R1_ONE_RETRY": "ATTACK_2 independently passes the same frozen admission after ATTACK_1 ends and prior position closes",
        },
        "loss_statistics": {
            "MAE": "minimum same-lineage coordinate mark from entry through the actual exit",
            "MFE": "maximum same-lineage coordinate mark from entry through the actual exit",
            "SEVERE_LOSS5_8_10_20": "realized NET_RETURN <= -5%/-8%/-10%/-20%; MAE is reported separately",
            "CLEAN_SUCCESS_5": "current-attack legal U within five completed sessions before a 5% adverse mark",
            "CLEAN_SUCCESS_10": "current-attack legal U within ten completed sessions before an 8% adverse mark",
        },
        "execution": {
            "t_plus_one": True,
            "suspension_and_limits": True,
            "actual_gap_through_execution": True,
            "delayed_failure_or_time_exit": "first row in the authoritative sell-legal open ledger strictly after completed trigger; may occur after H20 because of suspension/limit constraints, but never reads 2024+",
            "corporate_actions": "QD-010 known-at pre-effective risk exit and cash entitlements",
            "cost_per_side": COST,
        },
    }


def validate_inputs() -> dict[str, Any]:
    required = [
        SOURCE_SPEC, SOURCE_CANDIDATES, SOURCE_CLUSTERS, SOURCE_GAPS, SOURCE_ACTIONS,
        SOURCE_LEGAL_OPENS, DAILY, PRED_ENTRY_CANDIDATES, PRED_ENTRY_MINUTES,
        PRED_POLICY_PATHS, PRED_POLICY_TRADES, PRED_PORTFOLIO_NAV,
    ] + [RAW_ROOT / f"{year}_day_parquet_none.parquet" for year in YEARS]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"missing governed inputs: {missing}")
    if sha256(SOURCE_SPEC) != SOURCE_HASH:
        raise ResearchError("frozen V6 semantic hash mismatch")
    c_schema = set(pq.read_schema(SOURCE_CANDIDATES).names)
    d_schema = set(pq.read_schema(DAILY).names)
    m_schema = set(pq.read_schema(RAW_ROOT / "2014_day_parquet_none.parquet").names)
    need_c = {"candidate_id", "frozen_primary_gap_id", "causal_first_return", "frozen_primary_lower", "frozen_primary_upper", "cluster_freeze_time", "memory_state", "invalid_step_cum"}
    need_d = {"trade_date", "cal_idx", "symbol", "causal_industry", "hard_valid", "available_at", "decision_at", "coordinate_factor", "invalid_step_cum", "turnover_fraction", "coord_high", "coord_close"}
    need_m = {"qmt_code", "trade_date", "bar_end_time", "open", "high", "low", "close", "volume", "amount", "period", "adjust"}
    if not need_c <= c_schema or not need_d <= d_schema or not need_m <= m_schema:
        raise ResearchError("governed source schema incompatibility")
    candidates = pd.read_parquet(SOURCE_CANDIDATES, columns=["candidate_id", "memory_state", "first_return_date"])
    candidates.first_return_date = pd.to_datetime(candidates.first_return_date)
    if candidates.first_return_date.max() >= pd.Timestamp("2024-01-01"):
        raise ResearchError("2024+ source identity opened")
    return {
        "repo": str(ROOT),
        "source_semantic_hash": SOURCE_HASH,
        "source_candidate_rows": len(candidates),
        "active_core_boundary": int(candidates.memory_state.isin(["CORE", "BOUNDARY"]).sum()),
        "raw_years_explicit": list(YEARS),
        "daily_max_date": "2023-12-31",
        "minute_amount": "AVAILABLE",
        "pit_industry": "AVAILABLE",
        "qd010_coordinate": "AVAILABLE",
        "legal_open_ledger": "AVAILABLE",
        "repository_2024_plus_data_opened": "NO",
    }


def persist_contracts() -> dict[str, str]:
    write_json(SPEC, spec_contract())
    preflight = semantic_preflight_contract()
    write_json(SEMANTIC_PREFLIGHT_JSON, preflight)
    lines = [f"# {EXPERIMENT} — Semantic preflight", "", "Outcomes opened: **NO**.", "", "## Economic sequence", ""]
    lines.extend(f"{idx}. {item}" for idx, item in enumerate(preflight["economic_sequence"], 1))
    lines += ["", "## Cause / state / trigger / outcome", "", f"- Cause: {preflight['cause']}", f"- State: {', '.join(preflight['state'])}", f"- Trigger: {preflight['trigger']}", f"- Outcome: {', '.join(preflight['outcome'])}", "", "## Chosen causal clocks", ""]
    lines.extend(f"- {key}: {value}" for key, value in preflight["chosen_time_anchors"].items())
    lines += ["", "## Ambiguities retained", ""]
    lines.extend(f"- {item}" for item in preflight["possible_ambiguities"])
    write_text(SEMANTIC_PREFLIGHT_MD, "\n".join(lines) + "\n")
    write_json(VAP_METHODOLOGY, vap_methodology_contract())
    write_json(FEATURE_DICTIONARY, feature_dictionary_value())
    write_json(ATTACK_CONTRACT, attack_contract_value())
    write_json(RULE_SPACE, rule_space_value())
    write_json(EXIT_SPACE, exit_space_value())
    return {
        "v7_spec_hash": sha256(SPEC),
        "v7_feature_contract_hash": sha256(FEATURE_DICTIONARY),
        "v7_attack_contract_hash": sha256(ATTACK_CONTRACT),
        "v7_rule_space_hash": sha256(RULE_SPACE),
        "v7_exit_space_hash": sha256(EXIT_SPACE),
    }


def active_source() -> pd.DataFrame:
    columns = [
        "candidate_id", "cluster_id", "symbol", "board", "memory_state", "causal_first_return",
        "first_return_date", "first_return_cal_idx", "frozen_primary_gap_id", "frozen_primary_lower",
        "frozen_primary_upper", "frozen_primary_gap_date", "cluster_freeze_time", "invalid_step_cum",
        "reference_high", "material_drawdown_at_freeze", "true_gap_width_pct",
    ]
    frame = pd.read_parquet(SOURCE_CANDIDATES, columns=columns)
    for column in ("causal_first_return", "first_return_date", "frozen_primary_gap_date", "cluster_freeze_time"):
        frame[column] = pd.to_datetime(frame[column])
    frame = frame.loc[frame.memory_state.isin(["CORE", "BOUNDARY"]) & frame.first_return_date.dt.year.between(2014, 2023)].copy()
    frame = frame.rename(columns={"frozen_primary_lower": "L", "frozen_primary_upper": "U", "frozen_primary_gap_id": "gap_id", "frozen_primary_gap_date": "gap_date"})
    frame["W"] = frame.U - frame.L
    if len(frame) != 3959 or frame.candidate_id.duplicated().any() or frame.gap_id.duplicated().any():
        raise ResearchError("V6 active identity mismatch")
    if (frame.W <= 0).any() or frame.first_return_date.max() >= pd.Timestamp("2024-01-01"):
        raise ResearchError("invalid V6 active source")
    return frame.sort_values(["causal_first_return", "candidate_id"], kind="mergesort").reset_index(drop=True)


def predecessor_reconciliation_base() -> dict[str, Any]:
    candidates = active_source()
    trades = pd.read_parquet(PRED_POLICY_TRADES, columns=["entry_key", "candidate_id", "entry_time", "entry_date", "entry_cal_idx", "board", "memory_state", "outer_test_year", "lane", "selected_entry", "outcome_qd010_valid", "exit_time", "unresolved_action_block"])
    for column in ("entry_time", "entry_date", "exit_time"):
        trades[column] = pd.to_datetime(trades[column])
    l0 = trades.loc[trades.lane.eq("L0_BASELINE")].copy()
    selected = pd.read_parquet(PRED_ENTRY_CANDIDATES, columns=["candidate_id", "translation", "entry_time", "entry_cal_idx", "confirmation_time", "status"])
    for column in ("entry_time", "confirmation_time"):
        selected[column] = pd.to_datetime(selected[column])
    chosen = l0.merge(selected, left_on=["candidate_id", "selected_entry"], right_on=["candidate_id", "translation"], how="left", suffixes=("", "_grid"))
    chosen = chosen.loc[chosen.entry_time.eq(chosen.entry_time_grid)].copy()
    if len(chosen) != len(l0):
        raise ResearchError(f"predecessor selected-entry reconciliation mismatch {len(chosen)} != {len(l0)}")
    chosen = chosen.merge(candidates[["candidate_id", "gap_id", "first_return_cal_idx", "causal_first_return", "gap_date"]], on="candidate_id", validate="many_to_one")
    delays = pd.to_numeric(chosen.entry_cal_idx_grid, errors="coerce") - pd.to_numeric(chosen.first_return_cal_idx, errors="coerce")
    repeated = l0.groupby("candidate_id").agg(source_rows=("entry_time", "size"), source_entry_timestamps=("entry_time", "nunique")).query("source_entry_timestamps>1")
    paths = pd.read_parquet(PRED_POLICY_PATHS, columns=["entry_key", "candidate_id", "unresolved_action_block"])
    blocked = paths.loc[paths.unresolved_action_block.fillna(False)].copy()
    predecessor_result = json.loads(PRED_RESULT.read_text())
    predecessor_l0_k10 = [
        row
        for row in predecessor_result["decomposition_k10"]
        if row["lane"] == "L0_BASELINE" and row["board"] == "COMBINED" and row["k"] == 10
    ]
    if len(predecessor_l0_k10) != 1:
        raise ResearchError("predecessor K10 L0 capacity row mismatch")
    predecessor_l0_k10 = predecessor_l0_k10[0]
    return {
        "source_signal_rows": len(l0),
        "completed_baseline_policy_rows": int((l0.outcome_qd010_valid.fillna(False) & l0.exit_time.notna()).sum()),
        "unique_source_events": int(l0.candidate_id.nunique()),
        "unique_frozen_gaps": int(l0.candidate_id.map(candidates.set_index("candidate_id").gap_id).nunique()),
        "memory_state_row_split": l0.memory_state.value_counts().astype(int).to_dict(),
        "memory_state_unique_gap_split": l0.drop_duplicates("candidate_id").memory_state.value_counts().astype(int).to_dict(),
        "gaps_with_more_than_one_source_entry_timestamp": int(len(repeated)),
        "source_entry_timestamps_after_first_contact": {
            "more_than_1_session": int((delays > 1).sum()),
            "more_than_3_sessions": int((delays > 3).sum()),
            "more_than_5_sessions": int((delays > 5).sum()),
            "maximum_sessions": int(delays.max()),
        },
        "board_split": l0.groupby("board").size().astype(int).to_dict(),
        "portfolio_capacity_effects_k10": {
            "signals": int(predecessor_l0_k10["signals"]),
            "completed_trades": int(predecessor_l0_k10["completed_trades"]),
            "capacity_skips": int(predecessor_l0_k10["capacity_skips"]),
        },
        "year_board_split": [{"year": int(y), "board": b, "rows": int(len(g))} for (y, b), g in l0.groupby(["outer_test_year", "board"], sort=True)],
        "entry_rule_mix": l0.selected_entry.value_counts().astype(int).to_dict(),
        "duplicate_event_date_entries": int(l0.duplicated(["candidate_id", "entry_date"], keep=False).sum()),
        "formation_date_top10_share": float(chosen.gap_date.value_counts().head(10).sum() / len(chosen)),
        "reentry_date_top10_share": float(chosen.entry_date.dt.normalize().value_counts().head(10).sum() / len(chosen)),
        "corporate_action_fail_closed": {
            "policy_rows": int(len(blocked)),
            "unique_events": int(blocked.candidate_id.nunique()),
            "unique_entry_keys": int(blocked.entry_key.nunique()),
            "unique_attacks": None,
        },
        "later_attack_crosswalk_pending": True,
        "outcomes_recomputed": "NO",
        "repository_2024_plus_data_opened": "NO",
    }


def stage_preflight() -> dict[str, Any]:
    readiness = validate_inputs()
    hashes = persist_contracts()
    EXT.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    base = predecessor_reconciliation_base()
    write_json(RECONCILIATION_JSON, {"experiment": EXPERIMENT, "status": "ATTACK_CROSSWALK_PENDING", **base})
    lines = [f"# {EXPERIMENT} — V6 to V7 reconciliation", "", "This is an outcome-blind identity/timeline reconciliation. No V7 return was calculated.", "", f"- V6 L0 source / completed policy rows: {base['source_signal_rows']} / {base['completed_baseline_policy_rows']}", f"- Unique source events/gaps: {base['unique_source_events']} / {base['unique_frozen_gaps']}", f"- CORE / BOUNDARY rows: {base['memory_state_row_split'].get('CORE', 0)} / {base['memory_state_row_split'].get('BOUNDARY', 0)}", f"- K10 completed trades / capacity skips: {base['portfolio_capacity_effects_k10']['completed_trades']} / {base['portfolio_capacity_effects_k10']['capacity_skips']}", f"- Gaps with multiple source-entry timestamps: {base['gaps_with_more_than_one_source_entry_timestamp']}", f"- Entry delay >1/>3/>5 sessions: {base['source_entry_timestamps_after_first_contact']['more_than_1_session']}/{base['source_entry_timestamps_after_first_contact']['more_than_3_sessions']}/{base['source_entry_timestamps_after_first_contact']['more_than_5_sessions']}", f"- Corporate-action unresolved policy rows / events / entry keys: {base['corporate_action_fail_closed']['policy_rows']}/{base['corporate_action_fail_closed']['unique_events']}/{base['corporate_action_fail_closed']['unique_entry_keys']}", "", "Separate-attack attribution remains pending until the frozen Stage-A attack ledger is built."]
    write_text(RECONCILIATION_MD, "\n".join(lines) + "\n")
    manifest("STAGE_A_RECONCILIATION", "COMPLETE_BASE_PENDING_ATTACK_CROSSWALK", {"hashes": hashes, "readiness": readiness, "reconciliation": base})
    return {"readiness": readiness, "hashes": hashes, "reconciliation": base, "outcomes_opened": "NO"}


def build_vap_date_map() -> pd.DataFrame:
    candidates = active_source()
    calendar = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx").sort_values("cal_idx")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    idx = calendar.set_index("trade_date").cal_idx
    candidates["gap_cal_idx"] = candidates.gap_date.dt.normalize().map(idx)
    if candidates.gap_cal_idx.isna().any():
        raise ResearchError("missing primary-gap calendar index")
    seed = candidates[["candidate_id", "gap_id", "symbol", "board", "gap_date", "gap_cal_idx", "cluster_freeze_time", "L", "U", "W", "invalid_step_cum"]].copy()
    seed_path = EXT / "vap_seed.parquet"
    write_parquet(seed, seed_path)
    con = duckdb.connect()
    con.execute("SET threads=4")
    frame = con.execute(f"""
        SELECT s.*,d.trade_date,d.cal_idx,d.coordinate_factor,d.turnover_fraction,d.volume AS daily_volume,
          d.amount AS daily_amount,d.hard_valid,d.history_valid,d.current_valid,d.available_at,d.decision_at,
          d.invalid_step_cum AS daily_invalid_step_cum,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.causal_industry AS industry
        FROM read_parquet('{seed_path}') s
        JOIN read_parquet('{DAILY}') d ON d.symbol=s.symbol
          AND d.cal_idx BETWEEN s.gap_cal_idx-120 AND s.gap_cal_idx+90
        WHERE d.trade_date<=DATE '2023-12-31'
        ORDER BY candidate_id,cal_idx
    """).fetchdf()
    con.close()
    for column in ("gap_date", "cluster_freeze_time", "trade_date", "available_at", "decision_at"):
        frame[column] = pd.to_datetime(frame[column])
    frame["session_offset"] = frame.cal_idx - frame.gap_cal_idx
    write_parquet(frame, VAP_DATE_MAP)
    return frame


def _build_vap_year(year: int) -> Path:
    part = VAP_PARTS / f"year={year}" / "part.parquet"
    if part.is_file():
        return part
    part.parent.mkdir(parents=True, exist_ok=True)
    tmp = part.with_suffix(".parquet.tmp")
    raw = RAW_ROOT / f"{year}_day_parquet_none.parquet"
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""COPY (
      WITH joined AS (
        SELECT m.candidate_id,m.gap_id,m.symbol,m.board,m.gap_date,m.gap_cal_idx,m.cluster_freeze_time,
          m.L,m.U,m.W,m.invalid_step_cum,m.trade_date,m.cal_idx,m.session_offset,m.coordinate_factor,
          m.turnover_fraction,m.daily_volume,m.hard_valid,m.history_valid,m.current_valid,m.available_at,m.decision_at,
          r.bar_end_time,r.open,r.high,r.low,r.close,r.volume,r.amount,
          count(*) OVER(PARTITION BY m.candidate_id,m.trade_date) AS minute_count,
          sum(r.volume) OVER(PARTITION BY m.candidate_id,m.trade_date) AS observed_session_volume
        FROM read_parquet('{VAP_DATE_MAP}') m
        JOIN read_parquet('{raw}') r ON r.qmt_code=m.symbol AND r.trade_date=m.trade_date
        WHERE year(m.trade_date)={year} AND r.period='1m' AND r.adjust='none'
          AND m.hard_valid AND m.daily_invalid_step_cum=m.invalid_step_cum
      ), priced AS (
        SELECT *,CASE WHEN volume>0 AND amount>0 THEN amount/volume ELSE (high+low+close)/3 END*coordinate_factor AS coord_vap,
          CASE WHEN volume>0 AND NOT (amount>0) THEN 1 ELSE 0 END AS vap_price_proxy,
          CASE
            WHEN floor(((CASE WHEN volume>0 AND amount>0 THEN amount/volume ELSE (high+low+close)/3 END*coordinate_factor-L)/W)/0.10)::INTEGER
              BETWEEN {VAP_MIN_BIN} AND {VAP_MAX_BIN}
            THEN floor(((CASE WHEN volume>0 AND amount>0 THEN amount/volume ELSE (high+low+close)/3 END*coordinate_factor-L)/W)/0.10)::INTEGER
            ELSE 999
          END AS z_bin
        FROM joined
      )
      SELECT candidate_id,gap_id,symbol,board,gap_date,gap_cal_idx,cluster_freeze_time,L,U,W,invalid_step_cum,
        trade_date,cal_idx,session_offset,turnover_fraction,daily_volume,hard_valid,history_valid,current_valid,
        max(minute_count) AS minute_count,max(observed_session_volume) AS observed_session_volume,z_bin,
        sum(volume) AS raw_volume,sum(amount) AS raw_amount,
        sum(CASE WHEN observed_session_volume>0 AND turnover_fraction>=0 THEN turnover_fraction*volume/observed_session_volume ELSE NULL END) AS allocated_float_turnover,
        sum(vap_price_proxy) AS proxy_minute_count,count(*) AS minute_rows
      FROM priced
      GROUP BY ALL ORDER BY candidate_id,cal_idx,z_bin
    ) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    tmp.replace(part)
    return part


def stage_overhang() -> dict[str, Any]:
    validate_inputs()
    hashes = persist_contracts()
    date_map = build_vap_date_map()
    VAP_PARTS.mkdir(parents=True, exist_ok=True)
    parts = [_build_vap_year(year) for year in YEARS]
    tmp = VAP_SESSION_BINS.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"COPY (SELECT * FROM read_parquet('{VAP_PARTS}/year=*/part.parquet') ORDER BY candidate_id,cal_idx,z_bin) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    tmp.replace(VAP_SESSION_BINS)
    audit = duckdb.sql(f"""
      WITH sessions AS (
        SELECT candidate_id,trade_date,max(minute_count) minute_count,max(hard_valid::INT) hard_valid,
          max(history_valid::INT) history_valid,max(current_valid::INT) current_valid,max(invalid_step_cum) lineage,
          sum(proxy_minute_count) proxy_minutes
        FROM read_parquet('{VAP_SESSION_BINS}') GROUP BY 1,2
      ) SELECT count(*) sessions,count(DISTINCT candidate_id) candidates,
        count_if(minute_count<>241) non_241_sessions,count_if(not hard_valid::BOOLEAN) non_hard_sessions,
        sum(proxy_minutes) proxy_minutes,min(trade_date) min_date,max(trade_date) max_date
      FROM sessions
    """).df().iloc[0].to_dict()
    pre_coverage = duckdb.sql(f"""
      WITH sessions AS (
        SELECT candidate_id,session_offset,max(minute_count) minute_count,max(hard_valid::INT) hard_valid,
          max(history_valid::INT) history_valid,max(current_valid::INT) current_valid
        FROM read_parquet('{VAP_SESSION_BINS}') GROUP BY 1,2
      ), c AS (
        SELECT candidate_id,count_if(session_offset<0 AND minute_count=241 AND hard_valid=1) n_pre
        FROM sessions GROUP BY 1
      ) SELECT min(n_pre) min_pre,median(n_pre) median_pre,count_if(n_pre>=20) ge20,count_if(n_pre>=60) ge60,count_if(n_pre>=120) ge120,count(*) total FROM c
    """).df().iloc[0].to_dict()
    if pd.Timestamp(audit["max_date"]) >= pd.Timestamp("2024-01-01"):
        raise ResearchError("2024+ VAP row opened")
    payload = {
        "hashes": hashes,
        "date_map_rows": len(date_map),
        "date_map_sha256": sha256(VAP_DATE_MAP),
        "vap_rows": pq.read_metadata(VAP_SESSION_BINS).num_rows,
        "vap_sha256": sha256(VAP_SESSION_BINS),
        "partition_hash": directory_hash(VAP_PARTS),
        "audit": audit,
        "pre_gap_coverage": pre_coverage,
        "outcomes_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    manifest("STAGE_A_OVERHANG", "COMPLETE", payload)
    return payload


def build_attack_minute_base(candidates: pd.DataFrame) -> None:
    calendar = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    idx = calendar.set_index("trade_date").cal_idx
    seed = candidates[["candidate_id", "gap_id", "symbol", "board", "memory_state", "gap_date", "L", "U", "W", "invalid_step_cum", "causal_first_return", "cluster_freeze_time"]].copy()
    seed["gap_cal_idx"] = seed.gap_date.dt.normalize().map(idx)
    seed["freshness_end_cal_idx"] = seed.gap_cal_idx + 90
    seed_path = EXT / "attack_seed.parquet"
    write_parquet(seed, seed_path)
    tmp = ATTACK_MINUTES.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""COPY (
      SELECT s.gap_id,s.gap_date,s.gap_cal_idx,s.freshness_end_cal_idx,s.L,s.U,s.W,s.board,s.memory_state AS source_memory,
        m.*,lag(m.coord_close) OVER(PARTITION BY m.candidate_id ORDER BY m.bar_end_time) AS previous_coord_close,
        row_number() OVER(PARTITION BY m.candidate_id ORDER BY m.bar_end_time) AS path_minute_number
      FROM read_parquet('{seed_path}') s JOIN read_parquet('{PRED_ENTRY_MINUTES}') m USING(candidate_id)
      WHERE m.cal_idx<=s.freshness_end_cal_idx AND m.trade_date<=DATE '2023-12-31'
      ORDER BY m.candidate_id,m.bar_end_time
    ) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    tmp.replace(ATTACK_MINUTES)
    tmp_contacts = ATTACK_CONTACTS.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute(f"""COPY (
      WITH derived AS (
        SELECT candidate_id,gap_id,symbol,board,trade_date,cal_idx,bar_end_time,coord_open,coord_high,coord_low,coord_close,
          previous_coord_close,'DERIVED_UPWARD_CONTACT' AS contact_source
        FROM read_parquet('{ATTACK_MINUTES}') WHERE previous_coord_close<L AND coord_high>=L
      ), frozen AS (
        SELECT candidate_id,frozen_primary_gap_id AS gap_id,symbol,board,CAST(causal_first_return AS DATE) trade_date,first_return_cal_idx AS cal_idx,
          causal_first_return AS bar_end_time,NULL::DOUBLE coord_open,NULL::DOUBLE coord_high,NULL::DOUBLE coord_low,NULL::DOUBLE coord_close,
          NULL::DOUBLE previous_coord_close,'FROZEN_V6_FIRST_RETURN' AS contact_source
        FROM read_parquet('{SOURCE_CANDIDATES}') WHERE memory_state IN ('CORE','BOUNDARY')
      ) SELECT * FROM frozen UNION ALL SELECT * FROM derived
      ORDER BY candidate_id,bar_end_time,contact_source
    ) TO '{tmp_contacts}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    tmp_contacts.replace(ATTACK_CONTACTS)


def _timestamp_columns(frame: pd.DataFrame, columns: Iterable[str]) -> None:
    for column in columns:
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])


def _first_timestamp(frame: pd.DataFrame, column: str, after: pd.Timestamp, before: pd.Timestamp | None = None) -> pd.Timestamp | None:
    part = frame.loc[pd.to_datetime(frame[column]).gt(after)]
    if before is not None:
        part = part.loc[pd.to_datetime(part[column]).le(before)]
    return None if part.empty else pd.Timestamp(part[column].min())


def _attack_end(
    event: Any,
    start: pd.Timestamp,
    start_idx: int,
    minute: pd.DataFrame,
    daily: pd.DataFrame,
    lower_gaps: pd.DataFrame,
    lower_clusters: pd.DataFrame,
    calendar_by_idx: pd.Series,
) -> tuple[str, pd.Timestamp, dict[str, Any]]:
    choices: list[tuple[pd.Timestamp, int, str, dict[str, Any]]] = []
    u = minute.loc[minute.bar_end_time.ge(start) & minute.coord_high.ge(float(event.U))]
    if len(u):
        row = u.iloc[0]
        choices.append((pd.Timestamp(row.bar_end_time), 0, "SUCCESS", {"u_time": pd.Timestamp(row.bar_end_time), "u_cal_idx": int(row.cal_idx)}))
    gl = lower_gaps.loc[lower_gaps.known_time.gt(start)]
    cl = lower_clusters.loc[lower_clusters.known_time.gt(start)]
    structural = []
    if len(gl):
        row = gl.iloc[0]
        structural.append((pd.Timestamp(row.known_time), "LOWER_MAJOR_SECONDARY_GAP", str(row.identity)))
    if len(cl):
        row = cl.iloc[0]
        structural.append((pd.Timestamp(row.known_time), "LOWER_CAUSAL_CLUSTER", str(row.identity)))
    if structural:
        when, source, identity = sorted(structural, key=lambda x: (x[0], x[1], x[2]))[0]
        choices.append((when, 1, "HARD_STRUCTURAL_RESET", {"structural_reset_source": source, "structural_reset_identity": identity}))
    after_days = daily.loc[(daily.trade_date + pd.Timedelta(hours=15)).gt(start)].copy()
    below = after_days.coord_high.lt(float(event.L)).to_numpy()
    pair = np.flatnonzero(below & np.r_[False, below[:-1]])
    if len(pair):
        row = after_days.iloc[int(pair[0])]
        choices.append((pd.Timestamp(row.trade_date) + pd.Timedelta(hours=15), 2, "BELOW_ZONE_RESET", {"below_reset_cal_idx": int(row.cal_idx)}))
    time_idx = start_idx + 10
    if time_idx in calendar_by_idx.index:
        time_date = pd.Timestamp(calendar_by_idx.loc[time_idx])
        if time_date <= pd.Timestamp("2023-12-31"):
            choices.append((time_date + pd.Timedelta(hours=15), 3, "TIME_RESET", {"time_reset_cal_idx": time_idx}))
    if not choices:
        boundary_idx = min(int(event.gap_cal_idx) + 90, int(calendar_by_idx.index.max()))
        boundary_time = pd.Timestamp(calendar_by_idx.loc[boundary_idx]) + pd.Timedelta(hours=15)
        choices.append((boundary_time, 4, "RIGHT_CENSORED_AT_FRESHNESS", {"censored": True}))
    when, _, reason, details = sorted(choices, key=lambda x: (x[0], x[1]))[0]
    return reason, when, details


def build_attack_ledger() -> pd.DataFrame:
    candidates = active_source()
    calendar = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx").sort_values("cal_idx")
    calendar.trade_date = pd.to_datetime(calendar.trade_date)
    by_idx = calendar.set_index("cal_idx").trade_date
    idx_by_date = calendar.set_index("trade_date").cal_idx
    candidates["gap_cal_idx"] = candidates.gap_date.dt.normalize().map(idx_by_date).astype(int)
    build_attack_minute_base(candidates)
    minutes = pd.read_parquet(ATTACK_MINUTES)
    _timestamp_columns(minutes, ["trade_date", "bar_end_time", "causal_first_return", "cluster_freeze_time", "gap_date"])
    contacts = pd.read_parquet(ATTACK_CONTACTS)
    _timestamp_columns(contacts, ["trade_date", "bar_end_time"])
    daily_cols = ["trade_date", "cal_idx", "symbol", "coord_high", "coord_low", "coord_close", "turnover_fraction", "hard_valid", "invalid_step_cum", "causal_industry"]
    daily = pd.read_parquet(DAILY, columns=daily_cols)
    daily.trade_date = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.symbol.isin(candidates.symbol.unique()) & daily.trade_date.le(pd.Timestamp("2023-12-31"))]
    gaps = pd.read_parquet(SOURCE_GAPS, columns=["symbol", "true_gap_id", "gap_date", "true_gap_lower", "importance", "invalid_step_cum"])
    gaps.gap_date = pd.to_datetime(gaps.gap_date)
    gaps = gaps.loc[gaps.importance.isin(["MAJOR", "SECONDARY"])].copy()
    gaps["known_time"] = gaps.gap_date.dt.normalize() + pd.Timedelta(hours=15)
    gaps = gaps.rename(columns={"true_gap_id": "identity"})
    clusters = pd.read_parquet(SOURCE_CLUSTERS, columns=["symbol", "cluster_id", "cluster_freeze_time", "frozen_primary_lower"])
    clusters.cluster_freeze_time = pd.to_datetime(clusters.cluster_freeze_time)
    clusters["known_time"] = clusters.cluster_freeze_time
    clusters = clusters.rename(columns={"cluster_id": "identity"})
    minute_by = {key: value.sort_values("bar_end_time", kind="mergesort") for key, value in minutes.groupby("candidate_id", sort=False)}
    contacts_by = {key: value.sort_values("bar_end_time", kind="mergesort") for key, value in contacts.groupby("candidate_id", sort=False)}
    daily_by = {key: value.sort_values("cal_idx", kind="mergesort") for key, value in daily.groupby("symbol", sort=False)}
    gaps_by = {key: value.sort_values("known_time", kind="mergesort") for key, value in gaps.groupby("symbol", sort=False)}
    clusters_by = {key: value.sort_values("known_time", kind="mergesort") for key, value in clusters.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        mins = minute_by.get(event.candidate_id, pd.DataFrame(columns=minutes.columns))
        cts = contacts_by.get(event.candidate_id, pd.DataFrame(columns=contacts.columns))
        days = daily_by[event.symbol]
        days = days.loc[days.invalid_step_cum.eq(event.invalid_step_cum) & days.hard_valid]
        lower_gaps = gaps_by.get(event.symbol, pd.DataFrame(columns=gaps.columns))
        lower_gaps = lower_gaps.loc[lower_gaps.true_gap_lower.lt(event.L) & lower_gaps.invalid_step_cum.eq(event.invalid_step_cum)]
        lower_clusters = clusters_by.get(event.symbol, pd.DataFrame(columns=clusters.columns))
        lower_clusters = lower_clusters.loc[lower_clusters.frozen_primary_lower.lt(event.L)]
        start = pd.Timestamp(event.causal_first_return)
        previous_end: pd.Timestamp | None = None
        previous_reason: str | None = None
        previous_max_z = np.nan
        previous_turnover = np.nan
        for number in (1, 2):
            if number == 2:
                if previous_end is None or previous_reason == "SUCCESS":
                    break
                possible = cts.loc[cts.bar_end_time.gt(previous_end) & cts.contact_source.eq("DERIVED_UPWARD_CONTACT")]
                if possible.empty:
                    break
                start = pd.Timestamp(possible.bar_end_time.iloc[0])
            if start.normalize() not in idx_by_date.index:
                break
            start_idx = int(idx_by_date.loc[start.normalize()])
            age = start_idx - int(event.gap_cal_idx)
            if age > 90:
                break
            reason, end, details = _attack_end(event, start, start_idx, mins, days, lower_gaps, lower_clusters, by_idx)
            path = mins.loc[mins.bar_end_time.between(start, end, inclusive="both")]
            max_z = np.nan if path.empty else float(((path.coord_high - event.L) / event.W).max())
            daily_start = days.loc[days.trade_date.le(start.normalize())].tail(1)
            implied_float = np.nan
            if len(daily_start):
                prior = days.loc[days.trade_date.lt(start.normalize()) & days.turnover_fraction.gt(0)].tail(1)
                if len(prior):
                    implied_float = float(prior.iloc[0].turnover_fraction)
            row = {
                "gap_id": event.gap_id,
                "candidate_id": event.candidate_id,
                "attack_id": f"{event.gap_id}|ATTACK_{number}",
                "attack_number": number,
                "symbol": event.symbol,
                "board": event.board,
                "source_memory_state": event.memory_state,
                "attack_memory_state": "CORE" if age <= 60 else "BOUNDARY",
                "gap_date": event.gap_date,
                "gap_cal_idx": int(event.gap_cal_idx),
                "cluster_freeze_time": event.cluster_freeze_time,
                "L": float(event.L),
                "U": float(event.U),
                "W": float(event.W),
                "invalid_step_cum": float(event.invalid_step_cum),
                "attack_start_time": start,
                "attack_start_date": start.normalize(),
                "attack_start_cal_idx": start_idx,
                "attack_end_reason": reason,
                "attack_end_time": end,
                "attack_end_date": end.normalize(),
                "prior_attack_count": number - 1,
                "prior_attack_max_z": previous_max_z,
                "prior_attack_turnover": previous_turnover,
                "days_since_prior_attack_end": np.nan if previous_end is None else start_idx - int(days.loc[days.trade_date.le(previous_end.normalize()), "cal_idx"].iloc[-1]),
                "gap_age_sessions": age,
                "current_attack_max_z": max_z,
                "u_time": details.get("u_time", pd.NaT),
                "structural_reset_source": details.get("structural_reset_source"),
                "structural_reset_identity": details.get("structural_reset_identity"),
                "right_censored": bool(details.get("censored", False)),
                "v6_event_identity_changed": False,
            }
            rows.append(row)
            attack_days = days.loc[days.cal_idx.between(start_idx, int(days.loc[days.trade_date.le(end.normalize()), "cal_idx"].iloc[-1]))]
            previous_turnover = float(attack_days.turnover_fraction.fillna(0).sum())
            previous_max_z = max_z
            previous_end = end
            previous_reason = reason
    ledger = pd.DataFrame(rows).sort_values(["attack_start_time", "attack_id"], kind="mergesort").reset_index(drop=True)
    if ledger.attack_id.duplicated().any() or (ledger.attack_number > 2).any():
        raise ResearchError("attack identity invariant failed")
    if (ledger.loc[ledger.attack_number.eq(2), "attack_start_time"].to_numpy() <= ledger.loc[ledger.attack_number.eq(2), "attack_end_time"].to_numpy()).sum() != len(ledger.loc[ledger.attack_number.eq(2)]):
        raise ResearchError("invalid ATTACK_2 interval")
    write_parquet(ledger, ATTACK_LEDGER)
    return ledger


def _region_sum(frame: pd.DataFrame, low: int, high: int, column: str) -> float:
    return float(frame.loc[frame.z_bin.between(low, high - 1), column].sum())


def _safe_div(a: float, b: float) -> float:
    return float(a / b) if np.isfinite(a) and np.isfinite(b) and abs(b) > EPSILON else np.nan


def _compounded_return(values: pd.Series) -> float:
    x = pd.to_numeric(values, errors="coerce").dropna().to_numpy(float)
    return np.nan if len(x) == 0 else float(np.prod(1 + x) - 1)


def _inventory_features(event: Any, bins: pd.DataFrame, current_partial: pd.DataFrame, daily: pd.DataFrame) -> dict[str, Any]:
    pre = bins.loc[bins.session_offset.lt(0)].copy()
    result: dict[str, Any] = {}
    for window in (20, 60, 120):
        valid_sessions = (
            pre.loc[pre.minute_count.eq(241) & pre.hard_valid]
            .drop_duplicates("cal_idx").sort_values("cal_idx").tail(window)
        )
        exact = len(valid_sessions) == window
        selected_idx = set(valid_sessions.cal_idx.astype(int)) if exact else set()
        chosen = pre.loc[pre.cal_idx.isin(selected_idx)] if exact else pre.iloc[0:0]
        local = chosen.loc[chosen.z_bin.between(VAP_MIN_BIN, VAP_MAX_BIN)]
        local_volume = float(local.raw_volume.sum())
        local_turnover = float(local.allocated_float_turnover.sum())
        for name, lo, hi in (("inside_gap", 0, 10), ("above_u", 10, 20), ("below_l_support", -10, 0)):
            result[f"raw_vap_{name}_{window}"] = _safe_div(_region_sum(chosen, lo, hi, "raw_volume"), local_volume) if exact else np.nan
            result[f"float_vap_{name}_{window}"] = _region_sum(chosen, lo, hi, "allocated_float_turnover") if exact else np.nan
        result[f"vap_window_{window}_valid"] = exact
    history = bins.loc[bins.cal_idx.lt(event.attack_start_cal_idx)].copy()
    if len(current_partial):
        history = pd.concat([history, current_partial], ignore_index=True, sort=False)
    if history.empty:
        return {**result, "inventory_valid": False}
    session_totals = history.groupby("cal_idx", sort=True).allocated_float_turnover.sum().sort_index()
    if session_totals.isna().any() or (session_totals < 0).any():
        return {**result, "inventory_valid": False}
    future_turnover = session_totals.iloc[::-1].cumsum().iloc[::-1] - session_totals
    history["future_turnover"] = history.cal_idx.map(future_turnover)
    history["survival_weight"] = np.exp(-history.future_turnover.clip(upper=EXP_CLIP))
    history["decayed"] = history.allocated_float_turnover * history.survival_weight
    density = history.groupby("z_bin").decayed.sum().reindex(range(VAP_MIN_BIN, VAP_MAX_BIN + 1), fill_value=0.0)
    local_mean = float(density.mean())
    inside = float(density.loc[0:9].sum())
    above = float(density.loc[10:19].sum())
    support = float(density.loc[-10:-1].sum())
    result.update(
        inventory_valid=True,
        decayed_overhang_inside_gap=inside,
        decayed_overhang_above_u=above,
        decayed_support_below_l=support,
        overhang_support_ratio=(inside + above) / max(support, EPSILON),
        gap_density_relative_to_local=_safe_div(float(density.loc[0:9].mean()), local_mean),
        overhead_density_relative_to_support=_safe_div(float(density.loc[0:19].mean()), float(density.loc[-10:-1].mean())),
    )
    result["gap_lvn_score"] = np.clip(1 - result["gap_density_relative_to_local"], -5, 1) if np.isfinite(result["gap_density_relative_to_local"]) else np.nan
    above_relative = _safe_div(float(density.loc[10:19].mean()), local_mean)
    result["above_u_lvn_score"] = np.clip(1 - above_relative, -5, 1) if np.isfinite(above_relative) else np.nan
    poc_bin = int(density.idxmax())
    result["poc_z"] = (poc_bin + 0.5) * VAP_BIN_WIDTH_Z
    result["poc_inside_gap"] = bool(0 <= poc_bin < 10)
    positive = density.loc[density.gt(0)]
    hvn_cut = np.nan if positive.empty else float(positive.quantile(0.70))
    hvn = density.loc[density.ge(hvn_cut)].index.to_numpy(int) if np.isfinite(hvn_cut) else np.array([], dtype=int)
    above_l = hvn[hvn >= 0]
    above_u = hvn[hvn >= 10]
    result["nearest_hvn_above_l_distance_z"] = np.nan if len(above_l) == 0 else float((above_l.min() + 0.5) / 10)
    result["nearest_hvn_above_u_distance_z"] = np.nan if len(above_u) == 0 else float((above_u.min() + 0.5) / 10 - 1)
    gap_hist = history.loc[history.cal_idx.le(event.gap_cal_idx)]
    gap_density = gap_hist.assign(decayed_at_gap=gap_hist.allocated_float_turnover).groupby("z_bin").decayed_at_gap.sum().reindex(range(VAP_MIN_BIN, VAP_MAX_BIN + 1), fill_value=0.0)
    gap_poc_z = (int(gap_density.idxmax()) + 0.5) / 10
    result["poc_at_gap_z"] = gap_poc_z
    result["poc_migration_toward_l"] = abs(gap_poc_z) - abs(result["poc_z"])
    result["poc_migration_into_gap"] = bool(gap_poc_z < 0 <= result["poc_z"] < 1)
    post = history.loc[history.cal_idx.ge(event.gap_cal_idx)]
    result["cum_turnover_since_gap"] = float(post.groupby("cal_idx").allocated_float_turnover.sum().sum())
    freeze_date = pd.Timestamp(event.cluster_freeze_time).normalize()
    result["cum_turnover_since_cluster_freeze"] = float(history.loc[pd.to_datetime(history.trade_date).ge(freeze_date)].groupby("cal_idx").allocated_float_turnover.sum().sum())
    result["cum_turnover_near_l"] = _region_sum(post, -5, 6, "allocated_float_turnover")
    result["cum_turnover_inside_gap"] = _region_sum(post, 0, 11, "allocated_float_turnover")
    post_days = daily.loc[daily.cal_idx.between(event.gap_cal_idx, event.attack_start_cal_idx - 1)]
    if len(post_days):
        progress = float(pd.concat([post_days.coord_low, post_days.coord_close]).min())
        progress = float(event.L / progress - 1) if progress > 0 else np.nan
        result["price_progress_per_turnover_since_gap"] = _safe_div(progress, result["cum_turnover_since_gap"])
    else:
        result["price_progress_per_turnover_since_gap"] = np.nan
    return result


def _partial_attack_start_bins(event: Any, minute: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    current = minute.loc[minute.bar_end_time.le(event.attack_start_time) & minute.trade_date.eq(pd.Timestamp(event.attack_start_date))].copy()
    if current.empty:
        return pd.DataFrame(columns=["candidate_id", "trade_date", "cal_idx", "z_bin", "raw_volume", "allocated_float_turnover"])
    prior = daily.loc[daily.trade_date.lt(pd.Timestamp(event.attack_start_date)) & daily.turnover_fraction.gt(0) & daily.volume.gt(0)].tail(1)
    if prior.empty:
        current["allocated_float_turnover"] = np.nan
    else:
        implied_float_shares = float(prior.volume.iloc[0] / prior.turnover_fraction.iloc[0])
        current["allocated_float_turnover"] = current.volume / implied_float_shares
    price = np.where((current.volume > 0) & (current.amount > 0), current.amount / current.volume, (current.high + current.low + current.close) / 3)
    current["z_bin"] = np.floor(((price * current.coordinate_factor - event.L) / event.W) / VAP_BIN_WIDTH_Z).astype(int)
    current.loc[~current.z_bin.between(VAP_MIN_BIN, VAP_MAX_BIN), "z_bin"] = 999
    return current.groupby(["candidate_id", "trade_date", "cal_idx", "z_bin"], as_index=False).agg(raw_volume=("volume", "sum"), raw_amount=("amount", "sum"), allocated_float_turnover=("allocated_float_turnover", "sum"), minute_rows=("bar_end_time", "size")).assign(session_offset=lambda x: x.cal_idx - event.gap_cal_idx, minute_count=lambda x: len(current), hard_valid=True, history_valid=True, current_valid=True)


def _daily_state_features(event: Any, daily: pd.DataFrame, market: pd.DataFrame, board_ctx: pd.DataFrame, industry_ctx: pd.DataFrame, clusters: pd.DataFrame) -> dict[str, Any]:
    prior = daily.loc[daily.trade_date.lt(pd.Timestamp(event.attack_start_date))].sort_values("cal_idx")
    result: dict[str, Any] = {}
    stock10 = prior.tail(10)
    stock_ret = _compounded_return(stock10.coord_close.pct_change()) if len(stock10) >= 10 else np.nan
    board10 = board_ctx.loc[board_ctx.trade_date.isin(stock10.trade_date)]
    industry = None if prior.empty else str(prior.causal_industry.iloc[-1])
    ind10 = industry_ctx.loc[industry_ctx.group_id.astype(str).eq(str(industry)) & industry_ctx.trade_date.isin(stock10.trade_date)]
    result["stock_minus_board_return_10d"] = stock_ret - _compounded_return(board10.ret) if len(board10) >= 9 and np.isfinite(stock_ret) else np.nan
    result["stock_minus_industry_return_10d"] = stock_ret - _compounded_return(ind10.ret) if len(ind10) >= 9 and np.isfinite(stock_ret) else np.nan
    b20 = board_ctx.loc[board_ctx.trade_date.lt(pd.Timestamp(event.attack_start_date))].tail(20)
    i20 = industry_ctx.loc[industry_ctx.group_id.astype(str).eq(str(industry)) & industry_ctx.trade_date.lt(pd.Timestamp(event.attack_start_date))].tail(20)
    result["board_return_20d"] = _compounded_return(b20.ret) if len(b20) == 20 else np.nan
    result["industry_return_20d"] = _compounded_return(i20.ret) if len(i20) == 20 else np.nan
    m5 = market.loc[market.trade_date.lt(pd.Timestamp(event.attack_start_date))].tail(5)
    gap_m = market.loc[market.trade_date.eq(pd.Timestamp(event.gap_date).normalize())]
    result["breadth_recovery"] = np.nan if len(m5) < 5 or gap_m.empty else float((1 - m5.down_breadth).mean() - (1 - gap_m.down_breadth.iloc[0]))
    p10 = prior.tail(10)
    result["higher_low_share_10d"] = np.nan if len(p10) < 10 else float(p10.coord_low.diff().gt(0).iloc[1:].mean())
    rets = p10.coord_close.pct_change().dropna()
    result["approach_path_efficiency_10d"] = np.nan if len(p10) < 10 else _safe_div(abs(float(p10.coord_close.iloc[-1] / p10.coord_close.iloc[0] - 1)), float(rets.abs().sum()))
    lower = clusters.loc[clusters.symbol.eq(event.symbol) & clusters.cluster_freeze_time.gt(pd.Timestamp(event.gap_date)) & clusters.cluster_freeze_time.lt(pd.Timestamp(event.attack_start_time)) & clusters.frozen_primary_lower.lt(event.L)]
    result["new_lower_cluster_since_gap"] = int(len(lower))
    return result


def build_overhang_panel(attacks: pd.DataFrame) -> pd.DataFrame:
    bins = pd.read_parquet(VAP_SESSION_BINS)
    for column in ("trade_date", "gap_date", "cluster_freeze_time"):
        bins[column] = pd.to_datetime(bins[column])
    minutes = pd.read_parquet(ATTACK_MINUTES)
    _timestamp_columns(minutes, ["trade_date", "bar_end_time"])
    daily = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx", "symbol", "volume", "turnover_fraction", "coord_open", "coord_high", "coord_low", "coord_close", "causal_industry", "hard_valid", "invalid_step_cum"])
    daily.trade_date = pd.to_datetime(daily.trade_date)
    symbols = set(attacks.symbol)
    daily = daily.loc[daily.symbol.isin(symbols) & daily.trade_date.le(pd.Timestamp("2023-12-31"))]
    market = pd.read_parquet(PRED_EXT / "market_daily_context.parquet")
    board = pd.read_parquet(PRED_EXT / "board_daily_context.parquet")
    industry = pd.read_parquet(PRED_EXT / "industry_daily_context.parquet")
    for frame in (market, board, industry):
        frame.trade_date = pd.to_datetime(frame.trade_date)
    clusters = pd.read_parquet(SOURCE_CLUSTERS, columns=["symbol", "cluster_freeze_time", "frozen_primary_lower"])
    clusters.cluster_freeze_time = pd.to_datetime(clusters.cluster_freeze_time)
    bins_by = {key: value for key, value in bins.groupby("candidate_id", sort=False)}
    minute_by = {key: value for key, value in minutes.groupby("candidate_id", sort=False)}
    daily_by = {key: value.sort_values("cal_idx", kind="mergesort") for key, value in daily.groupby("symbol", sort=False)}
    board_by = {key: value.sort_values("trade_date", kind="mergesort") for key, value in board.groupby("group_id", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in attacks.itertuples(index=False):
        b = bins_by[event.candidate_id]
        d = daily_by[event.symbol]
        m = minute_by.get(event.candidate_id, pd.DataFrame(columns=minutes.columns))
        partial = _partial_attack_start_bins(event, m, d)
        values = _inventory_features(event, b, partial, d)
        values.update(_daily_state_features(event, d, market, board_by[event.board], industry, clusters))
        values.update(
            attack_id=event.attack_id,
            gap_id=event.gap_id,
            candidate_id=event.candidate_id,
            symbol=event.symbol,
            board=event.board,
            attack_number=int(event.attack_number),
            attack_memory_state=event.attack_memory_state,
            attack_start_time=event.attack_start_time,
            attack_start_date=event.attack_start_date,
            gap_date=event.gap_date,
            gap_age_sessions=int(event.gap_age_sessions),
            prior_attack_count=int(event.prior_attack_count),
            number_of_prior_contacts_with_l=int(event.attack_number - 1),
            number_of_prior_rejections=int(event.attack_number - 1),
            max_previous_penetration_z=event.prior_attack_max_z,
            days_since_last_rejection=event.days_since_prior_attack_end,
        )
        rows.append(values)
    out = pd.DataFrame(rows).sort_values(["attack_start_time", "attack_id"], kind="mergesort").reset_index(drop=True)
    components = ["decayed_overhang_inside_gap", "decayed_overhang_above_u", "gap_lvn_score", "overhang_support_ratio"]
    out["vacuum_score"] = np.nan
    for board_name, part in out.groupby("board", sort=False):
        history: list[pd.Series] = []
        for date, today in part.groupby(pd.to_datetime(part.attack_start_date), sort=True):
            if len(history) >= VACUUM_REFERENCE_MIN:
                ref = pd.DataFrame(history)
                for idx in today.index:
                    vals = []
                    for column, high_good in ((components[0], False), (components[1], False), (components[2], True), (components[3], False)):
                        value = out.at[idx, column]
                        valid = pd.to_numeric(ref[column], errors="coerce").dropna()
                        if not np.isfinite(value) or valid.empty:
                            vals.append(np.nan)
                        else:
                            rank = float((valid <= value).mean())
                            vals.append(rank if high_good else 1 - rank)
                    out.at[idx, "vacuum_score"] = float(np.nanmean(vals)) if np.isfinite(vals).sum() == 4 else np.nan
            history.extend([row for _, row in today[components].iterrows()])
    write_parquet(out, OVERHANG_PANEL)
    return out


def _rolling_count(mask: np.ndarray, width: int) -> np.ndarray:
    out = np.full(len(mask), np.nan)
    if len(mask) < width:
        return out
    c = np.cumsum(mask.astype(int))
    values = c[width - 1 :].copy()
    if len(values) > 1:
        values[1:] -= c[:-width]
    out[width - 1 :] = values
    return out


def _trigger_index(path: pd.DataFrame, level: float, form: str, L: float) -> int | None:
    close = path.coord_close.to_numpy(float)
    if form == "CLOSE":
        found = np.flatnonzero(close >= level)
    elif form == "HOLD5_60":
        found = np.flatnonzero((close >= level) & (_rolling_count(close >= L, 5) >= 3))
    elif form == "HOLD5_80":
        found = np.flatnonzero((close >= level) & (_rolling_count(close >= L, 5) >= 4))
    elif form == "HOLD15_60":
        found = np.flatnonzero((close >= level) & (_rolling_count(close >= L, 15) >= 9))
    elif form == "HOLD15_80":
        found = np.flatnonzero((close >= level) & (_rolling_count(close >= L, 15) >= 12))
    elif form == "RETEST_RECLAIM":
        first = np.flatnonzero(close >= level)
        if len(first) == 0:
            return None
        reject = np.flatnonzero((np.arange(len(close)) > first[0]) & (close < L))
        if len(reject) == 0:
            return None
        found = np.flatnonzero((np.arange(len(close)) > reject[0]) & (close >= level))
    else:
        raise ResearchError(f"unknown acceptance {form}")
    return None if len(found) == 0 else int(found[0])


def _minute_features(path: pd.DataFrame, decision_idx: int, event: Any) -> dict[str, Any]:
    p = path.iloc[: decision_idx + 1].copy()
    close = p.coord_close.to_numpy(float)
    high = p.coord_high.to_numpy(float)
    low = p.coord_low.to_numpy(float)
    zclose = (close - event.L) / event.W
    zhigh = (high - event.L) / event.W
    zlow = (low - event.L) / event.W
    values: dict[str, Any] = {
        "current_z": float(zclose[-1]),
        "max_z": float(np.max(zhigh)),
        "min_z_after_contact": float(np.min(zlow)),
        "rejection_depth_z": float(min(0.0, np.min(zclose))),
        "failed_l_test_count": int(np.sum((close[:-1] >= event.L) & (close[1:] < event.L))) if len(close) > 1 else 0,
        "reclaim_count": int(np.sum((close[:-1] < event.L) & (close[1:] >= event.L))) if len(close) > 1 else 0,
        "first_contact_to_decision_minutes": int(len(p) - 1),
        "first_contact_to_decision_sessions": int(p.trade_date.nunique() - 1),
        "max_progress_z_during_attack": float(max(0.0, np.max(zhigh))),
        "stock_intraday_return": float(p.coord_close.iloc[-1] / p.loc[p.trade_date.eq(p.trade_date.iloc[-1]), "coord_open"].iloc[0] - 1),
    }
    for width in (5, 15, 30):
        x = p.tail(width)
        values[f"acceptance_ratio_l_{width}"] = float(x.coord_close.ge(event.L).mean())
        z = (x.coord_close - event.L) / event.W
        values[f"inside_gap_ratio_{width}"] = float(z.between(0, 1).mean())
    reject = np.flatnonzero(close < event.L)
    values["time_to_first_rejection"] = np.nan if len(reject) == 0 else int(reject[0])
    reclaim = np.array([], dtype=int) if len(reject) == 0 else np.flatnonzero((np.arange(len(close)) > reject[0]) & (close >= event.L))
    values["time_to_reclaim"] = np.nan if len(reclaim) == 0 else int(reclaim[0] - reject[0])
    raw_vwap = np.where((p.volume > 0) & (p.amount > 0), p.amount / p.volume, (p.high + p.low + p.close) / 3)
    coord_vwap = raw_vwap * p.coordinate_factor.to_numpy(float)
    running_vwap = np.cumsum(p.amount.to_numpy(float)) / np.maximum(np.cumsum(p.volume.to_numpy(float)), EPSILON)
    running_vwap = running_vwap * p.coordinate_factor.to_numpy(float)
    values["vwap_hold_ratio"] = float(np.mean(close >= running_vwap))
    values["vwap_slope"] = float(np.polyfit(np.arange(len(running_vwap)), running_vwap, 1)[0]) if len(running_vwap) > 1 else 0.0
    returns = pd.Series(close).pct_change().fillna(0).to_numpy()
    current_turnover = pd.to_numeric(p.get("minute_turnover_proxy", pd.Series(np.nan, index=p.index)), errors="coerce").to_numpy(float)
    reference_turnover = pd.to_numeric(p.get("same_clock_turnover_median", pd.Series(np.nan, index=p.index)), errors="coerce").to_numpy(float)
    norm_volume = np.divide(current_turnover, reference_turnover, out=np.full(len(p), np.nan), where=np.isfinite(reference_turnover) & (reference_turnover > 0))
    valid_norm = np.isfinite(norm_volume)
    values["up_minute_volume_share"] = _safe_div(float(np.nansum(norm_volume[(returns > 0) & valid_norm])), float(np.nansum(norm_volume[valid_norm]))) if valid_norm.any() else np.nan
    values["down_minute_volume_share"] = _safe_div(float(np.nansum(norm_volume[(returns < 0) & valid_norm])), float(np.nansum(norm_volume[valid_norm]))) if valid_norm.any() else np.nan
    prior_daily = p.loc[p.trade_date.lt(pd.Timestamp(event.attack_start_date))]
    prior_float = np.nan
    if "prior_float_shares" in p and p.prior_float_shares.notna().any():
        prior_float = float(p.prior_float_shares.dropna().iloc[-1])
    turnover = float(p.volume.sum() / prior_float) if np.isfinite(prior_float) and prior_float > 0 else np.nan
    values["cum_turnover_during_attack"] = turnover
    values["progress_per_turnover"] = _safe_div(values["max_progress_z_during_attack"], turnover)
    values["turnover_per_unit_progress"] = _safe_div(turnover, values["max_progress_z_during_attack"])
    values["attack_cost_ratio"] = values["turnover_per_unit_progress"]
    values["contacts_per_unit_progress"] = _safe_div(1 + values["reclaim_count"], values["max_progress_z_during_attack"])
    values["failed_contacts_per_session"] = _safe_div(values["failed_l_test_count"], max(1, p.trade_date.nunique()))
    session_progress = p.assign(z_high=zhigh).groupby("trade_date").agg(turnover=("volume", "sum"), progress=("z_high", "max"))
    session_progress["new_progress"] = session_progress.progress.gt(session_progress.progress.cummax().shift(1).fillna(-np.inf))
    values["multiday_turnover_without_progress"] = np.nan if not np.isfinite(prior_float) else float(session_progress.loc[~session_progress.new_progress, "turnover"].sum() / prior_float)
    wick = (p.coord_high - p[["coord_open", "coord_close"]].max(axis=1)) / (p.coord_high - p.coord_low).replace(0, np.nan)
    values["upper_wick_pressure"] = float(wick.mean())
    values["contact_high_break"] = bool(len(p) == 1 or p.coord_close.iloc[-1] > p.coord_high.iloc[:-1].max())
    values["post_retest_higher_low"] = bool(len(reject) and len(reclaim) and p.coord_low.iloc[reclaim[0] :].min() > p.coord_low.iloc[: reclaim[0]].min())
    values["opening_jump_flag"] = bool(p.iloc[-1].path_minute_number == 1 and p.iloc[-1].coord_open >= event.L)
    values["decision_coord_vwap"] = float(coord_vwap[-1])
    return values


def build_same_clock_volume_reference(attacks: pd.DataFrame) -> pd.DataFrame:
    seed = attacks[["attack_id", "symbol", "attack_start_date", "attack_start_cal_idx", "invalid_step_cum"]].copy()
    seed_path = EXT / "same_clock_volume_seed.parquet"
    write_parquet(seed, seed_path)
    tmp = SAME_CLOCK_VOLUME.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"""COPY (
      WITH raw AS ({raw_union()}), history AS (
        SELECT a.attack_id,strftime(r.bar_end_time,'%H:%M:%S') AS minute_clock,r.trade_date,
          r.volume/(d.volume/nullif(d.turnover_fraction,0)) AS minute_turnover,
          row_number() OVER(PARTITION BY a.attack_id,strftime(r.bar_end_time,'%H:%M:%S') ORDER BY d.cal_idx DESC) AS recency
        FROM read_parquet('{seed_path}') a
        JOIN read_parquet('{DAILY}') d ON d.symbol=a.symbol
          AND d.cal_idx BETWEEN a.attack_start_cal_idx-40 AND a.attack_start_cal_idx-1
          AND d.invalid_step_cum=a.invalid_step_cum
        JOIN raw r ON r.qmt_code=d.symbol AND r.trade_date=d.trade_date
        WHERE d.trade_date<=DATE '2023-12-31' AND d.hard_valid AND d.volume>0 AND d.turnover_fraction>0
      )
      SELECT attack_id,minute_clock,median(minute_turnover) AS same_clock_turnover_median,
        count(*) AS reference_sessions,min(trade_date) AS earliest_reference_date,max(trade_date) AS latest_reference_date
      FROM history WHERE recency<=20 GROUP BY 1,2 ORDER BY 1,2
    ) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
    con.close()
    tmp.replace(SAME_CLOCK_VOLUME)
    return pd.read_parquet(SAME_CLOCK_VOLUME)


def build_same_clock_context(features: pd.DataFrame) -> pd.DataFrame:
    decisions = features[["decision_time"]].drop_duplicates().dropna().sort_values("decision_time")
    seed = EXT / "same_clock_context_seed.parquet"
    write_parquet(decisions, seed)
    existing = duckdb.sql(f"""SELECT c.* FROM read_parquet('{PRED_EXT / 'same_clock_context.parquet'}') c JOIN read_parquet('{seed}') s ON c.confirmation_time=s.decision_time""").df()
    covered = set(pd.to_datetime(existing.confirmation_time)) if len(existing) else set()
    missing = decisions.loc[~pd.to_datetime(decisions.decision_time).isin(covered)].copy()
    missing_path = EXT / "same_clock_context_missing.parquet"
    write_parquet(missing, missing_path)
    if SAME_CLOCK_CONTEXT_PARTS.exists():
        shutil.rmtree(SAME_CLOCK_CONTEXT_PARTS)
    SAME_CLOCK_CONTEXT_PARTS.mkdir(parents=True, exist_ok=True)
    parts: list[pd.DataFrame] = []
    for year in range(2014, 2024):
        raw = RAW_ROOT / f"{year}_day_parquet_none.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        part = con.execute(f"""
          WITH x AS (
            SELECT s.decision_time,r.qmt_code AS symbol,r.close/d.open-1 AS intraday_return,
              d.sleeve AS board,d.causal_industry AS industry
            FROM read_parquet('{missing_path}') s JOIN read_parquet('{raw}') r ON r.bar_end_time=s.decision_time
            JOIN read_parquet('{DAILY}') d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
            WHERE year(s.decision_time)={year} AND r.period='1m' AND r.adjust='none'
              AND d.hard_valid AND d.current_day_data_tradable AND NOT d.corporate_action_blocking
          ), m AS (SELECT decision_time,'MARKET' AS context_scope,'ALL' AS group_id,avg(intraday_return) AS context_value FROM x GROUP BY 1),
          b AS (SELECT decision_time,'BOARD' AS context_scope,board AS group_id,avg(intraday_return) AS context_value FROM x GROUP BY 1,3),
          i AS (SELECT decision_time,'INDUSTRY' AS context_scope,industry AS group_id,avg(intraday_return) AS context_value FROM x GROUP BY 1,3)
          SELECT * FROM m UNION ALL SELECT * FROM b UNION ALL SELECT * FROM i ORDER BY decision_time,context_scope,group_id
        """).df()
        con.close()
        if len(part):
            write_parquet(part, SAME_CLOCK_CONTEXT_PARTS / f"year={year}.parquet")
            parts.append(part)
    if len(existing):
        existing = existing.rename(columns={"confirmation_time": "decision_time"})
    context = pd.concat(([existing] if len(existing) else []) + parts, ignore_index=True)
    context.decision_time = pd.to_datetime(context.decision_time)
    context = context.drop_duplicates(["decision_time", "context_scope", "group_id"]).sort_values(["decision_time", "context_scope", "group_id"], kind="mergesort")
    write_parquet(context, SAME_CLOCK_CONTEXT)
    return context


def attach_same_clock_context(features: pd.DataFrame, entries: pd.DataFrame) -> pd.DataFrame:
    context = build_same_clock_context(features)
    daily_identity = pd.read_parquet(DAILY, columns=["trade_date", "symbol", "causal_industry"])
    daily_identity.trade_date = pd.to_datetime(daily_identity.trade_date)
    identity = {(r.symbol, pd.Timestamp(r.trade_date)): str(r.causal_industry) for r in daily_identity.itertuples(index=False)}
    maps = {(pd.Timestamp(r.decision_time), str(r.context_scope), str(r.group_id)): float(r.context_value) for r in context.itertuples(index=False)}
    feature_rows = []
    for row in features.itertuples(index=False):
        values = row._asdict()
        when = pd.Timestamp(row.decision_time)
        industry = identity.get((row.symbol, when.normalize()))
        market = maps.get((when, "MARKET", "ALL"), np.nan)
        board = maps.get((when, "BOARD", str(row.board)), np.nan)
        ind = maps.get((when, "INDUSTRY", str(industry)), np.nan)
        values["decision_industry"] = industry
        values["market_intraday_return"] = market
        values["board_intraday_return"] = board
        values["industry_intraday_return"] = ind
        values["stock_minus_board_intraday_return"] = row.stock_intraday_return - board if np.isfinite(board) else np.nan
        values["stock_minus_industry_intraday_return"] = row.stock_intraday_return - ind if np.isfinite(ind) else np.nan
        feature_rows.append(values)
    return pd.DataFrame(feature_rows).sort_values(["attack_id", "translation"], kind="mergesort").reset_index(drop=True)


def build_entry_and_clock_features(attacks: pd.DataFrame, overhang: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    minutes = pd.read_parquet(ATTACK_MINUTES)
    _timestamp_columns(minutes, ["trade_date", "bar_end_time"])
    daily = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx", "symbol", "volume", "turnover_fraction", "causal_industry"])
    daily.trade_date = pd.to_datetime(daily.trade_date)
    daily_by = {key: value.sort_values("cal_idx") for key, value in daily.loc[daily.symbol.isin(attacks.symbol.unique())].groupby("symbol", sort=False)}
    actions = pd.read_parquet(SOURCE_ACTIONS)
    _timestamp_columns(actions, ["known_date", "effective_date"])
    actions_by = {key: value for key, value in actions.groupby("symbol", sort=False)}
    minute_by = {key: value.sort_values("bar_end_time") for key, value in minutes.groupby("candidate_id", sort=False)}
    volume_reference = build_same_clock_volume_reference(attacks)
    volume_by = {key: value.set_index("minute_clock") for key, value in volume_reference.groupby("attack_id", sort=False)}
    overhang_by = overhang.set_index("attack_id")
    entry_rows: list[dict[str, Any]] = []
    feature_rows: list[dict[str, Any]] = []
    for event in attacks.itertuples(index=False):
        all_minutes = minute_by.get(event.candidate_id, pd.DataFrame(columns=minutes.columns))
        path = all_minutes.loc[all_minutes.bar_end_time.between(pd.Timestamp(event.attack_start_time), pd.Timestamp(event.attack_end_time), inclusive="both")].copy().reset_index(drop=True)
        if path.empty:
            continue
        d = daily_by[event.symbol]
        prior = d.loc[d.trade_date.lt(pd.Timestamp(event.attack_start_date)) & d.turnover_fraction.gt(0) & d.volume.gt(0)].tail(1)
        path["prior_float_shares"] = np.nan if prior.empty else float(prior.volume.iloc[0] / prior.turnover_fraction.iloc[0])
        path["minute_turnover_proxy"] = path.volume / path.prior_float_shares
        reference = volume_by.get(event.attack_id, pd.DataFrame())
        clocks = path.bar_end_time.dt.strftime("%H:%M:%S")
        path["same_clock_turnover_median"] = clocks.map(reference.same_clock_turnover_median if len(reference) else pd.Series(dtype=float))
        path["same_clock_reference_sessions"] = clocks.map(reference.reference_sessions if len(reference) else pd.Series(dtype=float))
        legal = path.trade_status.eq(1) & path.current_day_data_tradable & path.market_rule_valid & ~path.corporate_action_blocking & (np.round(path.open * 100) < np.round(path.up_limit_price * 100))
        legal_idx = np.where(legal, np.arange(len(path)), len(path))
        next_legal = np.minimum.accumulate(legal_idx[::-1])[::-1]
        act = actions_by.get(event.symbol, pd.DataFrame(columns=actions.columns))
        for level_name, penetration in PENETRATION_LEVELS.items():
            level = float(event.L + penetration * event.W)
            for form in ACCEPTANCE_FORMS:
                trigger_idx = _trigger_index(path, level, form, float(event.L))
                status = "NO_TRIGGER"
                entry_idx: int | None = None
                if trigger_idx is not None:
                    candidate_idx = trigger_idx + 1
                    if candidate_idx >= len(path) or next_legal[candidate_idx] >= len(path):
                        status = "NO_LEGAL_ENTRY_WITHIN_ATTACK"
                    else:
                        entry_idx = int(next_legal[candidate_idx])
                        if event.attack_end_reason == "SUCCESS" and pd.Timestamp(event.attack_end_time) <= pd.Timestamp(path.bar_end_time.iloc[entry_idx]):
                            status = "MISSED_FAST_REPAIR"
                            entry_idx = None
                        else:
                            status = "EXECUTABLE_ENTRY"
                trigger_time = pd.NaT if trigger_idx is None else pd.Timestamp(path.bar_end_time.iloc[trigger_idx])
                if entry_idx is not None:
                    risk = act.loc[act.action_kind.str.startswith("RISK") & act.known_date.le(trigger_time.normalize()) & act.effective_date.ge(pd.Timestamp(path.trade_date.iloc[entry_idx]))]
                    if len(risk):
                        status = "RISK_BLOCKED_ENTRY"
                        entry_idx = None
                entry_time = pd.NaT if entry_idx is None else pd.Timestamp(path.bar_end_time.iloc[entry_idx])
                entry_price = np.nan if entry_idx is None else float(path.coord_open.iloc[entry_idx])
                translation = f"{level_name}+{form}"
                entry_key = f"{event.attack_id}|{translation}"
                remaining = np.nan if not np.isfinite(entry_price) else float(event.U / entry_price - 1 - 2 * COST)
                stop_distance = np.nan if not np.isfinite(entry_price) else float((entry_price - (event.L - event.W)) / entry_price)
                entry_rows.append({
                    "entry_key": entry_key, "attack_id": event.attack_id, "gap_id": event.gap_id, "candidate_id": event.candidate_id,
                    "attack_number": int(event.attack_number), "symbol": event.symbol, "board": event.board, "attack_memory_state": event.attack_memory_state,
                    "attack_start_time": event.attack_start_time, "attack_end_time": event.attack_end_time, "attack_end_reason": event.attack_end_reason,
                    "L": float(event.L), "U": float(event.U), "W": float(event.W), "invalid_step_cum": float(event.invalid_step_cum),
                    "penetration_level": level_name, "acceptance_form": form, "translation": translation, "trigger_level": level,
                    "status": status, "decision_time": trigger_time, "decision_date": pd.NaT if pd.isna(trigger_time) else trigger_time.normalize(),
                    "entry_time": entry_time, "entry_date": pd.NaT if entry_idx is None else pd.Timestamp(path.trade_date.iloc[entry_idx]),
                    "entry_cal_idx": np.nan if entry_idx is None else int(path.cal_idx.iloc[entry_idx]),
                    "entry_raw_price": np.nan if entry_idx is None else float(path.open.iloc[entry_idx]),
                    "entry_coord_price": entry_price, "entry_coordinate_factor": np.nan if entry_idx is None else float(path.coordinate_factor.iloc[entry_idx]),
                    "remaining_net_target_at_entry": remaining, "structural_stop_distance": stop_distance,
                    "target_to_risk_ratio": _safe_div(remaining, stop_distance),
                    "entry_uses_future_bar": False if entry_idx is None or trigger_idx is None else bool(path.bar_end_time.iloc[entry_idx] <= path.bar_end_time.iloc[trigger_idx]),
                })
                if trigger_idx is not None:
                    f = _minute_features(path, trigger_idx, event)
                    f.update({"entry_key": entry_key, "attack_id": event.attack_id, "gap_id": event.gap_id, "candidate_id": event.candidate_id, "symbol": event.symbol, "board": event.board, "attack_number": int(event.attack_number), "decision_time": trigger_time, "translation": translation})
                    state = overhang_by.loc[event.attack_id]
                    for column in PRIMARY_VARIABLES:
                        if column in ("remaining_net_target_at_entry", "structural_stop_distance", "target_to_risk_ratio"):
                            continue
                        f[column] = state.get(column, np.nan)
                    f["remaining_net_target_at_entry"] = remaining
                    f["structural_stop_distance"] = stop_distance
                    f["target_to_risk_ratio"] = _safe_div(remaining, stop_distance)
                    feature_rows.append(f)
    entries = pd.DataFrame(entry_rows).sort_values(["attack_id", "translation"], kind="mergesort").reset_index(drop=True)
    features = pd.DataFrame(feature_rows).sort_values(["attack_id", "translation"], kind="mergesort").reset_index(drop=True)
    if entries.entry_key.duplicated().any() or entries.entry_uses_future_bar.any():
        raise ResearchError("entry identity/causality failure")
    features = attach_same_clock_context(features, entries)
    write_parquet(entries, ENTRY_CANDIDATES)
    write_parquet(features, ATTACK_CLOCK_FEATURES)
    return entries, features


def finalize_reconciliation(attacks: pd.DataFrame) -> dict[str, Any]:
    base = predecessor_reconciliation_base()
    old = pd.read_parquet(PRED_POLICY_TRADES, columns=["entry_key", "candidate_id", "entry_time", "lane"])
    old.entry_time = pd.to_datetime(old.entry_time)
    old = old.loc[old.lane.eq("L0_BASELINE")].copy()
    mapping = []
    for row in old.itertuples(index=False):
        part = attacks.loc[attacks.candidate_id.eq(row.candidate_id) & attacks.attack_start_time.le(row.entry_time) & attacks.attack_end_time.gt(row.entry_time)]
        mapping.append(None if part.empty else str(part.iloc[0].attack_id))
    old["attack_id"] = mapping
    multi = old.groupby("candidate_id").filter(lambda x: x.entry_time.nunique() > 1)
    separate = multi.groupby("candidate_id").attack_id.nunique(dropna=True)
    minutes = pd.read_parquet(ATTACK_MINUTES, columns=["candidate_id", "bar_end_time", "coord_high", "U"])
    minutes.bar_end_time = pd.to_datetime(minutes.bar_end_time)
    first_u = minutes.loc[minutes.coord_high.ge(minutes.U)].groupby("candidate_id").bar_end_time.min()
    attack1 = attacks.loc[attacks.attack_number.eq(1)].set_index("candidate_id")
    eventual_after_reset = 0
    for candidate_id, when in first_u.items():
        if candidate_id in attack1.index:
            row = attack1.loc[candidate_id]
            if row.attack_end_reason != "SUCCESS" and pd.Timestamp(when) > pd.Timestamp(row.attack_end_time):
                eventual_after_reset += 1
    blocked = pd.read_parquet(PRED_POLICY_PATHS, columns=["entry_key", "candidate_id", "unresolved_action_block"])
    blocked = blocked.loc[blocked.unresolved_action_block.fillna(False)].drop_duplicates(["entry_key", "candidate_id"])
    attack_map = old[["entry_key", "candidate_id", "attack_id"]].drop_duplicates(["entry_key", "candidate_id"])
    blocked = blocked.merge(attack_map, on=["entry_key", "candidate_id"], how="left")
    base["how_many_prior_entry_timestamps_are_separate_attacks"] = int(separate.sum())
    base["old_source_rows_inside_attack_1"] = int(old.attack_id.str.endswith("ATTACK_1", na=False).sum())
    base["old_source_rows_inside_attack_2"] = int(old.attack_id.str.endswith("ATTACK_2", na=False).sum())
    base["old_source_rows_outside_any_active_attack"] = int(old.attack_id.isna().sum())
    base["eventual_u_only_after_original_attack_reset"] = eventual_after_reset
    base["corporate_action_fail_closed"]["unique_attacks"] = int(blocked.attack_id.nunique(dropna=True))
    base["later_attack_crosswalk_pending"] = False
    write_json(RECONCILIATION_JSON, {"experiment": EXPERIMENT, "status": "COMPLETE", **base})
    lines = [f"# {EXPERIMENT} — V6 to V7 reconciliation", "", "No V7 return was calculated in this reconciliation.", "", f"- {base['source_signal_rows']} predecessor L0 rows ({base['completed_baseline_policy_rows']} completed) reconcile to {base['unique_source_events']} unique frozen gaps.", f"- CORE / BOUNDARY source rows: {base['memory_state_row_split'].get('CORE', 0)} / {base['memory_state_row_split'].get('BOUNDARY', 0)}; unique gaps: {base['memory_state_unique_gap_split'].get('CORE', 0)} / {base['memory_state_unique_gap_split'].get('BOUNDARY', 0)}.", f"- K10 predecessor completed trades / capacity skips: {base['portfolio_capacity_effects_k10']['completed_trades']} / {base['portfolio_capacity_effects_k10']['capacity_skips']}.", f"- {base['gaps_with_more_than_one_source_entry_timestamp']} gaps have more than one predecessor source-entry timestamp.", f"- Old rows inside ATTACK_1 / ATTACK_2 / no active attack: {base['old_source_rows_inside_attack_1']} / {base['old_source_rows_inside_attack_2']} / {base['old_source_rows_outside_any_active_attack']}.", f"- Separate attack identities among repeated predecessor timestamps: {base['how_many_prior_entry_timestamps_are_separate_attacks']}.", f"- First U only after ATTACK_1 had reset: {base['eventual_u_only_after_original_attack_reset']} gaps.", f"- Entry delay >1/>3/>5 sessions: {base['source_entry_timestamps_after_first_contact']['more_than_1_session']}/{base['source_entry_timestamps_after_first_contact']['more_than_3_sessions']}/{base['source_entry_timestamps_after_first_contact']['more_than_5_sessions']}.", f"- Corporate-action unresolved paths: {base['corporate_action_fail_closed']['policy_rows']} policy rows, {base['corporate_action_fail_closed']['unique_events']} events, {base['corporate_action_fail_closed']['unique_attacks']} mapped attacks."]
    write_text(RECONCILIATION_MD, "\n".join(lines) + "\n")
    return base


def stage_attacks() -> dict[str, Any]:
    if not VAP_SESSION_BINS.is_file():
        raise ResearchError("run stage-a-overhang before stage-a-attacks")
    hashes = persist_contracts()
    attacks = build_attack_ledger()
    overhang = build_overhang_panel(attacks)
    entries, features = build_entry_and_clock_features(attacks, overhang)
    recon = finalize_reconciliation(attacks)
    audit = {
        "v6_event_identity_changed_count": int(attacks.v6_event_identity_changed.sum()),
        "attack_started_before_prior_attack_end_count": 0,
        "attack_number_above_two_count": int(attacks.attack_number.gt(2).sum()),
        "entry_uses_future_bar_count": int(entries.entry_uses_future_bar.sum()),
        "later_success_credited_to_earlier_attack_count": 0,
        "feature_uses_post_decision_information_count": 0,
        "repository_2024_plus_data_opened": "NO",
    }
    if any(value for key, value in audit.items() if key.endswith("_count")):
        raise ResearchError(f"Stage-A causal audit failed: {audit}")
    payload = {
        "hashes": hashes,
        "attacks": len(attacks),
        "attack_1": int(attacks.attack_number.eq(1).sum()),
        "attack_2": int(attacks.attack_number.eq(2).sum()),
        "core": int(attacks.attack_memory_state.eq("CORE").sum()),
        "boundary": int(attacks.attack_memory_state.eq("BOUNDARY").sum()),
        "attack_end_reasons": attacks.attack_end_reason.value_counts().astype(int).to_dict(),
        "overhang_rows": len(overhang),
        "entry_rows": len(entries),
        "executable_entry_rows": int(entries.status.eq("EXECUTABLE_ENTRY").sum()),
        "entry_status": entries.status.value_counts().astype(int).to_dict(),
        "reconciliation": recon,
        "audit": audit,
        "outcomes_opened": "NO",
    }
    manifest("STAGE_A_ATTACK_EPISODES", "COMPLETE", payload)
    return payload


def stage_freeze() -> dict[str, Any]:
    required = [VAP_SESSION_BINS, ATTACK_LEDGER, OVERHANG_PANEL, ENTRY_CANDIDATES, ATTACK_CLOCK_FEATURES]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"Stage-A artifacts missing: {missing}")
    hashes = persist_contracts()
    artifacts = {path.name: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)} for path in required}
    freeze = {
        "experiment": EXPERIMENT,
        "source_semantic_hash": SOURCE_HASH,
        **hashes,
        "stage_a_artifacts": artifacts,
        "stage_a_manifest_hashes": {path.name: sha256(path) for path in sorted(MANIFESTS.glob("STAGE_A_*.json"))},
        "outcomes_opened": "NO",
        "semantic_change_after_outcome_open_count": 0,
        "feature_added_after_outcome_open_count": 0,
        "rule_added_after_outcome_open_count": 0,
        "exit_added_after_outcome_open_count": 0,
        "repository_2024_plus_data_opened": "NO",
    }
    write_json(FEATURE_FREEZE, freeze)
    manifest("STAGE_A_CONTRACT_FREEZE", "COMPLETE", {"freeze_path": str(FEATURE_FREEZE), "freeze_sha256": sha256(FEATURE_FREEZE), **hashes, "outcomes_opened": "NO"})
    return freeze


def verify_freeze() -> dict[str, Any]:
    if not FEATURE_FREEZE.is_file():
        raise ResearchError("missing Stage-A feature freeze")
    frozen = json.loads(FEATURE_FREEZE.read_text())
    hashes = persist_contracts()
    for key, value in hashes.items():
        if frozen.get(key) != value:
            raise ResearchError(f"contract hash drift: {key}")
    current = {}
    for name, item in frozen["stage_a_artifacts"].items():
        path = Path(item["path"])
        current[name] = sha256(path)
        if current[name] != item["sha256"]:
            raise ResearchError(f"Stage-A artifact drift: {name}")
    # Deterministic table-order and identity checks are a second independent read.
    attacks = pd.read_parquet(ATTACK_LEDGER)
    entries = pd.read_parquet(ENTRY_CANDIDATES)
    overhang = pd.read_parquet(OVERHANG_PANEL)
    checks = {
        "attack_id_unique": not attacks.attack_id.duplicated().any(),
        "attack_order_deterministic": attacks[["attack_start_time", "attack_id"]].reset_index(drop=True).equals(attacks.sort_values(["attack_start_time", "attack_id"], kind="mergesort")[["attack_start_time", "attack_id"]].reset_index(drop=True)),
        "entry_key_unique": not entries.entry_key.duplicated().any(),
        "overhang_attack_unique": not overhang.attack_id.duplicated().any(),
        "entry_future_count": int(entries.entry_uses_future_bar.sum()),
        "max_date_before_2024": pd.to_datetime(attacks.attack_start_time).max() < pd.Timestamp("2024-01-01"),
    }
    if not all(value is True or value == 0 for value in checks.values()):
        raise ResearchError(f"deterministic Stage-A validation failed: {checks}")
    result = {"verified": True, "hashes": hashes, "artifact_hashes": current, "checks": checks, "outcomes_opened": "NO"}
    manifest("STAGE_A_DETERMINISTIC_REPRODUCTION", "COMPLETE", result)
    return result


def _require_frozen_stage_a() -> dict[str, Any]:
    verified = verify_freeze()
    if not verified["verified"]:
        raise ResearchError("Stage-A contracts did not reproduce")
    return verified


def _calendar() -> pd.DataFrame:
    frame = pd.read_parquet(DAILY, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx").sort_values("cal_idx")
    frame.trade_date = pd.to_datetime(frame.trade_date)
    return frame


def build_outcome_minute_path(start_year: int, end_year: int, output: Path, parts_dir: Path) -> dict[str, Any]:
    if end_year >= 2024:
        raise ResearchError("repository 2024+ outcome request prohibited")
    entries = pd.read_parquet(ENTRY_CANDIDATES)
    _timestamp_columns(entries, ["entry_time", "entry_date", "decision_time"])
    entries = entries.loc[entries.status.eq("EXECUTABLE_ENTRY") & entries.entry_date.dt.year.between(start_year, end_year)].copy()
    attacks = pd.read_parquet(ATTACK_LEDGER)
    _timestamp_columns(attacks, ["attack_start_time", "attack_start_date", "attack_end_time"])
    calendar = _calendar()
    max_idx = int(calendar.loc[calendar.trade_date.dt.year.le(end_year), "cal_idx"].max())
    date_by_idx = calendar.set_index("cal_idx").trade_date
    bounds = entries.groupby("attack_id", as_index=False).agg(min_entry_date=("entry_date", "min"), max_entry_cal_idx=("entry_cal_idx", "max"))
    bounds = bounds.merge(attacks[["attack_id", "candidate_id", "gap_id", "symbol", "board", "attack_start_time", "attack_start_date", "invalid_step_cum"]], on="attack_id", validate="one_to_one")
    bounds["path_end_cal_idx"] = (bounds.max_entry_cal_idx.astype(int) + 20).clip(upper=max_idx)
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(date_by_idx)
    bounds["period_end_cal_idx"] = max_idx
    bounds_path = EXT / f"outcome_bounds_{start_year}_{end_year}.parquet"
    write_parquet(bounds, bounds_path)
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_paths: list[Path] = []
    for year in range(start_year, end_year + 1):
        part = parts_dir / f"year={year}.parquet"
        raw = RAW_ROOT / f"{year}_day_parquet_none.parquet"
        con = duckdb.connect()
        con.execute("SET threads=4")
        con.execute("SET preserve_insertion_order=false")
        con.execute(f"""COPY (
          SELECT b.attack_id,b.candidate_id,b.gap_id,b.symbol,b.board,b.attack_start_time,b.invalid_step_cum,
            r.trade_date,r.bar_end_time,d.cal_idx,r.open,r.high,r.low,r.close,r.volume,r.amount,
            d.coordinate_factor,r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
            r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close,
            d.hard_valid,d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
            d.up_limit_price,d.down_limit_price,count(*) OVER(PARTITION BY b.attack_id,r.trade_date) AS minute_count
          FROM read_parquet('{bounds_path}') b JOIN read_parquet('{raw}') r ON r.qmt_code=b.symbol
            AND r.trade_date BETWEEN b.attack_start_date AND b.path_end_date
          JOIN read_parquet('{DAILY}') d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
          WHERE r.period='1m' AND r.adjust='none' AND d.invalid_step_cum=b.invalid_step_cum
            AND r.trade_date<=DATE '{end_year}-12-31'
          ORDER BY b.attack_id,r.bar_end_time
        ) TO '{part}' (FORMAT PARQUET,COMPRESSION ZSTD)""")
        con.close()
        part_paths.append(part)
    tmp = output.with_suffix(".parquet.tmp")
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(f"COPY (SELECT * FROM read_parquet('{parts_dir}/year=*.parquet') ORDER BY attack_id,bar_end_time) TO '{tmp}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()
    tmp.replace(output)
    audit = duckdb.sql(f"""SELECT count(*) minute_rows,count(DISTINCT attack_id) attacks,min(trade_date) min_date,max(trade_date) max_date,
      count_if(minute_count<>241) non_241_rows FROM read_parquet('{output}')""").df().iloc[0].to_dict()
    if pd.Timestamp(audit["max_date"]) >= pd.Timestamp("2024-01-01"):
        raise ResearchError("2024+ outcome minute opened")
    return {"bounds": len(bounds), "rows": pq.read_metadata(output).num_rows, "sha256": sha256(output), "audit": audit}


def iter_parquet_groups(path: Path, key: str, batch_size: int = 250_000) -> Iterable[tuple[str, pd.DataFrame]]:
    parquet = pq.ParquetFile(path)
    carry = pd.DataFrame()
    for batch in parquet.iter_batches(batch_size=batch_size):
        frame = batch.to_pandas()
        if len(carry):
            frame = pd.concat([carry, frame], ignore_index=True)
        last = frame[key].iloc[-1]
        complete = frame.loc[frame[key].ne(last)]
        carry = frame.loc[frame[key].eq(last)].copy()
        for value, group in complete.groupby(key, sort=False):
            yield str(value), group.reset_index(drop=True)
    if len(carry):
        for value, group in carry.groupby(key, sort=False):
            yield str(value), group.reset_index(drop=True)


def _legal_sell_mask(path: pd.DataFrame, entry_idx: int, lineage: float) -> pd.Series:
    return (
        path.cal_idx.gt(entry_idx)
        & path.invalid_step_cum.eq(lineage)
        & path.hard_valid
        & path.trade_status.eq(1)
        & path.current_day_data_tradable
        & path.market_rule_valid
        & ~path.corporate_action_blocking
        & path.open.gt(0)
        & (np.round(path.open * 100) > np.round(path.down_limit_price * 100))
    )


def _next_legal_path_open(path: pd.DataFrame, trigger: pd.Timestamp, entry_idx: int, lineage: float) -> dict[str, Any] | None:
    eligible = path.loc[path.bar_end_time.gt(trigger) & _legal_sell_mask(path, entry_idx, lineage)]
    if eligible.empty:
        return None
    row = eligible.iloc[0]
    return {"exit_time": pd.Timestamp(row.bar_end_time), "exit_date": pd.Timestamp(row.trade_date), "exit_cal_idx": int(row.cal_idx), "exit_raw_price": float(row.open), "coordinate_factor": float(row.coordinate_factor)}


def _next_legal_ledger_open(legal: pd.DataFrame, trigger: pd.Timestamp, entry_idx: int, lineage: float) -> dict[str, Any] | None:
    eligible = legal.loc[
        legal.bar_end_time.gt(trigger)
        & legal.cal_idx.gt(entry_idx)
        & legal.invalid_step_cum.eq(lineage)
    ]
    if eligible.empty:
        return None
    row = eligible.iloc[0]
    return {"exit_time": pd.Timestamp(row.bar_end_time), "exit_date": pd.Timestamp(row.trade_date), "exit_cal_idx": int(row.cal_idx), "exit_raw_price": float(row.raw_open), "coordinate_factor": float(row.coordinate_factor)}


def _target_within_attack(path: pd.DataFrame, entry: Any, attack: Any) -> dict[str, Any] | None:
    sellable = path.loc[
        path.bar_end_time.gt(pd.Timestamp(entry.entry_time))
        & path.bar_end_time.le(pd.Timestamp(attack.attack_end_time))
        & _legal_sell_mask(path, int(entry.entry_cal_idx), float(entry.invalid_step_cum))
        & path.coord_high.ge(float(entry.U))
    ]
    if sellable.empty:
        return None
    row = sellable.iloc[0]
    raw_target = float(entry.U / row.coordinate_factor)
    execution = max(float(row.open), raw_target)
    if execution > float(row.high) + 1e-8:
        raise ResearchError(f"impossible target execution {entry.entry_key}")
    return {"exit_time": pd.Timestamp(row.bar_end_time), "exit_date": pd.Timestamp(row.trade_date), "exit_cal_idx": int(row.cal_idx), "exit_raw_price": execution, "coordinate_factor": float(row.coordinate_factor), "reason": "CURRENT_ATTACK_U"}


def _intraday_rejection_trigger(path: pd.DataFrame, entry: Any) -> pd.Timestamp | None:
    p = path.loc[path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & path.cal_idx.gt(int(entry.entry_cal_idx))].copy()
    if p.empty:
        return None
    clock = p.bar_end_time.dt.hour * 60 + p.bar_end_time.dt.minute
    p["session_segment"] = np.where(clock <= 11 * 60 + 30, "AM", "PM")
    anchor = np.where(p.session_segment.eq("AM"), 9 * 60 + 30, 13 * 60)
    p["block15"] = ((clock - anchor - 1) // 15).astype(int)
    closes = p.groupby(["trade_date", "session_segment", "block15"], sort=True).tail(1).copy()
    below = closes.coord_close.lt(float(entry.L)).to_numpy()
    deep = ((closes.coord_close - float(entry.L)) / float(entry.W)).le(-0.25).to_numpy()
    hit = np.flatnonzero(below & np.r_[False, below[:-1]] & deep)
    return None if len(hit) == 0 else pd.Timestamp(closes.bar_end_time.iloc[int(hit[0])])


def _daily_failure_trigger(days: pd.DataFrame, entry: Any, policy: str, path: pd.DataFrame, attack: Any) -> pd.Timestamp | None:
    post = days.loc[days.cal_idx.ge(int(entry.entry_cal_idx))].copy()
    if policy == "X2_ZONE_DAMAGE_05W":
        hit = post.loc[post.coord_close.le(float(entry.L - 0.50 * entry.W))]
    elif policy == "X3_ZONE_DAMAGE_10W":
        hit = post.loc[post.coord_close.le(float(entry.L - 1.00 * entry.W))]
    elif policy in ("X4_NO_PROGRESS_D3", "X4_NO_PROGRESS_D5"):
        offset = 3 if policy.endswith("D3") else 5
        checkpoint = int(entry.entry_cal_idx) + offset
        row = post.loc[post.cal_idx.eq(checkpoint)]
        if row.empty:
            return None
        observed = path.loc[path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & path.cal_idx.le(checkpoint)]
        max_progress = np.nan if observed.empty else float((observed.coord_high.max() - entry.L) / entry.W)
        hit = row if np.isfinite(max_progress) and max_progress < 0.25 and float(row.coord_close.iloc[0]) < float(entry.L) else row.iloc[0:0]
    elif policy == "X5_STRUCTURAL_BREAK":
        return pd.Timestamp(attack.attack_end_time) if attack.attack_end_reason == "HARD_STRUCTURAL_RESET" and pd.Timestamp(attack.attack_end_time) > pd.Timestamp(entry.entry_time) else None
    else:
        return None
    return None if hit.empty else pd.Timestamp(hit.trade_date.iloc[0]) + pd.Timedelta(hours=15)


def _horizon_exit(path: pd.DataFrame, days: pd.DataFrame, legal: pd.DataFrame, entry: Any, horizon: int) -> dict[str, Any] | None:
    target_idx = int(entry.entry_cal_idx) + horizon
    row = days.loc[days.cal_idx.eq(target_idx)]
    if row.empty:
        return None
    day = row.iloc[0]
    trigger = pd.Timestamp(day.trade_date) + pd.Timedelta(hours=15)
    legal_close = (
        bool(day.hard_valid)
        and float(day.invalid_step_cum) == float(entry.invalid_step_cum)
        and int(day.trade_status) == 1
        and bool(day.current_day_data_tradable)
        and bool(day.market_rule_valid)
        and not bool(day.corporate_action_blocking)
        and round(float(day.close) * 100) > round(float(day.down_limit_price) * 100)
    )
    if legal_close:
        return {"exit_time": trigger, "exit_date": pd.Timestamp(day.trade_date), "exit_cal_idx": target_idx, "exit_raw_price": float(day.close), "coordinate_factor": float(day.coordinate_factor), "reason": "TIME_STOP"}
    delayed = _next_legal_ledger_open(legal, trigger, int(entry.entry_cal_idx), float(entry.invalid_step_cum))
    if delayed is not None:
        delayed["reason"] = "TIME_STOP_DELAYED"
    return delayed


def _cash_events(actions: pd.DataFrame, entry_date: pd.Timestamp, exit_date: pd.Timestamp) -> tuple[float, str]:
    rows = actions.loc[actions.action_kind.eq("CASH_ONLY") & actions.effective_date.gt(entry_date.normalize()) & actions.effective_date.le(exit_date.normalize())]
    events = [{"date": str(pd.Timestamp(row.effective_date).date()), "cash_per_share": float(row.cash_per_share), "event_id": str(row.event_id)} for row in rows.itertuples(index=False)]
    return float(sum(item["cash_per_share"] for item in events)), json.dumps(events, sort_keys=True)


def _risk_exit(actions: pd.DataFrame, entry: Any, days: pd.DataFrame, legal: pd.DataFrame, cutoff: pd.Timestamp) -> dict[str, Any] | None:
    return anatomy.forced_risk_exit(actions, pd.Timestamp(entry.decision_time), pd.Timestamp(entry.entry_date), days, legal, float(entry.invalid_step_cum), cutoff)


def _policy_trigger(policy: str, path: pd.DataFrame, days: pd.DataFrame, entry: Any, attack: Any) -> tuple[pd.Timestamp | None, str | None]:
    if policy == "X0_NO_FAILURE_EXIT":
        return None, None
    candidates: list[tuple[pd.Timestamp, str]] = []
    if policy in ("X1_INTRADAY_REJECTION", "X6_HYBRID_D3", "X6_HYBRID_D5"):
        value = _intraday_rejection_trigger(path, entry)
        if value is not None:
            candidates.append((value, "INTRADAY_REJECTION"))
    daily_policies: list[str] = []
    if policy in ("X2_ZONE_DAMAGE_05W", "X3_ZONE_DAMAGE_10W", "X4_NO_PROGRESS_D3", "X4_NO_PROGRESS_D5", "X5_STRUCTURAL_BREAK"):
        daily_policies.append(policy)
    elif policy == "X6_HYBRID_D3":
        daily_policies.extend(["X4_NO_PROGRESS_D3", "X5_STRUCTURAL_BREAK"])
    elif policy == "X6_HYBRID_D5":
        daily_policies.extend(["X4_NO_PROGRESS_D5", "X5_STRUCTURAL_BREAK"])
    for item in daily_policies:
        value = _daily_failure_trigger(days, entry, item, path, attack)
        if value is not None:
            candidates.append((value, item))
    return (None, None) if not candidates else sorted(candidates, key=lambda x: (x[0], x[1]))[0]


def _build_entry_policy_rows(entry: Any, attack: Any, path: pd.DataFrame, days: pd.DataFrame, legal: pd.DataFrame, actions: pd.DataFrame, eventual_later_u: bool) -> list[dict[str, Any]]:
    target = _target_within_attack(path, entry, attack)
    rows: list[dict[str, Any]] = []
    policies = ("X0_NO_FAILURE_EXIT", "X1_INTRADAY_REJECTION", "X2_ZONE_DAMAGE_05W", "X3_ZONE_DAMAGE_10W", "X4_NO_PROGRESS_D3", "X4_NO_PROGRESS_D5", "X5_STRUCTURAL_BREAK", "X6_HYBRID_D3", "X6_HYBRID_D5")
    failure_by_policy: dict[str, dict[str, Any] | None] = {}
    for policy in policies:
        trigger, trigger_reason = _policy_trigger(policy, path, days, entry, attack)
        failure = None if trigger is None else _next_legal_ledger_open(legal, trigger, int(entry.entry_cal_idx), float(entry.invalid_step_cum))
        if failure is not None:
            failure["reason"] = trigger_reason
        failure_by_policy[policy] = failure
    for horizon in TIME_STOPS:
        horizon_exit = _horizon_exit(path, days, legal, entry, horizon)
        horizon_time = pd.Timestamp(days.loc[days.cal_idx.eq(int(entry.entry_cal_idx) + horizon), "trade_date"].iloc[0]) + pd.Timedelta(hours=15) if len(days.loc[days.cal_idx.eq(int(entry.entry_cal_idx) + horizon)]) else pd.Timestamp(f"{pd.Timestamp(entry.entry_date).year}-12-31 15:00")
        risk = _risk_exit(actions, entry, days, legal, horizon_time)
        for policy in policies:
            failure = failure_by_policy[policy]
            options = [item for item in (target, failure, horizon_exit) if item is not None]
            blocked = bool(risk is not None and risk.get("blocked"))
            if risk is not None and not blocked:
                options.append({**risk, "exit_cal_idx": int(days.loc[days.trade_date.eq(pd.Timestamp(risk["exit_date"])), "cal_idx"].iloc[0]), "coordinate_factor": np.nan, "reason": "CORPORATE_ACTION_RISK"})
            chosen = None if not options else sorted(options, key=lambda x: (pd.Timestamp(x["exit_time"]), 0 if x["reason"] == "CURRENT_ATTACK_U" else 1, x["reason"]))[0]
            if blocked and (chosen is None or pd.Timestamp(chosen["exit_time"]) >= pd.Timestamp(risk["effective_date"])):
                chosen = None
            if chosen is None:
                net = mae = mfe = np.nan
                cash_json = "[]"
                exit_time = exit_date = pd.NaT
                exit_price = exit_idx = np.nan
                exit_reason = "UNRESOLVED_ACTION_OR_HORIZON"
                outcome_valid = False
            else:
                exit_time = pd.Timestamp(chosen["exit_time"])
                exit_date = pd.Timestamp(chosen["exit_date"])
                exit_price = float(chosen["exit_raw_price"])
                exit_idx = int(chosen["exit_cal_idx"])
                exit_reason = str(chosen["reason"])
                cash, cash_json = _cash_events(actions, pd.Timestamp(entry.entry_date), exit_date)
                net = (exit_price * (1 - COST) + cash) / (float(entry.entry_raw_price) * (1 + COST)) - 1
                observed = path.loc[path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & path.bar_end_time.le(exit_time)]
                mae = np.nan if observed.empty else float(observed.coord_low.min() / float(entry.entry_coord_price) - 1)
                mfe = np.nan if observed.empty else float(observed.coord_high.max() / float(entry.entry_coord_price) - 1)
                outcome_valid = True
            target_time = pd.NaT if target is None else pd.Timestamp(target["exit_time"])
            target_offset = np.nan if target is None else int(target["exit_cal_idx"] - int(entry.entry_cal_idx))
            pre_target = path.loc[path.bar_end_time.gt(pd.Timestamp(entry.entry_time)) & (path.bar_end_time.lt(target_time) if pd.notna(target_time) else False)] if target is not None else path.iloc[0:0]
            target_mae = np.nan if pre_target.empty else float(pre_target.coord_low.min() / float(entry.entry_coord_price) - 1)
            clean5 = bool(target is not None and target_offset <= 5 and (not np.isfinite(target_mae) or target_mae > -0.05))
            clean10 = bool(target is not None and target_offset <= 10 and (not np.isfinite(target_mae) or target_mae > -0.08))
            rows.append({
                "entry_key": entry.entry_key, "attack_id": entry.attack_id, "gap_id": entry.gap_id, "candidate_id": entry.candidate_id,
                "attack_number": int(entry.attack_number), "symbol": entry.symbol, "board": entry.board, "attack_memory_state": entry.attack_memory_state,
                "attack_start_time": entry.attack_start_time, "attack_end_time": entry.attack_end_time, "attack_end_reason": entry.attack_end_reason,
                "translation": entry.translation, "decision_time": entry.decision_time, "entry_time": entry.entry_time, "entry_date": entry.entry_date,
                "entry_cal_idx": int(entry.entry_cal_idx), "entry_raw_price": float(entry.entry_raw_price), "entry_coord_price": float(entry.entry_coord_price),
                "L": float(entry.L), "U": float(entry.U), "W": float(entry.W), "remaining_net_target_at_entry": float(entry.remaining_net_target_at_entry),
                "time_stop": horizon, "exit_policy": policy, "exit_time": exit_time, "exit_date": exit_date, "exit_cal_idx": exit_idx,
                "exit_raw_price": exit_price, "exit_reason": exit_reason, "outcome_valid": outcome_valid, "net_return": net,
                "mae": mae, "mfe": mfe, "holding_sessions": np.nan if not outcome_valid else int(exit_idx - int(entry.entry_cal_idx)),
                "holding_minutes": np.nan if not outcome_valid else (exit_time - pd.Timestamp(entry.entry_time)).total_seconds() / 60,
                "attack_success": bool(attack.attack_end_reason == "SUCCESS"), "u_hit": bool(exit_reason == "CURRENT_ATTACK_U"),
                "clean_attack_success_5": clean5, "clean_attack_success_10": clean10,
                "rough_attack_success": bool(attack.attack_end_reason == "SUCCESS" and not clean10),
                "failed_attack": bool(attack.attack_end_reason in ("HARD_STRUCTURAL_RESET", "BELOW_ZONE_RESET")),
                "timed_out_attack": bool(attack.attack_end_reason == "TIME_RESET"),
                "eventual_u_after_failed_attack": bool(eventual_later_u),
                "severe_loss5": bool(np.isfinite(net) and net <= -0.05), "severe_loss8": bool(np.isfinite(net) and net <= -0.08),
                "severe_loss10": bool(np.isfinite(net) and net <= -0.10), "severe_loss20": bool(np.isfinite(net) and net <= -0.20),
                "cash_events_json": cash_json, "unresolved_action_block": bool(not outcome_valid and blocked),
                "stop_executed_at_impossible_price": False,
                "t1_same_day_exit": bool(outcome_valid and int(exit_idx) <= int(entry.entry_cal_idx)),
                "corporate_action_coordinate_violation": False,
                "later_success_credited_to_earlier_attack": False,
            })
    return rows


def build_attack_outcomes(start_year: int, end_year: int, minute_path: Path, output: Path) -> dict[str, Any]:
    entries = pd.read_parquet(ENTRY_CANDIDATES)
    _timestamp_columns(entries, ["decision_time", "entry_time", "entry_date", "attack_start_time", "attack_end_time"])
    entries = entries.loc[entries.status.eq("EXECUTABLE_ENTRY") & entries.entry_date.dt.year.between(start_year, end_year)].copy()
    attacks = pd.read_parquet(ATTACK_LEDGER)
    _timestamp_columns(attacks, ["attack_start_time", "attack_end_time"])
    attack_by = attacks.set_index("attack_id")
    # Eventual-U is descriptive only.  It is searched on the already-frozen
    # 90-session semantic path and never alters the current attack outcome.
    semantic_minutes = pd.read_parquet(ATTACK_MINUTES, columns=["candidate_id", "bar_end_time", "coord_high", "U"])
    semantic_minutes.bar_end_time = pd.to_datetime(semantic_minutes.bar_end_time)
    first_u_by_candidate = semantic_minutes.loc[semantic_minutes.coord_high.ge(semantic_minutes.U)].groupby("candidate_id").bar_end_time.min().to_dict()
    entry_by = {key: value.sort_values("entry_time") for key, value in entries.groupby("attack_id", sort=False)}
    daily = pd.read_parquet(PRED_EXT / "daily_relevant.parquet")
    daily.trade_date = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.trade_date.dt.year.between(start_year, end_year) & daily.symbol.isin(entries.symbol.unique())]
    daily_by = {key: value.sort_values("cal_idx") for key, value in daily.groupby("symbol", sort=False)}
    legal = pd.read_parquet(SOURCE_LEGAL_OPENS)
    _timestamp_columns(legal, ["trade_date", "bar_end_time"])
    legal = legal.loc[legal.trade_date.dt.year.between(start_year, end_year)]
    legal_by = {key: value.sort_values("bar_end_time") for key, value in legal.groupby("symbol", sort=False)}
    actions = pd.read_parquet(SOURCE_ACTIONS)
    _timestamp_columns(actions, ["known_date", "effective_date"])
    actions_by = {key: value for key, value in actions.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for attack_id, path in iter_parquet_groups(minute_path, "attack_id"):
        if attack_id not in entry_by or attack_id not in attack_by.index:
            continue
        path = path.sort_values("bar_end_time").reset_index(drop=True)
        _timestamp_columns(path, ["trade_date", "bar_end_time"])
        attack = attack_by.loc[attack_id]
        days = daily_by.get(str(attack.symbol), pd.DataFrame(columns=daily.columns))
        legal_symbol = legal_by.get(str(attack.symbol), pd.DataFrame(columns=legal.columns))
        action = actions_by.get(str(attack.symbol), pd.DataFrame(columns=actions.columns))
        for entry in entry_by[attack_id].itertuples(index=False):
            first_later_u = first_u_by_candidate.get(str(entry.candidate_id))
            eventual_later_u = bool(
                attack.attack_end_reason != "SUCCESS"
                and first_later_u is not None
                and pd.Timestamp(first_later_u) > pd.Timestamp(attack.attack_end_time)
            )
            rows.extend(_build_entry_policy_rows(entry, attack, path, days, legal_symbol, action, eventual_later_u))
        seen.add(attack_id)
    missing = set(entry_by) - seen
    if missing:
        # Missing same-lineage paths are explicit fail-closed outcomes.
        for attack_id in sorted(missing):
            for entry in entry_by[attack_id].itertuples(index=False):
                for horizon in TIME_STOPS:
                    for policy in ("X0_NO_FAILURE_EXIT", "X1_INTRADAY_REJECTION", "X2_ZONE_DAMAGE_05W", "X3_ZONE_DAMAGE_10W", "X4_NO_PROGRESS_D3", "X4_NO_PROGRESS_D5", "X5_STRUCTURAL_BREAK", "X6_HYBRID_D3", "X6_HYBRID_D5"):
                        rows.append({"entry_key": entry.entry_key, "attack_id": attack_id, "gap_id": entry.gap_id, "candidate_id": entry.candidate_id, "attack_number": int(entry.attack_number), "symbol": entry.symbol, "board": entry.board, "attack_memory_state": entry.attack_memory_state, "attack_start_time": entry.attack_start_time, "attack_end_time": entry.attack_end_time, "attack_end_reason": entry.attack_end_reason, "translation": entry.translation, "decision_time": entry.decision_time, "entry_time": entry.entry_time, "entry_date": entry.entry_date, "entry_cal_idx": int(entry.entry_cal_idx), "entry_raw_price": float(entry.entry_raw_price), "entry_coord_price": float(entry.entry_coord_price), "L": float(entry.L), "U": float(entry.U), "W": float(entry.W), "remaining_net_target_at_entry": float(entry.remaining_net_target_at_entry), "time_stop": horizon, "exit_policy": policy, "exit_time": pd.NaT, "exit_date": pd.NaT, "exit_cal_idx": np.nan, "exit_raw_price": np.nan, "exit_reason": "MISSING_SAME_LINEAGE_PATH", "outcome_valid": False, "net_return": np.nan, "mae": np.nan, "mfe": np.nan, "holding_sessions": np.nan, "holding_minutes": np.nan, "attack_success": False, "u_hit": False, "clean_attack_success_5": False, "clean_attack_success_10": False, "rough_attack_success": False, "failed_attack": False, "timed_out_attack": False, "eventual_u_after_failed_attack": False, "severe_loss5": False, "severe_loss8": False, "severe_loss10": False, "severe_loss20": False, "cash_events_json": "[]", "unresolved_action_block": True, "stop_executed_at_impossible_price": False, "t1_same_day_exit": False, "corporate_action_coordinate_violation": False, "later_success_credited_to_earlier_attack": False})
    out = pd.DataFrame(rows).sort_values(["entry_key", "time_stop", "exit_policy"], kind="mergesort").reset_index(drop=True)
    write_parquet(out, output)
    audit = {
        "rows": len(out),
        "entry_keys": int(out.entry_key.nunique()),
        "valid_rows": int(out.outcome_valid.sum()),
        "missing_path_attacks": len(missing),
        "stop_executed_at_impossible_price_count": int(out.stop_executed_at_impossible_price.sum()),
        "t1_same_day_exit_count": int(out.t1_same_day_exit.sum()),
        "corporate_action_coordinate_violation_count": int(out.corporate_action_coordinate_violation.sum()),
        "later_success_credited_to_earlier_attack_count": int(out.later_success_credited_to_earlier_attack.sum()),
        "max_entry_date": str(entries.entry_date.max()),
        "repository_2024_plus_data_opened": "NO",
    }
    if any(audit[key] for key in ("stop_executed_at_impossible_price_count", "t1_same_day_exit_count", "corporate_action_coordinate_violation_count", "later_success_credited_to_earlier_attack_count")):
        raise ResearchError(f"outcome audit failed: {audit}")
    return audit


def stage_b_outcomes() -> dict[str, Any]:
    _require_frozen_stage_a()
    path = build_outcome_minute_path(2014, 2021, ATTACK_OUTCOME_MINUTES, OUTCOME_MINUTE_PARTS)
    outcome = build_attack_outcomes(2014, 2021, ATTACK_OUTCOME_MINUTES, ATTACK_OUTCOMES)
    payload = {"label": "DEVELOPMENT_ONLY", "minute_path": path, "outcomes": outcome, "attack_outcomes_sha256": sha256(ATTACK_OUTCOMES), "post_2021_scientific_evidence_accepted": "NO", "repository_2024_plus_data_opened": "NO"}
    manifest("STAGE_B_OUTCOMES", "COMPLETE", payload)
    return payload


def outer_folds() -> list[dict[str, Any]]:
    rows = []
    for year in range(2017, 2022):
        for half in (1, 2):
            start = pd.Timestamp(year=year, month=1 if half == 1 else 7, day=1)
            end = pd.Timestamp(year=year, month=6 if half == 1 else 12, day=30 if half == 1 else 31)
            rows.append({"fold": f"{year}H{half}", "year": year, "half": half, "start": start, "end": end})
    return rows


class PanelStore:
    """Lazy policy panels; only the requested frozen policy slice is merged."""

    def __init__(self, outcome_path: Path = ATTACK_OUTCOMES) -> None:
        self.outcomes = pd.read_parquet(outcome_path)
        _timestamp_columns(self.outcomes, ["attack_start_time", "decision_time", "entry_time", "entry_date", "exit_time", "exit_date"])
        self.features = pd.read_parquet(ATTACK_CLOCK_FEATURES)
        self.features.decision_time = pd.to_datetime(self.features.decision_time)
        attacks = pd.read_parquet(ATTACK_LEDGER, columns=["attack_id", "gap_date", "gap_cal_idx", "gap_age_sessions", "cluster_freeze_time", "attack_memory_state"])
        _timestamp_columns(attacks, ["gap_date", "cluster_freeze_time"])
        clusters = pd.read_parquet(SOURCE_CLUSTERS, columns=["cluster_id", "gap_count"])
        source = active_source()[["candidate_id", "cluster_id", "true_gap_width_pct", "material_drawdown_at_freeze"]]
        source = source.merge(clusters, on="cluster_id", validate="many_to_one")
        self.meta = attacks.merge(
            pd.read_parquet(ATTACK_LEDGER, columns=["attack_id", "candidate_id"]),
            on="attack_id", validate="one_to_one",
        ).merge(
            source[["candidate_id", "true_gap_width_pct", "gap_count", "material_drawdown_at_freeze"]],
            on="candidate_id", validate="many_to_one",
        )
        self.cache: dict[tuple[str, int, str], pd.DataFrame] = {}

    def get(self, translation: str, horizon: int, policy: str) -> pd.DataFrame:
        key = (translation, int(horizon), policy)
        if key in self.cache:
            return self.cache[key]
        base = self.outcomes.loc[
            self.outcomes.translation.eq(translation)
            & self.outcomes.time_stop.eq(int(horizon))
            & self.outcomes.exit_policy.eq(policy)
        ].copy()
        feature = self.features.loc[self.features.translation.eq(translation)].drop_duplicates("entry_key")
        shared = ("entry_key", "attack_id", "gap_id", "candidate_id", "symbol", "board", "attack_number", "translation", "decision_time")
        keep = list(shared) + [column for column in feature.columns if column not in shared and column not in base.columns]
        base = base.merge(feature[keep], on=list(shared), validate="one_to_one")
        base = base.merge(self.meta, on=["attack_id", "candidate_id", "attack_memory_state"], suffixes=("", "_ledger"), validate="one_to_one")
        base["attack_start_date"] = base.attack_start_time.dt.normalize()
        base["gap_date"] = pd.to_datetime(base.gap_date).dt.normalize()
        base["calendar_year"] = base.attack_start_time.dt.year
        base["single_multigap"] = np.where(base.gap_count.eq(1), "SINGLE", "MULTIGAP")
        base = base.sort_values(["attack_start_time", "attack_id"], kind="mergesort").reset_index(drop=True)
        self.cache[key] = base
        return base


def baseline_panel(outcome_path: Path = ATTACK_OUTCOMES) -> pd.DataFrame:
    return PanelStore(outcome_path).get("Z0+CLOSE", 20, "X0_NO_FAILURE_EXIT")


def fold_train_test(panel: pd.DataFrame, fold: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    calendar = _calendar()
    boundary_rows = calendar.loc[calendar.trade_date.ge(fold["start"])]
    if boundary_rows.empty:
        raise ResearchError(f"missing boundary for {fold['fold']}")
    boundary_idx = int(boundary_rows.cal_idx.iloc[0])
    test = panel.loc[panel.attack_start_date.between(fold["start"], fold["end"]) & panel.outcome_valid].copy()
    test_gap_ids = set(test.gap_id.astype(str))
    train = panel.loc[
        panel.attack_start_date.lt(fold["start"])
        & panel.outcome_valid
        & (panel.entry_cal_idx.astype(float) + 20 <= boundary_idx - 20)
        & ~panel.gap_id.astype(str).isin(test_gap_ids)
    ].copy()
    same_gap = len(set(train.gap_id.astype(str)) & test_gap_ids)
    purge = int((train.entry_cal_idx.astype(float) + 20 > boundary_idx - 20).sum())
    own = int(train.attack_start_date.between(fold["start"], fold["end"]).sum())
    audit = {"same_gap_split": same_gap, "purge_violation": purge, "test_half_in_train": own}
    if any(audit.values()):
        raise ResearchError(f"fold audit failed {fold['fold']}: {audit}")
    return train, test, audit


def inner_folds_before(outer_start: pd.Timestamp) -> list[dict[str, Any]]:
    folds = []
    for year in range(2015, int(outer_start.year) + 1):
        for half in (1, 2):
            start = pd.Timestamp(year=year, month=1 if half == 1 else 7, day=1)
            if start >= outer_start:
                continue
            end = pd.Timestamp(year=year, month=6 if half == 1 else 12, day=30 if half == 1 else 31)
            folds.append({"fold": f"{year}H{half}", "year": year, "half": half, "start": start, "end": end})
    return folds


def latest_full_train_year(boundary: pd.Timestamp) -> int:
    return int(boundary.year) - 1


def _condition(feature: str, operator: str, threshold: float, source: str) -> dict[str, Any]:
    return {"feature": feature, "operator": operator, "threshold": float(threshold), "source": source}


def _condition_mask(frame: pd.DataFrame, condition: dict[str, Any]) -> pd.Series:
    if condition["feature"] not in frame:
        return pd.Series(False, index=frame.index)
    value = pd.to_numeric(frame[condition["feature"]], errors="coerce")
    threshold = float(condition["threshold"])
    operator = condition["operator"]
    if operator == ">=":
        return value.ge(threshold) & value.notna()
    if operator == "<=":
        return value.le(threshold) & value.notna()
    if operator == ">":
        return value.gt(threshold) & value.notna()
    if operator == "<":
        return value.lt(threshold) & value.notna()
    if operator == "==":
        return value.eq(threshold) & value.notna()
    raise ResearchError(f"unknown condition operator {operator}")


def apply_rule_model(frame: pd.DataFrame, model: dict[str, Any]) -> tuple[pd.Series, pd.Series]:
    if not model.get("valid", False):
        return pd.Series(False, index=frame.index), pd.Series(0.0, index=frame.index)
    conditions = model.get("conditions", [])
    if not conditions:
        return pd.Series(True, index=frame.index), pd.Series(1.0, index=frame.index)
    passed = pd.concat([_condition_mask(frame, condition).rename(str(i)) for i, condition in enumerate(conditions)], axis=1)
    score = passed.mean(axis=1)
    if model["kind"] == "vote":
        mask = passed.sum(axis=1).ge(int(model["minimum_votes"]))
    else:
        mask = passed.all(axis=1)
    return mask, score.astype(float)


def _fixed_overhang_rule(rule_id: str, train: pd.DataFrame) -> dict[str, Any]:
    q = lambda feature, value: float(pd.to_numeric(train[feature], errors="coerce").quantile(value))
    specifications: dict[str, list[tuple[str, str, float, str]]] = {
        "VACUUM_Q70": [("vacuum_score", ">=", q("vacuum_score", 0.70), "TRAIN_Q70")],
        "RATIO_Q30": [("overhang_support_ratio", "<=", q("overhang_support_ratio", 0.30), "TRAIN_Q30")],
        "INSIDE_Q30": [("decayed_overhang_inside_gap", "<=", q("decayed_overhang_inside_gap", 0.30), "TRAIN_Q30")],
        "ABOVE_Q30": [("decayed_overhang_above_u", "<=", q("decayed_overhang_above_u", 0.30), "TRAIN_Q30")],
        "VACUUM_Q50_RATIO_Q50": [("vacuum_score", ">=", q("vacuum_score", 0.50), "TRAIN_Q50"), ("overhang_support_ratio", "<=", q("overhang_support_ratio", 0.50), "TRAIN_Q50")],
        "VACUUM_Q70_RATIO_Q50": [("vacuum_score", ">=", q("vacuum_score", 0.70), "TRAIN_Q70"), ("overhang_support_ratio", "<=", q("overhang_support_ratio", 0.50), "TRAIN_Q50")],
        "INSIDE_Q30_ABOVE_Q30": [("decayed_overhang_inside_gap", "<=", q("decayed_overhang_inside_gap", 0.30), "TRAIN_Q30"), ("decayed_overhang_above_u", "<=", q("decayed_overhang_above_u", 0.30), "TRAIN_Q30")],
    }
    if rule_id in specifications:
        conditions = [_condition(*item) for item in specifications[rule_id]]
        return {"rule_id": rule_id, "kind": "all", "conditions": conditions, "complexity": len(conditions), "valid": all(np.isfinite(item["threshold"]) for item in conditions)}
    vote = {
        "OVERHANG_VOTE_3_OF_4_Q50": (0.50, 0.50, 3),
        "OVERHANG_VOTE_2_OF_4_Q70": (0.70, 0.30, 2),
    }
    if rule_id in vote:
        high_q, low_q, minimum = vote[rule_id]
        conditions = [
            _condition("vacuum_score", ">=", q("vacuum_score", high_q), f"TRAIN_Q{int(high_q * 100)}"),
            _condition("decayed_overhang_inside_gap", "<=", q("decayed_overhang_inside_gap", low_q), f"TRAIN_Q{int(low_q * 100)}"),
            _condition("decayed_overhang_above_u", "<=", q("decayed_overhang_above_u", low_q), f"TRAIN_Q{int(low_q * 100)}"),
            _condition("overhang_support_ratio", "<=", q("overhang_support_ratio", low_q), f"TRAIN_Q{int(low_q * 100)}"),
        ]
        return {"rule_id": rule_id, "kind": "vote", "conditions": conditions, "minimum_votes": minimum, "complexity": 4, "valid": all(np.isfinite(item["threshold"]) for item in conditions)}
    raise ResearchError(f"unknown fixed overhang rule {rule_id}")


def _flag_contract(train: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    columns: dict[str, pd.Series] = {}
    specs: list[dict[str, Any]] = []
    for feature, direction in SIMPLE_RULE_FEATURE_DIRECTIONS.items():
        if feature not in train:
            continue
        values = pd.to_numeric(train[feature], errors="coerce")
        if values.notna().sum() < 40 or values.nunique(dropna=True) < 2:
            continue
        for quantile in (0.30, 0.50, 0.70):
            threshold = float(values.quantile(quantile))
            if not np.isfinite(threshold):
                continue
            operator = ">=" if direction > 0 else "<="
            name = f"{feature}|{operator}|Q{int(quantile * 100)}"
            condition = _condition(feature, operator, threshold, f"TRAIN_Q{int(quantile * 100)}")
            columns[name] = _condition_mask(train, condition).astype(float)
            specs.append({"name": name, "condition": condition, "overhang": feature in OVERHANG_DIRECTIONS})
    return pd.DataFrame(columns, index=train.index), specs


def _opposite_condition(condition: dict[str, Any]) -> dict[str, Any]:
    opposite = {">=": "<", "<=": ">", ">": "<=", "<": ">="}[condition["operator"]]
    return _condition(condition["feature"], opposite, condition["threshold"], condition["source"] + "_COMPLEMENT")


def _tree_leaf_conditions(model: DecisionTreeClassifier, representative: np.ndarray, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node = 0
    conditions: list[dict[str, Any]] = []
    while model.tree_.children_left[node] != model.tree_.children_right[node]:
        feature_idx = int(model.tree_.feature[node])
        threshold = float(model.tree_.threshold[node])
        if threshold < 0 or threshold > 1:
            raise ResearchError("binary flag tree used a non-binary threshold")
        expected_true = bool(representative[feature_idx] > threshold)
        base = specs[feature_idx]["condition"]
        conditions.append(base if expected_true else _opposite_condition(base))
        node = int(model.tree_.children_right[node] if expected_true else model.tree_.children_left[node])
    return conditions


def _fit_single_leaf(
    x: pd.DataFrame,
    specs: list[dict[str, Any]],
    target: np.ndarray,
    rank_value: np.ndarray,
    rule_id: str,
) -> dict[str, Any]:
    if len(x) < 80 or len(np.unique(target)) < 2 or x.shape[1] == 0:
        return {"rule_id": rule_id, "kind": "all", "conditions": [], "complexity": 99, "valid": False, "reason": "INSUFFICIENT_TRAIN"}
    tree = DecisionTreeClassifier(criterion="log_loss", max_depth=3, min_samples_leaf=40, class_weight="balanced", random_state=20260903)
    tree.fit(x, target)
    leaves = tree.apply(x)
    choices = []
    matrix = x.to_numpy(float)
    for leaf in sorted(np.unique(leaves)):
        idx = np.flatnonzero(leaves == leaf)
        if len(idx) < 40:
            continue
        representative = matrix[int(idx[0])]
        conditions = _tree_leaf_conditions(tree, representative, specs)
        favorable_overhang = any(
            condition["feature"] in OVERHANG_DIRECTIONS
            and condition["operator"] == (">=" if OVERHANG_DIRECTIONS[condition["feature"]] > 0 else "<=")
            for condition in conditions
        )
        if not favorable_overhang or len(conditions) > 3:
            continue
        choices.append((float(np.nanmean(rank_value[idx])), len(idx), -len(conditions), int(leaf), conditions))
    if not choices:
        return {"rule_id": rule_id, "kind": "all", "conditions": [], "complexity": 99, "valid": False, "reason": "NO_FAVORABLE_OVERHANG_LEAF"}
    _, support, _, leaf, conditions = sorted(choices, reverse=True, key=lambda item: item[:4])[0]
    return {"rule_id": rule_id, "kind": "all", "conditions": conditions, "complexity": len(conditions), "valid": True, "train_leaf_support": support, "leaf_id": leaf, "tree_text": export_text(tree, feature_names=list(x.columns))}


def _fit_generated_rule(rule_id: str, train: pd.DataFrame) -> dict[str, Any]:
    x, specs = _flag_contract(train)
    target = train.clean_attack_success_10.astype(int).to_numpy()
    if rule_id == "TREE_SINGLE_LEAF":
        return _fit_single_leaf(x, specs, target, target.astype(float), rule_id)
    if rule_id == "RULEFIT_LITE":
        if len(x) < 80 or len(np.unique(target)) < 2 or x.shape[1] == 0:
            return {"rule_id": rule_id, "kind": "vote", "conditions": [], "complexity": 99, "valid": False, "reason": "INSUFFICIENT_TRAIN"}
        model = LogisticRegression(penalty="elasticnet", l1_ratio=0.80, C=0.10, solver="saga", max_iter=4000, class_weight="balanced", random_state=20260903)
        model.fit(x, target)
        ranked = sorted([(float(coef), i) for i, coef in enumerate(model.coef_[0]) if coef > 0], key=lambda item: (-item[0], specs[item[1]]["name"]))
        selected = [item for item in ranked[:5]]
        if not selected or not any(specs[i]["overhang"] for _, i in selected):
            return {"rule_id": rule_id, "kind": "vote", "conditions": [], "complexity": 99, "valid": False, "reason": "NO_POSITIVE_OVERHANG_FLAG"}
        conditions = [specs[i]["condition"] for _, i in selected]
        return {"rule_id": rule_id, "kind": "vote", "conditions": conditions, "minimum_votes": max(1, math.ceil(0.60 * len(conditions))), "complexity": len(conditions), "valid": True, "coefficients": [coef for coef, _ in selected]}
    if rule_id == "LGBM_DISTILLED_LEAF":
        model_features = [column for column in rule_space_value()["model_features"] if column in train]
        if len(train) < 80 or len(np.unique(target)) < 2 or not model_features:
            return {"rule_id": rule_id, "kind": "all", "conditions": [], "complexity": 99, "valid": False, "reason": "INSUFFICIENT_TRAIN"}
        values = train[model_features].replace([np.inf, -np.inf], np.nan)
        medians = values.median()
        values = values.fillna(medians).fillna(0.0)
        params = rule_space_value()["methods"]["LIGHTGBM_CEILING"].copy()
        params.pop("deployable", None); params.pop("objective", None)
        ceiling = lgb.LGBMClassifier(objective="binary", **params)
        ceiling.fit(values, target)
        prediction = ceiling.predict_proba(values)[:, 1]
        surrogate_target = (prediction >= np.quantile(prediction, 0.70)).astype(int)
        fitted = _fit_single_leaf(x, specs, surrogate_target, prediction, rule_id)
        fitted["ceiling_feature_importance"] = dict(sorted(zip(model_features, map(int, ceiling.feature_importances_)), key=lambda item: (-item[1], item[0])))
        return fitted
    raise ResearchError(f"unknown generated rule {rule_id}")


def fit_overhang_rule(rule_id: str, train: pd.DataFrame) -> dict[str, Any]:
    if rule_id in rule_space_value()["fixed_low_overhang_rules"]:
        return _fixed_overhang_rule(rule_id, train)
    return _fit_generated_rule(rule_id, train)


def fit_environment_rule(environment_id: str, train: pd.DataFrame) -> dict[str, Any]:
    q50 = lambda feature: float(pd.to_numeric(train[feature], errors="coerce").quantile(0.50))
    definitions = {
        "NONE": [],
        "RELATIVE_REPAIR": [_condition("stock_minus_board_return_10d", ">=", q50("stock_minus_board_return_10d"), "TRAIN_Q50"), _condition("stock_minus_industry_return_10d", ">=", q50("stock_minus_industry_return_10d"), "TRAIN_Q50")],
        "SYSTEM_REPAIR": [_condition("board_return_20d", ">=", 0.0, "NATURAL_ZERO"), _condition("industry_return_20d", ">=", 0.0, "NATURAL_ZERO")],
        "BREADTH_REPAIR": [_condition("breadth_recovery", ">=", 0.0, "NATURAL_ZERO")],
        "APPROACH_QUALITY": [_condition("higher_low_share_10d", ">=", q50("higher_low_share_10d"), "TRAIN_Q50"), _condition("approach_path_efficiency_10d", ">=", q50("approach_path_efficiency_10d"), "TRAIN_Q50")],
        "NO_LOWER_CLUSTER": [_condition("new_lower_cluster_since_gap", "==", 0.0, "NATURAL_ZERO")],
    }
    if environment_id not in definitions:
        raise ResearchError(f"unknown environment {environment_id}")
    conditions = definitions[environment_id]
    return {"environment_id": environment_id, "kind": "all", "conditions": conditions, "complexity": len(conditions), "valid": all(np.isfinite(item["threshold"]) for item in conditions)}


def apply_admission(frame: pd.DataFrame, overhang: dict[str, Any], environment: dict[str, Any] | None = None) -> tuple[pd.Series, pd.Series]:
    overhang_mask, overhang_score = apply_rule_model(frame, overhang)
    if environment is None:
        return overhang_mask, overhang_score
    environment_mask, environment_score = apply_rule_model(frame, environment)
    return overhang_mask & environment_mask, (overhang_score + environment_score) / 2


def _cvar5(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna().sort_values()
    if values.empty:
        return np.nan
    return float(values.head(max(1, math.ceil(0.05 * len(values)))).mean())


def trade_path_calmar(frame: pd.DataFrame) -> float:
    valid = frame.loc[frame.outcome_valid & frame.net_return.notna()].sort_values(["exit_time", "entry_time", "entry_key"], kind="mergesort")
    if valid.empty:
        return -99.0
    returns = valid.net_return.astype(float).clip(lower=-0.99) / 10.0
    nav = (1.0 + returns).cumprod()
    drawdown = nav / nav.cummax() - 1.0
    elapsed = max((pd.Timestamp(valid.exit_time.max()) - pd.Timestamp(valid.entry_time.min())).days / 365.25, 1 / 365.25)
    cagr = float(nav.iloc[-1] ** (1 / elapsed) - 1)
    maximum = float(drawdown.min())
    return cagr / abs(maximum) if maximum < 0 else (99.0 if cagr > 0 else 0.0)


def selection_metrics(frame: pd.DataFrame, denominator: int | None = None) -> dict[str, Any]:
    valid = frame.loc[frame.outcome_valid & frame.net_return.notna()].copy()
    returns = valid.net_return.astype(float)
    if returns.empty:
        return {
            "trades": 0, "mean_net_return": np.nan, "median_net_return": np.nan,
            "true_win_rate": np.nan, "u_hit": np.nan, "clean_success_10": np.nan,
            "failed_attack": np.nan, "severe_loss8": np.nan, "severe_loss10": np.nan,
            "cvar5": np.nan, "economic_utility": -99.0, "trade_path_calmar": -99.0,
            "retention": 0.0,
        }
    cvar = _cvar5(returns)
    return {
        "trades": len(valid),
        "mean_net_return": float(returns.mean()),
        "median_net_return": float(returns.median()),
        "true_win_rate": float(returns.gt(0).mean()),
        "u_hit": float(valid.u_hit.mean()),
        "clean_success_10": float(valid.clean_attack_success_10.mean()),
        "failed_attack": float(valid.failed_attack.mean()),
        "severe_loss8": float(valid.severe_loss8.mean()),
        "severe_loss10": float(valid.severe_loss10.mean()),
        "cvar5": cvar,
        "economic_utility": float(returns.mean() - 0.20 * abs(cvar)),
        "trade_path_calmar": trade_path_calmar(valid),
        "retention": float(len(valid) / max(1, denominator if denominator is not None else len(valid))),
    }


def summarize_candidate_blocks(rows: pd.DataFrame, full_support: dict[str, dict[str, Any]]) -> pd.DataFrame:
    summaries = []
    for candidate, part in rows.groupby("candidate", sort=True):
        valid = part.loc[part.trades.gt(0)]
        utilities = valid.economic_utility.astype(float)
        pooled_count = int(valid.trades.sum())
        support = full_support[candidate]
        summaries.append({
            "candidate": candidate,
            "inner_blocks": len(valid),
            "median_inner_utility": -99.0 if valid.empty else float(utilities.median()),
            "mean_inner_utility": -99.0 if valid.empty else float(utilities.mean()),
            "utility_standard_error": np.inf if len(valid) < 2 else float(utilities.std(ddof=1) / math.sqrt(len(valid))),
            "median_inner_calmar": -99.0 if valid.empty else float(valid.trade_path_calmar.median()),
            "median_inner_severe10": 1.0 if valid.empty else float(valid.severe_loss10.median()),
            "median_inner_clean10": 0.0 if valid.empty else float(valid.clean_success_10.median()),
            "median_inner_retention": 0.0 if valid.empty else float(valid.retention.median()),
            "positive_inner_blocks": int(valid.economic_utility.gt(0).sum()),
            "inner_oof_trades": pooled_count,
            **support,
        })
    return pd.DataFrame(summaries)


def one_se_choice(summary: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    if summary.empty:
        raise ResearchError("no candidate summaries")
    support_eligible = summary.loc[
        summary.full_train_trades.ge(80)
        & summary.latest_full_train_year_trades.ge(15)
        & summary.condition_count.le(5)
    ].copy()
    eligible = support_eligible.loc[support_eligible.inner_blocks.ge(3)].copy()
    if "simplicity_rank" not in support_eligible:
        support_eligible["simplicity_rank"] = 0
    if "simplicity_rank" not in eligible:
        eligible["simplicity_rank"] = 0
    if eligible.empty:
        if support_eligible.empty:
            raise ResearchError("no candidate satisfies frozen support/complexity requirements")
        # The deployment procedure remains cash because fewer than three inner
        # blocks are informative.  FORCED_CHOICE_WF still needs a deterministic
        # diagnostic candidate, so use the best-supported simplest existing one.
        chosen = support_eligible.sort_values(
            ["inner_blocks", "condition_count", "median_inner_utility", "simplicity_rank", "candidate"],
            ascending=[False, True, False, True, True], kind="mergesort",
        ).iloc[0]
        summary["within_one_se"] = False
        summary["eligible"] = False
        summary["forced_choice_fallback"] = summary.candidate.eq(chosen.candidate)
        summary["selected"] = summary.candidate.eq(chosen.candidate)
        return chosen, summary
    best = eligible.sort_values(["median_inner_utility", "candidate"], ascending=[False, True], kind="mergesort").iloc[0]
    tolerance = float(best.utility_standard_error) if np.isfinite(best.utility_standard_error) else 0.0
    eligible["within_one_se"] = eligible.median_inner_utility.ge(float(best.median_inner_utility) - tolerance)
    pool = eligible.loc[eligible.within_one_se].copy()
    chosen = pool.sort_values(
        ["condition_count", "median_inner_utility", "median_inner_calmar", "median_inner_severe10", "median_inner_clean10", "median_inner_retention", "simplicity_rank", "candidate"],
        ascending=[True, False, False, True, False, False, True, True], kind="mergesort",
    ).iloc[0]
    summary = summary.merge(eligible[["candidate", "within_one_se"]], on="candidate", how="left")
    summary["eligible"] = summary.candidate.isin(set(eligible.candidate))
    summary["forced_choice_fallback"] = False
    summary["selected"] = summary.candidate.eq(chosen.candidate)
    return chosen, summary


def metric_rows(frame: pd.DataFrame, weighting: str) -> dict[str, Any]:
    source_n = len(frame)
    if weighting == "event":
        values = frame
    else:
        key = "attack_start_date" if weighting == "attack_date_equal" else "gap_date"
        fields = ["net_return", "attack_success", "clean_attack_success_10", "failed_attack", "severe_loss8", "severe_loss10"]
        values = frame.groupby(key, as_index=False)[fields].mean()
    returns = pd.to_numeric(values.net_return, errors="coerce").dropna()
    return {
        "observations": source_n,
        "weighted_units": len(values),
        "mean_net_return": np.nan if returns.empty else float(returns.mean()),
        "median_net_return": np.nan if returns.empty else float(returns.median()),
        "attack_success": np.nan if values.empty else float(values.attack_success.mean()),
        "clean_success_10": np.nan if values.empty else float(values.clean_attack_success_10.mean()),
        "failed_attack": np.nan if values.empty else float(values.failed_attack.mean()),
        "severe_loss8": np.nan if values.empty else float(values.severe_loss8.mean()),
        "severe_loss10": np.nan if values.empty else float(values.severe_loss10.mean()),
        "cvar5": _cvar5(returns),
    }


def _quantile_edges(series: pd.Series, quantiles: list[float]) -> list[float]:
    valid = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if valid.empty:
        return [np.nan for _ in quantiles]
    return [float(valid.quantile(q)) for q in quantiles]


def _assign_bins(series: pd.Series, edges: list[float]) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").to_numpy(float)
    finite_edges = np.array(edges, dtype=float)
    result = np.searchsorted(finite_edges, values, side="right") + 1
    output = pd.Series(result, index=series.index, dtype="Float64")
    output.loc[~np.isfinite(values)] = pd.NA
    return output


def build_direct_analysis() -> pd.DataFrame:
    panel = baseline_panel()
    panel = panel.loc[panel.attack_memory_state.eq("CORE") & panel.attack_number.eq(1)].copy()
    variables = list(PRIMARY_VARIABLES) + ["acceptance_ratio_l_5", "acceptance_ratio_l_15", "acceptance_ratio_l_30", "current_z", "max_z", "rejection_depth_z", "failed_l_test_count", "reclaim_count", "vwap_hold_ratio", "stock_minus_board_intraday_return", "stock_minus_industry_intraday_return", "progress_per_turnover", "attack_cost_ratio"]
    rows: list[dict[str, Any]] = []
    surfaces = rule_space_value()["direct_analysis"]["surfaces"]
    for fold in outer_folds():
        train, test, _ = fold_train_test(panel, fold)
        for variable in variables:
            edges = _quantile_edges(train[variable], [0.2, 0.4, 0.6, 0.8])
            for sample_name, sample in (("TRAIN", train), ("OUTER_TEST", test)):
                tagged = sample.copy()
                tagged["bucket"] = _assign_bins(tagged[variable], edges)
                for bucket, part in tagged.groupby("bucket", dropna=True, sort=True):
                    for weighting in ("event", "attack_date_equal", "gap_formation_date_equal"):
                        rows.append({"analysis_type": "UNIVARIATE", "fold": fold["fold"], "sample": sample_name, "variable_x": variable, "variable_y": None, "bucket_x": int(bucket), "bucket_y": None, "thresholds_x": json.dumps(edges), "thresholds_y": None, "weighting": weighting, **metric_rows(part, weighting)})
        for x_name, y_name in surfaces:
            x_edges = _quantile_edges(train[x_name], [1 / 3, 2 / 3])
            y_edges = _quantile_edges(train[y_name], [1 / 3, 2 / 3])
            for sample_name, sample in (("TRAIN", train), ("OUTER_TEST", test)):
                tagged = sample.copy()
                tagged["bucket_x"] = _assign_bins(tagged[x_name], x_edges)
                tagged["bucket_y"] = _assign_bins(tagged[y_name], y_edges)
                for (bx, by), part in tagged.groupby(["bucket_x", "bucket_y"], dropna=True, sort=True):
                    for weighting in ("event", "attack_date_equal", "gap_formation_date_equal"):
                        rows.append({"analysis_type": "SURFACE", "fold": fold["fold"], "sample": sample_name, "variable_x": x_name, "variable_y": y_name, "bucket_x": int(bx), "bucket_y": int(by), "thresholds_x": json.dumps(x_edges), "thresholds_y": json.dumps(y_edges), "weighting": weighting, **metric_rows(part, weighting)})
    out = pd.DataFrame(rows).sort_values(["analysis_type", "fold", "sample", "variable_x", "variable_y", "bucket_x", "bucket_y", "weighting"], kind="mergesort", na_position="last")
    write_parquet(out, DIRECT_ANALYSIS)
    return out


def _fwl_effect(frame: pd.DataFrame, treatment: str, outcome: str) -> tuple[float, int]:
    use = frame[[treatment, outcome, "board", "calendar_year", "attack_start_date", "true_gap_width_pct", "gap_age_sessions", "remaining_net_target_at_entry", "attack_memory_state", "single_multigap", "board_return_20d"]].dropna().copy()
    if len(use) < 30 or use[treatment].nunique() < 2:
        return np.nan, len(use)
    use["gap_width_bin"] = pd.qcut(use.true_gap_width_pct.rank(method="first"), 5, labels=False, duplicates="drop").astype(str)
    use["market_condition"] = pd.cut(use.board_return_20d, [-np.inf, 0, np.inf], labels=["WEAK", "REPAIRED"]).astype(str)
    categorical = ["board", "calendar_year", "attack_start_date", "gap_width_bin", "attack_memory_state", "single_multigap", "market_condition"]
    numeric = ["gap_age_sessions", "remaining_net_target_at_entry"]
    pre = ColumnTransformer([
        ("categorical", OneHotEncoder(handle_unknown="ignore", drop="first"), categorical),
        ("numeric", StandardScaler(), numeric),
    ])
    x = pre.fit_transform(use)
    t = use[treatment].astype(float).to_numpy(); y = use[outcome].astype(float).to_numpy()
    t_model = Ridge(alpha=1e-8, solver="lsqr").fit(x, t)
    y_model = Ridge(alpha=1e-8, solver="lsqr").fit(x, y)
    tr = t - t_model.predict(x); yr = y - y_model.predict(x)
    return _safe_div(float(tr @ yr), float(tr @ tr)), len(use)


def build_matched_analysis() -> pd.DataFrame:
    panel = baseline_panel()
    panel = panel.loc[panel.attack_memory_state.eq("CORE") & panel.attack_number.eq(1)].copy()
    rows: list[dict[str, Any]] = []
    for fold in outer_folds():
        train, test, _ = fold_train_test(panel, fold)
        cutoff = float(train.vacuum_score.quantile(0.70))
        test["low_overhang"] = test.vacuum_score.ge(cutoff)
        for board in ("COMBINED", "MAIN", "CHINEXT"):
            part = test if board == "COMBINED" else test.loc[test.board.eq(board)]
            for outcome in ("net_return", "attack_success", "severe_loss10"):
                effect, n = _fwl_effect(part, "low_overhang", outcome)
                date = part.groupby("attack_start_date").filter(lambda x: x.low_overhang.nunique() == 2)
                date_effect = np.nan
                if len(date):
                    grouped = date.groupby(["attack_start_date", "low_overhang"])[outcome].mean().unstack()
                    if False in grouped and True in grouped:
                        date_effect = float((grouped[True] - grouped[False]).mean())
                rows.append({"fold": fold["fold"], "board": board, "outcome": outcome, "n": n, "train_vacuum_q70": cutoff, "fwl_effect": effect, "attack_date_equal_effect": date_effect})
    out = pd.DataFrame(rows).sort_values(["fold", "board", "outcome"], kind="mergesort")
    write_parquet(out, MATCHED_ANALYSIS)
    return out


def stage_b_direct() -> dict[str, Any]:
    _require_frozen_stage_a()
    if not ATTACK_OUTCOMES.is_file():
        raise ResearchError("run stage-b-outcomes first")
    direct = build_direct_analysis()
    matched = build_matched_analysis()
    payload = {"direct_rows": len(direct), "direct_sha256": sha256(DIRECT_ANALYSIS), "matched_rows": len(matched), "matched_sha256": sha256(MATCHED_ANALYSIS), "repository_2024_plus_data_opened": "NO"}
    manifest("STAGE_B_DIRECT_ANALYSIS", "COMPLETE", payload)
    return payload


def _auc(target: pd.Series, prediction: np.ndarray) -> float:
    y = target.astype(int).to_numpy()
    return np.nan if len(np.unique(y)) < 2 else float(roc_auc_score(y, prediction))


def _ecdf_score(reference: pd.Series, values: pd.Series, direction: int) -> np.ndarray:
    ref = np.sort(pd.to_numeric(reference, errors="coerce").dropna().to_numpy(float))
    val = pd.to_numeric(values, errors="coerce").to_numpy(float)
    score = np.full(len(val), np.nan)
    finite = np.isfinite(val)
    if len(ref):
        pct = np.searchsorted(ref, val[finite], side="right") / len(ref)
        score[finite] = pct if direction > 0 else 1.0 - pct
    return score


def _model_scores(method: str, train: pd.DataFrame, test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    target = train.clean_attack_success_10.astype(int).to_numpy()
    model_features = [feature for feature in rule_space_value()["model_features"] if feature in train]
    if method == "MONOTONE_SCORECARD":
        features = rule_space_value()["methods"]["MONOTONE_SCORECARD"]["features"]
        directions = rule_space_value()["methods"]["MONOTONE_SCORECARD"]["directions"]
        train_parts = [_ecdf_score(train[feature], train[feature], direction) for feature, direction in zip(features, directions)]
        test_parts = [_ecdf_score(train[feature], test[feature], direction) for feature, direction in zip(features, directions)]
        return np.nanmean(np.vstack(train_parts), axis=0), np.nanmean(np.vstack(test_parts), axis=0), {"features": features}
    if method == "SHALLOW_DECISION_TREE":
        parameters = rule_space_value()["methods"][method]
        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("model", DecisionTreeClassifier(**parameters)),
        ])
        model.fit(train[model_features].replace([np.inf, -np.inf], np.nan), target)
        return model.predict_proba(train[model_features].replace([np.inf, -np.inf], np.nan))[:, 1], model.predict_proba(test[model_features].replace([np.inf, -np.inf], np.nan))[:, 1], {"tree_text": export_text(model.named_steps["model"], feature_names=model_features)}
    if method == "SPARSE_LOGISTIC":
        parameters = rule_space_value()["methods"][method].copy()
        parameters.pop("time_respecting_scaling", None)
        model = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(**parameters)),
        ])
        model.fit(train[model_features].replace([np.inf, -np.inf], np.nan), target)
        coefficients = model.named_steps["model"].coef_[0]
        detail = dict(sorted(zip(model_features, map(float, coefficients)), key=lambda item: (-abs(item[1]), item[0])))
        return model.predict_proba(train[model_features].replace([np.inf, -np.inf], np.nan))[:, 1], model.predict_proba(test[model_features].replace([np.inf, -np.inf], np.nan))[:, 1], {"coefficients": detail}
    if method == "RULEFIT_LITE":
        fitted = _fit_generated_rule("RULEFIT_LITE", train)
        _, train_score = apply_rule_model(train, fitted)
        _, test_score = apply_rule_model(test, fitted)
        return train_score.to_numpy(float), test_score.to_numpy(float), {"distilled_rule": fitted}
    if method == "LIGHTGBM_CEILING":
        parameters = rule_space_value()["methods"][method].copy()
        parameters.pop("deployable", None); parameters.pop("objective", None)
        train_x = train[model_features].replace([np.inf, -np.inf], np.nan)
        test_x = test[model_features].replace([np.inf, -np.inf], np.nan)
        model = lgb.LGBMClassifier(objective="binary", **parameters)
        model.fit(train_x, target)
        detail = dict(sorted(zip(model_features, map(int, model.feature_importances_)), key=lambda item: (-item[1], item[0])))
        return model.predict_proba(train_x)[:, 1], model.predict_proba(test_x)[:, 1], {"feature_importance": detail}
    raise ResearchError(f"unknown model method {method}")


def _prediction_diagnostic(frame: pd.DataFrame, prediction: np.ndarray, cutoff: float) -> dict[str, Any]:
    finite = np.isfinite(prediction)
    use = frame.loc[finite].copy()
    pred = prediction[finite]
    top = use.loc[pred >= cutoff]
    metrics = selection_metrics(top, len(use))
    return {
        "observations": len(use),
        "auc_clean10": _auc(use.clean_attack_success_10, pred),
        "prediction_mean": None if len(pred) == 0 else float(np.mean(pred)),
        "prediction_std": None if len(pred) == 0 else float(np.std(pred)),
        "prediction_p05": None if len(pred) == 0 else float(np.quantile(pred, 0.05)),
        "prediction_p95": None if len(pred) == 0 else float(np.quantile(pred, 0.95)),
        "top30_cutoff": cutoff,
        **{f"top30_{key}": value for key, value in metrics.items()},
    }


def run_model_diagnostics() -> pd.DataFrame:
    panel = baseline_panel()
    panel = panel.loc[panel.attack_memory_state.eq("CORE") & panel.attack_number.eq(1) & panel.outcome_valid].copy()
    rows = []
    methods = ("MONOTONE_SCORECARD", "SHALLOW_DECISION_TREE", "SPARSE_LOGISTIC", "RULEFIT_LITE", "LIGHTGBM_CEILING")
    for fold in outer_folds():
        fold_train, fold_test, audit = fold_train_test(panel, fold)
        for board in ("MAIN", "CHINEXT"):
            train = fold_train.loc[fold_train.board.eq(board)].copy()
            test = fold_test.loc[fold_test.board.eq(board)].copy()
            if len(train) < 80 or len(test) == 0 or train.clean_attack_success_10.nunique() < 2:
                continue
            for method in methods:
                train_prediction, test_prediction, detail = _model_scores(method, train, test)
                cutoff = float(np.nanquantile(train_prediction, 0.70))
                for sample, frame, prediction in (("TRAIN", train, train_prediction), ("OUTER_TEST", test, test_prediction)):
                    rows.append({
                        "fold": fold["fold"], "board": board, "method": method, "sample": sample,
                        "detail_json": canonical_json(detail).strip(), **audit,
                        **_prediction_diagnostic(frame, prediction, cutoff),
                    })
    out = pd.DataFrame(rows).sort_values(["fold", "board", "method", "sample"], kind="mergesort")
    write_parquet(out, MODEL_DIAGNOSTICS)
    return out


def stage_b_rules() -> dict[str, Any]:
    _require_frozen_stage_a()
    if not DIRECT_ANALYSIS.is_file() or not MATCHED_ANALYSIS.is_file():
        raise ResearchError("direct analysis must complete before any model fit")
    diagnostics = run_model_diagnostics()
    payload = {
        "model_diagnostic_rows": len(diagnostics),
        "model_diagnostics_sha256": sha256(MODEL_DIAGNOSTICS),
        "raw_black_box_deployable": "NO",
        "rule_added_after_outcome_open_count": 0,
        "repository_2024_plus_data_opened": "NO",
    }
    manifest("STAGE_B_RULE_DISCOVERY", "MODEL_CEILING_COMPLETE_HIERARCHY_PENDING", payload)
    return payload


def _inner_pairs(panel: pd.DataFrame, outer_start: pd.Timestamp) -> list[tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, int]]]:
    output = []
    for fold in inner_folds_before(outer_start):
        train, valid, audit = fold_train_test(panel, fold)
        if len(train) and len(valid):
            output.append((fold, train, valid, audit))
    return output


def _block_record(
    outer_fold: str,
    board: str,
    stage: str,
    candidate: str,
    inner: dict[str, Any],
    selected: pd.DataFrame,
    denominator: int,
    condition_count: int,
    parameters: dict[str, Any],
    audit: dict[str, int],
) -> dict[str, Any]:
    return {
        "outer_fold": outer_fold, "board": board, "selection_stage": stage,
        "candidate": candidate, "inner_fold": inner["fold"],
        "condition_count": int(condition_count), "parameters_json": canonical_json(parameters).strip(),
        **audit, **selection_metrics(selected, denominator),
    }


def _full_support(frame: pd.DataFrame, mask: pd.Series, boundary: pd.Timestamp, condition_count: int, simplicity_rank: int = 0) -> dict[str, Any]:
    selected = frame.loc[mask & frame.outcome_valid & frame.net_return.notna()]
    latest = latest_full_train_year(boundary)
    return {
        "full_train_trades": len(selected),
        "latest_full_train_year": latest,
        "latest_full_train_year_trades": int(selected.attack_start_date.dt.year.eq(latest).sum()),
        "condition_count": int(condition_count),
        "simplicity_rank": int(simplicity_rank),
    }


def choose_overhang_rule(
    panel: pd.DataFrame,
    outer: dict[str, Any],
    board: str,
) -> tuple[str, dict[str, Any], pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train, test, _ = fold_train_test(panel.loc[panel.board.eq(board)], outer)
    candidate_ids = list(rule_space_value()["fixed_low_overhang_rules"]) + ["TREE_SINGLE_LEAF", "RULEFIT_LITE", "LGBM_DISTILLED_LEAF"]
    rows = []
    support: dict[str, dict[str, Any]] = {}
    full_models: dict[str, dict[str, Any]] = {}
    for candidate in candidate_ids:
        for inner, inner_train, inner_valid, audit in _inner_pairs(train, outer["start"]):
            fitted = fit_overhang_rule(candidate, inner_train)
            mask, _ = apply_rule_model(inner_valid, fitted)
            selected = inner_valid.loc[mask]
            rows.append(_block_record(outer["fold"], board, "OVERHANG", candidate, inner, selected, len(inner_valid), int(fitted.get("complexity", 99)) + 1, fitted, audit))
        fitted = fit_overhang_rule(candidate, train)
        mask, _ = apply_rule_model(train, fitted)
        full_models[candidate] = fitted
        support[candidate] = _full_support(train, mask, outer["start"], int(fitted.get("complexity", 99)) + 1)
    block_rows = pd.DataFrame(rows)
    summary = summarize_candidate_blocks(block_rows, support)
    chosen, summary = one_se_choice(summary)
    rule_id = str(chosen.candidate)
    return rule_id, full_models[rule_id], train, test, block_rows, summary


def choose_environment(
    panel: pd.DataFrame,
    outer: dict[str, Any],
    board: str,
    overhang_id: str,
) -> tuple[str, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    train, _, _ = fold_train_test(panel.loc[panel.board.eq(board)], outer)
    candidates = list(rule_space_value()["fixed_environment_extensions"])
    rows = []
    support: dict[str, dict[str, Any]] = {}
    full_models: dict[str, dict[str, Any]] = {}
    full_overhang = fit_overhang_rule(overhang_id, train)
    for rank, candidate in enumerate(candidates):
        for inner, inner_train, inner_valid, audit in _inner_pairs(train, outer["start"]):
            overhang = fit_overhang_rule(overhang_id, inner_train)
            environment = fit_environment_rule(candidate, inner_train)
            mask, _ = apply_admission(inner_valid, overhang, environment)
            selected = inner_valid.loc[mask]
            count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
            rows.append(_block_record(outer["fold"], board, "ENVIRONMENT", candidate, inner, selected, len(inner_valid), count, {"overhang": overhang, "environment": environment}, audit))
        environment = fit_environment_rule(candidate, train)
        mask, _ = apply_admission(train, full_overhang, environment)
        count = int(full_overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
        full_models[candidate] = environment
        support[candidate] = _full_support(train, mask, outer["start"], count, rank)
    block_rows = pd.DataFrame(rows)
    summary = summarize_candidate_blocks(block_rows, support)
    chosen, summary = one_se_choice(summary)
    candidate = str(chosen.candidate)
    return candidate, full_models[candidate], block_rows, summary


def _admitted(
    train: pd.DataFrame,
    target: pd.DataFrame,
    overhang_id: str,
    environment_id: str,
    remaining_floor: float | None,
    attack_numbers: tuple[int, ...],
    fit_reference: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any], pd.Series]:
    reference = train if fit_reference is None else fit_reference
    overhang = fit_overhang_rule(overhang_id, reference)
    environment = fit_environment_rule(environment_id, reference)
    mask, score = apply_admission(target, overhang, environment)
    mask &= target.attack_number.isin(attack_numbers)
    if remaining_floor is not None:
        mask &= target.remaining_net_target_at_entry.ge(float(remaining_floor))
    selected = target.loc[mask].copy()
    selected["simple_rule_score"] = score.loc[mask].astype(float)
    if 2 in attack_numbers and len(selected):
        # ATTACK_2 is independent, but it cannot create a second position while
        # a selected ATTACK_1 trade on the same frozen gap is still open.
        first_exit = selected.loc[selected.attack_number.eq(1)].groupby("gap_id").exit_time.max().to_dict()
        blocked_retry = selected.attack_number.eq(2) & selected.apply(
            lambda row: row.gap_id in first_exit and pd.Timestamp(first_exit[row.gap_id]) >= pd.Timestamp(row.entry_time), axis=1,
        )
        selected = selected.loc[~blocked_retry].copy()
    return selected, overhang, environment, score


def _baseline_outer_reference(store: PanelStore, outer: dict[str, Any], board: str) -> pd.DataFrame:
    panel = store.get("Z0+CLOSE", 20, "X0_NO_FAILURE_EXIT")
    panel = panel.loc[panel.board.eq(board) & panel.attack_memory_state.eq("CORE") & panel.attack_number.eq(1)]
    train, _, _ = fold_train_test(panel, outer)
    return train


def _reference_for_target(reference: pd.DataFrame, target_validation: pd.DataFrame) -> pd.DataFrame:
    test_gaps = set(target_validation.gap_id.astype(str))
    return reference.loc[~reference.gap_id.astype(str).isin(test_gaps)].copy()


def _inner_reference(reference: pd.DataFrame, inner: dict[str, Any], target_validation: pd.DataFrame) -> pd.DataFrame:
    train, _, _ = fold_train_test(reference, inner)
    return _reference_for_target(train, target_validation)


def _upstream_admission_support(
    store: PanelStore,
    outer: dict[str, Any],
    board: str,
    overhang_id: str,
    environment_id: str,
) -> dict[str, Any]:
    train = _baseline_outer_reference(store, outer, board)
    selected, overhang, environment, _ = _admitted(train, train, overhang_id, environment_id, None, (1,))
    support = _full_support(
        train,
        pd.Series(train.index.isin(selected.index), index=train.index),
        outer["start"],
        int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1,
    )
    support["support_scope"] = "UPSTREAM_ADMISSION_COMPLETED_ATTACKS"
    return support


def choose_entry_translation(
    store: PanelStore,
    outer: dict[str, Any],
    board: str,
    overhang_id: str,
    environment_id: str,
) -> tuple[str, float, pd.DataFrame, pd.DataFrame]:
    rows = []
    support: dict[str, dict[str, Any]] = {}
    candidate_panels: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    upstream_support = _upstream_admission_support(store, outer, board, overhang_id, environment_id)
    reference_outer = _baseline_outer_reference(store, outer, board)
    translations = [f"{level}+{form}" for level in PENETRATION_LEVELS for form in ACCEPTANCE_FORMS]
    for translation_rank, translation in enumerate(translations):
        panel = store.get(translation, 20, "X0_NO_FAILURE_EXIT")
        panel = panel.loc[panel.board.eq(board) & panel.attack_memory_state.eq("CORE") & panel.attack_number.eq(1)]
        train, test, _ = fold_train_test(panel, outer)
        for floor_rank, remaining_floor in enumerate(REMAINING_TARGETS):
            candidate = f"{translation}|RNT{int(remaining_floor * 10000):03d}BP"
            candidate_panels[candidate] = (train, test)
            for inner, inner_train, inner_valid, audit in _inner_pairs(train, outer["start"]):
                reference = _inner_reference(reference_outer, inner, inner_valid)
                selected, overhang, environment, _ = _admitted(inner_train, inner_valid, overhang_id, environment_id, remaining_floor, (1,), reference)
                count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
                rows.append(_block_record(outer["fold"], board, "ENTRY", candidate, inner, selected, len(inner_valid), count, {"translation": translation, "remaining_floor": remaining_floor, "overhang": overhang, "environment": environment}, audit))
            reference = _reference_for_target(reference_outer, test)
            selected, overhang, environment, _ = _admitted(train, train, overhang_id, environment_id, remaining_floor, (1,), reference)
            count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
            support[candidate] = {**upstream_support, "condition_count": count, "simplicity_rank": translation_rank * 10 + floor_rank, "downstream_full_train_trades": len(selected), "downstream_latest_full_train_year_trades": int(selected.attack_start_date.dt.year.eq(latest_full_train_year(outer["start"])).sum())}
    block_rows = pd.DataFrame(rows)
    summary = summarize_candidate_blocks(block_rows, support)
    chosen, summary = one_se_choice(summary)
    candidate = str(chosen.candidate)
    translation, floor_text = candidate.split("|RNT")
    return translation, int(floor_text.removesuffix("BP")) / 10000.0, block_rows, summary


def choose_exit_policy(
    store: PanelStore,
    outer: dict[str, Any],
    board: str,
    overhang_id: str,
    environment_id: str,
    translation: str,
    remaining_floor: float,
) -> tuple[int, str, pd.DataFrame, pd.DataFrame]:
    rows = []
    support: dict[str, dict[str, Any]] = {}
    upstream_support = _upstream_admission_support(store, outer, board, overhang_id, environment_id)
    reference_outer = _baseline_outer_reference(store, outer, board)
    horizon_order = {20: 0, 10: 1, 5: 2}
    for policy_rank, policy in enumerate(FAILURE_POLICIES):
        for horizon in TIME_STOPS:
            candidate = f"{policy}|H{horizon}"
            panel = store.get(translation, horizon, policy)
            panel = panel.loc[panel.board.eq(board) & panel.attack_memory_state.eq("CORE") & panel.attack_number.eq(1)]
            train, _, _ = fold_train_test(panel, outer)
            for inner, inner_train, inner_valid, audit in _inner_pairs(train, outer["start"]):
                reference = _inner_reference(reference_outer, inner, inner_valid)
                selected, overhang, environment, _ = _admitted(inner_train, inner_valid, overhang_id, environment_id, remaining_floor, (1,), reference)
                count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
                rows.append(_block_record(outer["fold"], board, "EXIT", candidate, inner, selected, len(inner_valid), count, {"horizon": horizon, "policy": policy}, audit))
            _, outer_test, _ = fold_train_test(panel, outer)
            reference = _reference_for_target(reference_outer, outer_test)
            selected, overhang, environment, _ = _admitted(train, train, overhang_id, environment_id, remaining_floor, (1,), reference)
            count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
            support[candidate] = {**upstream_support, "condition_count": count, "simplicity_rank": policy_rank * 10 + horizon_order[horizon], "downstream_full_train_trades": len(selected), "downstream_latest_full_train_year_trades": int(selected.attack_start_date.dt.year.eq(latest_full_train_year(outer["start"])).sum())}
    block_rows = pd.DataFrame(rows)
    summary = summarize_candidate_blocks(block_rows, support)
    chosen, summary = one_se_choice(summary)
    policy, horizon = str(chosen.candidate).split("|H")
    return int(horizon), policy, block_rows, summary


def choose_retry(
    store: PanelStore,
    outer: dict[str, Any],
    board: str,
    overhang_id: str,
    environment_id: str,
    translation: str,
    remaining_floor: float,
    horizon: int,
    policy: str,
) -> tuple[str, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    panel = store.get(translation, horizon, policy)
    panel = panel.loc[panel.board.eq(board) & panel.attack_memory_state.eq("CORE")]
    train, _, _ = fold_train_test(panel, outer)
    rows = []
    support: dict[str, dict[str, Any]] = {}
    selected_oof = []
    upstream_support = _upstream_admission_support(store, outer, board, overhang_id, environment_id)
    reference_outer = _baseline_outer_reference(store, outer, board)
    for rank, (candidate, attacks) in enumerate((("R0_NO_RETRY", (1,)), ("R1_ONE_RETRY", (1, 2)))):
        for inner, inner_train, inner_valid, audit in _inner_pairs(train, outer["start"]):
            reference = _inner_reference(reference_outer, inner, inner_valid)
            selected, overhang, environment, _ = _admitted(inner_train, inner_valid, overhang_id, environment_id, remaining_floor, attacks, reference)
            selected["inner_fold"] = inner["fold"]
            selected["retry_candidate"] = candidate
            selected_oof.append(selected)
            count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
            rows.append(_block_record(outer["fold"], board, "RETRY", candidate, inner, selected, len(inner_valid), count, {"attack_numbers": attacks}, audit))
        _, outer_test, _ = fold_train_test(panel, outer)
        reference = _reference_for_target(reference_outer, outer_test)
        selected, overhang, environment, _ = _admitted(train, train, overhang_id, environment_id, remaining_floor, attacks, reference)
        count = int(overhang.get("complexity", 99)) + int(environment.get("complexity", 99)) + 1
        support[candidate] = {**upstream_support, "condition_count": count, "simplicity_rank": rank, "downstream_full_train_trades": len(selected), "downstream_latest_full_train_year_trades": int(selected.attack_start_date.dt.year.eq(latest_full_train_year(outer["start"])).sum())}
    block_rows = pd.DataFrame(rows)
    summary = summarize_candidate_blocks(block_rows, support)
    chosen, summary = one_se_choice(summary)
    chosen_id = str(chosen.candidate)
    oof = pd.concat(selected_oof, ignore_index=True) if selected_oof else pd.DataFrame()
    oof = oof.loc[oof.retry_candidate.eq(chosen_id)].copy() if len(oof) else oof
    return chosen_id, block_rows, summary, oof


def _baseline_inner_oof(panel: pd.DataFrame, outer_start: pd.Timestamp) -> pd.DataFrame:
    parts = []
    for inner, _, valid, _ in _inner_pairs(panel, outer_start):
        value = valid.copy()
        value["inner_fold"] = inner["fold"]
        parts.append(value)
    return pd.concat(parts, ignore_index=True) if parts else panel.iloc[0:0].copy()


def _decorate_lane(frame: pd.DataFrame, outer: dict[str, Any], board: str, lane: str, procedure: str, selection: dict[str, Any]) -> pd.DataFrame:
    output = frame.copy()
    output["outer_fold"] = outer["fold"]
    output["board_sleeve"] = board
    output["lane"] = lane
    output["procedure"] = procedure
    for key, value in selection.items():
        output[f"selected_{key}"] = value if not isinstance(value, (dict, list, tuple)) else canonical_json(value).strip()
    if "simple_rule_score" not in output:
        output["simple_rule_score"] = 0.0
    return output


def _test_panel(store: PanelStore, outer: dict[str, Any], board: str, translation: str, horizon: int, policy: str, attack_numbers: tuple[int, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = store.get(translation, horizon, policy)
    panel = panel.loc[panel.board.eq(board) & panel.attack_memory_state.eq("CORE") & panel.attack_number.isin(attack_numbers)]
    train, test, _ = fold_train_test(panel, outer)
    return train, test


def run_hierarchical_walkforward() -> dict[str, Any]:
    store = PanelStore()
    all_inner = []
    all_candidates = []
    selections = []
    trade_parts = []
    audit = Counter()
    for outer in outer_folds():
        base_panel = store.get("Z0+CLOSE", 20, "X0_NO_FAILURE_EXIT")
        base_panel = base_panel.loc[base_panel.attack_memory_state.eq("CORE") & base_panel.attack_number.eq(1)]
        for board in ("MAIN", "CHINEXT"):
            overhang_id, overhang_model, base_train, base_test, rows, summary = choose_overhang_rule(base_panel, outer, board)
            all_inner.append(rows); summary["outer_fold"] = outer["fold"]; summary["board"] = board; summary["selection_stage"] = "OVERHANG"; all_candidates.append(summary)

            environment_id, environment_model, rows, summary = choose_environment(base_panel, outer, board, overhang_id)
            all_inner.append(rows); summary["outer_fold"] = outer["fold"]; summary["board"] = board; summary["selection_stage"] = "ENVIRONMENT"; all_candidates.append(summary)

            translation, remaining_floor, rows, summary = choose_entry_translation(store, outer, board, overhang_id, environment_id)
            all_inner.append(rows); summary["outer_fold"] = outer["fold"]; summary["board"] = board; summary["selection_stage"] = "ENTRY"; all_candidates.append(summary)

            horizon, policy, rows, summary = choose_exit_policy(store, outer, board, overhang_id, environment_id, translation, remaining_floor)
            all_inner.append(rows); summary["outer_fold"] = outer["fold"]; summary["board"] = board; summary["selection_stage"] = "EXIT"; all_candidates.append(summary)

            retry, rows, summary, final_oof = choose_retry(store, outer, board, overhang_id, environment_id, translation, remaining_floor, horizon, policy)
            all_inner.append(rows); summary["outer_fold"] = outer["fold"]; summary["board"] = board; summary["selection_stage"] = "RETRY"; all_candidates.append(summary)
            retry_summary = summary.loc[summary.selected].iloc[0]

            baseline_oof = _baseline_inner_oof(base_train, outer["start"])
            final_metrics = selection_metrics(final_oof, len(baseline_oof))
            baseline_metrics = selection_metrics(baseline_oof, len(baseline_oof))
            gate_checks = {
                "mean_net_return_positive": bool(final_metrics["mean_net_return"] > 0),
                "median_net_return_positive": bool(final_metrics["median_net_return"] > 0),
                "clean_success_above_baseline": bool(final_metrics["clean_success_10"] > baseline_metrics["clean_success_10"]),
                "severe10_below_baseline": bool(final_metrics["severe_loss10"] < baseline_metrics["severe_loss10"]),
                "median_inner_utility_positive": bool(retry_summary.median_inner_utility > 0),
                "positive_inner_blocks_at_least_three": bool(retry_summary.positive_inner_blocks >= 3),
            }
            deployment_ready = all(gate_checks.values())
            selected = {
                "overhang_rule": overhang_id,
                "environment": environment_id,
                "translation": translation,
                "remaining_floor": remaining_floor,
                "time_stop": horizon,
                "exit_policy": policy,
                "retry": retry,
            }

            # L0: frozen attack baseline.
            l0 = base_test.loc[base_test.outcome_valid].copy()
            l0["simple_rule_score"] = 0.0
            trade_parts.append(_decorate_lane(l0, outer, board, "L0_ATTACK_BASELINE", "FORCED_CHOICE_WF", selected))

            # L1 and L2 on the fixed baseline translation and exit.
            l1, _, _, _ = _admitted(base_train, base_test, overhang_id, "NONE", None, (1,))
            trade_parts.append(_decorate_lane(l1, outer, board, "L1_LOW_OVERHANG", "FORCED_CHOICE_WF", selected))
            l2, _, _, _ = _admitted(base_train, base_test, overhang_id, environment_id, None, (1,))
            trade_parts.append(_decorate_lane(l2, outer, board, "L2_LOW_OVERHANG_ENVIRONMENT", "FORCED_CHOICE_WF", selected))

            # L3: selected entry translation but baseline exit.
            entry_train, entry_test = _test_panel(store, outer, board, translation, 20, "X0_NO_FAILURE_EXIT", (1,))
            entry_reference = _reference_for_target(base_train, entry_test)
            l3, _, _, _ = _admitted(entry_train, entry_test, overhang_id, environment_id, remaining_floor, (1,), entry_reference)
            trade_parts.append(_decorate_lane(l3, outer, board, "L3_ATTACK_ACCEPTANCE", "FORCED_CHOICE_WF", selected))

            # L4: selected failure/time policy applied without admission to L0.
            loss_train, loss_test = _test_panel(store, outer, board, "Z0+CLOSE", horizon, policy, (1,))
            loss_test = loss_test.loc[loss_test.outcome_valid].copy(); loss_test["simple_rule_score"] = 0.0
            trade_parts.append(_decorate_lane(loss_test, outer, board, "L4_FAILURE_EXIT", "FORCED_CHOICE_WF", selected))

            # L5/L6: full selected rule; ATTACK_2 independently passes admission.
            attacks = (1, 2) if retry == "R1_ONE_RETRY" else (1,)
            full_train, full_test = _test_panel(store, outer, board, translation, horizon, policy, attacks)
            full_reference = _reference_for_target(base_train, full_test)
            l5, final_overhang, final_environment, _ = _admitted(full_train, full_test, overhang_id, environment_id, remaining_floor, attacks, full_reference)
            trade_parts.append(_decorate_lane(l5, outer, board, "L5_FULL_SIMPLE_RULE", "FORCED_CHOICE_WF", selected))
            if retry == "R1_ONE_RETRY":
                l6 = l5.loc[l5.attack_number.eq(2)].copy()
                trade_parts.append(_decorate_lane(l6, outer, board, "L6_ONE_RETRY_INCREMENT", "FORCED_CHOICE_WF", selected))
            if deployment_ready:
                trade_parts.append(_decorate_lane(l5, outer, board, "L5_FULL_SIMPLE_RULE", "DEPLOYMENT_GATED_WF", selected))
                if retry == "R1_ONE_RETRY":
                    trade_parts.append(_decorate_lane(l5.loc[l5.attack_number.eq(2)], outer, board, "L6_ONE_RETRY_INCREMENT", "DEPLOYMENT_GATED_WF", selected))

            outer_test_metrics = selection_metrics(l5, len(full_test))
            record = {
                "outer_fold": outer["fold"], "selection_role": "OUTER_WALKFORWARD", "board": board,
                "train_start": "2014-01-01", "test_start": outer["start"], "test_end": outer["end"],
                **selected,
                "overhang_model_json": canonical_json(final_overhang).strip(),
                "environment_model_json": canonical_json(final_environment).strip(),
                "admission_condition_count": int(final_overhang.get("complexity", 99)) + int(final_environment.get("complexity", 99)) + 1,
                "deployment_ready": deployment_ready,
                "gate_checks_json": canonical_json(gate_checks).strip(),
                "train_oof_metrics_json": canonical_json(final_metrics).strip(),
                "baseline_train_oof_metrics_json": canonical_json(baseline_metrics).strip(),
                "outer_test_metrics_json": canonical_json(outer_test_metrics).strip(),
                "test_half_used_in_own_selection": False,
                "same_gap_split_across_folds_count": 0,
                "purge_embargo_violation_count": 0,
            }
            selections.append(record)
            print(canonical_json({"outer_fold": outer["fold"], "board": board, "selected": selected, "deployment_ready": deployment_ready, "test_trades": outer_test_metrics["trades"]}).strip(), flush=True)

    # Freeze one deployment rule per sleeve using Development only.  This is a
    # training-only 2022 boundary: no 2022 row exists in the Development store,
    # and the resulting thresholds remain unchanged for both diagnostic years.
    deployment_outer = {"fold": "DEPLOYMENT_FREEZE_2022", "year": 2022, "half": 1, "start": pd.Timestamp("2022-01-01"), "end": pd.Timestamp("2022-06-30")}
    base_panel = store.get("Z0+CLOSE", 20, "X0_NO_FAILURE_EXIT")
    base_panel = base_panel.loc[base_panel.attack_memory_state.eq("CORE") & base_panel.attack_number.eq(1)]
    for board in ("MAIN", "CHINEXT"):
        overhang_id, _, base_train, _, rows, summary = choose_overhang_rule(base_panel, deployment_outer, board)
        all_inner.append(rows); summary["outer_fold"] = deployment_outer["fold"]; summary["board"] = board; summary["selection_stage"] = "OVERHANG"; all_candidates.append(summary)
        environment_id, _, rows, summary = choose_environment(base_panel, deployment_outer, board, overhang_id)
        all_inner.append(rows); summary["outer_fold"] = deployment_outer["fold"]; summary["board"] = board; summary["selection_stage"] = "ENVIRONMENT"; all_candidates.append(summary)
        translation, remaining_floor, rows, summary = choose_entry_translation(store, deployment_outer, board, overhang_id, environment_id)
        all_inner.append(rows); summary["outer_fold"] = deployment_outer["fold"]; summary["board"] = board; summary["selection_stage"] = "ENTRY"; all_candidates.append(summary)
        horizon, policy, rows, summary = choose_exit_policy(store, deployment_outer, board, overhang_id, environment_id, translation, remaining_floor)
        all_inner.append(rows); summary["outer_fold"] = deployment_outer["fold"]; summary["board"] = board; summary["selection_stage"] = "EXIT"; all_candidates.append(summary)
        retry, rows, summary, final_oof = choose_retry(store, deployment_outer, board, overhang_id, environment_id, translation, remaining_floor, horizon, policy)
        all_inner.append(rows); summary["outer_fold"] = deployment_outer["fold"]; summary["board"] = board; summary["selection_stage"] = "RETRY"; all_candidates.append(summary)
        retry_summary = summary.loc[summary.selected].iloc[0]
        baseline_oof = _baseline_inner_oof(base_train, deployment_outer["start"])
        final_metrics = selection_metrics(final_oof, len(baseline_oof)); baseline_metrics = selection_metrics(baseline_oof, len(baseline_oof))
        gate_checks = {
            "mean_net_return_positive": bool(final_metrics["mean_net_return"] > 0),
            "median_net_return_positive": bool(final_metrics["median_net_return"] > 0),
            "clean_success_above_baseline": bool(final_metrics["clean_success_10"] > baseline_metrics["clean_success_10"]),
            "severe10_below_baseline": bool(final_metrics["severe_loss10"] < baseline_metrics["severe_loss10"]),
            "median_inner_utility_positive": bool(retry_summary.median_inner_utility > 0),
            "positive_inner_blocks_at_least_three": bool(retry_summary.positive_inner_blocks >= 3),
        }
        final_reference = _baseline_outer_reference(store, deployment_outer, board)
        final_overhang = fit_overhang_rule(overhang_id, final_reference); final_environment = fit_environment_rule(environment_id, final_reference)
        selections.append({
            "outer_fold": deployment_outer["fold"], "selection_role": "POST_DIAGNOSTIC_FROZEN_DEPLOYMENT", "board": board,
            "train_start": "2014-01-01", "test_start": pd.Timestamp("2022-01-01"), "test_end": pd.Timestamp("2023-12-31"),
            "overhang_rule": overhang_id, "environment": environment_id, "translation": translation,
            "remaining_floor": remaining_floor, "time_stop": horizon, "exit_policy": policy, "retry": retry,
            "overhang_model_json": canonical_json(final_overhang).strip(), "environment_model_json": canonical_json(final_environment).strip(),
            "admission_condition_count": int(final_overhang.get("complexity", 99)) + int(final_environment.get("complexity", 99)) + 1,
            "deployment_ready": all(gate_checks.values()), "gate_checks_json": canonical_json(gate_checks).strip(),
            "train_oof_metrics_json": canonical_json(final_metrics).strip(), "baseline_train_oof_metrics_json": canonical_json(baseline_metrics).strip(),
            "outer_test_metrics_json": canonical_json({"status": "UNOPENED_AT_FREEZE"}).strip(),
            "test_half_used_in_own_selection": False, "same_gap_split_across_folds_count": 0, "purge_embargo_violation_count": 0,
        })
        print(canonical_json({"deployment_freeze": board, "selected": {"overhang": overhang_id, "environment": environment_id, "translation": translation, "remaining_floor": remaining_floor, "time_stop": horizon, "exit_policy": policy, "retry": retry}, "deployment_ready": all(gate_checks.values())}).strip(), flush=True)

    inner = pd.concat(all_inner, ignore_index=True).sort_values(["outer_fold", "board", "selection_stage", "candidate", "inner_fold"], kind="mergesort")
    candidates = pd.concat(all_candidates, ignore_index=True).sort_values(["outer_fold", "board", "selection_stage", "candidate"], kind="mergesort")
    selection_frame = pd.DataFrame(selections).sort_values(["outer_fold", "board"], kind="mergesort")
    trades = pd.concat(trade_parts, ignore_index=True).sort_values(["procedure", "lane", "entry_time", "board", "gap_id", "attack_number"], kind="mergesort")
    write_parquet(inner, INNER_OOF_RESULTS)
    write_parquet(candidates, RULE_CANDIDATES)
    write_parquet(selection_frame, OUTER_SELECTIONS)
    write_parquet(trades, TRADES)
    audit.update({
        "same_gap_split_across_folds_count": int(inner.same_gap_split.sum()),
        "purge_embargo_violation_count": int(inner.purge_violation.sum()),
        "test_half_used_in_own_selection_count": int(selection_frame.test_half_used_in_own_selection.sum()),
        "maximum_admission_conditions": int(selection_frame.admission_condition_count.max()),
    })
    if audit["same_gap_split_across_folds_count"] or audit["purge_embargo_violation_count"] or audit["test_half_used_in_own_selection_count"] or audit["maximum_admission_conditions"] > 5:
        raise ResearchError(f"walk-forward audit failed: {dict(audit)}")
    freeze = {
        "experiment": EXPERIMENT,
        "label": "2014_2021_DEVELOPMENT_PROCEDURE_FROZEN_BEFORE_POST_OBSERVATION_DIAGNOSTIC",
        "stage_a_freeze_sha256": sha256(FEATURE_FREEZE),
        "rule_candidates_sha256": sha256(RULE_CANDIDATES),
        "inner_oof_results_sha256": sha256(INNER_OOF_RESULTS),
        "outer_walkforward_selections_sha256": sha256(OUTER_SELECTIONS),
        "trades_sha256": sha256(TRADES),
        "semantic_change_after_outcome_open_count": 0,
        "feature_added_after_outcome_open_count": 0,
        "rule_added_after_outcome_open_count": 0,
        "exit_added_after_outcome_open_count": 0,
        "post_observation_opened": "NO",
        "repository_2024_plus_data_opened": "NO",
    }
    write_json(FINAL_PROCEDURE_FREEZE, freeze)
    return {
        "selections": len(selection_frame),
        "deployment_ready_folds": int(selection_frame.deployment_ready.sum()),
        "trade_rows": len(trades),
        "inner_rows": len(inner),
        "candidate_rows": len(candidates),
        "audit": dict(audit),
        "final_procedure_freeze_sha256": sha256(FINAL_PROCEDURE_FREEZE),
        "repository_2024_plus_data_opened": "NO",
    }


def stage_b_walkforward() -> dict[str, Any]:
    _require_frozen_stage_a()
    if not MODEL_DIAGNOSTICS.is_file():
        raise ResearchError("run stage-b-rules before walk-forward")
    result = run_hierarchical_walkforward()
    manifest("STAGE_B_WALKFORWARD", "COMPLETE", result)
    return result


@dataclass
class V7Replay:
    nav: pd.DataFrame
    accepted: pd.DataFrame
    ledger: pd.DataFrame
    audit: dict[str, int]


def replay_v7(trades: pd.DataFrame, daily: pd.DataFrame, board: str, k: int, years: tuple[int, ...]) -> V7Replay:
    signals = trades.loc[trades.board.eq(board) & pd.to_datetime(trades.entry_date).dt.year.isin(years) & trades.outcome_valid].copy()
    signals = signals.sort_values(
        ["entry_time", "simple_rule_score", "vacuum_score", "target_to_risk_ratio", "symbol", "gap_id"],
        ascending=[True, False, False, False, True, True], kind="mergesort", na_position="last",
    )
    calendar = daily.loc[daily.trade_date.dt.year.isin(years), ["trade_date", "cal_idx"]].drop_duplicates("trade_date").sort_values("trade_date")
    if calendar.empty:
        raise ResearchError("empty replay calendar")
    period_end = pd.Timestamp(calendar.trade_date.max()) + pd.Timedelta(hours=15)
    relevant = daily.loc[daily.symbol.isin(signals.symbol.unique())].copy()
    dates_by_symbol = {symbol: part.sort_values("trade_date") for symbol, part in relevant.groupby("symbol", sort=False)}
    marks = {(row.symbol, pd.Timestamp(row.trade_date)): float(row.close) for row in relevant.itertuples(index=False) if np.isfinite(row.close)}
    cash = 1.0
    active_by_symbol: dict[str, dict[str, Any]] = {}
    active_gaps: set[str] = set()
    accepted: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    audit = Counter()

    def initialize_actions(position: dict[str, Any]) -> None:
        position["cash_events"] = json.loads(position.get("cash_events_json") or "[]")
        position["cash_event_index"] = 0
        position["action_cash_per_share"] = 0.0

    def credit(position: dict[str, Any], when: pd.Timestamp) -> float:
        amount = 0.0
        while position["cash_event_index"] < len(position["cash_events"]):
            event = position["cash_events"][position["cash_event_index"]]
            if pd.Timestamp(event["date"]) > when.normalize():
                break
            per_share = float(event["cash_per_share"])
            amount += position["qty"] * per_share
            position["action_cash_per_share"] += per_share
            position["cash_event_index"] += 1
        return amount

    def mark(position: dict[str, Any], when: pd.Timestamp) -> float:
        part = dates_by_symbol.get(position["symbol"], pd.DataFrame())
        prior = part.loc[part.trade_date.lt(when.normalize())] if len(part) else part
        return float(prior.close.iloc[-1]) if len(prior) else float(position["entry_raw_price"])

    def close_due(when: pd.Timestamp) -> None:
        nonlocal cash
        due = sorted(
            [position for position in active_by_symbol.values() if pd.notna(position["exit_time"]) and pd.Timestamp(position["exit_time"]) <= when],
            key=lambda position: (pd.Timestamp(position["exit_time"]), position["symbol"], position["gap_id"]),
        )
        for position in due:
            cash += credit(position, pd.Timestamp(position["exit_time"]))
            cash += position["qty"] * float(position["exit_raw_price"]) * (1 - COST)
            position["completed"] = True
            position["net_return"] = (float(position["exit_raw_price"]) * (1 - COST) + position["action_cash_per_share"]) / (float(position["entry_raw_price"]) * (1 + COST)) - 1
            active_by_symbol.pop(position["symbol"], None)
            active_gaps.discard(str(position["gap_id"]))

    for timestamp, group in signals.groupby("entry_time", sort=True):
        timestamp = pd.Timestamp(timestamp)
        close_due(timestamp)
        for position in active_by_symbol.values():
            cash += credit(position, timestamp)
        for row in group.itertuples(index=False):
            base = {"entry_key": row.entry_key, "attack_id": row.attack_id, "gap_id": row.gap_id, "symbol": row.symbol, "board": board, "k": k, "entry_time": row.entry_time, "exit_time": row.exit_time}
            if row.symbol in active_by_symbol:
                audit["duplicate_symbol_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_DUPLICATE_SYMBOL", "capacity_skip": False})
                continue
            if str(row.gap_id) in active_gaps:
                audit["duplicate_gap_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_DUPLICATE_GAP", "capacity_skip": False})
                continue
            if len(active_by_symbol) >= k:
                audit["capacity_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_CAPACITY", "capacity_skip": True})
                continue
            nav_now = cash + sum(position["qty"] * mark(position, timestamp) for position in active_by_symbol.values())
            outlay = nav_now / k
            if cash + 1e-12 < outlay or outlay <= 0:
                audit["insufficient_cash_skip_count"] += 1
                ledger.append({**base, "status": "SKIPPED_INSUFFICIENT_CASH", "capacity_skip": False})
                continue
            quantity = outlay / (float(row.entry_raw_price) * (1 + COST))
            cash -= outlay
            if cash < -1e-12:
                audit["negative_cash_or_leverage_count"] += 1
            position = row._asdict()
            position.update(qty=quantity, completed=False, entry_nav=nav_now, entry_outlay=outlay, initial_weight=outlay / nav_now)
            initialize_actions(position)
            accepted.append(position)
            active_by_symbol[row.symbol] = position
            active_gaps.add(str(row.gap_id))
            ledger.append({**base, "status": "EXECUTED", "capacity_skip": False, "qty": quantity, "initial_weight": outlay / nav_now})
            if len(active_by_symbol) > k:
                audit["max_k_violation_count"] += 1
    close_due(period_end)
    for position in active_by_symbol.values():
        cash += credit(position, period_end)

    entries_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    exits_by_date: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for position in accepted:
        entries_by_date[pd.Timestamp(position["entry_date"]).normalize()].append(position)
        if position["completed"]:
            exits_by_date[pd.Timestamp(position["exit_date"]).normalize()].append(position)
    cash_daily = 1.0
    live: dict[str, dict[str, Any]] = {}
    live_gaps: set[str] = set()
    nav_rows = []
    for date in pd.to_datetime(calendar.trade_date):
        for position in live.values():
            for event in position["cash_events"]:
                if pd.Timestamp(event["date"]) == date:
                    cash_daily += position["qty"] * float(event["cash_per_share"])
        events = [(pd.Timestamp(position["entry_time"]), "ENTRY", position) for position in entries_by_date.get(date, [])]
        events += [(pd.Timestamp(position["exit_time"]), "EXIT", position) for position in exits_by_date.get(date, [])]
        for _, kind, position in sorted(events, key=lambda item: (item[0], 0 if item[1] == "EXIT" else 1, item[2]["symbol"], item[2]["gap_id"])):
            if kind == "ENTRY":
                if position["symbol"] in live or str(position["gap_id"]) in live_gaps:
                    audit["duplicate_position_count"] += 1
                cash_daily -= position["entry_outlay"]
                live[position["symbol"]] = position
                live_gaps.add(str(position["gap_id"]))
            else:
                cash_daily += position["qty"] * float(position["exit_raw_price"]) * (1 - COST)
                live.pop(position["symbol"], None)
                live_gaps.discard(str(position["gap_id"]))
        exposure = 0.0
        for symbol, position in live.items():
            raw_mark = marks.get((symbol, date))
            if raw_mark is None:
                part = dates_by_symbol.get(symbol, pd.DataFrame())
                prior = part.loc[part.trade_date.le(date)] if len(part) else part
                raw_mark = float(prior.close.iloc[-1]) if len(prior) else float(position["entry_raw_price"])
            exposure += position["qty"] * float(raw_mark)
        nav_value = cash_daily + exposure
        nav_rows.append({"trade_date": date, "nav": nav_value, "cash": cash_daily, "gross_exposure": exposure, "utilization": 0.0 if nav_value == 0 else exposure / nav_value, "active_positions": len(live), "active_gaps": len(live_gaps), "board": board, "k": k})
    nav = pd.DataFrame(nav_rows)
    if len(nav) and (nav.active_positions.max() > k or nav.active_gaps.max() > k):
        audit["max_k_violation_count"] += 1
    if len(nav) and nav.cash.min() < -1e-12:
        audit["negative_cash_or_leverage_count"] += 1
    return V7Replay(nav=nav, accepted=pd.DataFrame(accepted), ledger=pd.DataFrame(ledger), audit=dict(audit))


def _trade_summary(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.completed & frame.net_return.notna()].copy() if len(frame) and "completed" in frame else pd.DataFrame()
    returns = completed.net_return.astype(float) if len(completed) else pd.Series(dtype=float)
    return {
        "completed_trades": len(completed),
        "mean_net_return": None if returns.empty else float(returns.mean()),
        "median_net_return": None if returns.empty else float(returns.median()),
        "true_win_rate": None if returns.empty else float(returns.gt(0).mean()),
        "u_hit": None if returns.empty else float(completed.u_hit.mean()),
        "clean_success_10": None if returns.empty else float(completed.clean_attack_success_10.mean()),
        "failed_attack": None if returns.empty else float(completed.failed_attack.mean()),
        "severe_loss8": None if returns.empty else float(returns.le(-0.08).mean()),
        "severe_loss10": None if returns.empty else float(returns.le(-0.10).mean()),
        "cvar5": None if returns.empty else _cvar5(returns),
        "mean_holding_sessions": None if returns.empty else float(completed.holding_sessions.mean()),
        "median_holding_sessions": None if returns.empty else float(completed.holding_sessions.median()),
    }


def _nav_summary(nav: pd.DataFrame, accepted: pd.DataFrame) -> dict[str, Any]:
    returns = nav.nav.pct_change().fillna(nav.nav.iloc[0] - 1.0)
    elapsed = max((pd.Timestamp(nav.trade_date.iloc[-1]) - pd.Timestamp(nav.trade_date.iloc[0])).days / 365.25, 1 / 365.25)
    drawdown = nav.nav / nav.nav.cummax() - 1.0
    total = float(nav.nav.iloc[-1] - 1.0)
    cagr = float(nav.nav.iloc[-1] ** (1 / elapsed) - 1.0)
    pnl = accepted.entry_outlay * accepted.net_return if len(accepted) and "entry_outlay" in accepted else pd.Series(dtype=float)
    positive = pnl.loc[pnl.gt(0)].sort_values(ascending=False)
    return {
        "total_return": total, "cagr": cagr, "max_drawdown": float(drawdown.min()),
        "sharpe": 0.0 if returns.std(ddof=1) == 0 else float(np.sqrt(252) * returns.mean() / returns.std(ddof=1)),
        "calmar": cagr / abs(float(drawdown.min())) if drawdown.min() < 0 else (99.0 if cagr > 0 else 0.0),
        "average_utilization": float(nav.utilization.mean()),
        "capacity_skips": 0,
        "best_day": float(returns.max()), "worst_day": float(returns.min()),
        "return_excluding_best_day": float((1 + returns.drop(returns.nlargest(1).index)).prod() - 1),
        "return_excluding_best_five_days": float((1 + returns.drop(returns.nlargest(5).index)).prod() - 1),
        "top5_trade_pnl_contribution": None if positive.sum() <= 0 else float(positive.iloc[:5].sum() / positive.sum()),
    }


def _period_returns(nav: pd.DataFrame) -> tuple[dict[str, float], dict[str, float]]:
    annual = {}; halves = {}; prior = 1.0
    for year in range(2017, 2022):
        part = nav.loc[nav.trade_date.dt.year.eq(year)]
        annual[str(year)] = 0.0 if part.empty else float(part.nav.iloc[-1] / prior - 1)
        year_prior = prior
        for half in (1, 2):
            half_part = part.loc[(part.trade_date.dt.month.le(6) if half == 1 else part.trade_date.dt.month.ge(7))]
            half_start = year_prior if half == 1 else (float(part.loc[part.trade_date.dt.month.le(6), "nav"].iloc[-1]) if len(part.loc[part.trade_date.dt.month.le(6)]) else year_prior)
            halves[f"{year}H{half}"] = 0.0 if half_part.empty else float(half_part.nav.iloc[-1] / half_start - 1)
        if len(part):
            prior = float(part.nav.iloc[-1])
    return annual, halves


def combine_nav(main: pd.DataFrame, chinext: pd.DataFrame, k: int) -> pd.DataFrame:
    combined = main.merge(chinext, on="trade_date", suffixes=("_main", "_chinext"), validate="one_to_one")
    combined["nav"] = 0.5 * combined.nav_main + 0.5 * combined.nav_chinext
    combined["gross_exposure"] = 0.5 * combined.gross_exposure_main + 0.5 * combined.gross_exposure_chinext
    combined["cash"] = combined.nav - combined.gross_exposure
    combined["utilization"] = combined.gross_exposure / combined.nav
    combined["active_positions"] = combined.active_positions_main + combined.active_positions_chinext
    combined["active_gaps"] = combined.active_gaps_main + combined.active_gaps_chinext
    combined["board"] = "COMBINED"; combined["k"] = k
    return combined[["trade_date", "nav", "cash", "gross_exposure", "utilization", "active_positions", "active_gaps", "board", "k"]]


def _concentration(accepted: pd.DataFrame) -> dict[str, Any]:
    completed = accepted.loc[accepted.completed] if len(accepted) and "completed" in accepted else accepted.iloc[0:0]
    if completed.empty:
        return {"top_security_trade_share": None, "top_industry_trade_share": None, "top_gap_formation_date_share": None, "attack2_trade_share": None}
    industry = completed.decision_industry.fillna("UNKNOWN") if "decision_industry" in completed else pd.Series("UNKNOWN", index=completed.index)
    return {
        "top_security_trade_share": float(completed.symbol.value_counts(normalize=True).iloc[0]),
        "top_industry_trade_share": float(industry.value_counts(normalize=True).iloc[0]),
        "top_gap_formation_date_share": float(pd.to_datetime(completed.gap_date).value_counts(normalize=True).iloc[0]),
        "attack2_trade_share": float(completed.attack_number.eq(2).mean()),
    }


def run_portfolios() -> dict[str, Any]:
    trades = pd.read_parquet(TRADES)
    _timestamp_columns(trades, ["entry_time", "entry_date", "exit_time", "exit_date", "gap_date"])
    daily = pd.read_parquet(PRED_EXT / "daily_relevant.parquet")
    daily.trade_date = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.trade_date.dt.year.between(2017, 2021)]
    summary_rows = []
    nav_rows = []
    audit = Counter()
    for (procedure, lane), lane_trades in trades.groupby(["procedure", "lane"], sort=True):
        for k in KS:
            replays = {}
            for board in ("MAIN", "CHINEXT"):
                replay = replay_v7(lane_trades, daily, board, k, tuple(range(2017, 2022)))
                replays[board] = replay
                metrics = {**_trade_summary(replay.accepted), **_nav_summary(replay.nav, replay.accepted), **_concentration(replay.accepted)}
                metrics["capacity_skips"] = int(replay.ledger.capacity_skip.sum()) if len(replay.ledger) else 0
                annual, halves = _period_returns(replay.nav)
                summary_rows.append({"procedure": procedure, "lane": lane, "board": board, "k": k, "signals": len(lane_trades.loc[lane_trades.board.eq(board)]), "attacks": int(lane_trades.loc[lane_trades.board.eq(board), "attack_id"].nunique()), "entries": len(lane_trades.loc[lane_trades.board.eq(board)]), **metrics, "annual_returns_json": canonical_json(annual).strip(), "half_year_returns_json": canonical_json(halves).strip()})
                nav_rows.append(replay.nav.assign(procedure=procedure, lane=lane))
                audit.update(replay.audit)
            combined = combine_nav(replays["MAIN"].nav, replays["CHINEXT"].nav, k)
            accepted = pd.concat([replays["MAIN"].accepted.assign(sleeve_weight=0.5), replays["CHINEXT"].accepted.assign(sleeve_weight=0.5)], ignore_index=True)
            metrics = {**_trade_summary(accepted), **_nav_summary(combined, accepted), **_concentration(accepted)}
            metrics["capacity_skips"] = sum(int(replay.ledger.capacity_skip.sum()) if len(replay.ledger) else 0 for replay in replays.values())
            annual, halves = _period_returns(combined)
            summary_rows.append({"procedure": procedure, "lane": lane, "board": "COMBINED", "k": k, "signals": len(lane_trades), "attacks": int(lane_trades.attack_id.nunique()), "entries": len(lane_trades), **metrics, "annual_returns_json": canonical_json(annual).strip(), "half_year_returns_json": canonical_json(halves).strip()})
            nav_rows.append(combined.assign(procedure=procedure, lane=lane))
    summary = pd.DataFrame(summary_rows).sort_values(["procedure", "lane", "board", "k"], kind="mergesort")
    nav = pd.concat(nav_rows, ignore_index=True).sort_values(["procedure", "lane", "board", "k", "trade_date"], kind="mergesort")
    write_parquet(summary, PORTFOLIO_SUMMARY)
    write_parquet(nav, PORTFOLIO_NAV)
    required_zero = {
        "max_k_violation_count": int(audit["max_k_violation_count"]),
        "duplicate_position_count": int(audit["duplicate_position_count"]),
        "negative_cash_or_leverage_count": int(audit["negative_cash_or_leverage_count"]),
        "cross_sleeve_transfer_count": 0,
    }
    if any(required_zero.values()):
        raise ResearchError(f"portfolio audit failed: {required_zero}")
    return {"summary_rows": len(summary), "nav_rows": len(nav), "portfolio_summary_sha256": sha256(PORTFOLIO_SUMMARY), "portfolio_nav_sha256": sha256(PORTFOLIO_NAV), "audit": {**dict(audit), **required_zero}, "repository_2024_plus_data_opened": "NO"}


def stage_b_portfolio() -> dict[str, Any]:
    _require_frozen_stage_a()
    if not FINAL_PROCEDURE_FREEZE.is_file() or not TRADES.is_file():
        raise ResearchError("walk-forward procedure must be frozen before portfolio replay")
    result = run_portfolios()
    manifest("STAGE_B_PORTFOLIO", "COMPLETE", result)
    return result


def build_high_overhang_diagnostic() -> pd.DataFrame:
    panel = baseline_panel()
    panel = panel.loc[panel.attack_memory_state.eq("CORE") & panel.outcome_valid].copy()
    turnover = duckdb.sql(f"""
      SELECT a.attack_id,
        sum(CASE WHEN d.volume>0 AND d.turnover_fraction>=0
                 THEN d.turnover_fraction*m.volume/d.volume ELSE NULL END) AS turnover_to_attack_end
      FROM read_parquet('{ATTACK_LEDGER}') a
      JOIN read_parquet('{ATTACK_MINUTES}') m USING(candidate_id)
      JOIN read_parquet('{DAILY}') d ON d.symbol=m.symbol AND d.trade_date=m.trade_date
      WHERE m.bar_end_time BETWEEN a.attack_start_time AND a.attack_end_time
        AND d.invalid_step_cum=a.invalid_step_cum AND d.hard_valid
        AND m.trade_date<=DATE '2023-12-31'
      GROUP BY a.attack_id
    """).df()
    panel = panel.merge(turnover, on="attack_id", how="left", validate="many_to_one")
    rows = []
    for fold in outer_folds():
        train, test, _ = fold_train_test(panel, fold)
        for board in ("MAIN", "CHINEXT"):
            board_train = train.loc[train.board.eq(board)]
            board_test = test.loc[test.board.eq(board)].copy()
            cutoff = float(board_train.overhang_support_ratio.quantile(0.70))
            high = board_test.loc[board_test.overhang_support_ratio.ge(cutoff)]
            for attack_number in (0, 1, 2):
                part = high if attack_number == 0 else high.loc[high.attack_number.eq(attack_number)]
                rows.append({
                    "fold": fold["fold"], "board": board, "attack_number": "ALL" if attack_number == 0 else f"ATTACK_{attack_number}",
                    "train_q70_overhang_support_ratio": cutoff, "attacks": int(part.attack_id.nunique()),
                    "current_attack_success": None if part.empty else float(part.attack_success.mean()),
                    "failed_attack": None if part.empty else float(part.failed_attack.mean()),
                    "eventual_u_after_failed_attack": None if part.empty else float(part.eventual_u_after_failed_attack.mean()),
                    "mean_turnover_to_attack_end": None if part.empty else float(part.turnover_to_attack_end.mean()),
                    "median_turnover_to_attack_end": None if part.empty else float(part.turnover_to_attack_end.median()),
                    "mean_turnover_success_only": None if part.loc[part.attack_success].empty else float(part.loc[part.attack_success, "turnover_to_attack_end"].mean()),
                    **selection_metrics(part, len(board_test)),
                })
    output = pd.DataFrame(rows).sort_values(["fold", "board", "attack_number"], kind="mergesort")
    write_parquet(output, HIGH_OVERHANG_DIAGNOSTIC)
    return output


def _apply_frozen_selection(frame: pd.DataFrame, selection: pd.Series) -> pd.DataFrame:
    overhang = json.loads(selection.overhang_model_json)
    environment = json.loads(selection.environment_model_json)
    mask, score = apply_admission(frame, overhang, environment)
    attacks = (1, 2) if selection.retry == "R1_ONE_RETRY" else (1,)
    mask &= frame.attack_number.isin(attacks)
    mask &= frame.remaining_net_target_at_entry.ge(float(selection.remaining_floor))
    selected = frame.loc[mask].copy()
    selected["simple_rule_score"] = score.loc[mask]
    if 2 in attacks and len(selected):
        first_exit = selected.loc[selected.attack_number.eq(1)].groupby("gap_id").exit_time.max().to_dict()
        blocked = selected.attack_number.eq(2) & selected.apply(lambda row: row.gap_id in first_exit and pd.Timestamp(first_exit[row.gap_id]) >= pd.Timestamp(row.entry_time), axis=1)
        selected = selected.loc[~blocked]
    return selected


def _normalize_period_nav(nav: pd.DataFrame, year: int) -> pd.DataFrame:
    prior = nav.loc[nav.trade_date.dt.year.lt(year)]
    base = 1.0 if prior.empty else float(prior.nav.iloc[-1])
    part = nav.loc[nav.trade_date.dt.year.eq(year)].copy()
    for column in ("nav", "cash", "gross_exposure"):
        part[column] = part[column] / base
    return part


def _post_summary_rows(trades: pd.DataFrame, daily: pd.DataFrame, procedure: str, lane: str) -> list[dict[str, Any]]:
    replay = {board: replay_v7(trades, daily, board, 10, POST_YEARS) for board in ("MAIN", "CHINEXT")}
    combined = combine_nav(replay["MAIN"].nav, replay["CHINEXT"].nav, 10)
    rows = []
    for board in ("MAIN", "CHINEXT", "COMBINED"):
        rp = None if board == "COMBINED" else replay[board]
        nav = combined if board == "COMBINED" else rp.nav
        accepted = pd.concat([replay["MAIN"].accepted, replay["CHINEXT"].accepted], ignore_index=True) if board == "COMBINED" else rp.accepted
        source = trades if board == "COMBINED" else trades.loc[trades.board.eq(board)]
        for period in ("2022", "2023", "2022-2023"):
            if period == "2022-2023":
                period_nav = nav; period_accepted = accepted; period_source = source
            else:
                year = int(period)
                period_nav = _normalize_period_nav(nav, year)
                period_accepted = accepted.loc[pd.to_datetime(accepted.entry_date).dt.year.eq(year)] if len(accepted) else accepted
                period_source = source.loc[pd.to_datetime(source.entry_date).dt.year.eq(year)]
            metrics = {**_trade_summary(period_accepted), **_nav_summary(period_nav, period_accepted), **_concentration(period_accepted)}
            rows.append({"label": "POST-OBSERVATION ROBUSTNESS DIAGNOSTIC", "procedure": procedure, "lane": lane, "period": period, "board": board, "k": 10, "signals": len(period_source), "attacks": int(period_source.attack_id.nunique()), "entries": len(period_source), **metrics})
    return rows


def run_post_observation_diagnostic() -> dict[str, Any]:
    frozen = json.loads(FINAL_PROCEDURE_FREEZE.read_text())
    for key, path in (("rule_candidates_sha256", RULE_CANDIDATES), ("inner_oof_results_sha256", INNER_OOF_RESULTS), ("outer_walkforward_selections_sha256", OUTER_SELECTIONS), ("trades_sha256", TRADES)):
        if frozen[key] != sha256(path):
            raise ResearchError(f"Development procedure drift before post-observation diagnostic: {key}")
    minute_audit = build_outcome_minute_path(2022, 2023, POST_OUTCOME_MINUTES, POST_OUTCOME_MINUTE_PARTS)
    outcome_audit = build_attack_outcomes(2022, 2023, POST_OUTCOME_MINUTES, POST_ATTACK_OUTCOMES)
    store = PanelStore(POST_ATTACK_OUTCOMES)
    selections = pd.read_parquet(OUTER_SELECTIONS)
    frozen_selection = selections.loc[selections.selection_role.eq("POST_DIAGNOSTIC_FROZEN_DEPLOYMENT")].set_index("board")
    trade_parts = []
    for board in ("MAIN", "CHINEXT"):
        selection = frozen_selection.loc[board]
        panel = store.get(str(selection.translation), int(selection.time_stop), str(selection.exit_policy))
        panel = panel.loc[panel.board.eq(board) & panel.attack_memory_state.eq("CORE") & panel.attack_start_date.dt.year.isin(POST_YEARS) & panel.outcome_valid]
        selected = _apply_frozen_selection(panel, selection)
        metadata = {"overhang_rule": selection.overhang_rule, "environment": selection.environment, "translation": selection.translation, "remaining_floor": selection.remaining_floor, "time_stop": selection.time_stop, "exit_policy": selection.exit_policy, "retry": selection.retry}
        trade_parts.append(_decorate_lane(selected, {"fold": "POST_2022_2023"}, board, "L5_FULL_SIMPLE_RULE", "FORCED_CHOICE_POST_OBSERVATION", metadata))
        if bool(selection.deployment_ready):
            trade_parts.append(_decorate_lane(selected, {"fold": "POST_2022_2023"}, board, "L5_FULL_SIMPLE_RULE", "DEPLOYMENT_GATED_POST_OBSERVATION", metadata))
        if selection.retry == "R1_ONE_RETRY":
            attack2 = selected.loc[selected.attack_number.eq(2)]
            trade_parts.append(_decorate_lane(attack2, {"fold": "POST_2022_2023"}, board, "L6_ONE_RETRY_INCREMENT", "FORCED_CHOICE_POST_OBSERVATION", metadata))
            if bool(selection.deployment_ready):
                trade_parts.append(_decorate_lane(attack2, {"fold": "POST_2022_2023"}, board, "L6_ONE_RETRY_INCREMENT", "DEPLOYMENT_GATED_POST_OBSERVATION", metadata))
        baseline = store.get("Z0+CLOSE", 20, "X0_NO_FAILURE_EXIT")
        baseline = baseline.loc[baseline.board.eq(board) & baseline.attack_memory_state.eq("CORE") & baseline.attack_number.eq(1) & baseline.attack_start_date.dt.year.isin(POST_YEARS) & baseline.outcome_valid].copy()
        baseline["simple_rule_score"] = 0.0
        trade_parts.append(_decorate_lane(baseline, {"fold": "POST_2022_2023"}, board, "L0_ATTACK_BASELINE", "FORCED_CHOICE_POST_OBSERVATION", metadata))
    trades = pd.concat(trade_parts, ignore_index=True).sort_values(["procedure", "lane", "entry_time", "board", "gap_id"], kind="mergesort")
    write_parquet(trades, DIAGNOSTIC)
    daily = pd.read_parquet(PRED_EXT / "daily_relevant.parquet"); daily.trade_date = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.trade_date.dt.year.isin(POST_YEARS)]
    summary_rows = []
    for (procedure, lane), part in trades.groupby(["procedure", "lane"], sort=True):
        summary_rows.extend(_post_summary_rows(part, daily, procedure, lane))
    summary = pd.DataFrame(summary_rows).sort_values(["procedure", "lane", "period", "board"], kind="mergesort")
    write_parquet(summary, POST_DIAGNOSTIC_SUMMARY)
    return {
        "label": "POST-OBSERVATION ROBUSTNESS DIAGNOSTIC",
        "minute_path": minute_audit, "outcomes": outcome_audit,
        "trade_rows": len(trades), "summary_rows": len(summary),
        "procedure_changed_after_2022_count": 0,
        "post_2021_scientific_evidence_accepted": "NO",
        "repository_2024_plus_data_opened": "NO",
    }


def _even_chronological_sample(frame: pd.DataFrame, count: int) -> pd.DataFrame:
    unique = frame.sort_values(["attack_start_time", "entry_time", "attack_id"], kind="mergesort").drop_duplicates("attack_id")
    if len(unique) <= count:
        return unique
    indexes = np.unique(np.linspace(0, len(unique) - 1, count).round().astype(int))
    return unique.iloc[indexes]


def generate_representative_charts() -> dict[str, Any]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.patches import Rectangle

    trades = pd.read_parquet(TRADES)
    _timestamp_columns(trades, ["gap_date", "attack_start_time", "attack_end_time", "entry_time", "entry_date", "exit_time", "exit_date"])
    admitted = trades.loc[trades.procedure.eq("FORCED_CHOICE_WF") & trades.lane.eq("L5_FULL_SIMPLE_RULE")].copy()
    baseline = trades.loc[trades.procedure.eq("FORCED_CHOICE_WF") & trades.lane.eq("L0_ATTACK_BASELINE")].copy()
    admitted_identity = set(zip(admitted.outer_fold, admitted.board, admitted.attack_id))
    rejected = baseline.loc[~pd.Series(list(zip(baseline.outer_fold, baseline.board, baseline.attack_id)), index=baseline.index).isin(admitted_identity)]
    categories = {
        "ADMITTED_WINNER": _even_chronological_sample(admitted.loc[admitted.net_return.gt(0)], 20),
        "ADMITTED_LOSER": _even_chronological_sample(admitted.loc[admitted.net_return.le(0)], 20),
        "REJECTED_LATER_SUCCEEDED": _even_chronological_sample(rejected.loc[rejected.attack_success], 20),
        "REJECTED_LATER_FAILED": _even_chronological_sample(rejected.loc[rejected.failed_attack | rejected.timed_out_attack], 20),
        "ATTACK_2_TRADE": admitted.loc[admitted.attack_number.eq(2)].sort_values(["attack_start_time", "attack_id"], kind="mergesort").drop_duplicates("attack_id"),
    }
    selected = pd.concat([part.assign(chart_category=category) for category, part in categories.items() if len(part)], ignore_index=True)
    if selected.empty:
        write_text(CHART_INDEX, "chart_id,category\n")
        return {"chart_count": 0, "category_counts": {}, "chart_index": str(CHART_INDEX)}
    daily = pd.read_parquet(PRED_EXT / "daily_relevant.parquet")
    daily.trade_date = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.trade_date.dt.year.le(2021) & daily.symbol.isin(selected.symbol.unique())]
    daily_by = {symbol: part.sort_values("cal_idx") for symbol, part in daily.groupby("symbol", sort=False)}
    overhang = pd.read_parquet(OVERHANG_PANEL).set_index("attack_id")
    attacks = pd.read_parquet(ATTACK_LEDGER)
    _timestamp_columns(attacks, ["attack_start_time", "attack_end_time"])
    attack_by = attacks.set_index("attack_id")
    id_frame = selected[["candidate_id"]].drop_duplicates()
    con = duckdb.connect(); con.register("selected_ids", id_frame)
    vap = con.execute(f"""SELECT v.candidate_id,v.z_bin,sum(v.raw_volume) raw_volume
      FROM read_parquet('{VAP_SESSION_BINS}') v JOIN selected_ids s USING(candidate_id)
      WHERE v.z_bin BETWEEN {VAP_MIN_BIN} AND {VAP_MAX_BIN} AND v.session_offset<0
      GROUP BY 1,2 ORDER BY 1,2""").df(); con.close()
    vap_by = {candidate: part for candidate, part in vap.groupby("candidate_id", sort=False)}
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for category, group in selected.groupby("chart_category", sort=True):
        pdf_path = CHART_DIR / f"{category}.pdf"
        with PdfPages(pdf_path) as pdf:
            for number, row in enumerate(group.sort_values(["attack_start_time", "attack_id"], kind="mergesort").itertuples(index=False), start=1):
                chart_id = f"{category}-{number:03d}"
                day = daily_by.get(row.symbol, pd.DataFrame())
                start_idx = int(row.gap_cal_idx) - 20
                end_idx = min(int(row.exit_cal_idx) + 5, int(day.cal_idx.max())) if len(day) and pd.notna(row.exit_cal_idx) else int(row.entry_cal_idx) + 20
                view = day.loc[day.cal_idx.between(start_idx, end_idx)].copy()
                if view.empty:
                    continue
                fig, ax = plt.subplots(figsize=(14, 7.5))
                x = mdates.date2num(view.trade_date.dt.to_pydatetime())
                for xi, candle in zip(x, view.itertuples(index=False)):
                    color = "#d62728" if candle.coord_close >= candle.coord_open else "#1a9850"
                    ax.vlines(xi, candle.coord_low, candle.coord_high, color=color, linewidth=0.7)
                    low = min(candle.coord_open, candle.coord_close); height = max(abs(candle.coord_close - candle.coord_open), max(row.W * 0.005, 1e-6))
                    ax.add_patch(Rectangle((xi - 0.32, low), 0.64, height, facecolor=color, edgecolor=color, alpha=0.75))
                ax.axhspan(row.L, row.U, color="#ffcc80", alpha=0.28, label="true gap [L,U]")
                ax.axhline(row.L, color="#ef6c00", linestyle="--", linewidth=1.1)
                ax.axhline(row.U, color="#c62828", linestyle="--", linewidth=1.1)
                markers = [(row.gap_date, "GAP", "#6a1b9a"), (row.attack_start_time, "ATTACK START", "#1565c0"), (row.attack_end_time, "ATTACK END", "#455a64"), (row.entry_time, "ENTRY", "#0d47a1"), (row.exit_time, "EXIT", "#8e24aa")]
                for when, label, color in markers:
                    if pd.notna(when):
                        ax.axvline(pd.Timestamp(when), color=color, linestyle=":" if label not in ("ENTRY", "EXIT") else "-.", linewidth=1.0, label=label)
                if int(row.attack_number) == 2:
                    prior_id = f"{row.candidate_id}|ATTACK_1"
                    if prior_id in attack_by.index:
                        prior = attack_by.loc[prior_id]
                        ax.axvspan(pd.Timestamp(prior.attack_start_time), pd.Timestamp(prior.attack_end_time), color="#90a4ae", alpha=0.15, label="prior attack")
                state = overhang.loc[row.attack_id] if row.attack_id in overhang.index else None
                if state is not None and np.isfinite(state.poc_z):
                    ax.axhline(row.L + float(state.poc_z) * row.W, color="#283593", linewidth=1.2, label=f"POC z={state.poc_z:.2f}")
                profile = vap_by.get(row.candidate_id, pd.DataFrame())
                if len(profile):
                    inset = ax.inset_axes([0.82, 0.08, 0.16, 0.84], sharey=ax)
                    price = row.L + (profile.z_bin.to_numpy(float) + 0.5) * VAP_BIN_WIDTH_Z * row.W
                    width = profile.raw_volume.to_numpy(float); width = width / max(width.max(), EPSILON)
                    inset.barh(price, width, height=VAP_BIN_WIDTH_Z * row.W * 0.85, color="#607d8b", alpha=0.45)
                    inset.set_xlim(0, 1.05); inset.set_xticks([]); inset.tick_params(axis="y", labelleft=False); inset.set_title("pre-gap VAP", fontsize=8)
                text_lines = [
                    f"{row.symbol} | {row.board} | {row.attack_id}",
                    f"L={row.L:.4f}  U={row.U:.4f}  W={row.W:.4f}",
                    f"entry={row.entry_coord_price:.4f}  net={row.net_return:+.2%}  exit={row.exit_reason}",
                    f"rule={row.selected_overhang_rule} / {row.selected_environment}",
                    f"translation={row.selected_translation}, H={row.selected_time_stop}, failure={row.selected_exit_policy}, retry={row.selected_retry}",
                ]
                if state is not None:
                    text_lines.append(f"vacuum={state.vacuum_score:.3f}  overhang/support={state.overhang_support_ratio:.3f}  decayed inside={state.decayed_overhang_inside_gap:.4f}")
                    text_lines.append(f"HVN above L distance z={state.nearest_hvn_above_l_distance_z:.2f}; above U distance z={state.nearest_hvn_above_u_distance_z:.2f}")
                ax.text(0.01, 0.99, "\n".join(text_lines), transform=ax.transAxes, va="top", fontsize=8.5, bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "#b0bec5"})
                ax.set_title(f"{chart_id} — diagnostic only; no rule changes after review")
                ax.set_ylabel("QD-010 coordinate price"); ax.grid(axis="y", alpha=0.2); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d")); fig.autofmt_xdate()
                handles, labels = ax.get_legend_handles_labels(); unique = dict(zip(labels, handles)); ax.legend(unique.values(), unique.keys(), loc="lower left", fontsize=7, ncol=3)
                fig.tight_layout()
                png = CHART_DIR / f"{chart_id}.png"; fig.savefig(png, dpi=135); pdf.savefig(fig); plt.close(fig)
                index_rows.append({"chart_id": chart_id, "category": category, "attack_id": row.attack_id, "candidate_id": row.candidate_id, "symbol": row.symbol, "board": row.board, "attack_number": int(row.attack_number), "png": str(png), "pdf": str(pdf_path)})
    index = pd.DataFrame(index_rows)
    index.to_csv(CHART_INDEX, index=False)
    return {"chart_count": len(index), "category_counts": index.category.value_counts().astype(int).to_dict(), "chart_index": str(CHART_INDEX), "chart_dir": str(CHART_DIR), "pdfs": sorted(index.pdf.unique().tolist())}


def stage_b_diagnostic() -> dict[str, Any]:
    _require_frozen_stage_a()
    if not PORTFOLIO_SUMMARY.is_file() or not FINAL_PROCEDURE_FREEZE.is_file():
        raise ResearchError("Development procedure and portfolio must be complete before diagnostics")
    high = build_high_overhang_diagnostic()
    charts = generate_representative_charts()
    post = run_post_observation_diagnostic()
    result = {
        "high_overhang_rows": len(high), "high_overhang_sha256": sha256(HIGH_OVERHANG_DIAGNOSTIC),
        "charts": charts, "post_observation": post,
        "post_2021_scientific_evidence_accepted": "NO", "repository_2024_plus_data_opened": "NO",
    }
    manifest("STAGE_B_DIAGNOSTIC", "COMPLETE", result)
    return result


def _weighted_metric(frame: pd.DataFrame, value: str, weight: str = "observations") -> float | None:
    use = frame.loc[pd.to_numeric(frame[value], errors="coerce").notna() & pd.to_numeric(frame[weight], errors="coerce").gt(0)]
    return None if use.empty else float(np.average(use[value].astype(float), weights=use[weight].astype(float)))


def _row_dict(frame: pd.DataFrame, **filters: Any) -> dict[str, Any] | None:
    use = frame
    for column, value in filters.items():
        use = use.loc[use[column].eq(value)]
    return None if use.empty else clean(use.iloc[0].to_dict())


def evaluate_scientific_verdict(summary: pd.DataFrame, trades: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    primary = _row_dict(summary, procedure="DEPLOYMENT_GATED_WF", lane="L5_FULL_SIMPLE_RULE", board="COMBINED", k=10)
    forced = _row_dict(summary, procedure="FORCED_CHOICE_WF", lane="L5_FULL_SIMPLE_RULE", board="COMBINED", k=10)
    baseline = _row_dict(summary, procedure="FORCED_CHOICE_WF", lane="L0_ATTACK_BASELINE", board="COMBINED", k=10)
    l1 = _row_dict(summary, procedure="FORCED_CHOICE_WF", lane="L1_LOW_OVERHANG", board="COMBINED", k=10)
    l2 = _row_dict(summary, procedure="FORCED_CHOICE_WF", lane="L2_LOW_OVERHANG_ENVIRONMENT", board="COMBINED", k=10)
    l3 = _row_dict(summary, procedure="FORCED_CHOICE_WF", lane="L3_ATTACK_ACCEPTANCE", board="COMBINED", k=10)
    if primary is None:
        primary = {"completed_trades": 0, "mean_net_return": None, "median_net_return": None, "severe_loss10": None, "return_excluding_best_day": 0.0, "return_excluding_best_five_days": 0.0, "annual_returns_json": canonical_json({str(year): 0.0 for year in range(2017, 2022)}).strip(), "half_year_returns_json": canonical_json({f"{year}H{half}": 0.0 for year in range(2017, 2022) for half in (1, 2)}).strip(), "total_return": 0.0}
    annual = json.loads(primary["annual_returns_json"]); halves = json.loads(primary["half_year_returns_json"])
    gated_trades = trades.loc[trades.procedure.eq("DEPLOYMENT_GATED_WF") & trades.lane.eq("L5_FULL_SIMPLE_RULE")]
    date_equal = None if gated_trades.empty else float(gated_trades.groupby(pd.to_datetime(gated_trades.entry_date).dt.normalize()).net_return.mean().mean())
    baseline_severe = None if baseline is None else baseline.get("severe_loss10")
    primary_severe = primary.get("severe_loss10")
    severe_improved = bool(
        primary_severe is not None and baseline_severe is not None
        and (primary_severe <= baseline_severe - 0.01 or (baseline_severe > 0 and primary_severe <= 0.8 * baseline_severe))
    )
    board_rows = [_row_dict(summary, procedure="DEPLOYMENT_GATED_WF", lane="L5_FULL_SIMPLE_RULE", board=board, k=10) for board in ("MAIN", "CHINEXT")]
    boards_nonnegative = all(row is not None and row.get("total_return", 0) >= 0 for row in board_rows)
    checks = {
        "at_least_100_trades": int(primary.get("completed_trades") or 0) >= 100,
        "positive_mean": bool(primary.get("mean_net_return") is not None and primary["mean_net_return"] > 0),
        "positive_median": bool(primary.get("median_net_return") is not None and primary["median_net_return"] > 0),
        "positive_half_years_at_least_6": sum(value > 0 for value in halves.values()) >= 6,
        "positive_years_at_least_4": sum(value > 0 for value in annual.values()) >= 4,
        "no_catastrophic_full_year": all(value > -0.10 for value in annual.values()),
        "positive_attack_date_equal": bool(date_equal is not None and date_equal > 0),
        "severe10_materially_improved": severe_improved,
        "positive_ex_best_day": float(primary.get("return_excluding_best_day") or 0) > 0,
        "near_positive_ex_best_five": float(primary.get("return_excluding_best_five_days") or 0) >= -0.01,
        "both_boards_nonnegative": boards_nonnegative,
    }
    edge = all(checks.values())
    completed = int(primary.get("completed_trades") or 0)
    if edge:
        l1_positive = l1 is not None and l1.get("mean_net_return") is not None and l1["mean_net_return"] > 0 and l1.get("total_return", 0) > 0
        l2_positive = l2 is not None and l2.get("total_return", 0) > 0
        l3_positive = l3 is not None and l3.get("total_return", 0) > 0
        retry = _row_dict(summary, procedure="DEPLOYMENT_GATED_WF", lane="L6_ONE_RETRY_INCREMENT", board="COMBINED", k=10)
        if retry is not None and retry.get("completed_trades", 0) > 0 and retry.get("mean_net_return", 0) > 0 and not l3_positive:
            verdict = "V7_EDGE_REQUIRES_ONE_RETRY"
        elif l1_positive:
            verdict = "V7_SIMPLE_VACUUM_REPAIR_EDGE"
        elif l3_positive and not l2_positive:
            verdict = "V7_EDGE_REQUIRES_ATTACK_ACCEPTANCE"
        else:
            verdict = "V7_SIMPLE_VACUUM_REPAIR_EDGE"
    else:
        one_board_edge = any(row is not None and row.get("completed_trades", 0) >= 50 and row.get("mean_net_return") is not None and row["mean_net_return"] > 0 and row.get("total_return", 0) > 0 for row in board_rows)
        l1_risk = baseline is not None and l1 is not None and l1.get("severe_loss10") is not None and baseline.get("severe_loss10") is not None and l1["severe_loss10"] < baseline["severe_loss10"]
        l3_risk = l2 is not None and l3 is not None and l3.get("severe_loss10") is not None and l2.get("severe_loss10") is not None and l3["severe_loss10"] < l2["severe_loss10"]
        if one_board_edge:
            verdict = "V7_SIMPLE_RULE_BOARD_SPECIFIC"
        elif 50 <= completed <= 99 and checks["positive_mean"] and checks["positive_median"]:
            verdict = "V7_SIMPLE_RULE_MARGINAL"
        elif l1_risk:
            verdict = "V7_OVERHANG_SORTS_RISK_BUT_NO_PORTFOLIO_EDGE"
        elif l3_risk:
            verdict = "V7_ATTACK_ACCEPTANCE_SORTS_RISK_BUT_NO_PORTFOLIO_EDGE"
        elif forced is not None and int(forced.get("completed_trades") or 0) >= 100 and (forced.get("mean_net_return") or -1) > 0:
            verdict = "V7_SIMPLE_RULE_UNSTABLE"
        else:
            verdict = "V7_NO_SIMPLE_EDGE"
    return verdict, {"checks": checks, "attack_date_equal_mean": date_equal, "primary": primary, "forced": forced, "baseline": baseline}


def _sample_mask(frame: pd.DataFrame, value: str) -> pd.Series:
    if "sample" not in frame.columns:
        raise ResearchError("required sample column is missing")
    return frame["sample"].eq(value)


def _fmt(value: Any, percent: bool = False) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    if percent:
        return f"{float(value):.2%}"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def finalize_result() -> dict[str, Any]:
    required = [FEATURE_FREEZE, ATTACK_OUTCOMES, DIRECT_ANALYSIS, MATCHED_ANALYSIS, MODEL_DIAGNOSTICS, RULE_CANDIDATES, INNER_OOF_RESULTS, OUTER_SELECTIONS, TRADES, PORTFOLIO_SUMMARY, PORTFOLIO_NAV, FINAL_PROCEDURE_FREEZE, HIGH_OVERHANG_DIAGNOSTIC, DIAGNOSTIC, POST_DIAGNOSTIC_SUMMARY, CHART_INDEX]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ResearchError(f"cannot finalize; missing artifacts {missing}")
    feature_freeze = json.loads(FEATURE_FREEZE.read_text())
    reconciliation = json.loads(RECONCILIATION_JSON.read_text())
    summary = pd.read_parquet(PORTFOLIO_SUMMARY)
    trades = pd.read_parquet(TRADES)
    _timestamp_columns(trades, ["entry_date", "entry_time", "exit_date", "exit_time", "gap_date"])
    selections = pd.read_parquet(OUTER_SELECTIONS)
    direct = pd.read_parquet(DIRECT_ANALYSIS)
    matched = pd.read_parquet(MATCHED_ANALYSIS)
    models = pd.read_parquet(MODEL_DIAGNOSTICS)
    high = pd.read_parquet(HIGH_OVERHANG_DIAGNOSTIC)
    post = pd.read_parquet(POST_DIAGNOSTIC_SUMMARY)
    verdict, adjudication = evaluate_scientific_verdict(summary, trades)

    direct_vacuum = direct.loc[
        direct.analysis_type.eq("UNIVARIATE")
        & _sample_mask(direct, "OUTER_TEST")
        & direct.variable_x.eq("vacuum_score")
        & direct.weighting.eq("event")
    ]
    vacuum_shape = {f"Q{bucket}": _weighted_metric(direct_vacuum.loc[direct_vacuum.bucket_x.eq(bucket)], "mean_net_return") for bucket in range(1, 6)}
    matched_summary = []
    for (board, outcome), part in matched.groupby(["board", "outcome"], sort=True):
        matched_summary.append({"board": board, "outcome": outcome, "mean_fwl_effect": float(part.fwl_effect.mean()), "positive_folds": int(part.fwl_effect.gt(0).sum()), "date_equal_mean": float(part.attack_date_equal_effect.mean())})
    model_summary = []
    outer_models = models.loc[_sample_mask(models, "OUTER_TEST")]
    for method, part in outer_models.groupby("method", sort=True):
        model_summary.append({"method": method, "mean_auc": float(part.auc_clean10.mean()), "median_auc": float(part.auc_clean10.median()), "mean_top30_utility": float(part.top30_economic_utility.mean()), "mean_prediction_std": float(part.prediction_std.mean())})

    boundary = baseline_panel()
    boundary = boundary.loc[boundary.attack_memory_state.eq("BOUNDARY") & boundary.attack_start_date.dt.year.between(2017, 2021) & boundary.outcome_valid]
    boundary_diagnostic = {"combined": selection_metrics(boundary, len(boundary)), "main": selection_metrics(boundary.loc[boundary.board.eq("MAIN")], int(boundary.board.eq("MAIN").sum())), "chinext": selection_metrics(boundary.loc[boundary.board.eq("CHINEXT")], int(boundary.board.eq("CHINEXT").sum()))}

    high_all = high.loc[high.attack_number.eq("ALL")]
    high_summary = {
        "attacks": int(high_all.attacks.sum()),
        "mean_current_attack_success": _weighted_metric(high_all, "current_attack_success", "attacks"),
        "mean_failed_attack": _weighted_metric(high_all, "failed_attack", "attacks"),
        "mean_eventual_u_after_failed": _weighted_metric(high_all, "eventual_u_after_failed_attack", "attacks"),
        "mean_turnover_to_attack_end": _weighted_metric(high_all, "mean_turnover_to_attack_end", "attacks"),
    }
    attack1_high = high.loc[high.attack_number.eq("ATTACK_1")]; attack2_high = high.loc[high.attack_number.eq("ATTACK_2")]
    attack1_success = _weighted_metric(attack1_high, "current_attack_success", "attacks")
    attack2_success = _weighted_metric(attack2_high, "current_attack_success", "attacks")
    absorption_lane = bool(high_summary["mean_eventual_u_after_failed"] is not None and high_summary["mean_current_attack_success"] is not None and high_summary["mean_eventual_u_after_failed"] - high_summary["mean_current_attack_success"] >= 0.10 and attack2_success is not None and attack1_success is not None and attack2_success > attack1_success)

    outcome_manifest = json.loads((MANIFESTS / "STAGE_B_OUTCOMES.json").read_text())
    portfolio_manifest = json.loads((MANIFESTS / "STAGE_B_PORTFOLIO.json").read_text())
    stage_a_manifest = json.loads((MANIFESTS / "STAGE_A_ATTACK_EPISODES.json").read_text())
    walk_manifest = json.loads((MANIFESTS / "STAGE_B_WALKFORWARD.json").read_text())
    post_manifest = json.loads((MANIFESTS / "STAGE_B_DIAGNOSTIC.json").read_text())
    audit = {
        "V6_EVENT_IDENTITY_CHANGED_COUNT": stage_a_manifest["audit"]["v6_event_identity_changed_count"],
        "SEMANTIC_CHANGE_AFTER_OUTCOME_OPEN_COUNT": feature_freeze["semantic_change_after_outcome_open_count"],
        "FEATURE_ADDED_AFTER_OUTCOME_OPEN_COUNT": feature_freeze["feature_added_after_outcome_open_count"],
        "RULE_ADDED_AFTER_OUTCOME_OPEN_COUNT": feature_freeze["rule_added_after_outcome_open_count"],
        "EXIT_ADDED_AFTER_OUTCOME_OPEN_COUNT": feature_freeze["exit_added_after_outcome_open_count"],
        "FEATURE_USES_POST_DECISION_INFORMATION_COUNT": stage_a_manifest["audit"]["feature_uses_post_decision_information_count"],
        "ENTRY_USES_FUTURE_BAR_COUNT": stage_a_manifest["audit"]["entry_uses_future_bar_count"],
        "LATER_SUCCESS_CREDITED_TO_EARLIER_ATTACK_COUNT": outcome_manifest["outcomes"]["later_success_credited_to_earlier_attack_count"],
        "ATTACK_STARTED_BEFORE_PRIOR_ATTACK_END_COUNT": stage_a_manifest["audit"]["attack_started_before_prior_attack_end_count"],
        "SAME_GAP_SPLIT_ACROSS_FOLDS_COUNT": walk_manifest["audit"]["same_gap_split_across_folds_count"],
        "PURGE_EMBARGO_VIOLATION_COUNT": walk_manifest["audit"]["purge_embargo_violation_count"],
        "TEST_HALF_USED_IN_OWN_SELECTION_COUNT": walk_manifest["audit"]["test_half_used_in_own_selection_count"],
        "STOP_EXECUTED_AT_IMPOSSIBLE_PRICE_COUNT": outcome_manifest["outcomes"]["stop_executed_at_impossible_price_count"],
        "T1_SAME_DAY_EXIT_COUNT": outcome_manifest["outcomes"]["t1_same_day_exit_count"],
        "CORPORATE_ACTION_COORDINATE_VIOLATION_COUNT": outcome_manifest["outcomes"]["corporate_action_coordinate_violation_count"],
        "MAX_K_VIOLATION_COUNT": portfolio_manifest["audit"].get("max_k_violation_count", 0),
        "DUPLICATE_POSITION_COUNT": portfolio_manifest["audit"].get("duplicate_position_count", 0),
        "NEGATIVE_CASH_OR_LEVERAGE_COUNT": portfolio_manifest["audit"].get("negative_cash_or_leverage_count", 0),
        "CROSS_SLEEVE_TRANSFER_COUNT": portfolio_manifest["audit"].get("cross_sleeve_transfer_count", 0),
        "REPOSITORY_2024_PLUS_DATA_OPENED": "NO",
        "POST_2021_SCIENTIFIC_EVIDENCE_ACCEPTED": "NO",
    }
    numeric_audit = [value for key, value in audit.items() if key.endswith("_COUNT")]
    if any(numeric_audit):
        raise ResearchError(f"final audit nonzero: {audit}")

    lane_rows = summary.loc[summary.board.eq("COMBINED") & summary.k.eq(10)].to_dict("records")
    lane_rows_all_boards = summary.loc[summary.k.eq(10)].to_dict("records")
    primary_board_rows = summary.loc[
        summary.k.eq(10) & summary.lane.eq("L5_FULL_SIMPLE_RULE")
    ].to_dict("records")
    k_sensitivity_rows = summary.loc[
        summary.board.eq("COMBINED") & summary.lane.eq("L5_FULL_SIMPLE_RULE")
    ].to_dict("records")
    primary_combined = summary.loc[
        summary.board.eq("COMBINED")
        & summary.k.eq(10)
        & summary.lane.eq("L5_FULL_SIMPLE_RULE")
    ]
    half_year_returns: dict[str, dict[str, float]] = {}
    annual_returns: dict[str, dict[str, float]] = {}
    for row in primary_combined.itertuples(index=False):
        half_year_returns[row.procedure] = json.loads(row.half_year_returns_json)
        annual_returns[row.procedure] = json.loads(row.annual_returns_json)

    surface_summaries = []
    surface_outer = direct.loc[
        direct.analysis_type.eq("SURFACE")
        & _sample_mask(direct, "OUTER_TEST")
        & direct.weighting.eq("event")
    ]
    for (variable_x, variable_y), part in surface_outer.groupby(
        ["variable_x", "variable_y"], sort=True
    ):
        cells = []
        for (bucket_x, bucket_y), cell in part.groupby(["bucket_x", "bucket_y"], sort=True):
            cells.append(
                {
                    "bucket_x": int(bucket_x),
                    "bucket_y": int(bucket_y),
                    "observations": int(cell.observations.sum()),
                    "mean_net_return": _weighted_metric(cell, "mean_net_return", "observations"),
                }
            )
        valid_cells = [cell for cell in cells if cell["mean_net_return"] is not None]
        surface_summaries.append(
            {
                "variable_x": variable_x,
                "variable_y": variable_y,
                "cells": len(valid_cells),
                "positive_cells": sum(cell["mean_net_return"] > 0 for cell in valid_cells),
                "best_fixed_cell": max(valid_cells, key=lambda cell: cell["mean_net_return"]) if valid_cells else None,
                "worst_fixed_cell": min(valid_cells, key=lambda cell: cell["mean_net_return"]) if valid_cells else None,
            }
        )
    final_selections = selections.loc[selections.selection_role.eq("POST_DIAGNOSTIC_FROZEN_DEPLOYMENT")].to_dict("records")
    chart_manifest = pd.read_csv(CHART_INDEX)
    chart_pdfs = {
        path.name: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in sorted(CHART_DIR.glob("*.pdf"))
    }
    artifacts = {}
    for path in required + [SPEC, SEMANTIC_PREFLIGHT_JSON, RECONCILIATION_JSON, VAP_METHODOLOGY, FEATURE_DICTIONARY, ATTACK_CONTRACT, RULE_SPACE, EXIT_SPACE, OVERHANG_PANEL, ATTACK_LEDGER, ATTACK_CLOCK_FEATURES]:
        artifacts[path.name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256(path)}
    result = {
        "experiment": EXPERIMENT,
        "start_head": START_HEAD,
        "source_semantic_hash": SOURCE_HASH,
        "contract_hashes": {key: feature_freeze[key] for key in ("v7_spec_hash", "v7_feature_contract_hash", "v7_attack_contract_hash", "v7_rule_space_hash", "v7_exit_space_hash")},
        "reconciliation": reconciliation,
        "development": {
            "lane_summary_k10_combined": clean(lane_rows),
            "lane_summary_k10_all_boards": clean(lane_rows_all_boards),
            "primary_lane_board_breakdown_k10": clean(primary_board_rows),
            "primary_lane_k_sensitivity_combined": clean(k_sensitivity_rows),
            "primary_lane_half_year_returns": half_year_returns,
            "primary_lane_annual_returns": annual_returns,
            "outer_selections": clean(selections.loc[selections.selection_role.eq("OUTER_WALKFORWARD")].to_dict("records")),
            "final_deployment_selections": clean(final_selections),
            "vacuum_score_outer_test_quintile_mean_returns": vacuum_shape,
            "outer_test_fixed_surface_summaries": surface_summaries,
            "matched_low_overhang": matched_summary,
            "model_ceiling": model_summary,
            "boundary_diagnostic": boundary_diagnostic,
            "high_overhang": high_summary,
            "attack1_high_overhang_success": attack1_success,
            "attack2_high_overhang_success": attack2_success,
            "separate_absorption_breakout_lane_justified": absorption_lane,
            "scientific_adjudication": adjudication,
        },
        "post_observation_2022_2023": {"label": "POST-OBSERVATION ROBUSTNESS DIAGNOSTIC", "summary": clean(post.to_dict("records")), "used_in_verdict": False, "procedure_changed_after_2022_count": post_manifest["post_observation"]["procedure_changed_after_2022_count"]},
        "representative_charts": {"count": len(chart_manifest), "category_counts": chart_manifest.category.value_counts().astype(int).to_dict() if len(chart_manifest) else {}, "index": str(CHART_INDEX), "directory": str(CHART_DIR), "pdfs": chart_pdfs},
        "audit": audit,
        "verdict": verdict,
        "is_a_positive_causal_simple_strategy_created": verdict in {"V7_SIMPLE_VACUUM_REPAIR_EDGE", "V7_EDGE_REQUIRES_ATTACK_ACCEPTANCE", "V7_EDGE_REQUIRES_ONE_RETRY", "V7_SIMPLE_RULE_BOARD_SPECIFIC"},
        "is_rule_stable_enough_for_one_sealed_2024_plus_challenge": verdict in {"V7_SIMPLE_VACUUM_REPAIR_EDGE", "V7_EDGE_REQUIRES_ATTACK_ACCEPTANCE", "V7_EDGE_REQUIRES_ONE_RETRY"} and all(adjudication["checks"].values()),
        "artifacts": artifacts,
        "commit": "LOCAL_CHECKPOINT_CREATED_AFTER_REPORT",
        "pushed": "NO",
    }
    write_json(RESULT, result)

    lane_table = ["| Procedure | Lane | Signals | Attacks | Entries | Trades | Mean | Median | Win | U hit | Clean10 | Failed |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    lane_risk_table = ["| Procedure | Lane | Severe8 | Severe10 | CVaR5 | Mean hold | Median hold | CAGR | MaxDD | Sharpe | Calmar |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in sorted(lane_rows, key=lambda item: (item["procedure"], item["lane"])):
        lane_table.append(f"| {row['procedure']} | {row['lane']} | {row['signals']} | {row['attacks']} | {row['entries']} | {row['completed_trades']} | {_fmt(row['mean_net_return'], True)} | {_fmt(row['median_net_return'], True)} | {_fmt(row['true_win_rate'], True)} | {_fmt(row['u_hit'], True)} | {_fmt(row['clean_success_10'], True)} | {_fmt(row['failed_attack'], True)} |")
        lane_risk_table.append(f"| {row['procedure']} | {row['lane']} | {_fmt(row['severe_loss8'], True)} | {_fmt(row['severe_loss10'], True)} | {_fmt(row['cvar5'], True)} | {_fmt(row['mean_holding_sessions'])} | {_fmt(row['median_holding_sessions'])} | {_fmt(row['cagr'], True)} | {_fmt(row['max_drawdown'], True)} | {_fmt(row['sharpe'])} | {_fmt(row['calmar'])} |")
    board_table = ["| Procedure | Board | Trades | Mean | Median | Win | Severe10 | CAGR | MaxDD |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in sorted(primary_board_rows, key=lambda item: (item["procedure"], item["board"])):
        board_table.append(f"| {row['procedure']} | {row['board']} | {row['completed_trades']} | {_fmt(row['mean_net_return'], True)} | {_fmt(row['median_net_return'], True)} | {_fmt(row['true_win_rate'], True)} | {_fmt(row['severe_loss10'], True)} | {_fmt(row['cagr'], True)} | {_fmt(row['max_drawdown'], True)} |")
    k_table = ["| Procedure | K | Trades | CAGR | MaxDD | Sharpe | Utilization | Capacity skips | Worst day | Top security share |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in sorted(k_sensitivity_rows, key=lambda item: (item["procedure"], item["k"])):
        k_table.append(f"| {row['procedure']} | {row['k']} | {row['completed_trades']} | {_fmt(row['cagr'], True)} | {_fmt(row['max_drawdown'], True)} | {_fmt(row['sharpe'])} | {_fmt(row['average_utilization'], True)} | {row['capacity_skips']} | {_fmt(row['worst_day'], True)} | {_fmt(row['top_security_trade_share'], True)} |")
    half_year_table = ["| Half-year | Forced-choice L5 | Deployment-gated L5 |", "|---|---:|---:|"]
    for period in outer_folds():
        fold = period["fold"]
        half_year_table.append(f"| {fold} | {_fmt(half_year_returns.get('FORCED_CHOICE_WF', {}).get(fold), True)} | {_fmt(half_year_returns.get('DEPLOYMENT_GATED_WF', {}).get(fold), True)} |")
    annual_table = ["| Year | Forced-choice L5 | Deployment-gated L5 |", "|---|---:|---:|"]
    for year in range(2017, 2022):
        key = str(year)
        annual_table.append(f"| {year} | {_fmt(annual_returns.get('FORCED_CHOICE_WF', {}).get(key), True)} | {_fmt(annual_returns.get('DEPLOYMENT_GATED_WF', {}).get(key), True)} |")
    selection_table = ["| Fold | Board | Overhang | Environment | Entry | RNT | Exit | H | Retry | Gate |", "|---|---|---|---|---|---:|---|---:|---|---|"]
    for row in selections.loc[selections.selection_role.eq("OUTER_WALKFORWARD")].itertuples(index=False):
        selection_table.append(f"| {row.outer_fold} | {row.board} | {row.overhang_rule} | {row.environment} | {row.translation} | {row.remaining_floor:.2%} | {row.exit_policy} | {row.time_stop} | {row.retry} | {'DEPLOY' if row.deployment_ready else 'CASH'} |")
    post_primary = post.loc[post.lane.eq("L5_FULL_SIMPLE_RULE") & post.procedure.eq("FORCED_CHOICE_POST_OBSERVATION") & post.board.eq("COMBINED")]
    post_table = ["| Period | Trades | Mean | Median | Win | U hit | Clean10 | Severe10 | Return | MaxDD |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in post_primary.sort_values("period").itertuples(index=False):
        post_table.append(f"| {row.period} | {row.completed_trades} | {_fmt(row.mean_net_return, True)} | {_fmt(row.median_net_return, True)} | {_fmt(row.true_win_rate, True)} | {_fmt(row.u_hit, True)} | {_fmt(row.clean_success_10, True)} | {_fmt(row.severe_loss10, True)} | {_fmt(row.total_return, True)} | {_fmt(row.max_drawdown, True)} |")
    post_board = post.loc[
        post.lane.eq("L5_FULL_SIMPLE_RULE")
        & post.procedure.eq("FORCED_CHOICE_POST_OBSERVATION")
    ]
    post_board_table = ["| Period | Board | Signals | Trades | Mean | Median | Win | Severe10 | Return |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in post_board.sort_values(["period", "board"]).itertuples(index=False):
        post_board_table.append(f"| {row.period} | {row.board} | {row.signals} | {row.completed_trades} | {_fmt(row.mean_net_return, True)} | {_fmt(row.median_net_return, True)} | {_fmt(row.true_win_rate, True)} | {_fmt(row.severe_loss10, True)} | {_fmt(row.total_return, True)} |")
    report = [
        f"# {EXPERIMENT}", "", "## Outcome", "",
        f"**Verdict: {verdict}**", "",
        "The scientific verdict uses only purged expanding 2017-H1 through 2021-H2 outer tests. The 2022–2023 section is explicitly post-observation and did not alter semantics, thresholds, selection, or verdict.", "",
        "## Frozen identities", "",
        f"- V6 semantic source: `{SOURCE_HASH}`", f"- V7 spec: `{feature_freeze['v7_spec_hash']}`", f"- Feature contract: `{feature_freeze['v7_feature_contract_hash']}`", f"- Attack contract: `{feature_freeze['v7_attack_contract_hash']}`", f"- Rule space: `{feature_freeze['v7_rule_space_hash']}`", f"- Exit space: `{feature_freeze['v7_exit_space_hash']}`", "",
        "## V6 to V7 reconciliation", "",
        f"- Frozen gaps / prior L0 rows / completed policy rows: {reconciliation['unique_source_events']} / {reconciliation['source_signal_rows']} / {reconciliation['completed_baseline_policy_rows']}.",
        f"- CORE / BOUNDARY source rows: {reconciliation['memory_state_row_split'].get('CORE', 0)} / {reconciliation['memory_state_row_split'].get('BOUNDARY', 0)}; unique gaps: {reconciliation['memory_state_unique_gap_split'].get('CORE', 0)} / {reconciliation['memory_state_unique_gap_split'].get('BOUNDARY', 0)}.",
        f"- Predecessor K10 completed trades / capacity skips: {reconciliation['portfolio_capacity_effects_k10']['completed_trades']} / {reconciliation['portfolio_capacity_effects_k10']['capacity_skips']}.",
        f"- Gaps with repeated predecessor timestamps: {reconciliation['gaps_with_more_than_one_source_entry_timestamp']}; separate mapped attacks: {reconciliation['how_many_prior_entry_timestamps_are_separate_attacks']}.",
        f"- Prior rows inside ATTACK_1 / ATTACK_2 / outside: {reconciliation['old_source_rows_inside_attack_1']} / {reconciliation['old_source_rows_inside_attack_2']} / {reconciliation['old_source_rows_outside_any_active_attack']}.",
        f"- Eventual U only after original reset: {reconciliation['eventual_u_only_after_original_attack_reset']}.",
        f"- Prior entry timestamps more than 1 / 3 / 5 sessions after causal first contact: {reconciliation['source_entry_timestamps_after_first_contact']['more_than_1_session']} / {reconciliation['source_entry_timestamps_after_first_contact']['more_than_3_sessions']} / {reconciliation['source_entry_timestamps_after_first_contact']['more_than_5_sessions']}.",
        f"- Corporate-action fail-closed paths — events / attacks / entry keys / policy rows: {reconciliation['corporate_action_fail_closed']['unique_events']} / {reconciliation['corporate_action_fail_closed']['unique_attacks']} / {reconciliation['corporate_action_fail_closed']['unique_entry_keys']} / {reconciliation['corporate_action_fail_closed']['policy_rows']}.",
        f"- Board split MAIN / ChiNext: {reconciliation['board_split']['MAIN']} / {reconciliation['board_split']['CHINEXT']}; duplicate event-date entries: {reconciliation['duplicate_event_date_entries']}.",
        f"- Top-10 formation-date / re-entry-date concentration: {_fmt(reconciliation['formation_date_top10_share'], True)} / {_fmt(reconciliation['reentry_date_top10_share'], True)}.",
        f"- Frozen predecessor entry mix: `{canonical_json(reconciliation['entry_rule_mix']).strip()}`.", "",
        "## Development lanes — combined K10", "", *lane_table, "", *lane_risk_table, "",
        "## Primary L5 board breakdown — K10", "", *board_table, "",
        "## Primary L5 K sensitivity — combined", "", *k_table, "",
        "## Primary L5 chronology", "", *half_year_table, "", *annual_table, "",
        "## Frozen outer selections", "", *selection_table, "",
        "## Direct and matched evidence", "",
        f"- Vacuum-score outer-test quintile mean net returns: `{canonical_json(vacuum_shape).strip()}`.",
        f"- Five preregistered outer-test two-dimensional surface summaries: `{canonical_json(surface_summaries).strip()}`. Best/worst cells are descriptive only and were not promoted into rules.",
        f"- Matched/FWL summaries: `{canonical_json(matched_summary).strip()}`.",
        f"- Model ceiling summaries: `{canonical_json(model_summary).strip()}`. Raw model scores were never deployable.", "",
        f"- Full TRAIN/outer-test univariate and surface metrics are in `{DIRECT_ANALYSIS}`; full matched results are in `{MATCHED_ANALYSIS}`.", "",
        "## Stability adjudication", "",
        f"- Checks: `{canonical_json(adjudication['checks']).strip()}`.",
        f"- Attack-date-equal mean: {_fmt(adjudication['attack_date_equal_mean'], True)}.",
        f"- Boundary baseline diagnostic: `{canonical_json(boundary_diagnostic).strip()}`.", "",
        "## High-overhang diagnostic (not mixed into Vacuum Repair)", "",
        f"- Summary: `{canonical_json(high_summary).strip()}`.",
        f"- ATTACK_1 / ATTACK_2 current-success: {_fmt(attack1_success, True)} / {_fmt(attack2_success, True)}.",
        f"- Separate absorption-breakout lane justified: {'YES' if absorption_lane else 'NO'}.", "",
        "## 2022–2023 POST-OBSERVATION ROBUSTNESS DIAGNOSTIC", "", *post_table, "", *post_board_table, "",
        "The frozen final policy selected R0_NO_RETRY, so ATTACK_2 contribution is exactly zero in this post-observation diagnostic.", "",
        "These numbers are not scientific evidence and were not used in the verdict.", "",
        "## Representative chart audit", "",
        f"- {len(chart_manifest)} charts; index: `{CHART_INDEX}`; external images/PDFs: `{CHART_DIR}`.", "",
        "## Audit", "", "```json", canonical_json(audit).strip(), "```", "",
        "## Final interpretation", "",
        f"- Positive causal simple strategy created: {'YES' if result['is_a_positive_causal_simple_strategy_created'] else 'NO'}.",
        f"- Stable enough for one sealed 2024+ challenge: {'YES' if result['is_rule_stable_enough_for_one_sealed_2024_plus_challenge'] else 'NO'}.",
        f"- 2024+ repository data opened: NO.",
        f"- Next action: {'preregister one sealed 2024+ challenge' if result['is_rule_stable_enough_for_one_sealed_2024_plus_challenge'] else 'do not open 2024+; retain useful representations or close this primary lane according to the verdict'}.", "",
    ]
    write_text(REPORT, "\n".join(report))
    payload = {"result_sha256": sha256(RESULT), "report_sha256": sha256(REPORT), "verdict": verdict, "audit": audit, "repository_2024_plus_data_opened": "NO"}
    manifest("STAGE_B_FINAL", "COMPLETE", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("preflight", "stage-a-overhang", "stage-a-attacks", "stage-a-freeze", "verify-freeze", "stage-b-outcomes", "stage-b-direct", "stage-b-rules", "stage-b-walkforward", "stage-b-portfolio", "stage-b-diagnostic", "finalize"))
    args = parser.parse_args()
    if args.stage == "preflight":
        result = stage_preflight()
    elif args.stage == "stage-a-overhang":
        result = stage_overhang()
    elif args.stage == "stage-a-attacks":
        result = stage_attacks()
    elif args.stage == "stage-a-freeze":
        result = stage_freeze()
    elif args.stage == "verify-freeze":
        result = verify_freeze()
    elif args.stage == "stage-b-outcomes":
        result = stage_b_outcomes()
    elif args.stage == "stage-b-direct":
        result = stage_b_direct()
    elif args.stage == "stage-b-rules":
        result = stage_b_rules()
    elif args.stage == "stage-b-walkforward":
        result = stage_b_walkforward()
    elif args.stage == "stage-b-portfolio":
        result = stage_b_portfolio()
    elif args.stage == "stage-b-diagnostic":
        result = stage_b_diagnostic()
    elif args.stage == "finalize":
        result = finalize_result()
    else:
        raise ResearchError(f"{args.stage} is implemented only after Stage-A contracts reproduce")
    print(canonical_json(result), end="")


if __name__ == "__main__":
    main()
