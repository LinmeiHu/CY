#!/usr/bin/env python3
"""Build or validate the immutable routed CY-062 V29R2 roll-forward input.

The wrapper is title-free. It routes SSE rows only from an exchange-inception
SSEDATE capture and SZSE rows only from the sufficient publishTime-window
capture. Both nested seals and the complete route are revalidated before any
candidate title or outcome content may be opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    seal_exchange_issuer_announcements_v1 as sealer,
)

ROOT = Path(__file__).resolve().parents[3]
ASSET_ID = "CY-062"
SSE_ROLE = "SSE_FULL_HISTORY_AUTHORITATIVE"
SZSE_ROLE = "SZSE_WINDOW_AUTHORITATIVE"
SSE_START = "1990-12-19"
SZSE_START = "2021-10-18"
QUERY_END = "2026-08-03"
SIGNAL_START = "2022-01-01"
OUTCOME_END = "2026-09-04"
EXPECTED_PARENT_ROWS = 197
EXPECTED_PARENT_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_v28_family_rollforward_through_20260904_v1/"
    "v28r2/selected_signals_2022_2026.parquet"
)
EXPECTED_PARENT_OUTCOMES = EXPECTED_PARENT_SELECTED.with_name("outcomes_2022_2026.parquet")
EXPECTED_PARENT_DAILY = (
    EXPECTED_PARENT_SELECTED.parents[1] / "common/outcome_daily_2022_2026.parquet"
)
EXPECTED_PARENT_HASHES = {
    "selected": "825d5a0dc81a1c242d8e8fb250511f298876f8750ae7374d4657d49abe1fb918",
    "outcomes": "973e90149f04a2545443e5ec117c1326eafee849c27748f0739d53f71782ac62",
    "outcome_daily": "4a7f0351c19ca6584c5b686a3e90d833583a44910f96dc96f45f1d4db8fee93c",
}

V29R2_STEM = "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-FACT-COOLDOWN-V29R2"
V29R1_STEM = "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-ISSUER-INTEGRITY-COOLDOWN-V29R1"
RUNNER_PATH = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_rollforward.py"
)
CORRECTION_FREEZE = ROOT / (
    "research/market_behavior_os_v2/experiments/"
    f"{V29R2_STEM}_rollforward_2022_2026_calendar_coverage_correction_r1_freeze.json"
)

SOURCE_IDENTITY_COLUMNS = [
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
    "revision_history_complete",
    "strict_pit_eligible",
    "hard_valid",
]
ROUTE_COLUMNS = [*SOURCE_IDENTITY_COLUMNS, "component_role"]
EXPECTED_TOP_BEFORE = {
    "universe.parquet",
    "sse_full_universe.parquet",
    "source_capture",
    "sse_full_history_capture",
}
EXPECTED_TOP_AFTER = {
    *EXPECTED_TOP_BEFORE,
    "announcement_route_index.parquet",
    "activation_audit.json",
    "asset_manifest.json",
}
EXPECTED_CAPTURE_TOP = {
    "announcements.parquet",
    "asset_manifest.json",
    "audit.json",
    "audit_validation.json",
    "raw",
    "request_pages.parquet",
    "source_manifest.json",
}
INVENTORY_ROLE_ORDER = (
    "universe",
    "sse_full_universe",
    "szse_window_source_manifest",
    "szse_window_nested_seal",
    "sse_full_history_source_manifest",
    "sse_full_history_nested_seal",
    "announcement_route_index",
    "activation_audit",
    "asset_builder",
    "rollforward_runner",
    "calendar_coverage_correction_r1_freeze",
    "collector",
    "sealer",
    "issuer_fact_classifier",
    "v29r2_frozen_preregistration",
    "v29r2_development_result",
    "retired_v29r1_semantic_blocker",
    "parent_selected",
    "parent_outcomes",
    "parent_outcome_daily",
)


class AssetError(RuntimeError):
    """Fail closed on CY-062 coverage, identity, timing, or immutable-byte drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssetError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetError(f"invalid {label}: {path}") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def file_fact(role: str, path: Path, *, content_read: bool) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {role}: {path}")
    return {
        "role": role,
        "path": str(path),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
        "content_read_during_asset_build": content_read,
    }


def exact_top(root: Path, expected: set[str]) -> None:
    require(root.is_dir() and not root.is_symlink(), f"invalid asset root: {root}")
    actual: set[str] = set()
    for path in root.iterdir():
        require(not path.is_symlink(), f"asset root contains a symlink: {path.name}")
        actual.add(path.name)
    require(actual == expected, f"asset top-level drifted: {sorted(actual)}")


def write_json_exclusive(path: Path, value: Mapping[str, Any], *, read_only: bool) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise AssetError(f"refusing to overwrite {path}") from exc
    if read_only:
        path.chmod(0o444)


def write_parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    require(not path.exists(), f"refusing to overwrite {path}")
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        temporary.replace(path)
        path.chmod(0o444)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def load_universe(path: Path, label: str, *, suffix: str | None = None) -> list[str]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}")
    frame = pd.read_parquet(path)
    require(list(frame.columns) == ["symbol"], f"{label} columns drifted")
    values = [str(value).strip().upper() for value in frame.symbol]
    try:
        normalized = [collector.normalize_symbol(value) for value in values]
    except collector.CaptureError as exc:
        raise AssetError(f"{label} contains an invalid symbol") from exc
    require(
        values == normalized == sorted(set(normalized)) and bool(values),
        f"{label} is not nonempty, canonical, sorted and unique",
    )
    if suffix:
        require(all(value.endswith(suffix) for value in values), f"{label} exchange drifted")
    return values


def expected_query_map(
    symbols: Sequence[str], start: str, end: str
) -> dict[str, tuple[str, str, str, str]]:
    return {
        spec.query_id: (spec.exchange, spec.symbol, spec.start, spec.end)
        for spec in collector.build_query_specs(list(symbols), start, end)
    }


def validate_query_coverage(
    pages: pd.DataFrame,
    symbols: Sequence[str],
    *,
    start: str,
    end: str,
    label: str,
) -> None:
    columns = ["query_id", "exchange", "symbol", "query_start", "query_end"]
    unique = pages[columns].drop_duplicates()
    require(not unique.query_id.duplicated().any(), f"{label} query identity is ambiguous")
    actual = {
        str(row.query_id): (
            str(row.exchange),
            str(row.symbol),
            str(row.query_start),
            str(row.query_end),
        )
        for row in unique.itertuples(index=False)
    }
    require(actual == expected_query_map(symbols, start, end), f"{label} query map drifted")
    for symbol in symbols:
        intervals = sorted(
            (pd.Timestamp(row.query_start), pd.Timestamp(row.query_end))
            for row in unique.loc[unique.symbol.eq(symbol)].itertuples(index=False)
        )
        require(
            intervals
            and intervals[0][0] == pd.Timestamp(start)
            and intervals[-1][1] == pd.Timestamp(end),
            f"{label} boundary gap for {symbol}",
        )
        require(
            all(
                current[0] == previous[1] + pd.Timedelta(days=1)
                for previous, current in pairwise(intervals)
            ),
            f"{label} interval gap/overlap for {symbol}",
        )


def validate_capture(
    root: Path,
    universe_path: Path,
    *,
    start: str,
    end: str,
    exchanges: set[str],
    label: str,
) -> dict[str, Any]:
    require(root.is_dir() and not root.is_symlink(), f"missing or unsafe {label} root")
    exact_top(root, EXPECTED_CAPTURE_TOP)
    try:
        sealed = sealer.validate_asset(root)
    except sealer.SealError as exc:
        raise AssetError(f"{label} nested seal failed: {exc}") from exc
    manifest = read_json(root / "source_manifest.json", f"{label} source manifest")
    require(
        manifest.get("coverage") == {"start": start, "end": end}
        and manifest.get("backtest_authorized") is False
        and manifest.get("strict_archival_pit_ready") is False
        and manifest.get("metadata_only") is True,
        f"{label} coverage or PIT-B declarations drifted",
    )
    require(
        Path(str(manifest.get("universe_source"))).resolve() == universe_path.resolve(),
        f"{label} universe path drifted",
    )
    symbols = load_universe(universe_path, f"{label} universe")
    announcements = pd.read_parquet(root / "announcements.parquet", columns=SOURCE_IDENTITY_COLUMNS)
    pages = pd.read_parquet(
        root / "request_pages.parquet",
        columns=[
            "query_id",
            "exchange",
            "symbol",
            "query_start",
            "query_end",
            "page",
        ],
    )
    require(
        not announcements.empty
        and not announcements.announcement_key.duplicated().any()
        and announcements.snapshot_id.eq(sealed["snapshot_id"]).all()
        and set(announcements.exchange.astype(str)) <= exchanges
        and set(announcements.symbol.astype(str)) <= set(symbols)
        and announcements.hard_valid.eq(True).all()
        and announcements.revision_history_complete.eq(False).all()
        and announcements.strict_pit_eligible.eq(False).all(),
        f"{label} row identity/PIT-B invariants drifted",
    )
    validate_query_coverage(pages, symbols, start=start, end=end, label=label)
    record_counts = manifest.get("record_counts", {})
    counts = {
        "universe_symbols": len(symbols),
        "queries": int(pages.query_id.nunique()),
        "raw_pages": len(pages),
        "raw_record_appearances": int(record_counts.get("captured_raw_record_appearances")),
        "canonical_announcements": len(announcements),
    }
    require(
        counts["raw_record_appearances"] == len(announcements)
        and int(record_counts.get("canonical_announcements")) == len(announcements),
        f"{label} source counts drifted",
    )
    return {
        "root": root,
        "sealed": sealed,
        "manifest": manifest,
        "symbols": symbols,
        "announcements": announcements,
        "counts": counts,
    }


def compare_sse_overlap(window: pd.DataFrame, full: pd.DataFrame) -> dict[str, Any]:
    full_symbols = set(full.symbol.astype(str))
    window_sse = window.loc[
        window.exchange.eq("SSE") & window.symbol.astype(str).isin(full_symbols)
    ].drop(columns=["snapshot_id"])
    full_dates = pd.to_datetime(full.source_query_date, errors="raise")
    full_overlap = full.loc[full.exchange.eq("SSE") & full_dates.ge(pd.Timestamp(SZSE_START))].drop(
        columns=["snapshot_id"]
    )
    left = window_sse.sort_values("announcement_key").reset_index(drop=True)
    right = full_overlap.sort_values("announcement_key").reset_index(drop=True)
    require(
        set(left.announcement_key) == set(right.announcement_key),
        "overlapping SSE announcement-key sets differ between captures",
    )
    try:
        pd.testing.assert_frame_equal(left, right, check_dtype=True, check_exact=True)
    except AssertionError as exc:
        raise AssetError(f"overlapping SSE normalized/raw-record identity drifted: {exc}") from exc
    return {
        "window_keys": len(left),
        "full_history_keys": len(right),
        "key_sets_equal": True,
        "raw_record_and_normalized_identity_equal": True,
    }


def build_route(
    selected_symbols: set[str], window: pd.DataFrame, full: pd.DataFrame
) -> pd.DataFrame:
    sse_symbols = {symbol for symbol in selected_symbols if symbol.endswith(".SH")}
    szse_symbols = {symbol for symbol in selected_symbols if symbol.endswith(".SZ")}
    routed_sse = full.loc[
        full.exchange.eq("SSE") & full.symbol.astype(str).isin(sse_symbols)
    ].copy()
    routed_sse["component_role"] = SSE_ROLE
    routed_szse = window.loc[
        window.exchange.eq("SZSE") & window.symbol.astype(str).isin(szse_symbols)
    ].copy()
    routed_szse["component_role"] = SZSE_ROLE
    route = pd.concat([routed_sse, routed_szse], ignore_index=True)
    route = (
        route[ROUTE_COLUMNS]
        .sort_values(
            ["exchange", "symbol", "source_query_date", "announcement_key"], kind="mergesort"
        )
        .reset_index(drop=True)
    )
    require(
        not route.empty
        and not route.announcement_key.duplicated().any()
        and set(route.symbol.astype(str)) <= selected_symbols
        and route.loc[route.exchange.eq("SSE"), "component_role"].eq(SSE_ROLE).all()
        and route.loc[route.exchange.eq("SZSE"), "component_role"].eq(SZSE_ROLE).all(),
        "authoritative route identity drifted",
    )
    return route


def validate_correction(runner: Path) -> None:
    correction = read_json(CORRECTION_FREEZE, "calendar-coverage correction")
    require(
        correction.get("status") == "FROZEN_BEFORE_TITLE_CLASSIFICATION_AND_OUTCOME_JOIN"
        and correction.get("trigger") == "SSEDATE_MEMBERSHIP_ADDDATE_KNOWLEDGE_TIME_GAP"
        and correction.get("rule_or_threshold_changed") is False
        and correction.get("title_classification_had_started") is False
        and correction.get("v29r2_filtered_selector_outcome_join_had_started") is False
        and correction.get("pre_stage_schema_diagnostic", {}).get("parent_outcome_bytes_opened")
        is True
        and correction.get("pre_stage_schema_diagnostic", {}).get("schema_exact_join_executed")
        is True
        and correction.get("pre_stage_schema_diagnostic", {}).get("rows") == 180
        and correction.get("pre_stage_schema_diagnostic", {}).get(
            "performance_statistics_computed_or_viewed"
        )
        is False
        and correction.get("pre_stage_schema_diagnostic", {}).get(
            "selector_or_threshold_changed_after_read"
        )
        is False,
        "calendar-coverage correction semantics drifted",
    )
    expected = {
        "runner": runner,
        "asset_builder": Path(__file__).resolve(),
        "collector": Path(collector.__file__).resolve(),
        "sealer": Path(sealer.__file__).resolve(),
        "classifier": ROOT
        / "research/market_behavior_os_v2/scripts/classify_exchange_issuer_risk_events_v2.py",
    }
    software = correction.get("software_identity", {})
    require(set(software) == set(expected), "correction software-role set drifted")
    for role, path in expected.items():
        require(
            Path(str(software[role].get("path", ""))).resolve() == path
            and software[role].get("sha256") == sha256(path),
            f"correction software binding drifted: {role}",
        )


def validate_inputs(
    asset_root: Path,
    parent_selected: Path,
    parent_outcomes: Path,
    parent_daily: Path,
    runner: Path,
) -> dict[str, Any]:
    require(runner.resolve() == RUNNER_PATH.resolve(), "unexpected roll-forward runner path")
    expected_paths = {
        "selected": EXPECTED_PARENT_SELECTED,
        "outcomes": EXPECTED_PARENT_OUTCOMES,
        "outcome_daily": EXPECTED_PARENT_DAILY,
    }
    supplied_paths = {
        "selected": parent_selected,
        "outcomes": parent_outcomes,
        "outcome_daily": parent_daily,
    }
    for role, expected_path in expected_paths.items():
        supplied = supplied_paths[role]
        require(
            supplied.resolve() == expected_path.resolve()
            and sha256(supplied) == EXPECTED_PARENT_HASHES[role],
            f"frozen V28R2 parent path/hash drifted: {role}",
        )
    window = validate_capture(
        asset_root / "source_capture",
        asset_root / "universe.parquet",
        start=SZSE_START,
        end=QUERY_END,
        exchanges={"SSE", "SZSE"},
        label="window capture",
    )
    full = validate_capture(
        asset_root / "sse_full_history_capture",
        asset_root / "sse_full_universe.parquet",
        start=SSE_START,
        end=QUERY_END,
        exchanges={"SSE"},
        label="SSE full-history capture",
    )
    selected = pd.read_parquet(
        parent_selected, columns=["gap_id", "symbol", "signal_date", "signal_time"]
    )
    require(
        len(selected) == EXPECTED_PARENT_ROWS and not selected.gap_id.duplicated().any(),
        "parent selected identity must contain 197 unique signals",
    )
    signal_dates = pd.to_datetime(selected.signal_date, errors="raise").dt.normalize()
    require(signal_dates.between(SIGNAL_START, QUERY_END).all(), "parent signal boundary drifted")
    selected_symbols = set(selected.symbol.astype(str))
    require(
        selected_symbols <= set(window["symbols"]),
        "window capture universe does not cover every parent symbol",
    )
    expected_sse = sorted(symbol for symbol in selected_symbols if symbol.endswith(".SH"))
    require(
        full["symbols"] == expected_sse,
        "SSE full-history universe does not exactly equal parent SH symbols",
    )
    minimum_window = (signal_dates.min() - pd.Timedelta(days=120)).normalize()
    require(
        pd.Timestamp(SZSE_START) <= minimum_window,
        "SZSE publishTime capture starts after a candidate window",
    )
    overlap = compare_sse_overlap(window["announcements"], full["announcements"])
    route = build_route(selected_symbols, window["announcements"], full["announcements"])
    validate_correction(runner)
    return {
        "window": window,
        "full": full,
        "route": route,
        "overlap": overlap,
        "parent_signals": len(selected),
        "parent_symbols": len(selected_symbols),
        "parent_sse_symbols": len(expected_sse),
        "parent_szse_symbols": len(selected_symbols) - len(expected_sse),
        "minimum_signal_window_start": minimum_window.date().isoformat(),
        "maximum_signal_date": signal_dates.max().date().isoformat(),
        "facts": [
            file_fact("parent_selected", parent_selected, content_read=True),
            file_fact("parent_outcomes", parent_outcomes, content_read=False),
            file_fact("parent_outcome_daily", parent_daily, content_read=False),
        ],
    }


def build_audit(validated: Mapping[str, Any], now: str, route_sha: str) -> dict[str, Any]:
    return {
        "audit_schema": "CY_BOUNDED_INPUT_ACTIVATION_AUDIT_V1",
        "asset_id": ASSET_ID,
        "status": "PASS",
        "validated_at": now,
        "pit_grade": "B",
        "revision_history_incomplete": True,
        "strict_pit_a_claim": False,
        "title_metadata_only": True,
        "title_projected_or_classified_during_build": False,
        "parent_outcome_content_read": False,
        "parent_daily_content_read": False,
        "authoritative_routing": {"SSE": SSE_ROLE, "SZSE": SZSE_ROLE},
        "checks": {
            "both_nested_sources_recursively_validated": True,
            "all_raw_pages_rehashed_and_reparsed": True,
            "pagination_and_record_counts_conserve": True,
            "every_parent_symbol_is_covered": True,
            "sse_parent_symbols_have_full_ssedate_history": True,
            "szse_parent_windows_are_fully_covered": True,
            "overlapping_sse_normalized_and_raw_record_identity_equal": True,
            "calendar_coverage_correction_bound_before_title_or_outcome_open": True,
        },
        "route_rows": len(validated["route"]),
        "route_sha256": route_sha,
        "overlap": validated["overlap"],
        "parent_signals": validated["parent_signals"],
        "parent_symbols": validated["parent_symbols"],
        "parent_sse_symbols": validated["parent_sse_symbols"],
        "parent_szse_symbols": validated["parent_szse_symbols"],
        "minimum_signal_window_start": validated["minimum_signal_window_start"],
        "maximum_signal_date": validated["maximum_signal_date"],
        "source_snapshot_ids": {
            SSE_ROLE: validated["full"]["sealed"]["snapshot_id"],
            SZSE_ROLE: validated["window"]["sealed"]["snapshot_id"],
        },
        "source_counts": {
            SSE_ROLE: validated["full"]["counts"],
            SZSE_ROLE: validated["window"]["counts"],
        },
    }


def binding_inventory(
    asset_root: Path,
    validated: Mapping[str, Any],
    audit_path: Path,
    route_path: Path,
    runner: Path,
) -> list[dict[str, Any]]:
    paths = [
        ("universe", asset_root / "universe.parquet", True),
        ("sse_full_universe", asset_root / "sse_full_universe.parquet", True),
        ("szse_window_source_manifest", asset_root / "source_capture/source_manifest.json", True),
        ("szse_window_nested_seal", asset_root / "source_capture/asset_manifest.json", True),
        (
            "sse_full_history_source_manifest",
            asset_root / "sse_full_history_capture/source_manifest.json",
            True,
        ),
        (
            "sse_full_history_nested_seal",
            asset_root / "sse_full_history_capture/asset_manifest.json",
            True,
        ),
        ("announcement_route_index", route_path, True),
        ("activation_audit", audit_path, True),
        ("asset_builder", Path(__file__).resolve(), False),
        ("rollforward_runner", runner, False),
        ("calendar_coverage_correction_r1_freeze", CORRECTION_FREEZE, True),
        ("collector", Path(collector.__file__).resolve(), False),
        ("sealer", Path(sealer.__file__).resolve(), False),
        (
            "issuer_fact_classifier",
            ROOT
            / "research/market_behavior_os_v2/scripts/classify_exchange_issuer_risk_events_v2.py",
            False,
        ),
        (
            "v29r2_frozen_preregistration",
            ROOT / f"research/market_behavior_os_v2/experiments/{V29R2_STEM}_preregistration.json",
            False,
        ),
        (
            "v29r2_development_result",
            ROOT / f"research/market_behavior_os_v2/artifacts/{V29R2_STEM}_development_result.json",
            False,
        ),
        (
            "retired_v29r1_semantic_blocker",
            ROOT / f"research/market_behavior_os_v2/artifacts/{V29R1_STEM}_semantic_blocker.json",
            False,
        ),
    ]
    result = [
        file_fact(role, path, content_read=content_read) for role, path, content_read in paths
    ] + list(validated["facts"])
    require(
        tuple(item["role"] for item in result) == INVENTORY_ROLE_ORDER,
        "inventory role/order drifted",
    )
    return result


def build_manifest(
    asset_root: Path,
    validated: Mapping[str, Any],
    parent_selected: Path,
    inventory: list[dict[str, Any]],
    route_path: Path,
    now: str,
) -> dict[str, Any]:
    snapshots = {
        SSE_ROLE: validated["full"]["sealed"]["snapshot_id"],
        SZSE_ROLE: validated["window"]["sealed"]["snapshot_id"],
    }
    counts = {
        SSE_ROLE: validated["full"]["counts"],
        SZSE_ROLE: validated["window"]["counts"],
    }
    return {
        "manifest_schema": "CY_IMMUTABLE_ASSET_MANIFEST_V1",
        "asset_id": ASSET_ID,
        "status": "SEALED_PENDING_CENTRAL_REGISTRATION",
        "immutable": True,
        "manifest_self_included": False,
        "location": str(asset_root),
        "created_at": now,
        "pit": {
            "grade": "B",
            "current_enumeration": True,
            "revision_history_incomplete": True,
            "strict_archival_pit_ready": False,
            "knowledge_time": "SSE max(original ADDDATE,SSEDATE+1 day); SZSE validated publishTime",
        },
        "coverage": {
            SSE_ROLE: {
                "query_membership_field": "SSEDATE",
                "query_start": SSE_START,
                "query_end": QUERY_END,
            },
            SZSE_ROLE: {
                "query_membership_and_knowledge_field": "publishTime",
                "query_start": SZSE_START,
                "query_end": QUERY_END,
            },
            "signal_start": SIGNAL_START,
            "fully_mature_signal_end": QUERY_END,
            "outcome_data_end": OUTCOME_END,
        },
        "source_snapshot_ids": snapshots,
        "source_counts": counts,
        "parent_selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "route_index": {
            "path": str(route_path),
            "sha256": sha256(route_path),
            "rows": len(validated["route"]),
        },
        "inventory": inventory,
        "limitations": [
            (
                "official current-enumeration metadata is PIT-B; deletion/revision "
                "vintages are incomplete"
            ),
            "titles are metadata only and are not claims about full document contents",
            "2025-2026 are post-selection temporal observations, not pristine validation",
            "V29R1 is retired and this asset does not authorize its later-period use",
            "strict PIT-A, live trading, sizing and order generation are prohibited",
        ],
        "title_route_contract": {
            "route_index_has_title_column": False,
            "filter_and_persist_causal_window_keys_before_title_projection": True,
            "join_cardinality": "one_to_one",
            "unmatched_duplicate_or_missing": "FAIL_CLOSED",
            "roles": {
                SSE_ROLE: str(asset_root / "sse_full_history_capture/announcements.parquet"),
                SZSE_ROLE: str(asset_root / "source_capture/announcements.parquet"),
            },
        },
        "stage_boundary": {
            "stage_a_may_read_parent_selected_and_candidate_window_titles": True,
            "stage_a_must_persist_route_key_freeze_before_title_projection": True,
            "stage_a_may_parse_parent_outcomes_or_daily": False,
            "stage_b_requires_immutable_stage_a_freeze": True,
        },
    }


def build(
    asset_root: Path,
    parent_selected: Path,
    parent_outcomes: Path,
    parent_daily: Path,
    runner: Path,
) -> dict[str, Any]:
    exact_top(asset_root, EXPECTED_TOP_BEFORE)
    validated = validate_inputs(asset_root, parent_selected, parent_outcomes, parent_daily, runner)
    now = datetime.now(UTC).isoformat()
    route_path = asset_root / "announcement_route_index.parquet"
    write_parquet_exclusive(route_path, validated["route"])
    route_sha = sha256(route_path)
    audit = build_audit(validated, now, route_sha)
    audit_path = asset_root / "activation_audit.json"
    write_json_exclusive(audit_path, audit, read_only=True)
    inventory = binding_inventory(asset_root, validated, audit_path, route_path, runner)
    manifest = build_manifest(asset_root, validated, parent_selected, inventory, route_path, now)
    manifest_path = asset_root / "asset_manifest.json"
    write_json_exclusive(manifest_path, manifest, read_only=True)
    exact_top(asset_root, EXPECTED_TOP_AFTER)
    return {
        "asset_manifest": str(manifest_path),
        "asset_manifest_sha256": sha256(manifest_path),
        "activation_audit_sha256": sha256(audit_path),
        "route_sha256": route_sha,
        "route_rows": len(validated["route"]),
        "source_snapshot_ids": manifest["source_snapshot_ids"],
    }


def validate(asset_root: Path) -> dict[str, Any]:
    exact_top(asset_root, EXPECTED_TOP_AFTER)
    manifest_path = asset_root / "asset_manifest.json"
    manifest = read_json(manifest_path, "asset manifest")
    require(
        manifest_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
        "asset manifest is writable",
    )
    inventory_list = manifest.get("inventory", [])
    require(isinstance(inventory_list, list), "manifest inventory is missing")
    inventory = {item.get("role"): item for item in inventory_list}
    require(
        tuple(item.get("role") for item in inventory_list) == INVENTORY_ROLE_ORDER
        and len(inventory) == len(INVENTORY_ROLE_ORDER),
        "manifest inventory role/path set drifted",
    )
    for role, item in inventory.items():
        path = Path(str(item.get("path", "")))
        require(
            path.is_file() and not path.is_symlink() and sha256(path) == item.get("sha256"),
            f"bound file drifted: {role}",
        )
    parent_selected = Path(inventory["parent_selected"]["path"])
    parent_outcomes = Path(inventory["parent_outcomes"]["path"])
    parent_daily = Path(inventory["parent_outcome_daily"]["path"])
    runner = Path(inventory["rollforward_runner"]["path"])
    validated = validate_inputs(asset_root, parent_selected, parent_outcomes, parent_daily, runner)
    route_path = asset_root / "announcement_route_index.parquet"
    actual_route = pd.read_parquet(route_path)
    try:
        pd.testing.assert_frame_equal(
            actual_route, validated["route"], check_dtype=True, check_exact=True
        )
    except AssertionError as exc:
        raise AssetError(f"route index content drifted: {exc}") from exc
    audit_path = asset_root / "activation_audit.json"
    audit = read_json(audit_path, "activation audit")
    require(
        audit_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
        "activation audit is writable",
    )
    now = audit.get("validated_at")
    require(isinstance(now, str) and now == manifest.get("created_at"), "seal time drifted")
    expected_audit = build_audit(validated, now, sha256(route_path))
    require(audit == expected_audit, "activation audit semantic content drifted")
    expected_inventory = binding_inventory(asset_root, validated, audit_path, route_path, runner)
    expected_manifest = build_manifest(
        asset_root, validated, parent_selected, expected_inventory, route_path, now
    )
    require(manifest == expected_manifest, "asset manifest semantic content drifted")
    return {
        "valid": True,
        "manifest_sha256": sha256(manifest_path),
        "route_rows": len(actual_route),
        "source_snapshot_ids": manifest["source_snapshot_ids"],
        "source_counts": manifest["source_counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "validate"))
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--parent-selected", type=Path)
    parser.add_argument("--parent-outcomes", type=Path)
    parser.add_argument("--parent-daily", type=Path)
    parser.add_argument("--runner", type=Path)
    args = parser.parse_args()
    if args.mode == "build":
        require(
            all(
                value is not None
                for value in (
                    args.parent_selected,
                    args.parent_outcomes,
                    args.parent_daily,
                    args.runner,
                )
            ),
            "build requires all bound paths",
        )
        result = build(
            args.asset_root.resolve(),
            args.parent_selected.resolve(),
            args.parent_outcomes.resolve(),
            args.parent_daily.resolve(),
            args.runner.resolve(),
        )
    else:
        result = validate(args.asset_root.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
