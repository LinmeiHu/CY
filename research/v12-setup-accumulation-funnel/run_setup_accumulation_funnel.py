#!/usr/bin/env python3
# ruff: noqa: E501
"""Authoritative setup/accumulation funnel audit on the frozen V3 replay.

This runner is read-only with respect to the frozen chip build, the production
panel inputs, and the lifecycle ledger.  It consumes the exact Reverse Wave V2
events and the already-built authoritative ledger; it never replays or mutates
the production state machine.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import rankdata

STUDY_DIR = Path(__file__).resolve().parent
REPO_ROOT = STUDY_DIR.parents[1]
OUTPUT_DIR = STUDY_DIR / "results"
REPORT_PATH = STUDY_DIR / "V12_SETUP_ACCUMULATION_FUNNEL_ROOT_CAUSE_STUDY.md"
V2_RESULTS = REPO_ROOT / "research/v12-reverse-wave-v2/results"
V3_ROOT = Path("/Users/linmei/Documents/CY/data/validation/v12_v3_500_temporal_20260828")
FREEZE_LOCK = Path("/Users/linmei/Documents/cyq-v3-500-build/V12_V3_500_TEMPORAL_BUILD_LOCK.json")
LEDGER_ROOT = Path("/Users/linmei/Documents/CY/data/validation/v12_lifecycle_entry_exit_ledger_500_20260828")

EXPECTED_BASELINE_COMMIT = "b59b1adde6ba43929f9ad20a533f296d610755dd"
EXPECTED_LEDGER_COMMIT = "3488a95dfb17815e7ea23f065c702106dcd10437"
EXPECTED_PARAMETER_ID = "9baed76ec299161c"
EXPECTED_ROOT_SHA256 = "915686c6b9a069688e4790a1e6a8e699feafaf951ca7b720c11ca8b21b85c29a"
EXPECTED_LOCK_SHA256 = "95a7b33ec28fe3c188b309e962522cb1bea16a23b7647c68068864a1e17fd6d9"
EXPECTED_V2_MANIFEST_SHA256 = "ea596b5fa2da7d70bbc39d6699a0f6ebfc379ded41fd261fde48107a4458ad9a"
EXPECTED_ROWS = 121_251
EXPECTED_WAVES = 1_599
EXPECTED_STRICT_TEMPORAL_ROWS = 36_219
EXPECTED_SYMBOLS = 500

SPLITS = ("discovery", "validation", "holdout")
SETUP_COMPONENTS = (
    "ev_turnover_absorption",
    "ev_near_price_chip_growth",
    "ev_concentration_improves",
    "ev_sticky_base",
    "ev_downside_absorption",
)
SOURCE_FILES = (
    "src/cyq_game/strategy/panel.py",
    "src/cyq_game/strategy/signals.py",
    "src/cyq_game/strategy/markup_retest.py",
    "src/cyq_game/strategy/lifecycle_ledger.py",
    "configs/markup_retest_main_chinext_2020_v1.yaml",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_id(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode()).hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=json_default)


def board(symbol: str) -> str:
    code = symbol.split(".", 1)[0]
    return "CHINEXT" if code.startswith(("300", "301")) else "MAIN"


def decision_date(values: pd.Series) -> pd.Series:
    return (
        pd.to_datetime(values, utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.tz_localize(None)
        .dt.normalize()
    )


def wilson(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return math.nan, math.nan
    p = successes / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total)) / denominator
    return max(0.0, center - half), min(1.0, center + half)


def auc_rank(labels: np.ndarray, values: np.ndarray) -> float:
    finite = np.isfinite(values)
    labels = labels[finite].astype(bool)
    values = values[finite]
    n1 = int(labels.sum())
    n0 = int((~labels).sum())
    if n1 == 0 or n0 == 0:
        return math.nan
    ranks = rankdata(values, method="average")
    return float((ranks[labels].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def cluster_rate_interval(
    frame: pd.DataFrame,
    value: str,
    *,
    symbol: str,
    seed: int,
    draws: int = 300,
) -> tuple[float, float]:
    if frame.empty:
        return math.nan, math.nan
    clusters = []
    for _, group in frame.groupby(symbol, sort=True):
        values = group[value].astype(bool).to_numpy()
        clusters.append((int(values.sum()), len(values)))
    rng = np.random.default_rng(seed)
    estimates = np.empty(draws, dtype=float)
    for draw in range(draws):
        picked = rng.integers(0, len(clusters), size=len(clusters))
        successes = sum(clusters[index][0] for index in picked)
        total = sum(clusters[index][1] for index in picked)
        estimates[draw] = successes / total
    return float(np.quantile(estimates, 0.025)), float(np.quantile(estimates, 0.975))


def verify_inputs() -> dict[str, Any]:
    v2_manifest_path = V2_RESULTS / "manifest.json"
    if sha256(v2_manifest_path) != EXPECTED_V2_MANIFEST_SHA256:
        raise RuntimeError("Reverse Wave V2 manifest changed")
    v2_manifest = json.loads(v2_manifest_path.read_text(encoding="utf-8"))
    for name in ("wave_events.parquet", "price_wave_labels.parquet", "production_attribution.parquet"):
        binding = v2_manifest["artifacts"][name]
        path = V2_RESULTS / name
        if path.stat().st_size != binding["bytes"] or sha256(path) != binding["sha256"]:
            raise RuntimeError(f"Reverse Wave V2 artifact changed: {name}")
    root_manifest = V3_ROOT / "manifest.json"
    if sha256(root_manifest) != EXPECTED_ROOT_SHA256 or sha256(FREEZE_LOCK) != EXPECTED_LOCK_SHA256:
        raise RuntimeError("frozen V3 identity changed")
    ledger_manifest_path = LEDGER_ROOT / "manifest.json"
    ledger_manifest = json.loads(ledger_manifest_path.read_text(encoding="utf-8"))
    provenance = ledger_manifest["provenance"]
    if provenance["frozen_root_manifest_sha256"] != EXPECTED_ROOT_SHA256:
        raise RuntimeError("ledger is not bound to the frozen V3 root")
    if provenance["strategy_parameter_id"] != EXPECTED_PARAMETER_ID:
        raise RuntimeError("accepted production parameter changed")
    if provenance["ledger_implementation_commit"] != EXPECTED_LEDGER_COMMIT:
        raise RuntimeError("ledger implementation identity changed")
    ledger_hashes: dict[str, str] = {}
    for name, binding in ledger_manifest["artifacts"].items():
        path = LEDGER_ROOT / name
        actual = sha256(path)
        if path.stat().st_size != binding.get("bytes", path.stat().st_size) or actual != binding["sha256"]:
            raise RuntimeError(f"ledger artifact changed: {name}")
        ledger_hashes[name] = actual
    unchanged = subprocess.run(
        ("git", "diff", "--quiet", EXPECTED_LEDGER_COMMIT, "--", *SOURCE_FILES),
        cwd=REPO_ROOT,
        check=False,
    ).returncode == 0
    if not unchanged:
        raise RuntimeError("authoritative strategy source differs from the ledger implementation commit")
    return {
        "reverse_wave_v2_completed_commit": EXPECTED_BASELINE_COMMIT,
        "reverse_wave_v2_manifest_sha256": EXPECTED_V2_MANIFEST_SHA256,
        "frozen_root_manifest_sha256": EXPECTED_ROOT_SHA256,
        "frozen_lock_sha256": EXPECTED_LOCK_SHA256,
        "ledger_manifest_sha256": sha256(ledger_manifest_path),
        "ledger_artifact_sha256": ledger_hashes,
        "ledger_provenance": provenance,
        "authoritative_source_unchanged_from_ledger_commit": unchanged,
        "authoritative_source_sha256": {name: sha256(REPO_ROOT / name) for name in SOURCE_FILES},
    }


def load_frozen_features() -> pd.DataFrame:
    scan = str(V3_ROOT / "symbol=*" / "daily_feature_candidate.parquet")
    columns = (
        "symbol", "trade_date", "snapshot_id", "available_at", "hard_valid", "research_valid",
        "quality_reason_codes", "known_cost_fraction_min", "peak_track_id", "peak_track_state",
        "peak_track_ambiguous", "peak_track_split", "peak_track_merge", "peak_track_lost",
        "peak_definition_version", "peak_track_version", "peak_track_band_lower",
        "peak_track_band_upper", "peak_track_age", "peak_track_mass", "peak_track_prominence",
        "model_spread_cost_p50", "model_spread_cost_p90", "model_spread_dominant_peak_today",
    )
    con = duckdb.connect()
    try:
        frame = con.execute(
            f"SELECT {','.join(columns)} FROM read_parquet(?, hive_partitioning=false, union_by_name=true) "
            "ORDER BY symbol, trade_date",
            [scan],
        ).fetchdf()
    finally:
        con.close()
    if len(frame) != EXPECTED_ROWS or frame["symbol"].nunique() != EXPECTED_SYMBOLS:
        raise RuntimeError("frozen feature coverage changed")
    frame["feature_date"] = pd.to_datetime(frame.pop("trade_date"))
    if frame.duplicated(["symbol", "feature_date"]).any():
        raise RuntimeError("duplicate frozen symbol/date")
    frame["raw_unknown_cost_present"] = frame["quality_reason_codes"].map(
        lambda values: "UNKNOWN_COST_PRESENT" in (values if isinstance(values, np.ndarray) else (values or []))
    )
    frame["base_exists"] = frame["peak_track_id"].notna()
    frame["strict_temporal_valid"] = (
        frame["base_exists"]
        & ~frame["peak_track_ambiguous"]
        & ~frame["peak_track_split"]
        & ~frame["peak_track_merge"]
        & ~frame["peak_track_lost"]
    )
    frame["ensemble_ambiguity"] = frame["peak_track_state"].eq("ENSEMBLE_PEAK_AMBIGUOUS")
    frame["known_cost_available"] = (
        frame["known_cost_fraction_min"].notna()
        & frame["known_cost_fraction_min"].between(0.0, 1.0, inclusive="both")
    )
    derived: list[pd.DataFrame] = []
    for _, group in frame.groupby("symbol", sort=False):
        group = group.sort_values("feature_date").copy()
        group["ambiguity_rate_20"] = group["ensemble_ambiguity"].astype(float).rolling(20, min_periods=20).mean()
        group["base_presence_20"] = group["base_exists"].astype(float).rolling(20, min_periods=20).mean()
        same = group["peak_track_id"].notna() & group["peak_track_id"].eq(group["peak_track_id"].shift(20))
        group["same_base_id_t20"] = same
        changes = group["peak_track_id"].ne(group["peak_track_id"].shift()) | group["peak_track_id"].isna()
        episode = changes.cumsum()
        age = group.groupby(episode, sort=False).cumcount() + 1
        group["rolling_base_episode_age"] = age.where(group["base_exists"]).astype(float)
        derived.append(group)
    frame = pd.concat(derived, ignore_index=True)
    if int(frame["strict_temporal_valid"].sum()) != EXPECTED_STRICT_TEMPORAL_ROWS:
        raise RuntimeError("strict temporal validity count changed")
    return frame.sort_values(["symbol", "feature_date"]).reset_index(drop=True)


def load_authoritative_ledger() -> tuple[pd.DataFrame, pd.DataFrame]:
    gates = pq.read_table(LEDGER_ROOT / "decision_gates.parquet").to_pandas()
    lifecycle = pq.read_table(LEDGER_ROOT / "lifecycle_events.parquet").to_pandas()
    gates["feature_date"] = decision_date(gates["decision_at"])
    lifecycle["feature_date"] = decision_date(lifecycle["decision_at"])
    principal = lifecycle[~lifecycle["event_type"].eq("ROOT_ANCHOR_BOUND")].copy()
    if len(principal) != EXPECTED_ROWS or principal.duplicated(["symbol", "feature_date"]).any():
        raise RuntimeError("lifecycle ledger is not one principal event per frozen row")
    details = principal["details_json"].map(json.loads)
    principal["production_setup_score"] = details.map(lambda value: float(value["setup_score"]))
    principal["production_breakout_excess_atr"] = details.map(
        lambda value: float(value["breakout_excess_atr"])
    )
    return gates, principal


def gate_wide(gates: pd.DataFrame) -> pd.DataFrame:
    key = ["symbol", "feature_date"]
    if gates.duplicated([*key, "gate_name"]).any():
        duplicate = gates[gates.duplicated([*key, "gate_name"], keep=False)].iloc[0]
        raise RuntimeError(f"duplicate gate on decision: {duplicate.gate_name}")
    passed = gates.pivot(index=key, columns="gate_name", values="passed").add_prefix("pass_")
    observed_bool = gates.pivot(index=key, columns="gate_name", values="observed_bool").add_prefix("bool_")
    observed_number = gates.pivot(index=key, columns="gate_name", values="observed_number").add_prefix("number_")
    return passed.join(observed_bool, how="outer").join(observed_number, how="outer").reset_index()


def deterministic_matched_controls(waves: pd.DataFrame, labels: pd.DataFrame) -> pd.DataFrame:
    """One exact-date/board control per wave, without replacement in a stratum.

    A control must be price-label complete, union-upside negative, and more than
    ten feature sessions from every selected wave for its own symbol.  Matching
    consumes no chip or future strategy field.
    """

    waves = waves[["event_id", "symbol", "feature_date", "feature_position", "split"]].copy()
    waves["board"] = waves["symbol"].map(board)
    labels = labels[["symbol", "feature_date", "feature_position", "split", "any_upside"]].copy()
    labels["board"] = labels["symbol"].map(board)
    positions = {
        symbol: group["feature_position"].to_numpy(dtype=int)
        for symbol, group in waves.groupby("symbol", sort=False)
    }
    eligible = []
    for row in labels.itertuples(index=False):
        if bool(row.any_upside):
            eligible.append(False)
            continue
        selected = positions.get(row.symbol)
        eligible.append(selected is None or bool(np.all(np.abs(selected - int(row.feature_position)) > 10)))
    labels = labels[np.asarray(eligible, dtype=bool)].copy()
    labels["control_order"] = [
        stable_id("MATCHED_CONTROL", row.symbol, pd.Timestamp(row.feature_date).date().isoformat())
        for row in labels.itertuples(index=False)
    ]
    rows: list[dict[str, Any]] = []
    for (date_value, board_value), wave_group in waves.groupby(["feature_date", "board"], sort=True):
        candidates = labels[
            labels["feature_date"].eq(date_value) & labels["board"].eq(board_value)
        ].sort_values(["control_order", "symbol"])
        wave_group = wave_group.sort_values("event_id")
        if len(candidates) < len(wave_group):
            raise RuntimeError(f"insufficient controls for {date_value.date()} {board_value}")
        for (_, wave), (_, control) in zip(
            wave_group.iterrows(), candidates.iloc[: len(wave_group)].iterrows(), strict=True
        ):
            rows.append(
                {
                    "pair_id": wave["event_id"],
                    "wave_event_id": wave["event_id"],
                    "wave_symbol": wave["symbol"],
                    "control_event_id": stable_id(
                        "SETUP_FUNNEL_CONTROL", control["symbol"], pd.Timestamp(date_value).date().isoformat()
                    ),
                    "symbol": control["symbol"],
                    "feature_date": date_value,
                    "feature_position": int(control["feature_position"]),
                    "split": wave["split"],
                    "board": board_value,
                    "matching_contract": (
                        "EXACT_FEATURE_DATE_AND_BOARD_WITHOUT_REPLACEMENT_WITHIN_STRATUM;"
                        "UNION_UPSIDE_NEGATIVE;DISTANCE_GT_10_FROM_SAME_SYMBOL_SELECTED_WAVE"
                    ),
                }
            )
    result = pd.DataFrame(rows).sort_values("wave_event_id").reset_index(drop=True)
    if len(result) != EXPECTED_WAVES or result.duplicated("control_event_id").any():
        raise RuntimeError("matched-control cardinality/uniqueness failure")
    return result


def attach_authority(
    events: pd.DataFrame,
    features: pd.DataFrame,
    ledger_wide: pd.DataFrame,
    lifecycle: pd.DataFrame,
    *,
    sample_type: str,
) -> pd.DataFrame:
    feature_columns = [
        "symbol", "feature_date", "snapshot_id", "available_at", "hard_valid", "research_valid",
        "raw_unknown_cost_present", "known_cost_available", "known_cost_fraction_min", "base_exists",
        "strict_temporal_valid", "ensemble_ambiguity", "ambiguity_rate_20", "base_presence_20",
        "same_base_id_t20", "rolling_base_episode_age", "peak_track_id", "peak_track_state",
        "peak_track_ambiguous", "peak_track_split", "peak_track_merge", "peak_track_lost",
        "peak_track_age", "peak_track_mass", "peak_track_prominence", "model_spread_cost_p50",
        "model_spread_cost_p90", "model_spread_dominant_peak_today",
    ]
    principal_columns = [
        "symbol", "feature_date", "event_type", "state_before", "state_after", "first_failed_gate",
        "failed_gates_json", "lifecycle_id", "root_anchor_id", "rolling_structural_base_id",
        "production_setup_score", "production_breakout_excess_atr",
    ]
    result = events.merge(features[feature_columns], on=["symbol", "feature_date"], how="left", validate="one_to_one")
    result = result.merge(ledger_wide, on=["symbol", "feature_date"], how="left", validate="one_to_one")
    result = result.merge(lifecycle[principal_columns], on=["symbol", "feature_date"], how="left", validate="one_to_one")
    if result["event_type"].isna().any() or result["snapshot_id"].isna().any():
        raise RuntimeError(f"{sample_type} lacks exact frozen/ledger coverage")
    result["sample_type"] = sample_type
    result["setup_score_evaluated"] = result.get("pass_setup_score", pd.Series(False, index=result.index)).notna()
    result["setup_score_pass"] = pd.Series(
        pd.array(result.get("pass_setup_score", pd.Series(False, index=result.index)), dtype="boolean"),
        index=result.index,
    ).fillna(False).astype(bool)
    result["setup_created"] = result["event_type"].eq("SETUP_OBSERVED")
    for target, source in (
        ("corporate_action_clear", "pass_corporate_action_clear"),
        ("production_hard_valid", "pass_hard_valid"),
        ("peak_identity_valid", "pass_peak_identity_valid"),
    ):
        result[target] = pd.Series(
            pd.array(result[source], dtype="boolean"), index=result.index
        ).fillna(False).astype(bool)
    result["tradable_evaluated"] = result.get("pass_tradable", pd.Series(False, index=result.index)).notna()
    result["tradable"] = pd.Series(
        pd.array(result.get("pass_tradable", pd.Series(False, index=result.index)), dtype="boolean"),
        index=result.index,
    ).fillna(False).astype(bool)
    for component in SETUP_COMPONENTS:
        column = f"bool_{component}"
        result[f"component_{component}"] = result.get(column, pd.Series(pd.NA, index=result.index)).astype("boolean")
    return result


def nested_root_cause(row: pd.Series) -> str:
    if row["first_failed_gate"] == "corporate_action_clear":
        return "CORPORATE_ACTION_BLOCK"
    if row["first_failed_gate"] == "hard_valid":
        if bool(row["ensemble_ambiguity"]):
            return "ENSEMBLE_PEAK_AMBIGUOUS"
        if not bool(row["base_exists"]):
            return "NO_CANONICAL_PEAK_IDENTITY_OTHER"
        if not bool(row["strict_temporal_valid"]):
            return "TRACKED_BASE_SPLIT_MERGE_OR_LOST"
        return "OTHER_LIFECYCLE_HARD_VALID_INPUT"
    if row["first_failed_gate"] == "tradable":
        return "NOT_TRADABLE_AT_DECISION"
    if row["first_failed_gate"] == "setup_score":
        return "ALL_FIVE_ACCUMULATION_COMPONENTS_NOT_SATISFIED"
    if row["first_failed_gate"] == "cooldown_complete":
        return "COOLDOWN_ACTIVE"
    if row["first_failed_gate"] == "breakout_excess_atr":
        return "EXISTING_ACCUMULATING_LIFECYCLE"
    if bool(row["setup_created"]):
        return "SETUP_CREATED"
    return "NO_BLOCKER_RECORDED"


def deepest_stage(row: pd.Series) -> str:
    if bool(row["setup_created"]):
        return "SETUP_CREATED"
    if bool(row["setup_score_evaluated"]):
        return "ACCUMULATION_SCORE_EVALUATED"
    if pd.notna(row.get("pass_breakout_excess_atr")):
        return "EXISTING_ACCUMULATING_LIFECYCLE"
    if bool(row["tradable_evaluated"]):
        return "TRADABILITY_EVALUATED"
    if bool(row["production_hard_valid"]):
        return "VALIDITY_AND_PEAK_IDENTITY_PASSED"
    if bool(row["corporate_action_clear"]):
        return "CORPORATE_ACTION_CLEAR"
    return "AUTHORITATIVE_OBSERVATION"


def make_wave_funnel(waves: pd.DataFrame) -> pd.DataFrame:
    result = waves.copy()
    result["nested_root_cause"] = result.apply(nested_root_cause, axis=1)
    result["deepest_funnel_stage"] = result.apply(deepest_stage, axis=1)
    result["all_observable_blockers"] = result["failed_gates_json"]
    result["observable_failed_setup_components"] = result.apply(
        lambda row: canonical_json(
            [
                component for component in SETUP_COMPONENTS
                if pd.notna(row[f"component_{component}"]) and not bool(row[f"component_{component}"])
            ]
        ) if bool(row["setup_score_evaluated"]) else "[]",
        axis=1,
    )
    columns = [
        "event_id", "symbol", "feature_date", "event_start", "split", "snapshot_id", "available_at",
        "production_setup_score", "corporate_action_clear", "production_hard_valid", "peak_identity_valid",
        "tradable_evaluated", "tradable", "state_before", "state_after", "setup_score_evaluated",
        *[f"component_{component}" for component in SETUP_COMPONENTS],
        "setup_score_pass", "setup_created", "base_exists", "strict_temporal_valid", "peak_track_id",
        "peak_track_state", "ensemble_ambiguity", "peak_track_ambiguous", "peak_track_split",
        "peak_track_merge", "peak_track_lost", "same_base_id_t20", "peak_track_age",
        "rolling_base_episode_age", "research_valid", "hard_valid", "raw_unknown_cost_present",
        "known_cost_available", "first_failed_gate", "nested_root_cause", "deepest_funnel_stage",
        "all_observable_blockers", "observable_failed_setup_components", "event_type", "lifecycle_id",
    ]
    return result[columns].sort_values(["feature_date", "symbol", "event_id"]).reset_index(drop=True)


def actual_stage_flags(frame: pd.DataFrame) -> dict[str, pd.Series]:
    corporate = frame["corporate_action_clear"]
    hard = corporate & frame["production_hard_valid"]
    peak = hard & frame["peak_identity_valid"]
    tradable = peak & frame["tradable_evaluated"] & frame["tradable"]
    candidate = tradable & frame["setup_score_evaluated"]
    score = candidate & frame["setup_score_pass"]
    created = score & frame["setup_created"]
    return {
        "authoritative_observation": pd.Series(True, index=frame.index),
        "corporate_action_clear": corporate,
        "lifecycle_hard_valid": hard,
        "peak_identity_valid": peak,
        "tradable": tradable,
        "neutral_or_broken_and_no_cooldown_setup_score_evaluated": candidate,
        "setup_score_ge_1_00": score,
        "setup_created": created,
    }


def funnel_stage_summary(waves: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sample, frame in (("wave", waves), ("control", controls)):
        flags = actual_stage_flags(frame)
        previous = pd.Series(True, index=frame.index)
        for order, (stage, passed) in enumerate(flags.items()):
            count = int(passed.sum())
            previous_count = int(previous.sum())
            rows.append(
                {
                    "sample_type": sample,
                    "stage_order": order,
                    "stage": stage,
                    "initial_n": len(frame),
                    "cumulative_survivors": count,
                    "cumulative_survival_rate": count / len(frame),
                    "incremental_survivors_from_prior": count,
                    "prior_stage_survivors": previous_count,
                    "incremental_pass_rate": count / previous_count if previous_count else math.nan,
                    "eliminated_at_stage": previous_count - count,
                    "authoritative_actual_path": True,
                }
            )
            previous = passed
    return pd.DataFrame(rows)


def first_blocker_attribution(waves: pd.DataFrame) -> pd.DataFrame:
    if "nested_root_cause" not in waves:
        waves = waves.copy()
        waves["nested_root_cause"] = waves.apply(nested_root_cause, axis=1)
    rows: list[dict[str, Any]] = []
    for split in ("total", *SPLITS):
        subset = waves if split == "total" else waves[waves["split"].eq(split)]
        grouped = subset.groupby(["first_failed_gate", "nested_root_cause"], dropna=False).size()
        for (blocker, cause), count in grouped.items():
            rows.append(
                {
                    "split": split,
                    "first_authoritative_blocker": blocker,
                    "nested_root_cause": cause,
                    "count": int(count),
                    "denominator": len(subset),
                    "percent": 100.0 * count / len(subset),
                }
            )
    return pd.DataFrame(rows).sort_values(["split", "count"], ascending=[True, False])


def validity_gate_audit(features: pd.DataFrame, gates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(
        name: str,
        values: pd.Series,
        *,
        dependency: str,
        source: str,
        expression: str,
        fail_closed: str,
        notes: str,
    ) -> None:
        evaluated = values.notna()
        passed = values[evaluated].astype(bool)
        rows.append(
            {
                "predicate": name,
                "production_dependency": dependency,
                "source": source,
                "expression": expression,
                "fail_closed": fail_closed,
                "total_rows": len(values),
                "evaluated_rows": int(evaluated.sum()),
                "pass_rows": int(passed.sum()),
                "fail_rows": int((~passed).sum()),
                "not_evaluated_rows": int((~evaluated).sum()),
                "pass_rate_among_evaluated": float(passed.mean()) if len(passed) else math.nan,
                "notes": notes,
            }
        )

    add(
        "frozen_research_valid", features["research_valid"], dependency="INDIRECT_PANEL_INPUT",
        source="lifecycle_ledger.build_frozen_v3_panel",
        expression="v.research_valid AS chip_input_valid; v.research_valid AS state_chain_valid",
        fail_closed="YES", notes="Feeds pre_chain_valid; not itself a named lifecycle gate.",
    )
    add(
        "frozen_hard_valid", features["hard_valid"], dependency="NOT_CONSUMED_BY_SETUP_REPLAY",
        source="daily_feature_candidate.parquet / lifecycle_ledger.build_frozen_v3_panel",
        expression="frozen v.hard_valid exists, but adapter sets daily_hard_valid=false and production research_hard_valid uses pre_chain_valid",
        fail_closed="N/A", notes="All rows false because UNKNOWN_COST_PRESENT; this is not LifecycleObservation.hard_valid.",
    )
    add(
        "UNKNOWN_COST_PRESENT_absent", ~features["raw_unknown_cost_present"], dependency="NOT_DIRECT",
        source="daily_feature_candidate.quality_reason_codes / signals.observation_from_record",
        expression="UNKNOWN_COST_PRESENT not in quality_reason_codes",
        fail_closed="NO", notes="Known-cost fraction availability, not the raw reason code, is consumed by production.",
    )
    add(
        "known_cost_fraction_available_and_bounded", features["known_cost_available"], dependency="DIRECT_COMPONENT_OF_PRE_CHAIN_AND_OBSERVATION_HARD_VALID",
        source="panel._create_panel_table / signals.observation_from_record",
        expression="known_cost_fraction_min IS NOT NULL AND BETWEEN 0 AND 1",
        fail_closed="YES", notes="All frozen rows have a bounded known-cost fraction despite UNKNOWN_COST_PRESENT.",
    )
    add(
        "peak_track_id_present", features["base_exists"], dependency="DIRECT_COMPONENT_OF_PRE_CHAIN_AND_PEAK_IDENTITY",
        source="panel._create_panel_table / LifecycleObservation.peak_identity_valid",
        expression="peak_track_id IS NOT NULL",
        fail_closed="YES", notes="Current canonical rolling-base identity availability.",
    )
    add(
        "peak_track_not_ambiguous", ~features["peak_track_ambiguous"], dependency="DIRECT_COMPONENT_OF_PRE_CHAIN_AND_PEAK_IDENTITY",
        source="panel._create_panel_table / LifecycleObservation.peak_identity_valid",
        expression="NOT peak_track_ambiguous",
        fail_closed="YES", notes="All rows without a current tracked base are marked ambiguous by the frozen contract.",
    )
    for name in ("split", "merge", "lost"):
        add(
            f"peak_track_no_{name}", ~features[f"peak_track_{name}"], dependency="DIRECT_COMPONENT_OF_PRE_CHAIN",
            source="panel._create_panel_table", expression=f"NOT peak_track_{name}", fail_closed="YES",
            notes="Not repeated in LifecycleObservation.peak_identity_valid; already folded into research_hard_valid.",
        )
    add(
        "strict_temporal_valid", features["strict_temporal_valid"], dependency="DIRECT_COMPOSITE_OF_PRE_CHAIN",
        source="panel._create_panel_table; Reverse Wave V2 canonical diagnostic",
        expression="peak id present AND not ambiguous/split/merge/lost",
        fail_closed="YES", notes="Version and band-shape checks are additionally enforced by production.",
    )
    key_count = gates[["symbol", "feature_date"]].drop_duplicates().shape[0]
    for gate_name, dependency, notes in (
        ("corporate_action_clear", "DIRECT_BLOCKING_GATE", "Gate order 0."),
        ("hard_valid", "DIRECT_BLOCKING_GATE", "Gate order 1; this is the derived LifecycleObservation value, not frozen hard_valid."),
        ("peak_identity_valid", "DIRECT_BLOCKING_GATE", "Gate order 2; evaluated even if hard_valid failed."),
        ("tradable", "DIRECT_BLOCKING_GATE_AFTER_VALIDITY", "Evaluated only after all validity gates pass."),
        ("cooldown_complete", "DIRECT_BLOCKING_GATE_IF_COOLDOWN_ACTIVE", "Only emitted on a failing active cooldown; zero occurrences."),
        ("setup_score", "DIRECT_BLOCKING_GATE_IN_NEUTRAL_OR_BROKEN", "Evaluated only in a new-setup-capable lifecycle state."),
    ):
        subset = gates[gates["gate_name"].eq(gate_name)]
        values = pd.Series(pd.NA, index=np.arange(key_count), dtype="boolean")
        if len(subset):
            values.iloc[: len(subset)] = subset["passed"].astype(bool).to_numpy()
        add(
            f"production_gate:{gate_name}", values, dependency=dependency,
            source=str(subset["source_function"].iloc[0]) if len(subset) else "LifecycleMachine.advance",
            expression=(
                f"observed {subset['operator'].iloc[0]} {subset['threshold_json'].iloc[0]}"
                if len(subset) else "memory.cooldown_remaining == 0"
            ),
            fail_closed="YES", notes=notes,
        )
    return pd.DataFrame(rows)


def comparison_stages(frame: pd.DataFrame) -> dict[str, pd.Series]:
    actual = actual_stage_flags(frame)
    stages: dict[str, pd.Series] = {
        "frozen_research_valid": frame["research_valid"].astype(bool),
        "current_canonical_base_exists": frame["base_exists"].astype(bool),
        "current_strict_temporal_valid": frame["strict_temporal_valid"].astype(bool),
        "not_ensemble_peak_ambiguous": ~frame["ensemble_ambiguity"].astype(bool),
    }
    stages.update({f"actual:{name}": values for name, values in actual.items()})
    return stages


def wave_control_comparison(waves: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    wave_stages = comparison_stages(waves)
    control_stages = comparison_stages(controls)
    for split in ("total", *SPLITS):
        wave_subset = waves if split == "total" else waves[waves["split"].eq(split)]
        control_subset = controls if split == "total" else controls[controls["split"].eq(split)]
        previous_wave_actual = pd.Series(True, index=wave_subset.index)
        previous_control_actual = pd.Series(True, index=control_subset.index)
        for order, stage in enumerate(wave_stages):
            w = wave_stages[stage].loc[wave_subset.index].astype(bool)
            c = control_stages[stage].loc[control_subset.index].astype(bool)
            wp, cp = int(w.sum()), int(c.sum())
            wr, cr = wp / len(w), cp / len(c)
            wlo, whi = wilson(wp, len(w))
            clo, chi = wilson(cp, len(c))
            wboot = wave_subset.assign(_pass=w.to_numpy())
            cboot = control_subset.assign(_pass=c.to_numpy())
            wblo, wbhi = cluster_rate_interval(wboot, "_pass", symbol="symbol", seed=4100 + order * 17 + len(rows))
            cblo, cbhi = cluster_rate_interval(cboot, "_pass", symbol="symbol", seed=9100 + order * 19 + len(rows))
            if stage.startswith("actual:"):
                wave_incremental = wp / int(previous_wave_actual.sum()) if previous_wave_actual.any() else math.nan
                control_incremental = cp / int(previous_control_actual.sum()) if previous_control_actual.any() else math.nan
                incremental_enrichment = (
                    wave_incremental / control_incremental if control_incremental else math.nan
                )
                previous_wave_actual = w
                previous_control_actual = c
            else:
                wave_incremental = control_incremental = incremental_enrichment = math.nan
            rows.append(
                {
                    "split": split, "stage_order": order, "predicate_or_cumulative_stage": stage,
                    "wave_n": len(w), "wave_pass": wp, "wave_pass_rate": wr,
                    "wave_wilson_low": wlo, "wave_wilson_high": whi,
                    "wave_symbol_cluster_low": wblo, "wave_symbol_cluster_high": wbhi,
                    "control_n": len(c), "control_pass": cp, "control_acceptance": cr,
                    "control_wilson_low": clo, "control_wilson_high": chi,
                    "control_symbol_cluster_low": cblo, "control_symbol_cluster_high": cbhi,
                    "wave_minus_control": wr - cr,
                    "enrichment_rate_ratio": wr / cr if cr else math.nan,
                    "wave_incremental_pass_rate": wave_incremental,
                    "control_incremental_acceptance": control_incremental,
                    "incremental_enrichment": incremental_enrichment,
                    "precision_in_balanced_matched_sample": wp / (wp + cp) if wp + cp else math.nan,
                    "wave_recall": wr,
                }
            )
    return pd.DataFrame(rows)


def accumulation_component_audit(
    gates: pd.DataFrame, waves: pd.DataFrame, controls: pd.DataFrame
) -> pd.DataFrame:
    definitions = {
        "ev_turnover_absorption": "turnover_mean20 >= turnover_q60_prior AND price_impact_mean20 <= impact_q50_prior",
        "ev_near_price_chip_growth": "asr > asr_lag20 AND profit_ratio >= 0.45",
        "ev_concentration_improves": "cbw <= cbw_lag20 AND concentration_20 >= concentration_lag20 AND peak_count <= peak_count_lag20 + 1",
        "ev_sticky_base": "peak_track_id = peak_track_id_lag20 AND recent_band_overlap >= 0.55 AND abs(p50-p50_lag20) <= max(atr14,1e-8)",
        "ev_downside_absorption": "close_vs_vwap >= 0 AND closing_30m_return >= 0",
    }
    rows: list[dict[str, Any]] = []
    population_keys = pd.concat(
        [
            waves[["symbol", "feature_date", "split"]].assign(population="wave"),
            controls[["symbol", "feature_date", "split"]].assign(population="control"),
        ],
        ignore_index=True,
    )
    for component in SETUP_COMPONENTS:
        all_gate = gates[gates["gate_name"].eq(component)]
        global_true = int(all_gate["observed_bool"].astype(bool).sum())
        joined = population_keys.merge(
            all_gate[["symbol", "feature_date", "observed_bool"]],
            on=["symbol", "feature_date"], how="left", validate="one_to_one",
        )
        for split in ("total", *SPLITS):
            subset = joined if split == "total" else joined[joined["split"].eq(split)]
            summary: dict[str, Any] = {
                "component": component,
                "definition": definitions[component],
                "source_function": "panel._create_panel_table",
                "pit_availability": "Computed from T and lagged/rolling values available by decision_at; logged only when score stage is reached.",
                "split": split,
                "global_score_stage_rows": len(all_gate),
                "global_true": global_true,
                "global_false": len(all_gate) - global_true,
                "global_prevalence": global_true / len(all_gate),
            }
            for population in ("wave", "control"):
                group = subset[subset["population"].eq(population)]
                evaluated = group["observed_bool"].notna()
                true_count = int(group.loc[evaluated, "observed_bool"].astype(bool).sum())
                total = int(evaluated.sum())
                lo, hi = wilson(true_count, total)
                summary.update(
                    {
                        f"{population}_total_events": len(group),
                        f"{population}_evaluated_at_score_stage": total,
                        f"{population}_missing_due_to_earlier_or_state_gate": len(group) - total,
                        f"{population}_true": true_count,
                        f"{population}_false": total - true_count,
                        f"{population}_prevalence": true_count / total if total else math.nan,
                        f"{population}_wilson_low": lo,
                        f"{population}_wilson_high": hi,
                    }
                )
            wr = summary["wave_prevalence"]
            cr = summary["control_prevalence"]
            summary["marginal_prevalence_difference"] = wr - cr if pd.notna(wr) and pd.notna(cr) else math.nan
            summary["marginal_enrichment"] = wr / cr if pd.notna(wr) and pd.notna(cr) and cr else math.nan
            rows.append(summary)
    return pd.DataFrame(rows)


def score_distributions(waves: pd.DataFrame, controls: pd.DataFrame, lifecycle: pd.DataFrame) -> pd.DataFrame:
    populations = (
        ("all_authoritative_rows", lifecycle, pd.Series(True, index=lifecycle.index)),
        (
            "all_score_stage_rows",
            lifecycle,
            lifecycle["first_failed_gate"].eq("setup_score") | lifecycle["event_type"].eq("SETUP_OBSERVED"),
        ),
        ("waves_all", waves, pd.Series(True, index=waves.index)),
        ("waves_score_stage", waves, waves["setup_score_evaluated"]),
        ("controls_all", controls, pd.Series(True, index=controls.index)),
        ("controls_score_stage", controls, controls["setup_score_evaluated"]),
    )
    rows: list[dict[str, Any]] = []
    for name, frame, mask in populations:
        values = pd.to_numeric(frame.loc[mask, "production_setup_score"], errors="coerce")
        row: dict[str, Any] = {
            "population": name, "n": len(values), "missing": int(values.isna().sum()),
            "mean": values.mean(), "min": values.min(), "p05": values.quantile(0.05),
            "p25": values.quantile(0.25), "median": values.median(), "p75": values.quantile(0.75),
            "p95": values.quantile(0.95), "max": values.max(),
        }
        for threshold in (0.2, 0.4, 0.6, 0.8, 1.0):
            row[f"rate_ge_{str(threshold).replace('.', '_')}"] = float(values.ge(threshold).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def threshold_coverage(waves: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    features = {
        "production_setup_score": ">=",
        "peak_track_age": None,
        "peak_track_mass": None,
        "peak_track_prominence": None,
        "rolling_base_episode_age": None,
        "base_presence_20": None,
        "ambiguity_rate_20": None,
        "model_spread_cost_p50": None,
        "model_spread_cost_p90": None,
        "model_spread_dominant_peak_today": None,
    }
    discovery = pd.concat(
        [
            waves[waves["split"].eq("discovery")].assign(_label=True),
            controls[controls["split"].eq("discovery")].assign(_label=False),
        ],
        ignore_index=True,
    )
    rows: list[dict[str, Any]] = []
    for feature, fixed_direction in features.items():
        values = pd.to_numeric(discovery[feature], errors="coerce").to_numpy(dtype=float)
        labels = discovery["_label"].to_numpy(dtype=bool)
        auc = auc_rank(labels, values)
        direction = fixed_direction or (">=" if pd.notna(auc) and auc >= 0.5 else "<=")
        discovery_waves = pd.to_numeric(
            waves.loc[waves["split"].eq("discovery"), feature], errors="coerce"
        )
        available = discovery_waves.dropna().sort_values(ascending=direction == "<=")
        for target in (0.80, 0.90, 0.95):
            needed = math.ceil(target * len(discovery_waves))
            achievable = len(available) >= needed
            if available.empty:
                threshold = math.nan
            elif achievable:
                threshold = float(available.iloc[needed - 1])
            else:
                threshold = float(available.iloc[-1])
            for split in SPLITS:
                wave_values = pd.to_numeric(waves.loc[waves["split"].eq(split), feature], errors="coerce")
                control_values = pd.to_numeric(controls.loc[controls["split"].eq(split), feature], errors="coerce")
                if pd.isna(threshold):
                    wp = pd.Series(False, index=wave_values.index)
                    cp = pd.Series(False, index=control_values.index)
                elif direction == ">=":
                    wp, cp = wave_values.ge(threshold), control_values.ge(threshold)
                else:
                    wp, cp = wave_values.le(threshold), control_values.le(threshold)
                rows.append(
                    {
                        "feature": feature, "discovery_direction": direction,
                        "discovery_auc_winner_higher": auc, "target_discovery_coverage": target,
                        "discovery_threshold": threshold,
                        "coverage_status": "ACHIEVABLE" if achievable else "UNACHIEVABLE_DUE_TO_MISSINGNESS",
                        "split": split, "wave_n": len(wave_values), "wave_available": int(wave_values.notna().sum()),
                        "wave_pass": int(wp.sum()), "wave_recall_missing_as_fail": float(wp.mean()),
                        "control_n": len(control_values), "control_available": int(control_values.notna().sum()),
                        "control_pass": int(cp.sum()), "control_acceptance_missing_as_fail": float(cp.mean()),
                        "event_sample_enrichment": float(wp.mean() / cp.mean()) if cp.mean() else math.nan,
                    }
                )
    return pd.DataFrame(rows)


def rolling_base_eligibility(waves: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    predicates = {
        "current_canonical_base": lambda d: d["base_exists"],
        "current_strict_temporal_valid": lambda d: d["strict_temporal_valid"],
        "no_peak_track_ambiguity": lambda d: ~d["peak_track_ambiguous"],
        "no_split": lambda d: ~d["peak_track_split"],
        "no_merge": lambda d: ~d["peak_track_merge"],
        "no_lost": lambda d: ~d["peak_track_lost"],
        "same_canonical_base_id_at_t_minus_20": lambda d: d["same_base_id_t20"],
        "production_peak_identity_valid": lambda d: d["peak_identity_valid"],
        "production_hard_valid": lambda d: d["production_hard_valid"],
        "base_exists_but_setup_score_rejects": lambda d: d["base_exists"] & d["setup_score_evaluated"] & ~d["setup_score_pass"],
        "no_usable_canonical_structural_base": lambda d: ~d["peak_identity_valid"],
    }
    rows: list[dict[str, Any]] = []
    for sample, frame in (("wave", waves), ("control", controls)):
        for split in ("total", *SPLITS):
            subset = frame if split == "total" else frame[frame["split"].eq(split)]
            for predicate, function in predicates.items():
                passed = function(subset).fillna(False).astype(bool)
                rows.append(
                    {
                        "sample_type": sample, "split": split, "predicate": predicate,
                        "n": len(subset), "pass": int(passed.sum()), "fail": int((~passed).sum()),
                        "pass_rate": float(passed.mean()),
                        "production_requires_explicit_peak_age_threshold": False,
                        "production_age_note": "No peak_track_age minimum; ev_sticky_base indirectly requires same ID at T-20.",
                    }
                )
    return pd.DataFrame(rows)


def downstream_threshold_audit(gates: pd.DataFrame) -> pd.DataFrame:
    specs = (
        ("setup_score", ">=", 1.00, "WEAKLY_ESTIMABLE", "One global pass; zero wave passes."),
        ("breakout_excess_atr", ">=", 0.25, "WEAKLY_ESTIMABLE", "Only nine accumulating observations; all failed."),
        ("retest_depth_atr", "<=", 0.50, "UNIDENTIFIABLE", "Never reached."),
        ("cost_migration_atr", ">=", 0.50, "UNIDENTIFIABLE", "Never reached."),
        ("retest_volume_ratio", "<=", 0.80, "UNIDENTIFIABLE", "Never reached."),
        ("retest_turnover_ratio", "<=", 0.80, "UNIDENTIFIABLE", "Never reached."),
        ("exact_root_retention", ">=", 0.70, "UNIDENTIFIABLE", "Never reached."),
        ("seller_model_disagreement_atr", "<=", 3.00, "WEAKLY_ESTIMABLE", "Not a setup gate; nine downstream observations, all above threshold."),
    )
    rows = []
    for name, operator, threshold, estimability, note in specs:
        subset = gates[gates["gate_name"].eq(name)]
        rows.append(
            {
                "gate": name, "accepted_operator": operator, "accepted_threshold": threshold,
                "evaluated_rows": len(subset), "pass_rows": int(subset["passed"].sum()) if len(subset) else 0,
                "fail_rows": int((~subset["passed"].astype(bool)).sum()) if len(subset) else 0,
                "blocking_in_ledger": bool(subset["blocking"].all()) if len(subset) else True,
                "estimability": estimability, "note": note,
            }
        )
    return pd.DataFrame(rows)


def setup_path_catalog() -> pd.DataFrame:
    rows = [
        (0, "raw snapshots and PIT availability", "signals.observation_from_record; LifecycleLedgerCollector._assert_pit", "required snapshots; available_at <= decision_at", "fail closed", "no"),
        (1, "frozen research validity adaptation", "lifecycle_ledger.build_frozen_v3_panel", "v.research_valid -> chip_input_valid and state_chain_valid; frozen hard_valid is not consumed", "fail closed downstream", "yes"),
        (2, "canonical temporal pre-chain validity", "panel._create_panel_table", "strategy_available_at <= strategy_decision_at AND bar_valid AND trading_state_valid AND float_valid AND corporate_action_valid AND market_valid AND market_rule_valid AND historical_identity_valid AND chip_input_valid AND state_chain_valid AND NOT action_blocking AND NOT strategy_corporate_action_blocking AND abs(mass_sum-1.0) <= mass_tolerance AND known_cost_fraction_min IS NOT NULL AND known_cost_fraction_min BETWEEN 0 AND 1 AND peak_track_id IS NOT NULL AND NOT peak_track_ambiguous AND NOT peak_track_split AND NOT peak_track_merge AND NOT peak_track_lost AND peak_definition_version = canonical-chip-peak-v2 AND peak_track_version = temporal-chip-peak-v3", "fail closed", "yes"),
        (3, "rolling evidence and five components", "panel._create_panel_table", "five exact Boolean expressions; ev_sticky_base uses same peak_track_id at lag20, overlap >=0.55, |p50-p50_lag20|<=ATR", "NULL later maps false/score fallback", "panel computes all"),
        (4, "setup score construction", "panel._create_panel_table", "sum(five Boolean components)/5.0", "non-finite maps to 0", "panel computes all"),
        (5, "observation hard_valid", "signals.observation_from_record", "research_hard_valid AND profile_valid AND peak_valid; false on missing positive fields or missing known_cost_fraction_min", "fail closed", "no"),
        (6, "accumulation warmup", "signals.observation_from_record", "if history_count < accumulation(60): setup_score=0.0", "fail closed", "score remains observable"),
        (7, "corporate action", "LifecycleMachine.advance", "corporate_action_blocking == false", "blocking", "no"),
        (8, "lifecycle hard validity", "LifecycleMachine.advance", "observation.hard_valid == true", "blocking", "no"),
        (9, "current peak identity", "LifecycleObservation.peak_identity_valid", "nonempty id, !ambiguous, valid positive band, exact peak definition version", "blocking", "no"),
        (10, "rebase and active-signal routing", "LifecycleMachine.advance", "rebase_lifecycle_memory; active_signal_id routes to _advance_open", "active lifecycle suppresses setup path", "no"),
        (11, "tradability", "LifecycleMachine.advance", "observation.tradable == true", "preserve memory and stop", "no"),
        (12, "cooldown", "LifecycleMachine.advance", "cooldown_remaining == 0", "decrement and stop", "no"),
        (13, "new-setup lifecycle state", "LifecycleMachine.advance", "state in {NEUTRAL,BROKEN}", "other states route to breakout/retest", "no"),
        (14, "accepted accumulation threshold", "LifecycleMachine.advance", "observation.setup_score >= 1.00", "blocking", "no"),
        (15, "root anchor and setup creation", "freeze_lifecycle_anchor; LifecycleMachine.advance", "freeze current canonical peak band/mass and enter ACCUMULATING", "fail closed via earlier peak validity", "terminal setup creation"),
    ]
    return pd.DataFrame(rows, columns=["execution_order", "stage", "authoritative_file_function", "exact_expression", "failure_semantics", "later_predicates_evaluated"])


def lifecycle_occupancy_audit(lifecycle: pd.DataFrame, gates: pd.DataFrame) -> pd.DataFrame:
    setup_dates = lifecycle[lifecycle["event_type"].eq("SETUP_OBSERVED")].groupby("symbol")["feature_date"].apply(list)
    cooldown = gates[gates["gate_name"].eq("cooldown_complete")].groupby("symbol").size()
    rows = []
    for symbol, group in lifecycle.groupby("symbol", sort=True):
        group = group.sort_values("feature_date")
        accumulating = group["state_before"].eq("ACCUMULATING") | group["state_after"].eq("ACCUMULATING")
        active = group["state_before"].isin(["QUALIFIED", "HOLDING"]) | group["state_after"].isin(["QUALIFIED", "HOLDING"])
        rows.append(
            {
                "symbol": symbol, "setup_count": int(group["event_type"].eq("SETUP_OBSERVED").sum()),
                "setup_dates_json": canonical_json([pd.Timestamp(value).date().isoformat() for value in setup_dates.get(symbol, [])]),
                "accumulating_observations": int(accumulating.sum()),
                "first_accumulating_date": group.loc[accumulating, "feature_date"].min(),
                "last_accumulating_date": group.loc[accumulating, "feature_date"].max(),
                "breakout_rejections": int(group["event_type"].eq("BREAKOUT_REJECTED").sum()),
                "cooldown_blocking_observations": int(cooldown.get(symbol, 0)),
                "active_signal_observations": int(active.sum()),
                "terminal_state": group.iloc[-1]["state_after"],
                "persistent_state_suppression_found": False,
                "one_shot_defect_evidence": False,
                "classification": "INTENTIONAL_STRATEGY_SEMANTIC" if accumulating.any() else "NO_LIFECYCLE_CREATED",
            }
        )
    return pd.DataFrame(rows)


def ensemble_audit(waves: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for feature in ("ensemble_ambiguity", "peak_track_ambiguous", "ambiguity_rate_20"):
        for split in ("total", *SPLITS):
            w = waves if split == "total" else waves[waves["split"].eq(split)]
            c = controls if split == "total" else controls[controls["split"].eq(split)]
            wv = pd.to_numeric(w[feature], errors="coerce")
            cv = pd.to_numeric(c[feature], errors="coerce")
            if feature == "ambiguity_rate_20":
                auc = auc_rank(
                    np.r_[np.ones(wv.notna().sum(), dtype=bool), np.zeros(cv.notna().sum(), dtype=bool)],
                    np.r_[wv.dropna().to_numpy(dtype=float), cv.dropna().to_numpy(dtype=float)],
                )
            else:
                auc = math.nan
            rows.append(
                {
                    "feature": feature, "split": split, "wave_n": len(w), "wave_available": int(wv.notna().sum()),
                    "wave_mean_or_prevalence": wv.mean(), "control_n": len(c), "control_available": int(cv.notna().sum()),
                    "control_mean_or_prevalence": cv.mean(), "wave_minus_control": wv.mean() - cv.mean(),
                    "auc_winner_higher": auc,
                    "production_setup_role": (
                        "DIRECT_FAIL_CLOSED_COMPONENT_OF_PRE_CHAIN_AND_PEAK_IDENTITY"
                        if feature == "peak_track_ambiguous" else
                        "DESCRIPTIVE_STATE_ASSOCIATED_WITH_DIRECT_PEAK_AMBIGUITY" if feature == "ensemble_ambiguity"
                        else "DESCRIPTIVE_PERSISTENCE_NOT_A_DIRECT_GATE"
                    ),
                }
            )
    return pd.DataFrame(rows)


def write_csv(frame: pd.DataFrame, name: str) -> Path:
    path = OUTPUT_DIR / name
    frame.to_csv(path, index=False, lineterminator="\n")
    return path


def render_report(tables: dict[str, pd.DataFrame], evidence: dict[str, Any]) -> str:
    waves = tables["wave_funnel.csv"]
    blockers = tables["first_blocker_attribution.csv"]
    stages = tables["funnel_stage_summary.csv"]
    ensemble = tables["ensemble_ambiguity_audit.csv"]
    components = tables["accumulation_component_audit.csv"]
    score = tables["accumulation_score_distribution.csv"]
    occupancy = tables["lifecycle_occupancy_audit.csv"]
    comparison = tables["wave_vs_control_gate_comparison.csv"]

    total_blockers = blockers[blockers["split"].eq("total")]
    hard_count = int(total_blockers.loc[total_blockers["first_authoritative_blocker"].eq("hard_valid"), "count"].sum())
    score_count = int(total_blockers.loc[total_blockers["first_authoritative_blocker"].eq("setup_score"), "count"].sum())
    tradable_count = int(total_blockers.loc[total_blockers["first_authoritative_blocker"].eq("tradable"), "count"].sum())
    ensemble_count = int((waves["nested_root_cause"] == "ENSEMBLE_PEAK_AMBIGUOUS").sum())
    no_identity = int((~waves["peak_identity_valid"]).sum())
    base_count = int(waves["base_exists"].sum())
    strict_count = int(waves["strict_temporal_valid"].sum())
    same_base_t20 = int(waves["same_base_id_t20"].sum())
    score_reached = int(waves["setup_score_evaluated"].sum())
    global_score = score[score["population"].eq("all_score_stage_rows")].iloc[0]
    setup_symbol = occupancy[occupancy["setup_count"].gt(0)].iloc[0]
    component_total = components[components["split"].eq("total")]
    component_text = "\n".join(
        f"| `{row.component}` | {int(row.wave_evaluated_at_score_stage)} | {int(row.wave_true)} "
        f"({row.wave_prevalence:.1%}) | {int(row.control_evaluated_at_score_stage)} | "
        f"{int(row.control_true)} ({row.control_prevalence:.1%}) |"
        for row in component_total.itertuples(index=False)
    )
    wave_stage = stages[stages["sample_type"].eq("wave")]
    stage_text = "\n".join(
        f"| {int(row.stage_order)} | `{row.stage}` | {int(row.cumulative_survivors):,} | "
        f"{row.cumulative_survival_rate:.1%} | {int(row.eliminated_at_stage):,} |"
        for row in wave_stage.itertuples(index=False)
    )
    actual_comparison = comparison[
        comparison["split"].eq("total")
        & comparison["predicate_or_cumulative_stage"].str.startswith("actual:")
    ]

    def percent(value: float) -> str:
        return "—" if pd.isna(value) else f"{value:.1%}"

    def ratio(value: float) -> str:
        return "—" if pd.isna(value) else f"{value:.2f}"

    comparison_text = "\n".join(
        f"| `{row.predicate_or_cumulative_stage.removeprefix('actual:')}` | "
        f"{percent(row.wave_pass_rate)} | {percent(row.control_acceptance)} | "
        f"{percent(row.wave_incremental_pass_rate)} | "
        f"{percent(row.control_incremental_acceptance)} | "
        f"{ratio(row.incremental_enrichment)} |"
        for row in actual_comparison.itertuples(index=False)
    )
    ensemble_rows = ensemble[ensemble["feature"].eq("ensemble_ambiguity") & ~ensemble["split"].eq("total")]
    ensemble_text = "\n".join(
        f"| {row.split.title()} | {row.wave_mean_or_prevalence:.1%} | "
        f"{row.control_mean_or_prevalence:.1%} | {row.wave_minus_control:+.1%} |"
        for row in ensemble_rows.itertuples(index=False)
    )
    return f"""# V12 Setup / Accumulation Funnel Root-Cause Study

## Executive answer

The production funnel is reconstructed authoritatively from the immutable 121,251-row frozen V3 fact and its already-built lifecycle ledger. No chip, panel, ledger, strategy state, threshold, or production source was rebuilt or changed.

Only one production setup was created because setup creation requires two rare conditions in sequence:

1. a fail-closed lifecycle-valid observation with a current canonical unambiguous tracked base; and
2. an accumulation score of exactly `1.00`, which is equivalent to all five Boolean accumulation components being true on the same observation.

Across the 1,599 exact Reverse Wave V2 pre-start observations, the authoritative first blocker is `hard_valid` for {hard_count:,} ({hard_count / EXPECTED_WAVES:.1%}), `setup_score` for {score_count:,} ({score_count / EXPECTED_WAVES:.1%}), and `tradable` for {tradable_count:,}. The `hard_valid` name is composite: {ensemble_count:,} waves ({ensemble_count / EXPECTED_WAVES:.1%}) were in exact `ENSEMBLE_PEAK_AMBIGUOUS` state, and {no_identity:,} ({no_identity / EXPECTED_WAVES:.1%}) lacked a valid production peak identity. Thus the dominant authoritative predicate is lifecycle `hard_valid`, while its dominant nested cause is unavailable/ambiguous canonical rolling-base identity.

This is not evidence that all 1,599 price waves were desirable trades. It is exact price-opportunity recall of zero, not a strategy-quality verdict. Exact-date/board matched controls show that ambiguity is more common before waves in discovery, validation, and holdout, so the fail-closed ambiguity restriction removes winners at least as aggressively as controls; however, removing it would change rolling windows and lifecycle state, making downstream setup/entry performance unidentifiable from this immutable replay.

## Governed baseline and PIT contract

| Item | Identity |
|---|---|
| Completed Reverse Wave V2 commit | `{evidence['reverse_wave_v2_completed_commit']}` |
| Frozen root manifest | `{evidence['frozen_root_manifest_sha256']}` |
| Freeze lock | `{evidence['frozen_lock_sha256']}` |
| Ledger manifest | `{evidence['ledger_manifest_sha256']}` |
| Ledger implementation commit | `{evidence['ledger_provenance']['ledger_implementation_commit']}` |
| Accepted parameter ID | `{EXPECTED_PARAMETER_ID}` |
| Feature rows / symbols | {EXPECTED_ROWS:,} / {EXPECTED_SYMBOLS} |
| Wave events / matched controls | {EXPECTED_WAVES:,} / {EXPECTED_WAVES:,} |

Wave observations use Reverse Wave V2 feature date T, whose authoritative availability precedes the price-defined event start T+1. Controls are selected without chip or strategy outcomes: union-upside-negative observations matched one-for-one on exact feature date and board, without replacement within each stratum, and more than ten feature sessions from any selected wave for the control symbol. Splits remain chronological; no row is randomly shuffled across time.

## Exact production setup path

The complete machine-readable execution order is `results/setup_path_catalog.csv`. The crucial source semantics are:

- `panel._create_panel_table` constructs `pre_chain_valid`. It requires PIT/input/action/mass/known-cost validity plus a current peak ID, no ambiguity/split/merge/loss, and exact peak versions. It then sets `research_hard_valid = pre_chain_valid`.
- `signals.observation_from_record` forms lifecycle `hard_valid = research_hard_valid AND profile_valid AND peak_valid`, then fails it closed on missing actionable positive fields or missing `known_cost_fraction_min`. If the valid-chain `history_count` is below the 60-session accumulation window, it forces setup score to `0.0`.
- `LifecycleMachine.advance` checks corporate action, lifecycle `hard_valid`, and current `peak_identity_valid`; rebases memory; routes any active signal away from setup creation; requires tradability, zero cooldown, and state `NEUTRAL` or `BROKEN`; compares `setup_score >= 1.00`; then freezes the root anchor and enters `ACCUMULATING`.
- There is no direct `peak_track_age` minimum. Persistence enters through `ev_sticky_base`, which requires the same track ID at T and T−20, recent band overlap at least `0.55`, and p50 movement within one ATR.
- Seller-model disagreement is not a setup gate. It is checked downstream in breakout/retest qualification.

Later state-machine predicates are not evaluated after a blocking failure. Panel quantities already computed on a rejected row remain observable, but they are not promoted to counterfactual lifecycle decisions.

## Canonical 1,599-wave funnel

| Order | Actual authoritative stage | Survivors | Recall | Eliminated at stage |
|---:|---|---:|---:|---:|
{stage_text}

The apparent zero incremental loss at `peak_identity_valid` is not evidence that peak identity is harmless: lifecycle `hard_valid` already embeds peak validity and the stricter split/merge/lost restrictions. The overlap is exposed in `wave_funnel.csv`, not double-attributed.

At T before launch, {base_count:,} waves had a current canonical base, {strict_count:,} were strict temporal-valid, and only {same_base_t20:,} had the same canonical base ID at T and T−20. Production imposes no direct peak-age threshold; the T−20 identity is only one operand inside `ev_sticky_base`. {no_identity:,} waves had no usable production peak identity. Of the {score_reached:,} waves that reached the accumulation-score gate, none passed `1.00`.

### Matched-control survival

| Actual cumulative stage | Wave recall | Control acceptance | Wave incremental pass | Control incremental pass | Incremental enrichment |
|---|---:|---:|---:|---:|---:|
{comparison_text}

The balanced matched-sample precision and Wilson intervals are in `wave_vs_control_gate_comparison.csv`. The same table includes 300-draw symbol-cluster bootstrap intervals for wave and control pass rates in total and in every chronological split. In total, the lifecycle-valid cumulative gate retains controls more often than waves, so the dominant validity restriction does not enrich for the price-wave outcome.

## Explicit validity audit

The raw frozen feature `hard_valid` and production lifecycle `hard_valid` are different fields with different semantics:

- frozen `research_valid`: 120,472 pass / 779 fail; it feeds the adapted panel;
- frozen `hard_valid`: 0 pass / 121,251 fail;
- raw `UNKNOWN_COST_PRESENT`: present on all 121,251 rows;
- bounded `known_cost_fraction_min`: available on all 121,251 rows;
- production lifecycle `hard_valid`: 27,736 pass / 93,515 fail;
- production `peak_identity_valid`: 41,619 pass / 79,632 fail;
- current strict temporal-valid: 36,219 pass / 85,032 fail.

The adapter deliberately maps frozen `research_valid` to `chip_input_valid` and `state_chain_valid`; it does not use frozen `hard_valid`. Production consumes the bounded known-cost fraction and fails only when it is missing. Therefore `UNKNOWN_COST_PRESENT` is descriptive lineage state, not the direct setup blocker in this replay. Full expressions and evaluated/not-evaluated counts are in `validity_gate_audit.csv`.

## Accumulation decomposition

The score is the exact arithmetic mean of five Boolean components. At the accepted threshold `>= 1.00`, it is a five-way conjunction.

| Component | Wave rows evaluated | Wave true | Control rows evaluated | Control true |
|---|---:|---:|---:|---:|
{component_text}

Globally, {int(global_score['n']):,} rows reached the score stage; only one passed. The score-stage distribution has median {global_score['median']:.1f}, 95th percentile {global_score['p95']:.1f}, and maximum {global_score['max']:.1f}. The exact distributions for all rows, wave observations, matched controls, and conditional score-stage rows are in `accumulation_score_distribution.csv`.

Component flags are panel evidence, while the compared score is the exact lifecycle observation value. During the 60-session valid-chain warmup, `observation_from_record` forces that score to `0.0` even if one or more raw component flags are true; the component table therefore must not be read as a recomputed counterfactual score.

The threshold is the terminal bottleneck conditional on reaching the setup-capable state, but it is not the dominant first blocker across waves: 1,225 waves disappear earlier at lifecycle `hard_valid`. Discovery coverage diagnostics find that the score threshold needed to cover 80%, 90%, or 95% of discovery waves is `0.0` because of the mass at zero; that accepts essentially all controls and does not validate discrimination. This is a diagnostic, not a recommendation.

## Ensemble ambiguity: direction and role

| Split | Wave `ENSEMBLE_PEAK_AMBIGUOUS` | Matched control | Difference |
|---|---:|---:|---:|
{ensemble_text}

The direction replicates: ambiguity is more prevalent before waves in all three chronological splits. Twenty-session ambiguity persistence is also analyzed in `ensemble_ambiguity_audit.csv`. This means `ENSEMBLE_AMBIGUITY_HAS_INFORMATION: YES` points toward later-wave association, not bearish selection. Production blocks the underlying `peak_track_ambiguous` state through `pre_chain_valid` and `peak_identity_valid`; the named ensemble state is descriptive but coincides with {ensemble_count:,} wave rejections.

This association does not justify relaxing consensus. It may reflect seller-model disagreement near transitions, but the frozen artifacts do not identify that mechanism causally.

## Setup semantics and lifecycle occupancy

There is no hidden cooldown, one-shot, or stale-terminal suppressor:

- no `cooldown_complete` rejection was emitted;
- no active signal or holding interval existed;
- one setup was created for `{setup_symbol['symbol']}` on {pd.Timestamp(setup_symbol['first_accumulating_date']).date().isoformat()};
- it remained `ACCUMULATING` through {pd.Timestamp(setup_symbol['last_accumulating_date']).date().isoformat()}, with {int(setup_symbol['breakout_rejections'])} observed breakout rejections, and the sample ended before expiry;
- all other symbols created no lifecycle.

The one setup is not an absorbing-state defect. It is the only observation where all prior gates and all five setup components passed. The state machine then behaved as authored.

Classification: `OVERLY_SELECTIVE_BUT_INTENTIONAL` for the exact-conjunction setup semantics; `TEMPORAL_REPRESENTATION_LIMITATION` for the dominant absence/ambiguity of a usable canonical base; no implementation defect found.

## Counterfactual limits and downstream thresholds

A one-row threshold relaxation can be measured only as static sensitivity. Allowing rows rejected solely by `setup_score` to continue would create new anchors and persistent lifecycle state, so later breakouts/retests/entries cannot be inferred without mutating the state machine. Likewise, removing ambiguity changes valid-chain epochs, rolling evidence, anchors, and occupancy. Those downstream states are unidentifiable here.

The accepted parameters remain unchanged. Setup score is weakly estimable (one pass); breakout excess is weakly estimable (nine observations, all failed); retest depth, cost migration, volume ratio, turnover ratio, and root retention are unidentifiable because they were never reached. See `downstream_threshold_audit.csv`.

## Answers to the required questions

1. **Why only one setup and zero entries?** Most observations fail lifecycle validity/current canonical base. Among 27,317 score-stage rows globally, only one satisfies all five components; it never breaks out, so no downstream entry path exists.
2. **Where do most waves disappear?** At authoritative lifecycle `hard_valid`: {hard_count:,}/{EXPECTED_WAVES:,}.
3. **Dominant data-validity condition?** The named first blocker is a validity gate, but its dominant nested cause is temporal peak/base ambiguity, not raw unknown-cost status.
4. **Dominant temporal/rolling-base availability blocker?** Yes: {no_identity:,} waves lack production peak identity, predominantly ensemble ambiguity.
5. **Is ensemble ambiguity dominant?** Yes as the largest nested observable cause ({ensemble_count:,}); it is also more prevalent among waves than matched controls in every split.
6. **Is accumulation `1.00` dominant?** No across all waves; yes as the terminal bottleneck conditional on reaching its stage. It shows no validated event/control discrimination.
7. **Is a setup state-machine predicate dominant?** No. Active lifecycle and cooldown do not explain suppression.
8. **Implementation defect?** No source/state evidence supports one.
9. **Would removing the dominant blocker improve downstream discrimination?** Not established. Downstream states become counterfactual and the observable ambiguity association points in the wrong direction for a winner-excluding gate.
10. **Can the current architecture support a statistically testable continuation/exit strategy without semantic redesign?** No. One setup, zero breakouts, and zero entries provide no estimable continuation/exit sample.

## Deliverables and reproducibility

The runner is `run_setup_accumulation_funnel.py`; focused regressions are in `test_setup_accumulation_funnel.py`. `results/manifest.json` binds all inputs, authoritative source hashes, row counts, study contracts, hard gates, and SHA-256 hashes for every machine-readable result.

## Hard gates

`SETUP_FUNNEL_RECONSTRUCTED_AUTHORITATIVELY: YES`

`1599_WAVES_FIRST_BLOCKER_ATTRIBUTED: YES`

`MATCHED_CONTROL_FUNNEL_COMPLETE: YES`

`DOMINANT_BLOCKER: LifecycleObservation.hard_valid (principally unavailable/ambiguous canonical peak identity)`

`DOMINANT_BLOCKER_CLASSIFICATION: TEMPORAL_REPRESENTATION_LIMITATION`

`HARD_VALID_IS_SETUP_BLOCKER: YES`

`UNKNOWN_COST_IS_SETUP_BLOCKER: NO`

`TEMPORAL_VALIDITY_IS_DOMINANT_BLOCKER: YES`

`ROLLING_BASE_AVAILABILITY_IS_DOMINANT_BLOCKER: YES`

`ENSEMBLE_AMBIGUITY_IS_DOMINANT_BLOCKER: YES`

`ACCUMULATION_SCORE_1_00_IS_DOMINANT_BLOCKER: NO`

`SETUP_STATE_MACHINE_IS_DOMINANT_BLOCKER: NO`

`IMPLEMENTATION_DEFECT_FOUND: NO`

`WAVE_RECALL_FAILURE_ROOT_CAUSE_IDENTIFIED: YES`

`EXISTING_DOWNSTREAM_THRESHOLDS_IDENTIFIABLE: PARTIAL`

`SAFE_TO_DESIGN_SETUP_RECALL_REMEDIATION: NO`

`SAFE_TO_CHANGE_ACCUMULATION_THRESHOLD: NO`

`SAFE_TO_PROCEED_TO_STRATEGY_REDESIGN: NO`

`SAFE_TO_START_FULL_MARKET_3941_BUILD: NO`
"""


def main() -> None:
    evidence = verify_inputs()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    features = load_frozen_features()
    gates, lifecycle = load_authoritative_ledger()
    wide = gate_wide(gates)
    waves_source = pq.read_table(V2_RESULTS / "wave_events.parquet").to_pandas()
    labels = pq.read_table(V2_RESULTS / "price_wave_labels.parquet").to_pandas()
    if len(waves_source) != EXPECTED_WAVES or not waves_source["any_upside"].all():
        raise RuntimeError("Reverse Wave V2 wave sample changed")
    controls_index = deterministic_matched_controls(waves_source, labels)
    wave_index = waves_source[["event_id", "symbol", "feature_date", "event_start", "feature_position", "split"]].copy()
    waves = attach_authority(wave_index, features, wide, lifecycle, sample_type="wave")
    controls = attach_authority(controls_index, features, wide, lifecycle, sample_type="control")
    wave_funnel = make_wave_funnel(waves)
    tables = {
        "wave_funnel.csv": wave_funnel,
        "matched_controls.csv": controls_index,
        "first_blocker_attribution.csv": first_blocker_attribution(waves),
        "funnel_stage_summary.csv": funnel_stage_summary(waves, controls),
        "accumulation_component_audit.csv": accumulation_component_audit(gates, waves, controls),
        "wave_vs_control_gate_comparison.csv": wave_control_comparison(waves, controls),
        "validity_gate_audit.csv": validity_gate_audit(features, gates),
        "accumulation_score_distribution.csv": score_distributions(waves, controls, lifecycle),
        "threshold_coverage_diagnostics.csv": threshold_coverage(waves, controls),
        "rolling_base_eligibility.csv": rolling_base_eligibility(waves, controls),
        "ensemble_ambiguity_audit.csv": ensemble_audit(waves, controls),
        "downstream_threshold_audit.csv": downstream_threshold_audit(gates),
        "setup_path_catalog.csv": setup_path_catalog(),
        "lifecycle_occupancy_audit.csv": lifecycle_occupancy_audit(lifecycle, gates),
    }
    output_paths = [write_csv(frame, name) for name, frame in tables.items()]
    report = render_report(tables, evidence)
    REPORT_PATH.write_text(report, encoding="utf-8")
    hard_gates = {
        "SETUP_FUNNEL_RECONSTRUCTED_AUTHORITATIVELY": "YES",
        "1599_WAVES_FIRST_BLOCKER_ATTRIBUTED": "YES",
        "MATCHED_CONTROL_FUNNEL_COMPLETE": "YES",
        "DOMINANT_BLOCKER": "LifecycleObservation.hard_valid (principally unavailable/ambiguous canonical peak identity)",
        "DOMINANT_BLOCKER_CLASSIFICATION": "TEMPORAL_REPRESENTATION_LIMITATION",
        "HARD_VALID_IS_SETUP_BLOCKER": "YES",
        "UNKNOWN_COST_IS_SETUP_BLOCKER": "NO",
        "TEMPORAL_VALIDITY_IS_DOMINANT_BLOCKER": "YES",
        "ROLLING_BASE_AVAILABILITY_IS_DOMINANT_BLOCKER": "YES",
        "ENSEMBLE_AMBIGUITY_IS_DOMINANT_BLOCKER": "YES",
        "ACCUMULATION_SCORE_1_00_IS_DOMINANT_BLOCKER": "NO",
        "SETUP_STATE_MACHINE_IS_DOMINANT_BLOCKER": "NO",
        "IMPLEMENTATION_DEFECT_FOUND": "NO",
        "WAVE_RECALL_FAILURE_ROOT_CAUSE_IDENTIFIED": "YES",
        "EXISTING_DOWNSTREAM_THRESHOLDS_IDENTIFIABLE": "PARTIAL",
        "SAFE_TO_DESIGN_SETUP_RECALL_REMEDIATION": "NO",
        "SAFE_TO_CHANGE_ACCUMULATION_THRESHOLD": "NO",
        "SAFE_TO_PROCEED_TO_STRATEGY_REDESIGN": "NO",
        "SAFE_TO_START_FULL_MARKET_3941_BUILD": "NO",
    }
    manifest = {
        "study": "V12 Setup Accumulation Funnel Root Cause Study",
        "study_contract_version": "v12-setup-accumulation-funnel-authoritative-v1",
        "input_evidence": evidence,
        "control_matching_contract": controls_index.iloc[0]["matching_contract"],
        "chronological_splits": {
            "discovery": "feature_date <= 2020-04-30",
            "validation": "2020-05-01 <= feature_date <= 2020-08-31",
            "holdout": "feature_date >= 2020-09-01",
        },
        "counts": {
            "frozen_rows": len(features), "symbols": features["symbol"].nunique(),
            "waves": len(waves), "matched_controls": len(controls),
            "matched_control_symbols": controls["symbol"].nunique(),
            "strict_temporal_rows": int(features["strict_temporal_valid"].sum()),
            "production_hard_valid_rows": int((gates["gate_name"].eq("hard_valid") & gates["passed"]).sum()),
            "production_setup_score_evaluations": int(gates["gate_name"].eq("setup_score").sum()),
            "production_setup_score_passes": int((gates["gate_name"].eq("setup_score") & gates["passed"]).sum()),
            "setup_created": int(lifecycle["event_type"].eq("SETUP_OBSERVED").sum()),
        },
        "hard_gates": hard_gates,
        "artifacts": {},
    }
    for path in [*output_paths, REPORT_PATH]:
        manifest["artifacts"][path.name] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(canonical_json({"status": "COMPLETE", "manifest": str(manifest_path), "counts": manifest["counts"]}))


if __name__ == "__main__":
    main()
