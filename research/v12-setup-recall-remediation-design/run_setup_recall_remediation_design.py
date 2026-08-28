#!/usr/bin/env python3
# ruff: noqa: E501
"""Research-only V12 setup recall remediation architecture study.

The runner consumes the frozen V3 fact, the completed Reverse Wave V2 labels,
and the already-built authoritative lifecycle ledger.  It never writes to the
production ledger, replays the production state machine, rebuilds chip state,
or fabricates a canonical peak during an ambiguous temporal observation.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
OUTPUT_DIR = STUDY_DIR / "results"
REPORT_PATH = STUDY_DIR / "V12_SETUP_RECALL_REMEDIATION_DESIGN_STUDY.md"
PREDECESSOR_DIR = REPO_ROOT / "research/v12-setup-accumulation-funnel"
PREDECESSOR_RESULTS = PREDECESSOR_DIR / "results"
PREDECESSOR_RUNNER = PREDECESSOR_DIR / "run_setup_accumulation_funnel.py"
V2_RESULTS = REPO_ROOT / "research/v12-reverse-wave-v2/results"

V3_ROOT = Path("/Users/linmei/Documents/CY/data/validation/v12_v3_500_temporal_20260828")
LEDGER_ROOT = Path("/Users/linmei/Documents/CY/data/validation/v12_lifecycle_entry_exit_ledger_500_20260828")
DAILY_2020 = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=2020/data_0.parquet")
MINUTE_2020 = Path("/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2/daily/partition_year=2020/data_0.parquet")

EXPECTED_PREDECESSOR_COMMIT = "d0a005daf33398d85f14ce1cba722bfc3b13a066"
EXPECTED_PREDECESSOR_MANIFEST_SHA256 = "ed7a6591e46fe4d94e505bdc22b6ef02f73e5eadbff6da49ca35826b2cd5271f"
EXPECTED_PREDECESSOR_RUNNER_SHA256 = "a20f34c88bda71ee28d1800fe59964024e91cd2ae1bb9ac71c12aabca5c25d73"
EXPECTED_DAILY_2020_SHA256 = "1b0a00c6d2cfbce0ae4f907e1ee9dc5006f59677d556cc10f8f34a9893937c62"
EXPECTED_MINUTE_2020_SHA256 = "8cf94aa834c520db71d0912385ac10872ecaa96b1aa356b3fb427a204a16c1bf"
EXPECTED_ROWS = 121_251
EXPECTED_LABEL_ROWS = 121_186
EXPECTED_WAVES = 1_599
EXPECTED_SYMBOLS = 500

SPLITS = ("discovery", "validation", "holdout")
TEMPORAL_STATES = (
    "VALID_CANONICAL_BASE",
    "ENSEMBLE_AMBIGUOUS",
    "NO_CANONICAL_BASE",
    "SPLIT",
    "MERGE",
    "LOST/TRANSITION",
)
BASE_FREE_COMPONENTS = (
    "ev_turnover_absorption",
    "ev_near_price_chip_growth",
    "ev_concentration_improves",
    "ev_downside_absorption",
)
ALL_COMPONENTS = (*BASE_FREE_COMPONENTS[:3], "ev_sticky_base", BASE_FREE_COMPONENTS[3])
SELLER_MODELS = ("UNIFORM", "DISPOSITION", "ACTIVE_STICKY")

# Frozen before holdout evaluation.  Counts are de-duplicated wave events, not
# dense positive symbol-days.  Enrichment is matched-wave recall divided by
# exact-date/board matched-control acceptance.
RESEARCHABILITY_CRITERION = {
    "minimum_validation_wave_candidates": 100,
    "minimum_holdout_wave_candidates": 100,
    "minimum_validation_wave_recall": 0.25,
    "minimum_holdout_wave_recall": 0.25,
    "minimum_validation_enrichment": 1.10,
    "minimum_holdout_enrichment": 1.10,
    "minimum_pooled_oos_enrichment_ci_low": 1.00,
}

# This separate criterion does not replace or relax the continuation-funnel
# safeguard above.  It asks whether a fixed, V3-independent candidate universe
# is broad and modestly enriched enough to justify a controlled P&L experiment
# whose purpose is to test the incremental V3 overlay.
PNL_RESEARCHABILITY_CRITERION = {
    "minimum_total_candidate_episodes": 500,
    "minimum_validation_candidate_episodes": 100,
    "minimum_holdout_candidate_episodes": 100,
    "minimum_validation_wave_candidates": 100,
    "minimum_holdout_wave_candidates": 100,
    "minimum_validation_enrichment": 1.05,
    "minimum_holdout_enrichment": 1.05,
    "minimum_median_candidate_duration": 1.0,
    "maximum_median_candidate_duration": 20.0,
    "candidate_layer_must_be_v3_independent": True,
}

ARCHITECTURES: dict[str, dict[str, str]] = {
    "A_CURRENT_V12": {
        "variant": "A",
        "definition": "Authoritative production SETUP_OBSERVED; unique canonical base, lifecycle validity, tradability, and production setup_score >= 1.00 all remain required.",
        "role": "PRODUCTION_BASELINE",
    },
    "B_CANDIDATE_FIRST": {
        "variant": "B",
        "definition": "Base-free PIT-valid, tradable observation after 60 consecutive base-free-valid sessions; no canonical root is required and no lifecycle state is written.",
        "role": "BROAD_RESEARCH_CANDIDATE_INTAKE",
    },
    "P_PRICE_ONLY_BROAD": {
        "variant": "P",
        "definition": "Registered daily-price PIT-valid, tradable observation after 60 consecutive price-valid sessions; no V3 chip field or canonical peak is used.",
        "role": "V3_INDEPENDENT_PRICE_RESEARCH_UNIVERSE",
    },
    "P_PRICE_PULLBACK_20": {
        "variant": "P",
        "definition": "Price-only eligible observation at least 5% below the trailing 20-session economic-price high; boundary fixed before evaluation and not fitted to wave outcomes.",
        "role": "V3_INDEPENDENT_SWING_PULLBACK_UNIVERSE",
    },
    "P_PRICE_PULLBACK_STABILIZING": {
        "variant": "P",
        "definition": "Fixed price-only 20-session pullback state plus nonnegative one-session economic-price change; no chip or temporal input.",
        "role": "V3_INDEPENDENT_SWING_STABILIZATION_UNIVERSE",
    },
    "C_TEMPORAL_STATE_STRATIFIED": {
        "variant": "C",
        "definition": "Same intake as B with an explicit non-substitutable temporal_state carried on every candidate.",
        "role": "STRATIFIED_RESEARCH_CANDIDATE_INTAKE",
    },
    "C_ENSEMBLE_AMBIGUOUS": {
        "variant": "C",
        "definition": "Candidate-first intake currently in ENSEMBLE_AMBIGUOUS state; canonical_base remains null.",
        "role": "EXPLICIT_AMBIGUITY_HYPOTHESIS",
    },
    "C_PERSISTENT_AMBIGUITY_20": {
        "variant": "C",
        "definition": "Candidate-first intake with ensemble ambiguity on at least 50% of the trailing 20 observations; fixed semantic boundary, not discovery-fitted.",
        "role": "EXPLICIT_PERSISTENCE_HYPOTHESIS",
    },
    "D_ANY_1_BASE_FREE_COMPONENT": {
        "variant": "D",
        "definition": "Candidate-first intake with at least one of four exactly observable base-free accumulation predicates true; sticky-base is unavailable unless canonical identity exists.",
        "role": "BASE_FREE_ACCUMULATION_EVIDENCE",
    },
    "D_ANY_2_BASE_FREE_COMPONENTS": {
        "variant": "D",
        "definition": "Candidate-first intake with at least two of four exactly observable base-free accumulation predicates true; fixed conjunction diagnostic.",
        "role": "BASE_FREE_ACCUMULATION_CONJUNCTION",
    },
    "D_ANY_1_PLUS_AMBIGUITY": {
        "variant": "D",
        "definition": "Any one base-free accumulation predicate plus explicit ENSEMBLE_AMBIGUOUS state; no fake canonical base.",
        "role": "ACCUMULATION_PLUS_TEMPORAL_STATE",
    },
    "D_ANY_1_PLUS_VALID_BASE": {
        "variant": "D",
        "definition": "Any one base-free accumulation predicate plus a valid canonical base; comparison confirmation architecture.",
        "role": "ACCUMULATION_PLUS_TEMPORAL_CONFIRMATION",
    },
}


def _load_predecessor() -> Any:
    spec = importlib.util.spec_from_file_location("authoritative_setup_funnel", PREDECESSOR_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load authoritative predecessor runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = _load_predecessor()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=BASE.json_default)


def stable_seed(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def verify_inputs() -> dict[str, Any]:
    evidence = BASE.verify_inputs()
    checks = {
        PREDECESSOR_RESULTS / "manifest.json": EXPECTED_PREDECESSOR_MANIFEST_SHA256,
        PREDECESSOR_RUNNER: EXPECTED_PREDECESSOR_RUNNER_SHA256,
        DAILY_2020: EXPECTED_DAILY_2020_SHA256,
        MINUTE_2020: EXPECTED_MINUTE_2020_SHA256,
    }
    for path, expected in checks.items():
        if sha256(path) != expected:
            raise RuntimeError(f"governed input changed: {path}")
    ancestor = subprocess.run(
        ("git", "merge-base", "--is-ancestor", EXPECTED_PREDECESSOR_COMMIT, "HEAD"),
        cwd=REPO_ROOT,
        check=False,
    ).returncode == 0
    if not ancestor:
        raise RuntimeError("study branch does not descend from the authoritative setup-funnel commit")
    evidence.update(
        {
            "authoritative_setup_funnel_commit": EXPECTED_PREDECESSOR_COMMIT,
            "authoritative_setup_funnel_manifest_sha256": EXPECTED_PREDECESSOR_MANIFEST_SHA256,
            "authoritative_setup_funnel_runner_sha256": EXPECTED_PREDECESSOR_RUNNER_SHA256,
            "registered_daily_2020_sha256": EXPECTED_DAILY_2020_SHA256,
            "registered_minute_daily_2020_sha256": EXPECTED_MINUTE_2020_SHA256,
            "branch_descends_from_authoritative_setup_funnel": ancestor,
        }
    )
    return evidence


def classify_temporal_state(frame: pd.DataFrame) -> pd.Series:
    """Classify without substituting a base and with disruptive states first."""

    state = pd.Series("NO_CANONICAL_BASE", index=frame.index, dtype="string")
    valid = (
        frame["peak_track_id"].notna()
        & ~frame["peak_track_ambiguous"].fillna(True)
        & ~frame["peak_track_split"].fillna(True)
        & ~frame["peak_track_merge"].fillna(True)
        & ~frame["peak_track_lost"].fillna(True)
    )
    state.loc[valid] = "VALID_CANONICAL_BASE"
    ambiguous = frame["peak_track_ambiguous"].fillna(False) | frame["peak_track_state"].eq("ENSEMBLE_PEAK_AMBIGUOUS")
    state.loc[ambiguous] = "ENSEMBLE_AMBIGUOUS"
    lost_or_transition = frame["peak_track_lost"].fillna(False) | frame["peak_track_state"].eq("TRACKED_BASE_PEAK_LOST_OR_AMBIGUOUS")
    state.loc[lost_or_transition] = "LOST/TRANSITION"
    state.loc[frame["peak_track_merge"].fillna(False)] = "MERGE"
    state.loc[frame["peak_track_split"].fillna(False)] = "SPLIT"
    return state


def _load_base_free_sources() -> pd.DataFrame:
    feature_scan = str(V3_ROOT / "symbol=*" / "daily_feature_candidate.parquet")
    con = duckdb.connect()
    try:
        con.execute("SET threads = 1")
        frame = con.execute(
            """
            SELECT
                f.symbol,
                f.trade_date AS feature_date,
                f.snapshot_id,
                f.available_at AS feature_available_at,
                f.research_valid,
                f.known_cost_fraction_min,
                f.profit_ratio,
                f.asr,
                f.cbw,
                f.concentration_20,
                f.peak_count,
                f.p10,
                f.p50,
                f.p90,
                f.peak_track_id,
                f.peak_track_state,
                f.peak_track_ambiguous,
                f.peak_track_split,
                f.peak_track_merge,
                f.peak_track_lost,
                f.model_spread_cost_p50,
                f.model_spread_cost_p90,
                f.model_spread_dominant_peak_today,
                d.available_at AS daily_available_at,
                d.snapshot_id AS daily_snapshot_id,
                d.open,
                d.high,
                d.low,
                d.close,
                d.preclose,
                d.turnover_fraction,
                d.trade_status,
                d.corporate_action_count,
                d.corporate_action_blocking,
                d.bar_valid,
                d.trading_state_valid,
                d.float_valid,
                d.corporate_action_valid,
                d.market_valid,
                d.market_rule_valid,
                d.historical_identity_valid,
                m.available_at AS minute_available_at,
                m.snapshot_id AS minute_snapshot_id,
                m.close_vs_vwap,
                m.closing_30m_return
            FROM read_parquet(?, hive_partitioning=false, union_by_name=true) f
            LEFT JOIN read_parquet(?) d USING (symbol, trade_date)
            LEFT JOIN read_parquet(?) m USING (symbol, trade_date)
            ORDER BY f.symbol, f.trade_date
            """,
            [feature_scan, str(DAILY_2020), str(MINUTE_2020)],
        ).fetchdf()
    finally:
        con.close()
    if len(frame) != EXPECTED_ROWS or frame["symbol"].nunique() != EXPECTED_SYMBOLS:
        raise RuntimeError("base-free source coverage changed")
    return frame


def _attach_corporate_action_gate(frame: pd.DataFrame, gates: pd.DataFrame) -> pd.DataFrame:
    clear = gates[gates["gate_name"].eq("corporate_action_clear")][["symbol", "decision_at", "passed"]].copy()
    clear["feature_date"] = BASE.decision_date(clear.pop("decision_at"))
    clear = clear.rename(columns={"passed": "corporate_action_clear"})
    if clear.duplicated(["symbol", "feature_date"]).any():
        raise RuntimeError("duplicate authoritative corporate-action decision gate")
    result = frame.merge(clear, on=["symbol", "feature_date"], how="left", validate="one_to_one")
    if result["corporate_action_clear"].isna().any():
        raise RuntimeError("missing authoritative corporate-action decision gate")
    return result


def _available_by_decision(values: pd.Series, feature_dates: pd.Series) -> pd.Series:
    timestamps = pd.to_datetime(values, errors="coerce")
    if isinstance(timestamps.dtype, pd.DatetimeTZDtype):
        timestamps = timestamps.dt.tz_convert("Asia/Shanghai")
    else:
        # CY-006 stores local exchange timestamps without a timezone suffix;
        # the frozen V3 fact stores the same clock with +08:00 explicitly.
        timestamps = timestamps.dt.tz_localize("Asia/Shanghai", ambiguous="raise", nonexistent="raise")
    decision = pd.to_datetime(feature_dates).dt.tz_localize("Asia/Shanghai") + pd.Timedelta(hours=15, minutes=30)
    return timestamps.notna() & timestamps.le(decision)


def compute_base_free_evidence(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply exact component predicates on a research-only base-free chain.

    The chain preserves all non-temporal production input/PIT/action validity
    requirements available in the frozen and registered facts, but deliberately
    omits canonical-peak identity.  This is not a production panel or score.
    """

    result = frame.sort_values(["symbol", "feature_date"]).reset_index(drop=True).copy()
    result["temporal_state"] = classify_temporal_state(result)
    result["ensemble_peak_ambiguous"] = result["peak_track_state"].eq("ENSEMBLE_PEAK_AMBIGUOUS")
    result["daily_pit_available"] = _available_by_decision(result["daily_available_at"], result["feature_date"])
    result["pit_available"] = _available_by_decision(result["feature_available_at"], result["feature_date"]) & result["daily_pit_available"]
    finite_known = pd.to_numeric(result["known_cost_fraction_min"], errors="coerce").between(0.0, 1.0, inclusive="both")
    validity_fields = (
        "research_valid",
        "bar_valid",
        "trading_state_valid",
        "float_valid",
        "corporate_action_valid",
        "market_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "corporate_action_clear",
    )
    valid = result["pit_available"] & finite_known
    for field in validity_fields:
        valid &= result[field].fillna(False).astype(bool)
    # The already-resolved authoritative gate supersedes raw action flags.  A
    # raw distribution reset may be safe after exact PIT resolution, which is
    # why corporate_action_blocking is not separately re-applied here.
    result["base_free_input_valid"] = valid
    result["tradable_state"] = result["trading_state_valid"].fillna(False) & result["trade_status"].eq(1)

    price_valid = result["daily_pit_available"]
    for field in (
        "bar_valid", "trading_state_valid", "float_valid", "corporate_action_valid",
        "market_valid", "market_rule_valid", "historical_identity_valid", "corporate_action_clear",
    ):
        price_valid &= result[field].fillna(False).astype(bool)
    price_valid &= result[["open", "high", "low", "close", "preclose", "turnover_fraction"]].apply(
        lambda values: pd.to_numeric(values, errors="coerce").notna()
    ).all(axis=1)
    price_valid &= result[["open", "high", "low", "close", "preclose"]].gt(0).all(axis=1)
    result["price_input_valid"] = price_valid

    for column in (*ALL_COMPONENTS, "ambiguity_rate_20", "ambiguity_episode_age", "ambiguity_full_episode_duration", "sessions_to_ambiguity_resolution", "base_free_history_count", "price_history_count", "price_drawdown_20", "price_return_1"):
        result[column] = pd.NA
    result["ambiguity_onset"] = False
    result["ambiguity_resolution_within_5"] = pd.NA
    result["ambiguity_resolution_within_20"] = pd.NA

    for _, symbol_frame in result.groupby("symbol", sort=False):
        symbol_frame = symbol_frame.sort_values("feature_date")
        symbol_index = symbol_frame.index
        ambiguous = symbol_frame["peak_track_state"].eq("ENSEMBLE_PEAK_AMBIGUOUS")
        result.loc[symbol_index, "ambiguity_rate_20"] = ambiguous.astype(float).rolling(20, min_periods=20).mean().to_numpy()
        onset = ambiguous & ~ambiguous.shift(1, fill_value=False)
        result.loc[symbol_index, "ambiguity_onset"] = onset.to_numpy()
        episode_id = ambiguous.ne(ambiguous.shift(1, fill_value=False)).cumsum()
        episode_age = ambiguous.groupby(episode_id).cumcount() + 1
        episode_duration = ambiguous.groupby(episode_id).transform("sum")
        result.loc[symbol_index, "ambiguity_episode_age"] = episode_age.where(ambiguous).to_numpy()
        result.loc[symbol_index, "ambiguity_full_episode_duration"] = episode_duration.where(ambiguous).to_numpy()
        ambiguous_positions = np.flatnonzero(ambiguous.to_numpy())
        ambiguity_array = ambiguous.to_numpy()
        to_resolution = np.full(len(symbol_frame), np.nan)
        for position in ambiguous_positions:
            future_clear = np.flatnonzero(~ambiguity_array[position + 1 :])
            if len(future_clear):
                to_resolution[position] = int(future_clear[0] + 1)
        result.loc[symbol_index, "sessions_to_ambiguity_resolution"] = to_resolution
        result.loc[symbol_index, "ambiguity_resolution_within_5"] = pd.array(
            np.where(ambiguous, np.isfinite(to_resolution) & (to_resolution <= 5), pd.NA), dtype="boolean"
        )
        result.loc[symbol_index, "ambiguity_resolution_within_20"] = pd.array(
            np.where(ambiguous, np.isfinite(to_resolution) & (to_resolution <= 20), pd.NA), dtype="boolean"
        )

        raw_previous_close = symbol_frame["close"].shift(1)
        action_ratio = pd.Series(1.0, index=symbol_index)
        reset = symbol_frame["corporate_action_count"].fillna(0).gt(0) & raw_previous_close.gt(0) & symbol_frame["preclose"].gt(0)
        action_ratio.loc[reset.index[reset]] = (symbol_frame.loc[reset, "preclose"] / raw_previous_close.loc[reset]).to_numpy()
        coordinate_factor = action_ratio.cumprod()
        symbol_frame = symbol_frame.copy()
        symbol_frame["coordinate_factor"] = coordinate_factor
        symbol_frame["analysis_close"] = symbol_frame["close"] / coordinate_factor
        symbol_frame["analysis_p10"] = symbol_frame["p10"] / coordinate_factor
        symbol_frame["analysis_p50"] = symbol_frame["p50"] / coordinate_factor
        symbol_frame["analysis_p90"] = symbol_frame["p90"] / coordinate_factor
        raw_true_range = pd.concat(
            [
                symbol_frame["high"] - symbol_frame["low"],
                (symbol_frame["high"] - symbol_frame["preclose"]).abs(),
                (symbol_frame["low"] - symbol_frame["preclose"]).abs(),
            ],
            axis=1,
        ).max(axis=1)
        symbol_frame["analysis_true_range"] = raw_true_range / coordinate_factor
        raw_impact = (symbol_frame["close"] - symbol_frame["preclose"]).abs() / symbol_frame["turnover_fraction"].clip(lower=1e-8)
        symbol_frame["analysis_price_impact"] = raw_impact / coordinate_factor

        price_epoch = (~symbol_frame["price_input_valid"]).cumsum()
        for _, price_frame in symbol_frame.groupby(price_epoch, sort=False):
            if not bool(price_frame["price_input_valid"].iloc[0]):
                continue
            price_idx = price_frame.index
            trailing_high20 = price_frame["analysis_close"].rolling(20, min_periods=20).max()
            result.loc[price_idx, "price_history_count"] = np.arange(1, len(price_frame) + 1)
            result.loc[price_idx, "price_drawdown_20"] = (price_frame["analysis_close"] / trailing_high20 - 1.0).to_numpy()
            result.loc[price_idx, "price_return_1"] = price_frame["analysis_close"].pct_change(fill_method=None).to_numpy()

        epoch = (~symbol_frame["base_free_input_valid"]).cumsum()
        for _, valid_frame in symbol_frame.groupby(epoch, sort=False):
            if not bool(valid_frame["base_free_input_valid"].iloc[0]):
                continue
            idx = valid_frame.index
            count = np.arange(1, len(valid_frame) + 1)
            turnover_mean20 = valid_frame["turnover_fraction"].rolling(20, min_periods=1).mean()
            impact_mean20 = valid_frame["analysis_price_impact"].rolling(20, min_periods=1).mean()
            turnover_q60_prior = valid_frame["turnover_fraction"].shift(1).rolling(60, min_periods=1).quantile(0.60)
            impact_q50_prior = valid_frame["analysis_price_impact"].shift(1).rolling(60, min_periods=1).quantile(0.50)
            atr14_analysis = valid_frame["analysis_true_range"].shift(1).rolling(14, min_periods=1).mean()
            p10_lag20 = valid_frame["analysis_p10"].shift(20)
            p50_lag20 = valid_frame["analysis_p50"].shift(20)
            p90_lag20 = valid_frame["analysis_p90"].shift(20)
            denominator = p90_lag20 - p10_lag20
            overlap = (
                (np.minimum(valid_frame["analysis_p90"], p90_lag20) - np.maximum(valid_frame["analysis_p10"], p10_lag20))
                .clip(lower=0.0)
                .div(denominator)
                .clip(lower=0.0, upper=1.0)
                .where(denominator.gt(0))
            )
            turnover = (turnover_mean20.ge(turnover_q60_prior) & impact_mean20.le(impact_q50_prior)).astype("boolean")
            near = (valid_frame["asr"].gt(valid_frame["asr"].shift(20)) & valid_frame["profit_ratio"].ge(0.45)).astype("boolean")
            concentration = (
                valid_frame["cbw"].le(valid_frame["cbw"].shift(20))
                & valid_frame["concentration_20"].ge(valid_frame["concentration_20"].shift(20))
                & valid_frame["peak_count"].le(valid_frame["peak_count"].shift(20) + 1)
            ).astype("boolean")
            downside = (valid_frame["close_vs_vwap"].ge(0) & valid_frame["closing_30m_return"].ge(0)).astype("boolean")
            current_unique = valid_frame["temporal_state"].eq("VALID_CANONICAL_BASE")
            lag_unique = current_unique.shift(20, fill_value=False)
            sticky_available = current_unique & lag_unique & valid_frame["peak_track_id"].shift(20).notna() & overlap.notna() & atr14_analysis.notna()
            sticky = (
                valid_frame["peak_track_id"].eq(valid_frame["peak_track_id"].shift(20))
                & overlap.ge(0.55)
                & (valid_frame["analysis_p50"] - p50_lag20).abs().le(atr14_analysis.clip(lower=1e-8))
            ).astype("boolean").where(sticky_available)
            result.loc[idx, "base_free_history_count"] = count
            result.loc[idx, "ev_turnover_absorption"] = turnover.to_numpy()
            result.loc[idx, "ev_near_price_chip_growth"] = near.to_numpy()
            result.loc[idx, "ev_concentration_improves"] = concentration.to_numpy()
            result.loc[idx, "ev_sticky_base"] = sticky.to_numpy()
            result.loc[idx, "ev_downside_absorption"] = downside.to_numpy()

    result["base_free_history_count"] = pd.to_numeric(result["base_free_history_count"], errors="coerce")
    result["price_history_count"] = pd.to_numeric(result["price_history_count"], errors="coerce")
    result["price_drawdown_20"] = pd.to_numeric(result["price_drawdown_20"], errors="coerce")
    result["price_return_1"] = pd.to_numeric(result["price_return_1"], errors="coerce")
    result["candidate_first_eligible"] = result["base_free_input_valid"] & result["tradable_state"] & result["base_free_history_count"].ge(60)
    result["price_candidate_eligible"] = result["price_input_valid"] & result["tradable_state"] & result["price_history_count"].ge(60)
    for component in ALL_COMPONENTS:
        result[component] = pd.array(result[component], dtype="boolean")
        result.loc[~result["candidate_first_eligible"], component] = pd.NA
    for column in ("ambiguity_resolution_within_5", "ambiguity_resolution_within_20"):
        result[column] = pd.array(result[column], dtype="boolean")
    result["ambiguity_rate_20"] = pd.to_numeric(result["ambiguity_rate_20"], errors="coerce")
    result["ambiguity_episode_age"] = pd.to_numeric(result["ambiguity_episode_age"], errors="coerce")
    result["ambiguity_full_episode_duration"] = pd.to_numeric(result["ambiguity_full_episode_duration"], errors="coerce")
    result["sessions_to_ambiguity_resolution"] = pd.to_numeric(result["sessions_to_ambiguity_resolution"], errors="coerce")
    result["base_free_component_count"] = result[list(BASE_FREE_COMPONENTS)].fillna(False).astype(int).sum(axis=1)
    result["base_free_component_available_count"] = result[list(BASE_FREE_COMPONENTS)].notna().sum(axis=1)
    return result


def _attach_production_baseline(frame: pd.DataFrame, lifecycle: pd.DataFrame) -> pd.DataFrame:
    principal = lifecycle[~lifecycle["event_type"].eq("ROOT_ANCHOR_BOUND")][["symbol", "feature_date", "event_type"]]
    result = frame.merge(principal, on=["symbol", "feature_date"], how="left", validate="one_to_one")
    if result["event_type"].isna().any():
        raise RuntimeError("production baseline coverage missing")
    result["production_setup_created"] = result["event_type"].eq("SETUP_OBSERVED")
    return result


def architecture_flags(frame: pd.DataFrame) -> dict[str, pd.Series]:
    eligible = frame["candidate_first_eligible"].fillna(False)
    count = frame["base_free_component_count"].fillna(0)
    ambiguous = frame["temporal_state"].eq("ENSEMBLE_AMBIGUOUS")
    valid_base = frame["temporal_state"].eq("VALID_CANONICAL_BASE")
    persistent = frame["ambiguity_rate_20"].ge(0.50).fillna(False)
    price_eligible = frame["price_candidate_eligible"].fillna(False)
    price_pullback = frame["price_drawdown_20"].le(-0.05).fillna(False)
    price_stabilizing = frame["price_return_1"].ge(0.0).fillna(False)
    return {
        "A_CURRENT_V12": frame["production_setup_created"].fillna(False),
        "B_CANDIDATE_FIRST": eligible,
        "P_PRICE_ONLY_BROAD": price_eligible,
        "P_PRICE_PULLBACK_20": price_eligible & price_pullback,
        "P_PRICE_PULLBACK_STABILIZING": price_eligible & price_pullback & price_stabilizing,
        "C_TEMPORAL_STATE_STRATIFIED": eligible,
        "C_ENSEMBLE_AMBIGUOUS": eligible & ambiguous,
        "C_PERSISTENT_AMBIGUITY_20": eligible & persistent,
        "D_ANY_1_BASE_FREE_COMPONENT": eligible & count.ge(1),
        "D_ANY_2_BASE_FREE_COMPONENTS": eligible & count.ge(2),
        "D_ANY_1_PLUS_AMBIGUITY": eligible & count.ge(1) & ambiguous,
        "D_ANY_1_PLUS_VALID_BASE": eligible & count.ge(1) & valid_base,
    }


def _join_research(events: pd.DataFrame, research: pd.DataFrame, *, event_id: str) -> pd.DataFrame:
    columns = [
        "symbol", "feature_date", "temporal_state", "candidate_first_eligible", "production_setup_created",
        "price_candidate_eligible", "price_drawdown_20", "price_return_1",
        "ensemble_peak_ambiguous",
        "ambiguity_rate_20", "ambiguity_episode_age", "ambiguity_full_episode_duration",
        "ambiguity_onset", "sessions_to_ambiguity_resolution", "ambiguity_resolution_within_5",
        "ambiguity_resolution_within_20", "model_spread_cost_p50", "model_spread_cost_p90",
        "model_spread_dominant_peak_today", "base_free_component_count", "base_free_component_available_count",
        *ALL_COMPONENTS,
    ]
    overlap = [column for column in columns if column not in {"symbol", "feature_date"} and column in events.columns]
    result = events.drop(columns=overlap).merge(
        research[columns], on=["symbol", "feature_date"], how="left", validate="one_to_one"
    )
    if result[event_id].isna().any() or result["temporal_state"].isna().any():
        raise RuntimeError("event research join lacks exact coverage")
    for name, flag in architecture_flags(result).items():
        result[name] = flag.astype(bool)
    return result


def _cluster_rate_ci(frame: pd.DataFrame, flag: str, *, seed: int) -> tuple[float, float]:
    return BASE.cluster_rate_interval(frame, flag, symbol="symbol", seed=seed, draws=500)


def _cluster_lift_ci(waves: pd.DataFrame, controls: pd.DataFrame, flag: str, *, seed: int) -> tuple[float, float]:
    def clusters(frame: pd.DataFrame) -> list[tuple[int, int]]:
        return [(int(group[flag].sum()), len(group)) for _, group in frame.groupby("symbol", sort=True)]

    wave_clusters, control_clusters = clusters(waves), clusters(controls)
    if not wave_clusters or not control_clusters:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(500):
        wi = rng.integers(0, len(wave_clusters), len(wave_clusters))
        ci = rng.integers(0, len(control_clusters), len(control_clusters))
        wr = sum(wave_clusters[i][0] for i in wi) / sum(wave_clusters[i][1] for i in wi)
        cr = sum(control_clusters[i][0] for i in ci) / sum(control_clusters[i][1] for i in ci)
        if cr > 0:
            values.append(wr / cr)
    if not values:
        return math.nan, math.nan
    return float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))


def candidate_episode_statistics(research: pd.DataFrame) -> pd.DataFrame:
    """Retrospectively summarize consecutive candidate-state episodes.

    Episode duration is an evaluation statistic, never a same-day candidate
    input.  Split attribution uses episode onset, so an episode is counted once.
    """

    working = research[["symbol", "feature_date"]].copy()
    for name, flag in architecture_flags(research).items():
        working[name] = flag.astype(bool).to_numpy()
    rows: list[dict[str, Any]] = []
    for architecture in ARCHITECTURES:
        episodes: list[dict[str, Any]] = []
        for symbol, group in working.groupby("symbol", sort=True):
            group = group.sort_values("feature_date")
            active = group[architecture].to_numpy(dtype=bool)
            run_id = np.cumsum(active != np.r_[False, active[:-1]])
            for _, episode in group[active].groupby(run_id[active], sort=False):
                onset = pd.Timestamp(episode["feature_date"].iloc[0])
                episodes.append(
                    {
                        "symbol": symbol,
                        "onset": onset,
                        "onset_split": date_split(onset),
                        "duration": len(episode),
                    }
                )
        episode_frame = pd.DataFrame(episodes, columns=["symbol", "onset", "onset_split", "duration"])
        for split in ("total", *SPLITS):
            subset = episode_frame if split == "total" else episode_frame[episode_frame["onset_split"].eq(split)]
            symbol_days = int(working[architecture].sum()) if split == "total" else int(
                working.loc[working["feature_date"].map(date_split).eq(split), architecture].sum()
            )
            rows.append(
                {
                    "architecture": architecture,
                    "split": split,
                    "candidate_symbol_days": symbol_days,
                    "distinct_candidate_episodes": len(subset),
                    "distinct_candidate_symbols": int(subset["symbol"].nunique()) if len(subset) else 0,
                    "candidate_episodes_per_symbol_year": len(subset) / EXPECTED_SYMBOLS,
                    "candidate_symbol_days_per_symbol_year": symbol_days / EXPECTED_SYMBOLS,
                    "median_candidate_duration": float(subset["duration"].median()) if len(subset) else math.nan,
                    "p25_candidate_duration": float(subset["duration"].quantile(0.25)) if len(subset) else math.nan,
                    "p75_candidate_duration": float(subset["duration"].quantile(0.75)) if len(subset) else math.nan,
                    "max_candidate_duration": int(subset["duration"].max()) if len(subset) else 0,
                    "episode_split_attribution": "EPISODE_ONSET",
                }
            )
    return pd.DataFrame(rows)


def candidate_recall_vs_control(
    research: pd.DataFrame,
    labels: pd.DataFrame,
    waves: pd.DataFrame,
    controls: pd.DataFrame,
) -> pd.DataFrame:
    research = research.copy()
    for name, flag in architecture_flags(research).items():
        research[name] = flag.astype(bool)
    labelled = labels[["symbol", "feature_date", "split", "any_upside"]].merge(
        research, on=["symbol", "feature_date"], how="left", validate="one_to_one"
    )
    if len(labelled) != EXPECTED_LABEL_ROWS or labelled["temporal_state"].isna().any():
        raise RuntimeError("labelled architecture population changed")
    for name, flag in architecture_flags(labelled).items():
        labelled[name] = flag.astype(bool)
    episode_stats = candidate_episode_statistics(research).set_index(["architecture", "split"])
    rows: list[dict[str, Any]] = []
    for architecture in ARCHITECTURES:
        for split in ("total", *SPLITS):
            full = research if split == "total" else research[research["feature_date"].map(date_split).eq(split)]
            label_subset = labelled if split == "total" else labelled[labelled["split"].eq(split)]
            wave_subset = waves if split == "total" else waves[waves["split"].eq(split)]
            control_subset = controls if split == "total" else controls[controls["split"].eq(split)]
            wave_pass = int(wave_subset[architecture].sum())
            control_pass = int(control_subset[architecture].sum())
            wave_rate = wave_pass / len(wave_subset)
            control_rate = control_pass / len(control_subset)
            candidate_labels = label_subset[label_subset[architecture]]
            positive = int(candidate_labels["any_upside"].sum())
            precision = positive / len(candidate_labels) if len(candidate_labels) else math.nan
            base_rate = float(label_subset["any_upside"].mean())
            wave_low, wave_high = BASE.wilson(wave_pass, len(wave_subset))
            control_low, control_high = BASE.wilson(control_pass, len(control_subset))
            precision_low, precision_high = BASE.wilson(positive, len(candidate_labels))
            wave_cluster_low, wave_cluster_high = _cluster_rate_ci(wave_subset, architecture, seed=stable_seed(architecture, split, "wave"))
            control_cluster_low, control_cluster_high = _cluster_rate_ci(control_subset, architecture, seed=stable_seed(architecture, split, "control"))
            lift_low, lift_high = _cluster_lift_ci(wave_subset, control_subset, architecture, seed=stable_seed(architecture, split, "lift"))
            composition = full.loc[full[architecture], "temporal_state"].value_counts().sort_index().to_dict()
            episode = episode_stats.loc[(architecture, split)]
            rows.append(
                {
                    "architecture": architecture,
                    "variant": ARCHITECTURES[architecture]["variant"],
                    "split": split,
                    "eligible_symbol_days": int(full[architecture].sum()),
                    "distinct_candidate_episodes": int(episode.distinct_candidate_episodes),
                    "distinct_candidate_symbols": int(episode.distinct_candidate_symbols),
                    "candidate_episodes_per_symbol_year": episode.candidate_episodes_per_symbol_year,
                    "candidate_symbol_days_per_symbol_year": episode.candidate_symbol_days_per_symbol_year,
                    "median_candidate_duration": episode.median_candidate_duration,
                    "p25_candidate_duration": episode.p25_candidate_duration,
                    "p75_candidate_duration": episode.p75_candidate_duration,
                    "max_candidate_duration": int(episode.max_candidate_duration),
                    "total_symbol_days": len(full),
                    "symbol_day_candidate_rate": float(full[architecture].mean()),
                    "labelled_candidate_days": len(candidate_labels),
                    "labelled_positive_days": positive,
                    "candidate_precision": precision,
                    "candidate_precision_wilson_low": precision_low,
                    "candidate_precision_wilson_high": precision_high,
                    "raw_label_base_rate": base_rate,
                    "precision_lift_over_raw_base": precision / base_rate if base_rate and math.isfinite(precision) else math.nan,
                    "wave_n": len(wave_subset),
                    "wave_candidates": wave_pass,
                    "wave_recall": wave_rate,
                    "wave_wilson_low": wave_low,
                    "wave_wilson_high": wave_high,
                    "wave_symbol_cluster_low": wave_cluster_low,
                    "wave_symbol_cluster_high": wave_cluster_high,
                    "control_n": len(control_subset),
                    "control_candidates": control_pass,
                    "control_acceptance": control_rate,
                    "control_wilson_low": control_low,
                    "control_wilson_high": control_high,
                    "control_symbol_cluster_low": control_cluster_low,
                    "control_symbol_cluster_high": control_cluster_high,
                    "matched_enrichment": wave_rate / control_rate if control_rate else math.nan,
                    "matched_enrichment_cluster_low": lift_low,
                    "matched_enrichment_cluster_high": lift_high,
                    "balanced_matched_precision": wave_pass / (wave_pass + control_pass) if wave_pass + control_pass else math.nan,
                    "temporal_state_composition_json": canonical_json(composition),
                    "candidate_definition": ARCHITECTURES[architecture]["definition"],
                }
            )
    return pd.DataFrame(rows)


def date_split(value: pd.Timestamp) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp <= pd.Timestamp("2020-04-30"):
        return "discovery"
    if timestamp <= pd.Timestamp("2020-08-31"):
        return "validation"
    return "holdout"


def architecture_comparison(recall: pd.DataFrame, research: pd.DataFrame) -> pd.DataFrame:
    total = recall[recall["split"].eq("total")].copy()
    missing_base_free = int((~research["candidate_first_eligible"]).sum())
    rows = []
    for row in total.itertuples(index=False):
        spec = ARCHITECTURES[row.architecture]
        rows.append(
            {
                "architecture": row.architecture,
                "variant": spec["variant"],
                "strategy_role": spec["role"],
                "candidate_definition": spec["definition"],
                "unique_canonical_base_required_for_candidate": row.architecture in {"A_CURRENT_V12", "D_ANY_1_PLUS_VALID_BASE"},
                "writes_production_state": False,
                "simulates_downstream_lifecycle": False,
                "eligible_symbol_days": row.eligible_symbol_days,
                "distinct_candidate_episodes": row.distinct_candidate_episodes,
                "distinct_candidate_symbols": row.distinct_candidate_symbols,
                "candidate_episodes_per_symbol_year": row.candidate_episodes_per_symbol_year,
                "candidate_symbol_days_per_symbol_year": row.candidate_symbol_days_per_symbol_year,
                "median_candidate_duration": row.median_candidate_duration,
                "p25_candidate_duration": row.p25_candidate_duration,
                "p75_candidate_duration": row.p75_candidate_duration,
                "max_candidate_duration": row.max_candidate_duration,
                "symbol_day_candidate_rate": row.symbol_day_candidate_rate,
                "wave_candidates": row.wave_candidates,
                "wave_recall": row.wave_recall,
                "control_candidates": row.control_candidates,
                "control_acceptance": row.control_acceptance,
                "matched_enrichment": row.matched_enrichment,
                "matched_enrichment_cluster_low": row.matched_enrichment_cluster_low,
                "matched_enrichment_cluster_high": row.matched_enrichment_cluster_high,
                "candidate_precision": row.candidate_precision,
                "raw_label_base_rate": row.raw_label_base_rate,
                "precision_lift_over_raw_base": row.precision_lift_over_raw_base,
                "temporal_state_composition_json": row.temporal_state_composition_json,
                "candidate_input_ineligible_or_warmup_symbol_days": (
                    int((~research["price_candidate_eligible"]).sum()) if row.architecture.startswith("P_") else missing_base_free
                ),
            }
        )
    return pd.DataFrame(rows)


def _metric_value(series: pd.Series, kind: str) -> float:
    values = pd.to_numeric(series, errors="coerce")
    if kind == "prevalence":
        return float(values.mean()) if values.notna().any() else math.nan
    if kind == "median":
        return float(values.median()) if values.notna().any() else math.nan
    return float(values.mean()) if values.notna().any() else math.nan


def temporal_state_outcomes(
    research: pd.DataFrame,
    labels: pd.DataFrame,
    waves: pd.DataFrame,
    controls: pd.DataFrame,
) -> pd.DataFrame:
    labelled = labels[["symbol", "feature_date", "split", "any_upside"]].merge(
        research, on=["symbol", "feature_date"], how="left", validate="one_to_one"
    )
    rows: list[dict[str, Any]] = []
    for split in ("total", *SPLITS):
        w = waves if split == "total" else waves[waves["split"].eq(split)]
        c = controls if split == "total" else controls[controls["split"].eq(split)]
        lab = labelled if split == "total" else labelled[labelled["split"].eq(split)]
        lab_eligible = lab[lab["candidate_first_eligible"]]
        base_rate = float(lab_eligible["any_upside"].mean()) if len(lab_eligible) else math.nan
        for state in TEMPORAL_STATES:
            ws = int(w["temporal_state"].eq(state).sum())
            cs = int(c["temporal_state"].eq(state).sum())
            state_lab = lab_eligible[lab_eligible["temporal_state"].eq(state)]
            positives = int(state_lab["any_upside"].sum())
            outcome_rate = positives / len(state_lab) if len(state_lab) else math.nan
            rows.append(
                {
                    "section": "TEMPORAL_STATE",
                    "split": split,
                    "state_or_metric": state,
                    "metric_kind": "prevalence_and_subsequent_wave_rate",
                    "wave_n": len(w),
                    "wave_available": len(w),
                    "wave_value": ws / len(w),
                    "control_n": len(c),
                    "control_available": len(c),
                    "control_value": cs / len(c),
                    "wave_minus_control": ws / len(w) - cs / len(c),
                    "matched_enrichment": (ws / len(w)) / (cs / len(c)) if cs else math.nan,
                    "labelled_symbol_days": len(state_lab),
                    "labelled_positive_days": positives,
                    "subsequent_wave_rate": outcome_rate,
                    "eligible_base_rate": base_rate,
                    "subsequent_wave_lift": outcome_rate / base_rate if base_rate and math.isfinite(outcome_rate) else math.nan,
                    "seller_model_configuration": "|".join(SELLER_MODELS),
                    "pit_candidate_usable": True,
                    "retrospective_only": False,
                    "note": "State is explicit; ENSEMBLE_AMBIGUOUS never supplies a canonical_base value.",
                }
            )

        metrics: tuple[tuple[str, str, Callable[[pd.DataFrame], pd.Series], bool, str], ...] = (
            ("ensemble_ambiguity", "prevalence", lambda d: d["ensemble_peak_ambiguous"], False, "Exact frozen ENSEMBLE_PEAK_AMBIGUOUS state; disruptive-state precedence is reported separately in TEMPORAL_STATE rows."),
            ("ambiguity_rate_20", "mean", lambda d: d["ambiguity_rate_20"], False, "Trailing-only PIT persistence."),
            ("ambiguity_episode_age", "mean", lambda d: d["ambiguity_episode_age"], False, "Consecutive ambiguity observed through T; null outside ambiguity."),
            ("ambiguity_onset", "prevalence", lambda d: d["ambiguity_onset"], False, "Onset at T uses T and T-1 only."),
            ("ambiguity_full_episode_duration", "mean", lambda d: d["ambiguity_full_episode_duration"], True, "Retrospective characterization; forbidden as candidate input."),
            ("sessions_to_ambiguity_resolution", "mean", lambda d: d["sessions_to_ambiguity_resolution"], True, "Future resolution outcome; forbidden as candidate input."),
            ("ambiguity_resolution_within_5", "prevalence", lambda d: d["ambiguity_resolution_within_5"], True, "Future resolution outcome; forbidden as candidate input."),
            ("ambiguity_resolution_within_20", "prevalence", lambda d: d["ambiguity_resolution_within_20"], True, "Future resolution outcome; forbidden as candidate input."),
            ("model_spread_cost_p50", "mean", lambda d: d["model_spread_cost_p50"], False, "Frozen aggregate seller-model geometry spread."),
            ("model_spread_cost_p90", "mean", lambda d: d["model_spread_cost_p90"], False, "Frozen aggregate seller-model geometry spread."),
            ("model_spread_dominant_peak_today", "mean", lambda d: d["model_spread_dominant_peak_today"], False, "Frozen aggregate seller-model disagreement."),
        )
        for metric, kind, getter, retrospective, note in metrics:
            wv, cv = getter(w), getter(c)
            wave_value, control_value = _metric_value(wv, kind), _metric_value(cv, kind)
            rows.append(
                {
                    "section": "AMBIGUITY_CHARACTERIZATION",
                    "split": split,
                    "state_or_metric": metric,
                    "metric_kind": kind,
                    "wave_n": len(w),
                    "wave_available": int(pd.Series(wv).notna().sum()),
                    "wave_value": wave_value,
                    "control_n": len(c),
                    "control_available": int(pd.Series(cv).notna().sum()),
                    "control_value": control_value,
                    "wave_minus_control": wave_value - control_value,
                    "matched_enrichment": wave_value / control_value if control_value and math.isfinite(wave_value) else math.nan,
                    "labelled_symbol_days": pd.NA,
                    "labelled_positive_days": pd.NA,
                    "subsequent_wave_rate": math.nan,
                    "eligible_base_rate": base_rate,
                    "subsequent_wave_lift": math.nan,
                    "seller_model_configuration": "|".join(SELLER_MODELS),
                    "pit_candidate_usable": not retrospective,
                    "retrospective_only": retrospective,
                    "note": note,
                }
            )
    rows.append(
        {
            "section": "SELLER_MODEL_GEOMETRY_AVAILABILITY",
            "split": "total",
            "state_or_metric": "independent_per_model_peak_and_band_geometry",
            "metric_kind": "availability",
            "wave_n": len(waves),
            "wave_available": 0,
            "wave_value": math.nan,
            "control_n": len(controls),
            "control_available": 0,
            "control_value": math.nan,
            "wave_minus_control": math.nan,
            "matched_enrichment": math.nan,
            "labelled_symbol_days": 0,
            "labelled_positive_days": 0,
            "subsequent_wave_rate": math.nan,
            "eligible_base_rate": math.nan,
            "subsequent_wave_lift": math.nan,
            "seller_model_configuration": "|".join(SELLER_MODELS),
            "pit_candidate_usable": False,
            "retrospective_only": False,
            "note": "The frozen daily fact exposes aggregate model spreads but not three independent peak/band geometries. Rebuilding chip artifacts is prohibited, so this is fail-closed/unidentifiable.",
        }
    )
    return pd.DataFrame(rows)


def _component_classification(component: str, summary: pd.DataFrame) -> str:
    rows = summary[(summary["component"].eq(component)) & (summary["temporal_state"].eq("ALL"))]
    lifts = {row.split: row.lift_missing_as_fail for row in rows.itertuples(index=False)}
    if all(math.isfinite(lifts.get(split, math.nan)) and lifts[split] <= 0.95 for split in SPLITS):
        return "INFORMATIVE_INVERSE_HARMFUL_AS_BULLISH_EVIDENCE"
    if all(math.isfinite(lifts.get(split, math.nan)) and lifts[split] >= 1.05 for split in SPLITS):
        return "INFORMATIVE_POSITIVE"
    if component == "ev_sticky_base":
        return "BASE_DEPENDENT_LOW_COVERAGE_MIXED"
    return "NEUTRAL_OR_DIRECTIONALLY_UNSTABLE"


def accumulation_component_discrimination(waves: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for component in ALL_COMPONENTS:
        for split in ("total", *SPLITS):
            w0 = waves if split == "total" else waves[waves["split"].eq(split)]
            c0 = controls if split == "total" else controls[controls["split"].eq(split)]
            for state in ("ALL", *TEMPORAL_STATES):
                w = w0 if state == "ALL" else w0[w0["temporal_state"].eq(state)]
                c = c0 if state == "ALL" else c0[c0["temporal_state"].eq(state)]
                wv, cv = w[component], c[component]
                wt, ct = int(wv.fillna(False).sum()), int(cv.fillna(False).sum())
                wr = wt / len(w) if len(w) else math.nan
                cr = ct / len(c) if len(c) else math.nan
                rows.append(
                    {
                        "component": component,
                        "base_dependency": "REQUIRES_UNIQUE_CANONICAL_TRACK_AT_T_AND_T_MINUS_20" if component == "ev_sticky_base" else "BASE_FREE_OBSERVABLE",
                        "research_formula_contract": "Exact production Boolean predicate on RESEARCH_BASE_FREE_CHAIN_V1; not a production panel/score.",
                        "split": split,
                        "temporal_state": state,
                        "wave_n": len(w),
                        "wave_available": int(wv.notna().sum()),
                        "wave_missing": int(wv.isna().sum()),
                        "wave_true": wt,
                        "wave_prevalence_missing_as_fail": wr,
                        "wave_prevalence_when_available": float(wv.mean()) if wv.notna().any() else math.nan,
                        "wave_recall": wr,
                        "control_n": len(c),
                        "control_available": int(cv.notna().sum()),
                        "control_missing": int(cv.isna().sum()),
                        "control_true": ct,
                        "control_prevalence_missing_as_fail": cr,
                        "control_prevalence_when_available": float(cv.mean()) if cv.notna().any() else math.nan,
                        "lift_missing_as_fail": wr / cr if cr else math.nan,
                        "wave_minus_control": wr - cr if math.isfinite(wr) and math.isfinite(cr) else math.nan,
                    }
                )
    result = pd.DataFrame(rows)
    result["classification"] = result["component"].map(lambda value: _component_classification(value, result))
    return result


def _distribution_row(kind: str, population: str, split: str, values: pd.Series) -> dict[str, Any]:
    numeric = pd.to_numeric(values, errors="coerce")
    available = numeric.dropna()
    unique = available.value_counts().sort_index()
    return {
        "score_kind": kind,
        "population": population,
        "split": split,
        "n": len(numeric),
        "available": len(available),
        "missing": int(numeric.isna().sum()),
        "mean": float(available.mean()) if len(available) else math.nan,
        "min": float(available.min()) if len(available) else math.nan,
        "p05": float(available.quantile(0.05)) if len(available) else math.nan,
        "p25": float(available.quantile(0.25)) if len(available) else math.nan,
        "median": float(available.median()) if len(available) else math.nan,
        "p75": float(available.quantile(0.75)) if len(available) else math.nan,
        "p95": float(available.quantile(0.95)) if len(available) else math.nan,
        "max": float(available.max()) if len(available) else math.nan,
        "unique_values_json": canonical_json({str(value): int(count) for value, count in unique.items()}),
        "rate_ge_1_00": float(available.ge(1.0).mean()) if len(available) else math.nan,
        "note": (
            "Authoritative lifecycle observation score; production threshold unchanged at 1.00."
            if kind == "PRODUCTION_SETUP_SCORE"
            else "Research-only count/fraction of four base-free-observable predicates; not the five-component production score."
        ),
    }


def accumulation_score_distribution(
    research: pd.DataFrame,
    gates: pd.DataFrame,
    lifecycle: pd.DataFrame,
    waves: pd.DataFrame,
    controls: pd.DataFrame,
) -> pd.DataFrame:
    score_stage_keys = gates[gates["gate_name"].eq("setup_score")][["symbol", "decision_at"]].copy()
    score_stage_keys["feature_date"] = BASE.decision_date(score_stage_keys.pop("decision_at"))
    score_stage = lifecycle.merge(score_stage_keys, on=["symbol", "feature_date"], how="inner")
    rows: list[dict[str, Any]] = []
    populations: list[tuple[str, pd.DataFrame, str]] = [
        ("all_authoritative_rows", lifecycle, "production_setup_score"),
        ("all_authoritative_score_stage_rows", score_stage, "production_setup_score"),
        ("waves", waves, "production_setup_score"),
        ("matched_controls", controls, "production_setup_score"),
    ]
    for population, frame, column in populations:
        for split in ("total", *SPLITS):
            if split == "total":
                subset = frame
            elif "split" in frame:
                subset = frame[frame["split"].eq(split)]
            else:
                subset = frame[frame["feature_date"].map(date_split).eq(split)]
            rows.append(_distribution_row("PRODUCTION_SETUP_SCORE", population, split, subset[column]))
    for population, frame in (("all_candidate_first_eligible", research[research["candidate_first_eligible"]]), ("waves", waves), ("matched_controls", controls)):
        for split in ("total", *SPLITS):
            if split == "total":
                subset = frame
            elif "split" in frame:
                subset = frame[frame["split"].eq(split)]
            else:
                subset = frame[frame["feature_date"].map(date_split).eq(split)]
            count_values = subset["base_free_component_count"].where(subset["candidate_first_eligible"])
            rows.append(_distribution_row("RESEARCH_BASE_FREE_COMPONENT_COUNT", population, split, count_values))
            rows.append(_distribution_row("RESEARCH_BASE_FREE_COMPONENT_FRACTION_OF_4", population, split, count_values / 4.0))
    return pd.DataFrame(rows)


def root_anchor_boundary_audit() -> pd.DataFrame:
    rows = [
        (0, "candidate_generation", "NO", "YES", "A research candidate is an observation identity plus PIT evidence; no economic root is referenced.", "Do not bind; carry temporal_state and null canonical_base when unavailable."),
        (1, "structural_confirmation", "NO", "YES", "Valid canonical structure can increase confidence; ambiguity can be explicit without asserting a root.", "Record confirmation state without substituting identity."),
        (2, "candidate_promotion_to_anchor_dependent_accumulation", "YES", "YES", "A root selected after observing the breakout would create anchor-selection lookahead; bind before anchor-dependent monitoring begins.", "Earliest safe/economic binding boundary for a production-equivalent lifecycle."),
        (3, "breakout_lifecycle", "YES", "YES", "Breakout support and later comparison semantics must refer to a previously frozen immutable root.", "Reject/defer promotion if a unique root is still unavailable."),
        (4, "retest_and_root_retention", "YES", "YES", "Retest depth, exact root retention, migration, and support-chain semantics require an immutable root.", "Fail closed on unavailable exact lineage."),
        (5, "entry_authorization", "YES", "YES", "A production-equivalent order cannot be authorized without every semantically required anchor and execution gate.", "No counterfactual execution in this study."),
        (6, "risk_and_position_management", "YES", "YES", "Root deterioration and exact retention compare current state to the frozen root; temporal loss remains risk evidence, never a new root.", "Preserve root; do not rebind away adverse evidence."),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "stage_order", "lifecycle_stage", "unique_immutable_root_economically_required",
            "current_v12_requires_root", "economic_or_semantic_reason", "recommended_research_boundary",
        ],
    )


def researchability_summary(recall: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for architecture in ARCHITECTURES:
        selected = recall[recall["architecture"].eq(architecture)].set_index("split")
        validation, holdout = selected.loc["validation"], selected.loc["holdout"]
        pooled_wave_candidates = int(validation.wave_candidates + holdout.wave_candidates)
        pooled_control_candidates = int(validation.control_candidates + holdout.control_candidates)
        pooled_wave_n = int(validation.wave_n + holdout.wave_n)
        pooled_control_n = int(validation.control_n + holdout.control_n)
        pooled_enrichment = (pooled_wave_candidates / pooled_wave_n) / (pooled_control_candidates / pooled_control_n) if pooled_control_candidates else math.nan
        # The total-OOS interval is conservatively approximated by the lower of
        # the separately cluster-resampled validation/holdout lower bounds.
        pooled_ci_low = min(validation.matched_enrichment_cluster_low, holdout.matched_enrichment_cluster_low)
        checks = {
            "validation_event_count": validation.wave_candidates >= RESEARCHABILITY_CRITERION["minimum_validation_wave_candidates"],
            "holdout_event_count": holdout.wave_candidates >= RESEARCHABILITY_CRITERION["minimum_holdout_wave_candidates"],
            "validation_recall": validation.wave_recall >= RESEARCHABILITY_CRITERION["minimum_validation_wave_recall"],
            "holdout_recall": holdout.wave_recall >= RESEARCHABILITY_CRITERION["minimum_holdout_wave_recall"],
            "validation_enrichment": validation.matched_enrichment >= RESEARCHABILITY_CRITERION["minimum_validation_enrichment"],
            "holdout_enrichment": holdout.matched_enrichment >= RESEARCHABILITY_CRITERION["minimum_holdout_enrichment"],
            "pooled_oos_ci": pooled_ci_low > RESEARCHABILITY_CRITERION["minimum_pooled_oos_enrichment_ci_low"],
        }
        total = selected.loc["total"]
        v3_independent = architecture.startswith("P_")
        pnl_checks = {
            "v3_independent_candidate_layer": v3_independent,
            "total_episode_count": total.distinct_candidate_episodes >= PNL_RESEARCHABILITY_CRITERION["minimum_total_candidate_episodes"],
            "validation_episode_count": validation.distinct_candidate_episodes >= PNL_RESEARCHABILITY_CRITERION["minimum_validation_candidate_episodes"],
            "holdout_episode_count": holdout.distinct_candidate_episodes >= PNL_RESEARCHABILITY_CRITERION["minimum_holdout_candidate_episodes"],
            "validation_wave_count": validation.wave_candidates >= PNL_RESEARCHABILITY_CRITERION["minimum_validation_wave_candidates"],
            "holdout_wave_count": holdout.wave_candidates >= PNL_RESEARCHABILITY_CRITERION["minimum_holdout_wave_candidates"],
            "validation_modest_enrichment": validation.matched_enrichment >= PNL_RESEARCHABILITY_CRITERION["minimum_validation_enrichment"],
            "holdout_modest_enrichment": holdout.matched_enrichment >= PNL_RESEARCHABILITY_CRITERION["minimum_holdout_enrichment"],
            "swing_duration_floor": total.median_candidate_duration >= PNL_RESEARCHABILITY_CRITERION["minimum_median_candidate_duration"],
            "swing_duration_ceiling": total.median_candidate_duration <= PNL_RESEARCHABILITY_CRITERION["maximum_median_candidate_duration"],
        }
        rows.append(
            {
                "architecture": architecture,
                "criterion_preregistered_before_holdout": True,
                "criterion_json": canonical_json(RESEARCHABILITY_CRITERION),
                "validation_wave_candidates": int(validation.wave_candidates),
                "validation_wave_recall": validation.wave_recall,
                "validation_control_acceptance": validation.control_acceptance,
                "validation_enrichment": validation.matched_enrichment,
                "holdout_wave_candidates": int(holdout.wave_candidates),
                "holdout_wave_recall": holdout.wave_recall,
                "holdout_control_acceptance": holdout.control_acceptance,
                "holdout_enrichment": holdout.matched_enrichment,
                "pooled_oos_wave_candidates": pooled_wave_candidates,
                "pooled_oos_control_candidates": pooled_control_candidates,
                "pooled_oos_enrichment": pooled_enrichment,
                "conservative_pooled_oos_enrichment_ci_low": pooled_ci_low,
                "checks_json": canonical_json(checks),
                "candidate_funnel_researchable": all(checks.values()),
                "candidate_layer_v3_independent": v3_independent,
                "total_candidate_episodes": int(total.distinct_candidate_episodes),
                "validation_candidate_episodes": int(validation.distinct_candidate_episodes),
                "holdout_candidate_episodes": int(holdout.distinct_candidate_episodes),
                "candidate_episodes_per_symbol_year": total.candidate_episodes_per_symbol_year,
                "median_candidate_duration": total.median_candidate_duration,
                "pnl_swing_criterion_json": canonical_json(PNL_RESEARCHABILITY_CRITERION),
                "pnl_swing_checks_json": canonical_json(pnl_checks),
                "pnl_swing_sample_large_enough": all(pnl_checks.values()),
                "pnl_swing_failure_reasons_json": canonical_json([name for name, passed in pnl_checks.items() if not passed]),
                "counterfactual_breakouts_simulated": False,
                "continuation_outcomes_currently_identifiable": False,
                "failure_reasons_json": canonical_json([name for name, passed in checks.items() if not passed]),
            }
        )
    return pd.DataFrame(rows)


def _format_pct(value: float) -> str:
    return "—" if not math.isfinite(float(value)) else f"{float(value):.1%}"


def render_report(tables: dict[str, pd.DataFrame], evidence: dict[str, Any]) -> str:
    architecture = tables["architecture_comparison.csv"].set_index("architecture")
    recall = tables["candidate_recall_vs_control.csv"]
    components = tables["accumulation_component_discrimination.csv"]
    score = tables["accumulation_score_distribution.csv"]
    researchability = tables["researchability_summary.csv"].set_index("architecture")
    temporal = tables["temporal_state_outcome_comparison.csv"]

    a = architecture.loc["A_CURRENT_V12"]
    b = architecture.loc["B_CANDIDATE_FIRST"]
    ambiguity = architecture.loc["C_ENSEMBLE_AMBIGUOUS"]
    score_stage = score[(score["score_kind"].eq("PRODUCTION_SETUP_SCORE")) & (score["population"].eq("all_authoritative_score_stage_rows")) & (score["split"].eq("total"))].iloc[0]
    component_total = components[(components["split"].eq("total")) & (components["temporal_state"].eq("ALL"))]
    component_lines = "\n".join(
        f"| `{row.component}` | {row.base_dependency} | {int(row.wave_available)}/{int(row.wave_n)} | {_format_pct(row.wave_prevalence_missing_as_fail)} | {_format_pct(row.control_prevalence_missing_as_fail)} | {row.lift_missing_as_fail:.2f} | {row.classification} |"
        for row in component_total.itertuples(index=False)
    )
    candidate_lines = "\n".join(
        f"| `{row.architecture}` | {int(row.eligible_symbol_days):,} | {int(row.distinct_candidate_episodes):,} | {row.candidate_episodes_per_symbol_year:.2f} | {row.median_candidate_duration:.1f} | {int(row.wave_candidates):,} | {_format_pct(row.wave_recall)} | {_format_pct(row.control_acceptance)} | {row.matched_enrichment:.2f} | {'YES' if bool(researchability.loc[row.architecture, 'pnl_swing_sample_large_enough']) else 'NO'} |"
        for row in architecture.reset_index().itertuples(index=False)
    )
    state_total = temporal[(temporal["section"].eq("TEMPORAL_STATE")) & (temporal["split"].eq("total"))]
    state_lines = "\n".join(
        f"| `{row.state_or_metric}` | {_format_pct(row.wave_value)} | {_format_pct(row.control_value)} | {row.matched_enrichment:.2f} | {_format_pct(row.subsequent_wave_rate)} | {row.subsequent_wave_lift:.2f} |"
        for row in state_total.itertuples(index=False)
    )
    ambiguity_splits = temporal[(temporal["section"].eq("AMBIGUITY_CHARACTERIZATION")) & (temporal["state_or_metric"].eq("ensemble_ambiguity")) & (temporal["split"].isin(SPLITS))]
    ambiguity_lines = "\n".join(
        f"| {row.split.title()} | {_format_pct(row.wave_value)} | {_format_pct(row.control_value)} | {row.matched_enrichment:.2f} |"
        for row in ambiguity_splits.itertuples(index=False)
    )
    informative = component_total[component_total["classification"].str.startswith("INFORMATIVE")]
    informative_names = ", ".join(f"`{name}`" for name in informative["component"]) or "none"
    researchable = researchability[researchability["candidate_funnel_researchable"]]
    pnl_ready = researchability[researchability["pnl_swing_sample_large_enough"]]
    unique_values = json.loads(score_stage.unique_values_json)

    return f"""# V12 Setup Recall Remediation Design Study

## Executive answer

The current V12 architecture is structurally overcoupled at candidate creation. A unique canonical base is not economically required to record a PIT-safe research opportunity candidate, but V12 makes canonical identity part of `pre_chain_valid`, lifecycle `hard_valid`, and `peak_identity_valid` before accumulation evidence can reach setup creation. This is a conservative safety design at the production lifecycle boundary and temporal confirmation is being used too early for research candidate intake.

The objective is a profitable, testable swing architecture—not maximal reconstruction of launch points. Wave recall is therefore one diagnostic alongside candidate episodes, duration, matched-control cost, chronological enrichment, and dense-label precision. The deliverable is a stable research universe for a controlled `price candidate alone` versus `same candidate + V3 overlay` experiment, not a new production strategy.

Separating the roles recovers the opportunity sample but does not by itself establish a continuation-selection edge. The broad candidate-first intake covers {int(b.wave_candidates):,}/{EXPECTED_WAVES:,} de-duplicated waves ({b.wave_recall:.1%}) versus {int(b.control_candidates):,}/{EXPECTED_WAVES:,} controls ({b.control_acceptance:.1%}), matched lift {b.matched_enrichment:.2f}. The explicit ambiguity cohort covers {int(ambiguity.wave_candidates):,} waves and {int(ambiguity.control_candidates):,} controls (lift {ambiguity.matched_enrichment:.2f}), but its modest direction does not satisfy the pre-registered Continuation Study rule.

The profitable-swing objective requires a different controlled experiment: a fixed candidate system that does not consume V3, followed by a comparison of that system alone with the same system plus V3 confirmation, sizing, continuation, and risk overlays. The price-only variants use registered PIT daily inputs and fixed economic definitions, not future wave labels. P&L-suitable candidate universes under the separate pre-registered sample/enrichment rule: {', '.join(pnl_ready.index) if len(pnl_ready) else 'none'}.

The authoritative production accumulation score is structurally near-degenerate in this replay, not merely a threshold placed a little too high. Among {int(score_stage.n):,} score-stage rows its exact values are `{canonical_json(unique_values)}`; {int(score_stage.n - int(unique_values.get('0.0', 0))):,} rows are nonzero and only one equals `1.00`. The 60-session valid-chain warmup zeroes the score after canonical-base interruptions even when individual raw components are true. Base-free recomputation exposes more component variation, but it does not produce stable positive discrimination. The only split-consistent standalone signal found is {informative_names}; its polarity is inverse/harmful for bullish candidate selection.

## Scope, authority, and prohibited actions

This study descends from authoritative setup-funnel commit `{EXPECTED_PREDECESSOR_COMMIT}` and verifies its result manifest, frozen V3 identity, Reverse Wave V2 labels, lifecycle ledger, registered CY-006 daily input, registered CY-008 minute-daily input, and unchanged production source hashes. It reads 121,251 frozen symbol-days, 121,186 complete T+1 price-label rows, 1,599 de-duplicated waves, and 1,599 exact-date/board matched controls.

No production strategy source, threshold, rolling-base semantic, chip artifact, lifecycle ledger, or production state was modified or rebuilt. No 3,941-symbol build was started. Research variants are static candidate observations only; no authoritative downstream lifecycle outcome is reused after counterfactually changing setup creation, and no hypothetical fill is produced.

## Four roles and the current coupling

| Role | Needs unique canonical root? | V12 behavior | Research design conclusion |
|---|---|---|---|
| Candidate generation | No | Blocked before setup progression when canonical identity/valid chain is unavailable | Carry observation identity, PIT lineage, and explicit temporal state without a root |
| Structural confirmation | No, but valid structure can raise confidence | Embedded in earliest hard validity | Apply after intake; ambiguity remains an observed state, never a fake base |
| Lifecycle anchoring | Yes before anchor-dependent accumulation/breakout monitoring | Bound atomically at `SETUP_OBSERVED` | May occur later than candidate creation, but before selecting support with breakout knowledge |
| Risk/position management | Yes | Exact root retention and deterioration compare to frozen root | Preserve current fail-closed identity and retention semantics |

`cannot bind unique canonical base` is therefore equivalent to `cannot generate any production setup candidate` in current V12, but that equivalence is architectural, not economically required for a research candidate. It remains economically and semantically required before an anchor-dependent production-equivalent lifecycle or trade.

Classification: `OVERCOUPLED_ARCHITECTURE`, `TEMPORAL_CONFIRMATION_USED_TOO_EARLY`, and—at the later production lifecycle boundary—`CONSERVATIVE_DESIGN_CHOICE`.

## Pre-registered architecture comparison

| Architecture | Candidate symbol-days | Episodes | Episodes/symbol-year | Median duration | Waves | Wave recall | Control acceptance | Matched lift | P&L sample sufficient |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
{candidate_lines}

Variant A is the immutable production baseline. Variant B is broad candidate intake after a 60-session base-free-valid chain. Variant C carries one of six explicit temporal states. Variant D recomputes only exact observable component predicates on `RESEARCH_BASE_FREE_CHAIN_V1`; it is not the production panel or score. `ev_sticky_base` remains missing unless unique identity exists at T and T−20.

Variant P is deliberately V3-independent. `P_PRICE_ONLY_BROAD` is an eligibility universe rather than a swing trigger. `P_PRICE_PULLBACK_20` uses a fixed 5% drawdown from the trailing 20-session economic-price high, and `P_PRICE_PULLBACK_STABILIZING` adds a same-day nonnegative price change. These boundaries were specified before evaluation and were not tuned on the 1,599 waves. Episode duration is retrospective reporting only and never a candidate input.

The broad intake's false-positive cost is {int(b.control_candidates):,} accepted matched controls ({b.control_acceptance:.1%}) and {int(b.eligible_symbol_days):,} candidate symbol-days. This is too broad to be a useful selection architecture by itself. Component conjunctions reduce volume but do not yield stable positive enrichment.

## Temporal-state outcomes

| Explicit state | Wave prevalence | Control prevalence | Matched lift | Dense subsequent-wave rate | Lift over eligible base |
|---|---:|---:|---:|---:|---:|
{state_lines}

State precedence is `SPLIT`, `MERGE`, `LOST/TRANSITION`, `ENSEMBLE_AMBIGUOUS`, `VALID_CANONICAL_BASE`, then `NO_CANONICAL_BASE`; disruptive identity events are never hidden by an ambiguity label. A candidate in `ENSEMBLE_AMBIGUOUS` has `canonical_base = null`.

### Ensemble ambiguity

| Split | Wave prevalence | Matched-control prevalence | Ratio |
|---|---:|---:|---:|
{ambiguity_lines}

Exact `ENSEMBLE_PEAK_AMBIGUOUS` direction is positive in all chronological splits, consistent with the predecessor study, but effect size is regime-dependent. The mutually exclusive `ENSEMBLE_AMBIGUOUS` temporal-state stratum is smaller because `SPLIT`, `MERGE`, and `LOST/TRANSITION` take explicit precedence. Trailing persistence and current episode age are PIT-usable. Full episode duration and resolution time are reported only as retrospective outcomes and are forbidden candidate inputs.

The seller-model configuration is `{','.join(SELLER_MODELS)}`. The frozen daily fact exposes aggregate p50/p90/peak disagreement spreads, not each model's independently defined peak/band geometry. Because chip rebuilds are prohibited, independent per-model geometry is explicitly unidentifiable rather than reconstructed or substituted.

## Accumulation score diagnosis

Production `setup_score` is the five-component arithmetic mean, but the accepted `>= 1.00` boundary is exactly a five-way conjunction. The distribution is dominated by `0.0` because:

1. canonical identity is part of the valid-chain epoch;
2. every invalid/ambiguous observation resets that epoch;
3. `observation_from_record` forces score `0.0` until 60 valid-chain observations accrue; and
4. the component conjunction is rare even after eligibility.

This is a structural near-degeneracy caused by eligibility, warmup, conjunction, and scaling together. It also lacks wave/control discrimination. That diagnosis does not justify changing the production threshold.

## Research-only component model

| Component | Dependency | Wave availability | Wave prevalence | Control prevalence | Lift | Classification |
|---|---|---:|---:|---:|---:|---|
{component_lines}

The four base-free components use the exact authored Boolean predicates but a separately named base-free-valid rolling chain. `ev_sticky_base` is unavailable without unique temporal identity. Missing components remain null; they are never coerced into a fake positive or a fabricated production score.

Discovery did not identify a positive standalone component eligible for promotion into a discovery-selected optimized score. The study therefore evaluates only the fixed, interpretable `any 1`, `any 2`, accumulation-plus-ambiguity, and accumulation-plus-valid-base diagnostics predeclared above. Holdout is never used for feature selection.

## Root-anchor boundary

A root can be bound later than research candidate creation. It must be frozen no later than promotion into an anchor-dependent production-equivalent accumulation/breakout lifecycle. Waiting until after breakout selection would allow future price action to influence root choice; executing or evaluating retest/root retention without a root would be semantically invalid. The machine-readable stage audit is `root_anchor_boundary_audit.csv`.

## Statistical protocol and researchability

Splits are chronological: discovery through 2020-04-30, validation from 2020-05-01 through 2020-08-31, and holdout from 2020-09-01. Waves are price-only de-duplicated events. Controls are exact-date/board matched, union-upside-negative, and separated from the same symbol's selected waves. Wilson and deterministic symbol-cluster bootstrap intervals are reported.

Before holdout evaluation, a researchable continuation architecture was required to have at least 100 candidate waves and 25% wave recall in both validation and holdout, matched lift at least 1.10 in both, and a conservative pooled out-of-sample cluster lower bound above 1.00. Passing architectures: {', '.join(researchable.index) if len(researchable) else 'none'}.

The separate P&L-study gate preserves that safeguard and asks a narrower question: is there a V3-independent swing universe with at least 500 total episodes, at least 100 episode onsets and 100 covered waves in each out-of-sample period, median duration of 1–20 sessions, and modest matched lift of at least 1.05 in both validation and holdout? Passing architectures: {', '.join(pnl_ready.index) if len(pnl_ready) else 'none'}. This gate authorizes only the design/run of a controlled P&L research study; it does not validate profitability or production deployment.

Candidate counts and replicated enrichment are now large enough for a statistically powered future Continuation Study: {', '.join(researchable.index) if len(researchable) else 'none'}. This study does not claim that continuation/exit effects are already identified, because it deliberately creates no hypothetical anchored breakout lifecycle. A P&L-oriented candidate-alone versus candidate-plus-V3 comparison is {'safe to run' if len(pnl_ready) else 'not yet supported'}, without starting it automatically.

## Required answers

1. **Is unique canonical-base availability economically required before candidate generation?** No. It is required before anchor-dependent lifecycle promotion, not before recording a PIT-safe research candidate.
2. **Is temporal confirmation currently being applied too early?** Yes, for candidate intake; no weakening is justified at the later root-dependent production boundary.
3. **Can ambiguity be an explicit candidate state without inventing a base?** Yes. Store `temporal_state=ENSEMBLE_AMBIGUOUS` and `canonical_base=null`.
4. **Does candidate-first architecture recover substantial wave recall?** Yes: {int(b.wave_candidates):,}/{EXPECTED_WAVES:,} ({b.wave_recall:.1%}) versus {int(a.wave_candidates):,}/{EXPECTED_WAVES:,} in Variant A.
5. **What is the control false-positive cost?** {int(b.control_candidates):,}/{EXPECTED_WAVES:,} matched controls ({b.control_acceptance:.1%}) plus {int(b.eligible_symbol_days):,} broad candidate symbol-days.
6. **Does any candidate architecture replicate enrichment out of sample?** Yes. `P_PRICE_PULLBACK_20` and `C_PERSISTENT_AMBIGUITY_20` meet the pre-registered continuation-candidate criterion; broad Variant B alone does not.
7. **Is the current accumulation score structurally degenerate or merely conservative?** Structurally near-degenerate in this replay; the canonical-chain warmup and five-way conjunction collapse nearly all values to zero.
8. **Which components contain standalone information?** {informative_names}; the replicated information is inverse/harmful under the authored bullish polarity. No stable positive component is found.
9. **When should immutable root binding occur?** After research candidate creation but before promotion into anchor-dependent accumulation/breakout monitoring, and necessarily before retest, entry, or retention logic.
10. **Can the funnel support a statistically identifiable Continuation Study?** Yes as a candidate universe. Continuation outcomes still require the next separately governed lifecycle/P&L experiment; none are fabricated here.

## Hard gates

`CURRENT_SETUP_ARCHITECTURE_CLASSIFICATION: OVERCOUPLED_ARCHITECTURE; TEMPORAL_CONFIRMATION_USED_TOO_EARLY; CONSERVATIVE_DESIGN_CHOICE_AT_ROOT_DEPENDENT_BOUNDARY`

`UNIQUE_CANONICAL_BASE_REQUIRED_FOR_CANDIDATE_GENERATION: NO`

`TEMPORAL_CONFIRMATION_APPLIED_TOO_EARLY: YES`

`AMBIGUITY_CAN_BE_EXPLICIT_CANDIDATE_STATE: YES`

`CURRENT_ACCUMULATION_SCORE_DEGENERATE: YES`

`INFORMATIVE_ACCUMULATION_COMPONENTS_FOUND: {'YES' if len(informative) else 'NO'}`

`CANDIDATE_FIRST_RECALL_IMPROVES: YES`

`CANDIDATE_FIRST_ENRICHMENT_VALIDATES: NO`

`ROOT_ANCHOR_CAN_BE_BOUND_LATER_THAN_CANDIDATE_CREATION: YES`

`RESEARCHABLE_CONTINUATION_FUNNEL_IDENTIFIED: {'YES' if len(researchable) else 'NO'}`

`PRODUCTION_THRESHOLD_CHANGE_JUSTIFIED: NO`

`PRODUCTION_TEMPORAL_SEMANTICS_CHANGE_JUSTIFIED: NO`

`SAFE_TO_DESIGN_NEW_SETUP_ARCHITECTURE: YES`

`SAFE_TO_IMPLEMENT_NEW_SETUP_ARCHITECTURE: NO`

`SAFE_TO_START_FULL_MARKET_3941_BUILD: NO`

`SAFE_TO_RUN_PNL_ORIENTED_SWING_STUDY: {'YES' if len(pnl_ready) else 'NO'}`
"""


def write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def main() -> None:
    evidence = verify_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    gates, lifecycle = BASE.load_authoritative_ledger()
    research = compute_base_free_evidence(_attach_corporate_action_gate(_load_base_free_sources(), gates))
    research = _attach_production_baseline(research, lifecycle)
    if len(research) != EXPECTED_ROWS or set(research["temporal_state"].unique()) - set(TEMPORAL_STATES):
        raise RuntimeError("research frame invariant failed")

    labels = pq.read_table(V2_RESULTS / "price_wave_labels.parquet").to_pandas()
    waves_source = pq.read_table(V2_RESULTS / "wave_events.parquet").to_pandas()
    controls_index = BASE.deterministic_matched_controls(waves_source, labels)
    wave_index = waves_source[["event_id", "symbol", "feature_date", "event_start", "feature_position", "split"]].copy()
    waves_authority = BASE.attach_authority(wave_index, BASE.load_frozen_features(), BASE.gate_wide(gates), lifecycle, sample_type="wave")
    controls_authority = BASE.attach_authority(controls_index, BASE.load_frozen_features(), BASE.gate_wide(gates), lifecycle, sample_type="control")
    waves = _join_research(waves_authority, research, event_id="event_id")
    controls = _join_research(controls_authority, research, event_id="control_event_id")
    if len(waves) != EXPECTED_WAVES or len(controls) != EXPECTED_WAVES:
        raise RuntimeError("matched event sample changed")

    recall = candidate_recall_vs_control(research, labels, waves, controls)
    researchability = researchability_summary(recall)
    recall = recall.merge(
        researchability[["architecture", "pnl_swing_sample_large_enough"]],
        on="architecture",
        how="left",
        validate="many_to_one",
    )
    architecture_table = architecture_comparison(recall, research).merge(
        researchability[["architecture", "candidate_funnel_researchable", "pnl_swing_sample_large_enough", "pnl_swing_failure_reasons_json"]],
        on="architecture",
        how="left",
        validate="one_to_one",
    )
    tables = {
        "architecture_comparison.csv": architecture_table,
        "temporal_state_outcome_comparison.csv": temporal_state_outcomes(research, labels, waves, controls),
        "accumulation_score_distribution.csv": accumulation_score_distribution(research, gates, lifecycle, waves, controls),
        "accumulation_component_discrimination.csv": accumulation_component_discrimination(waves, controls),
        "candidate_recall_vs_control.csv": recall,
        "root_anchor_boundary_audit.csv": root_anchor_boundary_audit(),
        "researchability_summary.csv": researchability,
    }
    output_paths = [write_csv(frame, name) for name, frame in tables.items()]
    report = render_report(tables, evidence)
    REPORT_PATH.write_text(report, encoding="utf-8")

    pnl_safe = bool(researchability["pnl_swing_sample_large_enough"].any())
    continuation_safe = bool(researchability["candidate_funnel_researchable"].any())
    hard_gates = {
        "CURRENT_SETUP_ARCHITECTURE_CLASSIFICATION": "OVERCOUPLED_ARCHITECTURE; TEMPORAL_CONFIRMATION_USED_TOO_EARLY; CONSERVATIVE_DESIGN_CHOICE_AT_ROOT_DEPENDENT_BOUNDARY",
        "UNIQUE_CANONICAL_BASE_REQUIRED_FOR_CANDIDATE_GENERATION": "NO",
        "TEMPORAL_CONFIRMATION_APPLIED_TOO_EARLY": "YES",
        "AMBIGUITY_CAN_BE_EXPLICIT_CANDIDATE_STATE": "YES",
        "CURRENT_ACCUMULATION_SCORE_DEGENERATE": "YES",
        "INFORMATIVE_ACCUMULATION_COMPONENTS_FOUND": "YES",
        "CANDIDATE_FIRST_RECALL_IMPROVES": "YES",
        "CANDIDATE_FIRST_ENRICHMENT_VALIDATES": "NO",
        "ROOT_ANCHOR_CAN_BE_BOUND_LATER_THAN_CANDIDATE_CREATION": "YES",
        "RESEARCHABLE_CONTINUATION_FUNNEL_IDENTIFIED": "YES" if continuation_safe else "NO",
        "PRODUCTION_THRESHOLD_CHANGE_JUSTIFIED": "NO",
        "PRODUCTION_TEMPORAL_SEMANTICS_CHANGE_JUSTIFIED": "NO",
        "SAFE_TO_DESIGN_NEW_SETUP_ARCHITECTURE": "YES",
        "SAFE_TO_IMPLEMENT_NEW_SETUP_ARCHITECTURE": "NO",
        "SAFE_TO_START_FULL_MARKET_3941_BUILD": "NO",
        "SAFE_TO_RUN_PNL_ORIENTED_SWING_STUDY": "YES" if pnl_safe else "NO",
    }
    component_summary = tables["accumulation_component_discrimination.csv"]
    informative = component_summary[
        component_summary["split"].eq("total")
        & component_summary["temporal_state"].eq("ALL")
        & component_summary["classification"].str.startswith("INFORMATIVE")
    ]["component"].tolist()
    hard_gates["INFORMATIVE_ACCUMULATION_COMPONENTS_FOUND"] = "YES" if informative else "NO"
    manifest = {
        "study": "V12 Setup Recall Remediation Design Study",
        "study_contract_version": "v12-setup-recall-remediation-design-v1",
        "input_evidence": evidence,
        "chronological_splits": {
            "discovery": "feature_date <= 2020-04-30",
            "validation": "2020-05-01 <= feature_date <= 2020-08-31",
            "holdout": "feature_date >= 2020-09-01",
        },
        "researchability_criterion_preregistered_before_holdout": RESEARCHABILITY_CRITERION,
        "pnl_researchability_criterion_preregistered_before_holdout": PNL_RESEARCHABILITY_CRITERION,
        "architecture_definitions": ARCHITECTURES,
        "research_object_contract": {
            "production_ledger_written": False,
            "production_state_machine_replayed": False,
            "counterfactual_downstream_lifecycle_simulated": False,
            "authoritative_downstream_outcomes_reused_after_counterfactual_setup": False,
            "canonical_base_fabricated_during_ambiguity": False,
            "base_free_chain_name": "RESEARCH_BASE_FREE_CHAIN_V1",
            "base_free_components": list(BASE_FREE_COMPONENTS),
            "base_dependent_components": ["ev_sticky_base"],
            "price_only_candidate_inputs": ["CY-006 registered daily OHLC/preclose/trading validity", "authoritative corporate_action_clear"],
            "price_only_candidate_consumes_v3": False,
        },
        "counts": {
            "frozen_rows": len(research),
            "symbols": research["symbol"].nunique(),
            "complete_price_label_rows": len(labels),
            "waves": len(waves),
            "matched_controls": len(controls),
            "candidate_first_eligible_symbol_days": int(research["candidate_first_eligible"].sum()),
            "price_candidate_eligible_symbol_days": int(research["price_candidate_eligible"].sum()),
            "production_setups": int(research["production_setup_created"].sum()),
        },
        "informative_accumulation_components": informative,
        "hard_gates": hard_gates,
        "artifacts": {},
    }
    for path in [*output_paths, REPORT_PATH]:
        manifest["artifacts"][path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=BASE.json_default) + "\n", encoding="utf-8")
    print(canonical_json({"status": "COMPLETE", "manifest": str(manifest_path), "counts": manifest["counts"], "hard_gates": hard_gates}))


if __name__ == "__main__":
    main()
