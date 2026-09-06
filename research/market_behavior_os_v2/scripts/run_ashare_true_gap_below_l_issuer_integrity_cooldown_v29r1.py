#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the preregistered V29R1 issuer-integrity cooling-period veto.

V29R1 retains the frozen V28R2 selector, entry, A67 target, H20 horizon,
40-bp round-trip cost, and Main/ChiNext K80-per-sleeve portfolio.  Its only
economic change is an inclusive 120-calendar-day veto after a high-precision
official-title ``OPEN`` issuer-risk disclosure.

The two stages are intentionally asymmetric.  Stage A may read the frozen
parent signal identity and the registered CY-036-R1 announcement metadata, but
it only streams the parent outcome files as bytes to bind their hashes.  Stage
B first revalidates that immutable freeze, then opens the exact bound parent
outcomes, proves a one-to-one exact execution-identity join, and delegates the
unchanged replay.  There is deliberately no post-2021 signal mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import numbers
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_risk_composite_asset_v29r1 as cy036r1,
)
from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v1 as classifier,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2 as v28r2,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = (
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29R1"
)
ASSET_ID = "CY-036-R1"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-ISSUER-RISK-V29R1-DEVELOPMENT-2018-2021-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_ISSUER_RISK_V29R1_DEVELOPMENT_SELECTOR_REPLAY"

EXPECTED_PREREGISTRATION_SHA256 = (
    "583e35cf4722daf569feec8bc64118cf430aa5b278b4c7149d6147ef79504b34"
)
EXPECTED_BLOCKER_SHA256 = (
    "42c3848ac9244e4ea7288f71594e639a3889b0a19e4036ee9955b82c55b91a7d"
)
PREREGISTRATION = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
BLOCKER = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29_coverage_blocker.json"
)
REGISTRY = ROOT / "configs/data_asset_registry.json"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_issuer_integrity_cooldown_v29r1"
)
STAGE_A_FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_development_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
COOLING_CALENDAR_DAYS = 120
SSE_QUERY_START = "1990-12-19"
SZSE_QUERY_START = "2017-10-01"
QUERY_END = "2021-12-31"
EXPECTED_PARENT_SIGNALS = 370
EXPECTED_PARENT_BY_YEAR = {"2018": 310, "2019": 24, "2020": 10, "2021": 26}

_REQUIRED_PARENT_COLUMNS = {
    "gap_id",
    "symbol",
    "signal_date",
    "signal_time",
    "entry_date",
    "entry_time",
    "entry_status",
    "entry_at_or_before_signal",
    "entry_after_signal_period_boundary",
    "buy_at_or_above_up_limit",
    "v28r2_orderly_amount_gate",
    "v28r2_feature_uses_post_signal_information",
}
_OUTCOME_ONLY_COLUMNS = {
    "exit_date",
    "exit_time",
    "exit_raw_price",
    "exit_reason",
    "net_return",
    "holding_sessions",
    "target_coordinate",
    "cash_events_json",
    "lineage_break_before_exit",
}
_REQUIRED_ANNOUNCEMENT_COLUMNS = {
    "component_role",
    "original_adddate",
    "original_ssedate",
    "original_publish_time",
    "causal_available_at",
    "snapshot_id",
    "announcement_key",
    "announcement_id",
    "symbol",
    "exchange",
    "published_at",
    "available_at",
    "precision",
    "source_publication_field",
    "source_publication_value",
    "source_query_date_field",
    "source_query_date",
    "query_year",
    "raw_record_sha256",
    "hard_valid",
    "revision_history_complete",
    "strict_pit_eligible",
}
_TITLE_SOURCE_COLUMNS = [
    "snapshot_id",
    "announcement_key",
    "announcement_id",
    "symbol",
    "title",
    "published_at",
    "available_at",
    "precision",
    "exchange",
    "source_publication_field",
    "source_publication_value",
    "source_query_date_field",
    "source_query_date",
    "query_year",
    "raw_record_sha256",
    "revision_history_complete",
    "strict_pit_eligible",
    "hard_valid",
]
_STRING_IDENTITY_FIELDS = {"symbol", "entry_status"}
_DATE_IDENTITY_FIELDS = {"signal_date", "entry_date"}
_TIMESTAMP_IDENTITY_FIELDS = {"signal_time", "entry_time"}
_INTEGER_IDENTITY_FIELDS = {"entry_cal_idx"}
_FLOAT_IDENTITY_FIELDS = {
    "entry_raw_price",
    "entry_coordinate_factor",
    "entry_coordinate_price",
    "entry_invalid_step_cum",
    "up_limit_price",
}
_BOOLEAN_IDENTITY_FIELDS = {
    "entry_at_or_before_signal",
    "entry_after_signal_period_boundary",
    "buy_at_or_above_up_limit",
}
_AUTH_REQUIRED_ARTIFACT_ROLES = {
    "activation_audit",
    "asset_builder",
    "announcement_route_index",
    "issuer_risk_classifier",
    "parent_development_result_identity",
    "parent_outcome_daily",
    "parent_outcomes",
    "parent_stage_a",
    "prior_v29_coverage_blocker",
}


class V29R1Error(RuntimeError):
    """Fail closed on protocol, source, time, identity, or execution drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V29R1Error(message)


def sha256(path: Path) -> str:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _value_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V29R1Error(f"invalid {label}: {path}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    except FileExistsError as exc:
        raise V29R1Error(f"refusing to overwrite frozen artifact: {path}") from exc


def _write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    except FileExistsError as exc:
        raise V29R1Error(f"refusing to overwrite report: {path}") from exc


def _write_parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _require(not path.exists() and not path.is_symlink(), f"refusing to overwrite parquet: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        os.link(temporary, path)
        path.chmod(0o444)
    except FileExistsError as exc:
        raise V29R1Error(f"refusing to overwrite parquet: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def classified_events_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_classified_events.parquet"


def title_route_selection_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_title_route_selection.parquet"


def selector_audit_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_selector_audit.parquet"


def selected_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_selected_entries.parquet"


def rejected_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_rejected_entries.parquet"


def lane_root() -> Path:
    return EXT_ROOT / "development/issuer_integrity"


def _normalize_symbol(value: object) -> str:
    try:
        return collector.normalize_symbol(value)
    except collector.CaptureError as exc:
        raise V29R1Error(f"invalid symbol: {value!r}") from exc


def _local_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        return classifier._exact_local_timestamp(value, label)
    except classifier.RiskEventInputError as exc:
        raise V29R1Error(str(exc)) from exc


def _source_date(value: object, label: str) -> pd.Timestamp:
    if value is None or value is pd.NaT:
        raise V29R1Error(f"{label} is missing")
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise V29R1Error(f"{label} is invalid: {value!r}") from exc
    _require(not pd.isna(parsed), f"{label} is missing")
    _require(parsed.tzinfo is None, f"{label} must be an exchange-local date")
    _require(parsed == parsed.normalize(), f"{label} must not contain intraday time")
    return parsed


def _same_local_timestamp(left: object, right: pd.Timestamp, label: str) -> None:
    try:
        actual = pd.Timestamp(left)
        if actual.tzinfo is not None:
            actual = actual.tz_convert("Asia/Shanghai").tz_localize(None)
    except (TypeError, ValueError) as exc:
        raise V29R1Error(f"{label} is invalid") from exc
    _require(not pd.isna(actual), f"{label} is missing")
    _require(actual == right, f"{label} differs from the preserved original source value")


def derive_causal_available_at(metadata: pd.DataFrame) -> pd.DataFrame:
    """Derive the frozen routed knowledge time while preserving source fields."""

    missing = sorted(_REQUIRED_ANNOUNCEMENT_COLUMNS.difference(metadata.columns))
    _require(not missing, f"announcement composite is missing columns: {missing}")
    _require(not metadata.empty, "announcement composite is empty; coverage is unknown")
    _require(
        not metadata["announcement_key"].astype("string").duplicated().any(),
        "duplicate announcement_key in composite",
    )
    _require(
        metadata["announcement_key"].notna().all()
        and metadata["raw_record_sha256"].astype("string").str.fullmatch(r"[0-9a-f]{64}").all(),
        "announcement or raw-record identity is missing",
    )
    _require(
        metadata["snapshot_id"].notna().all()
        and metadata["snapshot_id"].astype("string").str.strip().ne("").all(),
        "announcement snapshot lineage is missing",
    )
    _require(
        metadata["hard_valid"].map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value)).all(),
        "composite contains a non-hard-valid row",
    )
    _require(
        metadata["revision_history_complete"].map(
            lambda value: isinstance(value, (bool, np.bool_)) and not bool(value)
        ).all()
        and metadata["strict_pit_eligible"].map(
            lambda value: isinstance(value, (bool, np.bool_)) and not bool(value)
        ).all(),
        "PIT-B revision limitations drifted",
    )

    result = metadata.copy()
    causal: list[pd.Timestamp] = []
    for index, row in result.iterrows():
        exchange = str(row["exchange"])
        role = str(row["component_role"])
        symbol = _normalize_symbol(row["symbol"])
        query_date = _source_date(row["source_query_date"], f"source_query_date at {index!r}")
        try:
            query_year = int(row["query_year"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise V29R1Error(f"invalid query_year at {index!r}") from exc
        _require(query_year == int(query_date.year), f"query_year/date mismatch at {index!r}")
        if exchange == "SSE":
            _require(symbol.endswith(".SH"), f"SSE symbol suffix mismatch at {index!r}")
            _require(
                role == "SSE_FULL_HISTORY_AUTHORITATIVE",
                f"SSE row uses a non-authoritative route at {index!r}",
            )
            _require(
                row["source_publication_field"] == "ADDDATE"
                and row["source_query_date_field"] == "SSEDATE",
                f"SSE original ADDDATE/SSEDATE lineage drifted at {index!r}",
            )
            _require(
                pd.notna(row["original_adddate"])
                and pd.notna(row["original_ssedate"])
                and pd.isna(row["original_publish_time"])
                and str(row["original_adddate"])
                == str(row["source_publication_value"]),
                f"SSE named original-time projection drifted at {index!r}",
            )
            try:
                original_adddate = collector.exact_source_second(
                    row["original_adddate"], "ADDDATE"
                )
                original_ssedate = collector.exact_source_date(
                    row["original_ssedate"], "SSEDATE"
                )
            except collector.CaptureError as exc:
                raise V29R1Error(
                    f"invalid original SSE ADDDATE/SSEDATE at {index!r}"
                ) from exc
            _require(
                query_date == original_ssedate,
                f"SSE named SSEDATE differs from source_query_date at {index!r}",
            )
            _require(
                row["precision"] == "SOURCE_SECOND",
                f"SSE ADDDATE precision drifted at {index!r}",
            )
            _same_local_timestamp(row["published_at"], original_adddate, f"SSE published_at at {index!r}")
            _same_local_timestamp(row["available_at"], original_adddate, f"SSE collector available_at at {index!r}")
            _require(
                pd.Timestamp(SSE_QUERY_START) <= query_date <= pd.Timestamp(QUERY_END),
                f"SSE query-membership date is outside full-history coverage at {index!r}",
            )
            repaired = max(original_adddate, query_date + pd.Timedelta(days=1))
        elif exchange == "SZSE":
            _require(symbol.endswith(".SZ"), f"SZSE symbol suffix mismatch at {index!r}")
            _require(
                role == "BASE_SZSE_AUTHORITATIVE",
                f"SZSE row uses a non-authoritative route at {index!r}",
            )
            _require(
                row["source_publication_field"] == "publishTime"
                and row["source_query_date_field"] == "publishTime",
                f"SZSE original publishTime lineage drifted at {index!r}",
            )
            _require(
                pd.notna(row["original_publish_time"])
                and pd.isna(row["original_adddate"])
                and pd.isna(row["original_ssedate"])
                and str(row["original_publish_time"])
                == str(row["source_publication_value"]),
                f"SZSE named original publishTime projection drifted at {index!r}",
            )
            try:
                original_published, original_available, original_precision = collector.causal_times(
                    row["original_publish_time"]
                )
            except collector.CaptureError as exc:
                raise V29R1Error(f"invalid original SZSE publishTime at {index!r}") from exc
            _require(
                query_date == original_published.normalize(),
                f"SZSE query date differs from publishTime at {index!r}",
            )
            _require(
                pd.Timestamp(SZSE_QUERY_START) <= query_date <= pd.Timestamp(QUERY_END),
                f"SZSE query-membership date is outside frozen coverage at {index!r}",
            )
            _require(
                row["precision"] == original_precision,
                f"SZSE conservative precision drifted at {index!r}",
            )
            _same_local_timestamp(row["published_at"], original_published, f"SZSE published_at at {index!r}")
            _same_local_timestamp(row["available_at"], original_available, f"SZSE collector available_at at {index!r}")
            repaired = original_available
        else:
            raise V29R1Error(f"unsupported exchange at {index!r}: {exchange!r}")
        causal.append(_local_timestamp(repaired, f"causal_available_at at {index!r}"))

    derived = pd.Series(causal, index=result.index, dtype="datetime64[ns, Asia/Shanghai]")
    declared = pd.Series(
        [
            _local_timestamp(value, f"sealed causal_available_at at {index!r}")
            for index, value in result["causal_available_at"].items()
        ],
        index=result.index,
        dtype="datetime64[ns, Asia/Shanghai]",
    )
    _require(
        declared.equals(derived),
        "sealed causal_available_at differs from the frozen derivation",
    )
    result = result.rename(columns={"causal_available_at": "sealed_causal_available_at"})
    result["causal_available_at"] = derived
    return result


def _development_route_scope(
    timed: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter route keys on causal time before any source-title projection."""

    cutoff = _local_timestamp("2022-01-01 00:00:00", "development cutoff")
    future = timed["causal_available_at"].ge(cutoff)
    eligible = timed.loc[~future].copy()
    scope = {
        "sealed_route_rows_read_for_integrity_and_timing": len(timed),
        "route_keys_selected_before_title_read": len(eligible),
        "rows_classified_and_selector_eligible_before_2022": len(eligible),
        "rows_causal_available_from_2022": int(future.sum()),
        "causal_available_from_2022_titles_read": False,
        "causal_available_from_2022_titles_classified": False,
        "causal_available_from_2022_rows_selector_used": False,
        "wording_guard": (
            "The whole sealed <=2021 query-membership route index was verified/read; "
            "only keys with repaired causal time <2022 were used to project titles. "
            "Later-causal titles were neither read, classified, nor selector-used."
        ),
    }
    return eligible, scope


def select_candidate_window_title_routes(
    timed: pd.DataFrame,
    entries: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select the union of exact candidate cooldown windows before title access."""

    _require(
        {"gap_id", "symbol", "signal_time"}.issubset(entries.columns),
        "candidate entries lack route-window fields",
    )
    _require(not entries.empty, "candidate entries are empty")
    _require(not entries["gap_id"].duplicated().any(), "duplicate candidate gap identity")
    route_symbols = timed["symbol"].map(_normalize_symbol)
    selected_mask = pd.Series(False, index=timed.index)
    latest_decision: pd.Timestamp | None = None
    for index, entry in entries.iterrows():
        symbol = _normalize_symbol(entry["symbol"])
        decision_at = _local_timestamp(entry["signal_time"], f"signal_time at {index!r}")
        _require(
            decision_at < _local_timestamp("2022-01-01 00:00:00", "development cutoff"),
            "post-2021 candidate cannot select announcement titles",
        )
        window_start = decision_at - pd.Timedelta(days=COOLING_CALENDAR_DAYS)
        selected_mask |= (
            route_symbols.eq(symbol)
            & timed["causal_available_at"].ge(window_start)
            & timed["causal_available_at"].le(decision_at)
        )
        latest_decision = (
            decision_at if latest_decision is None else max(latest_decision, decision_at)
        )
    eligible = timed.loc[selected_mask].copy()
    cutoff = _local_timestamp("2022-01-01 00:00:00", "development cutoff")
    _require(
        eligible["causal_available_at"].lt(cutoff).all(),
        "candidate route selection contains a causal time from 2022 or later",
    )
    future = timed["causal_available_at"].ge(cutoff)
    scope = {
        "sealed_route_rows_read_for_integrity_and_timing": len(timed),
        "candidate_windows": len(entries),
        "route_keys_selected_and_frozen_before_title_read": len(eligible),
        "rows_classified_and_selector_eligible_before_2022": len(eligible),
        "rows_causal_available_from_2022": int(future.sum()),
        "latest_candidate_decision_at": (
            None if latest_decision is None else latest_decision.isoformat()
        ),
        "causal_available_from_2022_titles_read": False,
        "causal_available_from_2022_titles_classified": False,
        "causal_available_from_2022_rows_selector_used": False,
        "title_access_order": (
            "route index causal-window filter -> immutable role/snapshot/key/hash freeze "
            "-> routed nested-title projection -> exact one-to-one lineage join"
        ),
    }
    return eligible, scope


def _classify_eligible_titles(
    eligible: pd.DataFrame,
    scope: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    _require("title" in eligible.columns, "eligible routes have no bound title")
    cutoff = _local_timestamp("2022-01-01 00:00:00", "development cutoff")
    classifier_input = eligible.rename(
        columns={
            "available_at": "original_collector_available_at",
            "published_at": "original_published_at",
            "precision": "original_precision",
            "causal_available_at": "available_at",
        }
    )
    if eligible.empty:
        classified = classifier_input.copy()
        classified["action"] = pd.Series(dtype="string")
        classified["risk_family"] = pd.Series(dtype="string")
        classified["matched_rule"] = pd.Series(dtype="string")
        classified["classification_version"] = pd.Series(dtype="string")
        return classified, dict(scope)
    try:
        classified = classifier.classify_exchange_announcements(classifier_input)
    except classifier.RiskEventInputError as exc:
        raise V29R1Error(f"title classification failed closed: {exc}") from exc
    _require(
        classified["available_at"].lt(cutoff).all(),
        "classifier output contains a causal time from 2022 or later",
    )
    return classified, dict(scope)


def classify_development_titles(
    metadata: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Pure helper for already attached synthetic/small title metadata."""

    timed = derive_causal_available_at(metadata)
    eligible, scope = _development_route_scope(timed)
    return _classify_eligible_titles(eligible, scope)


def apply_issuer_integrity_cooldown(
    entries: pd.DataFrame,
    classifications: pd.DataFrame,
    *,
    covered_symbols: Sequence[str],
) -> pd.DataFrame:
    """Apply the inclusive OPEN-only veto; CLOSE never erases the cooldown."""

    missing_entries = sorted({"gap_id", "symbol", "signal_date", "signal_time"} - set(entries))
    _require(not missing_entries, f"entries are missing columns: {missing_entries}")
    required_events = {
        "announcement_key",
        "announcement_id",
        "symbol",
        "available_at",
        "action",
        "risk_family",
        "matched_rule",
        "classification_version",
    }
    missing_events = sorted(required_events - set(classifications))
    _require(not missing_events, f"classifications are missing columns: {missing_events}")
    _require(not entries.empty, "parent entries are empty")
    _require(not entries["gap_id"].duplicated().any(), "duplicate parent gap identity")

    work = entries.copy()
    work["symbol"] = work["symbol"].map(_normalize_symbol)
    work["signal_date"] = pd.to_datetime(work["signal_date"], errors="raise").dt.normalize()
    signal_times = [
        _local_timestamp(value, f"signal_time at {index!r}")
        for index, value in work["signal_time"].items()
    ]
    covered_values = list(covered_symbols)
    covered = {_normalize_symbol(value) for value in covered_values}
    _require(len(covered) == len(covered_values), "covered symbol identity is duplicated")

    events = classifications.copy()
    events["symbol"] = events["symbol"].map(_normalize_symbol)
    events["available_at"] = [
        _local_timestamp(value, f"event available_at at {index!r}")
        for index, value in events["available_at"].items()
    ]
    _require(
        events["classification_version"].eq(classifier.CLASSIFICATION_VERSION).all(),
        "classification version drifted",
    )
    _require(
        events["action"].isin(
            {classifier.ACTION_OPEN, classifier.ACTION_CLOSE, classifier.ACTION_IGNORE}
        ).all(),
        "unsupported classifier action",
    )
    recognized = events["action"].isin({classifier.ACTION_OPEN, classifier.ACTION_CLOSE})
    _require(
        events.loc[recognized, "risk_family"].isin(classifier.RISK_FAMILIES).all(),
        "recognized event has an unsupported family",
    )
    _require(
        not events.loc[events["action"].eq(classifier.ACTION_OPEN)].duplicated(
            ["announcement_key", "risk_family"]
        ).any(),
        "duplicate OPEN announcement/family identity",
    )
    open_events = events.loc[events["action"].eq(classifier.ACTION_OPEN)].sort_values(
        ["symbol", "available_at", "announcement_key", "risk_family"],
        kind="mergesort",
    )
    open_by_symbol = {
        symbol: frame.reset_index(drop=True)
        for symbol, frame in open_events.groupby("symbol", sort=False)
    }

    records: list[dict[str, Any]] = []
    end_exclusive = _local_timestamp("2022-01-01 00:00:00", "query end")
    for row_number, (_, entry) in enumerate(work.iterrows()):
        signal_at = signal_times[row_number]
        window_start = signal_at - pd.Timedelta(days=COOLING_CALENDAR_DAYS)
        symbol = str(entry["symbol"])
        exchange_start = SSE_QUERY_START if symbol.endswith(".SH") else SZSE_QUERY_START
        coverage_start = _local_timestamp(f"{exchange_start} 00:00:00", "coverage start")
        failures: list[str] = []
        if symbol not in covered:
            failures.append("SYMBOL_NOT_IN_SEALED_UNIVERSE")
        if window_start < coverage_start:
            failures.append("WINDOW_START_PRECEDES_EXCHANGE_QUERY_COVERAGE")
        if signal_at >= end_exclusive:
            failures.append("SIGNAL_AFTER_SEALED_QUERY_COVERAGE")
        if int(entry["signal_date"].year) not in DEVELOPMENT_YEARS:
            failures.append("SIGNAL_YEAR_OUTSIDE_DEVELOPMENT")
        complete = not failures

        symbol_events = open_by_symbol.get(symbol, pd.DataFrame(columns=open_events.columns))
        matched = symbol_events.loc[
            symbol_events["available_at"].ge(window_start)
            & symbol_events["available_at"].le(signal_at)
        ].sort_values(["available_at", "announcement_key", "risk_family"], kind="mergesort")
        event_payload = [
            {
                "announcement_key": str(event.announcement_key),
                "announcement_id": str(event.announcement_id),
                "causal_available_at": pd.Timestamp(event.available_at).isoformat(),
                "risk_family": str(event.risk_family),
                "matched_rule": str(event.matched_rule),
            }
            for event in matched.itertuples(index=False)
        ]
        keys = sorted({event["announcement_key"] for event in event_payload})
        families = sorted({event["risk_family"] for event in event_payload})
        gate = complete and not event_payload
        reason = (
            "INCOMPLETE_COVERAGE:" + "|".join(failures)
            if failures
            else "RECENT_HIGH_PRECISION_OPEN_ISSUER_RISK"
            if event_payload
            else ""
        )
        records.append(
            {
                "gap_id": entry["gap_id"],
                "v29r1_signal_time_local": signal_at,
                "v29r1_window_start_at": window_start,
                "v29r1_window_end_at": signal_at,
                "v29r1_exchange_query_coverage_start": coverage_start,
                "v29r1_coverage_complete": complete,
                "v29r1_coverage_failure_reasons": "|".join(failures),
                "v29r1_open_transition_count": len(event_payload),
                "v29r1_open_announcement_count": len(keys),
                "v29r1_open_announcement_keys": "|".join(keys),
                "v29r1_open_risk_families": "|".join(families),
                "v29r1_open_events_json": _canonical_json(event_payload),
                "v29r1_latest_open_causal_available_at": (
                    pd.NaT if matched.empty else matched["available_at"].max()
                ),
                "v29r1_issuer_integrity_cooldown_gate": gate,
                "v29r1_rejection_reason": reason,
                "v29r1_feature_uses_post_signal_information": False,
            }
        )
    result = work.merge(pd.DataFrame.from_records(records), on="gap_id", validate="one_to_one")
    _require(
        result.loc[
            result["v29r1_issuer_integrity_cooldown_gate"], "v29r1_coverage_complete"
        ].all(),
        "selector admitted an incompletely covered signal",
    )
    return result


def _software_paths() -> dict[str, Path]:
    return {
        "execution_repair_runner_sha256": Path(v28.replay.repair.__file__).resolve(),
        "lane_replay_runner_sha256": Path(v28.replay.__file__).resolve(),
        "parent_selector_runner_sha256": Path(v28r2.__file__).resolve(),
        "portfolio_runner_sha256": Path(v28.replay.repair.v1.__file__).resolve(),
    }


def _parent_source_paths() -> dict[str, Path]:
    paths = v28.replay.source_paths("DEVELOPMENT")
    return {"outcomes": paths["outcomes"], "outcome_daily": paths["outcome_daily"]}


def _verify_protocol() -> tuple[dict[str, Any], dict[str, Any]]:
    _require(sha256(PREREGISTRATION) == EXPECTED_PREREGISTRATION_SHA256, "V29R1 preregistration SHA-256 drifted")
    _require(sha256(BLOCKER) == EXPECTED_BLOCKER_SHA256, "prior V29 coverage blocker drifted")
    prereg = _read_json_object(PREREGISTRATION, "V29R1 preregistration")
    blocker = _read_json_object(BLOCKER, "prior V29 coverage blocker")
    _require(
        prereg.get("experiment") == EXPERIMENT
        and prereg.get("status") == "SEMANTIC_RULE_FROZEN_BEFORE_DEVELOPMENT_EVENT_OR_OUTCOME_JOIN",
        "V29R1 preregistration status drifted",
    )
    _require(prereg.get("parent") == v28r2.EXPERIMENT, "V29R1 parent drifted")
    prior = prereg.get("prior_v29_blocker", {})
    _require(
        prior.get("artifact_sha256") == EXPECTED_BLOCKER_SHA256
        and prior.get("status") == "FAIL_CLOSED_SSE_ADDDATE_DOMAIN_COVERAGE_NOT_PROVEN"
        and prior.get("v29_cy036_registration_or_backtest_authorized") is False,
        "V29R1 does not retain the V29 coverage blocker",
    )
    _require(
        blocker.get("conclusion", {}).get("status") == prior.get("status")
        and blocker.get("conclusion", {}).get("backtest_authorized") is False
        and blocker.get("conclusion", {}).get("central_registry_registration_authorized") is False,
        "prior V29 blocker semantics drifted",
    )
    condition = prereg.get("only_new_economic_condition", {})
    _require(
        condition.get("families") == list(classifier.RISK_FAMILIES)
        and condition.get("window") == "signal_time - 120 calendar days <= causal_available_at <= signal_time"
        and condition.get("close_treatment") == "An explicit CLOSE never shortens the 120-calendar-day cooling period."
        and condition.get("missing_or_unproven_coverage") == "REJECT",
        "V29R1 selector contract drifted",
    )
    coverage = prereg.get("source_coverage_contract", {})
    _require(
        coverage.get("sse", {}).get("start") == SSE_QUERY_START
        and coverage.get("sse", {}).get("end") == QUERY_END
        and coverage.get("sse", {}).get("membership_field") == "SSEDATE"
        and coverage.get("szse", {}).get("start") == SZSE_QUERY_START
        and coverage.get("szse", {}).get("end") == QUERY_END
        and coverage.get("szse", {}).get("knowledge_field") == "publishTime"
        and coverage.get("title_metadata_only") is True
        and coverage.get("unknown_page_identity_hash_or_coverage") == "FAIL_CLOSED",
        "V29R1 routed source coverage contract drifted",
    )
    repair = prereg.get("knowledge_time_repair", {})
    _require(
        repair.get("derivation_must_preserve_original_fields") == ["ADDDATE", "SSEDATE", "publishTime"]
        and repair.get("sse", {}).get("causal_available_at")
        == "max(original ADDDATE, SSEDATE + 1 calendar day 00:00 Asia/Shanghai)"
        and repair.get("sse", {}).get("missing_or_invalid_adddate_or_ssedate") == "FAIL_CLOSED"
        and repair.get("szse", {}).get("missing_or_invalid_publishTime") == "FAIL_CLOSED",
        "V29R1 causal-time repair contract drifted",
    )
    _require(
        prereg.get("development", {}).get("signal_years") == list(DEVELOPMENT_YEARS),
        "V29R1 development years drifted",
    )

    parent_paths = {
        "parent_runner_sha256": Path(v28r2.__file__).resolve(),
        "parent_development_stage_a_sha256": v28r2.STAGE_A_FREEZE,
        "parent_development_result_sha256": v28r2.DEVELOPMENT_RESULT,
    }
    for key, path in parent_paths.items():
        _require(prereg.get(key) == sha256(path), f"{key} drifted")
    blocker_classifier_hash = blocker.get("software_hashes", {}).get("classifier_runner_sha256")
    _require(
        blocker_classifier_hash == sha256(Path(classifier.__file__).resolve()),
        "issuer-risk classifier differs from the blocker-bound identity",
    )

    replay = prereg.get("stage_b_identity_and_replay_freeze", {})
    expected_software = replay.get("software_hashes_frozen_now")
    current_software = {key: sha256(path) for key, path in _software_paths().items()}
    _require(expected_software == current_software, "replay/repair/portfolio software hash drift")
    constant = replay.get("constant_contract", {})
    _require(
        constant.get("portfolio_k_per_sleeve") == v28.replay.PORTFOLIO_K == 80
        and constant.get("target_fraction") == v28.replay.TARGET_FRACTION == v28.replay.repair.v1.TARGET_FRACTION == 0.67
        and constant.get("maximum_holding_sessions") == v28.replay.TIME_STOP == v28.replay.repair.v1.TIME_STOP == 20
        and constant.get("side_cost_entry") == v28.replay.repair.v1.COST == 0.002
        and constant.get("side_cost_exit") == v28.replay.repair.v1.COST == 0.002
        and constant.get("round_trip_cost") == 0.004
        and constant.get("failure_stop") == "NONE",
        "K80/A67/H20/cost/stop constant contract drifted",
    )
    expected_sources = replay.get("actual_parent_source_hashes")
    source_paths = _parent_source_paths()
    current_sources = {name: sha256(path) for name, path in source_paths.items()}
    _require(current_sources == expected_sources, "actual parent outcome source hash drift")
    exact_fields = replay.get("join_contract", {}).get("exact_fields")
    _require(
        exact_fields
        == [
            "symbol",
            "signal_date",
            "signal_time",
            "entry_date",
            "entry_time",
            "entry_status",
            "entry_cal_idx",
            "entry_raw_price",
            "entry_coordinate_factor",
            "entry_coordinate_price",
            "entry_invalid_step_cum",
            "up_limit_price",
            "entry_at_or_before_signal",
            "entry_after_signal_period_boundary",
            "buy_at_or_above_up_limit",
        ],
        "exact selected/outcome join fields drifted",
    )
    hashes = {
        "preregistration_sha256": sha256(PREREGISTRATION),
        "prior_v29_blocker_sha256": sha256(BLOCKER),
        "classifier_runner_sha256": sha256(Path(classifier.__file__).resolve()),
        "parent_runner_sha256": sha256(Path(v28r2.__file__).resolve()),
        "parent_stage_a_sha256": sha256(v28r2.STAGE_A_FREEZE),
        "parent_development_result_sha256": sha256(v28r2.DEVELOPMENT_RESULT),
        "software_hashes": current_software,
        "parent_source_hashes_streamed_without_parsing": current_sources,
    }
    return prereg, hashes


def _fingerprints_by_role(authorization: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = authorization.get("bound_artifacts")
    _require(isinstance(values, list), "bounded authorization has no artifact list")
    result: dict[str, Mapping[str, Any]] = {}
    for value in values:
        _require(isinstance(value, dict), "bounded authorization artifact is not an object")
        role = value.get("role")
        _require(isinstance(role, str) and role, "bounded authorization artifact role is missing")
        _require(role not in result, f"duplicate bounded artifact role: {role}")
        result[role] = value
    return result


def _require_fingerprint(value: object, path: Path, expected_hash: str, label: str) -> None:
    _require(isinstance(value, dict), f"{label} fingerprint is missing")
    _require(
        value.get("path") == str(path) and value.get("sha256") == expected_hash,
        f"{label} fingerprint drifted",
    )


def _validate_title_route_contract(
    manifest: Mapping[str, Any],
    *,
    asset_root: Path,
    base_root: Path,
) -> dict[str, Any]:
    contract = manifest.get("title_route_contract")
    _require(isinstance(contract, dict), "CY-036-R1 title_route_contract is missing")
    _require(
        contract.get("build_time_title_handling")
        == {
            "nested_sealer_reparsed_and_validated_title_metadata_from_raw_pages": True,
            "wrapper_projected_or_copied_title_column": False,
            "wrapper_classified_title_column": False,
        },
        "CY-036-R1 build-time title handling drifted",
    )
    _require(
        contract.get("required_access_order")
        == [
            (
                "Validate CY-036-R1 and filter announcement_route_index.parquet using "
                "window_start <= causal_available_at <= decision_at."
            ),
            (
                "Freeze the selected component_role, snapshot_id, announcement_key and "
                "lineage hashes before opening a nested title column."
            ),
            (
                "Open only the routed nested announcements rows for those frozen keys, "
                "then enforce the exact one-to-one join and lineage equality."
            ),
        ],
        "CY-036-R1 required title-access order drifted",
    )
    _require(
        contract.get("causal_cutoff_column") == "causal_available_at"
        and contract.get("causal_cutoff_relation")
        == "causal_available_at <= decision_at"
        and contract.get("route_index_selection_fields")
        == [
            "component_role",
            "snapshot_id",
            "announcement_key",
            "raw_record_sha256",
        ]
        and contract.get("component_selection_key") == "component_role"
        and contract.get("nested_title_column") == "title"
        and contract.get("nested_join_keys") == ["snapshot_id", "announcement_key"]
        and contract.get("join_cardinality") == "one_to_one"
        and contract.get("unmatched_or_duplicate_policy")
        == "FAIL_CLOSED_NO_SILENT_ROW_LOSS_OR_DEDUPLICATION",
        "CY-036-R1 title routing or cardinality contract drifted",
    )
    expected_post_join = [
        "raw_record_sha256",
        "symbol",
        "exchange",
        "source_publication_field",
        "source_publication_value",
        "source_query_date_field",
        "source_query_date",
    ]
    _require(
        contract.get("post_join_exact_fields") == expected_post_join,
        "CY-036-R1 post-title-join exact fields drifted",
    )
    roles = contract.get("roles")
    _require(isinstance(roles, dict), "CY-036-R1 title roles are missing")
    expected_roles = {
        "SSE_FULL_HISTORY_AUTHORITATIVE": (
            asset_root / cy036r1.SSE_CAPTURE_NAME / "announcements.parquet",
            "SSE",
            "sse_full_history_nested_announcements",
        ),
        "BASE_SZSE_AUTHORITATIVE": (
            base_root / "announcements.parquet",
            "SZSE",
            "base_nested_announcements",
        ),
    }
    _require(set(roles) == set(expected_roles), "CY-036-R1 title role set drifted")
    source_routing = manifest.get("source_routing", {})
    for role, (path, exchange, inventory_role) in expected_roles.items():
        item = roles.get(role)
        _require(isinstance(item, dict), f"CY-036-R1 title role {role} is missing")
        _require(
            item.get("nested_announcements_path") == str(path.resolve(strict=True))
            and item.get("expected_exchange") == exchange
            and item.get("inventory_role") == inventory_role
            and item.get("snapshot_id")
            == source_routing.get(role, {}).get("snapshot_id"),
            f"CY-036-R1 title role binding drifted: {role}",
        )
    content = manifest.get("content", {})
    _require(
        content.get("route_index_includes_title") is False
        and content.get("classification_included") is False
        and content.get("outcomes_included") is False
        and content.get("route_index_columns")
        == [
            "component_role",
            "original_adddate",
            "original_ssedate",
            "original_publish_time",
            "causal_available_at",
            "snapshot_id",
            "announcement_key",
            "announcement_id",
            "source_record_key",
            "symbol",
            "security_code",
            "published_at",
            "available_at",
            "precision",
            "document_url",
            "exchange",
            "source",
            "source_endpoint",
            "source_publication_field",
            "source_publication_value",
            "source_query_date_field",
            "source_query_date",
            "query_id",
            "query_year",
            "raw_record_sha256",
            "revision_history_complete",
            "strict_pit_eligible",
            "hard_valid",
        ],
        "CY-036-R1 route-index schema/content boundary drifted",
    )
    _require(
        manifest.get("pit", {}).get("knowledge_time") == "causal_available_at only",
        "CY-036-R1 manifest does not bind repaired causal knowledge time",
    )
    return dict(contract)


def _validate_registry_documents(
    registry: Mapping[str, Any],
    asset: Mapping[str, Any],
    authorization: Mapping[str, Any],
    manifest: Mapping[str, Any],
    *,
    manifest_path: Path,
) -> None:
    _require(
        registry.get("global_gate", {}).get("free_causal_research_ready") is True
        and registry.get("global_gate", {}).get("backtest_authorized") is True,
        "central research/backtest gate is not open",
    )
    _require(
        asset.get("asset_id") == ASSET_ID
        and asset.get("status") == "RESEARCH_CONDITIONAL"
        and asset.get("physical_state") == "MATERIALIZED"
        and asset.get("pit_grade") == "B",
        "CY-036-R1 registry state is not bounded PIT-B research input",
    )
    lineage = asset.get("lineage", {})
    _require(
        lineage.get("record_available_at") is True
        and lineage.get("record_snapshot_id") is True
        and lineage.get("immutable_manifest") is True
        and lineage.get("bounded_authorization_id") == AUTHORIZATION_ID,
        "CY-036-R1 lineage or authorization binding drifted",
    )
    _require(
        lineage.get("manifest_path") == str(manifest_path)
        and lineage.get("manifest_sha256") == sha256(manifest_path),
        "CY-036-R1 registered manifest fingerprint drifted",
    )
    coverage = asset.get("coverage", {})
    _require(
        coverage.get("sse_query_start") == SSE_QUERY_START
        and coverage.get("szse_query_start") == SZSE_QUERY_START
        and coverage.get("query_end") == QUERY_END
        and coverage.get("signal_start") == "2018-01-01"
        and coverage.get("signal_end") == QUERY_END,
        "CY-036-R1 registered routed coverage drifted",
    )
    _require(
        authorization.get("authorization_id") == AUTHORIZATION_ID
        and authorization.get("purpose") == AUTHORIZATION_PURPOSE
        and authorization.get("asset_id") == ASSET_ID
        and authorization.get("dependency_asset_id") == "CY-033"
        and authorization.get("dependency_status") == "RESEARCH_CONDITIONAL"
        and authorization.get("record_level_available_at_available") is True
        and authorization.get("current_survivor_fallback_allowed") is False
        and authorization.get("event_classification_authorized") is True
        and authorization.get("development_outcome_join_authorized") is True
        and authorization.get("portfolio_replay_authorized") is True
        and authorization.get("post_2021_announcement_classification_authorized")
        is False
        and authorization.get("post_2021_signal_or_selector_authorized") is False,
        "V29R1 bounded authorization flags drifted",
    )
    dependency_matches = [
        item
        for item in registry.get("assets", [])
        if isinstance(item, dict)
        and item.get("asset_id") == authorization.get("dependency_asset_id")
    ]
    _require(
        len(dependency_matches) == 1
        and dependency_matches[0].get("status")
        == authorization.get("dependency_status"),
        "V29R1 bounded dependency is missing or has status drift",
    )
    scope = authorization.get("scope", {})
    _require(
        scope.get("project") == "research/market_behavior_os_v2"
        and scope.get("start") == SSE_QUERY_START
        and scope.get("end") == QUERY_END
        and scope.get("signal_start") == "2018-01-01"
        and scope.get("signal_end") == QUERY_END
        and scope.get("sse_query_start") == SSE_QUERY_START
        and scope.get("szse_query_start") == SZSE_QUERY_START,
        "V29R1 bounded authorization scope drifted",
    )
    manifest_hash = sha256(manifest_path)
    _require_fingerprint(authorization.get("bound_manifest"), manifest_path, manifest_hash, "bound manifest")
    _require_fingerprint(
        authorization.get("bound_strategy"),
        PREREGISTRATION,
        EXPECTED_PREREGISTRATION_SHA256,
        "bound strategy",
    )
    protocol = authorization.get("bound_protocol")
    _require_fingerprint(protocol, PREREGISTRATION, EXPECTED_PREREGISTRATION_SHA256, "bound protocol")
    _require(
        isinstance(protocol, dict)
        and protocol.get("runner_path") == str(Path(__file__).resolve())
        and protocol.get("runner_sha256") == sha256(Path(__file__).resolve()),
        "bounded protocol runner binding drifted",
    )
    artifacts = _fingerprints_by_role(authorization)
    _require(
        set(artifacts) == _AUTH_REQUIRED_ARTIFACT_ROLES,
        "bounded authorization artifact-role set drifted",
    )
    root = manifest_path.parent
    expected = {
        "activation_audit": root / cy036r1.ACTIVATION_AUDIT_NAME,
        "asset_builder": Path(cy036r1.__file__).resolve(),
        "announcement_route_index": root / cy036r1.COMPOSITE_NAME,
        "issuer_risk_classifier": Path(classifier.__file__).resolve(),
        "parent_development_result_identity": v28r2.DEVELOPMENT_RESULT,
        "parent_outcome_daily": _parent_source_paths()["outcome_daily"],
        "parent_outcomes": _parent_source_paths()["outcomes"],
        "parent_stage_a": v28r2.STAGE_A_FREEZE,
        "prior_v29_coverage_blocker": BLOCKER,
    }
    for role, path in expected.items():
        _require_fingerprint(artifacts[role], path, sha256(path), role)
    _require(
        manifest.get("asset_id") == ASSET_ID
        and manifest.get("status") == "PASS"
        and manifest.get("registered") is False
        and manifest.get("backtest_authorized") is False
        and manifest.get("protocol_binding", {}).get("experiment") == EXPERIMENT
        and manifest.get("protocol_binding", {}).get("preregistration_sha256")
        == EXPECTED_PREREGISTRATION_SHA256,
        "sealed CY-036-R1 manifest protocol or non-authorizing state drifted",
    )


def verify_registered_cy036r1() -> dict[str, Any]:
    registry = _read_json_object(REGISTRY, "central data-asset registry")
    assets = [
        item
        for item in registry.get("assets", [])
        if isinstance(item, dict) and item.get("asset_id") == ASSET_ID
    ]
    authorizations = [
        item
        for item in registry.get("bounded_authorizations", [])
        if isinstance(item, dict) and item.get("authorization_id") == AUTHORIZATION_ID
    ]
    _require(len(assets) == 1, f"{ASSET_ID} must resolve to exactly one registry entry")
    _require(len(authorizations) == 1, f"{AUTHORIZATION_ID} must resolve exactly once")
    asset = assets[0]
    authorization = authorizations[0]
    root = Path(str(asset.get("location", "")))
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink(), "CY-036-R1 location is missing or unsafe")
    manifest_path = root / cy036r1.ASSET_MANIFEST_NAME
    manifest = _read_json_object(manifest_path, "CY-036-R1 asset manifest")
    _validate_registry_documents(
        registry,
        asset,
        authorization,
        manifest,
        manifest_path=manifest_path,
    )
    base_root = Path(
        str(manifest.get("source_routing", {}).get("BASE_SZSE_AUTHORITATIVE", {}).get("root", ""))
    )
    _require(base_root.is_absolute(), "CY-036-R1 base component root is missing")
    title_route_contract = _validate_title_route_contract(
        manifest,
        asset_root=root,
        base_root=base_root,
    )
    try:
        sealed = cy036r1.validate_asset(root, base_root)
    except Exception as exc:
        raise V29R1Error(f"CY-036-R1 full nested validation failed: {exc}") from exc
    _require(
        sealed.get("status") == "PASS"
        and sealed.get("asset_id") == ASSET_ID
        and sealed.get("asset_manifest_sha256") == sha256(manifest_path),
        "CY-036-R1 nested validation identity drifted",
    )
    base = cy036r1._base_identity(base_root, full_seal=False)
    covered_symbols = list(base["symbols"])
    _require(
        len(covered_symbols) == cy036r1.EXPECTED_BASE_SYMBOLS,
        "CY-036-R1 covered universe size drifted",
    )
    return {
        "asset_root": str(root),
        "base_component_root": str(base_root),
        "asset_manifest_sha256": sha256(manifest_path),
        "registered_asset_entry_sha256": _value_sha256(asset),
        "bounded_authorization_sha256": _value_sha256(authorization),
        "data_asset_registry_sha256": sha256(REGISTRY),
        "covered_symbols": covered_symbols,
        "composite_sha256": sha256(root / cy036r1.COMPOSITE_NAME),
        "activation_audit_sha256": sha256(root / cy036r1.ACTIVATION_AUDIT_NAME),
        "title_route_contract": title_route_contract,
        "base_nested_files_verified": sealed.get("base_nested_files_verified"),
        "sse_nested_files_verified": sealed.get("sse_nested_files_verified"),
    }


def _load_parent_entries() -> pd.DataFrame:
    entries = pd.read_parquet(v28r2.selected_path())
    missing = sorted(_REQUIRED_PARENT_COLUMNS.difference(entries.columns))
    _require(not missing, f"V28R2 selected identity is missing columns: {missing}")
    outcome_columns = sorted(_OUTCOME_ONLY_COLUMNS.intersection(entries.columns))
    _require(not outcome_columns, f"Stage A parent contains outcome-only columns: {outcome_columns}")
    _require(len(entries) == EXPECTED_PARENT_SIGNALS, "V28R2 selected row count drifted")
    _require(not entries["gap_id"].duplicated().any(), "V28R2 duplicate gap identity")
    _require(
        entries["v28r2_orderly_amount_gate"].eq(True).all()
        and entries["v28r2_feature_uses_post_signal_information"].eq(False).all(),
        "V28R2 causal orderly-demand invariant failed",
    )
    signal_dates = pd.to_datetime(entries["signal_date"], errors="raise")
    signal_times = pd.to_datetime(entries["signal_time"], errors="raise")
    entry_times = pd.to_datetime(entries["entry_time"], errors="raise")
    _require(
        signal_dates.dt.year.isin(DEVELOPMENT_YEARS).all()
        and signal_dates.max() <= pd.Timestamp(QUERY_END),
        "V28R2 parent contains a post-2021 signal",
    )
    _require(
        entry_times.gt(signal_times).all()
        and entries["entry_at_or_before_signal"].eq(False).all()
        and entries["entry_after_signal_period_boundary"].eq(False).all()
        and entries["buy_at_or_above_up_limit"].eq(False).all(),
        "V28R2 parent T+1/period-boundary/up-limit invariant failed",
    )
    yearly = signal_dates.dt.year.value_counts()
    _require(
        {str(year): int(yearly.get(year, 0)) for year in DEVELOPMENT_YEARS}
        == EXPECTED_PARENT_BY_YEAR,
        "V28R2 parent yearly identity drifted",
    )
    return entries


def _source_identity_equal(left: object, right: object) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if isinstance(left, (pd.Timestamp, np.datetime64)) or isinstance(
        right, (pd.Timestamp, np.datetime64)
    ):
        try:
            return pd.Timestamp(left) == pd.Timestamp(right)
        except (TypeError, ValueError):
            return False
    return type(left) is type(right) and left == right


def attach_authoritative_titles(
    route_index: pd.DataFrame,
    sse_announcements: pd.DataFrame,
    base_announcements: pd.DataFrame,
    *,
    additional_exact_fields: Sequence[str] = (),
) -> pd.DataFrame:
    """Attach titles from the one authoritative route with exact identity proof."""

    base_compare_fields = [
        "snapshot_id",
        "announcement_id",
        "symbol",
        "exchange",
        "published_at",
        "available_at",
        "precision",
        "source_publication_field",
        "source_publication_value",
        "source_query_date_field",
        "source_query_date",
        "query_year",
        "raw_record_sha256",
        "hard_valid",
        "revision_history_complete",
        "strict_pit_eligible",
    ]
    compare_fields = list(dict.fromkeys([*base_compare_fields, *additional_exact_fields]))
    required_route = {"announcement_key", "component_role", *compare_fields}
    required_source = {"announcement_key", "title", *compare_fields}
    _require(
        required_route.issubset(route_index.columns),
        "route index lacks title-join identity fields",
    )
    for label, frame in (
        ("SSE title source", sse_announcements),
        ("base title source", base_announcements),
    ):
        _require(
            required_source.issubset(frame.columns),
            f"{label} lacks title-join identity fields",
        )
    authoritative_sse = sse_announcements.loc[
        sse_announcements["exchange"].eq("SSE")
    ].copy()
    authoritative_szse = base_announcements.loc[
        base_announcements["exchange"].eq("SZSE")
    ].copy()
    source = pd.concat([authoritative_sse, authoritative_szse], ignore_index=True)
    _require(
        not route_index["announcement_key"].duplicated().any()
        and not source["announcement_key"].duplicated().any(),
        "title route contains duplicate announcement identity",
    )
    route_keys = set(route_index["announcement_key"].astype(str))
    source_keys = set(source["announcement_key"].astype(str))
    _require(
        route_keys == source_keys and len(route_index) == len(source),
        "authoritative title source and route-index identity sets differ",
    )
    source_by_key = {
        str(row["announcement_key"]): row for _, row in source.iterrows()
    }
    titles: list[str] = []
    for _, routed in route_index.iterrows():
        key = str(routed["announcement_key"])
        original = source_by_key[key]
        expected_role = (
            "SSE_FULL_HISTORY_AUTHORITATIVE"
            if original["exchange"] == "SSE"
            else "BASE_SZSE_AUTHORITATIVE"
        )
        _require(
            routed["component_role"] == expected_role,
            f"announcement route conflicts with title source at {key}",
        )
        for field in compare_fields:
            _require(
                _source_identity_equal(routed[field], original[field]),
                f"title-source identity mismatch at {key}.{field}",
            )
        title = original["title"]
        _require(
            isinstance(title, str) and bool(title.strip()),
            f"authoritative title is missing at {key}",
        )
        titles.append(title)
    result = route_index.copy()
    result["title"] = titles
    return result


def _read_authoritative_title_rows(
    source_path: Path,
    eligible_routes: pd.DataFrame,
    *,
    component_role: str,
    exchange: str,
    additional_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Project titles only for causal-pre-2022 route keys via an inner join."""

    _require(
        source_path.is_file() and not source_path.is_symlink(),
        f"missing or unsafe authoritative title source: {source_path}",
    )
    wanted = eligible_routes.loc[
        eligible_routes["component_role"].eq(component_role),
        ["snapshot_id", "announcement_key"],
    ].copy()
    _require(
        wanted[["snapshot_id", "announcement_key"]].notna().all().all()
        and not wanted.duplicated(["snapshot_id", "announcement_key"]).any(),
        f"eligible {exchange} title keys are missing or duplicated",
    )
    projected_columns = list(dict.fromkeys([*_TITLE_SOURCE_COLUMNS, *additional_columns]))
    if wanted.empty:
        return pd.DataFrame(columns=projected_columns)
    projection = ", ".join(f'a."{column}"' for column in projected_columns)
    connection = duckdb.connect()
    try:
        connection.register("eligible_title_keys", wanted)
        result = connection.execute(
            f"""
            SELECT {projection}
            FROM read_parquet(?) AS a
            INNER JOIN eligible_title_keys AS k
              ON a.snapshot_id = k.snapshot_id
             AND a.announcement_key = k.announcement_key
            WHERE a.exchange = ?
            ORDER BY a.announcement_key
            """,
            [str(source_path), exchange],
        ).fetchdf()
    except Exception as exc:
        raise V29R1Error(
            f"unable to project only eligible {exchange} authoritative titles"
        ) from exc
    finally:
        connection.close()
    _require(
        len(result) == len(wanted)
        and set(result["announcement_key"].astype(str))
        == set(wanted["announcement_key"].astype(str)),
        f"eligible {exchange} title projection did not conserve key identity",
    )
    return result


def _load_classifications(
    asset: Mapping[str, Any],
    entries: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = Path(str(asset["asset_root"])) / cy036r1.COMPOSITE_NAME
    _require(path.is_file() and not path.is_symlink(), "CY-036-R1 composite is missing")
    try:
        route_index = pd.read_parquet(path)
    except Exception as exc:
        raise V29R1Error("unable to read sealed CY-036-R1 route index") from exc
    timed = derive_causal_available_at(route_index)
    eligible_routes, scope = select_candidate_window_title_routes(timed, entries)
    title_contract = asset.get("title_route_contract")
    _require(isinstance(title_contract, dict), "validated title-route contract is missing")
    route_selection_fields = title_contract["route_index_selection_fields"]
    frozen_route_fields = [*route_selection_fields, "causal_available_at"]
    _require(
        set(frozen_route_fields).issubset(eligible_routes.columns),
        "eligible title route cannot freeze the contracted lineage fields",
    )
    route_freeze = eligible_routes[frozen_route_fields].sort_values(
        ["causal_available_at", "component_role", "snapshot_id", "announcement_key"],
        kind="mergesort",
    ).reset_index(drop=True)
    _write_parquet_exclusive(title_route_selection_path(), route_freeze)
    scope["title_route_selection_fields"] = frozen_route_fields
    scope["title_route_selection_sha256"] = sha256(title_route_selection_path())
    exact_fields = title_contract["post_join_exact_fields"]
    sse_announcements = _read_authoritative_title_rows(
        Path(str(asset["asset_root"]))
        / cy036r1.SSE_CAPTURE_NAME
        / "announcements.parquet",
        eligible_routes,
        component_role="SSE_FULL_HISTORY_AUTHORITATIVE",
        exchange="SSE",
        additional_columns=exact_fields,
    )
    base_announcements = _read_authoritative_title_rows(
        Path(str(asset["base_component_root"])) / "announcements.parquet",
        eligible_routes,
        component_role="BASE_SZSE_AUTHORITATIVE",
        exchange="SZSE",
        additional_columns=exact_fields,
    )
    metadata = attach_authoritative_titles(
        eligible_routes,
        sse_announcements,
        base_announcements,
        additional_exact_fields=exact_fields,
    )
    return _classify_eligible_titles(metadata, scope)


def _require_pristine_stage_a_outputs() -> None:
    existing = [
        path
        for path in (
            classified_events_path(),
            title_route_selection_path(),
            selector_audit_path(),
            selected_path(),
            rejected_path(),
            STAGE_A_FREEZE,
            DEVELOPMENT_RESULT,
            REPORT,
            lane_root(),
        )
        if path.exists()
    ]
    _require(not existing, f"V29R1 Stage-A outputs already exist: {existing}")


def _require_pristine_stage_b_outputs() -> None:
    existing = [path for path in (DEVELOPMENT_RESULT, REPORT, lane_root()) if path.exists()]
    _require(not existing, f"V29R1 Stage-B outputs already exist: {existing}")


def _identity_sha256(values: Sequence[object]) -> str:
    return _value_sha256(sorted(str(value) for value in values))


def run_stage_a() -> dict[str, Any]:
    """Freeze selector identity; outcome files are byte-hashed, never parsed."""

    _require_pristine_stage_a_outputs()
    asset = verify_registered_cy036r1()
    _, protocol_hashes = _verify_protocol()
    entries = _load_parent_entries()
    classifications, temporal_scope = _load_classifications(asset, entries)
    audit = apply_issuer_integrity_cooldown(
        entries,
        classifications,
        covered_symbols=asset["covered_symbols"],
    ).sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    selected = audit.loc[audit["v29r1_issuer_integrity_cooldown_gate"]].copy()
    rejected = audit.loc[~audit["v29r1_issuer_integrity_cooldown_gate"]].copy()
    for path, frame in (
        (classified_events_path(), classifications),
        (selector_audit_path(), audit),
        (selected_path(), selected),
        (rejected_path(), rejected),
    ):
        _write_parquet_exclusive(path, frame)

    selected_years = pd.to_datetime(selected["signal_date"]).dt.year.value_counts()
    family_counts: Counter[str] = Counter()
    for value in rejected["v29r1_open_risk_families"]:
        family_counts.update(item for item in str(value).split("|") if item)
    development = {
        "parent_signals": len(audit),
        "selected_signals": len(selected),
        "rejected_signals": len(rejected),
        "selected_by_signal_year": {
            str(year): int(selected_years.get(year, 0)) for year in DEVELOPMENT_YEARS
        },
        "rejected_recent_open_event": int(
            rejected["v29r1_rejection_reason"].eq("RECENT_HIGH_PRECISION_OPEN_ISSUER_RISK").sum()
        ),
        "rejected_incomplete_coverage": int(
            rejected["v29r1_rejection_reason"].str.startswith("INCOMPLETE_COVERAGE:").sum()
        ),
        "rejected_risk_family_signal_counts": dict(sorted(family_counts.items())),
        "classified_event_identity_sha256": _identity_sha256(
            (
                classifications["announcement_key"].astype(str)
                + "|"
                + classifications["action"].astype(str)
                + "|"
                + classifications["risk_family"].astype("string").fillna("")
            ).tolist()
        ),
        "selected_gap_identity_sha256": _identity_sha256(selected["gap_id"].tolist()),
        "rejected_gap_identity_sha256": _identity_sha256(rejected["gap_id"].tolist()),
        "classified_events_sha256": sha256(classified_events_path()),
        "title_route_selection_sha256": sha256(title_route_selection_path()),
        "selector_audit_sha256": sha256(selector_audit_path()),
        "selected_entries_sha256": sha256(selected_path()),
        "rejected_entries_sha256": sha256(rejected_path()),
    }
    _require(
        development["selected_signals"] + development["rejected_signals"]
        == development["parent_signals"],
        "V29R1 selector identity conservation failed",
    )
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_IDENTITY_AND_EXECUTION_BINDING_BEFORE_OUTCOME_OPEN",
        "runner_sha256": sha256(Path(__file__).resolve()),
        "protocol_hashes": protocol_hashes,
        "cy036r1_identity": {key: value for key, value in asset.items() if key != "covered_symbols"},
        "rule": {
            "window": "signal_time-120 calendar days <= causal_available_at <= signal_time",
            "action": "OPEN only",
            "families": list(classifier.RISK_FAMILIES),
            "close_treatment": "CLOSE_NEVER_SHORTENS_120_CALENDAR_DAY_COOLDOWN",
            "missing_or_unproven_coverage": "REJECT",
        },
        "temporal_scope": temporal_scope,
        "development": development,
        "stage_b_binding_frozen_before_outcome_open": {
            "parent_source_hashes": protocol_hashes[
                "parent_source_hashes_streamed_without_parsing"
            ],
            "software_hashes": protocol_hashes["software_hashes"],
            "constant_contract": _read_json_object(
                PREREGISTRATION, "V29R1 preregistration"
            )["stage_b_identity_and_replay_freeze"]["constant_contract"],
            "join_fields": _read_json_object(
                PREREGISTRATION, "V29R1 preregistration"
            )["stage_b_identity_and_replay_freeze"]["join_contract"]["exact_fields"],
        },
        "development_outcomes_opened": "NO_BYTES_HASHED_ONLY",
        "parent_development_result_parsed": False,
        "post_2021_query_partition_collected_or_opened": False,
        "causal_available_from_2022_titles_read": False,
        "causal_available_from_2022_titles_classified_or_selector_used": False,
    }
    _write_json_exclusive(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    _require(STAGE_A_FREEZE.is_file(), "V29R1 Stage-A freeze is missing")
    freeze = _read_json_object(STAGE_A_FREEZE, "V29R1 Stage-A freeze")
    _require(
        freeze.get("experiment") == EXPERIMENT
        and freeze.get("stage") == "DEVELOPMENT_IDENTITY_AND_EXECUTION_BINDING_BEFORE_OUTCOME_OPEN"
        and freeze.get("development_outcomes_opened") == "NO_BYTES_HASHED_ONLY"
        and freeze.get("parent_development_result_parsed") is False
        and freeze.get("post_2021_query_partition_collected_or_opened") is False
        and freeze.get("causal_available_from_2022_titles_read") is False,
        "V29R1 Stage-A freeze status drifted",
    )
    current_asset = verify_registered_cy036r1()
    _, current_protocol = _verify_protocol()
    current_asset = {key: value for key, value in current_asset.items() if key != "covered_symbols"}
    drift: dict[str, Any] = {}
    for key, expected, actual in (
        ("runner_sha256", freeze.get("runner_sha256"), sha256(Path(__file__).resolve())),
        ("protocol_hashes", freeze.get("protocol_hashes"), current_protocol),
        ("cy036r1_identity", freeze.get("cy036r1_identity"), current_asset),
    ):
        if expected != actual:
            drift[key] = [expected, actual]
    development = freeze.get("development", {})
    paths = {
        "classified_events_sha256": classified_events_path(),
        "title_route_selection_sha256": title_route_selection_path(),
        "selector_audit_sha256": selector_audit_path(),
        "selected_entries_sha256": selected_path(),
        "rejected_entries_sha256": rejected_path(),
    }
    for key, path in paths.items():
        actual = sha256(path) if path.is_file() else None
        if development.get(key) != actual:
            drift[key] = [development.get(key), actual]
    _require(not drift, f"V29R1 Stage-A drift: {drift}")

    audit = pd.read_parquet(selector_audit_path())
    selected = pd.read_parquet(selected_path())
    rejected = pd.read_parquet(rejected_path())
    _require(
        len(audit) == development.get("parent_signals")
        and len(selected) == development.get("selected_signals")
        and len(rejected) == development.get("rejected_signals"),
        "V29R1 frozen selector counts drifted",
    )
    accepted_ids = set(
        audit.loc[audit["v29r1_issuer_integrity_cooldown_gate"], "gap_id"].astype(str)
    )
    rejected_ids = set(
        audit.loc[~audit["v29r1_issuer_integrity_cooldown_gate"], "gap_id"].astype(str)
    )
    _require(
        accepted_ids == set(selected["gap_id"].astype(str))
        and rejected_ids == set(rejected["gap_id"].astype(str))
        and not accepted_ids.intersection(rejected_ids),
        "V29R1 frozen accepted/rejected partition drifted",
    )
    _require(
        pd.to_datetime(audit["signal_date"]).dt.year.isin(DEVELOPMENT_YEARS).all(),
        "V29R1 Stage-A audit contains a post-2021 signal",
    )
    return {
        "verified": True,
        "runner_sha256": sha256(Path(__file__).resolve()),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "selected_entries_sha256": sha256(selected_path()),
        "selected_signals": len(selected),
        "parent_source_hashes": current_protocol[
            "parent_source_hashes_streamed_without_parsing"
        ],
    }


def _canonical_scalar(value: object, field: str) -> tuple[str, object]:
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    _require(not missing, f"exact join field {field} is missing")
    if field in _STRING_IDENTITY_FIELDS:
        _require(isinstance(value, str) and value != "", f"exact string field {field} is invalid")
        return ("string", value)
    if field in _DATE_IDENTITY_FIELDS or field in _TIMESTAMP_IDENTITY_FIELDS:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise V29R1Error(f"exact timestamp field {field} is invalid") from exc
        _require(not pd.isna(timestamp), f"exact timestamp field {field} is missing")
        if field in _DATE_IDENTITY_FIELDS:
            _require(timestamp == timestamp.normalize(), f"exact date field {field} has time")
        return ("timestamp_iso8601", timestamp.isoformat())
    if field in _INTEGER_IDENTITY_FIELDS:
        _require(
            isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)),
            f"exact integer field {field} has a nonnumeric source type",
        )
        numeric = float(value)
        _require(
            math.isfinite(numeric) and numeric.is_integer(),
            f"exact integer field {field} is not integral",
        )
        return ("int64", int(numeric))
    if field in _FLOAT_IDENTITY_FIELDS:
        _require(
            isinstance(value, numbers.Real) and not isinstance(value, (bool, np.bool_)),
            f"exact floating field {field} has a nonnumeric source type",
        )
        numeric = float(value)
        _require(math.isfinite(numeric), f"exact floating field {field} is nonfinite")
        return ("float64_hex", numeric.hex())
    if field in _BOOLEAN_IDENTITY_FIELDS:
        _require(isinstance(value, (bool, np.bool_)), f"exact boolean field {field} is invalid")
        return ("bool", bool(value))
    raise V29R1Error(f"no declared exact canonicalization for {field}")


def verify_exact_selected_outcome_join(
    selected: pd.DataFrame,
    outcomes: pd.DataFrame,
    *,
    exact_fields: Sequence[str],
) -> dict[str, Any]:
    """Prove exact one-to-one executable identity before portfolio replay."""

    required = {"gap_id", *exact_fields}
    for label, frame in (("selected", selected), ("outcomes", outcomes)):
        missing = sorted(required.difference(frame.columns))
        _require(not missing, f"{label} exact join columns are missing: {missing}")
        _require(not frame["gap_id"].duplicated().any(), f"{label} has duplicate gap_id")
        _require(frame["gap_id"].notna().all(), f"{label} has a missing gap_id")
        _require(
            frame["gap_id"].map(
                lambda value: isinstance(value, str) and bool(value)
            ).all(),
            f"{label} gap_id must be a nonempty exact string",
        )
    executable = selected.loc[selected["entry_status"].eq("EXECUTABLE_ENTRY")].copy()
    executable_ids = set(executable["gap_id"].astype(str))
    joined = outcomes.loc[outcomes["gap_id"].astype(str).isin(executable_ids)].copy()
    joined_ids = set(joined["gap_id"].astype(str))
    _require(
        len(executable) == len(joined)
        and len(executable_ids) == len(executable)
        and joined_ids == executable_ids,
        "selected executable/outcome one-to-one identity conservation failed",
    )
    selected_by_id = {str(row["gap_id"]): row for _, row in executable.iterrows()}
    outcome_by_id = {str(row["gap_id"]): row for _, row in joined.iterrows()}
    for gap_id in sorted(executable_ids):
        for field in exact_fields:
            left = _canonical_scalar(selected_by_id[gap_id][field], field)
            right = _canonical_scalar(outcome_by_id[gap_id][field], field)
            _require(left == right, f"exact selected/outcome mismatch at {gap_id}.{field}")
    _require(
        executable["entry_at_or_before_signal"].eq(False).all()
        and executable["entry_after_signal_period_boundary"].eq(False).all()
        and executable["buy_at_or_above_up_limit"].eq(False).all(),
        "selected executable entry violates T+1/period/up-limit invariants",
    )
    return {
        "selected_executable_rows": len(executable),
        "joined_outcome_rows": len(joined),
        "identity_sets_equal": True,
        "exact_fields_equal": True,
        "canonicalization": {
            "string": "nonempty exact Unicode code-point sequence",
            "date_or_timestamp": "exact pandas Timestamp ISO-8601; no rounding or timezone conversion",
            "integer": "finite integral numeric source value then exact int64 value",
            "float": "finite real source type then exact IEEE-754 float64 hexadecimal value",
            "boolean": "strict bool/np.bool_ value",
        },
        "gap_identity_sha256": _identity_sha256(sorted(executable_ids)),
    }


def _verify_parent_result_binding(parent_result: Mapping[str, Any], expected: Mapping[str, str]) -> None:
    opened = parent_result.get("lane", {}).get("source_hashes_opened_in_stage_b")
    _require(opened == expected, "V28R2 development result records different outcome sources")
    _require(
        parent_result.get("development_outcomes_opened") == "YES"
        and parent_result.get("post_2021_entries_or_outcomes_opened") == "NO",
        "V28R2 parent development/later-period boundary drifted",
    )


@contextmanager
def _development_runtime() -> Iterator[None]:
    replay = v28.replay
    old_root = replay.EXT_ROOT
    old_selected = replay.selected_entries_path
    old_lane = replay.lane_root
    try:
        replay.EXT_ROOT = EXT_ROOT
        replay.selected_entries_path = lambda label: selected_path()
        replay.lane_root = lambda label: lane_root()
        yield
    finally:
        replay.EXT_ROOT = old_root
        replay.selected_entries_path = old_selected
        replay.lane_root = old_lane


def run_stage_b() -> dict[str, Any]:
    """Open only bound parent development outcomes after complete Stage-A proof."""

    _require_pristine_stage_b_outputs()
    verification = verify_stage_a()
    prereg = _read_json_object(PREREGISTRATION, "V29R1 preregistration")
    expected_sources = prereg["stage_b_identity_and_replay_freeze"]["actual_parent_source_hashes"]
    source_paths = _parent_source_paths()
    _require(
        {name: sha256(path) for name, path in source_paths.items()} == expected_sources,
        "parent outcome sources drifted immediately before opening",
    )
    parent_result = _read_json_object(v28r2.DEVELOPMENT_RESULT, "V28R2 development result")
    _verify_parent_result_binding(parent_result, expected_sources)
    selected = pd.read_parquet(selected_path())
    source_outcomes = pd.read_parquet(source_paths["outcomes"])
    join_audit = verify_exact_selected_outcome_join(
        selected,
        source_outcomes,
        exact_fields=prereg["stage_b_identity_and_replay_freeze"]["join_contract"]["exact_fields"],
    )
    joined_dates = pd.to_datetime(
        source_outcomes.loc[
            source_outcomes["gap_id"].astype(str).isin(set(selected["gap_id"].astype(str))),
            "signal_date",
        ],
        errors="raise",
    )
    _require(joined_dates.dt.year.isin(DEVELOPMENT_YEARS).all(), "joined outcomes include a post-2021 signal")
    _require(
        {name: sha256(path) for name, path in source_paths.items()} == expected_sources,
        "parent outcome sources drifted during exact join verification",
    )
    with _development_runtime():
        lane = v28.replay.run_lane("DEVELOPMENT", DEVELOPMENT_YEARS)
    _require(
        {name: sha256(path) for name, path in source_paths.items()} == expected_sources,
        "parent outcome sources drifted during unchanged replay",
    )
    accepted_path = lane_root() / "portfolio_accepted.parquet"
    accepted = pd.read_parquet(accepted_path)
    _require(
        not accepted.empty
        and pd.to_datetime(accepted["signal_date"]).dt.year.isin(DEVELOPMENT_YEARS).all(),
        "V29R1 replay returned empty or out-of-period accepted trades",
    )
    summary = v28._accepted_summary(accepted, DEVELOPMENT_YEARS)
    checks = v28.development_checks(summary)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_EXACT_BOUND_OUTCOME_REPLAY",
        "stage_a_verification": verification,
        "parent_result_source_binding": expected_sources,
        "exact_join_audit": join_audit,
        "lane": lane,
        "accepted_summary": summary,
        "goal_checks": checks,
        "selector_passed": passed,
        "verdict": (
            "DEVELOPMENT_PASS_LATER_DATA_REMAINS_LOCKED"
            if passed
            else "DEVELOPMENT_FAILED_LATER_DATA_REMAINS_LOCKED"
        ),
        "development_outcomes_opened": "YES_EXACT_HASH_BOUND_2018_2021_SIGNALS_ONLY",
        "post_2021_signal_selection_classification_or_validation_opened": "NO",
        "later_period_authorization_created": "NO",
        "hashes": {
            "portfolio_accepted": sha256(accepted_path),
            "filtered_outcomes": sha256(lane_root() / "outcomes.parquet"),
            "parent_outcomes": sha256(source_paths["outcomes"]),
            "parent_outcome_daily": sha256(source_paths["outcome_daily"]),
        },
    }
    _write_json_exclusive(DEVELOPMENT_RESULT, result)
    _render_report(result)
    return result


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _render_report(result: Mapping[str, Any]) -> None:
    summary = result["accepted_summary"]
    freeze = _read_json_object(STAGE_A_FREEZE, "V29R1 Stage-A freeze")["development"]
    rows: list[str] = []
    for year in DEVELOPMENT_YEARS:
        item = summary["yearly_by_signal_year"][str(year)]
        hold = item["average_holding_sessions"]
        rows.append(
            f"|{year}|{item['trades']}|{_pct(item['mean_net'])}|"
            f"{_pct(item['median_net'])}|{_pct(item['win'])}|{_pct(item['severe10'])}|"
            f"{'—' if hold is None else f'{hold:.2f}'}|"
        )
    text = "\n".join(
        [
            f"# {EXPERIMENT}",
            "",
            "V29R1 retains every V28R2 price, volume and execution rule. It vetoes only a signal with a high-precision official-title OPEN issuer-risk disclosure in the inclusive prior 120 calendar days; a CLOSE never shortens the cooldown.",
            "",
            "SSE knowledge time is max(original ADDDATE, SSEDATE plus one calendar day at 00:00 Asia/Shanghai). SZSE keeps the collector's conservative publishTime rule. This is a PIT-B current-enumeration reconstruction, not PIT-A or live evidence.",
            "",
            "## Development 2018-2021",
            "",
            f"Stage A retained {freeze['selected_signals']} of {freeze['parent_signals']} V28R2 signals and rejected {freeze['rejected_signals']} before outcome content was opened.",
            "",
            f"Exact K80 accepted {summary['accepted_trades']} ({summary['accepted_trades_per_year']:.2f}/year), mean {_pct(summary['mean_net'])}, median {_pct(summary['median_net'])}, win {_pct(summary['win'])}, severe10 {_pct(summary['severe10'])}, average hold {summary['average_holding_sessions']:.2f} sessions.",
            "",
            "|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|",
            "|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            f"Development passed: **{result['selector_passed']}**.",
            "",
            "The sealed <=2021 query-membership composite was verified. Rows with repaired causal availability from 2022 were not title-classified or selector-used. No later-period signal, selection, classification, validation, or authorization was opened.",
            "",
        ]
    )
    _write_text_exclusive(REPORT, text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stage-a", "stage-b", "all"), default="all")
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    if args.mode in ("stage-a", "all"):
        payload["stage_a"] = run_stage_a()
    if args.mode in ("stage-b", "all"):
        payload["stage_b"] = run_stage_b()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
