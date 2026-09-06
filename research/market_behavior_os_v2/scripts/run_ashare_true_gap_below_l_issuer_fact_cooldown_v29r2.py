#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the preregistered V29R2 issuer-fact cooling-period veto.

V29R2 keeps the V28R2 signal, execution, A67 target, H20 horizon, 40-bp
round-trip cost and Main/ChiNext K80-per-sleeve portfolio unchanged.  Its only
change from the retired V29R1 selector is the frozen V2 official-title
taxonomy: a governance document that merely discusses a risk topic is not an
issuer-level adverse fact.

Stage A validates the registered title-free CY-036-R2 route, freezes the exact
candidate-window keys before projecting any nested title, classifies only the
causally pre-2022 rows, and binds the already-preregistered selector identity.
The parent outcome files are streamed only as bytes for SHA-256.  Stage B first
revalidates the complete Stage-A freeze, then opens the exact bound 2018-2021
outcomes and delegates the unchanged replay.  There is no post-2021 mode.
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

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_activation_asset_v29r2 as cy036r2,
)
from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_risk_composite_asset_v29r1 as cy036r1,
)
from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v2 as classifier,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_integrity_cooldown_v29r1 as v29r1,
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
    "ISSUER-FACT-COOLDOWN-V29R2"
)
ASSET_ID = "CY-036-R2"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-DEVELOPMENT-2018-2021-V1"
)
AUTHORIZATION_PURPOSE = "ASHARE_ISSUER_FACT_V29R2_DEVELOPMENT_SELECTOR_REPLAY"

EXPECTED_PREREGISTRATION_SHA256 = (
    "076566c5cd85158997d39e4690c090e98110e85597d55ebf7d5b4fa0e63a5a3a"
)
EXPECTED_CLASSIFIER_SHA256 = (
    "127f62e551d4344ede9d41970ea7a6634f5f4b192fe2829a78eed8c72cf2da9d"
)
EXPECTED_SEMANTIC_BLOCKER_SHA256 = (
    "df1654f143cf534c4101cd12671092e3dc61d475b439ff7ee75daca83cc5bd45"
)
PREREGISTRATION = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
SEMANTIC_BLOCKER = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29R1_semantic_blocker.json"
)
REGISTRY = ROOT / "configs/data_asset_registry.json"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_issuer_fact_cooldown_v29r2"
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
EXPECTED_CANDIDATE_TITLES = 13_338
EXPECTED_CLASSIFIED_OPEN_ROWS = 20
EXPECTED_SELECTED_SIGNALS = 362
EXPECTED_REJECTED_SIGNALS = 8
EXPECTED_SELECTED_BY_YEAR = {"2018": 305, "2019": 22, "2020": 10, "2021": 25}
EXPECTED_OPEN_BY_FAMILY = {
    "CONTROLLER_FUND_MISAPPROPRIATION": 1,
    "ILLEGAL_GUARANTEE": 2,
    "ISSUER_BANK_ACCOUNT_FREEZE": 2,
    "REGULATORY_INVESTIGATION": 12,
    "RISK_WARNING_OR_DELISTING": 3,
}
EXPECTED_CLASSIFIED_ROW_IDENTITY_SHA256 = (
    "8164f6392c541bdbbe5467d0f4ea9d9a81332f2e579c470911a57b9f51530cb2"
)
EXPECTED_SELECTED_GAP_IDENTITY_SHA256 = (
    "fc0dac8e29829cc653bb7bb0b41fe66e336638f2ee510bb420baf124608245d5"
)
EXPECTED_REJECTED_GAP_IDENTITY_SHA256 = (
    "b80cfadeb47fd9c86981263270e44f97d2ab937b57dda74ae0b528467814b492"
)
EXPECTED_REJECTED_GAP_IDS = (
    "000519.SZ|2018-01-31",
    "002181.SZ|2018-10-11",
    "002535.SZ|2019-11-22",
    "300278.SZ|2021-01-26",
    "600397.SH|2018-01-31",
    "600568.SH|2019-08-02",
    "600749.SH|2018-02-01",
    "603111.SH|2018-08-20",
)

_REQUIRED_PARENT_COLUMNS = v29r1._REQUIRED_PARENT_COLUMNS
_OUTCOME_ONLY_COLUMNS = v29r1._OUTCOME_ONLY_COLUMNS
_REQUIRED_ANNOUNCEMENT_COLUMNS = v29r1._REQUIRED_ANNOUNCEMENT_COLUMNS
_TITLE_SOURCE_COLUMNS = v29r1._TITLE_SOURCE_COLUMNS
_STRING_IDENTITY_FIELDS = v29r1._STRING_IDENTITY_FIELDS
_DATE_IDENTITY_FIELDS = v29r1._DATE_IDENTITY_FIELDS
_TIMESTAMP_IDENTITY_FIELDS = v29r1._TIMESTAMP_IDENTITY_FIELDS
_INTEGER_IDENTITY_FIELDS = v29r1._INTEGER_IDENTITY_FIELDS
_FLOAT_IDENTITY_FIELDS = v29r1._FLOAT_IDENTITY_FIELDS
_BOOLEAN_IDENTITY_FIELDS = v29r1._BOOLEAN_IDENTITY_FIELDS
EXACT_JOIN_FIELDS = (
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
)
_AUTH_REQUIRED_ARTIFACT_ROLES = {
    "activation_audit",
    "asset_builder",
    "announcement_route_index",
    "issuer_fact_classifier",
    "parent_development_result_identity",
    "parent_outcome_daily",
    "parent_outcomes",
    "parent_stage_a",
    "retired_v29r1_semantic_blocker",
}
_SCOPED_CY036R2_IDENTITY_FIELDS = (
    "activation_audit_sha256",
    "asset_manifest_sha256",
    "asset_root",
    "base_component_root",
    "base_nested_files_verified",
    "bounded_authorization_sha256",
    "registered_asset_entry_sha256",
    "route_index_sha256",
    "sse_nested_files_verified",
    "title_route_contract",
    "upstream_asset_root",
)


class V29R2Error(RuntimeError):
    """Fail closed on protocol, source, time, identity, or execution drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V29R2Error(message)


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


def _identity_sha256(values: Sequence[object]) -> str:
    return _value_sha256(sorted(str(value) for value in values))


def _scoped_cy036r2_identity(runtime: Mapping[str, Any]) -> dict[str, Any]:
    """Return only the target asset/auth identity, excluding registry container bytes.

    The normalized target asset and authorization hashes already bind every field in
    those records, including their bounded artifact fingerprints.  Hashing the whole
    registry JSON as part of Stage A would additionally couple this experiment to
    unrelated assets, authorizations, ordering and registry timestamps.
    """

    missing = sorted(set(_SCOPED_CY036R2_IDENTITY_FIELDS).difference(runtime))
    _require(not missing, f"CY-036-R2 scoped identity fields are missing: {missing}")
    return {field: runtime[field] for field in _SCOPED_CY036R2_IDENTITY_FIELDS}


def _verify_frozen_cy036r2_identity(
    frozen: object, runtime: Mapping[str, Any]
) -> dict[str, Any]:
    current = _scoped_cy036r2_identity(runtime)
    _require(
        isinstance(frozen, dict) and frozen == current,
        "V29R2 frozen target asset/authorization identity drifted",
    )
    return current


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V29R2Error(f"invalid {label}: {path}") from exc
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
        raise V29R2Error(f"refusing to overwrite frozen artifact: {path}") from exc


def _write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o444)
    except FileExistsError as exc:
        raise V29R2Error(f"refusing to overwrite report: {path}") from exc


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
        raise V29R2Error(f"refusing to overwrite parquet: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def classified_events_path() -> Path:
    return EXT_ROOT / "development/issuer_fact_classified_events.parquet"


def title_route_selection_path() -> Path:
    return EXT_ROOT / "development/issuer_fact_title_route_selection.parquet"


def selector_audit_path() -> Path:
    return EXT_ROOT / "development/issuer_fact_selector_audit.parquet"


def selected_path() -> Path:
    return EXT_ROOT / "development/issuer_fact_selected_entries.parquet"


def rejected_path() -> Path:
    return EXT_ROOT / "development/issuer_fact_rejected_entries.parquet"


def lane_root() -> Path:
    return EXT_ROOT / "development/issuer_fact"


def _normalize_symbol(value: object) -> str:
    try:
        return v29r1._normalize_symbol(value)
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc


def _local_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        return v29r1._local_timestamp(value, label)
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc


def derive_causal_available_at(metadata: pd.DataFrame) -> pd.DataFrame:
    """Reuse the unchanged, audited V29R1 causal-time derivation."""

    try:
        return v29r1.derive_causal_available_at(metadata)
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc


def select_candidate_window_title_routes(
    timed: pd.DataFrame,
    entries: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reuse the unchanged causal-window route selection before title access."""

    try:
        return v29r1.select_candidate_window_title_routes(timed, entries)
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc


def attach_authoritative_titles(
    route_index: pd.DataFrame,
    sse_announcements: pd.DataFrame,
    base_announcements: pd.DataFrame,
    *,
    additional_exact_fields: Sequence[str] = (),
) -> pd.DataFrame:
    """Reuse the unchanged one-to-one nested-title lineage proof."""

    try:
        return v29r1.attach_authoritative_titles(
            route_index,
            sse_announcements,
            base_announcements,
            additional_exact_fields=additional_exact_fields,
        )
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc


def _read_authoritative_title_rows(
    source_path: Path,
    eligible_routes: pd.DataFrame,
    *,
    component_role: str,
    exchange: str,
    additional_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Project only the already-frozen route keys from a nested source."""

    try:
        return v29r1._read_authoritative_title_rows(
            source_path,
            eligible_routes,
            component_role=component_role,
            exchange=exchange,
            additional_columns=additional_columns,
        )
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc


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
        raise V29R2Error(f"title classification failed closed: {exc}") from exc
    _require(
        classified["available_at"].lt(cutoff).all(),
        "classifier output contains a causal time from 2022 or later",
    )
    return classified, dict(scope)


def classify_development_titles(
    metadata: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Pure helper for bounded tests and already-attached pre-2022 metadata."""

    timed = derive_causal_available_at(metadata)
    try:
        eligible, scope = v29r1._development_route_scope(timed)
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc
    return _classify_eligible_titles(eligible, scope)


def apply_issuer_fact_cooldown(
    entries: pd.DataFrame,
    classifications: pd.DataFrame,
    *,
    covered_symbols: Sequence[str],
) -> pd.DataFrame:
    """Apply the inclusive V2 OPEN-only veto; CLOSE never erases cooldown."""

    missing_entries = sorted(
        {"gap_id", "symbol", "signal_date", "signal_time"} - set(entries)
    )
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
    work["signal_date"] = pd.to_datetime(
        work["signal_date"], errors="raise"
    ).dt.normalize()
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
        coverage_start = _local_timestamp(
            f"{exchange_start} 00:00:00", "coverage start"
        )
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

        symbol_events = open_by_symbol.get(
            symbol, pd.DataFrame(columns=open_events.columns)
        )
        matched = symbol_events.loc[
            symbol_events["available_at"].ge(window_start)
            & symbol_events["available_at"].le(signal_at)
        ].sort_values(
            ["available_at", "announcement_key", "risk_family"], kind="mergesort"
        )
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
            else "RECENT_HIGH_PRECISION_OPEN_ISSUER_FACT"
            if event_payload
            else ""
        )
        records.append(
            {
                "gap_id": entry["gap_id"],
                "v29r2_signal_time_local": signal_at,
                "v29r2_window_start_at": window_start,
                "v29r2_window_end_at": signal_at,
                "v29r2_exchange_query_coverage_start": coverage_start,
                "v29r2_coverage_complete": complete,
                "v29r2_coverage_failure_reasons": "|".join(failures),
                "v29r2_open_transition_count": len(event_payload),
                "v29r2_open_announcement_count": len(keys),
                "v29r2_open_announcement_keys": "|".join(keys),
                "v29r2_open_risk_families": "|".join(families),
                "v29r2_open_events_json": _canonical_json(event_payload),
                "v29r2_latest_open_causal_available_at": (
                    pd.NaT if matched.empty else matched["available_at"].max()
                ),
                "v29r2_issuer_fact_cooldown_gate": gate,
                "v29r2_rejection_reason": reason,
                "v29r2_feature_uses_post_signal_information": False,
            }
        )
    result = work.merge(
        pd.DataFrame.from_records(records), on="gap_id", validate="one_to_one"
    )
    _require(
        result.loc[
            result["v29r2_issuer_fact_cooldown_gate"], "v29r2_coverage_complete"
        ].all(),
        "selector admitted an incompletely covered signal",
    )
    return result


def _software_paths() -> dict[str, Path]:
    return {
        "execution_repair_runner_sha256": Path(v28.replay.repair.__file__).resolve(),
        "lane_replay_runner_sha256": Path(v28.replay.__file__).resolve(),
        "portfolio_runner_sha256": Path(v28.replay.repair.v1.__file__).resolve(),
    }


def _parent_source_paths() -> dict[str, Path]:
    paths = v28.replay.source_paths("DEVELOPMENT")
    return {"outcomes": paths["outcomes"], "outcome_daily": paths["outcome_daily"]}


def _selector_contract(prereg: Mapping[str, Any]) -> dict[str, Any]:
    value = prereg.get("selector_identity_frozen_before_v29r2_outcome_replay")
    _require(isinstance(value, dict), "V29R2 frozen selector identity is missing")
    expected = {
        "candidate_announcement_titles": EXPECTED_CANDIDATE_TITLES,
        "candidate_signals": EXPECTED_PARENT_SIGNALS,
        "classified_open_by_family": EXPECTED_OPEN_BY_FAMILY,
        "classified_open_rows": EXPECTED_CLASSIFIED_OPEN_ROWS,
        "classified_row_identity_sha256": EXPECTED_CLASSIFIED_ROW_IDENTITY_SHA256,
        "rejected_gap_ids": list(EXPECTED_REJECTED_GAP_IDS),
        "rejected_signals": EXPECTED_REJECTED_SIGNALS,
        "rejected_gap_identity_sha256": EXPECTED_REJECTED_GAP_IDENTITY_SHA256,
        "selected_by_signal_year": EXPECTED_SELECTED_BY_YEAR,
        "selected_gap_identity_sha256": EXPECTED_SELECTED_GAP_IDENTITY_SHA256,
        "selected_signals": EXPECTED_SELECTED_SIGNALS,
    }
    _require(value == expected, "V29R2 preregistered selector identity drifted")
    return dict(value)


def _verify_protocol() -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind protocol and byte identities without parsing outcome content."""

    _require(
        sha256(PREREGISTRATION) == EXPECTED_PREREGISTRATION_SHA256,
        "V29R2 preregistration SHA-256 drifted",
    )
    _require(
        sha256(Path(classifier.__file__).resolve()) == EXPECTED_CLASSIFIER_SHA256,
        "V29R2 classifier SHA-256 drifted",
    )
    _require(
        sha256(SEMANTIC_BLOCKER) == EXPECTED_SEMANTIC_BLOCKER_SHA256,
        "retired V29R1 semantic blocker drifted",
    )
    prereg = _read_json_object(PREREGISTRATION, "V29R2 preregistration")
    blocker = _read_json_object(SEMANTIC_BLOCKER, "retired V29R1 semantic blocker")
    _require(
        prereg.get("experiment") == EXPERIMENT
        and prereg.get("status")
        == "SEMANTIC_REPAIR_AND_SELECTOR_IDENTITY_FROZEN_BEFORE_V29R2_OUTCOME_REPLAY"
        and prereg.get("parent") == v28r2.EXPERIMENT,
        "V29R2 protocol identity or status drifted",
    )
    _require(
        blocker.get("status") == "BLOCKED"
        and blocker.get("governance", {}).get("validation_consumed")
        == "V29R1_VALIDATION_NOT_CONSUMED"
        and blocker.get("governance", {}).get("development_result_status")
        == "RETIRED_NOT_VALIDATION_ELIGIBLE",
        "retired V29R1 blocker semantics drifted",
    )
    correction = prereg.get("retired_parent_correction", {})
    _require(
        correction.get("blocked_experiment") == v29r1.EXPERIMENT
        and correction.get("semantic_blocker_sha256")
        == EXPECTED_SEMANTIC_BLOCKER_SHA256
        and correction.get("v29r1_validation_consumed") is False,
        "V29R2 does not retain the V29R1 semantic blocker",
    )
    development = prereg.get("development", {})
    _require(
        development.get("signal_years") == list(DEVELOPMENT_YEARS)
        and development.get("candidate_title_population_already_consumed") is True
        and development.get("outcomes_already_consumed_by_parent_and_retired_v29r1")
        is True,
        "V29R2 development quarantine drifted",
    )
    success = development.get("success_contract", {})
    _require(
        success
        == {
            "accepted_trades_per_year_strictly_greater_than": 50,
            "average_holding_sessions_strictly_less_than": 15,
            "each_signal_year_mean_net_positive": True,
            "mean_net_at_least": 0.04,
        },
        "V29R2 development success contract drifted",
    )
    knowledge = prereg.get("knowledge_time", {})
    _require(
        knowledge.get("sse")
        == "max(original ADDDATE, SSEDATE + 1 calendar day 00:00 Asia/Shanghai)"
        and knowledge.get("szse")
        == "source-second publishTime when present; otherwise publishTime date + 1 calendar day 00:00 Asia/Shanghai"
        and knowledge.get("unknown_missing_or_unprovable") == "FAIL_CLOSED"
        and knowledge.get("window")
        == "signal_time - 120 calendar days <= causal_available_at <= signal_time",
        "V29R2 knowledge-time contract drifted",
    )
    semantic = prereg.get("semantic_rule", {})
    _require(
        semantic.get("rule")
        == "Admit only when zero qualifying OPEN issuer-fact titles fall inside the inclusive prior 120-calendar-day window."
        and semantic.get("close_treatment")
        == "An explicit CLOSE never shortens the 120-calendar-day cooling period."
        and semantic.get("missing_or_unproven_coverage") == "REJECT"
        and semantic.get("threshold_search")
        == "NONE; 120 calendar days is carried unchanged from V29R1 so this experiment isolates the semantic repair."
        and set(semantic.get("families", {})) == set(classifier.RISK_FAMILIES),
        "V29R2 issuer-fact selector contract drifted",
    )
    later = prereg.get("later_period_protocol", {})
    _require(
        later.get("no_rule_change_after_open") is True
        and "2022_2024" in later
        and "2025_plus" in later,
        "V29R2 later-data lock drifted",
    )
    _selector_contract(prereg)

    parent_paths = {
        "runner_sha256": Path(v28r2.__file__).resolve(),
        "development_stage_a_sha256": v28r2.STAGE_A_FREEZE,
        "development_result_sha256": v28r2.DEVELOPMENT_RESULT,
    }
    current_parent = {key: sha256(path) for key, path in parent_paths.items()}
    _require(
        prereg.get("parent_identity") == current_parent,
        "V29R2 parent selector identity drifted",
    )
    current_software = {key: sha256(path) for key, path in _software_paths().items()}
    declared_software = prereg.get("software_frozen_before_v29r2_outcome_replay", {})
    _require(
        declared_software.get("classifier_path")
        == "research/market_behavior_os_v2/scripts/classify_exchange_issuer_risk_events_v2.py"
        and declared_software.get("classifier_sha256") == EXPECTED_CLASSIFIER_SHA256
        and {
            key: declared_software.get(key)
            for key in current_software
        }
        == current_software,
        "V29R2 replay or classifier software drifted",
    )
    constant = prereg.get("stage_b_constant_contract", {})
    _require(
        constant.get("portfolio_k_per_sleeve") == v28.replay.PORTFOLIO_K == 80
        and constant.get("target_fraction")
        == v28.replay.TARGET_FRACTION
        == v28.replay.repair.v1.TARGET_FRACTION
        == 0.67
        and constant.get("maximum_holding_sessions")
        == v28.replay.TIME_STOP
        == v28.replay.repair.v1.TIME_STOP
        == 20
        and constant.get("side_cost_entry") == v28.replay.repair.v1.COST == 0.002
        and constant.get("side_cost_exit") == v28.replay.repair.v1.COST == 0.002
        and constant.get("round_trip_cost") == 0.004
        and constant.get("failure_stop") == "NONE",
        "V29R2 K80/A67/H20/cost/stop contract drifted",
    )
    source_paths = _parent_source_paths()
    current_sources = {name: sha256(path) for name, path in source_paths.items()}
    _require(
        prereg.get("stage_b_source_hashes") == current_sources,
        "V29R2 parent outcome source hash drifted",
    )
    hashes = {
        "preregistration_sha256": sha256(PREREGISTRATION),
        "classifier_sha256": sha256(Path(classifier.__file__).resolve()),
        "retired_v29r1_semantic_blocker_sha256": sha256(SEMANTIC_BLOCKER),
        "parent_identity": current_parent,
        "software_hashes": current_software,
        "parent_source_hashes_streamed_without_parsing": current_sources,
    }
    return prereg, hashes


def _fingerprints_by_role(
    authorization: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    values = authorization.get("bound_artifacts")
    _require(isinstance(values, list), "bounded authorization has no artifact list")
    result: dict[str, Mapping[str, Any]] = {}
    for value in values:
        _require(isinstance(value, dict), "bounded authorization artifact is not an object")
        role = value.get("role")
        _require(isinstance(role, str) and role, "bounded artifact role is missing")
        _require(role not in result, f"duplicate bounded artifact role: {role}")
        result[role] = value
    return result


def _require_fingerprint(
    value: object, path: Path, expected_hash: str, label: str
) -> None:
    _require(isinstance(value, dict), f"{label} fingerprint is missing")
    _require(
        value.get("path") == str(path) and value.get("sha256") == expected_hash,
        f"{label} fingerprint drifted",
    )


def _validate_title_route_contract(manifest: Mapping[str, Any]) -> dict[str, Any]:
    contract = manifest.get("title_route_contract")
    _require(isinstance(contract, dict), "CY-036-R2 title_route_contract is missing")
    _require(
        contract.get("build_time_title_handling")
        == {
            "nested_sealer_reparsed_and_validated_title_metadata_from_raw_pages": True,
            "wrapper_projected_or_copied_title_column": False,
            "wrapper_classified_title_column": False,
        },
        "CY-036-R2 build-time title handling drifted",
    )
    _require(
        contract.get("required_access_order")
        == [
            (
                "Validate CY-036-R2 and filter announcement_route_index.parquet using "
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
        "CY-036-R2 required title-access order drifted",
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
        "CY-036-R2 title routing or cardinality contract drifted",
    )
    exact_fields = [
        "raw_record_sha256",
        "symbol",
        "exchange",
        "source_publication_field",
        "source_publication_value",
        "source_query_date_field",
        "source_query_date",
    ]
    _require(
        contract.get("post_join_exact_fields") == exact_fields,
        "CY-036-R2 post-title-join exact fields drifted",
    )
    activation = contract.get("activation_wrapper", {})
    _require(
        activation.get("upstream_asset_id") == cy036r2.UPSTREAM_ASSET_ID
        and activation.get("route_index_byte_identical_to_upstream") is True
        and activation.get("title_column_projected_or_opened_by_builder") is False
        and activation.get("title_classification_performed_by_builder") is False,
        "CY-036-R2 activation-wrapper boundary drifted",
    )
    routing = manifest.get("source_routing")
    roles = contract.get("roles")
    _require(
        isinstance(routing, dict)
        and isinstance(roles, dict)
        and set(routing) == set(roles) == cy036r2._EXPECTED_COMPONENT_ROLES,
        "CY-036-R2 authoritative title role set drifted",
    )
    role_contract = {
        "SSE_FULL_HISTORY_AUTHORITATIVE": (
            "SSE",
            "sse_full_history_nested_announcements",
        ),
        "BASE_SZSE_AUTHORITATIVE": ("SZSE", "base_nested_announcements"),
    }
    for role, (exchange, inventory_role) in role_contract.items():
        route = routing[role]
        item = roles[role]
        _require(
            isinstance(route, dict)
            and isinstance(item, dict)
            and item.get("nested_announcements_path")
            == str((Path(str(route.get("root"))) / "announcements.parquet").resolve(strict=True))
            and item.get("expected_exchange") == exchange
            and item.get("inventory_role") == inventory_role
            and item.get("snapshot_id") == route.get("snapshot_id"),
            f"CY-036-R2 nested title role binding drifted: {role}",
        )
    content = manifest.get("content", {})
    _require(
        content.get("route_index_includes_title") is False
        and content.get("classification_included") is False
        and content.get("classifier_executed_during_build") is False
        and content.get("outcomes_included_or_opened") is False
        and content.get("route_index_byte_identical_to_v29r1") is True
        and content.get("route_index_columns") == cy036r2._EXPECTED_ROUTE_COLUMNS,
        "CY-036-R2 route-index content boundary drifted",
    )
    _require(
        manifest.get("pit", {}).get("knowledge_time") == "causal_available_at only",
        "CY-036-R2 manifest does not bind repaired causal knowledge time",
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
        "CY-036-R2 registry state is not bounded PIT-B research input",
    )
    lineage = asset.get("lineage", {})
    _require(
        lineage.get("record_available_at") is True
        and lineage.get("record_snapshot_id") is True
        and lineage.get("immutable_manifest") is True
        and lineage.get("bounded_authorization_id") == AUTHORIZATION_ID,
        "CY-036-R2 lineage or authorization binding drifted",
    )
    _require(
        lineage.get("manifest_path") == str(manifest_path)
        and lineage.get("manifest_sha256") == sha256(manifest_path),
        "CY-036-R2 registered manifest fingerprint drifted",
    )
    coverage = asset.get("coverage", {})
    _require(
        coverage.get("sse_query_start") == SSE_QUERY_START
        and coverage.get("szse_query_start") == SZSE_QUERY_START
        and coverage.get("query_end") == QUERY_END
        and coverage.get("signal_start") == "2018-01-01"
        and coverage.get("signal_end") == QUERY_END,
        "CY-036-R2 registered routed coverage drifted",
    )
    _require(
        authorization.get("authorization_id") == AUTHORIZATION_ID
        and authorization.get("purpose") == AUTHORIZATION_PURPOSE
        and authorization.get("asset_id") == ASSET_ID
        and authorization.get("dependency_asset_id") == cy036r2.UPSTREAM_ASSET_ID
        and authorization.get("dependency_status") == "RESEARCH_CONDITIONAL"
        and authorization.get("record_level_available_at_available") is True
        and authorization.get("current_survivor_fallback_allowed") is False
        and authorization.get("event_classification_authorized") is True
        and authorization.get("development_outcome_join_authorized") is True
        and authorization.get("portfolio_replay_authorized") is True
        and authorization.get("post_2021_announcement_classification_authorized")
        is False
        and authorization.get("post_2021_signal_or_selector_authorized") is False,
        "V29R2 bounded authorization flags drifted",
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
        "V29R2 bounded dependency is missing or has status drift",
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
        "V29R2 bounded authorization scope drifted",
    )
    manifest_hash = sha256(manifest_path)
    _require_fingerprint(
        authorization.get("bound_manifest"), manifest_path, manifest_hash, "bound manifest"
    )
    _require_fingerprint(
        authorization.get("bound_strategy"),
        PREREGISTRATION,
        EXPECTED_PREREGISTRATION_SHA256,
        "bound strategy",
    )
    protocol = authorization.get("bound_protocol")
    _require_fingerprint(
        protocol,
        PREREGISTRATION,
        EXPECTED_PREREGISTRATION_SHA256,
        "bound protocol",
    )
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
        "activation_audit": root / cy036r2.ACTIVATION_AUDIT_NAME,
        "asset_builder": Path(cy036r2.__file__).resolve(),
        "announcement_route_index": root / cy036r2.ROUTE_INDEX_NAME,
        "issuer_fact_classifier": Path(classifier.__file__).resolve(),
        "parent_development_result_identity": v28r2.DEVELOPMENT_RESULT,
        "parent_outcome_daily": _parent_source_paths()["outcome_daily"],
        "parent_outcomes": _parent_source_paths()["outcomes"],
        "parent_stage_a": v28r2.STAGE_A_FREEZE,
        "retired_v29r1_semantic_blocker": SEMANTIC_BLOCKER,
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
        == EXPECTED_PREREGISTRATION_SHA256
        and manifest.get("protocol_binding", {}).get("classifier_sha256")
        == EXPECTED_CLASSIFIER_SHA256,
        "sealed CY-036-R2 manifest protocol or non-authorizing state drifted",
    )


def verify_registered_cy036r2() -> dict[str, Any]:
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
    _require(
        len(authorizations) == 1,
        f"{AUTHORIZATION_ID} must resolve to exactly one authorization",
    )
    asset = assets[0]
    authorization = authorizations[0]
    root = Path(str(asset.get("location", "")))
    _require(
        root.is_absolute() and root.is_dir() and not root.is_symlink(),
        "CY-036-R2 location is missing or unsafe",
    )
    manifest_path = root / cy036r2.ASSET_MANIFEST_NAME
    manifest = _read_json_object(manifest_path, "CY-036-R2 asset manifest")
    _validate_registry_documents(
        registry,
        asset,
        authorization,
        manifest,
        manifest_path=manifest_path,
    )
    title_route_contract = _validate_title_route_contract(manifest)
    upstream_root = Path(
        str(manifest.get("upstream_activation", {}).get("root", ""))
    )
    base_root = Path(
        str(
            manifest.get("source_routing", {})
            .get("BASE_SZSE_AUTHORITATIVE", {})
            .get("root", "")
        )
    )
    _require(
        upstream_root.is_absolute() and base_root.is_absolute(),
        "CY-036-R2 upstream or base source root is missing",
    )
    try:
        sealed = cy036r2.validate_asset(root, upstream_root, base_root)
    except Exception as exc:
        raise V29R2Error(f"CY-036-R2 full recursive validation failed: {exc}") from exc
    _require(
        sealed.get("status") == "PASS"
        and sealed.get("asset_id") == ASSET_ID
        and sealed.get("asset_manifest_sha256") == sha256(manifest_path),
        "CY-036-R2 recursive validation identity drifted",
    )
    base = cy036r1._base_identity(base_root, full_seal=False)
    covered_symbols = list(base["symbols"])
    _require(
        len(covered_symbols) == cy036r1.EXPECTED_BASE_SYMBOLS,
        "CY-036-R2 covered universe size drifted",
    )
    return {
        "asset_root": str(root),
        "upstream_asset_root": str(upstream_root),
        "base_component_root": str(base_root),
        "asset_manifest_sha256": sha256(manifest_path),
        "registered_asset_entry_sha256": _value_sha256(asset),
        "bounded_authorization_sha256": _value_sha256(authorization),
        "data_asset_registry_sha256": sha256(REGISTRY),
        "covered_symbols": covered_symbols,
        "route_index_sha256": sha256(root / cy036r2.ROUTE_INDEX_NAME),
        "activation_audit_sha256": sha256(root / cy036r2.ACTIVATION_AUDIT_NAME),
        "title_route_contract": title_route_contract,
        "base_nested_files_verified": sealed.get("base_nested_files_verified"),
        "sse_nested_files_verified": sealed.get("sse_nested_files_verified"),
    }


def _load_parent_entries() -> pd.DataFrame:
    """Read only the frozen V28R2 signal/execution identity, never outcomes."""

    try:
        entries = v29r1._load_parent_entries()
    except v29r1.V29R1Error as exc:
        raise V29R2Error(str(exc)) from exc
    _require(len(entries) == EXPECTED_PARENT_SIGNALS, "V28R2 parent count drifted")
    yearly = pd.to_datetime(entries["signal_date"], errors="raise").dt.year.value_counts()
    _require(
        {str(year): int(yearly.get(year, 0)) for year in DEVELOPMENT_YEARS}
        == EXPECTED_PARENT_BY_YEAR,
        "V28R2 parent yearly identity drifted",
    )
    return entries


def _load_classifications(
    asset: Mapping[str, Any],
    entries: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    route_path = Path(str(asset["asset_root"])) / cy036r2.ROUTE_INDEX_NAME
    _require(
        route_path.is_file() and not route_path.is_symlink(),
        "CY-036-R2 route index is missing",
    )
    try:
        route_index = pd.read_parquet(route_path)
    except Exception as exc:
        raise V29R2Error("unable to read sealed CY-036-R2 route index") from exc
    timed = derive_causal_available_at(route_index)
    eligible_routes, scope = select_candidate_window_title_routes(timed, entries)
    _require(
        len(eligible_routes) == EXPECTED_CANDIDATE_TITLES,
        "V29R2 candidate-window title count differs from preregistration",
    )
    title_contract = asset.get("title_route_contract")
    _require(isinstance(title_contract, dict), "validated title-route contract is missing")
    route_selection_fields = title_contract["route_index_selection_fields"]
    frozen_route_fields = [*route_selection_fields, "causal_available_at"]
    _require(
        set(frozen_route_fields).issubset(eligible_routes.columns),
        "eligible title route cannot freeze contracted lineage fields",
    )
    route_freeze = eligible_routes[frozen_route_fields].sort_values(
        ["causal_available_at", "component_role", "snapshot_id", "announcement_key"],
        kind="mergesort",
    ).reset_index(drop=True)
    _write_parquet_exclusive(title_route_selection_path(), route_freeze)
    scope["title_route_selection_fields"] = frozen_route_fields
    scope["title_route_selection_sha256"] = sha256(title_route_selection_path())
    scope["candidate_announcement_titles_preregistered"] = EXPECTED_CANDIDATE_TITLES

    exact_fields = title_contract["post_join_exact_fields"]
    roles = title_contract["roles"]
    sse_announcements = _read_authoritative_title_rows(
        Path(str(roles["SSE_FULL_HISTORY_AUTHORITATIVE"]["nested_announcements_path"])),
        eligible_routes,
        component_role="SSE_FULL_HISTORY_AUTHORITATIVE",
        exchange="SSE",
        additional_columns=exact_fields,
    )
    base_announcements = _read_authoritative_title_rows(
        Path(str(roles["BASE_SZSE_AUTHORITATIVE"]["nested_announcements_path"])),
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


def _selector_identity_values(
    classifications: pd.DataFrame,
    selected: pd.DataFrame,
    rejected: pd.DataFrame,
) -> dict[str, Any]:
    open_rows = classifications.loc[
        classifications["action"].eq(classifier.ACTION_OPEN)
    ]
    family_counts = Counter(open_rows["risk_family"].astype(str).tolist())
    selected_years = pd.to_datetime(
        selected["signal_date"], errors="raise"
    ).dt.year.value_counts()
    classified_identities = (
        classifications["announcement_key"].astype(str)
        + "|"
        + classifications["action"].astype(str)
        + "|"
        + classifications["risk_family"].astype("string").fillna("")
    ).tolist()
    return {
        "candidate_announcement_titles": int(
            classifications["announcement_key"].astype(str).nunique()
        ),
        "candidate_signals": int(len(selected) + len(rejected)),
        "classified_open_by_family": dict(sorted(family_counts.items())),
        "classified_open_rows": len(open_rows),
        "classified_row_identity_sha256": _identity_sha256(classified_identities),
        "rejected_gap_ids": sorted(rejected["gap_id"].astype(str).tolist()),
        "rejected_signals": len(rejected),
        "rejected_gap_identity_sha256": _identity_sha256(rejected["gap_id"].tolist()),
        "selected_by_signal_year": {
            str(year): int(selected_years.get(year, 0)) for year in DEVELOPMENT_YEARS
        },
        "selected_gap_identity_sha256": _identity_sha256(selected["gap_id"].tolist()),
        "selected_signals": len(selected),
    }


def _verify_preregistered_selector_identity(
    prereg: Mapping[str, Any],
    classifications: pd.DataFrame,
    selected: pd.DataFrame,
    rejected: pd.DataFrame,
) -> dict[str, Any]:
    actual = _selector_identity_values(classifications, selected, rejected)
    expected = _selector_contract(prereg)
    _require(
        actual == expected,
        f"V29R2 selector differs from frozen preregistered identity: expected={expected}, actual={actual}",
    )
    return actual


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
    _require(not existing, f"V29R2 Stage-A outputs already exist: {existing}")


def _require_pristine_stage_b_outputs() -> None:
    existing = [
        path for path in (DEVELOPMENT_RESULT, REPORT, lane_root()) if path.exists()
    ]
    _require(not existing, f"V29R2 Stage-B outputs already exist: {existing}")


def run_stage_a() -> dict[str, Any]:
    """Freeze the exact preregistered selector; outcomes stay byte-hash-only."""

    _require_pristine_stage_a_outputs()
    asset = verify_registered_cy036r2()
    prereg, protocol_hashes = _verify_protocol()
    entries = _load_parent_entries()
    classifications, temporal_scope = _load_classifications(asset, entries)
    audit = apply_issuer_fact_cooldown(
        entries,
        classifications,
        covered_symbols=asset["covered_symbols"],
    ).sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    selected = audit.loc[audit["v29r2_issuer_fact_cooldown_gate"]].copy()
    rejected = audit.loc[~audit["v29r2_issuer_fact_cooldown_gate"]].copy()
    selector_identity = _verify_preregistered_selector_identity(
        prereg, classifications, selected, rejected
    )

    for path, frame in (
        (classified_events_path(), classifications),
        (selector_audit_path(), audit),
        (selected_path(), selected),
        (rejected_path(), rejected),
    ):
        _write_parquet_exclusive(path, frame)

    rejected_family_counts: Counter[str] = Counter()
    for value in rejected["v29r2_open_risk_families"]:
        rejected_family_counts.update(item for item in str(value).split("|") if item)
    development = {
        **selector_identity,
        "parent_signals": len(audit),
        "rejected_recent_open_event": int(
            rejected["v29r2_rejection_reason"]
            .eq("RECENT_HIGH_PRECISION_OPEN_ISSUER_FACT")
            .sum()
        ),
        "rejected_incomplete_coverage": int(
            rejected["v29r2_rejection_reason"]
            .str.startswith("INCOMPLETE_COVERAGE:")
            .sum()
        ),
        "rejected_risk_family_signal_counts": dict(
            sorted(rejected_family_counts.items())
        ),
        "classified_events_sha256": sha256(classified_events_path()),
        "title_route_selection_sha256": sha256(title_route_selection_path()),
        "selector_audit_sha256": sha256(selector_audit_path()),
        "selected_entries_sha256": sha256(selected_path()),
        "rejected_entries_sha256": sha256(rejected_path()),
    }
    _require(
        development["selected_signals"] + development["rejected_signals"]
        == development["parent_signals"]
        == EXPECTED_PARENT_SIGNALS,
        "V29R2 selector identity conservation failed",
    )
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_PREREGISTERED_IDENTITY_AND_EXECUTION_BINDING_BEFORE_OUTCOME_OPEN",
        "runner_sha256": sha256(Path(__file__).resolve()),
        "protocol_hashes": protocol_hashes,
        "cy036r2_scoped_identity": _scoped_cy036r2_identity(asset),
        "rule": {
            "window": "signal_time-120 calendar days <= causal_available_at <= signal_time",
            "action": "OPEN issuer-fact title only",
            "families": list(classifier.RISK_FAMILIES),
            "classification_version": classifier.CLASSIFICATION_VERSION,
            "document_role_gate": "GOVERNANCE_DISCUSSION_WITHOUT_EXPLICIT_ADVERSE_FACT_IS_IGNORE",
            "close_treatment": "CLOSE_NEVER_SHORTENS_120_CALENDAR_DAY_COOLDOWN",
            "missing_or_unproven_coverage": "REJECT",
        },
        "temporal_scope": temporal_scope,
        "development": development,
        "preregistered_selector_identity": _selector_contract(prereg),
        "stage_b_binding_frozen_before_outcome_open": {
            "parent_source_hashes": protocol_hashes[
                "parent_source_hashes_streamed_without_parsing"
            ],
            "software_hashes": protocol_hashes["software_hashes"],
            "constant_contract": prereg["stage_b_constant_contract"],
            "join_fields": list(EXACT_JOIN_FIELDS),
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
    _require(STAGE_A_FREEZE.is_file(), "V29R2 Stage-A freeze is missing")
    freeze = _read_json_object(STAGE_A_FREEZE, "V29R2 Stage-A freeze")
    _require(
        freeze.get("experiment") == EXPERIMENT
        and freeze.get("stage")
        == "DEVELOPMENT_PREREGISTERED_IDENTITY_AND_EXECUTION_BINDING_BEFORE_OUTCOME_OPEN"
        and freeze.get("development_outcomes_opened") == "NO_BYTES_HASHED_ONLY"
        and freeze.get("parent_development_result_parsed") is False
        and freeze.get("post_2021_query_partition_collected_or_opened") is False
        and freeze.get("causal_available_from_2022_titles_read") is False
        and freeze.get("causal_available_from_2022_titles_classified_or_selector_used")
        is False,
        "V29R2 Stage-A freeze status drifted",
    )
    current_asset = verify_registered_cy036r2()
    prereg, current_protocol = _verify_protocol()
    _verify_frozen_cy036r2_identity(
        freeze.get("cy036r2_scoped_identity"), current_asset
    )
    drift: dict[str, Any] = {}
    for key, expected, actual in (
        ("runner_sha256", freeze.get("runner_sha256"), sha256(Path(__file__).resolve())),
        ("protocol_hashes", freeze.get("protocol_hashes"), current_protocol),
        (
            "preregistered_selector_identity",
            freeze.get("preregistered_selector_identity"),
            _selector_contract(prereg),
        ),
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
    _require(not drift, f"V29R2 Stage-A drift: {drift}")

    classifications = pd.read_parquet(classified_events_path())
    routes = pd.read_parquet(title_route_selection_path())
    audit = pd.read_parquet(selector_audit_path())
    selected = pd.read_parquet(selected_path())
    rejected = pd.read_parquet(rejected_path())
    _require(
        len(routes) == EXPECTED_CANDIDATE_TITLES
        and len(audit) == development.get("parent_signals")
        and len(selected) == development.get("selected_signals")
        and len(rejected) == development.get("rejected_signals"),
        "V29R2 frozen route or selector counts drifted",
    )
    _verify_preregistered_selector_identity(
        prereg, classifications, selected, rejected
    )
    accepted_ids = set(
        audit.loc[audit["v29r2_issuer_fact_cooldown_gate"], "gap_id"].astype(str)
    )
    rejected_ids = set(
        audit.loc[~audit["v29r2_issuer_fact_cooldown_gate"], "gap_id"].astype(str)
    )
    _require(
        accepted_ids == set(selected["gap_id"].astype(str))
        and rejected_ids == set(rejected["gap_id"].astype(str))
        and not accepted_ids.intersection(rejected_ids),
        "V29R2 frozen accepted/rejected partition drifted",
    )
    _require(
        pd.to_datetime(audit["signal_date"], errors="raise")
        .dt.year.isin(DEVELOPMENT_YEARS)
        .all()
        and pd.to_datetime(classifications["available_at"], errors="raise")
        .lt(pd.Timestamp("2022-01-01", tz="Asia/Shanghai"))
        .all(),
        "V29R2 Stage-A artifacts contain a post-2021 signal or causal title",
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
        _require(
            isinstance(value, str) and value != "",
            f"exact string field {field} is invalid",
        )
        return ("string", value)
    if field in _DATE_IDENTITY_FIELDS or field in _TIMESTAMP_IDENTITY_FIELDS:
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError) as exc:
            raise V29R2Error(f"exact timestamp field {field} is invalid") from exc
        _require(not pd.isna(timestamp), f"exact timestamp field {field} is missing")
        if field in _DATE_IDENTITY_FIELDS:
            _require(
                timestamp == timestamp.normalize(),
                f"exact date field {field} has time",
            )
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
        _require(
            isinstance(value, (bool, np.bool_)),
            f"exact boolean field {field} is invalid",
        )
        return ("bool", bool(value))
    raise V29R2Error(f"no declared exact canonicalization for {field}")


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
            _require(
                left == right,
                f"exact selected/outcome mismatch at {gap_id}.{field}",
            )
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


def _verify_parent_result_binding(
    parent_result: Mapping[str, Any], expected: Mapping[str, str]
) -> None:
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
    prereg = _read_json_object(PREREGISTRATION, "V29R2 preregistration")
    expected_sources = prereg["stage_b_source_hashes"]
    source_paths = _parent_source_paths()
    _require(
        {name: sha256(path) for name, path in source_paths.items()} == expected_sources,
        "parent outcome sources drifted immediately before opening",
    )
    parent_result = _read_json_object(
        v28r2.DEVELOPMENT_RESULT, "V28R2 development result"
    )
    _verify_parent_result_binding(parent_result, expected_sources)
    selected = pd.read_parquet(selected_path())
    source_outcomes = pd.read_parquet(source_paths["outcomes"])
    join_audit = verify_exact_selected_outcome_join(
        selected,
        source_outcomes,
        exact_fields=EXACT_JOIN_FIELDS,
    )
    joined_dates = pd.to_datetime(
        source_outcomes.loc[
            source_outcomes["gap_id"].astype(str).isin(
                set(selected["gap_id"].astype(str))
            ),
            "signal_date",
        ],
        errors="raise",
    )
    _require(
        joined_dates.dt.year.isin(DEVELOPMENT_YEARS).all(),
        "joined outcomes include a post-2021 signal",
    )
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
        and pd.to_datetime(accepted["signal_date"], errors="raise")
        .dt.year.isin(DEVELOPMENT_YEARS)
        .all(),
        "V29R2 replay returned empty or out-of-period accepted trades",
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
    freeze = _read_json_object(STAGE_A_FREEZE, "V29R2 Stage-A freeze")["development"]
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
            "V29R2 retains every V28R2 price, volume and execution rule. It vetoes only a signal with an explicit official-title issuer-level adverse fact in the inclusive prior 120 calendar days; governance discussion without an adverse fact is ignored, and CLOSE never shortens the cooldown.",
            "",
            "SSE knowledge time is max(original ADDDATE, SSEDATE plus one calendar day at 00:00 Asia/Shanghai). SZSE keeps the conservative publishTime rule. This remains a PIT-B current-enumeration reconstruction, not PIT-A or live evidence.",
            "",
            "## Development 2018-2021",
            "",
            f"Stage A reproduced the preregistered identity exactly: {freeze['candidate_announcement_titles']} candidate titles, {freeze['classified_open_rows']} OPEN rows, {freeze['selected_signals']} selected and {freeze['rejected_signals']} rejected before outcome content was opened.",
            "",
            f"Exact K80 accepted {summary['accepted_trades']} ({summary['accepted_trades_per_year']:.2f}/year), mean {_pct(summary['mean_net'])}, median {_pct(summary['median_net'])}, win {_pct(summary['win'])}, severe10 {_pct(summary['severe10'])}, average hold {summary['average_holding_sessions']:.2f} sessions.",
            "",
            "|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|",
            "|---:|---:|---:|---:|---:|---:|---:|",
            *rows,
            "",
            f"Development passed: **{result['selector_passed']}**.",
            "",
            "Rows causally available from 2022 were not title-projected, classified or selector-used. No later-period signal, validation outcome or authorization was opened by this development runner.",
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
