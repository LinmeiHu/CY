#!/usr/bin/env python3
"""Construct EXP-OBL-001 lineages without reading any post-entry outcome."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
LEGACY_SCRIPTS = ROOT / "research/chinext_v1/regime_attribution/scripts"
if str(LEGACY_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LEGACY_SCRIPTS))

import run_phase2_feature_library as phase2  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-001_spec.json"
IDENTITIES = (
    ROOT / "research/chinext_v1/regime_attribution/artifacts/yearly_trades.csv"
)
CY006_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
QD004_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "QD-004-2018-2026-20260820.json"
)
CY008_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-008-pit-b-minute-v2-2018-2026-20260821.json"
)
CY008_AUDIT = Path(
    "/Users/linmei/Documents/CY/data/audit/"
    "CY-008-minute-pit-b-cross-year-gate.json"
)

FEATURE_TABLE = WORK / "artifacts/formation_features.csv"
ASSIGNMENT_TABLE = WORK / "artifacts/lineage_assignments.csv"
AUDIT_JSON = WORK / "artifacts/EXP-OBL-001_audit.json"
FREEZE_MANIFEST = WORK / "lineage_freezes/LINEAGE-OBL-001.json"
REPORT = WORK / "reports/EXP-OBL-001_outcome_blind_lineage_freeze.md"

EXPECTED_TIMES = (
    [pd.Timestamp("2000-01-01 09:30").time()]
    + list(pd.date_range("2000-01-01 09:31", "2000-01-01 11:30", freq="1min").time)
    + list(pd.date_range("2000-01-01 13:01", "2000-01-01 15:00", freq="1min").time)
)
FORBIDDEN_COLUMNS = {
    "round_trip_return",
    "realized_pnl",
    "mfe",
    "mae",
    "false_breakout",
    "winner20",
    "extreme_winner",
    "severe_loss",
    "exit_signal_date",
    "exit_execution_date",
    "canonical_exit_reason",
    "holding_trading_days",
}
BASE_COMPONENTS = (
    "support_shift20",
    "range_contraction20",
    "volatility_contraction20",
)
ACCEPTANCE_COMPONENTS = (
    "time_above_reference",
    "close_reference_retention",
    "below_reference_resilience",
)
LINEAGE_NAMES = {
    (0, 0): "L00_BASE_LOW_ACCEPTANCE_LOW",
    (0, 1): "L01_BASE_LOW_ACCEPTANCE_HIGH",
    (1, 0): "L10_BASE_HIGH_ACCEPTANCE_LOW",
    (1, 1): "L11_BASE_HIGH_ACCEPTANCE_HIGH",
}


class LineageFreezeError(RuntimeError):
    """Raised when an identity, PIT, outcome-blindness, or freeze gate fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, float_format="%.12g", lineterminator="\n")
    os.replace(temporary, path)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-001":
        raise LineageFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_REVEAL":
        raise LineageFreezeError("experiment is not frozen before outcome reveal")
    if spec.get("outcome_access") is not False:
        raise LineageFreezeError("outcome access prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise LineageFreezeError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise LineageFreezeError(f"frozen input mismatch: {mismatches}")
    phase2.validate_inputs()
    return spec, identities


def inventory_files(inventory_path: Path, required: list[str]) -> dict[str, Path]:
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    root = Path(inventory["root"])
    indexed = {item["path"]: item for item in inventory["files"]}
    missing = sorted(set(required) - set(indexed))
    if missing:
        raise LineageFreezeError(f"inventory entries missing: {missing}")
    paths: dict[str, Path] = {}
    mismatches: dict[str, dict[str, Any]] = {}
    for relative in required:
        item = indexed[relative]
        path = root / relative
        if not path.is_file():
            raise LineageFreezeError(f"inventoried file missing: {path}")
        size = path.stat().st_size
        digest = sha256_file(path)
        if size != int(item["size"]) or digest != item["sha256"]:
            mismatches[relative] = {
                "expected_size": int(item["size"]),
                "actual_size": size,
                "expected_sha256": item["sha256"],
                "actual_sha256": digest,
            }
        paths[relative] = path
    if mismatches:
        raise LineageFreezeError(f"inventory content mismatch: {mismatches}")
    return paths


def load_identities() -> pd.DataFrame:
    # usecols is the program's hard separation from the outcome-bearing source file.
    frame = pd.read_csv(
        IDENTITIES,
        usecols=[
            "trade_id",
            "baseline_block",
            "symbol",
            "entry_signal_date",
            "entry_execution_date",
        ],
        dtype={"symbol": str},
    )
    for column in ("entry_signal_date", "entry_execution_date"):
        frame[column] = pd.to_datetime(frame[column], errors="raise")
    if len(frame) != 399 or frame.trade_id.nunique() != 399:
        raise LineageFreezeError("identity population is not 399 unique cycles")
    if frame.duplicated(["baseline_block", "symbol", "entry_signal_date"]).any():
        raise LineageFreezeError("duplicate canonical event key")
    if not (frame.entry_signal_date < frame.entry_execution_date).all():
        raise LineageFreezeError("entry signal is not strictly before execution")
    if not frame.symbol.str.fullmatch(r"30[01]\d{3}\.SZ").all():
        raise LineageFreezeError("identity population is not canonical ChiNext")
    frame["entry_year"] = frame.entry_signal_date.dt.year
    if sorted(frame.entry_year.unique().tolist()) != list(range(2018, 2026)):
        raise LineageFreezeError("identity years changed")
    if FORBIDDEN_COLUMNS.intersection(frame.columns):
        raise LineageFreezeError("outcome column entered identity frame")
    return frame.sort_values("trade_id").reset_index(drop=True)


def build_daily_history(identities: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="chinext_v1_obl001_") as temporary:
        transient_root = Path(temporary)
        manifest = phase2.extended.materialize_transient_inputs(transient_root)
        if manifest["canonical_sha256"] != phase2.EXPECTED_TRANSIENT_CANONICAL:
            raise LineageFreezeError("extended canonical transient identity changed")
        if manifest["membership"]["sha256"] != phase2.EXPECTED_TRANSIENT_MEMBERSHIP:
            raise LineageFreezeError("extended membership transient identity changed")
        connection = phase2.duckdb.connect()
        connection.execute("SET threads=1")
        phase2.create_membership_tables(
            connection, transient_root / "daily_membership.parquet"
        )
        panel_counts = phase2.create_panel_tables(connection, transient_root)
        phase2.create_stock_features(connection)
        identity_projection = identities[
            ["trade_id", "baseline_block", "symbol", "entry_signal_date"]
        ].copy()
        connection.register("obl_identity", identity_projection)
        connection.execute(
            """
            CREATE TEMP TABLE obl_entries AS
            SELECT i.*,c.cal_idx AS signal_idx
            FROM obl_identity i
            JOIN calendar c ON CAST(i.entry_signal_date AS DATE)=c.trade_date
            """
        )
        if connection.execute("SELECT count(*) FROM obl_entries").fetchone()[0] != 399:
            raise LineageFreezeError("entry dates did not map one-to-one to calendar")
        history = connection.execute(
            """
            SELECT e.trade_id,e.baseline_block,e.symbol,e.signal_idx,
                   w.trade_date,w.cal_idx,w.critical_valid,w.coordinate_step_valid,
                   w.step_log_return,w.adjusted_close,w.adjusted_high,w.adjusted_low,
                   w.close AS raw_close,w.amount,w.volume,w.snapshot_id,w.available_at,
                   w.industry
            FROM obl_entries e
            JOIN stock_windows w
              ON w.baseline_block=e.baseline_block AND w.symbol=e.symbol
             AND w.cal_idx BETWEEN e.signal_idx-79 AND e.signal_idx
            ORDER BY e.trade_id,w.cal_idx
            """
        ).fetchdf()
        connection.close()
    return history, {
        "panel_counts": panel_counts,
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
    }


def safe_sample_std(values: np.ndarray) -> float:
    if len(values) < 2 or not np.isfinite(values).all():
        raise LineageFreezeError("invalid volatility subwindow")
    return float(np.std(values, ddof=1))


def daily_features(history: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    maximum_breakout_margin_error = 0.0
    for trade_id, rows in history.groupby("trade_id", sort=True):
        rows = rows.sort_values("cal_idx").reset_index(drop=True)
        signal_idx = int(rows.signal_idx.iloc[0])
        expected = list(range(signal_idx - 79, signal_idx + 1))
        if rows.cal_idx.astype(int).tolist() != expected:
            raise LineageFreezeError(f"incomplete 80-session history: {trade_id}")
        if not rows.critical_valid.astype(bool).all():
            raise LineageFreezeError(f"hard-invalid daily row: {trade_id}")
        if not rows.iloc[1:].coordinate_step_valid.astype(bool).all():
            raise LineageFreezeError(f"invalid action coordinate: {trade_id}")
        numeric = rows[
            ["adjusted_close", "adjusted_high", "adjusted_low", "raw_close", "amount"]
        ].to_numpy(float)
        if not np.isfinite(numeric).all() or (numeric[:, :4] <= 0).any() or (numeric[:, 4] < 0).any():
            raise LineageFreezeError(f"invalid daily numeric history: {trade_id}")

        prior60 = rows.iloc[-61:-1]
        signal = rows.iloc[-1]
        reference_adjusted = float(prior60.adjusted_close.max())
        signal_adjusted = float(signal.adjusted_close)
        if not signal_adjusted > reference_adjusted:
            raise LineageFreezeError(f"accepted event fails strict prior-60 breakout: {trade_id}")
        reference_raw = reference_adjusted * float(signal.raw_close) / signal_adjusted
        raw_margin = float(signal.raw_close) / reference_raw - 1.0
        adjusted_margin = signal_adjusted / reference_adjusted - 1.0
        maximum_breakout_margin_error = max(
            maximum_breakout_margin_error, abs(raw_margin - adjusted_margin)
        )

        prior20 = rows.iloc[-21:-1].reset_index(drop=True)
        early = prior20.iloc[:10]
        late = prior20.iloc[10:]
        early_width = (float(early.adjusted_high.max()) - float(early.adjusted_low.min())) / float(early.adjusted_close.iloc[-1])
        late_width = (float(late.adjusted_high.max()) - float(late.adjusted_low.min())) / float(late.adjusted_close.iloc[-1])
        if early_width <= 0 or late_width <= 0:
            raise LineageFreezeError(f"degenerate prior base range: {trade_id}")
        early_returns = early.step_log_return.iloc[1:].to_numpy(float)
        late_returns = late.step_log_return.iloc[1:].to_numpy(float)
        early_amount = float(early.amount.sum())
        late_amount = float(late.amount.sum())
        if early_amount <= 0 or late_amount <= 0:
            raise LineageFreezeError(f"nonpositive base amount: {trade_id}")
        previous_max_positions = np.flatnonzero(
            np.isclose(
                prior60.adjusted_close.to_numpy(float),
                reference_adjusted,
                rtol=1e-12,
                atol=1e-12,
            )
        )
        if len(previous_max_positions) == 0:
            raise LineageFreezeError(f"prior reference position missing: {trade_id}")
        latest_reference_position = int(previous_max_positions[-1])
        records.append(
            {
                "trade_id": trade_id,
                "breakout_reference_raw": reference_raw,
                "breakout_margin": adjusted_margin,
                "support_shift20": math.log(
                    float(late.adjusted_low.min()) / float(early.adjusted_low.min())
                ),
                "resistance_shift20": math.log(
                    float(late.adjusted_high.max()) / float(early.adjusted_high.max())
                ),
                "range_contraction20": math.log(early_width / late_width),
                "volatility_contraction20": safe_sample_std(early_returns)
                - safe_sample_std(late_returns),
                "downside_amount_contraction20": float(
                    early.loc[early.step_log_return < 0, "amount"].sum() / early_amount
                    - late.loc[late.step_log_return < 0, "amount"].sum() / late_amount
                ),
                "prior60_reference_test_count_2pct": int(
                    (prior60.adjusted_close >= 0.98 * reference_adjusted).sum()
                ),
                "sessions_since_reference": int(len(prior60) - 1 - latest_reference_position),
                "prebreakout_distance": math.log(
                    float(prior60.adjusted_close.iloc[-1]) / reference_adjusted
                ),
                "daily_snapshot_id": signal.snapshot_id,
                "entry_industry": signal.industry,
                "daily_available_at": pd.Timestamp(signal.available_at).isoformat(),
            }
        )
    result = pd.DataFrame(records)
    if len(result) != 399 or result.trade_id.nunique() != 399:
        raise LineageFreezeError("daily feature output is not 399 unique events")
    result.attrs["maximum_breakout_margin_error"] = maximum_breakout_margin_error
    return result


def read_filtered(
    path: Path,
    identities: pd.DataFrame,
    columns: list[str],
    *,
    suffixed_symbol: bool,
) -> pd.DataFrame:
    dates = sorted(identities.entry_signal_date.dt.date.unique())
    symbols = sorted(
        identities.symbol.unique()
        if suffixed_symbol
        else identities.symbol.str[:6].unique()
    )
    table = pq.read_table(
        path,
        columns=columns,
        filters=[("trade_date", "in", dates), ("symbol", "in", symbols)],
    )
    frame = table.to_pandas()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    keys = identities[["trade_id", "symbol", "entry_signal_date"]].copy()
    keys["source_symbol"] = keys.symbol if suffixed_symbol else keys.symbol.str[:6]
    return frame.merge(
        keys[["trade_id", "entry_signal_date", "source_symbol"]],
        left_on=["symbol", "trade_date"],
        right_on=["source_symbol", "entry_signal_date"],
        how="inner",
        validate="many_to_one",
    )


def continuous_rows(rows: pd.DataFrame) -> pd.DataFrame:
    ordered = rows.sort_values("bar_end_time").reset_index(drop=True)
    times = pd.to_datetime(ordered.bar_end_time).dt.time.tolist()
    if times != EXPECTED_TIMES:
        raise LineageFreezeError("signal session does not have exact 241-bar grid")
    return ordered.iloc[1:].reset_index(drop=True)


def aggregate_5m(rows: pd.DataFrame) -> pd.DataFrame:
    if len(rows) != 240:
        raise LineageFreezeError("5-minute aggregation requires 240 bars")
    working = rows.copy()
    working["window_index"] = np.arange(240) // 5
    result = (
        working.groupby("window_index", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
            bar_end_time=("bar_end_time", "last"),
        )
        .reset_index()
    )
    if len(result) != 48:
        raise LineageFreezeError("full session did not aggregate to 48 windows")
    return result


def longest_true_run(values: np.ndarray) -> int:
    best = current = 0
    for value in values.astype(bool):
        current = current + 1 if value else 0
        best = max(best, current)
    return best


def reference_path_features(rows: pd.DataFrame, reference: float) -> dict[str, float]:
    numeric = rows[["open", "high", "low", "close", "volume", "amount"]].to_numpy(float)
    if not np.isfinite(numeric).all() or (numeric[:, :4] <= 0).any() or (numeric[:, 4:] < 0).any():
        raise LineageFreezeError("invalid intraday OHLCV")
    crossed = rows.high.to_numpy(float) > reference
    if not crossed.any():
        raise LineageFreezeError("accepted breakout session never crossed reference")
    first = int(np.flatnonzero(crossed)[0])
    post = rows.iloc[first:].reset_index(drop=True)
    closes = post.close.to_numpy(float)
    above = closes > reference
    equal = np.isclose(closes, reference, rtol=1e-12, atol=1e-12)
    time_above = float(above.mean() + 0.5 * equal.mean())
    volume = post.volume.to_numpy(float)
    total_volume = float(volume.sum())
    if total_volume <= 0:
        raise LineageFreezeError("nonpositive post-cross volume")
    volume_above = float((volume * above).sum() + 0.5 * (volume * equal).sum()) / total_volume
    losses = int(np.sum((closes[:-1] > reference) & (closes[1:] <= reference))) if len(closes) > 1 else 0
    below_fraction = float((closes <= reference).mean())
    session_high = float(post.high.max())
    final_close = float(rows.close.iloc[-1])
    if session_high <= reference or final_close <= reference:
        raise LineageFreezeError("accepted breakout does not close strictly above reference")
    retention = (final_close - reference) / (session_high - reference)
    running_high = np.maximum.accumulate(post.high.to_numpy(float))
    max_drawdown = float(np.min(post.low.to_numpy(float) / running_high - 1.0))
    return {
        "first_cross_index": float(first),
        "time_above_reference": time_above,
        "volume_above_reference": volume_above,
        "reference_loss_count": float(losses),
        "longest_below_reference_run": float(longest_true_run(closes <= reference)),
        "below_reference_resilience": 1.0 - below_fraction,
        "close_reference_retention": float(retention),
        "postcross_max_drawdown": max_drawdown,
    }


def compare_opening_windows(raw: pd.DataFrame, execution: pd.DataFrame) -> float:
    observed = aggregate_5m(continuous_rows(raw)).iloc[:6]
    expected = execution.sort_values("window_index").reset_index(drop=True)
    if expected.window_index.astype(int).tolist() != list(range(6)):
        raise LineageFreezeError("CY-008 opening windows are not 0..5")
    maximum = 0.0
    for column in ("open", "high", "low", "close", "volume", "amount"):
        left = observed[column].to_numpy(float)
        right = expected[column].to_numpy(float)
        scale = np.maximum(1.0, np.maximum(np.abs(left), np.abs(right)))
        maximum = max(maximum, float(np.max(np.abs(left - right) / scale)))
    return maximum


def build_intraday_features(
    identities: pd.DataFrame,
    daily: pd.DataFrame,
    qd004: dict[str, Path],
    cy008: dict[str, Path],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    references = dict(zip(daily.trade_id, daily.breakout_reference_raw, strict=True))
    records: list[dict[str, Any]] = []
    max_opening_difference = 0.0
    for year, yearly in identities.groupby("entry_year", sort=True):
        raw = read_filtered(
            qd004[f"bars/{year}_day_parquet_none.parquet"],
            yearly,
            [
                "symbol",
                "exchange",
                "period",
                "adjust",
                "trade_date",
                "bar_end_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "source",
            ],
            suffixed_symbol=False,
        )
        daily_gate = read_filtered(
            cy008[f"daily/partition_year={year}/data_0.parquet"],
            yearly,
            [
                "symbol",
                "trade_date",
                "available_at",
                "minute_count",
                "distinct_minute_count",
                "source_resolution_minutes",
                "session_complete",
                "ohlc_valid",
                "unit_valid",
                "volume_reconciled",
                "amount_reconciled",
                "daily_hard_valid",
                "hard_valid",
                "snapshot_id",
                "daily_snapshot_id",
            ],
            suffixed_symbol=True,
        )
        execution = read_filtered(
            cy008[f"execution_5m/partition_year={year}/data_0.parquet"],
            yearly,
            [
                "symbol",
                "trade_date",
                "window_index",
                "available_at",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "hard_valid",
                "snapshot_id",
            ],
            suffixed_symbol=True,
        )
        for trade_id, rows in raw.groupby("trade_id", sort=True):
            if len(rows) != 241 or rows.bar_end_time.nunique() != 241:
                raise LineageFreezeError(f"raw minute coverage changed: {trade_id}")
            if not (
                rows.exchange.eq("SZ")
                & rows.period.eq("1m")
                & rows.adjust.eq("none")
            ).all():
                raise LineageFreezeError(f"raw minute semantics changed: {trade_id}")
            gate = daily_gate[daily_gate.trade_id == trade_id]
            windows = execution[execution.trade_id == trade_id]
            if len(gate) != 1 or len(windows) != 6:
                raise LineageFreezeError(f"CY-008 coverage changed: {trade_id}")
            item = gate.iloc[0]
            checks = (
                int(item.minute_count) == 241,
                int(item.distinct_minute_count) == 241,
                int(item.source_resolution_minutes) == 1,
                bool(item.session_complete),
                bool(item.ohlc_valid),
                bool(item.unit_valid),
                bool(item.volume_reconciled),
                bool(item.amount_reconciled),
                bool(item.daily_hard_valid),
                bool(item.hard_valid),
                windows.hard_valid.astype(bool).all(),
            )
            if not all(checks):
                raise LineageFreezeError(f"CY-008 hard-valid gate failed: {trade_id}")
            available_at = pd.Timestamp(item.available_at)
            signal_date = pd.Timestamp(rows.entry_signal_date.iloc[0])
            if available_at != signal_date + pd.Timedelta(hours=15, minutes=30):
                raise LineageFreezeError(f"minute feature availability changed: {trade_id}")
            maximum = compare_opening_windows(rows, windows)
            max_opening_difference = max(max_opening_difference, maximum)
            if maximum > 1e-12:
                raise LineageFreezeError(f"opening-window mismatch: {trade_id}")
            continuous = continuous_rows(rows)
            five = aggregate_5m(continuous)
            primary = reference_path_features(continuous, references[trade_id])
            neighbor = reference_path_features(five, references[trade_id])
            records.append(
                {
                    "trade_id": trade_id,
                    "feature_available_at": available_at.isoformat(),
                    "minute_snapshot_id": item.snapshot_id,
                    "minute_daily_snapshot_id": item.daily_snapshot_id,
                    **primary,
                    **{f"{key}_5m": value for key, value in neighbor.items()},
                }
            )
    result = pd.DataFrame(records)
    if len(result) != 399 or result.trade_id.nunique() != 399:
        raise LineageFreezeError("intraday feature output is not 399 unique events")
    return result, {
        "raw_minute_rows": 399 * 241,
        "continuous_minute_rows": 399 * 240,
        "cy008_daily_hard_valid": 399,
        "cy008_opening_windows_hard_valid": 399 * 6,
        "maximum_relative_opening_window_difference": max_opening_difference,
    }


def percentile_rank_within_year(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.groupby("entry_year")[column].rank(method="average", pct=True)


def lineage_id(base_high: pd.Series, acceptance_high: pd.Series) -> pd.Series:
    return pd.Series(
        [
            LINEAGE_NAMES[(int(base), int(acceptance))]
            for base, acceptance in zip(base_high, acceptance_high, strict=True)
        ],
        index=base_high.index,
    )


def construct_lineages(features: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if FORBIDDEN_COLUMNS.intersection(features.columns):
        raise LineageFreezeError("outcome column entered formation feature frame")
    for column in (*BASE_COMPONENTS, *ACCEPTANCE_COMPONENTS):
        features[f"{column}_rank"] = percentile_rank_within_year(features, column)
    features["base_repair_score"] = features[
        [f"{column}_rank" for column in BASE_COMPONENTS]
    ].mean(axis=1)
    features["breakout_acceptance_score"] = features[
        [f"{column}_rank" for column in ACCEPTANCE_COMPONENTS]
    ].mean(axis=1)
    split = float(spec["lineage_algorithm"]["fixed_split"])
    features["base_repair_high"] = features.base_repair_score >= split
    features["breakout_acceptance_high"] = features.breakout_acceptance_score >= split
    features["lineage_id"] = lineage_id(
        features.base_repair_high, features.breakout_acceptance_high
    )

    # Neighbor: remove one base component and replace 1m acceptance with exact 5m aggregation.
    features["base_neighbor_score"] = features[
        ["support_shift20_rank", "range_contraction20_rank"]
    ].mean(axis=1)
    neighbor_columns: list[str] = []
    for component in ACCEPTANCE_COMPONENTS:
        source = f"{component}_5m"
        rank = f"{source}_rank"
        features[rank] = percentile_rank_within_year(features, source)
        neighbor_columns.append(rank)
    features["acceptance_neighbor_5m_score"] = features[neighbor_columns].mean(axis=1)
    features["neighbor_lineage_id"] = lineage_id(
        features.base_neighbor_score >= split,
        features.acceptance_neighbor_5m_score >= split,
    )
    features["assignment_margin"] = np.minimum(
        np.abs(features.base_repair_score - split),
        np.abs(features.breakout_acceptance_score - split),
    )
    counts = features.lineage_id.value_counts().sort_index()
    expected_lineages = sorted(LINEAGE_NAMES.values())
    if sorted(counts.index.tolist()) != expected_lineages:
        raise LineageFreezeError("one or more frozen lineage IDs collapsed")
    by_year = pd.crosstab(features.entry_year, features.lineage_id).reindex(
        columns=expected_lineages, fill_value=0
    )
    by_block = pd.crosstab(features.baseline_block, features.lineage_id).reindex(
        columns=expected_lineages, fill_value=0
    )
    agreement = float((features.lineage_id == features.neighbor_lineage_id).mean())
    gates_spec = spec["construction_gates"]
    gates = {
        "complete_coverage": len(features) == 399 and features.trade_id.nunique() == 399,
        "minimum_lineage_size": int(counts.min()) >= gates_spec["minimum_lineage_size"],
        "maximum_lineage_fraction": float(counts.max() / len(features))
        <= gates_spec["maximum_lineage_fraction"],
        "every_lineage_in_every_year": int(by_year.min().min())
        >= gates_spec["minimum_lineage_count_per_year"],
        "neighbor_assignment_agreement": agreement
        >= gates_spec["minimum_neighbor_assignment_agreement"],
        "no_outcome_columns": not bool(FORBIDDEN_COLUMNS.intersection(features.columns)),
    }
    if not all(gates.values()):
        raise LineageFreezeError(
            f"outcome-blind lineage construction gates failed: {gates}; "
            f"counts={counts.to_dict()}; agreement={agreement}"
        )
    audit = {
        "lineage_counts": counts.to_dict(),
        "lineage_fractions": (counts / len(features)).to_dict(),
        "lineage_counts_by_year": by_year.to_dict(orient="index"),
        "lineage_counts_by_block": by_block.to_dict(orient="index"),
        "neighbor_assignment_agreement": agreement,
        "assignment_margin_le_0_05_fraction": float(
            (features.assignment_margin <= 0.05).mean()
        ),
        "gates": gates,
    }
    return features, audit


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    counts = audit["lineage"]["lineage_counts"]
    lines = [
        "# EXP-OBL-001 outcome-blind lineage freeze",
        "",
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.",
        "",
        "No future return, MFE, MAE, false-breakout, holding, exit, winner, or loser field was read. No outcome association was calculated.",
        "",
        "## Frozen lineage counts",
        "",
        "| Lineage | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(counts.items()))
    lines.extend(
        [
            "",
            "The four IDs are neutral quadrants of base-repair and canonical-reference acceptance. They do not encode favorable or unfavorable outcomes.",
            "",
            f"Exact 5-minute/base-neighbor assignment agreement: `{audit['lineage']['neighbor_assignment_agreement']:.6f}`.",
            "",
            "All full signal-session features are available at 15:30 Asia/Shanghai and can first inform T+1 or later. Canonical V1 remains unchanged.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, bound_identities = validate_spec_and_inputs()
    identities = load_identities()
    years = list(range(2018, 2026))
    cy006 = inventory_files(
        CY006_INVENTORY,
        [f"partition_year={year}/data_0.parquet" for year in years],
    )
    qd004 = inventory_files(
        QD004_INVENTORY,
        [f"bars/{year}_day_parquet_none.parquet" for year in years],
    )
    cy008 = inventory_files(
        CY008_INVENTORY,
        [
            path
            for year in years
            for path in (
                f"daily/partition_year={year}/data_0.parquet",
                f"execution_5m/partition_year={year}/data_0.parquet",
            )
        ],
    )
    cross_audit = json.loads(CY008_AUDIT.read_text(encoding="utf-8"))
    if cross_audit.get("pass") is not True or not all(cross_audit.get("checks", {}).values()):
        raise LineageFreezeError("CY-008 cross-year audit is not PASS")
    # cy006 is deliberately materialized and hash-validated even though phase2 resolves paths.
    if len(cy006) != 8:
        raise LineageFreezeError("CY-006 required partition count changed")

    history, daily_audit = build_daily_history(identities)
    daily = daily_features(history)
    intraday, intraday_audit = build_intraday_features(
        identities, daily, qd004, cy008
    )
    features = identities.merge(daily, on="trade_id", validate="one_to_one")
    features = features.merge(intraday, on="trade_id", validate="one_to_one")
    features, lineage_audit = construct_lineages(features, spec)
    if FORBIDDEN_COLUMNS.intersection(features.columns):
        raise LineageFreezeError("outcome columns entered final feature table")

    feature_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "feature_available_at",
        "daily_available_at",
        "daily_snapshot_id",
        "minute_snapshot_id",
        "minute_daily_snapshot_id",
        "entry_industry",
        "breakout_reference_raw",
        "breakout_margin",
        "support_shift20",
        "resistance_shift20",
        "range_contraction20",
        "volatility_contraction20",
        "downside_amount_contraction20",
        "prior60_reference_test_count_2pct",
        "sessions_since_reference",
        "prebreakout_distance",
        "first_cross_index",
        "time_above_reference",
        "volume_above_reference",
        "reference_loss_count",
        "longest_below_reference_run",
        "below_reference_resilience",
        "close_reference_retention",
        "postcross_max_drawdown",
        "base_repair_score",
        "breakout_acceptance_score",
        "base_neighbor_score",
        "acceptance_neighbor_5m_score",
        "assignment_margin",
        "lineage_id",
        "neighbor_lineage_id",
    ]
    assignment_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "feature_available_at",
        "lineage_id",
        "neighbor_lineage_id",
        "base_repair_score",
        "breakout_acceptance_score",
        "assignment_margin",
    ]
    feature_output = features[feature_columns].sort_values("trade_id").reset_index(drop=True)
    assignment_output = features[assignment_columns].sort_values("trade_id").reset_index(drop=True)
    atomic_csv(FEATURE_TABLE, feature_output)
    atomic_csv(ASSIGNMENT_TABLE, assignment_output)
    feature_sha = sha256_file(FEATURE_TABLE)
    assignment_sha = sha256_file(ASSIGNMENT_TABLE)
    input_aggregate = hashlib.sha256(
        "\n".join(f"{path}:{digest}" for path, digest in sorted(bound_identities.items())).encode()
    ).hexdigest()
    freeze_id = f"LINEAGE-OBL-001-{assignment_sha[:16].upper()}"
    audit = {
        "experiment_id": "EXP-OBL-001",
        "hypothesis_id": "H-OBL-002",
        "status": "FROZEN_OUTCOME_BLIND_LINEAGES",
        "lineage_freeze_id": freeze_id,
        "outcome_columns_read": [],
        "population": {
            "events": len(features),
            "unique_trade_ids": int(features.trade_id.nunique()),
            "date_min": features.entry_signal_date.min().date().isoformat(),
            "date_max": features.entry_signal_date.max().date().isoformat(),
            "years": sorted(features.entry_year.unique().astype(int).tolist()),
        },
        "daily": {
            **daily_audit,
            "history_rows": len(history),
            "maximum_breakout_margin_coordinate_error": daily.attrs[
                "maximum_breakout_margin_error"
            ],
        },
        "intraday": intraday_audit,
        "lineage": lineage_audit,
        "artifact_hashes": {
            str(FEATURE_TABLE.relative_to(ROOT)): feature_sha,
            str(ASSIGNMENT_TABLE.relative_to(ROOT)): assignment_sha,
        },
        "bound_input_hashes": bound_identities,
        "bound_input_aggregate_sha256": input_aggregate,
        "available_at_timestamp": "entry signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "entry execution T+1 open or later",
        "interpretation": "neutral structural taxonomy; no outcome meaning assigned",
    }
    atomic_write(
        AUDIT_JSON,
        json.dumps(clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    freeze_manifest = {
        "schema_version": "1.0.0",
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-001",
        "status": "FROZEN_BEFORE_OUTCOME_REVEAL",
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": sha256_file(SPEC),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "feature_table": str(FEATURE_TABLE.relative_to(ROOT)),
        "feature_table_sha256": feature_sha,
        "assignment_table": str(ASSIGNMENT_TABLE.relative_to(ROOT)),
        "assignment_table_sha256": assignment_sha,
        "audit_path": str(AUDIT_JSON.relative_to(ROOT)),
        "audit_sha256": sha256_file(AUDIT_JSON),
        "lineage_ids": sorted(LINEAGE_NAMES.values()),
        "outcome_access_before_freeze": False,
        "outcome_columns_read": [],
        "immutable_scientific_elements": spec["immutable_scientific_elements"],
    }
    atomic_write(
        FREEZE_MANIFEST,
        json.dumps(freeze_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
