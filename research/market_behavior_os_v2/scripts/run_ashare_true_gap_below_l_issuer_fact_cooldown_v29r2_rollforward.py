#!/usr/bin/env python3
"""Roll the frozen V29R2 issuer-fact veto through the current mature cohort.

This is a fixed-rule temporal report, not a new search.  Stage A uses only the
parent V28R2 selected identity and a registered official-announcement snapshot.
It freezes the vetoed cohort before Stage B is allowed to attach the already
computed A67/H20 outcomes and replay the unchanged K80 portfolio.

V29R1 is deliberately not implemented here: its immutable semantic blocker
forbids later-period use of that retired title taxonomy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_asset_v29r2 as asset_builder,
)
from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v2 as classifier,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay,
)
from research.market_behavior_os_v2.scripts import (
    seal_exchange_issuer_announcements_v1 as sealer,
)
from scripts import validate_data_registry as registry_validator

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "configs/data_asset_registry.json"
ASSET_ID = "CY-062"
AUTHORIZATION_ID = "CYQ-AUTH-ASHARE-ISSUER-FACT-V29R2-ROLLFORWARD-2022-2026-V1"
AUTHORIZATION_PURPOSE = "ASHARE_ISSUER_FACT_V29R2_ROLLFORWARD_2022_2026"
YEARS = (2022, 2023, 2024, 2025, 2026)
COOLING_DAYS = 120
DATA_END = pd.Timestamp("2026-09-04")
MATURE_SIGNAL_CUTOFF = pd.Timestamp("2026-08-03")
SEMANTIC_BLOCKER = ROOT / (
    "research/market_behavior_os_v2/artifacts/ASHARE-TRUE-GAP-BELOW-L-ORDERLY-"
    "DEMAND-ISSUER-INTEGRITY-COOLDOWN-V29R1_semantic_blocker.json"
)
EXPECTED_V29R1_BLOCKER_SHA256 = "df1654f143cf534c4101cd12671092e3dc61d475b439ff7ee75daca83cc5bd45"

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

SSE_COMPONENT_ROLE = "SSE_FULL_HISTORY_AUTHORITATIVE"
SZSE_COMPONENT_ROLE = "SZSE_WINDOW_AUTHORITATIVE"
CORRECTION_FREEZE_ROLE = "calendar_coverage_correction_r1_freeze"
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
AUTH_REQUIRED_ARTIFACT_ROLES = {
    "activation_audit",
    "asset_builder",
    "announcement_route_index",
    CORRECTION_FREEZE_ROLE,
    "collector",
    "sealer",
    "issuer_fact_classifier",
    "rollforward_runner",
    "parent_selected",
    "parent_outcomes",
    "parent_outcome_daily",
    "retired_v29r1_semantic_blocker",
    "v29r2_frozen_preregistration",
    "v29r2_development_result",
}
EXPECTED_AUTH_ALLOWED_USES = [
    (
        "classify only exact routed title rows inside frozen 2022-2026 parent-signal "
        "cooling windows after a persisted title-free route-key freeze"
    ),
    (
        "apply the unchanged V29R2 120-calendar-day issuer-fact cooldown and run one "
        "exact A67 H20 40-bp K80 roll-forward after Stage-A freeze"
    ),
]
EXPECTED_AUTH_BLOCKED_USES = [
    (
        "V29R1 fallback semantics, alternate taxonomy, cooldown tuning, threshold "
        "search, execution changes or rescue experiments"
    ),
    "unbound files, strict PIT-A claims, live trading, sizing or order generation",
    (
        "claiming 2025-2026 as pristine validation or treating missing unproven "
        "coverage as zero events"
    ),
]


class RollforwardError(RuntimeError):
    """Fail closed on coverage, registry, identity, timing, or replay drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RollforwardError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def value_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink(), f"missing or unsafe {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RollforwardError(f"invalid {label}: {path}") from exc
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RollforwardError(f"refusing to overwrite {path}") from exc
    path.chmod(0o444)


def write_parquet_exclusive(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), f"refusing to overwrite {path}")
    frame.to_parquet(path, index=False, compression="zstd")
    path.chmod(0o444)


def local_timestamp(value: object, label: str) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RollforwardError(f"invalid {label}: {value!r}") from exc
    require(not pd.isna(parsed), f"missing {label}")
    require(parsed.tzinfo is None, f"{label} must be exchange-local and timezone-naive")
    return parsed.tz_localize("Asia/Shanghai")


def derive_causal_available_at(routes: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the frozen V29R2 PIT-B knowledge time from preserved source fields."""

    require(list(routes.columns) == ROUTE_COLUMNS, "announcement route projection drifted")
    require(not routes.empty, "announcement route is empty; coverage is unknown")
    require(not routes.announcement_key.duplicated().any(), "duplicate announcement key")
    require(
        routes.hard_valid.map(lambda x: isinstance(x, (bool, np.bool_)) and bool(x)).all(),
        "announcement route contains hard-invalid rows",
    )
    require(routes.revision_history_complete.eq(False).all(), "PIT-B revision flag drifted")
    require(routes.strict_pit_eligible.eq(False).all(), "strict-PIT flag drifted")
    work = routes.copy()
    causal: list[pd.Timestamp] = []
    for row in work.itertuples(index=False):
        query_date = pd.Timestamp(row.source_query_date)
        require(
            query_date.tzinfo is None and query_date == query_date.normalize(),
            "source query date must be an exchange-local date",
        )
        require(int(row.query_year) == int(query_date.year), "query year/date mismatch")
        if row.exchange == "SSE":
            require(
                str(row.symbol).endswith(".SH")
                and row.component_role == SSE_COMPONENT_ROLE
                and row.source_publication_field == "ADDDATE"
                and row.source_query_date_field == "SSEDATE"
                and row.precision == "SOURCE_SECOND",
                "SSE source lineage drifted",
            )
            try:
                adddate = collector.exact_source_second(row.source_publication_value, "ADDDATE")
            except collector.CaptureError as exc:
                raise RollforwardError(str(exc)) from exc
            published = pd.Timestamp(row.published_at)
            original_available = pd.Timestamp(row.available_at)
            require(
                published == adddate and original_available == adddate,
                "SSE normalized source time differs from ADDDATE",
            )
            repaired = max(adddate, query_date + pd.Timedelta(days=1))
        elif row.exchange == "SZSE":
            require(
                str(row.symbol).endswith(".SZ")
                and row.component_role == SZSE_COMPONENT_ROLE
                and row.source_publication_field == "publishTime"
                and row.source_query_date_field == "publishTime",
                "SZSE source lineage drifted",
            )
            try:
                published, repaired, precision = collector.causal_times(
                    row.source_publication_value
                )
            except collector.CaptureError as exc:
                raise RollforwardError(str(exc)) from exc
            require(
                pd.Timestamp(row.published_at) == published
                and pd.Timestamp(row.available_at) == repaired
                and row.precision == precision
                and query_date == published.normalize(),
                "SZSE normalized source time differs from publishTime",
            )
        else:
            raise RollforwardError(f"unsupported exchange: {row.exchange!r}")
        causal.append(local_timestamp(repaired, "causal_available_at"))
    work["causal_available_at"] = causal
    return work


def select_window_routes(
    timed: pd.DataFrame, entries: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Select exact 120-day candidate windows before projecting any title column."""

    require(
        {"gap_id", "symbol", "signal_date", "signal_time"}.issubset(entries.columns),
        "parent selected identity lacks signal fields",
    )
    require(
        not entries.empty and not entries.gap_id.duplicated().any(),
        "parent selected identity is empty or duplicated",
    )
    route_symbols = timed.symbol.astype(str)
    mask = pd.Series(False, index=timed.index)
    minimum_window: pd.Timestamp | None = None
    latest_signal: pd.Timestamp | None = None
    for row in entries.itertuples(index=False):
        signal = local_timestamp(row.signal_time, "signal_time")
        start = signal - pd.Timedelta(days=COOLING_DAYS)
        mask |= (
            route_symbols.eq(str(row.symbol))
            & timed.causal_available_at.ge(start)
            & timed.causal_available_at.le(signal)
        )
        minimum_window = start if minimum_window is None else min(minimum_window, start)
        latest_signal = signal if latest_signal is None else max(latest_signal, signal)
    selected = timed.loc[mask].sort_values(
        ["causal_available_at", "symbol", "announcement_key"], kind="mergesort"
    )
    return selected, {
        "candidate_signals": len(entries),
        "route_rows_validated_without_titles": len(timed),
        "window_route_keys_selected_before_title_projection": len(selected),
        "minimum_window_start": minimum_window.isoformat() if minimum_window is not None else None,
        "latest_signal_time": latest_signal.isoformat() if latest_signal is not None else None,
    }


def attach_titles(asset_root: Path, selected_routes: pd.DataFrame) -> pd.DataFrame:
    """Project titles only for the already-frozen route-key set and prove identity."""

    keys = selected_routes.announcement_key.astype(str).tolist()
    if not keys:
        result = selected_routes.copy()
        result["title"] = pd.Series(dtype="string")
        return result
    title_columns = [*SOURCE_IDENTITY_COLUMNS, "title"]
    parts: list[pd.DataFrame] = []
    source_specs = (
        (
            SSE_COMPONENT_ROLE,
            "SSE",
            asset_root / "sse_full_history_capture/announcements.parquet",
        ),
        (
            SZSE_COMPONENT_ROLE,
            "SZSE",
            asset_root / "source_capture/announcements.parquet",
        ),
    )
    for role, exchange, source_path in source_specs:
        role_keys = (
            selected_routes.loc[selected_routes.component_role.eq(role), "announcement_key"]
            .astype(str)
            .tolist()
        )
        if not role_keys:
            continue
        part = pd.read_parquet(
            source_path,
            columns=title_columns,
            filters=[("announcement_key", "in", role_keys)],
        )
        require(part.exchange.eq(exchange).all(), f"{role} title source exchange drifted")
        part["component_role"] = role
        parts.append(part)
    require(bool(parts), "nonempty route keys produced no routed title source")
    titles = pd.concat(parts, ignore_index=True)
    require(
        len(titles) == len(keys) and not titles.announcement_key.duplicated().any(),
        "title projection does not conserve route identity",
    )
    indexed = titles.set_index("announcement_key", drop=False)
    require(set(indexed.index.astype(str)) == set(keys), "title projection key set drifted")
    ordered = indexed.loc[keys].reset_index(drop=True)
    for column in ROUTE_COLUMNS:
        left = selected_routes[column].reset_index(drop=True)
        right = ordered[column].reset_index(drop=True)
        if pd.api.types.is_datetime64_any_dtype(left) or pd.api.types.is_datetime64_any_dtype(
            right
        ):
            same = pd.to_datetime(left).equals(pd.to_datetime(right))
        else:
            same = left.equals(right)
        require(same, f"title source identity mismatch at {column}")
    require(
        ordered.title.map(lambda x: isinstance(x, str) and bool(x.strip())).all(),
        "title projection contains an empty title",
    )
    ordered["causal_available_at"] = selected_routes.causal_available_at.to_list()
    return ordered


def classify_titles(routes_with_titles: pd.DataFrame) -> pd.DataFrame:
    if routes_with_titles.empty:
        columns = [
            *routes_with_titles.columns,
            "action",
            "risk_family",
            "matched_rule",
            "classification_version",
        ]
        return pd.DataFrame(columns=columns)
    payload = routes_with_titles.rename(
        columns={
            "available_at": "original_collector_available_at",
            "published_at": "original_published_at",
            "precision": "original_precision",
            "causal_available_at": "available_at",
        }
    )
    try:
        return classifier.classify_exchange_announcements(payload)
    except classifier.RiskEventInputError as exc:
        raise RollforwardError(f"V29R2 title classification failed: {exc}") from exc


def apply_cooldown(entries: pd.DataFrame, classifications: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen inclusive 120-calendar-day OPEN-only veto."""

    events = classifications.loc[classifications.action.eq(classifier.ACTION_OPEN)].copy()
    if not events.empty:
        require(
            events.classification_version.eq(classifier.CLASSIFICATION_VERSION).all(),
            "classifier version drifted",
        )
        require(
            events.risk_family.isin(classifier.RISK_FAMILIES).all(), "unsupported OPEN risk family"
        )
        require(
            not events.duplicated(["announcement_key", "risk_family"]).any(),
            "duplicate OPEN announcement/family",
        )
    by_symbol = {
        str(symbol): group.sort_values(
            ["available_at", "announcement_key", "risk_family"], kind="mergesort"
        )
        for symbol, group in events.groupby("symbol", sort=False)
    }
    records: list[dict[str, Any]] = []
    for row in entries.itertuples(index=False):
        signal = local_timestamp(row.signal_time, "signal_time")
        start = signal - pd.Timedelta(days=COOLING_DAYS)
        candidates = by_symbol.get(str(row.symbol), events.iloc[:0])
        matched = candidates.loc[
            candidates.available_at.ge(start) & candidates.available_at.le(signal)
        ]
        payload = [
            {
                "announcement_key": str(event.announcement_key),
                "causal_available_at": pd.Timestamp(event.available_at).isoformat(),
                "risk_family": str(event.risk_family),
                "matched_rule": str(event.matched_rule),
            }
            for event in matched.itertuples(index=False)
        ]
        records.append(
            {
                "gap_id": str(row.gap_id),
                "v29r2_window_start_at": start,
                "v29r2_window_end_at": signal,
                "v29r2_open_transition_count": len(payload),
                "v29r2_open_events_json": canonical_json(payload),
                "v29r2_issuer_fact_cooldown_gate": not payload,
                "v29r2_rejection_reason": "" if not payload else "RECENT_EXPLICIT_OPEN_ISSUER_FACT",
                "v29r2_feature_uses_post_signal_information": False,
            }
        )
    result = entries.merge(pd.DataFrame(records), on="gap_id", validate="one_to_one")
    require(
        not result.v29r2_feature_uses_post_signal_information.any(),
        "post-signal information reached the selector",
    )
    return result


def detailed_yearly(
    selected: pd.DataFrame, accepted: pd.DataFrame, years: Sequence[int] = YEARS
) -> dict[str, Any]:
    """Return complete signal-year metrics without dropping empty years."""

    signal_year = pd.to_datetime(selected.signal_date, errors="raise").dt.year
    accepted_year = pd.to_datetime(accepted.signal_date, errors="raise").dt.year
    payload: dict[str, Any] = {}
    for year in years:
        signals = selected.loc[signal_year.eq(year)]
        trades = accepted.loc[accepted_year.eq(year)]
        completed_mask = (
            trades.completed.eq(True)
            if "completed" in trades
            else pd.Series(True, index=trades.index)
        )
        completed = trades.loc[completed_mask]
        returns = pd.to_numeric(completed.net_return, errors="raise")
        holding = pd.to_numeric(completed.holding_sessions, errors="raise")
        payload[str(year)] = {
            "signals_after_veto": len(signals),
            "unique_signal_dates": int(
                pd.to_datetime(signals.signal_date, errors="raise").dt.normalize().nunique()
            ),
            "executable_signals": int(signals.entry_status.eq("EXECUTABLE_ENTRY").sum()),
            "accepted": len(trades),
            "completed": len(completed),
            "mean_net": None if completed.empty else float(returns.mean()),
            "median_net": None if completed.empty else float(returns.median()),
            "win": None if completed.empty else float(returns.gt(0).mean()),
            "severe10": None if completed.empty else float(returns.le(-0.10).mean()),
            "mean_holding_sessions": None if completed.empty else float(holding.mean()),
            "median_holding_sessions": None if completed.empty else float(holding.median()),
            "exit_reasons": {
                str(key): int(value)
                for key, value in completed.exit_reason.value_counts().sort_index().items()
            },
        }
    return payload


def verify_registration(asset_root: Path) -> dict[str, Any]:
    registry = read_json(REGISTRY, "data registry")
    registry_errors = registry_validator.validate_registry(
        registry, verify_paths=True, verify_hashes=True
    )
    require(not registry_errors, f"central data registry validation failed: {registry_errors}")
    require(
        registry.get("global_gate", {}).get("free_causal_research_ready") is True
        and registry.get("global_gate", {}).get("backtest_authorized") is True,
        "central causal-research/backtest gate is closed",
    )
    assets = [x for x in registry.get("assets", []) if x.get("asset_id") == ASSET_ID]
    auths = [
        x
        for x in registry.get("bounded_authorizations", [])
        if x.get("authorization_id") == AUTHORIZATION_ID
    ]
    require(len(assets) == 1 and len(auths) == 1, "CY-062 registration/authorization missing")
    asset, auth = assets[0], auths[0]
    manifest_path = asset_root / "asset_manifest.json"
    manifest = read_json(manifest_path, "CY-062 manifest")
    lineage = asset.get("lineage", {})
    require(
        asset.get("status") == "RESEARCH_CONDITIONAL"
        and asset.get("physical_state") == "MATERIALIZED"
        and asset.get("pit_grade") == "B"
        and Path(str(asset.get("location"))) == asset_root
        and lineage.get("record_available_at") is True
        and lineage.get("record_snapshot_id") is True
        and lineage.get("immutable_manifest") is True
        and lineage.get("manifest_path") == str(manifest_path)
        and lineage.get("manifest_sha256") == sha256(manifest_path)
        and lineage.get("bounded_authorization_id") == AUTHORIZATION_ID
        and auth.get("asset_id") == ASSET_ID
        and auth.get("purpose") == AUTHORIZATION_PURPOSE,
        "CY-062 registry semantics drifted",
    )
    coverage = asset.get("coverage", {})
    require(
        coverage.get("sse_query_start") == "1990-12-19"
        and coverage.get("szse_query_start") == "2021-10-18"
        and coverage.get("query_end") == "2026-08-03"
        and coverage.get("signal_start") == "2022-01-01"
        and coverage.get("signal_end") == "2026-08-03"
        and coverage.get("outcome_end") == "2026-09-04"
        and coverage.get("route_rows") == manifest.get("route_index", {}).get("rows"),
        "CY-062 registered coverage drifted",
    )
    dependency_id = auth.get("dependency_asset_id")
    dependencies = [x for x in registry.get("assets", []) if x.get("asset_id") == dependency_id]
    scope = auth.get("scope", {})
    require(
        dependency_id == "CY-033"
        and auth.get("dependency_status") == "RESEARCH_CONDITIONAL"
        and len(dependencies) == 1
        and dependencies[0].get("status") == auth.get("dependency_status")
        and auth.get("current_survivor_fallback_allowed") is False
        and auth.get("record_level_available_at_available") is True
        and auth.get("event_classification_authorized") is True
        and auth.get("validation_outcome_join_authorized") is True
        and auth.get("portfolio_replay_authorized") is True
        and auth.get("strict_pit_a_authorized") is False
        and auth.get("live_trading_authorized") is False
        and auth.get("v29r1_fallback_authorized") is False
        and auth.get("post_2024_pristine_validation_claim_authorized") is False,
        "CY-062 bounded authorization flags/dependency drifted",
    )
    require(
        scope.get("project") == "research/market_behavior_os_v2"
        and scope.get("start") == "1990-12-19"
        and scope.get("end") == "2026-09-04"
        and scope.get("sse_query_start") == "1990-12-19"
        and scope.get("szse_query_start") == "2021-10-18"
        and scope.get("announcement_query_end") == "2026-08-03"
        and scope.get("signal_start") == "2022-01-01"
        and scope.get("signal_end") == "2026-08-03"
        and scope.get("outcome_end") == "2026-09-04",
        "CY-062 bounded authorization scope drifted",
    )
    require(
        auth.get("bound_manifest") == {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "CY-062 bound manifest drifted",
    )
    correction_fact = next(
        (
            item
            for item in manifest.get("inventory", [])
            if item.get("role") == CORRECTION_FREEZE_ROLE
        ),
        None,
    )
    require(
        correction_fact is not None
        and auth.get("bound_strategy")
        == {
            "path": correction_fact.get("path"),
            "sha256": correction_fact.get("sha256"),
        },
        "CY-062 bound strategy must be the calendar-coverage correction",
    )
    bound_protocol = auth.get("bound_protocol", {})
    require(
        bound_protocol.get("path") == correction_fact.get("path")
        and bound_protocol.get("sha256") == correction_fact.get("sha256")
        and bound_protocol.get("runner_path") == str(Path(__file__).resolve())
        and bound_protocol.get("runner_sha256") == sha256(Path(__file__).resolve()),
        "CY-062 bound protocol/runner drifted",
    )
    artifacts = auth.get("bound_artifacts", [])
    require(isinstance(artifacts, list), "CY-062 bounded artifacts are missing")
    fingerprints = {x.get("role"): x for x in artifacts}
    require(
        len(fingerprints) == len(artifacts) and set(fingerprints) == AUTH_REQUIRED_ARTIFACT_ROLES,
        "CY-062 required artifact fingerprints are missing or duplicated",
    )
    for role, item in fingerprints.items():
        path = Path(str(item.get("path", "")))
        require(
            path.is_file() and sha256(path) == item.get("sha256"),
            f"CY-062 bound artifact drifted: {role}",
        )
    require(
        auth.get("record_level_available_at_available") is True,
        "CY-062 lacks record-level available_at",
    )
    require(
        auth.get("allowed_uses") == EXPECTED_AUTH_ALLOWED_USES
        and auth.get("blocked_uses") == EXPECTED_AUTH_BLOCKED_USES
        and isinstance(auth.get("known_limitations"), list)
        and {
            "PIT-B",
            "revision",
            "2025-2026",
        }
        <= {
            token
            for text in auth["known_limitations"]
            for token in ("PIT-B", "revision", "2025-2026")
            if token in text
        },
        "CY-062 authorization use/limitation contract drifted",
    )
    return {"asset": asset, "authorization": auth, "fingerprints": fingerprints}


def verify_protocol_correction(manifest: Mapping[str, Any]) -> dict[str, Any]:
    inventory = {item.get("role"): item for item in manifest.get("inventory", [])}
    require(
        CORRECTION_FREEZE_ROLE in inventory,
        "CY-062 manifest does not bind the calendar-coverage correction",
    )
    require(
        "rollforward_freeze" not in inventory,
        "Stage A must bind only the calendar-coverage correction, not the superseded freeze",
    )
    fact = inventory[CORRECTION_FREEZE_ROLE]
    correction_path = Path(str(fact.get("path", "")))
    require(
        correction_path.is_file() and sha256(correction_path) == fact.get("sha256"),
        "calendar-coverage correction bytes drifted",
    )
    correction = read_json(correction_path, "calendar-coverage correction")
    require(
        correction.get("status") == "FROZEN_BEFORE_TITLE_CLASSIFICATION_AND_OUTCOME_JOIN"
        and correction.get("trigger") == "SSEDATE_MEMBERSHIP_ADDDATE_KNOWLEDGE_TIME_GAP"
        and correction.get("rule_or_threshold_changed") is False
        and correction.get("title_classification_had_started") is False
        and correction.get("v29r2_filtered_selector_outcome_join_had_started") is False,
        "calendar-coverage correction semantics drifted",
    )
    routing = correction.get("authoritative_routing", {})
    diagnostic = correction.get("pre_stage_schema_diagnostic", {})
    require(
        routing.get("SSE") == SSE_COMPONENT_ROLE
        and routing.get("SZSE") == SZSE_COMPONENT_ROLE
        and diagnostic.get("parent_outcome_bytes_opened") is True
        and diagnostic.get("schema_exact_join_executed") is True
        and diagnostic.get("rows") == 180
        and diagnostic.get("performance_statistics_computed_or_viewed") is False
        and diagnostic.get("selector_or_threshold_changed_after_read") is False,
        "calendar-coverage correction source routing drifted",
    )
    software = correction.get("software_identity", {})
    expected_paths = {
        "runner": Path(__file__).resolve(),
        "asset_builder": ROOT / "research/market_behavior_os_v2/scripts/"
        "build_exchange_issuer_fact_rollforward_asset_v29r2.py",
        "collector": ROOT / "research/market_behavior_os_v2/scripts/"
        "fetch_exchange_issuer_announcements_v1.py",
        "sealer": ROOT / "research/market_behavior_os_v2/scripts/"
        "seal_exchange_issuer_announcements_v1.py",
        "classifier": ROOT / "research/market_behavior_os_v2/scripts/"
        "classify_exchange_issuer_risk_events_v2.py",
    }
    require(set(software) == set(expected_paths), "correction software bindings drifted")
    for role, path in expected_paths.items():
        item = software[role]
        require(
            Path(str(item.get("path", ""))).resolve() == path
            and item.get("sha256") == sha256(path),
            f"calendar-coverage correction software drifted: {role}",
        )
    return {"path": str(correction_path), "sha256": sha256(correction_path)}


def verify_asset(asset_root: Path, parent_selected: Path) -> dict[str, Any]:
    registered = verify_registration(asset_root)
    try:
        builder_validation = asset_builder.validate(asset_root)
    except asset_builder.AssetError as exc:
        raise RollforwardError(f"CY-062 wrapper semantic validation failed: {exc}") from exc
    manifest = read_json(asset_root / "asset_manifest.json", "CY-062 manifest")
    require(
        manifest.get("asset_id") == ASSET_ID and manifest.get("immutable") is True,
        "CY-062 manifest identity/state drifted",
    )
    require(
        builder_validation.get("valid") is True
        and builder_validation.get("manifest_sha256") == sha256(asset_root / "asset_manifest.json")
        and builder_validation.get("route_rows") == manifest.get("route_index", {}).get("rows")
        and builder_validation.get("source_snapshot_ids") == manifest.get("source_snapshot_ids")
        and builder_validation.get("source_counts") == manifest.get("source_counts"),
        "CY-062 builder validation identity drifted",
    )
    require(
        manifest.get("parent_selected")
        == {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "CY-062 parent selected identity drifted",
    )
    inventory = {item.get("role"): item for item in manifest.get("inventory", [])}
    for role in AUTH_REQUIRED_ARTIFACT_ROLES:
        manifest_fact = inventory.get(role)
        registry_fact = registered["fingerprints"].get(role)
        require(
            manifest_fact is not None
            and registry_fact is not None
            and {
                "path": manifest_fact.get("path"),
                "sha256": manifest_fact.get("sha256"),
            }
            == {
                "path": registry_fact.get("path"),
                "sha256": registry_fact.get("sha256"),
            },
            f"CY-062 manifest/authorization fingerprint mismatch: {role}",
        )
    correction = verify_protocol_correction(manifest)
    validated_sources: dict[str, Any] = {}
    for role, relative in (
        (SZSE_COMPONENT_ROLE, "source_capture"),
        (SSE_COMPONENT_ROLE, "sse_full_history_capture"),
    ):
        try:
            validated_sources[role] = sealer.validate_asset(asset_root / relative)
        except sealer.SealError as exc:
            raise RollforwardError(f"CY-062 nested {role} validation failed: {exc}") from exc
    route_path = asset_root / "announcement_route_index.parquet"
    route = manifest.get("route_index", {})
    require(
        route
        == {
            "path": str(route_path),
            "sha256": sha256(route_path),
            "rows": int(pd.read_parquet(route_path, columns=["announcement_key"]).shape[0]),
        },
        "CY-062 route-index identity drifted",
    )
    return {
        "manifest_sha256": sha256(asset_root / "asset_manifest.json"),
        "builder_validation": builder_validation,
        "registered_asset_entry_sha256": value_sha256(registered["asset"]),
        "bounded_authorization_sha256": value_sha256(registered["authorization"]),
        "protocol_correction": correction,
        "source_snapshot_ids": {
            role: payload["snapshot_id"] for role, payload in validated_sources.items()
        },
        "source_counts": builder_validation["source_counts"],
        "route_index": route,
        "bound_artifacts": {
            role: {
                "path": str(registered["fingerprints"][role]["path"]),
                "sha256": str(registered["fingerprints"][role]["sha256"]),
            }
            for role in sorted(AUTH_REQUIRED_ARTIFACT_ROLES)
        },
    }


def verify_execution_contract(selected: pd.DataFrame) -> dict[str, Any]:
    require(
        replay.TARGET_FRACTION == replay.repair.v1.TARGET_FRACTION == 0.67
        and replay.TIME_STOP == replay.repair.v1.TIME_STOP == 20
        and replay.repair.v1.COST == 0.002
        and replay.PORTFOLIO_K == 80,
        "unchanged A67/H20/40bp/K80 software contract drifted",
    )
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")]
    require(not executable.empty, "selected cohort has no executable signal")
    signal_dates = pd.to_datetime(executable.signal_date, errors="raise")
    entry_dates = pd.to_datetime(executable.entry_date, errors="raise")
    signal_times = pd.to_datetime(executable.signal_time, errors="raise")
    entry_times = pd.to_datetime(executable.entry_time, errors="raise")
    require(
        entry_dates.gt(signal_dates).all()
        and entry_times.gt(signal_times).all()
        and executable.entry_at_or_before_signal.eq(False).all()
        and executable.buy_at_or_above_up_limit.eq(False).all(),
        "selected executable entries violate T+1/up-limit constraints",
    )
    return {
        "target": "A67",
        "time_stop_horizon": "H20 clock; legal execution can extend across non-valid sessions",
        "cost_per_side": 0.002,
        "round_trip_cost": 0.004,
        "portfolio_k_per_sleeve": 80,
        "t_plus_one_and_execution_flags_verified": True,
    }


def verify_exact_selected_outcome_join(
    selected: pd.DataFrame, outcomes: pd.DataFrame
) -> dict[str, Any]:
    required = {"gap_id", *EXACT_JOIN_FIELDS}
    for label, frame in (("selected", selected), ("outcomes", outcomes)):
        require(required.issubset(frame.columns), f"{label} exact join fields are missing")
        require(
            not frame.gap_id.duplicated().any() and frame.gap_id.notna().all(),
            f"{label} gap identity is duplicated or missing",
        )
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    joined = outcomes.loc[outcomes.gap_id.astype(str).isin(ids)].copy()
    require(
        len(ids) == len(executable) == len(joined) and set(joined.gap_id.astype(str)) == ids,
        "selected executable/outcome identities do not conserve one-to-one",
    )
    left = executable.set_index("gap_id").sort_index()
    right = joined.set_index("gap_id").sort_index()
    for field in EXACT_JOIN_FIELDS:
        require(
            left[field].notna().all()
            and right[field].notna().all()
            and left[field].equals(right[field]),
            f"exact selected/outcome mismatch at {field}",
        )
    return {
        "selected_executable_rows": len(executable),
        "joined_outcome_rows": len(joined),
        "exact_fields": list(EXACT_JOIN_FIELDS),
        "exact_fields_equal": True,
        "gap_identity_sha256": value_sha256(sorted(ids)),
    }


def verify_outcome_contract(selected: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, Any]:
    executable_ids = set(
        selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY"), "gap_id"].astype(str)
    )
    joined = outcomes.loc[outcomes.gap_id.astype(str).isin(executable_ids)].copy()
    required = {
        "alpha",
        "horizon",
        "stop",
        "target_coordinate",
        "L",
        "entry_coordinate_price",
        "exit_date",
        "exit_time",
        "exit_reason",
        "net_return",
        "holding_sessions",
    }
    require(required.issubset(joined.columns), "outcome contract fields are missing")
    alpha = pd.to_numeric(joined.alpha, errors="raise")
    horizon = pd.to_numeric(joined.horizon, errors="raise")
    expected_target = pd.to_numeric(joined.entry_coordinate_price, errors="raise") + 0.67 * (
        pd.to_numeric(joined.L, errors="raise")
        - pd.to_numeric(joined.entry_coordinate_price, errors="raise")
    )
    actual_target = pd.to_numeric(joined.target_coordinate, errors="raise")
    net = pd.to_numeric(joined.net_return, errors="raise")
    holding = pd.to_numeric(joined.holding_sessions, errors="raise")
    completed = (
        joined.exit_date.notna()
        & joined.exit_time.notna()
        & joined.exit_reason.notna()
        & joined.net_return.notna()
        & joined.holding_sessions.notna()
    )
    require(
        alpha.eq(0.67).all()
        and horizon.eq(20).all()
        and joined.stop.eq("NONE").all()
        and np.isclose(actual_target, expected_target, rtol=0.0, atol=1e-12).all()
        and completed.all()
        and joined.exit_date.notna().all()
        and joined.exit_time.notna().all()
        and joined.exit_reason.map(lambda value: isinstance(value, str) and bool(value)).all()
        and np.isfinite(net).all()
        and np.isfinite(holding).all()
        and holding.ge(0).all()
        and pd.to_datetime(joined.exit_date, errors="raise").dt.normalize().le(DATA_END).all(),
        "actual outcome rows violate A67/H20/NONE/completion/data-end contract",
    )
    return {
        "rows": len(joined),
        "alpha": 0.67,
        "horizon": 20,
        "stop": "NONE",
        "target_formula_verified": True,
        "completed_and_finite_net_verified": True,
        "maximum_exit_date": pd.Timestamp(joined.exit_date.max()).date().isoformat(),
    }


def verify_accepted_contract(accepted: pd.DataFrame) -> dict[str, Any]:
    required = {
        "alpha",
        "horizon",
        "stop",
        "exit_date",
        "exit_time",
        "exit_reason",
        "net_return",
        "holding_sessions",
    }
    require(not accepted.empty and required.issubset(accepted.columns), "accepted fields missing")
    inferred_complete = (
        accepted.exit_date.notna()
        & accepted.exit_time.notna()
        & accepted.exit_reason.notna()
        & accepted.net_return.notna()
        & accepted.holding_sessions.notna()
    )
    explicit_completed_present = "completed" in accepted
    if explicit_completed_present:
        require(
            accepted.completed.map(
                lambda value: isinstance(value, (bool, np.bool_)) and bool(value)
            ).all()
            and accepted.completed.eq(inferred_complete).all(),
            "accepted explicit completed flag is false or contradicts exit evidence",
        )
    net = pd.to_numeric(accepted.net_return, errors="raise")
    require(
        inferred_complete.all()
        and np.isfinite(net).all()
        and accepted.alpha.eq(0.67).all()
        and accepted.horizon.eq(20).all()
        and accepted.stop.eq("NONE").all()
        and pd.to_datetime(accepted.exit_date, errors="raise").dt.normalize().le(DATA_END).all(),
        "accepted replay rows violate A67/H20/NONE/completion/data-end contract",
    )
    return {
        "rows": len(accepted),
        "completion_evidence_all_true": True,
        "explicit_completed_column_present": explicit_completed_present,
        "explicit_completed_preserved": True,
    }


def run_stage_a(asset_root: Path, parent_selected: Path, output_root: Path) -> dict[str, Any]:
    require(not output_root.exists(), f"refusing non-pristine Stage-A output root: {output_root}")
    require(
        sha256(SEMANTIC_BLOCKER) == EXPECTED_V29R1_BLOCKER_SHA256, "V29R1 semantic blocker drifted"
    )
    identity = verify_asset(asset_root, parent_selected)
    entries = pd.read_parquet(parent_selected)
    signal_dates = pd.to_datetime(entries.signal_date, errors="raise").dt.normalize()
    require(signal_dates.dt.year.isin(YEARS).all(), "parent contains a signal outside 2022-2026")
    require(signal_dates.max() <= MATURE_SIGNAL_CUTOFF, "parent contains an immature signal")
    routes = pd.read_parquet(asset_root / "announcement_route_index.parquet")
    timed = derive_causal_available_at(routes)
    selected_routes, route_audit = select_window_routes(timed, entries)
    szse_coverage = read_json(
        asset_root / "source_capture/source_manifest.json", "SZSE window source manifest"
    )["coverage"]
    sse_coverage = read_json(
        asset_root / "sse_full_history_capture/source_manifest.json",
        "SSE full-history source manifest",
    )["coverage"]
    require(
        pd.Timestamp(szse_coverage["start"])
        <= pd.Timestamp(route_audit["minimum_window_start"]).tz_localize(None).normalize(),
        "SZSE announcement capture starts after a candidate window",
    )
    require(
        pd.Timestamp(szse_coverage["end"]) >= signal_dates.max(),
        "SZSE announcement capture ends before a candidate signal",
    )
    require(
        pd.Timestamp(sse_coverage["start"]) == pd.Timestamp("1990-12-19")
        and pd.Timestamp(sse_coverage["end"]) >= signal_dates.max(),
        "SSE source is not authoritative full history through every candidate signal",
    )
    stage = output_root / "stage_a"
    route_freeze_path = stage / "title_route_selection.parquet"
    pretitle_freeze_path = stage / "pretitle_route_freeze.json"
    title_free_route = selected_routes[[*ROUTE_COLUMNS, "causal_available_at"]].copy()
    write_parquet_exclusive(route_freeze_path, title_free_route)
    pretitle_freeze = {
        "stage": "TITLE_FREE_CAUSAL_WINDOW_KEYS_FROZEN_BEFORE_TITLE_PROJECTION",
        "asset_identity": identity,
        "parent_selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "route_audit": route_audit,
        "route_columns": list(title_free_route.columns),
        "route_rows": len(title_free_route),
        "route_sha256": sha256(route_freeze_path),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "titles_opened": False,
        "stage_a_process_outcome_content_opened": False,
    }
    write_json_exclusive(pretitle_freeze_path, pretitle_freeze)
    require(
        sha256(route_freeze_path) == pretitle_freeze["route_sha256"]
        and read_json(pretitle_freeze_path, "persisted pretitle freeze") == pretitle_freeze,
        "pretitle route freeze drifted before title access",
    )
    persisted_routes = pd.read_parquet(route_freeze_path)
    try:
        pd.testing.assert_frame_equal(
            persisted_routes, title_free_route, check_dtype=True, check_exact=True
        )
    except AssertionError as exc:
        raise RollforwardError(f"persisted pretitle route bytes differ: {exc}") from exc
    require(
        list(persisted_routes.columns) == [*ROUTE_COLUMNS, "causal_available_at"]
        and len(persisted_routes) == pretitle_freeze["route_rows"],
        "persisted pretitle route selection drifted before title access",
    )
    with_titles = attach_titles(asset_root, persisted_routes)
    classified = classify_titles(with_titles)
    audit = apply_cooldown(entries, classified)
    selected = audit.loc[audit.v29r2_issuer_fact_cooldown_gate].copy()
    rejected = audit.loc[~audit.v29r2_issuer_fact_cooldown_gate].copy()
    execution_contract = verify_execution_contract(selected)
    write_parquet_exclusive(stage / "classified_events.parquet", classified)
    write_parquet_exclusive(stage / "selector_audit.parquet", audit)
    write_parquet_exclusive(stage / "selected_entries.parquet", selected)
    write_parquet_exclusive(stage / "rejected_entries.parquet", rejected)
    freeze = {
        "stage": "V29R2_FIXED_RULE_ROLLFORWARD_COHORT_FROZEN_BEFORE_STAGE_B_OUTCOME_JOIN",
        "asset_identity": identity,
        "parent_selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "route_audit": route_audit,
        "pretitle_route_freeze": {
            "path": str(pretitle_freeze_path),
            "sha256": sha256(pretitle_freeze_path),
        },
        "parent_signals": len(entries),
        "selected_signals": len(selected),
        "rejected_signals": len(rejected),
        "selected_by_signal_year": {
            str(year): int(pd.to_datetime(selected.signal_date).dt.year.eq(year).sum())
            for year in YEARS
        },
        "classified_open_by_family": {
            str(key): int(value)
            for key, value in classified.loc[
                classified.action.eq(classifier.ACTION_OPEN), "risk_family"
            ]
            .value_counts()
            .sort_index()
            .items()
        },
        "execution_contract": execution_contract,
        "hashes": {
            "classified_events": sha256(stage / "classified_events.parquet"),
            "title_route_selection": sha256(route_freeze_path),
            "selector_audit": sha256(stage / "selector_audit.parquet"),
            "selected_entries": sha256(stage / "selected_entries.parquet"),
            "rejected_entries": sha256(stage / "rejected_entries.parquet"),
        },
        "stage_a_process_outcome_content_opened": False,
        "rule_changed": False,
        "v29r1_later_period_status": "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
    }
    write_json_exclusive(stage / "freeze.json", freeze)
    return freeze


def verify_stage_a(asset_root: Path, parent_selected: Path, output_root: Path) -> dict[str, Any]:
    identity = verify_asset(asset_root, parent_selected)
    stage = output_root / "stage_a"
    freeze_path = stage / "freeze.json"
    freeze = read_json(freeze_path, "Stage-A freeze")
    require(
        freeze.get("stage")
        == "V29R2_FIXED_RULE_ROLLFORWARD_COHORT_FROZEN_BEFORE_STAGE_B_OUTCOME_JOIN"
        and freeze.get("stage_a_process_outcome_content_opened") is False
        and freeze.get("rule_changed") is False
        and freeze.get("v29r1_later_period_status") == "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
        "Stage-A freeze status drifted",
    )
    require(freeze.get("asset_identity") == identity, "Stage-A frozen asset identity drifted")
    require(
        freeze.get("parent_selected")
        == {"path": str(parent_selected), "sha256": sha256(parent_selected)},
        "Stage-A parent selected identity drifted",
    )
    paths = {
        "classified_events": stage / "classified_events.parquet",
        "title_route_selection": stage / "title_route_selection.parquet",
        "selector_audit": stage / "selector_audit.parquet",
        "selected_entries": stage / "selected_entries.parquet",
        "rejected_entries": stage / "rejected_entries.parquet",
    }
    for role, path in paths.items():
        require(
            path.is_file() and freeze.get("hashes", {}).get(role) == sha256(path),
            f"Stage-A artifact drifted: {role}",
        )
        require(
            path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"Stage-A artifact is writable: {role}",
        )
    classified = pd.read_parquet(paths["classified_events"])
    title_routes = pd.read_parquet(paths["title_route_selection"])
    audit = pd.read_parquet(paths["selector_audit"])
    selected = pd.read_parquet(paths["selected_entries"])
    rejected = pd.read_parquet(paths["rejected_entries"])
    parent = pd.read_parquet(parent_selected)
    parent_ids = set(parent.gap_id.astype(str))
    audit_ids = set(audit.gap_id.astype(str))
    selected_ids = set(selected.gap_id.astype(str))
    rejected_ids = set(rejected.gap_id.astype(str))
    require(
        len(audit) == len(parent) == freeze.get("parent_signals")
        and audit_ids == parent_ids
        and not selected_ids.intersection(rejected_ids)
        and selected_ids.union(rejected_ids) == parent_ids
        and selected.v29r2_issuer_fact_cooldown_gate.eq(True).all()
        and rejected.v29r2_issuer_fact_cooldown_gate.eq(False).all(),
        "Stage-A selected/rejected partition drifted",
    )
    require(
        len(selected) == freeze.get("selected_signals")
        and len(rejected) == freeze.get("rejected_signals")
        and freeze.get("selected_by_signal_year")
        == {
            str(year): int(pd.to_datetime(selected.signal_date).dt.year.eq(year).sum())
            for year in YEARS
        },
        "Stage-A selector counts drifted",
    )
    pretitle_fact = freeze.get("pretitle_route_freeze", {})
    pretitle_path = stage / "pretitle_route_freeze.json"
    pretitle = read_json(pretitle_path, "pretitle route freeze")
    require(
        pretitle_fact == {"path": str(pretitle_path), "sha256": sha256(pretitle_path)}
        and pretitle.get("stage") == "TITLE_FREE_CAUSAL_WINDOW_KEYS_FROZEN_BEFORE_TITLE_PROJECTION"
        and pretitle.get("asset_identity") == identity
        and pretitle.get("route_sha256") == sha256(paths["title_route_selection"])
        and pretitle.get("route_rows") == len(title_routes)
        and pretitle.get("route_columns") == list(title_routes.columns)
        and pretitle.get("titles_opened") is False
        and pretitle.get("stage_a_process_outcome_content_opened") is False
        and list(title_routes.columns) == [*ROUTE_COLUMNS, "causal_available_at"],
        "pretitle persisted route-key freeze drifted",
    )
    current_routes = pd.read_parquet(asset_root / "announcement_route_index.parquet")
    current_timed = derive_causal_available_at(current_routes)
    current_selection, current_route_audit = select_window_routes(current_timed, parent)
    current_title_free = current_selection[[*ROUTE_COLUMNS, "causal_available_at"]]
    try:
        pd.testing.assert_frame_equal(
            title_routes, current_title_free, check_dtype=True, check_exact=True
        )
    except AssertionError as exc:
        raise RollforwardError(f"Stage-A route selection no longer reproduces: {exc}") from exc
    require(
        pretitle.get("route_audit") == current_route_audit
        and freeze.get("route_audit") == current_route_audit,
        "Stage-A route-selection audit no longer reproduces",
    )
    for frozen_json in (pretitle_path, freeze_path):
        require(
            frozen_json.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0,
            f"Stage-A freeze is writable: {frozen_json.name}",
        )
    require(
        classified.empty
        or pd.to_datetime(classified.available_at, errors="raise")
        .le(
            pd.Timestamp(MATURE_SIGNAL_CUTOFF, tz="Asia/Shanghai")
            + pd.Timedelta(hours=23, minutes=59, seconds=59)
        )
        .all(),
        "Stage-A classifications exceed the mature signal boundary",
    )
    execution_contract = verify_execution_contract(selected)
    require(
        freeze.get("execution_contract") == execution_contract,
        "Stage-A execution contract drifted",
    )
    return {
        "verified": True,
        "stage_a_freeze_sha256": sha256(freeze_path),
        "asset_identity": identity,
        "hashes": freeze["hashes"],
        "execution_contract": execution_contract,
    }


@contextmanager
def replay_context(
    selected_path: Path, outcomes_path: Path, daily_path: Path, lane_root: Path
) -> Iterator[None]:
    old_source = replay.source_paths
    old_selected = replay.selected_entries_path
    old_lane = replay.lane_root
    try:
        replay.source_paths = lambda _label: {
            "root": outcomes_path.parent,
            "outcomes": outcomes_path,
            "outcome_daily": daily_path,
        }
        replay.selected_entries_path = lambda _label: selected_path
        replay.lane_root = lambda _label: lane_root
        yield
    finally:
        replay.source_paths = old_source
        replay.selected_entries_path = old_selected
        replay.lane_root = old_lane


def run_stage_b(
    asset_root: Path,
    parent_selected: Path,
    parent_outcomes: Path,
    parent_daily: Path,
    output_root: Path,
) -> dict[str, Any]:
    require(
        not (output_root / "stage_b").exists() and not (output_root / "result.json").exists(),
        "refusing non-pristine Stage-B output surface",
    )
    verification = verify_stage_a(asset_root, parent_selected, output_root)
    identity = verification["asset_identity"]
    for role, path in (
        ("parent_selected", parent_selected),
        ("parent_outcomes", parent_outcomes),
        ("parent_outcome_daily", parent_daily),
    ):
        fact = identity["bound_artifacts"][role]
        require(
            Path(fact["path"]).resolve() == path.resolve() and fact["sha256"] == sha256(path),
            f"CLI {role} does not equal the manifest/authorization fingerprint",
        )
    freeze_path = output_root / "stage_a/freeze.json"
    freeze = read_json(freeze_path, "Stage-A freeze")
    require(
        freeze.get("stage_a_process_outcome_content_opened") is False,
        "Stage-A outcome boundary drifted",
    )
    selected_path = output_root / "stage_a/selected_entries.parquet"
    require(
        freeze.get("hashes", {}).get("selected_entries") == sha256(selected_path),
        "Stage-A selected cohort drifted",
    )
    selected = pd.read_parquet(selected_path)
    outcomes = pd.read_parquet(parent_outcomes)
    join_audit = verify_exact_selected_outcome_join(selected, outcomes)
    outcome_contract = verify_outcome_contract(selected, outcomes)
    execution_contract = verify_execution_contract(selected)
    bound_source_hashes = {
        "parent_outcomes": sha256(parent_outcomes),
        "parent_outcome_daily": sha256(parent_daily),
    }
    lane_root = output_root / "stage_b/lane"
    with replay_context(selected_path, parent_outcomes, parent_daily, lane_root):
        lane = replay.run_lane("ROLLFORWARD", YEARS)
    portfolio_audit = lane.get("portfolio", {}).get("audit", {})
    require(
        portfolio_audit.get("max_k_violation_count") == 0
        and portfolio_audit.get("negative_cash_or_leverage_count") == 0,
        "K80 portfolio replay violates capacity or cash/leverage invariants",
    )
    require(
        bound_source_hashes
        == {
            "parent_outcomes": sha256(parent_outcomes),
            "parent_outcome_daily": sha256(parent_daily),
        },
        "parent outcome sources drifted during unchanged replay",
    )
    post_replay_verification = verify_stage_a(asset_root, parent_selected, output_root)
    require(
        verification["stage_a_freeze_sha256"] == post_replay_verification["stage_a_freeze_sha256"]
        and verification["hashes"] == post_replay_verification["hashes"],
        "Stage-A bytes drifted during Stage B",
    )
    accepted_path = lane_root / "portfolio_accepted.parquet"
    accepted = pd.read_parquet(accepted_path)
    accepted_contract = verify_accepted_contract(accepted)
    yearly = detailed_yearly(selected, accepted)
    result = {
        "strategy": "V29R2",
        "status": "COMPLETE_PIT_B_FIXED_RULE_ROLLFORWARD",
        "scientific_periods": {
            "2022-2024": "DEPENDENT_FIXED_RULE_VALIDATION_NOT_PRISTINE_OOS",
            "2025-2026": "POST_SELECTION_TEMPORAL_DIAGNOSTIC",
        },
        "data_end": DATA_END.date().isoformat(),
        "fully_mature_signal_cutoff": MATURE_SIGNAL_CUTOFF.date().isoformat(),
        "evidence_grade": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        "asset_identity": identity,
        "stage_a_verification": verification,
        "stage_a_freeze": {"path": str(freeze_path), "sha256": sha256(freeze_path)},
        "exact_join_audit": join_audit,
        "outcome_contract": outcome_contract,
        "accepted_contract": accepted_contract,
        "execution_contract": execution_contract,
        "portfolio_audit": portfolio_audit,
        "parent_sources": {
            "selected": {"path": str(parent_selected), "sha256": sha256(parent_selected)},
            "outcomes": {"path": str(parent_outcomes), "sha256": sha256(parent_outcomes)},
            "outcome_daily": {"path": str(parent_daily), "sha256": sha256(parent_daily)},
        },
        "yearly_by_signal_year": yearly,
        "lane": lane,
        "output_hashes": {
            "portfolio_accepted": sha256(accepted_path),
            "filtered_outcomes": sha256(lane_root / "outcomes.parquet"),
            "portfolio_nav": sha256(lane_root / "portfolio_nav.parquet"),
        },
        "rule_changed": False,
        "v29r1_later_period_status": "BLOCKED_BY_IMMUTABLE_SEMANTIC_INVALIDITY",
    }
    write_json_exclusive(output_root / "result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage-a", "stage-b"))
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--parent-selected", type=Path, required=True)
    parser.add_argument("--parent-outcomes", type=Path)
    parser.add_argument("--parent-daily", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "stage-a":
        result = run_stage_a(args.asset_root, args.parent_selected, args.output_root)
    else:
        require(
            args.parent_outcomes is not None and args.parent_daily is not None,
            "Stage B requires parent outcomes and daily paths",
        )
        result = run_stage_b(
            args.asset_root,
            args.parent_selected,
            args.parent_outcomes,
            args.parent_daily,
            args.output_root,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
