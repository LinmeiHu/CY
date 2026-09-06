#!/usr/bin/env python3
"""Build the non-authorizing V29R1 issuer-risk metadata composite.

The composite repairs the SSE knowledge-time coverage problem without opening
any outcome data.  It uses a sealed SSE-only capture whose query domain starts
at the exchange's first trading day and routes sources explicitly:

* SSE symbols come only from the full-history SSE capture;
* SZSE symbols come only from the existing bounded base capture.

The overlapping SSE query interval is an audit surface, not a deduplication
surface.  Every overlapping announcement key and its raw-record/normalized
identity must agree one-for-one.  Both nested seals are fully revalidated on
every build or validation, including every raw page and snapshot identity.

The wrapper projects identity and time columns only and never opens the title
column for inspection or classification.  It never reads returns, portfolios,
or post-2021 query partitions, and its output remains PIT-B, title-source-only,
revision-incomplete, unregistered, and backtest-unauthorized.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2 as v28r2,
)
from research.market_behavior_os_v2.scripts import (
    seal_exchange_issuer_announcements_v1 as source_sealer,
)

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"

ASSET_ID = "CY-036-R1"
BUILDER_ID = "CY-036-R1-EXCHANGE-ISSUER-RISK-COMPOSITE-BUILDER-V1"
EXPERIMENT = (
    "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29R1"
)
PARENT_EXPERIMENT = v28r2.EXPERIMENT

PREREGISTRATION_PATH = OS_ROOT / f"experiments/{EXPERIMENT}_preregistration.json"
EXPECTED_PREREGISTRATION_SHA256 = (
    "583e35cf4722daf569feec8bc64118cf430aa5b278b4c7149d6147ef79504b34"
)
V29_BLOCKER_PATH = OS_ROOT / (
    "artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-"
    "ISSUER-INTEGRITY-COOLDOWN-V29_coverage_blocker.json"
)
V28R2_RUNNER_PATH = Path(v28r2.__file__).resolve()
V28R2_STAGE_A_PATH = v28r2.STAGE_A_FREEZE
V28R2_DEVELOPMENT_RESULT_PATH = v28r2.DEVELOPMENT_RESULT

SSE_QUERY_START = "1990-12-19"
BASE_QUERY_START = "2017-10-01"
QUERY_END = "2021-12-31"
EXPECTED_BASE_SYMBOLS = 378
EXPECTED_SSE_SYMBOLS = 127
EXPECTED_BASE_UNIVERSE_SHA256 = (
    "19de877c24c646f0f225890f3376831aa043e62feed6346f0ee339545555f571"
)
EXPECTED_BASE_SNAPSHOT_ID = (
    "exchange-announcement-"
    "258a32a6e4694987f22fb8386ee72683508fc91192becdc2fa2556fb57deddf3"
)
EXPECTED_BASE_ASSET_MANIFEST_SHA256 = (
    "9eb9851b364019db123b73080031a5f51db806d78a48120a4c3d6a42634ef59c"
)
SSE_CAUSAL_AVAILABLE_AT_CONTRACT = (
    "causal_available_at=max(original ADDDATE,SSEDATE+1 calendar day 00:00 Asia/Shanghai)"
)
SZSE_CAUSAL_AVAILABLE_AT_CONTRACT = "causal_available_at=validated available_at"

SSE_UNIVERSE_NAME = "sse_universe.parquet"
SSE_CAPTURE_NAME = "sse_full_history_capture"
COMPOSITE_NAME = "announcement_route_index.parquet"
ACTIVATION_AUDIT_NAME = "activation_audit.json"
ASSET_MANIFEST_NAME = "asset_manifest.json"

_PREPARED_TOP_LEVEL = {SSE_UNIVERSE_NAME}
_BUILD_TOP_LEVEL = {SSE_UNIVERSE_NAME, SSE_CAPTURE_NAME}
_SEALED_TOP_LEVEL = {
    SSE_UNIVERSE_NAME,
    SSE_CAPTURE_NAME,
    COMPOSITE_NAME,
    ACTIVATION_AUDIT_NAME,
    ASSET_MANIFEST_NAME,
}
_CAPTURE_FILES = (
    "source_manifest.json",
    "audit.json",
    "announcements.parquet",
    "request_pages.parquet",
    source_sealer.AUDIT_VALIDATION_NAME,
    source_sealer.ASSET_MANIFEST_NAME,
)
_IDENTITY_COLUMNS = [
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
]
_OVERLAP_EXCLUDED_COLUMNS = {"snapshot_id"}

_CAPTURE_INVENTORY_ROLES = {
    "source_manifest.json": "source_manifest",
    "audit.json": "collector_audit",
    "announcements.parquet": "nested_announcements",
    "request_pages.parquet": "request_pages",
    source_sealer.AUDIT_VALIDATION_NAME: "seal_validation_audit",
    source_sealer.ASSET_MANIFEST_NAME: "nested_asset_manifest",
}


class V29R1AssetError(RuntimeError):
    """Fail closed on source, coverage, identity, or immutable-wrapper drift."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V29R1AssetError(message)


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise V29R1AssetError(f"invalid {label}: {path}") from exc
    _require(isinstance(value, dict), f"{label} must be a JSON object")
    return value


def _file_facts(path: Path, label: str) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    return {"sha256": collector.sha256_file(path), "bytes": path.stat().st_size}


def _strict_bool(value: Any, expected: bool, label: str) -> None:
    _require(isinstance(value, bool) and value is expected, f"{label} must be {expected}")


def _string(value: Any, label: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{label} must be a non-empty string")
    return value


def _safe_existing_dir(path: Path, label: str) -> Path:
    _require(not path.is_symlink(), f"{label} must not be a symlink: {path}")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise V29R1AssetError(f"{label} does not exist: {path}") from exc
    _require(resolved.is_dir(), f"{label} is not a directory: {resolved}")
    return resolved


def _safe_asset_root(path: Path, *, create: bool = False) -> Path:
    _require(not path.is_symlink(), f"asset root must not be a symlink: {path}")
    if create and not path.exists():
        path.mkdir(parents=True)
    return _safe_existing_dir(path, "asset root")


def _require_exact_top_level(root: Path, expected: set[str], label: str) -> None:
    actual: set[str] = set()
    for path in root.iterdir():
        _require(not path.is_symlink(), f"{label} contains a symlink: {path.name}")
        actual.add(path.name)
    _require(not expected - actual, f"{label} is missing entries: {sorted(expected - actual)}")
    _require(not actual - expected, f"{label} contains extra entries: {sorted(actual - expected)}")


def _load_canonical_universe(
    path: Path,
    label: str,
    *,
    expected_count: int,
    suffix: str | None = None,
) -> list[str]:
    _file_facts(path, label)
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise V29R1AssetError(f"unable to read {label}") from exc
    _require(list(frame.columns) == ["symbol"], f"{label} columns must be exactly ['symbol']")
    _require(not frame.empty and frame.symbol.notna().all(), f"{label} is empty or missing")
    raw = [str(value).strip().upper() for value in frame.symbol.tolist()]
    try:
        normalized = [collector.normalize_symbol(value) for value in raw]
    except collector.CaptureError as exc:
        raise V29R1AssetError(f"{label} contains an invalid symbol") from exc
    _require(raw == normalized, f"{label} symbols are not canonical")
    _require(normalized == sorted(normalized), f"{label} is not deterministically sorted")
    _require(len(normalized) == len(set(normalized)), f"{label} contains duplicate symbols")
    _require(len(normalized) == expected_count, f"{label} must contain {expected_count} symbols")
    if suffix is not None:
        _require(
            all(symbol.endswith(suffix) for symbol in normalized),
            f"{label} has wrong exchange",
        )
    return normalized


def _base_identity(base_capture_root: Path, *, full_seal: bool) -> dict[str, Any]:
    root = _safe_existing_dir(base_capture_root, "base source capture")
    source_manifest = _read_json_object(root / "source_manifest.json", "base source manifest")
    asset_manifest_path = root / source_sealer.ASSET_MANIFEST_NAME
    asset_manifest = _read_json_object(asset_manifest_path, "base source asset manifest")
    _require(
        collector.sha256_file(asset_manifest_path) == EXPECTED_BASE_ASSET_MANIFEST_SHA256,
        "base source asset-manifest SHA-256 is not the frozen parent identity",
    )
    _require(
        source_manifest.get("asset_id") == collector.ASSET_ID
        and asset_manifest.get("asset_id") == collector.ASSET_ID,
        "base source asset_id drifted",
    )
    _require(
        source_manifest.get("coverage")
        == {"start": BASE_QUERY_START, "end": QUERY_END},
        "base source query coverage drifted",
    )
    _require(
        source_manifest.get("snapshot_id") == EXPECTED_BASE_SNAPSHOT_ID
        and asset_manifest.get("snapshot_id") == EXPECTED_BASE_SNAPSHOT_ID,
        "base source snapshot identity drifted",
    )
    _strict_bool(source_manifest.get("backtest_authorized"), False, "base authorization")
    _strict_bool(asset_manifest.get("backtest_authorized"), False, "base seal authorization")
    declared_universe = Path(_string(source_manifest.get("universe_source"), "base universe"))
    _require(declared_universe.is_absolute(), "base universe path must be absolute")
    symbols = _load_canonical_universe(
        declared_universe,
        "base universe",
        expected_count=EXPECTED_BASE_SYMBOLS,
    )
    _require(
        collector.sha256_file(declared_universe) == EXPECTED_BASE_UNIVERSE_SHA256,
        "base universe SHA-256 is not the frozen parent identity",
    )
    sealed: dict[str, Any] | None = None
    if full_seal:
        try:
            sealed = source_sealer.validate_asset(root)
        except Exception as exc:
            raise V29R1AssetError(f"base source full seal validation failed: {exc}") from exc
        _require(sealed.get("status") == "PASS", "base source seal did not pass")
        _require(
            sealed.get("snapshot_id") == EXPECTED_BASE_SNAPSHOT_ID,
            "base source revalidated snapshot drifted",
        )
        _strict_bool(sealed.get("backtest_authorized"), False, "base nested authorization")
    return {
        "root": root,
        "source_manifest": source_manifest,
        "asset_manifest": asset_manifest,
        "asset_manifest_facts": _file_facts(asset_manifest_path, "base asset manifest"),
        "universe_path": declared_universe,
        "symbols": symbols,
        "sealed": sealed,
    }


def prepare_sse_universe(base_capture_root: Path, asset_root: Path) -> dict[str, Any]:
    """Create the exact sorted .SH subset of the frozen 378-symbol base universe."""

    base = _base_identity(base_capture_root, full_seal=False)
    root = _safe_asset_root(asset_root, create=True)
    _require_exact_top_level(root, set(), "new composite root")
    symbols = [symbol for symbol in base["symbols"] if symbol.endswith(".SH")]
    _require(len(symbols) == EXPECTED_SSE_SYMBOLS, "derived SSE symbol count drifted")
    output = root / SSE_UNIVERSE_NAME
    fd, temporary_name = tempfile.mkstemp(prefix=f".{SSE_UNIVERSE_NAME}.", dir=root)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        pd.DataFrame({"symbol": symbols}).to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(output)
        output.chmod(0o444)
    except Exception:
        temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        raise
    verified = _load_canonical_universe(
        output,
        SSE_UNIVERSE_NAME,
        expected_count=EXPECTED_SSE_SYMBOLS,
        suffix=".SH",
    )
    _require(verified == symbols, "written SSE universe differs from derived parent subset")
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "base_universe_sha256": EXPECTED_BASE_UNIVERSE_SHA256,
        "sse_universe": str(output),
        "sse_universe_sha256": collector.sha256_file(output),
        "symbols": len(symbols),
        "next_state": "CAPTURE_AND_SEAL_SSE_FULL_HISTORY",
        "registered": False,
        "backtest_authorized": False,
    }


def _validate_preregistration() -> dict[str, Any]:
    preregistration_facts = _file_facts(PREREGISTRATION_PATH, "V29R1 preregistration")
    _require(
        preregistration_facts["sha256"] == EXPECTED_PREREGISTRATION_SHA256,
        "V29R1 preregistration SHA-256 differs from the frozen identity",
    )
    prereg = _read_json_object(PREREGISTRATION_PATH, "V29R1 preregistration")
    _require(prereg.get("experiment") == EXPERIMENT, "V29R1 experiment drifted")
    _require(
        prereg.get("status")
        == "SEMANTIC_RULE_FROZEN_BEFORE_DEVELOPMENT_EVENT_OR_OUTCOME_JOIN",
        "V29R1 is not a pre-event/pre-outcome semantic freeze",
    )
    _require(prereg.get("parent") == PARENT_EXPERIMENT, "V29R1 parent drifted")

    parent_files = {
        "parent_runner_sha256": (V28R2_RUNNER_PATH, "V28R2 runner"),
        "parent_development_stage_a_sha256": (V28R2_STAGE_A_PATH, "V28R2 Stage A"),
        "parent_development_result_sha256": (
            V28R2_DEVELOPMENT_RESULT_PATH,
            "V28R2 development result identity",
        ),
    }
    parent_facts: dict[str, dict[str, Any]] = {}
    for key, (path, label) in parent_files.items():
        facts = _file_facts(path, label)
        _require(prereg.get(key) == facts["sha256"], f"{label} SHA-256 differs from V29R1")
        parent_facts[key] = facts

    repair = prereg.get("knowledge_time_repair")
    _require(isinstance(repair, dict), "V29R1 knowledge_time_repair is missing")
    sse_repair = repair.get("sse")
    szse_repair = repair.get("szse")
    _require(
        isinstance(sse_repair, dict)
        and sse_repair.get("causal_available_at")
        == "max(original ADDDATE, SSEDATE + 1 calendar day 00:00 Asia/Shanghai)"
        and sse_repair.get("missing_or_invalid_adddate_or_ssedate") == "FAIL_CLOSED",
        "V29R1 SSE knowledge-time repair drifted",
    )
    _require(
        isinstance(szse_repair, dict)
        and szse_repair.get("date_only_or_midnight_publishTime")
        == "next calendar day 00:00 Asia/Shanghai"
        and szse_repair.get("intraday_publishTime")
        == "official source second in Asia/Shanghai",
        "V29R1 SZSE knowledge-time repair drifted",
    )
    _require(
        repair.get("derivation_must_preserve_original_fields")
        == ["ADDDATE", "SSEDATE", "publishTime"],
        "V29R1 original-field preservation contract drifted",
    )

    coverage = prereg.get("source_coverage_contract")
    _require(isinstance(coverage, dict), "V29R1 source_coverage_contract is missing")
    sse_coverage = coverage.get("sse")
    szse_coverage = coverage.get("szse")
    _require(
        isinstance(sse_coverage, dict)
        and sse_coverage.get("start") == SSE_QUERY_START
        and sse_coverage.get("end") == QUERY_END
        and sse_coverage.get("membership_field") == "SSEDATE",
        "V29R1 SSE source coverage contract drifted",
    )
    _require(
        isinstance(szse_coverage, dict)
        and szse_coverage.get("start") == BASE_QUERY_START
        and szse_coverage.get("end") == QUERY_END
        and szse_coverage.get("knowledge_field") == "publishTime",
        "V29R1 SZSE source coverage contract drifted",
    )
    _strict_bool(coverage.get("title_metadata_only"), True, "V29R1 title-only contract")
    _require(
        coverage.get("unknown_page_identity_hash_or_coverage") == "FAIL_CLOSED",
        "V29R1 missing-source policy drifted",
    )

    later = prereg.get("locked_later_periods")
    _require(isinstance(later, dict), "V29R1 later-period lock is missing")
    _require(
        "2022_2024" in later and "2025_plus" in later,
        "V29R1 later-period lock is incomplete",
    )
    prior = prereg.get("prior_v29_blocker")
    _require(isinstance(prior, dict), "V29R1 prior blocker identity is missing")
    blocker_facts = _file_facts(V29_BLOCKER_PATH, "V29 coverage blocker")
    _require(
        prior.get("artifact_sha256") == blocker_facts["sha256"]
        and prior.get("status") == "FAIL_CLOSED_SSE_ADDDATE_DOMAIN_COVERAGE_NOT_PROVEN",
        "V29 coverage-blocker identity drifted",
    )
    _strict_bool(
        prior.get("v29_cy036_registration_or_backtest_authorized"),
        False,
        "V29 prior authorization",
    )
    return {
        "preregistration": prereg,
        "preregistration_facts": preregistration_facts,
        "blocker_facts": blocker_facts,
        "parent_facts": parent_facts,
    }


def _read_capture_tables(root: Path, label: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        announcements = pd.read_parquet(
            root / "announcements.parquet", columns=_IDENTITY_COLUMNS
        )
        pages = pd.read_parquet(
            root / "request_pages.parquet",
            columns=[
                "query_id",
                "exchange",
                "symbol",
                "query_year",
                "query_start",
                "query_end",
                "page",
            ],
        )
    except Exception as exc:
        raise V29R1AssetError(f"unable to read {label} metadata tables") from exc
    _require(
        list(announcements.columns) == _IDENTITY_COLUMNS,
        f"{label} projected identity columns drifted",
    )
    required_pages = {
        "query_id",
        "exchange",
        "symbol",
        "query_year",
        "query_start",
        "query_end",
        "page",
    }
    _require(required_pages.issubset(pages.columns), f"{label} request columns are missing")
    return announcements, pages


def _validate_capture_rows(
    announcements: pd.DataFrame,
    symbols: Sequence[str],
    *,
    snapshot_id: str,
    exchanges: set[str],
    label: str,
) -> None:
    _require(not announcements.empty, f"{label} announcements are empty")
    _require(not announcements.duplicated("announcement_key").any(), f"{label} duplicate keys")
    _require(
        announcements["snapshot_id"].notna().all()
        and announcements["snapshot_id"].eq(snapshot_id).all(),
        f"{label} snapshot lineage drifted",
    )
    _require(set(announcements.exchange.astype(str)) <= exchanges, f"{label} exchange drifted")
    _require(set(announcements.symbol.astype(str)) <= set(symbols), f"{label} symbol drifted")
    _require(
        all(value is True for value in announcements.hard_valid.tolist()),
        f"{label} has non-hard-valid records",
    )
    _require(
        all(value is False for value in announcements.revision_history_complete.tolist())
        and all(value is False for value in announcements.strict_pit_eligible.tolist()),
        f"{label} PIT-B limitations drifted",
    )


def _expected_query_rows(
    symbols: Sequence[str], start: str, end: str
) -> dict[str, tuple[str, str, str, str]]:
    return {
        spec.query_id: (spec.exchange, spec.symbol, spec.start, spec.end)
        for spec in collector.build_query_specs(list(symbols), start, end)
    }


def _validate_query_coverage(
    pages: pd.DataFrame,
    symbols: Sequence[str],
    *,
    start: str,
    end: str,
    label: str,
) -> None:
    columns = ["query_id", "exchange", "symbol", "query_start", "query_end"]
    unique = pages[columns].drop_duplicates()
    _require(
        not unique.duplicated("query_id").any(),
        f"{label} query_id maps to multiple intervals",
    )
    actual = {
        str(row.query_id): (
            str(row.exchange),
            str(row.symbol),
            str(row.query_start),
            str(row.query_end),
        )
        for row in unique.itertuples(index=False)
    }
    expected = _expected_query_rows(symbols, start, end)
    _require(actual == expected, f"{label} query coverage has a gap, overlap, or identity drift")

    for symbol in symbols:
        intervals = sorted(
            (
                pd.Timestamp(row.query_start),
                pd.Timestamp(row.query_end),
            )
            for row in unique.loc[unique.symbol.eq(symbol)].itertuples(index=False)
        )
        _require(bool(intervals), f"{label} has no query interval for {symbol}")
        _require(intervals[0][0] == pd.Timestamp(start), f"{label} start gap for {symbol}")
        _require(intervals[-1][1] == pd.Timestamp(end), f"{label} end gap for {symbol}")
        for previous, current in pairwise(intervals):
            _require(
                current[0] == previous[1] + pd.Timedelta(days=1),
                f"{label} query gap or overlap for {symbol}",
            )


def _validate_historical_capture(asset_root: Path, sse_symbols: Sequence[str]) -> dict[str, Any]:
    capture_root = _safe_existing_dir(asset_root / SSE_CAPTURE_NAME, "SSE full-history capture")
    try:
        sealed = source_sealer.validate_asset(capture_root)
    except Exception as exc:
        raise V29R1AssetError(f"SSE full-history seal validation failed: {exc}") from exc
    _require(sealed.get("status") == "PASS", "SSE full-history seal did not pass")
    _strict_bool(sealed.get("backtest_authorized"), False, "SSE nested authorization")

    source_manifest = _read_json_object(capture_root / "source_manifest.json", "SSE manifest")
    asset_manifest = _read_json_object(
        capture_root / source_sealer.ASSET_MANIFEST_NAME,
        "SSE asset manifest",
    )
    _require(
        source_manifest.get("coverage") == {"start": SSE_QUERY_START, "end": QUERY_END},
        "SSE full-history query coverage drifted",
    )
    declared_universe = Path(_string(source_manifest.get("universe_source"), "SSE universe"))
    expected_universe = (asset_root / SSE_UNIVERSE_NAME).resolve(strict=True)
    _require(
        declared_universe.is_absolute()
        and declared_universe.resolve(strict=True) == expected_universe,
        "SSE capture is not bound to this wrapper's sse_universe.parquet",
    )
    actual_symbols = _load_canonical_universe(
        declared_universe,
        "SSE capture universe",
        expected_count=EXPECTED_SSE_SYMBOLS,
        suffix=".SH",
    )
    _require(actual_symbols == list(sse_symbols), "SSE capture universe set drifted")
    _require(
        source_manifest.get("snapshot_id") == sealed.get("snapshot_id")
        and asset_manifest.get("snapshot_id") == sealed.get("snapshot_id"),
        "SSE nested snapshot identity drifted",
    )
    announcements, pages = _read_capture_tables(capture_root, "SSE full-history")
    _validate_capture_rows(
        announcements,
        sse_symbols,
        snapshot_id=str(sealed["snapshot_id"]),
        exchanges={"SSE"},
        label="SSE full-history",
    )
    _validate_query_coverage(
        pages,
        sse_symbols,
        start=SSE_QUERY_START,
        end=QUERY_END,
        label="SSE full-history",
    )
    return {
        "root": capture_root,
        "sealed": sealed,
        "source_manifest": source_manifest,
        "asset_manifest": asset_manifest,
        "announcements": announcements,
        "pages": pages,
    }


def _validate_base_capture_tables(base: Mapping[str, Any]) -> dict[str, Any]:
    root: Path = base["root"]
    sealed = base["sealed"]
    _require(isinstance(sealed, dict), "base source was not fully revalidated")
    announcements, pages = _read_capture_tables(root, "base source")
    _validate_capture_rows(
        announcements,
        base["symbols"],
        snapshot_id=EXPECTED_BASE_SNAPSHOT_ID,
        exchanges={"SSE", "SZSE"},
        label="base source",
    )
    _validate_query_coverage(
        pages,
        base["symbols"],
        start=BASE_QUERY_START,
        end=QUERY_END,
        label="base source",
    )
    return {"announcements": announcements, "pages": pages}


def _scalar_equal(left: Any, right: Any) -> bool:
    if pd.isna(left) and pd.isna(right):
        return True
    if isinstance(left, pd.Timestamp) or isinstance(right, pd.Timestamp):
        try:
            return pd.Timestamp(left) == pd.Timestamp(right)
        except (TypeError, ValueError):
            return False
    return type(left) is type(right) and left == right


def _audit_sse_overlap(base: pd.DataFrame, historical: pd.DataFrame) -> dict[str, Any]:
    start = pd.Timestamp(BASE_QUERY_START)
    end = pd.Timestamp(QUERY_END)
    base_dates = pd.to_datetime(base.source_query_date)
    historical_dates = pd.to_datetime(historical.source_query_date)
    base_overlap = base.loc[
        base.exchange.eq("SSE") & base_dates.between(start, end, inclusive="both")
    ]
    historical_overlap = historical.loc[
        historical.exchange.eq("SSE")
        & historical_dates.between(start, end, inclusive="both")
    ]
    base_by_key = {str(row["announcement_key"]): row for _, row in base_overlap.iterrows()}
    history_by_key = {
        str(row["announcement_key"]): row for _, row in historical_overlap.iterrows()
    }
    _require(
        set(base_by_key) == set(history_by_key),
        "overlapping SSE announcement-key sets differ between sealed sources",
    )
    compared_columns = [
        column for column in _IDENTITY_COLUMNS if column not in _OVERLAP_EXCLUDED_COLUMNS
    ]
    _require("raw_record_sha256" in compared_columns, "raw-record identity is not audited")
    for key in sorted(base_by_key):
        left = base_by_key[key]
        right = history_by_key[key]
        for column in compared_columns:
            _require(
                _scalar_equal(left[column], right[column]),
                f"overlapping SSE identity conflict at {key}.{column}",
            )
    return {
        "start": BASE_QUERY_START,
        "end": QUERY_END,
        "base_keys": len(base_by_key),
        "historical_keys": len(history_by_key),
        "one_to_one_key_set_equal": True,
        "raw_record_sha256_equal": True,
        "normalized_identity_equal": True,
        "capture_specific_page_lineage_compared": False,
        "capture_specific_page_lineage_reason": (
            "page number, page body, retrieval time and snapshot are capture identities; "
            "the exact raw official record hash and every normalized source field are compared"
        ),
    }


def _composite_frame(base: pd.DataFrame, historical: pd.DataFrame) -> pd.DataFrame:
    routed_sse = historical.loc[historical.exchange.eq("SSE")].copy()
    original_sse_available = pd.to_datetime(routed_sse.available_at)
    sse_display_floor = pd.to_datetime(routed_sse.source_query_date).dt.normalize() + pd.Timedelta(
        days=1
    )
    _require(
        original_sse_available.notna().all() and sse_display_floor.notna().all(),
        "SSE knowledge-time repair input is missing",
    )
    routed_sse.insert(
        0,
        "causal_available_at",
        pd.concat([original_sse_available, sse_display_floor], axis=1).max(axis=1),
    )
    routed_sse.insert(
        0,
        "original_publish_time",
        pd.Series(pd.NA, index=routed_sse.index, dtype="string"),
    )
    routed_sse.insert(
        0,
        "original_ssedate",
        pd.to_datetime(routed_sse.source_query_date).dt.strftime("%Y-%m-%d").astype("string"),
    )
    routed_sse.insert(
        0,
        "original_adddate",
        routed_sse.source_publication_value.astype("string"),
    )
    routed_sse.insert(0, "component_role", "SSE_FULL_HISTORY_AUTHORITATIVE")
    routed_szse = base.loc[base.exchange.eq("SZSE")].copy()
    original_szse_available = pd.to_datetime(routed_szse.available_at)
    _require(original_szse_available.notna().all(), "SZSE available_at is missing")
    routed_szse.insert(0, "causal_available_at", original_szse_available)
    routed_szse.insert(
        0,
        "original_publish_time",
        routed_szse.source_publication_value.astype("string"),
    )
    routed_szse.insert(
        0,
        "original_ssedate",
        pd.Series(pd.NA, index=routed_szse.index, dtype="string"),
    )
    routed_szse.insert(
        0,
        "original_adddate",
        pd.Series(pd.NA, index=routed_szse.index, dtype="string"),
    )
    routed_szse.insert(0, "component_role", "BASE_SZSE_AUTHORITATIVE")
    composite = pd.concat([routed_sse, routed_szse], ignore_index=True)
    _require(not composite.empty, "routed composite is empty")
    _require(
        not composite.duplicated("announcement_key").any(),
        "routed composite contains an announcement-key conflict",
    )
    composite = composite.sort_values(
        ["available_at", "symbol", "announcement_id", "announcement_key"],
        kind="mergesort",
    ).reset_index(drop=True)
    expected_columns = [
        "component_role",
        "original_adddate",
        "original_ssedate",
        "original_publish_time",
        "causal_available_at",
        *_IDENTITY_COLUMNS,
    ]
    _require(list(composite.columns) == expected_columns, "composite columns drifted")
    _require(
        pd.to_datetime(composite.causal_available_at)
        .ge(pd.to_datetime(composite.available_at))
        .all(),
        "causal_available_at precedes an original availability time",
    )
    _require(
        composite.loc[composite.exchange.eq("SSE"), "original_adddate"].notna().all()
        and composite.loc[composite.exchange.eq("SSE"), "original_ssedate"].notna().all()
        and composite.loc[
            composite.exchange.eq("SSE"), "original_publish_time"
        ].isna().all(),
        "SSE original ADDDATE/SSEDATE projection drifted",
    )
    _require(
        composite.loc[composite.exchange.eq("SZSE"), "original_publish_time"].notna().all()
        and composite.loc[composite.exchange.eq("SZSE"), "original_adddate"].isna().all()
        and composite.loc[composite.exchange.eq("SZSE"), "original_ssedate"].isna().all(),
        "SZSE original publishTime projection drifted",
    )
    return composite


def _frame_equal(expected: pd.DataFrame, actual: pd.DataFrame, label: str) -> None:
    _require(list(actual.columns) == list(expected.columns), f"{label} columns drifted")
    _require(len(actual) == len(expected), f"{label} row count drifted")
    try:
        pd.testing.assert_frame_equal(
            actual.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_dtype=True,
            check_exact=True,
        )
    except AssertionError as exc:
        raise V29R1AssetError(f"{label} content drifted: {exc}") from exc


def _available_at_audit(composite: pd.DataFrame) -> dict[str, Any]:
    original_available = pd.to_datetime(composite.available_at)
    causal_available = pd.to_datetime(composite.causal_available_at)
    result: dict[str, Any] = {
        "semantics": (
            "observed original and repaired causal availability; distinct from and does not "
            "replace official query-membership coverage"
        ),
        "original_available_at_min": pd.Timestamp(original_available.min()).isoformat(),
        "original_available_at_max": pd.Timestamp(original_available.max()).isoformat(),
        "causal_available_at_min": pd.Timestamp(causal_available.min()).isoformat(),
        "causal_available_at_max": pd.Timestamp(causal_available.max()).isoformat(),
        "rows_lifted_by_frozen_repair": int(causal_available.gt(original_available).sum()),
    }
    routes = {
        "SSE_FULL_HISTORY_AUTHORITATIVE": (SSE_QUERY_START, QUERY_END),
        "BASE_SZSE_AUTHORITATIVE": (BASE_QUERY_START, QUERY_END),
    }
    route_rows: dict[str, Any] = {}
    for role, (start, end) in routes.items():
        mask = composite.component_role.eq(role)
        original_values = original_available.loc[mask]
        values = causal_available.loc[mask]
        _require(not values.empty, f"no announcements for routed component {role}")
        start_ts = pd.Timestamp(start)
        end_exclusive = pd.Timestamp(end) + pd.Timedelta(days=1)
        route_rows[role] = {
            "rows": int(mask.sum()),
            "original_available_at_min": pd.Timestamp(original_values.min()).isoformat(),
            "original_available_at_max": pd.Timestamp(original_values.max()).isoformat(),
            "causal_available_at_min": pd.Timestamp(values.min()).isoformat(),
            "causal_available_at_max": pd.Timestamp(values.max()).isoformat(),
            "rows_lifted_by_frozen_repair": int(values.gt(original_values).sum()),
            "before_query_start_rows": int(values.lt(start_ts).sum()),
            "on_or_after_query_end_plus_one_day_rows": int(values.ge(end_exclusive).sum()),
        }
    result["routes"] = route_rows
    return result


def _collect_context(asset_root: Path, base_capture_root: Path) -> dict[str, Any]:
    root = _safe_asset_root(asset_root)
    sse_universe = _load_canonical_universe(
        root / SSE_UNIVERSE_NAME,
        SSE_UNIVERSE_NAME,
        expected_count=EXPECTED_SSE_SYMBOLS,
        suffix=".SH",
    )
    protocol = _validate_preregistration()
    base = _base_identity(base_capture_root, full_seal=True)
    derived = [symbol for symbol in base["symbols"] if symbol.endswith(".SH")]
    _require(sse_universe == derived, "SSE universe does not exactly equal the base .SH subset")
    historical = _validate_historical_capture(root, sse_universe)
    base_tables = _validate_base_capture_tables(base)
    overlap = _audit_sse_overlap(base_tables["announcements"], historical["announcements"])
    composite = _composite_frame(base_tables["announcements"], historical["announcements"])
    return {
        "root": root,
        "protocol": protocol,
        "base": base,
        "historical": historical,
        "sse_universe": sse_universe,
        "overlap": overlap,
        "composite": composite,
    }


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise V29R1AssetError(f"refusing to overwrite existing wrapper file: {path}") from exc


def _write_parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    _require(not path.exists(), f"refusing to overwrite existing wrapper file: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _component_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    base = context["base"]
    historical = context["historical"]
    return {
        "BASE_SZSE_AUTHORITATIVE": {
            "root": str(base["root"]),
            "snapshot_id": base["sealed"]["snapshot_id"],
            "asset_manifest_sha256": base["sealed"]["asset_manifest_sha256"],
            "query_membership_field": "publishTime",
            "query_start": BASE_QUERY_START,
            "query_end": QUERY_END,
            "symbols": EXPECTED_BASE_SYMBOLS - EXPECTED_SSE_SYMBOLS,
        },
        "SSE_FULL_HISTORY_AUTHORITATIVE": {
            "root": str(historical["root"]),
            "snapshot_id": historical["sealed"]["snapshot_id"],
            "asset_manifest_sha256": historical["sealed"]["asset_manifest_sha256"],
            "query_membership_field": "SSEDATE",
            "causal_availability_field": SSE_CAUSAL_AVAILABLE_AT_CONTRACT,
            "query_start": SSE_QUERY_START,
            "query_end": QUERY_END,
            "symbols": EXPECTED_SSE_SYMBOLS,
        },
    }


def _software_lineage() -> dict[str, Any]:
    paths = {
        "builder": Path(__file__).resolve(),
        "collector": Path(collector.__file__).resolve(),
        "sealer": Path(source_sealer.__file__).resolve(),
    }
    return {
        role: {
            "path": str(path),
            "sha256": _file_facts(path, f"{role} code")["sha256"],
        }
        for role, path in paths.items()
    }


def _capture_inventory_role(prefix: str, filename: str) -> str:
    _require(filename in _CAPTURE_INVENTORY_ROLES, f"unknown capture inventory file: {filename}")
    return f"{prefix}_{_CAPTURE_INVENTORY_ROLES[filename]}"


def _title_route_contract(context: Mapping[str, Any]) -> dict[str, Any]:
    base_root: Path = context["base"]["root"]
    historical_root: Path = context["historical"]["root"]
    return {
        "build_time_title_handling": {
            "nested_sealer_reparsed_and_validated_title_metadata_from_raw_pages": True,
            "wrapper_projected_or_copied_title_column": False,
            "wrapper_classified_title_column": False,
        },
        "required_access_order": [
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
        "causal_cutoff_column": "causal_available_at",
        "causal_cutoff_relation": "causal_available_at <= decision_at",
        "route_index_selection_fields": [
            "component_role",
            "snapshot_id",
            "announcement_key",
            "raw_record_sha256",
        ],
        "component_selection_key": "component_role",
        "nested_title_column": "title",
        "nested_join_keys": ["snapshot_id", "announcement_key"],
        "join_cardinality": "one_to_one",
        "unmatched_or_duplicate_policy": "FAIL_CLOSED_NO_SILENT_ROW_LOSS_OR_DEDUPLICATION",
        "post_join_exact_fields": [
            "raw_record_sha256",
            "symbol",
            "exchange",
            "source_publication_field",
            "source_publication_value",
            "source_query_date_field",
            "source_query_date",
        ],
        "roles": {
            "SSE_FULL_HISTORY_AUTHORITATIVE": {
                "nested_announcements_path": str(
                    (historical_root / "announcements.parquet").resolve(strict=True)
                ),
                "inventory_role": _capture_inventory_role(
                    "sse_full_history", "announcements.parquet"
                ),
                "snapshot_id": context["historical"]["sealed"]["snapshot_id"],
                "expected_exchange": "SSE",
            },
            "BASE_SZSE_AUTHORITATIVE": {
                "nested_announcements_path": str(
                    (base_root / "announcements.parquet").resolve(strict=True)
                ),
                "inventory_role": _capture_inventory_role("base", "announcements.parquet"),
                "snapshot_id": context["base"]["sealed"]["snapshot_id"],
                "expected_exchange": "SZSE",
            },
        },
    }


def _build_audit(context: Mapping[str, Any], sealed_at: str) -> dict[str, Any]:
    composite: pd.DataFrame = context["composite"]
    base_ann = context["base"]["root"] / "announcements.parquet"
    historical_ann = context["historical"]["root"] / "announcements.parquet"
    return {
        "audit_schema": "CY_BOUNDED_INPUT_ACTIVATION_AUDIT_V1",
        "audit_id": BUILDER_ID,
        "asset_id": ASSET_ID,
        "status": "PASS",
        "validated_at": sealed_at,
        "registered": False,
        "backtest_authorized": False,
        "authorization_state": "SEALED_BUT_FALSE_UNTIL_EXACT_REGISTRY_BINDING",
        "knowledge_time_contract": {
            "decision_field": "causal_available_at",
            "SSE": SSE_CAUSAL_AVAILABLE_AT_CONTRACT,
            "SZSE": SZSE_CAUSAL_AVAILABLE_AT_CONTRACT,
        },
        "protocol": {
            "experiment": EXPERIMENT,
            "preregistration_sha256": context["protocol"]["preregistration_facts"]["sha256"],
            "parent": PARENT_EXPERIMENT,
            "prior_v29_coverage_blocker_sha256": context["protocol"]["blocker_facts"][
                "sha256"
            ],
            "parent_hashes": {
                key: value["sha256"]
                for key, value in context["protocol"]["parent_facts"].items()
            },
            "outcome_files_access": "SHA256_STREAM_ONLY_CONTENT_NOT_PARSED",
        },
        "software_lineage": _software_lineage(),
        "source_routing": _component_summary(context),
        "title_route_contract": _title_route_contract(context),
        "query_coverage": {
            "SSE": {
                "start": SSE_QUERY_START,
                "end": QUERY_END,
                "field": "SSEDATE",
                "complete_from_exchange_inception": True,
            },
            "SZSE": {
                "start": BASE_QUERY_START,
                "end": QUERY_END,
                "field": "publishTime",
            },
            "no_routed_gap_or_overlap": True,
            "overlap_is_audit_only_not_a_second_route": True,
        },
        "causal_available_at_observation": _available_at_audit(composite),
        "sse_overlap_audit": dict(context["overlap"]),
        "counts": {
            "base_source_rows": int(
                pd.read_parquet(base_ann, columns=["announcement_key"]).shape[0]
            ),
            "sse_full_history_source_rows": int(
                pd.read_parquet(historical_ann, columns=["announcement_key"]).shape[0]
            ),
            "composite_rows": len(composite),
            "composite_unique_announcement_keys": int(composite.announcement_key.nunique()),
            "sse_symbols": EXPECTED_SSE_SYMBOLS,
            "szse_symbols": EXPECTED_BASE_SYMBOLS - EXPECTED_SSE_SYMBOLS,
        },
        "checks": {
            "base_nested_seal_fully_revalidated": True,
            "sse_nested_seal_fully_revalidated": True,
            "every_nested_raw_page_rehashed_and_reparsed": True,
            "both_nested_snapshot_ids_recomputed": True,
            "sse_universe_exact_parent_subset": True,
            "sse_query_domain_starts_at_exchange_inception": True,
            "sse_query_intervals_complete_without_gap_or_overlap": True,
            "szse_query_intervals_complete_without_gap_or_overlap": True,
            "overlap_key_sets_equal": True,
            "overlap_raw_record_and_normalized_identity_equal": True,
            "authoritative_routes_disjoint": True,
            "composite_announcement_keys_unique": True,
            "post_2021_query_partition_opened": False,
            "return_or_portfolio_table_opened": False,
            "nested_sealer_validated_title_metadata_from_raw_pages": True,
            "wrapper_projected_or_classified_title_column": False,
            "classification_or_strategy_run": False,
        },
        "limitations": [
            (
                "PIT-B current official metadata reconstruction; revision-vintage history "
                "is incomplete"
            ),
            (
                "the nested sealer validates title metadata while reparsing raw pages; "
                "the wrapper route index does not copy or classify titles"
            ),
            "effective available_at observations are not query-coverage boundaries",
            "the base SSE overlap is audit-only and contributes zero routed rows",
            "PASS does not register or authorize this asset for a backtest",
        ],
    }


def _inventory_entry(
    role: str,
    path: Path,
    *,
    root: Path,
    storage_scope: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    facts = _file_facts(path, role)
    rendered = path.relative_to(root).as_posix() if storage_scope == "ASSET_ROOT" else str(path)
    result = {
        "role": role,
        "storage_scope": storage_scope,
        "path": rendered,
        "sha256": facts["sha256"],
        "bytes": facts["bytes"],
    }
    if extra:
        result.update(extra)
    return result


def _build_inventory(
    context: Mapping[str, Any], audit_path: Path, composite_path: Path
) -> list[dict[str, Any]]:
    root: Path = context["root"]
    entries = [
        _inventory_entry(
            "sse_universe",
            root / SSE_UNIVERSE_NAME,
            root=root,
            storage_scope="ASSET_ROOT",
            extra={
                "derived_from_base_universe_sha256": EXPECTED_BASE_UNIVERSE_SHA256,
                "exact_parent_subset": True,
            },
        ),
        _inventory_entry(
            "announcement_route_index",
            composite_path,
            root=root,
            storage_scope="ASSET_ROOT",
        ),
        _inventory_entry(
            "activation_audit", audit_path, root=root, storage_scope="ASSET_ROOT"
        ),
        _inventory_entry(
            "v29r1_composite_builder_code",
            Path(__file__).resolve(),
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "exchange_announcement_collector_code",
            Path(collector.__file__).resolve(),
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "exchange_announcement_sealer_code",
            Path(source_sealer.__file__).resolve(),
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29r1_preregistration",
            PREREGISTRATION_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
        _inventory_entry(
            "v29_coverage_blocker",
            V29_BLOCKER_PATH,
            root=root,
            storage_scope="EXTERNAL_LINEAGE",
        ),
    ]
    for key, path in (
        ("v28r2_parent_runner", V28R2_RUNNER_PATH),
        ("v28r2_parent_stage_a", V28R2_STAGE_A_PATH),
        ("v28r2_parent_development_result_identity", V28R2_DEVELOPMENT_RESULT_PATH),
    ):
        entries.append(
            _inventory_entry(key, path, root=root, storage_scope="EXTERNAL_LINEAGE")
        )
    components = (
        ("base", context["base"]["root"], "EXTERNAL_LINEAGE", context["base"]["sealed"]),
        (
            "sse_full_history",
            context["historical"]["root"],
            "ASSET_ROOT",
            context["historical"]["sealed"],
        ),
    )
    for prefix, component_root, storage_scope, sealed in components:
        for name in _CAPTURE_FILES:
            extra = None
            if name == source_sealer.ASSET_MANIFEST_NAME:
                extra = {
                    "nested_snapshot_id": sealed["snapshot_id"],
                    "nested_files_verified": sealed["files_verified"],
                    "raw_page_inventory": "FULLY_REVALIDATED_BY_NESTED_SEAL_NOT_DUPLICATED",
                }
            entries.append(
                _inventory_entry(
                    _capture_inventory_role(prefix, name),
                    component_root / name,
                    root=root,
                    storage_scope=storage_scope,
                    extra=extra,
                )
            )
    return entries


def _build_manifest(
    context: Mapping[str, Any],
    audit: Mapping[str, Any],
    inventory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    inventory_rows = [dict(row) for row in inventory]
    return {
        "manifest_schema": "CY_IMMUTABLE_ASSET_MANIFEST_V1",
        "asset_id": ASSET_ID,
        "name": "V29R1 routed full-history issuer-risk title metadata composite",
        "status": "PASS",
        "physical_state": "MATERIALIZED",
        "immutable": True,
        "manifest_self_included": False,
        "registered": False,
        "backtest_authorized": False,
        "backtest_authorization_condition": (
            "false until the registry binds this exact manifest SHA-256 and a separate "
            "runner verifies its frozen V29R1 protocol"
        ),
        "sealed_at": audit["validated_at"],
        "builder_id": BUILDER_ID,
        "location": str(context["root"]),
        "protocol_binding": {
            "experiment": EXPERIMENT,
            "preregistration_sha256": context["protocol"]["preregistration_facts"]["sha256"],
            "parent": PARENT_EXPERIMENT,
        },
        "software_lineage": _software_lineage(),
        "source_routing": _component_summary(context),
        "title_route_contract": _title_route_contract(context),
        "query_coverage": dict(audit["query_coverage"]),
        "causal_available_at_observation": dict(audit["causal_available_at_observation"]),
        "pit": {
            "grade": "B",
            "revision_history_incomplete": True,
            "strict_archival_pit_ready": False,
            "knowledge_time": "causal_available_at only",
            "knowledge_time_contract": (
                f"SSE {SSE_CAUSAL_AVAILABLE_AT_CONTRACT}; "
                f"SZSE {SZSE_CAUSAL_AVAILABLE_AT_CONTRACT}"
            ),
        },
        "content": {
            "source_tables_title_metadata_only": True,
            "route_index_includes_title": False,
            "route_index_columns": [
                "component_role",
                "original_adddate",
                "original_ssedate",
                "original_publish_time",
                "causal_available_at",
                *_IDENTITY_COLUMNS,
            ],
            "sse_causal_available_at": SSE_CAUSAL_AVAILABLE_AT_CONTRACT,
            "szse_causal_available_at": SZSE_CAUSAL_AVAILABLE_AT_CONTRACT,
            "announcement_documents_included": False,
            "classification_included": False,
            "outcomes_included": False,
        },
        "limitations": list(audit["limitations"]),
        "inventory": inventory_rows,
        "inventory_sha256": collector.sha256_bytes(
            collector.canonical_json(inventory_rows).encode("utf-8")
        ),
    }


def build_asset(asset_root: Path, base_capture_root: Path) -> dict[str, Any]:
    """Build and seal the routed composite after validating both source seals."""

    root = _safe_asset_root(asset_root)
    _require_exact_top_level(root, _BUILD_TOP_LEVEL, "unsealed composite root")
    context = _collect_context(root, base_capture_root)
    composite_path = root / COMPOSITE_NAME
    audit_path = root / ACTIVATION_AUDIT_NAME
    manifest_path = root / ASSET_MANIFEST_NAME
    created: list[Path] = []
    try:
        _write_parquet_exclusive(composite_path, context["composite"])
        created.append(composite_path)
        sealed_at = datetime.now(UTC).isoformat()
        audit = _build_audit(context, sealed_at)
        _write_json_exclusive(audit_path, audit)
        created.append(audit_path)
        inventory = _build_inventory(context, audit_path, composite_path)
        manifest = _build_manifest(context, audit, inventory)
        _write_json_exclusive(manifest_path, manifest)
        created.append(manifest_path)
        for path in (root / SSE_UNIVERSE_NAME, composite_path, audit_path, manifest_path):
            path.chmod(0o444)
        _require_exact_top_level(root, _SEALED_TOP_LEVEL, "sealed composite root")
    except Exception:
        for path in reversed(created):
            if path.exists():
                path.chmod(0o644)
                path.unlink()
        raise
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "asset_manifest": str(manifest_path),
        "asset_manifest_sha256": collector.sha256_file(manifest_path),
        "composite_rows": len(context["composite"]),
        "base_snapshot_id": context["base"]["sealed"]["snapshot_id"],
        "sse_snapshot_id": context["historical"]["sealed"]["snapshot_id"],
        "registered": False,
        "backtest_authorized": False,
    }


def _require_read_only(path: Path, label: str) -> None:
    _require(stat.S_IMODE(path.stat().st_mode) & 0o222 == 0, f"{label} is not read-only")


def validate_asset(asset_root: Path, base_capture_root: Path) -> dict[str, Any]:
    """Revalidate every source page, the routing audit, and the immutable composite."""

    root = _safe_asset_root(asset_root)
    _require_exact_top_level(root, _SEALED_TOP_LEVEL, "sealed composite root")
    context = _collect_context(root, base_capture_root)
    composite_path = root / COMPOSITE_NAME
    audit_path = root / ACTIVATION_AUDIT_NAME
    manifest_path = root / ASSET_MANIFEST_NAME
    try:
        actual_composite = pd.read_parquet(composite_path)
    except Exception as exc:
        raise V29R1AssetError("unable to read sealed composite") from exc
    _frame_equal(context["composite"], actual_composite, "sealed composite")

    audit = _read_json_object(audit_path, ACTIVATION_AUDIT_NAME)
    sealed_at = _string(audit.get("validated_at"), "activation validated_at")
    try:
        parsed = pd.Timestamp(sealed_at)
    except (TypeError, ValueError) as exc:
        raise V29R1AssetError("activation validated_at is invalid") from exc
    _require(not pd.isna(parsed) and parsed.tzinfo is not None, "validated_at lacks timezone")
    expected_audit = _build_audit(context, sealed_at)
    _require(
        collector.canonical_json(audit) == collector.canonical_json(expected_audit),
        "activation audit content drifted",
    )
    inventory = _build_inventory(context, audit_path, composite_path)
    expected_manifest = _build_manifest(context, expected_audit, inventory)
    manifest = _read_json_object(manifest_path, ASSET_MANIFEST_NAME)
    _require(
        collector.canonical_json(manifest) == collector.canonical_json(expected_manifest),
        "asset manifest content or inventory drifted",
    )
    for path, label in (
        (root / SSE_UNIVERSE_NAME, SSE_UNIVERSE_NAME),
        (composite_path, COMPOSITE_NAME),
        (audit_path, ACTIVATION_AUDIT_NAME),
        (manifest_path, ASSET_MANIFEST_NAME),
    ):
        _require_read_only(path, label)
    return {
        "status": "PASS",
        "asset_id": ASSET_ID,
        "asset_manifest_sha256": collector.sha256_file(manifest_path),
        "composite_rows": len(actual_composite),
        "base_nested_files_verified": context["base"]["sealed"]["files_verified"],
        "sse_nested_files_verified": context["historical"]["sealed"]["files_verified"],
        "registered": False,
        "backtest_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare = subparsers.add_parser("prepare-universe")
    prepare.add_argument("--base-capture-root", type=Path, required=True)
    prepare.add_argument("--asset-root", type=Path, required=True)
    for mode in ("build", "validate"):
        child = subparsers.add_parser(mode)
        child.add_argument("--asset-root", type=Path, required=True)
        child.add_argument("--base-capture-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare-universe":
        result = prepare_sse_universe(args.base_capture_root, args.asset_root)
    elif args.mode == "build":
        result = build_asset(args.asset_root, args.base_capture_root)
    else:
        result = validate_asset(args.asset_root, args.base_capture_root)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
