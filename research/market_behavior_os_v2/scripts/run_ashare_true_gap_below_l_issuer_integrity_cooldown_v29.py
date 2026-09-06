#!/usr/bin/env python3
"""Run the preregistered V29 issuer-integrity cooling-period veto.

V29 changes exactly one thing relative to the frozen V28R2 development
identity: a signal is admitted only when a fully covered 120-calendar-day
window contains no high-precision ``OPEN`` issuer-risk title event whose
official ``available_at`` is no later than the completed signal decision.

The runner intentionally has no post-2021 mode.  Stage A validates the bounded
registered CY-036 wrapper, classifies title metadata, and freezes selected and
rejected identities before any outcome table is opened.  Development then
revalidates that freeze and delegates the unchanged T+1/A67/H20/K80 replay to
the existing exact parent replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_risk_asset_v1 as cy036,
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
    "ISSUER-INTEGRITY-COOLDOWN-V29"
)
ASSET_ID = "CY-036"
EXPECTED_PREREGISTRATION_SHA256 = (
    "663f5c8bd953983ac041f2279f6d43ea408182b15613b46d903661690d1f8c42"
)
PREREGISTRATION = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
REGISTRY = ROOT / "configs/data_asset_registry.json"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_issuer_integrity_cooldown_v29"
)
STAGE_A_FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_development_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
BLOCKER = OS_ROOT / f"artifacts/{EXPERIMENT}_coverage_blocker.json"
EXPECTED_BLOCKER_SHA256 = (
    "42c3848ac9244e4ea7288f71594e639a3889b0a19e4036ee9955b82c55b91a7d"
)

DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
COOLING_CALENDAR_DAYS = 120
CAPTURE_START = "2017-10-01"
CAPTURE_END = "2021-12-31"
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
    "snapshot_id",
    "announcement_key",
    "announcement_id",
    "symbol",
    "exchange",
    "title",
    "published_at",
    "available_at",
    "precision",
    "hard_valid",
    "revision_history_complete",
    "strict_pit_eligible",
    "query_year",
    "source_query_date",
}


class V29Error(RuntimeError):
    """Fail closed on protocol, registry, coverage, identity, or PIT drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V29Error(message)


def sha256(path: Path) -> str:
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
        raise V29Error(f"invalid {label}: {path}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
                + "\n"
            )
    except FileExistsError as exc:
        raise V29Error(f"refusing to overwrite frozen artifact: {path}") from exc


def selected_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_selected_entries.parquet"


def selector_audit_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_selector_audit.parquet"


def rejected_path() -> Path:
    return EXT_ROOT / "development/issuer_integrity_rejected_entries.parquet"


def lane_root() -> Path:
    return EXT_ROOT / "development/issuer_integrity"


def _normalized_local_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        return classifier._exact_local_timestamp(value, label)
    except classifier.RiskEventInputError as exc:
        raise V29Error(str(exc)) from exc


def _normalize_symbol(value: object) -> str:
    try:
        return collector.normalize_symbol(value)
    except collector.CaptureError as exc:
        raise V29Error(f"invalid signal symbol: {value!r}") from exc


def _verify_preregistration_and_parent() -> dict[str, Any]:
    """Verify frozen parent files without invoking V28R2's live registry chain."""

    _require(
        sha256(PREREGISTRATION) == EXPECTED_PREREGISTRATION_SHA256,
        "V29 preregistration SHA-256 drifted",
    )
    prereg = _read_json_object(PREREGISTRATION, "V29 preregistration")
    _require(prereg.get("experiment") == EXPERIMENT, "V29 experiment drifted")
    _require(
        prereg.get("status")
        == "SEMANTIC_RULE_FROZEN_BEFORE_DEVELOPMENT_EVENT_OUTCOME_JOIN",
        "V29 preregistration is not a pre-outcome semantic freeze",
    )
    _require(prereg.get("parent") == v28r2.EXPERIMENT, "V29 parent drifted")

    condition = prereg.get("only_new_condition")
    _require(isinstance(condition, dict), "V29 condition declaration is missing")
    _require(
        condition.get("window")
        == "signal_time - 120 calendar days <= event available_at <= signal_time",
        "V29 inclusive available_at window drifted",
    )
    _require(
        condition.get("families") == list(classifier.RISK_FAMILIES),
        "V29 risk-family set or order drifted",
    )
    _require(
        condition.get("close_treatment")
        == (
            "An explicit CLOSE does not erase the 120-day cooling period; the gate "
            "measures recent severe disclosure, not only current legal state."
        ),
        "V29 CLOSE treatment drifted",
    )
    _require(
        condition.get("missing_policy")
        == (
            "Reject unless official exchange metadata coverage, every required page, "
            "identity, hash, classification version, and available_at relation are "
            "proven for the whole window."
        ),
        "V29 missing-data policy drifted",
    )

    classifier_contract = prereg.get("classifier")
    _require(isinstance(classifier_contract, dict), "V29 classifier binding is missing")
    classifier_path = Path(classifier.__file__).resolve()
    _require(
        classifier_contract.get("version") == classifier.CLASSIFICATION_VERSION,
        "V29 classifier version drifted",
    )
    _require(
        classifier_contract.get("runner_sha256") == sha256(classifier_path),
        "V29 classifier runner SHA-256 drifted",
    )
    _require(
        classifier_contract.get("knowledge_time") == "available_at only",
        "V29 knowledge-time rule drifted",
    )

    development = prereg.get("development")
    _require(isinstance(development, dict), "V29 development declaration is missing")
    _require(
        development.get("signal_years") == list(DEVELOPMENT_YEARS),
        "V29 development years drifted",
    )
    _require(
        development.get("announcement_capture_start") == CAPTURE_START
        and development.get("announcement_capture_end") == CAPTURE_END,
        "V29 development announcement coverage drifted",
    )

    parent_files = {
        "parent_runner_sha256": Path(v28r2.__file__).resolve(),
        "parent_development_stage_a_sha256": v28r2.STAGE_A_FREEZE,
        # Intentionally streamed as bytes only.  Stage A must never parse this outcome result.
        "parent_development_result_sha256": v28r2.DEVELOPMENT_RESULT,
    }
    for prereg_key, path in parent_files.items():
        _require(path.is_file(), f"missing frozen V28R2 parent file: {path}")
        _require(prereg.get(prereg_key) == sha256(path), f"{prereg_key} drifted")

    parent_stage = _read_json_object(v28r2.STAGE_A_FREEZE, "V28R2 Stage-A freeze")
    _require(parent_stage.get("experiment") == v28r2.EXPERIMENT, "V28R2 Stage-A drifted")
    _require(
        parent_stage.get("development_outcomes_opened") == "NO_IN_THIS_STAGE"
        and parent_stage.get("post_2021_entries_or_outcomes_opened") == "NO_IN_THIS_STAGE",
        "V28R2 parent is not a pre-outcome development identity",
    )
    parent_development = parent_stage.get("development")
    _require(isinstance(parent_development, dict), "V28R2 development identity is missing")
    parent_selected = v28r2.selected_path()
    _require(parent_selected.is_file(), "V28R2 selected identity is missing")
    _require(
        parent_development.get("selected_entries_sha256") == sha256(parent_selected),
        "V28R2 selected parquet differs from its pre-outcome Stage-A freeze",
    )
    _require(
        parent_development.get("selected_signals") == EXPECTED_PARENT_SIGNALS
        and parent_development.get("selected_by_signal_year") == EXPECTED_PARENT_BY_YEAR,
        "V28R2 frozen development population drifted",
    )
    return {
        "preregistration_sha256": sha256(PREREGISTRATION),
        "classifier_runner_sha256": sha256(classifier_path),
        "parent_runner_sha256": sha256(Path(v28r2.__file__).resolve()),
        "parent_stage_a_sha256": sha256(v28r2.STAGE_A_FREEZE),
        "parent_selected_entries_sha256": sha256(parent_selected),
        "parent_development_result_sha256": sha256(v28r2.DEVELOPMENT_RESULT),
    }


def _registry_asset_entry() -> tuple[dict[str, Any], dict[str, Any]]:
    registry = _read_json_object(REGISTRY, "central data-asset registry")
    matches = [
        item
        for item in registry.get("assets", [])
        if isinstance(item, dict) and item.get("asset_id") == ASSET_ID
    ]
    _require(len(matches) == 1, f"{ASSET_ID} must resolve to exactly one registry entry")
    return registry, matches[0]


def verify_registered_cy036() -> dict[str, Any]:
    """Validate the exact central binding and rerun the complete nested asset seal."""

    registry, registered = _registry_asset_entry()
    _require(
        registry.get("global_gate", {}).get("free_causal_research_ready") is True
        and registry.get("global_gate", {}).get("backtest_authorized") is True,
        "central research/backtest gate is not open",
    )
    _require(
        registered.get("status") == "RESEARCH_CONDITIONAL"
        and registered.get("physical_state") == "MATERIALIZED"
        and registered.get("pit_grade") == "B",
        f"{ASSET_ID} registry state is not bounded PIT-B research input",
    )
    root = Path(str(registered.get("location", "")))
    _require(root.is_absolute() and root.is_dir(), f"{ASSET_ID} location is missing")
    lineage = registered.get("lineage")
    _require(isinstance(lineage, dict), f"{ASSET_ID} lineage is missing")
    _require(
        lineage.get("record_available_at") is True
        and lineage.get("record_snapshot_id") is True
        and lineage.get("immutable_manifest") is True,
        f"{ASSET_ID} record timing/snapshot/immutability lineage is incomplete",
    )

    manifest_path = Path(str(lineage.get("manifest_path", "")))
    source_manifest_path = Path(str(lineage.get("source_manifest_path", "")))
    _require(
        manifest_path == root / cy036.ASSET_MANIFEST_NAME and manifest_path.is_file(),
        f"{ASSET_ID} wrapper manifest path is not exact",
    )
    _require(
        lineage.get("manifest_sha256") == sha256(manifest_path),
        f"{ASSET_ID} wrapper manifest hash mismatch",
    )
    _require(
        source_manifest_path == root / cy036.SOURCE_CAPTURE_NAME / "asset_manifest.json"
        and source_manifest_path.is_file(),
        f"{ASSET_ID} source manifest path is not exact",
    )
    _require(
        lineage.get("source_manifest_sha256") == sha256(source_manifest_path),
        f"{ASSET_ID} source manifest hash mismatch",
    )

    coverage = registered.get("coverage")
    _require(isinstance(coverage, dict), f"{ASSET_ID} coverage is missing")
    _require(
        coverage.get("start") == CAPTURE_START and coverage.get("end") == CAPTURE_END,
        f"{ASSET_ID} coverage differs from the preregistered interval",
    )
    allowed = "\n".join(str(value) for value in registered.get("allowed_uses", []))
    blocked = "\n".join(str(value) for value in registered.get("blocked_uses", []))
    _require(
        EXPERIMENT in allowed and "2018-2021" in allowed and "development" in allowed.lower(),
        f"{ASSET_ID} does not authorize this exact development use",
    )
    _require(
        "validation" in blocked.lower() and "live" in blocked.lower(),
        f"{ASSET_ID} blocked-use boundary is incomplete",
    )

    try:
        sealed = cy036.validate_asset(root)
    except Exception as exc:
        raise V29Error(f"{ASSET_ID} full wrapper validation failed: {exc}") from exc
    _require(
        sealed.get("status") == "PASS" and sealed.get("asset_id") == ASSET_ID,
        f"{ASSET_ID} wrapper validation did not pass",
    )
    manifest = _read_json_object(manifest_path, f"{ASSET_ID} wrapper manifest")
    _require(
        manifest.get("asset_id") == ASSET_ID
        and manifest.get("coverage") == {"start": CAPTURE_START, "end": CAPTURE_END},
        f"{ASSET_ID} wrapper identity or coverage drifted",
    )
    _require(
        manifest.get("pit", {}).get("grade") == "B"
        and manifest.get("pit", {}).get("revision_history_incomplete") is True
        and manifest.get("content", {}).get("title_only") is True,
        f"{ASSET_ID} PIT-B/title-only limitations drifted",
    )
    _require(
        manifest.get("content", {}).get("classifier_version")
        == classifier.CLASSIFICATION_VERSION
        and manifest.get("protocol_binding", {}).get("experiment") == EXPERIMENT
        and manifest.get("protocol_binding", {}).get("preregistration_sha256")
        == EXPECTED_PREREGISTRATION_SHA256,
        f"{ASSET_ID} classifier/protocol binding drifted",
    )
    return {
        "asset_root": str(root),
        "registered_asset_entry_sha256": _value_sha256(registered),
        "wrapper_manifest_sha256": sha256(manifest_path),
        "source_manifest_sha256": sha256(source_manifest_path),
        "wrapper_validator_sha256": sha256(Path(cy036.__file__).resolve()),
        "source_snapshot_id": str(manifest.get("content", {}).get("source_snapshot_id", "")),
        "nested_files_verified": sealed.get("nested_files_verified"),
    }


def _load_parent_entries() -> pd.DataFrame:
    entries = pd.read_parquet(v28r2.selected_path())
    missing = sorted(_REQUIRED_PARENT_COLUMNS.difference(entries.columns))
    _require(not missing, f"V28R2 selected identity is missing columns: {missing}")
    outcome_columns = sorted(_OUTCOME_ONLY_COLUMNS.intersection(entries.columns))
    _require(
        not outcome_columns,
        f"Stage A parent contains outcome-only columns: {outcome_columns}",
    )
    _require(len(entries) == EXPECTED_PARENT_SIGNALS, "V28R2 selected row count drifted")
    _require(not entries["gap_id"].duplicated().any(), "V28R2 duplicate gap identity")
    _require(
        entries["v28r2_orderly_amount_gate"].eq(True).all()
        and entries["v28r2_feature_uses_post_signal_information"].eq(False).all(),
        "V28R2 parent gate or causal feature invariant failed",
    )
    signal_dates = pd.to_datetime(entries["signal_date"], errors="raise")
    _require(
        signal_dates.dt.year.isin(DEVELOPMENT_YEARS).all()
        and signal_dates.max() <= pd.Timestamp("2021-12-31"),
        "V28R2 parent contains a post-2021 signal",
    )
    signal_times = pd.to_datetime(entries["signal_time"], errors="raise")
    entry_times = pd.to_datetime(entries["entry_time"], errors="raise")
    _require(
        entry_times.gt(signal_times).all()
        and entries["entry_at_or_before_signal"].eq(False).all()
        and entries["entry_after_signal_period_boundary"].eq(False).all()
        and entries["buy_at_or_above_up_limit"].eq(False).all(),
        "V28R2 parent T+1, period-boundary, or up-limit entry invariant failed",
    )
    by_year = signal_dates.dt.year.value_counts().sort_index()
    _require(
        {str(year): int(by_year.get(year, 0)) for year in DEVELOPMENT_YEARS}
        == EXPECTED_PARENT_BY_YEAR,
        "V28R2 parent yearly identity drifted",
    )
    return entries


def _load_and_validate_announcements(
    asset: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    root = Path(str(asset["asset_root"]))
    path = root / cy036.SOURCE_CAPTURE_NAME / "announcements.parquet"
    _require(path.is_file() and not path.is_symlink(), "CY-036 announcements table is missing")
    try:
        metadata = pd.read_parquet(path)
    except Exception as exc:
        raise V29Error("unable to read the sealed CY-036 announcements table") from exc
    missing = sorted(_REQUIRED_ANNOUNCEMENT_COLUMNS.difference(metadata.columns))
    _require(not missing, f"CY-036 announcements are missing columns: {missing}")
    _require(not metadata.empty, "CY-036 announcements are empty; event coverage is unknown")
    _require(
        metadata["hard_valid"].map(lambda value: isinstance(value, bool) and value).all(),
        "CY-036 contains a non-hard-valid announcement row",
    )
    _require(
        metadata["revision_history_complete"]
        .map(lambda value: isinstance(value, bool) and not value)
        .all()
        and metadata["strict_pit_eligible"]
        .map(lambda value: isinstance(value, bool) and not value)
        .all(),
        "CY-036 PIT-B revision limitations drifted",
    )
    snapshots = metadata["snapshot_id"].astype("string")
    _require(
        snapshots.notna().all()
        and snapshots.str.strip().ne("").all()
        and snapshots.nunique() == 1
        and snapshots.iloc[0] == asset["source_snapshot_id"],
        "CY-036 record snapshot lineage is missing or inconsistent",
    )
    years = pd.to_numeric(metadata["query_year"], errors="coerce")
    _require(
        years.notna().all() and years.le(2021).all(),
        "CY-036 announcements contain a post-2021 query partition",
    )
    query_dates = pd.to_datetime(metadata["source_query_date"], errors="raise")
    _require(
        query_dates.between(pd.Timestamp(CAPTURE_START), pd.Timestamp(CAPTURE_END)).all(),
        "CY-036 announcement query dates exceed the preregistered capture",
    )
    _require(
        not metadata["announcement_key"].astype("string").duplicated().any(),
        "CY-036 duplicate announcement_key identity",
    )
    try:
        normalized = classifier._normalize_temporal_columns(metadata, "CY-036 metadata")
    except classifier.RiskEventInputError as exc:
        raise V29Error(f"CY-036 announcement timing failed closed: {exc}") from exc

    development_end_exclusive = _normalized_local_timestamp(
        "2022-01-01 00:00:00", "development announcement cutoff"
    )
    post_development = normalized["available_at"].ge(development_end_exclusive)
    eligible = normalized.loc[~post_development].copy()
    _require(
        not eligible.empty,
        "CY-036 contains no announcement available during the development period",
    )
    temporal_scope = {
        "sealed_source_rows": len(normalized),
        "classified_rows_available_before_2022": len(eligible),
        "unclassified_rows_available_from_2022": int(post_development.sum()),
        "unclassified_min_available_at": (
            None
            if not post_development.any()
            else normalized.loc[post_development, "available_at"].min().isoformat()
        ),
        "unclassified_max_available_at": (
            None
            if not post_development.any()
            else normalized.loc[post_development, "available_at"].max().isoformat()
        ),
        "future_available_titles_classified": False,
    }
    try:
        classified = classifier.classify_exchange_announcements(eligible)
    except classifier.RiskEventInputError as exc:
        raise V29Error(f"CY-036 title classification failed closed: {exc}") from exc
    return classified, temporal_scope


def _require_pristine_stage_a_outputs() -> None:
    existing = [
        path
        for path in (
            selector_audit_path(),
            selected_path(),
            rejected_path(),
            STAGE_A_FREEZE,
            DEVELOPMENT_RESULT,
            REPORT,
        )
        if path.exists()
    ]
    _require(not existing, f"V29 Stage-A outputs already exist: {existing}")


def _require_pristine_development_outputs() -> None:
    existing = [
        path for path in (DEVELOPMENT_RESULT, REPORT, lane_root()) if path.exists()
    ]
    _require(not existing, f"V29 development outputs already exist: {existing}")


def _fail_closed_on_retired_v29() -> None:
    """Keep the superseded V29 executable after its coverage audit failed."""

    _require(BLOCKER.is_file(), "V29 coverage blocker is missing")
    _require(sha256(BLOCKER) == EXPECTED_BLOCKER_SHA256, "V29 coverage blocker drifted")
    blocker = _read_json_object(BLOCKER, "V29 coverage blocker")
    _require(
        blocker.get("conclusion", {}).get("status")
        == "FAIL_CLOSED_SSE_ADDDATE_DOMAIN_COVERAGE_NOT_PROVEN"
        and blocker.get("conclusion", {}).get("backtest_authorized") is False,
        "V29 coverage blocker semantics drifted",
    )
    raise V29Error(
        "V29 is retired and backtest-prohibited: SSE ADDDATE-domain coverage was "
        "not proven; use the separately preregistered V29R1 only after its full "
        "source asset is sealed and registered"
    )


def apply_issuer_integrity_cooldown(
    entries: pd.DataFrame,
    classifications: pd.DataFrame,
    *,
    covered_symbols: Sequence[str],
    coverage_start: str = CAPTURE_START,
    coverage_end: str = CAPTURE_END,
) -> pd.DataFrame:
    """Attach the frozen inclusive 120-day OPEN-event veto to parent entries.

    This pure selector consumes ``available_at`` for knowledge time.  It never
    replays OPEN/CLOSE state, so a later CLOSE cannot shorten the cooling window.
    """

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
        _normalized_local_timestamp(value, f"signal_time at row {index!r}")
        for index, value in work["signal_time"].items()
    ]
    covered = {_normalize_symbol(value) for value in covered_symbols}
    _require(len(covered) == len(list(covered_symbols)), "covered symbol identity is duplicated")
    start_at = _normalized_local_timestamp(f"{coverage_start} 00:00:00", "coverage_start")
    end_exclusive = _normalized_local_timestamp(
        f"{coverage_end} 00:00:00", "coverage_end"
    ) + pd.Timedelta(days=1)

    events = classifications.copy()
    events["symbol"] = events["symbol"].map(_normalize_symbol)
    events["available_at"] = [
        _normalized_local_timestamp(value, f"event available_at at row {index!r}")
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
    for row_number, (_, entry) in enumerate(work.iterrows()):
        signal_at = signal_times[row_number]
        window_start = signal_at - pd.Timedelta(days=COOLING_CALENDAR_DAYS)
        coverage_failures: list[str] = []
        if entry["symbol"] not in covered:
            coverage_failures.append("SYMBOL_NOT_IN_SEALED_UNIVERSE")
        if window_start < start_at:
            coverage_failures.append("WINDOW_START_PRECEDES_SEALED_CAPTURE")
        if signal_at >= end_exclusive:
            coverage_failures.append("SIGNAL_AFTER_SEALED_CAPTURE")
        if int(entry["signal_date"].year) not in DEVELOPMENT_YEARS:
            coverage_failures.append("SIGNAL_YEAR_OUTSIDE_DEVELOPMENT")
        coverage_complete = not coverage_failures

        symbol_events = open_by_symbol.get(
            entry["symbol"], pd.DataFrame(columns=open_events.columns)
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
                "available_at": pd.Timestamp(event.available_at).isoformat(),
                "risk_family": str(event.risk_family),
                "matched_rule": str(event.matched_rule),
                **(
                    {"title": str(event.title)}
                    if "title" in matched.columns
                    else {}
                ),
            }
            for event in matched.itertuples(index=False)
        ]
        announcement_keys = sorted({item["announcement_key"] for item in event_payload})
        families = sorted({item["risk_family"] for item in event_payload})
        gate = coverage_complete and not event_payload
        if not coverage_complete:
            rejection_reason = "INCOMPLETE_COVERAGE:" + "|".join(coverage_failures)
        elif event_payload:
            rejection_reason = "RECENT_HIGH_PRECISION_OPEN_ISSUER_RISK"
        else:
            rejection_reason = ""
        records.append(
            {
                "gap_id": entry["gap_id"],
                "v29_signal_time_local": signal_at,
                "v29_window_start_at": window_start,
                "v29_window_end_at": signal_at,
                "v29_coverage_complete": coverage_complete,
                "v29_coverage_failure_reasons": "|".join(coverage_failures),
                "v29_open_transition_count": len(event_payload),
                "v29_open_announcement_count": len(announcement_keys),
                "v29_open_announcement_keys": "|".join(announcement_keys),
                "v29_open_risk_families": "|".join(families),
                "v29_open_events_json": _canonical_json(event_payload),
                "v29_latest_open_available_at": (
                    pd.NaT if matched.empty else matched["available_at"].max()
                ),
                "v29_issuer_integrity_cooldown_gate": gate,
                "v29_rejection_reason": rejection_reason,
                "v29_feature_uses_post_signal_information": False,
            }
        )
    result = work.merge(pd.DataFrame.from_records(records), on="gap_id", validate="one_to_one")
    _require(
        not result["v29_issuer_integrity_cooldown_gate"].isna().any(),
        "V29 gate contains unknown values",
    )
    _require(
        result.loc[result["v29_issuer_integrity_cooldown_gate"], "v29_coverage_complete"].all(),
        "V29 admitted an incompletely covered signal",
    )
    return result


def _load_covered_symbols(asset_root: Path) -> list[str]:
    path = asset_root / cy036.UNIVERSE_NAME
    try:
        universe = pd.read_parquet(path, columns=["symbol"])
    except Exception as exc:
        raise V29Error("unable to read CY-036 sealed universe") from exc
    _require(not universe.empty and universe["symbol"].notna().all(), "CY-036 universe is empty")
    symbols = [_normalize_symbol(value) for value in universe["symbol"]]
    _require(symbols == sorted(symbols), "CY-036 universe is not deterministically sorted")
    _require(
        len(symbols) == len(set(symbols)) == cy036.EXPECTED_UNIVERSE_SYMBOLS,
        "CY-036 universe identity drifted",
    )
    return symbols


def _identity_sha256(values: Sequence[object]) -> str:
    return _value_sha256(sorted(str(value) for value in values))


def run_stage_a() -> dict[str, Any]:
    """Freeze the V29 selector identity without opening any outcome artifact."""

    _require_pristine_stage_a_outputs()
    _fail_closed_on_retired_v29()
    protocol_hashes = _verify_preregistration_and_parent()
    asset = verify_registered_cy036()
    entries = _load_parent_entries()
    classifications, announcement_temporal_scope = _load_and_validate_announcements(asset)
    covered_symbols = _load_covered_symbols(Path(str(asset["asset_root"])))
    audit = apply_issuer_integrity_cooldown(
        entries,
        classifications,
        covered_symbols=covered_symbols,
    ).sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    selected = audit.loc[audit["v29_issuer_integrity_cooldown_gate"]].copy()
    rejected = audit.loc[~audit["v29_issuer_integrity_cooldown_gate"]].copy()

    for path, frame in (
        (selector_audit_path(), audit),
        (selected_path(), selected),
        (rejected_path(), rejected),
    ):
        v28.replay.repair.write_parquet(frame, path)

    selected_years = selected["signal_date"].dt.year.value_counts()
    rejected_family_counts: Counter[str] = Counter()
    for value in rejected["v29_open_risk_families"]:
        rejected_family_counts.update(item for item in str(value).split("|") if item)
    period = {
        "parent_signals": len(audit),
        "selected_signals": len(selected),
        "rejected_signals": len(rejected),
        "selected_by_signal_year": {
            str(year): int(selected_years.get(year, 0)) for year in DEVELOPMENT_YEARS
        },
        "rejected_recent_open_event": int(
            rejected["v29_rejection_reason"]
            .eq("RECENT_HIGH_PRECISION_OPEN_ISSUER_RISK")
            .sum()
        ),
        "rejected_incomplete_coverage": int(
            rejected["v29_rejection_reason"].str.startswith("INCOMPLETE_COVERAGE:").sum()
        ),
        "rejected_risk_family_signal_counts": dict(sorted(rejected_family_counts.items())),
        "accepted_gap_identity_sha256": _identity_sha256(selected["gap_id"].tolist()),
        "rejected_gap_identity_sha256": _identity_sha256(rejected["gap_id"].tolist()),
        "selector_audit_sha256": sha256(selector_audit_path()),
        "selected_entries_sha256": sha256(selected_path()),
        "rejected_entries_sha256": sha256(rejected_path()),
    }
    _require(
        period["selected_signals"] + period["rejected_signals"] == period["parent_signals"],
        "V29 selector identity conservation failed",
    )
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        "runner_sha256": sha256(Path(__file__)),
        "protocol_hashes": protocol_hashes,
        "cy036_identity": asset,
        "rule": {
            "window": "signal_time-120 calendar days <= available_at <= signal_time",
            "action": "OPEN only",
            "families": list(classifier.RISK_FAMILIES),
            "close_treatment": "CLOSE_DOES_NOT_SHORTEN_COOLING_PERIOD",
            "missing_policy": "REJECT",
        },
        "coverage_proof": {
            "start": CAPTURE_START,
            "end": CAPTURE_END,
            "covered_symbols": len(covered_symbols),
            "source_snapshot_id": asset["source_snapshot_id"],
            "all_parent_windows_complete": bool(audit["v29_coverage_complete"].all()),
            "post_2021_announcement_partition_opened": False,
            "announcement_temporal_scope": announcement_temporal_scope,
        },
        "development": period,
        "development_outcomes_opened": "NO_IN_THIS_STAGE",
        "post_2021_entries_announcements_or_outcomes_opened": "NO_IN_THIS_STAGE",
    }
    _write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    _require(STAGE_A_FREEZE.is_file(), "V29 development Stage-A freeze is missing")
    freeze = _read_json_object(STAGE_A_FREEZE, "V29 Stage-A freeze")
    _require(
        freeze.get("experiment") == EXPERIMENT
        and freeze.get("stage") == "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN"
        and freeze.get("development_outcomes_opened") == "NO_IN_THIS_STAGE"
        and freeze.get("post_2021_entries_announcements_or_outcomes_opened")
        == "NO_IN_THIS_STAGE",
        "V29 Stage-A freeze status drifted",
    )
    current_protocol = _verify_preregistration_and_parent()
    current_asset = verify_registered_cy036()
    drift: dict[str, Any] = {}
    for key, expected, actual in (
        ("runner_sha256", freeze.get("runner_sha256"), sha256(Path(__file__))),
        ("protocol_hashes", freeze.get("protocol_hashes"), current_protocol),
        ("cy036_identity", freeze.get("cy036_identity"), current_asset),
    ):
        if expected != actual:
            drift[key] = [expected, actual]
    paths = {
        "selector_audit_sha256": selector_audit_path(),
        "selected_entries_sha256": selected_path(),
        "rejected_entries_sha256": rejected_path(),
    }
    period = freeze.get("development", {})
    for key, path in paths.items():
        actual = sha256(path) if path.is_file() else None
        if period.get(key) != actual:
            drift[key] = [period.get(key), actual]
    _require(not drift, f"V29 development Stage-A drift: {drift}")

    audit = pd.read_parquet(selector_audit_path())
    selected = pd.read_parquet(selected_path())
    rejected = pd.read_parquet(rejected_path())
    _require(
        len(audit) == period.get("parent_signals")
        and len(selected) == period.get("selected_signals")
        and len(rejected) == period.get("rejected_signals"),
        "V29 frozen selector counts drifted",
    )
    accepted_ids = set(
        audit.loc[audit["v29_issuer_integrity_cooldown_gate"], "gap_id"].astype(str)
    )
    rejected_ids = set(
        audit.loc[~audit["v29_issuer_integrity_cooldown_gate"], "gap_id"].astype(str)
    )
    _require(
        accepted_ids == set(selected["gap_id"].astype(str))
        and rejected_ids == set(rejected["gap_id"].astype(str))
        and not (accepted_ids & rejected_ids),
        "V29 frozen accepted/rejected identity partition drifted",
    )
    _require(
        pd.to_datetime(audit["signal_date"]).dt.year.isin(DEVELOPMENT_YEARS).all(),
        "V29 Stage-A audit contains a post-2021 signal",
    )
    return {
        "verified": True,
        "runner_sha256": sha256(Path(__file__)),
        "selected_entries_sha256": sha256(selected_path()),
        "selected_signals": len(selected),
    }


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


def run_development() -> dict[str, Any]:
    """Open only the frozen 2018-2021 outcomes after Stage-A verification."""

    _require_pristine_development_outputs()
    _fail_closed_on_retired_v29()
    verification = verify_stage_a()
    with _development_runtime():
        lane = v28.replay.run_lane("DEVELOPMENT", DEVELOPMENT_YEARS)
    accepted_path = lane_root() / "portfolio_accepted.parquet"
    accepted = pd.read_parquet(accepted_path)
    _require(
        not accepted.empty
        and pd.to_datetime(accepted["signal_date"]).dt.year.isin(DEVELOPMENT_YEARS).all(),
        "V29 exact replay returned empty or out-of-period accepted trades",
    )
    summary = v28._accepted_summary(accepted, DEVELOPMENT_YEARS)
    checks = v28.development_checks(summary)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "lane": lane,
        "accepted_summary": summary,
        "goal_checks": checks,
        "selector_passed": passed,
        "verdict": (
            "DEVELOPMENT_PASS_LATER_DATA_REMAINS_LOCKED"
            if passed
            else "DEVELOPMENT_FAILED_LATER_DATA_REMAINS_LOCKED"
        ),
        "development_outcomes_opened": "YES_2018_2021_ONLY",
        "post_2021_entries_announcements_or_outcomes_opened": "NO",
        "later_period_authorization_created": "NO",
        "hashes": {
            "portfolio_accepted": sha256(accepted_path),
            "outcomes": sha256(lane_root() / "outcomes.parquet"),
        },
    }
    _write_json(DEVELOPMENT_RESULT, result)
    _render_report(result)
    return result


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _render_report(result: Mapping[str, Any]) -> None:
    summary = result["accepted_summary"]
    freeze = _read_json_object(STAGE_A_FREEZE, "V29 Stage-A freeze")["development"]
    rows: list[str] = []
    for year in DEVELOPMENT_YEARS:
        item = summary["yearly_by_signal_year"][str(year)]
        hold = item["average_holding_sessions"]
        rows.append(
            f"|{year}|{item['trades']}|{_pct(item['mean_net'])}|"
            f"{_pct(item['median_net'])}|{_pct(item['win'])}|{_pct(item['severe10'])}|"
            f"{'—' if hold is None else f'{hold:.2f}'}|"
        )
    lines = [
        f"# {EXPERIMENT}",
        "",
        (
            "V29 leaves the V28R2 price, volume, entry, target, holding, cost, and "
            "K80 rules unchanged. It vetoes a signal when an official high-precision "
            "OPEN issuer-risk title became available during the inclusive 120 calendar "
            "days ending at the completed signal decision."
        ),
        "",
        (
            "A later CLOSE does not erase that cooling period. Silence is accepted only "
            "when the complete sealed CY-036 official-exchange metadata window is proven; "
            "unknown or incomplete coverage rejects."
        ),
        "",
        "## Development 2018-2021",
        "",
        (
            f"Stage A retained {freeze['selected_signals']} of "
            f"{freeze['parent_signals']} V28R2 signals and rejected "
            f"{freeze['rejected_signals']} before outcomes were opened."
        ),
        "",
        (
            f"Exact K80 accepted {summary['accepted_trades']} "
            f"({summary['accepted_trades_per_year']:.2f}/year), mean "
            f"{_pct(summary['mean_net'])}, median {_pct(summary['median_net'])}, "
            f"win {_pct(summary['win'])}, severe10 {_pct(summary['severe10'])}, "
            f"average hold {summary['average_holding_sessions']:.2f} sessions."
        ),
        "",
        "|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"Development passed: **{result['selector_passed']}**.",
        "",
        (
            "No post-2021 entries, announcement partitions, or outcomes were opened. "
            "No later-period authorization was created."
        ),
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stage-a", "development", "all"), default="all")
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    if args.mode in ("stage-a", "all"):
        payload["stage_a"] = run_stage_a()
    if args.mode in ("development", "all"):
        payload["development"] = run_development()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
