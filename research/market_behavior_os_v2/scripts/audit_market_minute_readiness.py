#!/usr/bin/env python3
"""Audit a deterministic strategy-independent five-day minute sample."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
LEGACY_SCRIPTS = ROOT / "research/chinext_v1/research_os_v2/scripts"
if str(LEGACY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LEGACY_SCRIPTS))

from audit_five_day_minute_data import (  # noqa: E402
    DESCRIPTOR_COLUMNS,
    EXPECTED_TIMES,
    aggregate_5m,
    descriptor_diagnostics,
    inventory_files,
    read_filtered,
    session_descriptors,
)


SPEC_PATH = PROGRAM / "experiments/AUDIT-MKT-MIN-001_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/AUDIT-MKT-MIN-001_sample.csv"
SESSION_PATH = PROGRAM / "artifacts/AUDIT-MKT-MIN-001_session_audit.csv"
DESCRIPTOR_PATH = PROGRAM / "artifacts/AUDIT-MKT-MIN-001_daily_descriptors.csv"
RESULT_PATH = PROGRAM / "artifacts/AUDIT-MKT-MIN-001_result.json"
REPORT_PATH = PROGRAM / "reports/AUDIT-MKT-MIN-001_market_minute_readiness.md"


class MarketMinuteAuditError(RuntimeError):
    """Fail-closed market-minute audit error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(path: str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _load_and_verify_spec() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_MARKET_MINUTE_ACCESS" or spec["outcome_access"] is not False:
        raise MarketMinuteAuditError("minute audit is not frozen outcome-blind")
    for role, binding in spec["input_bindings"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise MarketMinuteAuditError(f"bound input identity mismatch: {role}")
    return spec


def deterministic_order(anchor: pd.Timestamp, view: str, symbol: str) -> str:
    payload = f"AUDIT-MKT-MIN-001|{anchor.strftime('%Y-%m-%d')}|{view}|{symbol}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _calendar_and_anchors(spec: dict) -> tuple[pd.DataFrame, dict[int, pd.Timestamp]]:
    calendar_path = _resolve(spec["input_bindings"]["calendar"]["path"])
    calendar = pq.read_table(calendar_path, columns=["trade_date"]).to_pandas()
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"], errors="raise")
    calendar = calendar.drop_duplicates().sort_values("trade_date").reset_index(drop=True)
    anchors: dict[int, pd.Timestamp] = {}
    for year in spec["sample"]["years"]:
        cutoff = pd.Timestamp(f"{year}-06-15")
        eligible = calendar.loc[(calendar.trade_date.dt.year == year) & (calendar.trade_date >= cutoff)]
        if eligible.empty:
            raise MarketMinuteAuditError(f"no anchor session for {year}")
        anchors[int(year)] = pd.Timestamp(eligible.trade_date.iloc[0])
    return calendar, anchors


def _verify_cy006_files(spec: dict) -> list[Path]:
    manifest_path = _resolve(spec["input_bindings"]["cy006_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(manifest["root"])
    indexed = {item["path"]: item for item in manifest["files"]}
    paths: list[Path] = []
    for year in spec["sample"]["years"]:
        relative = f"partition_year={year}/data_0.parquet"
        item = indexed.get(relative)
        if item is None:
            raise MarketMinuteAuditError(f"CY-006 partition missing: {relative}")
        path = root / relative
        if path.stat().st_size != int(item["size"]) or sha256_file(path) != item["sha256"]:
            raise MarketMinuteAuditError(f"CY-006 partition identity mismatch: {relative}")
        paths.append(path)
    return paths


def build_sample(spec: dict, cy006_paths: list[Path]) -> tuple[pd.DataFrame, dict[int, pd.Timestamp]]:
    calendar, anchors = _calendar_and_anchors(spec)
    index_by_date = {pd.Timestamp(value): index for index, value in enumerate(calendar.trade_date)}
    required_dates: dict[int, list[pd.Timestamp]] = {}
    for year, anchor in anchors.items():
        anchor_index = index_by_date[anchor]
        if anchor_index < 5:
            raise MarketMinuteAuditError("insufficient calendar history")
        required_dates[year] = [pd.Timestamp(value) for value in calendar.trade_date.iloc[anchor_index - 5:anchor_index]]

    daily_frames: list[pd.DataFrame] = []
    columns = [
        "symbol", "trade_date", "hard_valid", "bar_valid", "trading_state_valid",
        "corporate_action_valid", "market_rule_valid", "historical_identity_valid",
        "corporate_action_blocking", "available_at", "decision_at", "close", "volume",
        "trade_status", "current_day_data_tradable",
    ]
    for path, year in zip(cy006_paths, spec["sample"]["years"], strict=True):
        dates = [value.date() for value in required_dates[int(year)]]
        table = pq.read_table(path, columns=columns, filters=[("trade_date", "in", dates)])
        frame = table.to_pandas()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
        daily_frames.append(frame)
    daily = pd.concat(daily_frames, ignore_index=True)
    daily["eligible"] = (
        daily.hard_valid.astype(bool) & daily.bar_valid.astype(bool)
        & daily.trading_state_valid.astype(bool) & daily.corporate_action_valid.astype(bool)
        & daily.market_rule_valid.astype(bool) & daily.historical_identity_valid.astype(bool)
        & ~daily.corporate_action_blocking.astype(bool)
        & (pd.to_datetime(daily.available_at, utc=True) <= pd.to_datetime(daily.decision_at, utc=True))
        & pd.to_numeric(daily.close, errors="coerce").gt(0)
        & pd.to_numeric(daily.volume, errors="coerce").gt(0)
        & pd.to_numeric(daily.trade_status, errors="coerce").eq(1)
        & daily.current_day_data_tradable.astype(bool)
    )
    rows: list[dict] = []
    per_view = int(spec["sample"]["symbols_per_anchor_view"])
    for year, anchor in anchors.items():
        dates = required_dates[year]
        cell = daily.loc[daily.trade_date.isin(dates)].copy()
        valid_counts = cell.loc[cell.eligible].groupby("symbol").trade_date.nunique()
        candidates = sorted(str(symbol) for symbol in valid_counts[valid_counts == 5].index)
        views = {
            "ALL_A": candidates,
            "SH_A": [symbol for symbol in candidates if symbol.endswith(".SH")],
            "SZ_A": [symbol for symbol in candidates if symbol.endswith(".SZ")],
            "CHINEXT_BOARD": [symbol for symbol in candidates if symbol.endswith(".SZ") and symbol[:3] in {"300", "301"}],
        }
        for view in spec["sample"]["views"]:
            ordered = sorted(views[view], key=lambda symbol: deterministic_order(anchor, view, symbol))
            if len(ordered) < per_view:
                raise MarketMinuteAuditError(f"insufficient daily candidates: {year}:{view}")
            for rank, symbol in enumerate(ordered[:per_view], start=1):
                trajectory_id = f"{year}:{view}:{rank:02d}:{symbol}"
                for relative_day, trade_date in zip(range(-5, 0), dates, strict=True):
                    rows.append({
                        "trade_id": trajectory_id, "baseline_block": f"MARKET_{year}_{view}",
                        "market_view": view, "selection_rank": rank, "symbol": symbol,
                        "source_symbol": symbol[:6], "entry_signal_date": anchor,
                        "anchor_date": anchor, "relative_day": relative_day,
                        "trade_date": trade_date, "target_year": int(trade_date.year),
                    })
    sample = pd.DataFrame(rows).sort_values(["trade_id", "relative_day"]).reset_index(drop=True)
    if sample.trade_id.nunique() != spec["sample"]["expected_trajectories"] or len(sample) != spec["sample"]["expected_sessions"]:
        raise MarketMinuteAuditError("sample population changed")
    if sample.duplicated(["trade_id", "relative_day"]).any():
        raise MarketMinuteAuditError("duplicate sample key")
    return sample, anchors


def validate_sessions(spec: dict, targets: pd.DataFrame, qd004: dict[str, Path], cy008: dict[str, Path]) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    audit_records: list[dict] = []
    descriptor_records: list[dict] = []
    max_opening_difference = 0.0
    max_conservation_difference = 0.0
    for year, yearly_targets in targets.groupby("target_year", sort=True):
        raw = read_filtered(qd004[f"bars/{year}_day_parquet_none.parquet"], yearly_targets, [
            "symbol", "exchange", "period", "adjust", "trade_date", "bar_end_time",
            "open", "high", "low", "close", "volume", "amount", "source",
        ], suffixed_symbol=False)
        daily = read_filtered(cy008[f"daily/partition_year={year}/data_0.parquet"], yearly_targets, [
            "symbol", "trade_date", "available_at", "minute_count", "distinct_minute_count",
            "source_resolution_minutes", "session_complete", "ohlc_valid", "unit_valid",
            "volume_reconciled", "amount_reconciled", "daily_hard_valid", "hard_valid",
            "invalid_reasons", "snapshot_id", "daily_snapshot_id",
        ], suffixed_symbol=True)
        execution = read_filtered(cy008[f"execution_5m/partition_year={year}/data_0.parquet"], yearly_targets, [
            "symbol", "trade_date", "window_index", "available_at", "open", "high", "low",
            "close", "volume", "amount", "circulating_shares", "trade_status", "up_limit_price",
            "down_limit_price", "market_rule_valid", "causal_inputs_valid",
            "source_resolution_minutes", "minute_count", "distinct_minute_count", "hard_valid", "snapshot_id",
        ], suffixed_symbol=True)
        for target in yearly_targets.itertuples(index=False):
            key = (raw.trade_id == target.trade_id) & (raw.relative_day == target.relative_day)
            rows = raw.loc[key].sort_values("bar_end_time").reset_index(drop=True)
            gate = daily.loc[(daily.trade_id == target.trade_id) & (daily.relative_day == target.relative_day)]
            windows = execution.loc[(execution.trade_id == target.trade_id) & (execution.relative_day == target.relative_day)].sort_values("window_index")
            if len(rows) != 241 or rows.bar_end_time.nunique() != 241:
                raise MarketMinuteAuditError(f"raw coverage failed: {target.trade_id}:{target.relative_day}")
            if pd.to_datetime(rows.bar_end_time).dt.time.tolist() != EXPECTED_TIMES:
                raise MarketMinuteAuditError(f"session grid failed: {target.trade_id}:{target.relative_day}")
            expected_exchange = "SH" if target.symbol.endswith(".SH") else "SZ"
            if not (rows.exchange.eq(expected_exchange) & rows.period.eq("1m") & rows.adjust.eq("none")).all():
                raise MarketMinuteAuditError(f"raw semantics failed: {target.trade_id}:{target.relative_day}")
            if len(gate) != 1 or len(windows) != 6:
                raise MarketMinuteAuditError(f"CY-008 coverage failed: {target.trade_id}:{target.relative_day}")
            item = gate.iloc[0]
            expected_available = pd.Timestamp(target.trade_date) + pd.Timedelta(hours=15, minutes=30)
            checks = (
                pd.Timestamp(item.available_at) == expected_available,
                int(item.minute_count) == 241, int(item.distinct_minute_count) == 241,
                int(item.source_resolution_minutes) == 1, bool(item.session_complete), bool(item.ohlc_valid),
                bool(item.unit_valid), bool(item.volume_reconciled), bool(item.amount_reconciled),
                bool(item.daily_hard_valid), bool(item.hard_valid),
                windows.window_index.astype(int).tolist() == list(range(6)),
                windows.hard_valid.astype(bool).all(), windows.market_rule_valid.astype(bool).all(),
                windows.causal_inputs_valid.astype(bool).all(),
                windows.source_resolution_minutes.astype(int).eq(1).all(),
                windows.minute_count.astype(int).eq(5).all(), windows.distinct_minute_count.astype(int).eq(5).all(),
            )
            if not all(checks):
                raise MarketMinuteAuditError(f"hard-valid gate failed: {target.trade_id}:{target.relative_day}")
            continuous = rows.iloc[1:].reset_index(drop=True)
            five = aggregate_5m(continuous)
            for column in ("open", "high", "low", "close", "volume", "amount"):
                difference = float(np.max(np.abs(five.loc[:5, column].to_numpy(float) - windows[column].to_numpy(float))))
                scale = max(1.0, float(np.max(np.abs(windows[column].to_numpy(float)))))
                max_opening_difference = max(max_opening_difference, difference / scale)
            volume_difference = abs(float(five.volume.sum()) - float(continuous.volume.sum()))
            amount_difference = abs(float(five.amount.sum()) - float(continuous.amount.sum()))
            max_conservation_difference = max(max_conservation_difference, volume_difference, amount_difference)
            if max_opening_difference > 1e-12 or volume_difference != 0 or amount_difference != 0:
                raise MarketMinuteAuditError(f"five-minute reconciliation failed: {target.trade_id}:{target.relative_day}")
            descriptors = session_descriptors(rows)
            if not np.isfinite(np.array(list(descriptors.values()), dtype=float)).all():
                raise MarketMinuteAuditError("nonfinite descriptor")
            prices = continuous[["open", "high", "low", "close"]].to_numpy(float)
            flat = bool(np.max(prices) == np.min(prices))
            context = windows.iloc[0]
            tolerance_up = max(0.001, abs(float(context.up_limit_price)) * 1e-6)
            tolerance_down = max(0.001, abs(float(context.down_limit_price)) * 1e-6)
            locked_up = flat and abs(float(continuous.close.iloc[-1]) - float(context.up_limit_price)) <= tolerance_up
            locked_down = flat and abs(float(continuous.close.iloc[-1]) - float(context.down_limit_price)) <= tolerance_down
            common = {
                "trade_id": target.trade_id, "market_view": target.market_view,
                "selection_rank": int(target.selection_rank), "symbol": target.symbol,
                "anchor_date": pd.Timestamp(target.anchor_date).date().isoformat(),
                "relative_day": int(target.relative_day),
                "trade_date": pd.Timestamp(target.trade_date).date().isoformat(),
            }
            audit_records.append({
                **common, "raw_rows": 241, "continuous_rows": 240,
                "derived_5m_windows": 48, "cy008_opening_windows": 6,
                "hard_valid": True, "flat_session": flat, "limit_locked_up": bool(locked_up),
                "limit_locked_down": bool(locked_down), "available_at": expected_available.isoformat(),
                "minute_snapshot_id": item.snapshot_id, "daily_snapshot_id": item.daily_snapshot_id,
            })
            descriptor_records.append({
                **common, "feature_available_at": expected_available.isoformat(), **descriptors,
            })
    audit = pd.DataFrame(audit_records).sort_values(["trade_id", "relative_day"])
    descriptors = pd.DataFrame(descriptor_records).sort_values(["trade_id", "relative_day"])
    if len(audit) != spec["sample"]["expected_sessions"] or audit[["trade_id", "relative_day"]].duplicated().any():
        raise MarketMinuteAuditError("session audit population changed")
    if descriptors[list(DESCRIPTOR_COLUMNS)].isna().any().any():
        raise MarketMinuteAuditError("descriptor coverage incomplete")
    return audit, descriptors, {
        "maximum_relative_opening_window_difference": max_opening_difference,
        "maximum_five_minute_conservation_difference": max_conservation_difference,
    }


def _render_report(result: dict) -> str:
    return "\n".join([
        "# AUDIT-MKT-MIN-001 market-minute readiness", "",
        f"Decision: `{result['decision']}`.", "", "## Population", "",
        f"- trajectories: {result['population']['trajectories']}",
        f"- five-day sessions: {result['population']['sessions']}",
        f"- raw mapped rows: {result['population']['raw_mapped_rows']}",
        f"- views: {', '.join(result['population']['views'])}",
        "- strategy membership, outcomes, returns, MFE, MAE, exits, and CY-011 read: **none**.",
        "", "## Contract result", "",
        f"- maximum opening-window relative difference: `{result['reconciliation']['maximum_relative_opening_window_difference']}`",
        f"- maximum derived-five-minute conservation difference: `{result['reconciliation']['maximum_five_minute_conservation_difference']}`",
        f"- flat sessions: {result['session_counts']['flat_sessions']}; limit-up locked: {result['session_counts']['limit_locked_up']}; limit-down locked: {result['session_counts']['limit_locked_down']}.",
        "", "Every selected trajectory has exact Day -5..Day -1 completed sessions. The complete trajectory is available only at Day -1 15:30 and cannot justify an earlier or same-bar fill.",
        "", "## Interpretation", "",
        "PASS establishes strategy-independent cross-year/view data and descriptor feasibility only. It does not freeze a minute representation, compare winners/losers, establish a mechanism, or imply a strategy archetype.",
        "", "## Reproducibility", "",
        f"- spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- sample SHA-256: `{result['hashes']['sample_sha256']}`",
        f"- descriptors SHA-256: `{result['hashes']['descriptors_sha256']}`",
    ]) + "\n"


def run() -> dict:
    spec = _load_and_verify_spec()
    cy006_paths = _verify_cy006_files(spec)
    sample, anchors = build_sample(spec, cy006_paths)
    qd004 = inventory_files(_resolve(spec["input_bindings"]["qd004_inventory"]["path"]), spec["selected_partitions"]["qd004"])
    cy008_required = spec["selected_partitions"]["cy008_daily"] + spec["selected_partitions"]["cy008_execution"]
    cy008 = inventory_files(_resolve(spec["input_bindings"]["cy008_inventory"]["path"]), cy008_required)
    audit, descriptors, reconciliation = validate_sessions(spec, sample, qd004, cy008)
    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_out = sample.copy()
    for column in ("entry_signal_date", "anchor_date", "trade_date"):
        sample_out[column] = pd.to_datetime(sample_out[column]).dt.strftime("%Y-%m-%d")
    sample_out.to_csv(SAMPLE_PATH, index=False, lineterminator="\n")
    audit.to_csv(SESSION_PATH, index=False, lineterminator="\n")
    descriptors.to_csv(DESCRIPTOR_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "decision": "PASS_STRATEGY_INDEPENDENT_MARKET_MINUTE_READINESS",
        "outcome_fields_read": [],
        "population": {
            "trajectories": int(sample.trade_id.nunique()), "sessions": int(len(sample)),
            "raw_mapped_rows": int(len(sample) * 241),
            "views": list(spec["sample"]["views"]),
            "anchors": {str(year): value.strftime("%Y-%m-%d") for year, value in anchors.items()},
        },
        "reconciliation": reconciliation,
        "session_counts": {
            "flat_sessions": int(audit.flat_session.sum()),
            "limit_locked_up": int(audit.limit_locked_up.sum()),
            "limit_locked_down": int(audit.limit_locked_down.sum()),
        },
        "descriptor_diagnostics": descriptor_diagnostics(descriptors),
        "limitations": {
            "representation_freeze": "NOT_PERFORMED", "economic_usefulness": "NOT_TESTED",
            "sample_representativeness": "BOUNDED_CROSS_YEAR_VIEW_READINESS_ONLY",
            "pit_grade": "bounded PIT-B",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH), "sample_sha256": sha256_file(SAMPLE_PATH),
            "session_audit_sha256": sha256_file(SESSION_PATH),
            "descriptors_sha256": sha256_file(DESCRIPTOR_PATH),
        },
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    final = run()
    print(json.dumps({
        "decision": final["decision"], "population": final["population"],
        "reconciliation": final["reconciliation"], "session_counts": final["session_counts"],
        "hashes": final["hashes"],
    }, indent=2, sort_keys=True))
