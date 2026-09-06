#!/usr/bin/env python3
"""Freeze V29R3 validation identities, then run one separately authorized replay.

Stage A is outcome blind.  It starts from the exact frozen V28R2 validation
selected identity and computes only the completed-signal-day stock return and
the same-day full-market hard-valid PIT median from registered wrapper CY-040.

Stage B is intentionally a separate command.  It verifies the immutable Stage
A freeze before it is allowed to resolve CY-041 or any outcome-source path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DAILY-NON-CHASING-V29R3-VALIDATION-2022-2024"
PREREGISTRATION = (
    OS_ROOT / "experiments/ASHARE-TRUE-GAP-BELOW-L-DAILY-NON-CHASING-V29R3_preregistration.json"
)
EXPECTED_PREREGISTRATION_SHA256 = "33595c6c163ef65a65298f1a2751b105e9d1ada149f7ec6f834385cd68fcb15d"
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_BUILDER = (
    OS_ROOT / "scripts/build_ashare_true_gap_below_l_daily_non_chasing_v29r3_activation_assets.py"
)

PARENT_IDENTITY_FREEZE = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2-"
    "VALIDATION-2022-2024_identity_freeze.json"
)
EXPECTED_PARENT_IDENTITY_FREEZE_SHA256 = (
    "8b61ca22a211d91be01c3da7669e1412ef201bc8ca0440ac052b804d0397f39c"
)
PARENT_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024/"
    "diagnostic_2022_2024/orderly_demand_selected_entries.parquet"
)
EXPECTED_PARENT_SELECTED_SHA256 = "c439ea1a74e7d1f865cf187fadca3834e8d8963537eeab9230e4f3981db14c23"

CY040_ASSET_ID = "CY-040"
CY040_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-DAILY-NON-CHASING-V29R3-STAGE-A-2022-2024-V1"
CY040_PURPOSE = "ASHARE_DAILY_NON_CHASING_V29R3_VALIDATION_STAGE_A"
CY040_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/CY-040-DAILY-NON-CHASING-V29R3-STAGE-A-2022-2024-V1"
)

CY041_ASSET_ID = "CY-041"
CY041_AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-DAILY-NON-CHASING-V29R3-STAGE-B-2022-2024-V1"
CY041_PURPOSE = "ASHARE_DAILY_NON_CHASING_V29R3_VALIDATION_STAGE_B"
CY041_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/CY-041-DAILY-NON-CHASING-V29R3-STAGE-B-2022-2024-V1"
)

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_daily_non_chasing_v29r3_validation_2022_2024"
)
STAGE_A_ROOT = OUTPUT_ROOT / "stage_a"
STAGE_A_FEATURES = STAGE_A_ROOT / "parent_signal_features.parquet"
STAGE_A_SELECTED = STAGE_A_ROOT / "selected_identity.parquet"
STAGE_A_FREEZE = STAGE_A_ROOT / "stage_a_freeze.json"
STAGE_B_ROOT = OUTPUT_ROOT / "stage_b"
STAGE_B_LANE = STAGE_B_ROOT / "full"
STAGE_B_DROP_CLUSTER_LANE = STAGE_B_ROOT / "drop_largest_signal_date"
STAGE_B_ATTEMPT = STAGE_B_ROOT / "attempt.json"
STAGE_B_RESULT = STAGE_B_ROOT / "result.json"
STAGE_B_REPORT = STAGE_B_ROOT / "report.md"

VALIDATION_YEARS = (2022, 2023, 2024)
VALIDATION_START = pd.Timestamp("2022-01-01")
VALIDATION_END = pd.Timestamp("2024-12-31 23:59:59")
THRESHOLD = 0.02
EXPECTED_PARENT_SIGNALS = 120
PORTFOLIO_K = 80
ALPHA = 0.67
HORIZON = 20
STOP = "NONE"
COST_PER_SIDE = 0.002
CROSS_SECTION_SEMANTICS = {
    "definition": "CONDITIONAL_OBSERVED_ROWS_IN_EXACT_REGISTERED_CY033_PARTITION",
    "current_universe_or_constituent_filter_applied": False,
    "historical_security_master_completeness_verified": False,
    "survivorship_free_claim_allowed": False,
    "full_a_share_population_claim_allowed": False,
    "limitation": (
        "QD-007 is not materialized, so CY-033 row inventory cannot be certified complete "
        "against a date-effective historical security master."
    ),
}

FORBIDDEN_STAGE_A_COLUMNS = {
    "alpha",
    "exit_cal_idx",
    "exit_date",
    "exit_raw_price",
    "exit_reason",
    "exit_time",
    "holding_sessions",
    "net_return",
    "stop",
    "target_coordinate",
}
FORBIDDEN_ISSUER_TOKENS = ("announcement", "issuer", "risk_title", "v29r1", "v29r2")


class V29R3ValidationError(RuntimeError):
    """Fail closed on authorization, PIT, identity, execution or date drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise V29R3ValidationError(f"JSON root must be an object: {path}")
    return value


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
    )


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    v28.replay.repair.write_parquet(frame, path)


def _lock_files(*paths: Path) -> None:
    for path in paths:
        path.chmod(0o444)


def _lock_tree_files(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o444)


def _assert_read_only(path: Path) -> None:
    if path.stat().st_mode & 0o222:
        raise V29R3ValidationError(f"frozen file is writable: {path}")


def verify_preregistration() -> dict[str, Any]:
    if not PREREGISTRATION.is_file():
        raise V29R3ValidationError("V29R3 preregistration is missing")
    actual = sha256(PREREGISTRATION)
    if actual != EXPECTED_PREREGISTRATION_SHA256:
        raise V29R3ValidationError(
            f"V29R3 preregistration drift: {actual} != {EXPECTED_PREREGISTRATION_SHA256}"
        )
    _assert_read_only(PREREGISTRATION)
    payload = _json(PREREGISTRATION)
    if (
        payload.get("experiment") != EXPERIMENT
        or payload.get("strategy_version") != "V29R3"
        or payload.get("scientific_status")
        != "POST_HOC_DEVELOPMENT_CANDIDATE_TEMPORAL_CHALLENGE_NOT_PRISTINE_OOS"
        or payload.get("single_additional_gate", {}).get("threshold") != THRESHOLD
        or payload.get("parent", {}).get("issuer_veto_inherited") is not False
        or payload.get("validation_window", {}).get("2025_or_later_read_permitted") is not False
    ):
        raise V29R3ValidationError("V29R3 preregistration semantics drift")
    return payload


def verify_parent_identity_metadata() -> dict[str, Any]:
    if not PARENT_IDENTITY_FREEZE.is_file():
        raise V29R3ValidationError("frozen V28R2 validation identity is missing")
    if sha256(PARENT_IDENTITY_FREEZE) != EXPECTED_PARENT_IDENTITY_FREEZE_SHA256:
        raise V29R3ValidationError("frozen V28R2 validation identity drift")
    freeze = _json(PARENT_IDENTITY_FREEZE)
    diagnostic = freeze.get("diagnostic", {})
    if (
        freeze.get("experiment")
        != "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2-VALIDATION-2022-2024"
        or freeze.get("stage") != "TEMPORAL_DIAGNOSTIC_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN"
        or freeze.get("diagnostic_outcomes_opened") != "NO_IN_THIS_STAGE"
        or freeze.get("2025_or_later_data_opened") != "NO_IN_THIS_STAGE"
        or tuple(freeze.get("validation_years", [])) != VALIDATION_YEARS
        or diagnostic.get("selected_signals") != EXPECTED_PARENT_SIGNALS
        or diagnostic.get("selected_entries_sha256") != EXPECTED_PARENT_SELECTED_SHA256
    ):
        raise V29R3ValidationError("frozen V28R2 validation identity semantics drift")
    return freeze


def _exact_item(items: Any, key: str, expected: str, label: str) -> dict[str, Any]:
    matches = [item for item in items or [] if isinstance(item, dict) and item.get(key) == expected]
    if len(matches) != 1:
        raise V29R3ValidationError(f"{label} must resolve exactly once: {expected}")
    return matches[0]


def _fingerprints(items: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items or []:
        if not isinstance(item, dict) or not isinstance(item.get("role"), str):
            raise V29R3ValidationError("invalid bound artifact fingerprint")
        if item["role"] in result:
            raise V29R3ValidationError(f"duplicate artifact role: {item['role']}")
        result[item["role"]] = item
    return result


def _verify_fingerprint(
    value: Any,
    *,
    label: str,
    expected_path: Path | None = None,
    expected_sha256: str | None = None,
) -> Path:
    if not isinstance(value, dict) or not value.get("path") or not value.get("sha256"):
        raise V29R3ValidationError(f"missing fingerprint: {label}")
    path = Path(str(value["path"]))
    if expected_path is not None and path != expected_path:
        raise V29R3ValidationError(f"unexpected path for {label}: {path}")
    if not path.is_file():
        raise V29R3ValidationError(f"missing file for {label}: {path}")
    actual = sha256(path)
    if actual != value["sha256"] or (expected_sha256 is not None and actual != expected_sha256):
        raise V29R3ValidationError(f"fingerprint drift for {label}: {path}")
    return path


def verify_activation(
    *,
    asset_id: str,
    authorization_id: str,
    purpose: str,
    dependency_asset_id: str,
    expected_root: Path,
) -> dict[str, Any]:
    """Verify only targeted registry entries so unrelated append-only churn is harmless."""
    registry = _json(REGISTRY)
    asset = _exact_item(registry.get("assets"), "asset_id", asset_id, "asset")
    authorization = _exact_item(
        registry.get("bounded_authorizations"),
        "authorization_id",
        authorization_id,
        "bounded authorization",
    )
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("physical_state") != "MATERIALIZED"
        or Path(str(asset.get("location"))) != expected_root
        or asset.get("lineage", {}).get("bounded_authorization_id") != authorization_id
        or authorization.get("purpose") != purpose
        or authorization.get("asset_id") != asset_id
        or authorization.get("dependency_asset_id") != dependency_asset_id
        or authorization.get("current_survivor_fallback_allowed") is not False
    ):
        raise V29R3ValidationError(f"{asset_id} activation semantics do not match V29R3")

    manifest_path = _verify_fingerprint(
        authorization.get("bound_manifest"),
        label=f"{asset_id} manifest",
        expected_path=expected_root / "asset_manifest.json",
    )
    _verify_fingerprint(
        authorization.get("bound_strategy"),
        label="V29R3 preregistration",
        expected_path=PREREGISTRATION,
        expected_sha256=EXPECTED_PREREGISTRATION_SHA256,
    )
    protocol = authorization.get("bound_protocol")
    if not isinstance(protocol, dict):
        raise V29R3ValidationError("bounded authorization lacks bound_protocol")
    _verify_fingerprint(
        protocol,
        label="V29R3 protocol",
        expected_path=PREREGISTRATION,
        expected_sha256=EXPECTED_PREREGISTRATION_SHA256,
    )
    if Path(str(protocol.get("runner_path", ""))) != Path(__file__) or protocol.get(
        "runner_sha256"
    ) != sha256(Path(__file__)):
        raise V29R3ValidationError("bounded runner identity drift")

    artifacts = _fingerprints(authorization.get("bound_artifacts"))
    _verify_fingerprint(
        artifacts.get("asset_builder"),
        label="V29R3 activation asset builder",
        expected_path=ASSET_BUILDER,
    )
    manifest = _json(manifest_path)
    if (
        manifest.get("asset_id") != asset_id
        or manifest.get("status") != "PASS"
        or manifest.get("authorization_id") != authorization_id
        or manifest.get("preregistration", {}).get("sha256") != EXPECTED_PREREGISTRATION_SHA256
        or manifest.get("runner", {}).get("sha256") != sha256(Path(__file__))
        or manifest.get("outcome_or_title_content_embedded") is not False
    ):
        raise V29R3ValidationError(f"{asset_id} manifest semantics drift")
    return {
        "asset": asset,
        "authorization": authorization,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "asset_digest": canonical_digest(asset),
        "authorization_digest": canonical_digest(authorization),
        "manifest_sha256": sha256(manifest_path),
    }


def verify_stage_a_activation() -> dict[str, Any]:
    activation = verify_activation(
        asset_id=CY040_ASSET_ID,
        authorization_id=CY040_AUTHORIZATION_ID,
        purpose=CY040_PURPOSE,
        dependency_asset_id="CY-033",
        expected_root=CY040_ROOT,
    )
    authorization = activation["authorization"]
    manifest = activation["manifest"]
    if (
        authorization.get("stage_a_outcome_read_authorized") is not False
        or authorization.get("stage_a_title_read_authorized") is not False
        or authorization.get("2025_plus_read_authorized") is not False
        or authorization.get("record_level_available_at_available") is not True
        or manifest.get("stage") != "OUTCOME_BLIND_STAGE_A_INPUT_WRAPPER"
        or manifest.get("outcome_paths_resolved") is not False
        or manifest.get("title_paths_resolved") is not False
        or manifest.get("cross_section_semantics") != CROSS_SECTION_SEMANTICS
        or authorization.get("cross_section_semantics") != CROSS_SECTION_SEMANTICS
    ):
        raise V29R3ValidationError("CY-040 is not an outcome-blind Stage-A activation")
    parent = manifest.get("parent_selected_identity", {})
    if (
        Path(str(parent.get("path", ""))) != PARENT_SELECTED
        or parent.get("sha256") != EXPECTED_PARENT_SELECTED_SHA256
        or Path(str(manifest.get("parent_identity_freeze", {}).get("path", "")))
        != PARENT_IDENTITY_FREEZE
        or manifest.get("parent_identity_freeze", {}).get("sha256")
        != EXPECTED_PARENT_IDENTITY_FREEZE_SHA256
    ):
        raise V29R3ValidationError("CY-040 parent identity binding drift")

    partitions = manifest.get("daily_partitions")
    if not isinstance(partitions, list) or len(partitions) != len(VALIDATION_YEARS):
        raise V29R3ValidationError("CY-040 must bind exactly three daily partitions")
    by_year = {int(item.get("year")): item for item in partitions if isinstance(item, dict)}
    if tuple(sorted(by_year)) != VALIDATION_YEARS:
        raise V29R3ValidationError("CY-040 partition years escaped 2022-2024")
    paths: dict[int, Path] = {}
    for year in VALIDATION_YEARS:
        item = by_year[year]
        path = _verify_fingerprint(item, label=f"CY-040 daily partition {year}")
        if f"partition_year={year}" not in path.as_posix():
            raise V29R3ValidationError(f"CY-040 partition path/year mismatch: {path}")
        paths[year] = path
    activation["daily_paths"] = paths
    return activation


def _to_naive_datetime(values: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(values, errors="raise")
    if isinstance(parsed.dtype, pd.DatetimeTZDtype):
        parsed = parsed.dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    return parsed


def _nonempty_snapshot(values: pd.Series) -> pd.Series:
    return (values.notna() & values.astype("string").str.strip().ne("")).fillna(False)


def _assert_no_forbidden_stage_a_columns(frame: pd.DataFrame) -> None:
    forbidden = FORBIDDEN_STAGE_A_COLUMNS.intersection(frame.columns)
    issuer = sorted(
        column
        for column in frame.columns
        if any(token in column.lower() for token in FORBIDDEN_ISSUER_TOKENS)
    )
    if forbidden or issuer:
        raise V29R3ValidationError(
            f"Stage A input contains outcomes or issuer/title fields: {sorted(forbidden)}, {issuer}"
        )


def load_parent_selected_identity() -> pd.DataFrame:
    if not PARENT_SELECTED.is_file() or sha256(PARENT_SELECTED) != EXPECTED_PARENT_SELECTED_SHA256:
        raise V29R3ValidationError("frozen V28R2 validation selected identity drift")
    frame = pd.read_parquet(PARENT_SELECTED)
    _assert_no_forbidden_stage_a_columns(frame)
    required = {"gap_id", "symbol", "signal_date", "signal_time", "entry_status"}
    if not required.issubset(frame.columns):
        raise V29R3ValidationError("parent selected identity lacks required columns")
    frame["signal_date"] = _to_naive_datetime(frame.signal_date).dt.normalize()
    frame["signal_time"] = _to_naive_datetime(frame.signal_time)
    if (
        len(frame) != EXPECTED_PARENT_SIGNALS
        or frame.gap_id.astype(str).duplicated().any()
        or not frame.signal_date.dt.year.isin(VALIDATION_YEARS).all()
        or not frame.signal_time.dt.normalize().eq(frame.signal_date).all()
        or frame.signal_time.max() > VALIDATION_END
    ):
        raise V29R3ValidationError("parent V28R2 validation cohort identity failure")
    return frame.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(
        drop=True
    )


def load_stage_a_daily(paths: dict[int, Path]) -> pd.DataFrame:
    columns = [
        "symbol",
        "trade_date",
        "decision_at",
        "close",
        "preclose",
        "trade_status",
        "hard_valid",
        "current_day_data_tradable",
        "available_at",
        "snapshot_id",
    ]
    frames = [pd.read_parquet(paths[year], columns=columns) for year in VALIDATION_YEARS]
    frame = pd.concat(frames, ignore_index=True)
    frame["trade_date"] = _to_naive_datetime(frame.trade_date).dt.normalize()
    frame["decision_at"] = _to_naive_datetime(frame.decision_at)
    frame["available_at"] = _to_naive_datetime(frame.available_at)
    if (
        frame.empty
        or frame.duplicated(["symbol", "trade_date"]).any()
        or not frame.trade_date.dt.year.isin(VALIDATION_YEARS).all()
        or frame.trade_date.max() > VALIDATION_END
    ):
        raise V29R3ValidationError("CY-040 daily input identity/date failure")
    return frame


def attach_daily_non_chasing_feature(
    entries: pd.DataFrame,
    daily: pd.DataFrame,
) -> pd.DataFrame:
    """Attach the exact signal-close feature; invalid or unknown state rejects."""
    required_entries = {"gap_id", "symbol", "signal_date", "signal_time"}
    required_daily = {
        "symbol",
        "trade_date",
        "decision_at",
        "close",
        "preclose",
        "trade_status",
        "hard_valid",
        "current_day_data_tradable",
        "available_at",
        "snapshot_id",
    }
    if not required_entries.issubset(entries.columns) or not required_daily.issubset(daily.columns):
        raise V29R3ValidationError("missing columns for V29R3 signal-close feature")
    if entries.gap_id.astype(str).duplicated().any():
        raise V29R3ValidationError("duplicate parent gap_id")

    wanted = entries.copy()
    wanted["signal_date"] = _to_naive_datetime(wanted.signal_date).dt.normalize()
    wanted["signal_time"] = _to_naive_datetime(wanted.signal_time)
    source = daily.copy()
    source["trade_date"] = _to_naive_datetime(source.trade_date).dt.normalize()
    source["decision_at"] = _to_naive_datetime(source.decision_at)
    source["available_at"] = _to_naive_datetime(source.available_at)
    if source.duplicated(["symbol", "trade_date"]).any():
        raise V29R3ValidationError("duplicate symbol-date in full-market daily input")

    source["_close"] = pd.to_numeric(source.close, errors="coerce")
    source["_preclose"] = pd.to_numeric(source.preclose, errors="coerce")
    source["_step_return"] = source._close / source._preclose - 1.0
    finite_price = np.isfinite(source._close) & np.isfinite(source._preclose)
    finite_return = np.isfinite(source._step_return)
    source["_base_eligible"] = (
        source.hard_valid.eq(True)
        & source.current_day_data_tradable.eq(True)
        & pd.to_numeric(source.trade_status, errors="coerce").eq(1.0)
        & source.available_at.notna()
        & source.decision_at.notna()
        & source.available_at.le(source.decision_at)
        & _nonempty_snapshot(source.snapshot_id)
        & finite_price
        & source._close.gt(0)
        & source._preclose.gt(0)
        & finite_return
    )

    daily_groups = {
        date: group.reset_index(drop=True)
        for date, group in source.groupby("trade_date", sort=False)
    }
    records: list[dict[str, Any]] = []
    for event in wanted[["gap_id", "symbol", "signal_date", "signal_time"]].itertuples(index=False):
        same_day = daily_groups.get(event.signal_date)
        if same_day is None:
            same_day = source.iloc[0:0]
        timely = (
            same_day._base_eligible
            & same_day.available_at.le(event.signal_time)
            & same_day.decision_at.le(event.signal_time)
        )
        market = same_day.loc[timely]
        market_n = len(market)
        market_median = float(market._step_return.median()) if market_n > 0 else math.nan
        signal = same_day.loc[same_day.symbol.astype(str).eq(str(event.symbol))]
        signal_unique = len(signal) == 1
        signal_eligible = bool(signal_unique and bool(timely.loc[signal.index[0]]))
        signal_return = (
            float(signal.iloc[0]._step_return) if signal_unique and signal_eligible else math.nan
        )
        feature_available = bool(signal_eligible and market_n > 0 and math.isfinite(market_median))
        excess = signal_return - market_median if feature_available else math.nan
        passed = bool(feature_available and excess <= THRESHOLD)
        if same_day.empty:
            reason = "MISSING_SIGNAL_DATE"
        elif not signal_unique:
            reason = "MISSING_OR_DUPLICATE_SIGNAL_ROW"
        elif not signal_eligible:
            reason = "SIGNAL_ROW_NOT_HARD_VALID_PIT_ELIGIBLE"
        elif market_n == 0 or not math.isfinite(market_median):
            reason = "NO_ELIGIBLE_FULL_MARKET_MEDIAN"
        elif passed:
            reason = "PASS"
        else:
            reason = "SIGNAL_EXCESS_MARKET_GT_0P02"
        records.append(
            {
                "gap_id": event.gap_id,
                "signal_stock_return": signal_return,
                "full_market_hard_valid_pit_median_return": market_median,
                "signal_excess_market_1d": excess,
                "market_eligible_n": market_n,
                "market_feature_latest_available_at": (
                    market.available_at.max() if market_n else pd.NaT
                ),
                "v29r3_feature_available": feature_available,
                "v29r3_rejection_reason": reason,
                "v29r3_daily_non_chasing_2pct_gate": passed,
                "v29r3_feature_uses_post_signal_information": False,
            }
        )
    result = wanted.merge(pd.DataFrame.from_records(records), on="gap_id", validate="one_to_one")
    if (
        result.v29r3_feature_uses_post_signal_information.any()
        or (
            result.market_feature_latest_available_at.notna()
            & result.market_feature_latest_available_at.gt(result.signal_time)
        ).any()
    ):
        raise V29R3ValidationError("V29R3 feature crossed the signal decision time")
    return result


def run_stage_a() -> dict[str, Any]:
    """Run only after CY-040 and its exact one-to-one authorization are active."""
    verify_preregistration()
    verify_parent_identity_metadata()
    activation = verify_stage_a_activation()
    if STAGE_A_FREEZE.exists() or STAGE_A_SELECTED.exists() or STAGE_A_FEATURES.exists():
        raise V29R3ValidationError("Stage A output already exists; overwrite is prohibited")

    # Data rows are deliberately not read until the targeted authorization passes.
    parent = load_parent_selected_identity()
    daily = load_stage_a_daily(activation["daily_paths"])
    featured = attach_daily_non_chasing_feature(parent, daily)
    selected = featured.loc[featured.v29r3_daily_non_chasing_2pct_gate].copy()
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort")
    if selected.empty or selected.gap_id.astype(str).duplicated().any():
        raise V29R3ValidationError("V29R3 Stage-A selected identity failure")

    _write_parquet(featured, STAGE_A_FEATURES)
    _write_parquet(selected, STAGE_A_SELECTED)
    by_year = selected.groupby(selected.signal_date.dt.year).size()
    by_date = selected.groupby(selected.signal_date).size().sort_values(ascending=False)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "V29R3_TEMPORAL_VALIDATION_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        "scientific_status": ("POST_HOC_DEVELOPMENT_CANDIDATE_TEMPORAL_CHALLENGE_NOT_PRISTINE_OOS"),
        "fixed_rule": (
            "V28R2 AND signal_stock_return-full_market_hard_valid_pit_median_return<=0.02"
        ),
        "preregistration_sha256": sha256(PREREGISTRATION),
        "runner_sha256": sha256(Path(__file__)),
        "asset_builder_sha256": sha256(ASSET_BUILDER),
        "parent_identity_freeze_sha256": sha256(PARENT_IDENTITY_FREEZE),
        "parent_selected_sha256": sha256(PARENT_SELECTED),
        "cy040_manifest_sha256": activation["manifest_sha256"],
        "cy040_asset_digest": activation["asset_digest"],
        "cy040_authorization_digest": activation["authorization_digest"],
        "daily_partition_hashes": {
            str(year): sha256(path) for year, path in activation["daily_paths"].items()
        },
        "cohort": {
            "parent_signals": len(featured),
            "feature_available": int(featured.v29r3_feature_available.sum()),
            "selected_signals": len(selected),
            "selected_executable_entries": int(selected.entry_status.eq("EXECUTABLE_ENTRY").sum()),
            "selected_by_signal_year": {
                str(year): int(by_year.get(year, 0)) for year in VALIDATION_YEARS
            },
            "selected_signal_dates": int(selected.signal_date.nunique()),
            "largest_selected_signal_date": str(pd.Timestamp(by_date.index[0]).date()),
            "largest_selected_signal_date_count": int(by_date.iloc[0]),
            "parent_features_path": str(STAGE_A_FEATURES),
            "parent_features_sha256": sha256(STAGE_A_FEATURES),
            "selected_path": str(STAGE_A_SELECTED),
            "selected_sha256": sha256(STAGE_A_SELECTED),
        },
        "cross_section_semantics": CROSS_SECTION_SEMANTICS,
        "issuer_veto_inherited": False,
        "issuer_or_title_data_opened": "NO",
        "validation_outcomes_opened": "NO_IN_THIS_STAGE",
        "2025_or_later_data_opened": "NO",
        "stage_b_authorized_by_stage_a": "NO_SEPARATE_CY041_AUTHORIZATION_REQUIRED",
        "rule_change_after_validation": "PROHIBITED",
    }
    _atomic_json(STAGE_A_FREEZE, freeze)
    _lock_files(STAGE_A_FEATURES, STAGE_A_SELECTED, STAGE_A_FREEZE)
    return freeze


def verify_stage_a_freeze() -> dict[str, Any]:
    """Verify the complete outcome-blind freeze without resolving Stage-B paths."""
    verify_preregistration()
    verify_parent_identity_metadata()
    if (
        not STAGE_A_FREEZE.is_file()
        or not STAGE_A_SELECTED.is_file()
        or not STAGE_A_FEATURES.is_file()
    ):
        raise V29R3ValidationError("completed V29R3 Stage-A freeze is missing")
    _assert_read_only(STAGE_A_FREEZE)
    _assert_read_only(STAGE_A_SELECTED)
    _assert_read_only(STAGE_A_FEATURES)
    freeze = _json(STAGE_A_FREEZE)
    if (
        freeze.get("stage") != "V29R3_TEMPORAL_VALIDATION_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN"
        or freeze.get("validation_outcomes_opened") != "NO_IN_THIS_STAGE"
        or freeze.get("issuer_or_title_data_opened") != "NO"
        or freeze.get("2025_or_later_data_opened") != "NO"
        or freeze.get("issuer_veto_inherited") is not False
        or freeze.get("cross_section_semantics") != CROSS_SECTION_SEMANTICS
    ):
        raise V29R3ValidationError("Stage-A freeze does not certify the required lock")
    activation = verify_stage_a_activation()
    checks = {
        "preregistration_sha256": sha256(PREREGISTRATION),
        "runner_sha256": sha256(Path(__file__)),
        "asset_builder_sha256": sha256(ASSET_BUILDER),
        "parent_identity_freeze_sha256": sha256(PARENT_IDENTITY_FREEZE),
        "parent_selected_sha256": sha256(PARENT_SELECTED),
        "cy040_manifest_sha256": activation["manifest_sha256"],
        "cy040_asset_digest": activation["asset_digest"],
        "cy040_authorization_digest": activation["authorization_digest"],
    }
    drift = {
        key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value
    }
    expected_daily = {str(year): sha256(path) for year, path in activation["daily_paths"].items()}
    if freeze.get("daily_partition_hashes") != expected_daily:
        drift["daily_partition_hashes"] = [freeze.get("daily_partition_hashes"), expected_daily]
    cohort = freeze.get("cohort", {})
    output_checks = {
        "parent_features_sha256": sha256(STAGE_A_FEATURES),
        "selected_sha256": sha256(STAGE_A_SELECTED),
    }
    for key, value in output_checks.items():
        if cohort.get(key) != value:
            drift[f"cohort.{key}"] = [cohort.get(key), value]
    if drift:
        raise V29R3ValidationError(f"Stage-A freeze drift: {drift}")

    selected = pd.read_parquet(
        STAGE_A_SELECTED,
        columns=["gap_id", "symbol", "signal_date", "signal_time", "entry_status"],
    )
    selected["signal_date"] = _to_naive_datetime(selected.signal_date).dt.normalize()
    selected["signal_time"] = _to_naive_datetime(selected.signal_time)
    if (
        selected.empty
        or len(selected) != cohort.get("selected_signals")
        or selected.gap_id.astype(str).duplicated().any()
        or not selected.signal_date.dt.year.isin(VALIDATION_YEARS).all()
        or selected.signal_time.max() > VALIDATION_END
    ):
        raise V29R3ValidationError("Stage-A selected cohort content drift")
    return {
        "freeze": freeze,
        "selected": selected,
        "freeze_sha256": sha256(STAGE_A_FREEZE),
        "selected_sha256": sha256(STAGE_A_SELECTED),
    }


def verify_stage_b_activation(stage_a: dict[str, Any]) -> dict[str, Any]:
    activation = verify_activation(
        asset_id=CY041_ASSET_ID,
        authorization_id=CY041_AUTHORIZATION_ID,
        purpose=CY041_PURPOSE,
        dependency_asset_id=CY040_ASSET_ID,
        expected_root=CY041_ROOT,
    )
    authorization = activation["authorization"]
    manifest = activation["manifest"]
    if (
        authorization.get("stage_a_verification_required") is not True
        or authorization.get("outcome_attachment_authorized") is not True
        or authorization.get("portfolio_replay_authorized") is not True
        or authorization.get("2025_plus_read_authorized") is not False
        or authorization.get("issuer_title_read_authorized") is not False
        or authorization.get("authorized_run_count") != 1
        or manifest.get("stage") != "STAGE_B_FIXED_COHORT_ACTIVATION_WRAPPER"
        or manifest.get("outcome_content_parsed_by_builder") is not False
    ):
        raise V29R3ValidationError("CY-041 is not the frozen one-run Stage-B activation")
    if (
        manifest.get("stage_a_freeze", {}).get("sha256") != stage_a["freeze_sha256"]
        or Path(str(manifest.get("stage_a_freeze", {}).get("path", ""))) != STAGE_A_FREEZE
        or manifest.get("stage_a_selected", {}).get("sha256") != stage_a["selected_sha256"]
        or Path(str(manifest.get("stage_a_selected", {}).get("path", ""))) != STAGE_A_SELECTED
    ):
        raise V29R3ValidationError("CY-041 does not bind the verified Stage-A cohort")
    sources = _fingerprints(manifest.get("stage_b_sources"))
    required = {
        "v28r2_validation_outcomes",
        "portfolio_daily_old",
        "portfolio_daily_later",
    }
    if set(sources) != required:
        raise V29R3ValidationError("CY-041 Stage-B source roles are not exact")
    activation["source_paths"] = {
        role: _verify_fingerprint(item, label=f"CY-041 {role}") for role, item in sources.items()
    }
    return activation


def prepare_stage_b() -> tuple[dict[str, Any], dict[str, Any]]:
    """Ordering contract: Stage-B paths cannot resolve before Stage-A verifies."""
    stage_a = verify_stage_a_freeze()
    activation = verify_stage_b_activation(stage_a)
    return stage_a, activation


def select_frozen_outcomes(selected: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    required_selected = {"gap_id", "symbol", "signal_date", "signal_time", "entry_status"}
    if not required_selected.issubset(selected.columns):
        raise V29R3ValidationError("Stage-A selected identity schema drift")
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    required = {
        "gap_id",
        "symbol",
        "signal_date",
        "signal_time",
        "entry_date",
        "entry_time",
        "exit_date",
        "exit_time",
        "alpha",
        "horizon",
        "stop",
        "entry_at_or_before_signal",
        "buy_at_or_above_up_limit",
    }
    if executable.empty or not required.issubset(source.columns):
        raise V29R3ValidationError("Stage-B source lacks a nonempty frozen outcome schema")
    ids = set(executable.gap_id.astype(str))
    outcomes = source.loc[source.gap_id.astype(str).isin(ids)].copy()
    if (
        outcomes.gap_id.astype(str).duplicated().any()
        or len(outcomes) != len(ids)
        or set(outcomes.gap_id.astype(str)) != ids
    ):
        raise V29R3ValidationError("Stage-B outcome identity conservation failure")
    outcomes["gap_id"] = outcomes.gap_id.astype(str)
    executable["gap_id"] = executable.gap_id.astype(str)
    for column in (
        "signal_date",
        "signal_time",
        "entry_date",
        "entry_time",
        "exit_date",
        "exit_time",
    ):
        outcomes[column] = _to_naive_datetime(outcomes[column])
        if not outcomes[column].notna().all() or outcomes[column].max() > VALIDATION_END:
            raise V29R3ValidationError(f"post-2024 value prohibited in {column}")
    expected_identity = executable[["gap_id", "symbol", "signal_date", "signal_time"]].copy()
    expected_identity["signal_date"] = _to_naive_datetime(
        expected_identity.signal_date
    ).dt.normalize()
    expected_identity["signal_time"] = _to_naive_datetime(expected_identity.signal_time)
    observed_identity = outcomes[["gap_id", "symbol", "signal_date", "signal_time"]].merge(
        expected_identity,
        on="gap_id",
        how="left",
        validate="one_to_one",
        suffixes=("_outcome", "_frozen"),
    )
    if (
        not observed_identity.symbol_outcome.astype(str)
        .eq(observed_identity.symbol_frozen.astype(str))
        .all()
        or not observed_identity.signal_date_outcome.dt.normalize()
        .eq(observed_identity.signal_date_frozen)
        .all()
        or not observed_identity.signal_time_outcome.eq(observed_identity.signal_time_frozen).all()
    ):
        raise V29R3ValidationError("Stage-B outcome fields drift from frozen identity")
    if (
        not outcomes.signal_date.dt.year.isin(VALIDATION_YEARS).all()
        or not outcomes.entry_date.gt(outcomes.signal_date).all()
        or not outcomes.entry_time.gt(outcomes.signal_time).all()
        or not outcomes.exit_time.ge(outcomes.entry_time).all()
        or not outcomes.alpha.eq(ALPHA).all()
        or not outcomes.horizon.eq(HORIZON).all()
        or not outcomes.stop.eq(STOP).all()
        or not outcomes.entry_at_or_before_signal.eq(False).all()
        or not outcomes.buy_at_or_above_up_limit.eq(False).all()
    ):
        raise V29R3ValidationError("frozen T+1/A67/H20/no-stop execution drift")
    return outcomes.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort")


def _load_stage_b_daily(paths: dict[str, Path], max_exit: pd.Timestamp) -> pd.DataFrame:
    if max_exit > VALIDATION_END:
        raise V29R3ValidationError("post-2024 portfolio daily read prohibited")
    filters = [
        ("trade_date", ">=", VALIDATION_START.to_pydatetime()),
        ("trade_date", "<=", max_exit.to_pydatetime()),
    ]
    old = pd.read_parquet(paths["portfolio_daily_old"], filters=filters)
    later = pd.read_parquet(paths["portfolio_daily_later"], filters=filters)
    daily = pd.concat([old, later], ignore_index=True)
    daily["trade_date"] = _to_naive_datetime(daily.trade_date).dt.normalize()
    daily = daily.loc[daily.trade_date.ge(VALIDATION_START) & daily.trade_date.le(max_exit)].copy()
    if daily.empty or daily.trade_date.max() > VALIDATION_END:
        raise V29R3ValidationError("Stage-B daily materialization escaped 2022-2024")
    duplicate = daily.duplicated(["symbol", "trade_date"], keep=False)
    if duplicate.any():
        compare = [column for column in ("open", "high", "low", "close") if column in daily]
        inconsistent = (
            daily.loc[duplicate].groupby(["symbol", "trade_date"])[compare].nunique(dropna=False)
            > 1
        ).any(axis=1)
        if inconsistent.any():
            raise V29R3ValidationError("inconsistent overlapping Stage-B daily rows")
    return daily.sort_values(["symbol", "trade_date"], kind="mergesort").drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )


def _tail_mean(values: pd.Series) -> float:
    count = max(1, math.ceil(len(values) * 0.05))
    return float(values.astype(float).sort_values().iloc[:count].mean())


def _stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "trades": 0,
            "mean_net": None,
            "median_net": None,
            "win": None,
            "severe10": None,
            "cvar5": None,
            "mean_holding_sessions": None,
            "median_holding_sessions": None,
        }
    values = frame.net_return.astype(float)
    return {
        "trades": len(frame),
        "mean_net": float(values.mean()),
        "median_net": float(values.median()),
        "win": float(values.gt(0).mean()),
        "severe10": float(values.le(-0.10).mean()),
        "cvar5": _tail_mean(values),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "median_holding_sessions": float(frame.holding_sessions.median()),
    }


def detailed_summary(accepted: pd.DataFrame) -> dict[str, Any]:
    work = accepted.copy()
    work["signal_date"] = _to_naive_datetime(work.signal_date).dt.normalize()
    overall = _stats(work)
    overall["accepted_per_year"] = len(work) / len(VALIDATION_YEARS)
    date_summary = (
        work.groupby("signal_date", as_index=False)
        .agg(
            trades=("gap_id", "size"),
            mean_net=("net_return", "mean"),
            median_net=("net_return", "median"),
            mean_holding_sessions=("holding_sessions", "mean"),
        )
        .sort_values("signal_date")
    )
    if date_summary.empty:
        equal_date = {
            "unique_signal_dates": 0,
            "equal_date_weight_mean_net": None,
            "equal_date_weight_median_net": None,
            "largest_signal_date": None,
            "largest_signal_date_trades": 0,
            "largest_signal_date_share": None,
        }
    else:
        largest = date_summary.sort_values(
            ["trades", "signal_date"], ascending=[False, True], kind="mergesort"
        ).iloc[0]
        equal_date = {
            "unique_signal_dates": len(date_summary),
            "equal_date_weight_mean_net": float(date_summary.mean_net.mean()),
            "equal_date_weight_median_net": float(date_summary.mean_net.median()),
            "largest_signal_date": str(pd.Timestamp(largest.signal_date).date()),
            "largest_signal_date_trades": int(largest.trades),
            "largest_signal_date_share": float(largest.trades / len(work)),
        }
    return {
        "overall": overall,
        "yearly_by_signal_year": {
            str(year): _stats(work.loc[work.signal_date.dt.year.eq(year)])
            for year in VALIDATION_YEARS
        },
        "signal_date_equal_weight": equal_date,
    }


def _run_portfolio_lane(
    outcomes: pd.DataFrame,
    daily: pd.DataFrame,
    root: Path,
    max_exit: pd.Timestamp,
) -> tuple[dict[str, Any], pd.DataFrame]:
    root.mkdir(parents=True, exist_ok=False)
    _write_parquet(outcomes, root / "outcomes.parquet")
    old_k = v28.replay.repair.v1.PORTFOLIO_K
    try:
        v28.replay.repair.v1.PORTFOLIO_K = PORTFOLIO_K
        v28.replay.repair.v1.configure_external(root, max_exit)
        audit = v28.replay.repair.v1.run_portfolio(outcomes, daily, VALIDATION_YEARS)
    finally:
        v28.replay.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    return audit, accepted


def run_stage_b() -> dict[str, Any]:
    """Run one fixed validation only after Stage A and CY-041 both verify."""
    stage_a, activation = prepare_stage_b()
    if (
        STAGE_B_ATTEMPT.exists()
        or STAGE_B_RESULT.exists()
        or STAGE_B_LANE.exists()
        or STAGE_B_DROP_CLUSTER_LANE.exists()
    ):
        raise V29R3ValidationError("Stage B was already materialized; a second run is prohibited")
    if not math.isclose(float(v28.replay.repair.v1.COST), COST_PER_SIDE, abs_tol=1e-12):
        raise V29R3ValidationError("20bp-per-side cost drift")
    if int(v28.PORTFOLIO_K) != PORTFOLIO_K:
        raise V29R3ValidationError("K80 drift")

    # No outcome path is available until prepare_stage_b verifies the Stage-A freeze.
    source_paths = activation["source_paths"]
    attempt = {
        "experiment": EXPERIMENT,
        "stage": "STAGE_B_SINGLE_ATTEMPT_SEAL_BEFORE_OUTCOME_ROW_READ",
        "stage_a_freeze_sha256": stage_a["freeze_sha256"],
        "stage_a_selected_sha256": stage_a["selected_sha256"],
        "cy041_manifest_sha256": activation["manifest_sha256"],
        "cy041_asset_digest": activation["asset_digest"],
        "cy041_authorization_digest": activation["authorization_digest"],
        "source_hashes": {role: sha256(path) for role, path in source_paths.items()},
        "outcome_rows_read_before_seal": False,
        "authorized_run_count": 1,
    }
    _atomic_json(STAGE_B_ATTEMPT, attempt)
    _lock_files(STAGE_B_ATTEMPT)
    source = pd.read_parquet(
        source_paths["v28r2_validation_outcomes"],
        filters=[
            ("signal_date", ">=", VALIDATION_START.to_pydatetime()),
            ("signal_date", "<=", VALIDATION_END.to_pydatetime()),
        ],
    )
    outcomes = select_frozen_outcomes(stage_a["selected"], source)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    daily = _load_stage_b_daily(source_paths, max_exit)

    full_audit, accepted = _run_portfolio_lane(
        outcomes,
        daily,
        STAGE_B_LANE,
        max_exit,
    )
    full_summary = detailed_summary(accepted)
    largest_date = full_summary["signal_date_equal_weight"]["largest_signal_date"]
    if largest_date is None:
        raise V29R3ValidationError("full capacity replay accepted no trades")
    drop_date = pd.Timestamp(largest_date)
    reduced = outcomes.loc[
        _to_naive_datetime(outcomes.signal_date).dt.normalize().ne(drop_date)
    ].copy()
    reduced_audit, reduced_accepted = _run_portfolio_lane(
        reduced,
        daily,
        STAGE_B_DROP_CLUSTER_LANE,
        max_exit,
    )
    reduced_summary = detailed_summary(reduced_accepted)

    result = {
        "experiment": EXPERIMENT,
        "scientific_status": ("POST_HOC_DEVELOPMENT_CANDIDATE_TEMPORAL_CHALLENGE_NOT_PRISTINE_OOS"),
        "fixed_rule": (
            "V28R2 AND signal_stock_return-full_market_hard_valid_pit_median_return<=0.02"
        ),
        "cross_section_semantics": CROSS_SECTION_SEMANTICS,
        "stage_b_attempt_sha256": sha256(STAGE_B_ATTEMPT),
        "stage_a_freeze_sha256": stage_a["freeze_sha256"],
        "stage_a_selected_sha256": stage_a["selected_sha256"],
        "cy041_manifest_sha256": activation["manifest_sha256"],
        "cy041_asset_digest": activation["asset_digest"],
        "cy041_authorization_digest": activation["authorization_digest"],
        "full_capacity_replay": {
            "summary": full_summary,
            "audit": full_audit,
        },
        "drop_largest_signal_date_replay": {
            "removed_signal_date": largest_date,
            "summary": reduced_summary,
            "audit": reduced_audit,
        },
        "execution": {
            "entry": "strictly after completed signal",
            "target": "A67 below L",
            "horizon": "H20",
            "stop": "NONE",
            "cost_per_side": COST_PER_SIDE,
            "round_trip_cost": 2 * COST_PER_SIDE,
            "portfolio_k_per_sleeve": PORTFOLIO_K,
        },
        "source_hashes": {role: sha256(path) for role, path in source_paths.items()},
        "output_hashes": {
            "full_outcomes": sha256(STAGE_B_LANE / "outcomes.parquet"),
            "full_accepted": sha256(STAGE_B_LANE / "portfolio_accepted.parquet"),
            "drop_cluster_outcomes": sha256(STAGE_B_DROP_CLUSTER_LANE / "outcomes.parquet"),
            "drop_cluster_accepted": sha256(
                STAGE_B_DROP_CLUSTER_LANE / "portfolio_accepted.parquet"
            ),
        },
        "maximum_exit_date_used": str(max_exit.date()),
        "issuer_veto_inherited": False,
        "issuer_or_title_data_opened": "NO",
        "2025_or_later_data_opened": "NO",
        "rule_changed_after_validation": "NO",
        "stage_b_run_count": 1,
    }
    _atomic_json(STAGE_B_RESULT, result)
    _atomic_text(STAGE_B_REPORT, render_report(result))
    _lock_tree_files(STAGE_B_LANE)
    _lock_tree_files(STAGE_B_DROP_CLUSTER_LANE)
    _lock_files(STAGE_B_RESULT, STAGE_B_REPORT)
    return result


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.3f}%"


def render_report(result: dict[str, Any]) -> str:
    summary = result["full_capacity_replay"]["summary"]
    overall = summary["overall"]
    rows = []
    for year in VALIDATION_YEARS:
        item = summary["yearly_by_signal_year"][str(year)]
        hold = (
            "—" if item["mean_holding_sessions"] is None else f"{item['mean_holding_sessions']:.3f}"
        )
        rows.append(
            f"|{year}|{item['trades']}|{_pct(item['mean_net'])}|"
            f"{_pct(item['median_net'])}|{_pct(item['win'])}|"
            f"{_pct(item['severe10'])}|{hold}|"
        )
    drop = result["drop_largest_signal_date_replay"]
    reduced = drop["summary"]["overall"]
    return "\n".join(
        [
            f"# {EXPERIMENT}",
            "",
            "This was the one frozen 2022-2024 temporal challenge of a post-hoc "
            "2018-2021 candidate. It is not pristine independent validation.",
            "",
            "V29R3 is exactly V28R2 plus DAILY_NON_CHASING_2PCT. It does not "
            "inherit any issuer announcement or title veto.",
            "",
            "The market reference is the unweighted median of eligible rows physically "
            "present in each exact registered CY-033 partition. No current-universe or "
            "constituent filter was applied. Because QD-007 is unavailable, historical "
            "security-master completeness is unverified; this is not a complete-A-share "
            "or survivorship-free claim.",
            "",
            f"Accepted {overall['trades']} ({overall['accepted_per_year']:.3f}/year), "
            f"mean {_pct(overall['mean_net'])}, median {_pct(overall['median_net'])}, "
            f"win {_pct(overall['win'])}, severe10 {_pct(overall['severe10'])}, "
            f"mean hold {overall['mean_holding_sessions']:.3f} sessions.",
            "",
            "|Signal year|Accepted|Mean|Median|Win|Severe10|Mean hold|",
            "|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            f"Largest accepted signal-date cluster: {drop['removed_signal_date']}. "
            f"After removing it and rerunning capacity: {reduced['trades']} accepted "
            f"({reduced['accepted_per_year']:.3f}/year), mean "
            f"{_pct(reduced['mean_net'])}, mean hold "
            f"{reduced['mean_holding_sessions']:.3f} sessions.",
            "",
            "Development concentration warning: 2018-10-26 supplied 95 of 202 "
            "accepted development trades; removing that date reduced development "
            "frequency to 34.75/year even after capacity replacements.",
            "",
            "Execution remained T+1, A67, H20, no stop, 20bp per side and K80 per sleeve. "
            "No 2025-or-later or issuer-title data were opened.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=("stage-a", "verify-stage-a", "stage-b"),
        help="Stage A and Stage B are intentionally never chained in one invocation.",
    )
    args = parser.parse_args()
    if args.mode == "stage-a":
        payload = run_stage_a()
    elif args.mode == "verify-stage-a":
        verified = verify_stage_a_freeze()
        payload = {
            "verified": True,
            "freeze_sha256": verified["freeze_sha256"],
            "selected_sha256": verified["selected_sha256"],
        }
    else:
        payload = run_stage_b()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
