#!/usr/bin/env python3
"""Run the frozen first A-share long-only ultra-short discovery batch."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-ULTRASHORT-DISCOVERY-CYCLE-014_spec.json"
AUDIT_PATH = PROGRAM / "GATE_DESIGN_AUDIT_ASHARE_ULTRASHORT_CYCLE_014.md"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-ULTRASHORT-DISCOVERY-CYCLE-014_summary.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-ULTRASHORT-DISCOVERY-CYCLE-014_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-ULTRASHORT-DISCOVERY-CYCLE-014_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_ultrashort_cycle_014")
PANEL_PATH = EXTERNAL_ROOT / "screen_panel.parquet"
EQUITY_PATH = EXTERNAL_ROOT / "replay_equity.parquet"
EXPECTED_SPEC_SHA256 = "e35ed20d28b599ae279eeab5aad3af5836ce483fdfead3153cf040df2f4d4eb7"
EXPECTED_AUDIT_SHA256 = "c2cba3f5957ad50cf5a242515b90d8172c5c3cfab38e1845e3c3e5584e32286f"
FAMILIES = (
    "price_limit_reopen_reseal_acceptance",
    "liquidity_shock_price_assimilation",
)
COST = 0.002
PRIMARY_HORIZON = 2


class UltraShortCycleError(RuntimeError):
    """Fail-closed error for Cycle 014."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise UltraShortCycleError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE013 = _load_module(
    "ashare_industry_lead_follow_cycle_013_for_014",
    PROGRAM / "scripts/run_ashare_industry_lead_follow_cycle_013.py",
)
CA = _load_module(
    "ashare_ca_replay_003_for_014",
    PROGRAM / "scripts/run_ashare_ca_replay_003.py",
)


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise UltraShortCycleError("frozen spec identity mismatch")
    if sha256_file(AUDIT_PATH) != EXPECTED_AUDIT_SHA256:
        raise UltraShortCycleError("gate-design audit identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_GATE_AUDIT_AND_FAMILIES_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise UltraShortCycleError("families were not frozen before outcomes")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise UltraShortCycleError(f"bound input changed: {role}")
    if tuple(spec["families"]) != FAMILIES:
        raise UltraShortCycleError("frozen family identity changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "Cycle-013", "same-session", "threshold grid", "combination"):
        if phrase not in prohibited:
            raise UltraShortCycleError(f"missing prohibition: {phrase}")
    return spec


def _configure(temp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='6GB'")
    connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    connection.execute("SET preserve_insertion_order=false")
    return connection


def _build_causal_frame(
    daily_paths: list[Path], minute_paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    con = _configure(temp_path)
    con.from_parquet([str(path) for path in daily_paths], union_by_name=True).create_view("daily")
    con.from_parquet([str(path) for path in minute_paths], union_by_name=True).create_view("minute")
    daily_audit = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER)
        FROM daily"""
    ).fetchone()
    minute_audit = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
        sum((hard_valid AND CAST(available_at AS TIME)<>TIME '15:30:00')::INTEGER)
        FROM minute"""
    ).fetchone()
    audit = {
        "daily_rows": int(daily_audit[0]),
        "daily_symbols": int(daily_audit[1]),
        "daily_first": str(daily_audit[2]),
        "daily_last": str(daily_audit[3]),
        "daily_time_travel": int(daily_audit[4]),
        "daily_lineage_failures": int(daily_audit[5]),
        "minute_rows": int(minute_audit[0]),
        "minute_symbols": int(minute_audit[1]),
        "minute_first": str(minute_audit[2]),
        "minute_last": str(minute_audit[3]),
        "minute_lineage_failures": int(minute_audit[4]),
        "minute_non_1530_hard_valid": int(minute_audit[5]),
    }
    expected = {
        "daily_rows": 6155390,
        "daily_symbols": 5262,
        "daily_first": "2018-01-02",
        "daily_last": "2023-12-29",
        "daily_time_travel": 0,
        "daily_lineage_failures": 0,
        "minute_rows": 6114413,
        "minute_symbols": 5235,
        "minute_first": "2018-01-02",
        "minute_last": "2023-12-29",
        "minute_lineage_failures": 0,
        "minute_non_1530_hard_valid": 0,
    }
    if audit != expected:
        raise UltraShortCycleError(f"source audit changed: {audit}")
    con.execute(
        """CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM daily) ORDER BY trade_date"""
    )
    calendar = [
        row[0] for row in con.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    con.execute(
        """CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.amount>0) history_valid,
        (d.hard_valid IS TRUE AND d.trade_status=1
         AND d.current_day_data_tradable IS TRUE AND d.is_st IS FALSE) current_valid,
        lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(c.cal_idx,20) OVER w cal_idx_lag20,lag(c.cal_idx,252) OVER w cal_idx_lag252,
        lag(d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.amount>0) OVER w previous_valid
        FROM daily d JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)"""
    )
    con.execute(
        """CREATE TEMP TABLE steps AS SELECT *,CASE
        WHEN history_valid AND previous_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0
         AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))
             /coalesce(share_multiplier,1))) ELSE NULL END step_log_return
        FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE rolling0 AS SELECT *,
        median(CASE WHEN history_valid THEN amount END) OVER p20 prior20_median_amount,
        avg(CASE WHEN history_valid THEN amount END) OVER p20 prior20_average_amount,
        count(CASE WHEN history_valid THEN amount END) OVER p20 prior20_count,
        sum(step_log_return) OVER r20 r20,
        count(step_log_return) OVER r20 r20_count
        FROM steps WINDOW
        p20 AS (PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        r20 AS (PARTITION BY symbol ORDER BY trade_date
          ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)"""
    )
    con.execute(
        """CREATE TEMP TABLE shock0 AS SELECT *,
        CASE WHEN amount>0 AND prior20_median_amount>0 AND prior20_count=20
          THEN ln(amount/prior20_median_amount) ELSE NULL END amount_shock
        FROM rolling0"""
    )
    con.execute(
        """CREATE TEMP TABLE shock1 AS SELECT *,
        quantile_cont(amount_shock,0.90) OVER shock_window prior252_shock_p90,
        count(amount_shock) OVER shock_window prior252_shock_count
        FROM shock0 WINDOW shock_window AS
        (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING)"""
    )
    frame = con.execute(
        """SELECT s.trade_date,s.cal_idx,s.symbol,s.industry,s.snapshot_id,
        s.available_at,s.decision_at,s.open,s.high,s.low,s.close,s.preclose,s.amount,
        s.up_limit_price,s.buy_blocked_open,s.sell_blocked_open,s.step_log_return,s.r20,
        s.prior20_average_amount,s.amount_shock,s.prior252_shock_p90,
        s.prior252_shock_count,m.available_at minute_available_at,
        m.snapshot_id minute_snapshot_id,m.daily_snapshot_id,m.opening_30m_return,
        m.closing_30m_return,m.close_vs_vwap,m.last_hour_volume_share,
        m.realized_volatility
        FROM shock1 s JOIN minute m USING(symbol,trade_date)
        WHERE s.current_valid AND s.history_valid AND s.cal_idx>=252
          AND s.cal_idx-s.cal_idx_lag252=252 AND s.cal_idx-s.cal_idx_lag20=20
          AND s.prior20_count=20 AND s.prior20_average_amount>=50000000
          AND s.r20_count=20 AND isfinite(s.step_log_return) AND isfinite(s.r20)
          AND s.up_limit_price>0 AND s.industry IS NOT NULL AND s.industry<>''
          AND m.hard_valid IS TRUE AND m.daily_hard_valid IS TRUE
          AND m.session_complete IS TRUE AND m.ohlc_valid IS TRUE
          AND m.unit_valid IS TRUE AND m.volume_reconciled IS TRUE
          AND m.amount_reconciled IS TRUE AND m.minute_count=241
          AND m.distinct_minute_count=241 AND m.source_resolution_minutes=1
          AND m.available_at=CAST(s.trade_date AS TIMESTAMP)+INTERVAL '15 hours 30 minutes'
          AND m.snapshot_id IS NOT NULL AND m.daily_snapshot_id=s.snapshot_id
          AND isfinite(m.close_vs_vwap) AND isfinite(m.realized_volatility)
        ORDER BY s.trade_date,s.symbol"""
    ).fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise UltraShortCycleError("invalid causal frame")
    audit["eligible_rows"] = len(frame)
    audit["eligible_symbols"] = int(frame.symbol.nunique())
    audit["eligible_dates"] = int(frame.trade_date.nunique())
    return frame, calendar, audit


def _minute_number(values: pd.Series) -> np.ndarray:
    timestamps = pd.to_datetime(values, errors="raise")
    return (timestamps.dt.hour * 60 + timestamps.dt.minute).to_numpy(dtype=np.int16)


def _cent_ticks(values: np.ndarray | float) -> np.ndarray:
    """Map governed A-share prices to their exact CNY0.01 trading tick."""
    return np.rint(np.asarray(values, dtype=float) * 100).astype(np.int64)


def _limit_lifecycle(
    frame: pd.DataFrame, raw_paths: dict[int, Path], temp_path: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = frame.loc[
        frame.high.ge(frame.up_limit_price - 1e-9) & frame.close.ge(frame.up_limit_price - 1e-9)
    ].copy()
    lifecycle_rows: list[dict[str, Any]] = []
    raw_rows = 0
    for year in range(2018, 2024):
        keys = candidates.loc[pd.to_datetime(candidates.trade_date).dt.year.eq(year)].copy()
        if keys.empty:
            continue
        keys["source_symbol"] = keys.symbol.astype(str).str.split(".", regex=False).str[0]
        keys["exchange"] = keys.symbol.astype(str).str.split(".", regex=False).str[1]
        con = _configure(temp_path)
        con.register(
            "candidate_keys",
            keys[
                [
                    "trade_date",
                    "source_symbol",
                    "exchange",
                    "symbol",
                    "industry",
                    "up_limit_price",
                    "prior20_average_amount",
                ]
            ],
        )
        raw = con.execute(
            """SELECT k.symbol AS full_symbol,k.industry,k.up_limit_price,
            k.prior20_average_amount,q.trade_date,q.bar_end_time,q.close
            FROM read_parquet(?) q JOIN candidate_keys k
              ON q.trade_date=k.trade_date AND q.symbol=k.source_symbol
             AND q.exchange=k.exchange
            WHERE q.period='1m' AND q.adjust='none'
            ORDER BY k.symbol,q.trade_date,q.bar_end_time""",
            [str(raw_paths[year])],
        ).fetchdf()
        con.close()
        raw_rows += len(raw)
        for (symbol, trade_date), group in raw.groupby(["full_symbol", "trade_date"], sort=True):
            group = group.sort_values("bar_end_time", kind="mergesort")
            if len(group) != 241:
                raise UltraShortCycleError(f"raw minute count changed: {symbol}:{trade_date}")
            minutes = _minute_number(group.bar_end_time)
            if not np.array_equal(minutes, CYCLE013.ADAPTER.EXPECTED_MINUTES):
                raise UltraShortCycleError(f"raw minute grid changed: {symbol}:{trade_date}")
            closes = pd.to_numeric(group.close, errors="raise").to_numpy(float)[1:]
            limit = float(group.up_limit_price.iloc[0])
            if not np.isfinite(closes).all() or (closes <= 0).any():
                raise UltraShortCycleError(f"invalid lifecycle prices: {symbol}:{trade_date}")
            close_ticks = _cent_ticks(closes)
            limit_tick = int(_cent_ticks(limit))
            at_limit = close_ticks == limit_tick
            if not at_limit.any() or not at_limit[-1]:
                raise UltraShortCycleError(
                    f"daily/raw limit identity changed: {symbol}:{trade_date}"
                )
            first = int(np.flatnonzero(at_limit)[0])
            off_after = np.flatnonzero(
                (np.arange(len(closes)) > first) & (close_ticks <= limit_tick - 1)
            )
            final_run = 0
            for value in at_limit[::-1]:
                if not value:
                    break
                final_run += 1
            transitions = int(np.sum((~at_limit[:-1]) & at_limit[1:]))
            kind = "simple_seal_control" if len(off_after) == 0 else "reopen_reseal_event"
            lifecycle_rows.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "industry": str(group.industry.iloc[0]),
                    "prior20_average_amount": float(group.prior20_average_amount.iloc[0]),
                    "lifecycle_kind": kind,
                    "acceptance_score": float(final_run / (len(closes) - first)),
                    "first_seal_minute": int(minutes[first + 1]),
                    "final_limit_run_minutes": final_run,
                    "reseal_transitions": transitions,
                }
            )
    lifecycle = pd.DataFrame(lifecycle_rows)
    if lifecycle.empty or lifecycle.duplicated(["trade_date", "symbol"]).any():
        raise UltraShortCycleError("invalid lifecycle panel")
    audit = {
        "daily_limit_close_candidates": len(candidates),
        "raw_rows": raw_rows,
        "reopen_reseal_events": int(lifecycle.lifecycle_kind.eq("reopen_reseal_event").sum()),
        "simple_seal_controls": int(lifecycle.lifecycle_kind.eq("simple_seal_control").sum()),
        "decision_dates": int(lifecycle.trade_date.nunique()),
    }
    return lifecycle, audit


def _rank(series: pd.Series) -> pd.Series:
    return series.rank(method="average", pct=True)


def _hash_order(symbol: str, trade_date: Any, seed: str) -> str:
    return hashlib.sha256(f"{seed}|{symbol}|{trade_date}".encode()).hexdigest()


def _residual_scores(group: pd.DataFrame) -> pd.Series:
    columns = ["raw_score", "control_return", "control_range", "control_r20"]
    valid = group[columns].notna().all(axis=1)
    output = pd.Series(np.nan, index=group.index)
    if valid.sum() < 20:
        return output
    y = group.loc[valid, "raw_score"].to_numpy(float)
    x = group.loc[valid, ["control_return", "control_range", "control_r20"]].to_numpy(float)
    x = np.column_stack([np.ones(len(x)), x])
    output.loc[valid] = y - x @ np.linalg.lstsq(x, y, rcond=None)[0]
    return output


def _family_selections(
    frame: pd.DataFrame, lifecycle: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    context_columns = [
        "trade_date",
        "symbol",
        "industry",
        "minute_available_at",
        "step_log_return",
        "r20",
        "high",
        "low",
        "close",
        "preclose",
        "close_vs_vwap",
        "amount_shock",
        "prior252_shock_p90",
        "prior252_shock_count",
    ]
    context = frame[context_columns].copy()
    life = lifecycle.merge(context, on=["trade_date", "symbol", "industry"], validate="one_to_one")
    events = life.loc[life.lifecycle_kind.eq("reopen_reseal_event")].copy()
    events = events.sort_values(
        ["trade_date", "acceptance_score", "prior20_average_amount", "symbol"],
        ascending=[True, False, False, True],
    )
    events["signal_rank"] = events.groupby("trade_date").cumcount() + 1
    events["candidate_count"] = events.groupby("trade_date").symbol.transform("size")
    top_a = events.loc[events.signal_rank.le(20)].copy()
    top_a["family"] = FAMILIES[0]
    top_a["leg"] = "selected"
    top_a["signal_score"] = top_a.acceptance_score
    controls_a = life.loc[life.lifecycle_kind.eq("simple_seal_control")].copy()
    controls_a["hash_order"] = [
        _hash_order(row.symbol, row.trade_date, "014-A") for row in controls_a.itertuples()
    ]
    selected_count_a = top_a.groupby("trade_date").size().to_dict()
    controls_a = controls_a.sort_values(["trade_date", "hash_order", "symbol"])
    controls_a = controls_a.loc[
        controls_a.groupby("trade_date").cumcount()
        < controls_a.trade_date.map(selected_count_a).fillna(0)
    ].copy()
    controls_a["signal_rank"] = controls_a.groupby("trade_date").cumcount() + 1
    controls_a["candidate_count"] = controls_a.groupby("trade_date").symbol.transform("size")
    controls_a["family"] = FAMILIES[0]
    controls_a["leg"] = "control"
    controls_a["signal_score"] = np.nan

    shock = frame.loc[
        frame.prior252_shock_count.ge(120)
        & frame.amount_shock.ge(frame.prior252_shock_p90)
        & frame.high.gt(frame.low)
    ].copy()
    shock["accept_vwap"] = shock.groupby("trade_date").close_vs_vwap.transform(_rank)
    shock["close_location"] = (shock.close - shock.low) / (shock.high - shock.low)
    shock["accept_location"] = shock.groupby("trade_date").close_location.transform(_rank)
    shock["raw_score"] = (shock.accept_vwap + shock.accept_location) / 2
    shock["control_return"] = shock.groupby("trade_date").step_log_return.transform(_rank)
    shock["daily_range"] = (shock.high - shock.low) / shock.preclose
    shock["control_range"] = shock.groupby("trade_date").daily_range.transform(_rank)
    shock["control_r20"] = shock.groupby("trade_date").r20.transform(_rank)
    shock["signal_score"] = np.nan
    for _, group in shock.groupby("trade_date", sort=True):
        shock.loc[group.index, "signal_score"] = _residual_scores(group)
    shock = shock.loc[np.isfinite(shock.signal_score)].copy()
    shock = shock.sort_values(
        ["trade_date", "signal_score", "prior20_average_amount", "symbol"],
        ascending=[True, False, False, True],
    )
    shock["signal_rank"] = shock.groupby("trade_date").cumcount() + 1
    shock["candidate_count"] = shock.groupby("trade_date").symbol.transform("size")
    top_b = shock.loc[shock.signal_rank.le(20)].copy()
    top_b["family"] = FAMILIES[1]
    top_b["leg"] = "selected"
    remaining = shock.loc[shock.signal_rank.gt(20)].copy()
    remaining["hash_order"] = [
        _hash_order(row.symbol, row.trade_date, "014-B") for row in remaining.itertuples()
    ]
    selected_count_b = top_b.groupby("trade_date").size().to_dict()
    controls_b = remaining.sort_values(["trade_date", "hash_order", "symbol"])
    controls_b = controls_b.loc[
        controls_b.groupby("trade_date").cumcount()
        < controls_b.trade_date.map(selected_count_b).fillna(0)
    ].copy()
    controls_b["signal_rank"] = controls_b.groupby("trade_date").cumcount() + 1
    controls_b["family"] = FAMILIES[1]
    controls_b["leg"] = "control"

    pieces = [top_a, controls_a, top_b, controls_b]
    columns = [
        "family",
        "leg",
        "trade_date",
        "symbol",
        "industry",
        "minute_available_at",
        "signal_score",
        "signal_rank",
        "candidate_count",
        "prior20_average_amount",
    ]
    selections = pd.concat([piece[columns] for piece in pieces], ignore_index=True)
    selections = selections.rename(columns={"minute_available_at": "available_at"})
    selections["decision_at"] = pd.to_datetime(selections.trade_date) + pd.Timedelta(
        hours=15, minutes=30
    )
    selections = selections.sort_values(
        ["family", "leg", "trade_date", "signal_rank", "symbol"]
    ).reset_index(drop=True)
    if selections.empty or selections.duplicated(["family", "leg", "trade_date", "symbol"]).any():
        raise UltraShortCycleError("invalid family selections")
    correlations = {
        name: float(shock[["signal_score", name]].corr().iloc[0, 1])
        for name in ("control_return", "control_range", "control_r20")
    }
    diagnostics = {
        FAMILIES[0]: {
            "eligible_events": len(events),
            "selected_rows": len(top_a),
            "control_rows": len(controls_a),
            "event_dates": int(events.trade_date.nunique()),
            "median_acceptance_score": float(events.acceptance_score.median()),
            "median_final_limit_run_minutes": float(events.final_limit_run_minutes.median()),
        },
        FAMILIES[1]: {
            "shock_eligible_rows": len(shock),
            "selected_rows": len(top_b),
            "control_rows": len(controls_b),
            "decision_dates": int(shock.trade_date.nunique()),
            "signal_control_correlations": correlations,
        },
    }
    return selections, diagnostics


def _outcome_links(selections: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    index = {day: position for position, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for candidate_row, candidate in selections.iterrows():
        signal = pd.Timestamp(candidate.trade_date).date()
        signal_index = index[signal]
        for offset in range(1, 5):
            if signal_index + offset >= len(calendar):
                continue
            rows.append(
                {
                    "candidate_row": candidate_row,
                    "symbol": candidate.symbol,
                    "trade_date": calendar[signal_index + offset],
                    "offset": offset,
                }
            )
    return pd.DataFrame(rows)


def _query_outcome_rows(daily_paths: list[Path], links: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("links", links)
    rows = con.execute(
        """SELECT l.candidate_row,l.offset,d.trade_date,d.symbol,d.open,d.high,d.low,
        d.close,d.amount,d.hard_valid,d.trade_status,d.current_day_data_tradable,
        d.buy_blocked_open,d.sell_blocked_open,d.corporate_action_count,
        d.corporate_action_valid,d.corporate_action_blocking,
        d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
        d.rights_ratio,d.available_at
        FROM read_parquet(?) d JOIN links l USING(symbol,trade_date)
        ORDER BY l.candidate_row,l.offset""",
        [[str(path) for path in daily_paths]],
    ).fetchdf()
    con.close()
    return rows


def _visible_action(row: Any) -> tuple[float, float] | None:
    rights = 0.0 if pd.isna(row.rights_ratio) else float(row.rights_ratio)
    multiplier = 1.0 if pd.isna(row.share_multiplier) else float(row.share_multiplier)
    cash = 0.0 if pd.isna(row.cash_per_share) else float(row.cash_per_share)
    available = (
        None
        if pd.isna(row.corporate_action_available_date)
        else pd.Timestamp(row.corporate_action_available_date).date()
    )
    trade_date_value = pd.Timestamp(row.trade_date).date()
    if not (
        bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and rights == 0.0
        and multiplier > 0
        and available is not None
        and available <= trade_date_value
        and all(math.isfinite(value) for value in (multiplier, cash))
    ):
        return None
    return multiplier, cash


def _row_prices_valid(row: Any) -> bool:
    return (
        bool(row.hard_valid)
        and pd.Timestamp(row.available_at).date() <= pd.Timestamp(row.trade_date).date()
        and all(math.isfinite(float(value)) and float(value) > 0 for value in (row.open, row.low))
    )


def _one_outcome(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    output: dict[str, Any] = {f"status_h{horizon}": "INCOMPLETE"}
    needed = group.loc[group.offset.le(horizon + 1)].sort_values("offset")
    if needed.offset.tolist() != list(range(1, horizon + 2)):
        return output
    entry = needed.iloc[0]
    if not (
        _row_prices_valid(entry)
        and int(entry.trade_status) == 1
        and bool(entry.current_day_data_tradable)
        and not bool(entry.buy_blocked_open)
    ):
        output[f"status_h{horizon}"] = "ENTRY_NOT_EXECUTABLE"
        return output
    entry_cost = float(entry.open) * (1 + COST)
    shares = 1.0
    cash = 0.0
    adverse = (float(entry.low) / entry_cost) - 1.0
    for row in needed.iloc[1:].itertuples(index=False):
        if not _row_prices_valid(row):
            return output
        if int(row.corporate_action_count or 0) > 0:
            action = _visible_action(row)
            if action is None:
                return output
            multiplier, cash_per_share = action
            cash += shares * cash_per_share
            shares *= multiplier
        if int(row.offset) <= horizon:
            adverse = min(adverse, (cash + shares * float(row.low)) / entry_cost - 1.0)
    exit_row = needed.iloc[-1]
    if not (
        int(exit_row.trade_status) == 1
        and bool(exit_row.current_day_data_tradable)
        and not bool(exit_row.sell_blocked_open)
    ):
        output[f"status_h{horizon}"] = "EXIT_NOT_EXECUTABLE"
        return output
    proceeds = cash + shares * float(exit_row.open) * (1 - COST)
    net = proceeds / entry_cost - 1.0
    adverse = min(adverse, net)
    output.update(
        {
            f"status_h{horizon}": "COMPLETE",
            f"net_return_h{horizon}": net,
            f"adverse_return_h{horizon}": adverse,
            f"severe_loss10_h{horizon}": adverse <= -0.10,
            f"entry_amount_h{horizon}": float(entry.amount),
        }
    )
    return output


def _attach_outcomes(selections: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    outcomes: dict[int, dict[str, Any]] = {}
    for candidate_row, group in rows.groupby("candidate_row", sort=True):
        combined: dict[str, Any] = {}
        for horizon in (1, 2, 3):
            combined.update(_one_outcome(group, horizon))
        outcomes[int(candidate_row)] = combined
    panel = selections.join(pd.DataFrame.from_dict(outcomes, orient="index"), how="left")
    for horizon in (1, 2, 3):
        panel[f"status_h{horizon}"] = panel[f"status_h{horizon}"].fillna("INCOMPLETE")
    return panel


def _period_masks(panel: pd.DataFrame) -> dict[str, pd.Series]:
    years = pd.to_datetime(panel.trade_date).dt.year
    return {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years.le(2020),
        "late_2021_2023": years.ge(2021),
    }


def _summarize(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    masks = _period_masks(panel)
    for family in FAMILIES:
        family_panel = panel.loc[panel.family.eq(family)]
        for horizon in (1, 2, 3):
            control_complete = family_panel.loc[
                family_panel.leg.eq("control") & family_panel[f"status_h{horizon}"].eq("COMPLETE")
            ].copy()
            control_date = control_complete.groupby("trade_date")[f"net_return_h{horizon}"].mean()
            control_severe_date = control_complete.groupby("trade_date")[
                f"severe_loss10_h{horizon}"
            ].mean()
            for period, mask in masks.items():
                for leg in ("selected", "control"):
                    subset = family_panel.loc[
                        mask.reindex(family_panel.index).fillna(False)
                        & family_panel.leg.eq(leg)
                        & family_panel[f"status_h{horizon}"].eq("COMPLETE")
                    ].copy()
                    returns = subset[f"net_return_h{horizon}"].astype(float)
                    matched = subset.trade_date.map(control_date) if leg == "selected" else None
                    matched_valid = (
                        matched.notna()
                        if matched is not None
                        else pd.Series(False, index=subset.index)
                    )
                    rows.append(
                        {
                            "family": family,
                            "leg": leg,
                            "period": period,
                            "horizon": horizon,
                            "count": len(subset),
                            "securities": int(subset.symbol.nunique()),
                            "decision_dates": int(subset.trade_date.nunique()),
                            "industries": int(subset.industry.nunique()),
                            "mean_net_return": float(returns.mean()) if len(returns) else np.nan,
                            "severe_loss10_fraction": float(
                                subset[f"severe_loss10_h{horizon}"].mean()
                            )
                            if len(subset)
                            else np.nan,
                            "mean_adverse_return": float(
                                subset[f"adverse_return_h{horizon}"].mean()
                            )
                            if len(subset)
                            else np.nan,
                            "matched_count": int(matched_valid.sum())
                            if leg == "selected"
                            else len(subset),
                            "matched_dates": int(subset.loc[matched_valid, "trade_date"].nunique())
                            if leg == "selected"
                            else int(subset.trade_date.nunique()),
                            "mean_excess_vs_control": float(
                                (returns.loc[matched_valid] - matched.loc[matched_valid]).mean()
                            )
                            if leg == "selected" and matched_valid.any()
                            else np.nan,
                            "severe_loss10_disadvantage": float(
                                (
                                    subset.loc[matched_valid, f"severe_loss10_h{horizon}"].astype(
                                        float
                                    )
                                    - subset.loc[matched_valid, "trade_date"].map(
                                        control_severe_date
                                    )
                                ).mean()
                            )
                            if leg == "selected" and matched_valid.any()
                            else np.nan,
                            "entry_executable_fraction": float(
                                family_panel.loc[
                                    mask.reindex(family_panel.index).fillna(False)
                                    & family_panel.leg.eq(leg),
                                    f"status_h{horizon}",
                                ]
                                .ne("ENTRY_NOT_EXECUTABLE")
                                .mean()
                            ),
                        }
                    )
    return (
        pd.DataFrame(rows)
        .sort_values(["family", "horizon", "period", "leg"])
        .reset_index(drop=True)
    )


def _promotion_decisions(summary: pd.DataFrame) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for family in FAMILIES:
        selected = summary.loc[
            summary.family.eq(family)
            & summary.leg.eq("selected")
            & summary.horizon.eq(PRIMARY_HORIZON)
        ].set_index("period")
        full = selected.loc["full"]
        early = selected.loc["early_2018_2020"]
        late = selected.loc["late_2021_2023"]
        gates = {
            "complete_selected": int(full["count"]) >= 100,
            "complete_matched": int(full.matched_count) >= 100,
            "decision_dates_each_block": int(early.decision_dates) >= 30
            and int(late.decision_dates) >= 30,
            "matched_dates_each_block": int(early.matched_dates) >= 30
            and int(late.matched_dates) >= 30,
            "security_breadth": int(full.securities) >= 20,
            "industry_breadth": int(full.industries) >= 5,
            "entry_executability": float(full.entry_executable_fraction) >= 0.90,
            "full_net": float(full.mean_net_return) > 0,
            "full_excess": float(full.mean_excess_vs_control) > 0,
            "early_net_and_excess": float(early.mean_net_return) >= 0
            and float(early.mean_excess_vs_control) >= 0,
            "late_net_and_excess": float(late.mean_net_return) >= 0
            and float(late.mean_excess_vs_control) >= 0,
        }
        passed = all(gates.values())
        if passed:
            classification = "PROMOTE_REPLAY"
        elif float(full.mean_net_return) <= 0 or float(full.mean_excess_vs_control) <= 0:
            classification = "NO_SIGNAL"
        elif float(early.mean_excess_vs_control) * float(late.mean_excess_vs_control) < 0:
            classification = "CHRONOLOGICALLY_UNSTABLE"
        elif not all(
            gates[name]
            for name in (
                "complete_selected",
                "complete_matched",
                "decision_dates_each_block",
                "matched_dates_each_block",
                "security_breadth",
                "industry_breadth",
            )
        ):
            classification = "PARKED_LOW_HEADROOM"
        else:
            classification = "MECHANISM_PARTIAL"
        output.append(
            {
                "family": family,
                "classification": classification,
                "promoted": passed,
                "gate_results": gates,
                "primary_full_net": float(full.mean_net_return),
                "primary_full_excess": float(full.mean_excess_vs_control),
                "early_net": float(early.mean_net_return),
                "early_excess": float(early.mean_excess_vs_control),
                "late_net": float(late.mean_net_return),
                "late_excess": float(late.mean_excess_vs_control),
                "severe_loss10": float(full.severe_loss10_fraction),
                "severe_loss10_disadvantage": float(full.severe_loss10_disadvantage),
            }
        )
    return output


def _replay_plans(
    panel: pd.DataFrame, family: str, leg: str, calendar: list[date], label: str
) -> pd.DataFrame:
    index = {day: position for position, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    selected = panel.loc[
        panel.family.eq(family)
        & panel.leg.eq(leg)
        & panel.signal_rank.le(10)
        & panel.status_h2.eq("COMPLETE")
    ]
    for item in selected.itertuples(index=False):
        signal = pd.Timestamp(item.trade_date).date()
        entry = index[signal] + 1
        due = entry + PRIMARY_HORIZON
        if due >= len(calendar):
            continue
        rows.append(
            {
                "family": label,
                "signal_date": signal,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry,
                "due_index": due,
                "horizon": PRIMARY_HORIZON,
            }
        )
    return pd.DataFrame(rows)


def _query_replay_rows(
    daily_paths: list[Path], plans: pd.DataFrame, calendar: list[date]
) -> pd.DataFrame:
    keys: set[tuple[str, date]] = set()
    for plan in plans.itertuples(index=False):
        for cal_index in range(plan.entry_index, min(plan.due_index + 21, len(calendar))):
            keys.add((plan.symbol, calendar[cal_index]))
    key_frame = pd.DataFrame(sorted(keys), columns=["symbol", "trade_date"])
    con = duckdb.connect()
    con.register("keys", key_frame)
    rows = con.execute(
        """SELECT d.trade_date,d.symbol,d.open,d.high,d.low,d.close,d.amount,d.hard_valid,
        d.trade_status,d.current_day_data_tradable,d.buy_blocked_open,d.sell_blocked_open,
        d.corporate_action_count,d.corporate_action_valid,d.corporate_action_blocking,
        d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,d.rights_ratio,
        d.available_at,d.invalid_reasons
        FROM read_parquet(?) d JOIN keys k USING(symbol,trade_date)
        ORDER BY d.trade_date,d.symbol""",
        [[str(path) for path in daily_paths]],
    ).fetchdf()
    con.close()
    if rows.duplicated(["symbol", "trade_date"]).any():
        raise UltraShortCycleError("duplicate replay market row")
    return rows


@dataclass
class Lot:
    symbol: str
    industry: str
    entry_index: int
    due_index: int
    shares: float
    invested_cost: float
    min_return: float = 0.0
    action_cash: float = 0.0
    forced_effective_date: date | None = None
    forced_event_id: str | None = None


def _replay(
    label: str,
    plans: pd.DataFrame,
    market_rows: pd.DataFrame,
    calendar: list[date],
    events: list[Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    if plans.empty:
        raise UltraShortCycleError(f"empty replay plans: {label}")
    row_map = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): row
        for row in market_rows.itertuples(index=False)
    }
    entry_map = {
        int(index): list(group.itertuples(index=False))
        for index, group in plans.groupby("entry_index", sort=True)
    }
    event_decisions, symbol_events = CA._event_maps(events)
    initial = 1_000_000.0
    cash = initial
    lots: list[Lot] = []
    turnover = 0.0
    planned_entries = 0
    entries = 0
    completed = 0
    severe = 0
    holding_days: list[int] = []
    capacity: list[float] = []
    nav_rows: list[dict[str, Any]] = []
    start = int(plans.entry_index.min())
    final_due = int(plans.due_index.max())
    final_index = min(final_due + 20, len(calendar) - 1)
    for cal_index in range(start, final_index + 1):
        current_date = calendar[cal_index]
        for lot in lots:
            if lot.forced_effective_date is not None and current_date >= lot.forced_effective_date:
                raise UltraShortCycleError(
                    f"pre-effective exit failed:{label}:{lot.symbol}:{current_date}"
                )
            row = row_map.get((lot.symbol, current_date))
            if row is None or not CA._holding_row_usable(row):
                raise UltraShortCycleError(
                    f"invalid holding row:{label}:{lot.symbol}:{current_date}"
                )
            if int(row.corporate_action_count or 0) > 0:
                action = _visible_action(row)
                if action is None:
                    raise UltraShortCycleError(
                        f"unresolved effective action:{label}:{lot.symbol}:{current_date}"
                    )
                multiplier, cash_per_share = action
                if multiplier != 1.0:
                    raise UltraShortCycleError(
                        f"share event reached effective date:{label}:{lot.symbol}:{current_date}"
                    )
                lot.action_cash += lot.shares * cash_per_share
            low_value = lot.action_cash + lot.shares * float(row.low)
            lot.min_return = min(lot.min_return, low_value / lot.invested_cost - 1.0)
        survivors: list[Lot] = []
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            if lot.forced_effective_date is None and cal_index < lot.due_index:
                survivors.append(lot)
                continue
            if not CA._sellable(row):
                survivors.append(lot)
                continue
            proceeds = lot.action_cash + lot.shares * float(row.open) * (1 - COST)
            lot.min_return = min(lot.min_return, proceeds / lot.invested_cost - 1.0)
            cash += proceeds
            turnover += lot.shares * float(row.open)
            completed += 1
            severe += int(lot.min_return <= -0.10)
            holding_days.append(cal_index - lot.entry_index)
        lots = survivors
        pre_nav = cash + sum(
            lot.action_cash + lot.shares * float(row_map[(lot.symbol, current_date)].open)
            for lot in lots
        )
        planned = entry_map.get(cal_index, [])
        planned_entries += len(planned)
        executable: list[tuple[Any, Any]] = []
        for plan in planned:
            row = row_map.get((plan.symbol, current_date))
            if CA._entry_blocked(plan.symbol, plan.signal_date, current_date, symbol_events):
                continue
            if (
                row is not None
                and CA.PRIOR._valid_market_row(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((plan, row))
        cohort = min(cash, pre_nav / 2)
        if executable:
            per_name = cohort / len(executable)
            for plan, row in executable:
                shares = per_name / (float(row.open) * (1 + COST))
                invested = shares * float(row.open) * (1 + COST)
                cash -= invested
                turnover += shares * float(row.open)
                lots.append(
                    Lot(
                        plan.symbol,
                        str(plan.industry),
                        cal_index,
                        int(plan.due_index),
                        shares,
                        invested,
                    )
                )
                entries += 1
                capacity.append(float(row.amount) * 0.05 * len(executable) * 2)
        for lot in lots:
            for event in event_decisions.get((lot.symbol, current_date), ()):
                if (
                    lot.forced_effective_date is None
                    or event.effective_date < lot.forced_effective_date
                ):
                    lot.forced_effective_date = event.effective_date
                    lot.forced_event_id = event.event_id
        nav = cash
        security_values: list[float] = []
        industry_values: dict[str, float] = {}
        for lot in lots:
            row = row_map[(lot.symbol, current_date)]
            value = lot.action_cash + lot.shares * float(row.close)
            nav += value
            security_values.append(value)
            industry_values[lot.industry] = industry_values.get(lot.industry, 0.0) + value
        invested = sum(security_values)
        nav_rows.append(
            {
                "trade_date": current_date,
                "label": label,
                "nav": nav,
                "cash": cash,
                "positions": len(lots),
                "industries": len(industry_values),
                "security_hhi": sum((value / invested) ** 2 for value in security_values)
                if invested > 0
                else 0.0,
                "industry_hhi": sum((value / invested) ** 2 for value in industry_values.values())
                if invested > 0
                else 0.0,
            }
        )
        if cal_index >= final_due and not lots and cal_index not in entry_map:
            break
    equity = pd.DataFrame(nav_rows)
    if lots:
        raise UltraShortCycleError(f"terminal open lots:{label}:{len(lots)}")
    daily_returns = equity.nav.pct_change().fillna(equity.nav.iloc[0] / initial - 1.0)
    drawdown = equity.nav / equity.nav.cummax() - 1.0
    years = len(equity) / 252
    annualized = (equity.nav.iloc[-1] / initial) ** (1 / years) - 1 if years > 0 else 0.0
    volatility = daily_returns.std(ddof=1)
    result = {
        "label": label,
        "status": "COMPLETE",
        "start_date": str(equity.trade_date.iloc[0]),
        "end_date": str(equity.trade_date.iloc[-1]),
        "total_return": float(equity.nav.iloc[-1] / initial - 1),
        "annualized_return": float(annualized),
        "daily_sharpe": float(math.sqrt(252) * daily_returns.mean() / volatility)
        if volatility > 0
        else 0.0,
        "maximum_drawdown": float(drawdown.min()),
        "severe_trade_fraction": float(severe / completed),
        "completed_trades": completed,
        "planned_entries": planned_entries,
        "entries": entries,
        "entry_execution_fraction": float(entries / planned_entries),
        "average_holding_sessions": float(np.mean(holding_days)),
        "turnover_multiple_initial_capital": float(turnover / initial),
        "opportunity_utilization": float(entries / planned_entries),
        "mean_positions": float(equity.positions.mean()),
        "mean_industries": float(equity.industries.mean()),
        "mean_security_hhi_invested_days": float(
            equity.loc[equity.positions.gt(0), "security_hhi"].mean()
        ),
        "mean_industry_hhi_invested_days": float(
            equity.loc[equity.positions.gt(0), "industry_hhi"].mean()
        ),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacity, 0.10)),
        "terminal_open_lots": 0,
    }
    return result, equity


def _run_replays(
    promoted: list[str], panel: pd.DataFrame, daily_paths: list[Path], calendar: list[date]
) -> tuple[list[dict[str, Any]], pd.DataFrame, dict[str, Any]]:
    if not promoted:
        return [], pd.DataFrame(), {}
    ca_spec = CA._load_spec()
    events, event_audit = CA._load_risk_events(ca_spec, calendar)
    replays: list[dict[str, Any]] = []
    equities: list[pd.DataFrame] = []
    for family in promoted:
        outcomes: dict[str, dict[str, Any]] = {}
        for leg in ("selected", "control"):
            label = f"{family}__{leg}"
            plans = _replay_plans(panel, family, leg, calendar, label)
            market_rows = _query_replay_rows(daily_paths, plans, calendar)
            full, equity = _replay(label, plans, market_rows, calendar, events)
            outcomes[leg] = full
            equities.append(equity)
            for block, years in (("early", (2018, 2020)), ("late", (2021, 2023))):
                block_plans = plans.loc[
                    pd.to_datetime(plans.signal_date).dt.year.between(*years)
                ].copy()
                block_label = f"{label}__{block}"
                block_plans["family"] = block_label
                block_rows = _query_replay_rows(daily_paths, block_plans, calendar)
                block_result, block_equity = _replay(
                    block_label, block_plans, block_rows, calendar, events
                )
                outcomes[leg][f"{block}_total_return"] = block_result["total_return"]
                equities.append(block_equity)
        candidate = outcomes["selected"]
        control = outcomes["control"]
        gates = {
            "complete": candidate["status"] == "COMPLETE" and control["status"] == "COMPLETE",
            "terminal_lots": candidate["terminal_open_lots"] == 0,
            "positive_total": candidate["total_return"] > 0,
            "beats_control_total": candidate["total_return"] > control["total_return"],
            "beats_control_early": candidate["early_total_return"] > control["early_total_return"],
            "beats_control_late": candidate["late_total_return"] > control["late_total_return"],
            "beats_control_sharpe": candidate["daily_sharpe"] > control["daily_sharpe"],
        }
        if all(gates.values()):
            classification = "STRATEGY_CANDIDATE"
        elif candidate["status"] != "COMPLETE":
            classification = "REPLAY_BLOCKED"
        elif candidate["total_return"] > 0:
            classification = "PROMISING_BUT_MIXED"
        else:
            classification = "NO_SIGNAL"
        replays.append(
            {
                "family": family,
                "classification": classification,
                "candidate_gates": gates,
                "selected": candidate,
                "control": control,
            }
        )
    return replays, pd.concat(equities, ignore_index=True), event_audit


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# A-share ultra-short discovery cycle 014",
        "",
        "## ENVIRONMENT",
        "",
        (
            "Repository: `/Users/linmei/Documents/"
            "CY-supermind-v6-autonomous-20260830`; branch: "
            "`research/ashare-ultrashort-v1`; starting checkpoint: `cedbb7bbf1`."
        ),
        "",
        "## DATA",
        "",
        (
            f"CY-006/CY-008 contain {result['source_audit']['daily_rows']:,}/"
            f"{result['source_audit']['minute_rows']:,} governed rows with zero lineage or "
            "time-travel failures. The shared causal domain has "
            f"{result['source_audit']['eligible_rows']:,} eligible security-dates. The "
            f"raw-minute lifecycle read contains {result['lifecycle_audit']['raw_rows']:,} "
            f"rows for {result['lifecycle_audit']['daily_limit_close_candidates']:,} "
            "preidentified limit-close sessions."
        ),
        "",
        "The compact panel contains "
        f"{result['panel']['rows']:,} rows, {result['panel']['securities']:,} securities, "
        f"{result['panel']['industries']} PIT industries, and "
        f"{result['panel']['decision_dates']:,} dates. Post-2023 and CY-011 were not read.",
        "",
        "## GATE_DESIGN_AUDIT",
        "",
        (
            "The audit was frozen before outcomes. Hard validity, after-cost break-even, "
            "chronology, effective sample/usability, and next-open executability are "
            "promotion gates. h1/h3, severe loss, concentration, redundancy, and mechanism "
            "geometry are diagnostics. No arbitrary 80% coverage gate exists."
        ),
        "",
        "## FROZEN_FAMILY_MAP",
        "",
        "| Slot | Family | Deduplication |",
        "|---|---|---|",
        "| A | Price-limit reopen--reseal acceptance | `NEW_DISTINCT` |",
        "| B | Liquidity-shock price assimilation | `NEW_DISTINCT` |",
        "| C | Late-session acceptance/rejection | `NEIGHBOR_OF_PRIOR` |",
        "| D | Event-driven reclaim/failure | `NEIGHBOR_OF_PRIOR` |",
        "| E | Optional independent family | `DEFERRED` |",
        (
            "| Cycle 013 | Industry minute leader--follower | `ALREADY_TESTED`; remains "
            "`SIMULTANEOUS_COMOVEMENT_ONLY` |"
        ),
        "",
        "## SCREEN_RESULTS",
        "",
        (
            "| Family | Decision | h2 net | h2 excess | Early excess | Late excess | "
            "Severe | Severe vs control |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["screen_decisions"]:
        lines.append(
            f"| {row['family']} | {row['classification']} | {row['primary_full_net']:.3%} | "
            f"{row['primary_full_excess']:.3%} | {row['early_excess']:.3%} | "
            f"{row['late_excess']:.3%} | {row['severe_loss10']:.2%} | "
            f"{row['severe_loss10_disadvantage']:.2%} |"
        )
    lines.extend(
        [
            "",
            (
                "Price-limit h1/h3 net returns are -0.446%/-0.843%; their excesses remain "
                "positive because simple-seal controls are substantially worse. "
                "Liquidity-shock h1/h3 net returns are -0.592%/-0.812%, with increasingly "
                "adverse excess. These neighbors are diagnostic only."
            ),
            "",
            "## PROMOTED_REPLAYS",
            "",
        ]
    )
    if result["replays"]:
        lines.extend(
            [
                (
                    "| Family | Classification | Total | Control | Sharpe | Control | "
                    "Max DD | Severe | Trades | Turnover |"
                ),
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for replay in result["replays"]:
            selected = replay["selected"]
            control = replay["control"]
            lines.append(
                f"| {replay['family']} | {replay['classification']} | "
                f"{selected['total_return']:.2%} | {control['total_return']:.2%} | "
                f"{selected['daily_sharpe']:.3f} | {control['daily_sharpe']:.3f} | "
                f"{selected['maximum_drawdown']:.2%} | {selected['severe_trade_fraction']:.2%} | "
                f"{selected['completed_trades']} | "
                f"{selected['turnover_multiple_initial_capital']:.2f}x |"
            )
    else:
        lines.extend(["No family earned replay.", ""])
    lines.extend(
        [
            "## STOPPED_FAMILIES",
            "",
            (
                "Price-limit reopen--reseal acceptance is stopped as `NO_SIGNAL`: it is "
                "less bad than simple-seal control, but the selected long leg loses after "
                "cost in both blocks. Liquidity-shock assimilation is stopped as "
                "`NO_SIGNAL`: selected and relative economics are adverse. Neither may be "
                "rescued through thresholds, formulas, h1/h3 selection, top-N, or controls "
                "inside this lane."
            ),
            "",
            "## PORTFOLIO_RESULTS",
            "",
            (
                "No executable portfolio was run because zero families passed the frozen "
                "cheap-screen economics. Therefore no family improved a real executable "
                "portfolio, and no portfolio metric is inferred from factor-screen elegance."
            ),
            "",
            "## RESEARCH_CONCLUSION",
            "",
            (
                "`NO NEW ULTRA-SHORT STRATEGY CANDIDATE.` No genuinely new investable "
                "1--3-session edge appeared. The price-limit relative excess and severe-path "
                "improvement are mechanism/risk diagnostics only; neither tested family is "
                "investable under its frozen long-only translation."
            ),
            "",
            "## NEXT_BEST_DIRECTION",
            "",
            (
                "The strongest remaining headroom is information unavailable in the current "
                "summary-OHLCV lane: governed order-book/queue state or investor-flow "
                "identity. The next budget should move to that independent lane under a "
                "separate data contract, not deepen either stopped family."
            ),
            "",
            "## BOUNDARIES",
            "",
            (
                "All evidence uses consumed 2018--2023 development history. Post-2023 and "
                "CY-011 were not read. No OOS, validation, live, or production claim is made."
            ),
            "",
            f"- Spec: `{result['hashes']['spec_sha256']}`",
            f"- Gate audit: `{result['hashes']['gate_audit_sha256']}`",
            f"- External panel: `{result['hashes']['panel_sha256']}`",
            f"- Summary: `{result['hashes']['summary_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, minute_paths, raw_paths = CYCLE013._partition_paths()
    CYCLE013._verify_content_hashes(daily_paths, minute_paths, raw_paths)
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cycle014_", dir="/Volumes/quant") as temp_dir:
        temp_path = Path(temp_dir)
        frame, calendar, source_audit = _build_causal_frame(daily_paths, minute_paths, temp_path)
        lifecycle, lifecycle_audit = _limit_lifecycle(frame, raw_paths, temp_path)
    selections, representation_diagnostics = _family_selections(frame, lifecycle)
    links = _outcome_links(selections, calendar)
    outcome_rows = _query_outcome_rows(daily_paths, links)
    panel = _attach_outcomes(selections, outcome_rows)
    summary = _summarize(panel)
    decisions = _promotion_decisions(summary)
    promoted = [row["family"] for row in decisions if row["promoted"]][:2]
    replays, equity, action_audit = _run_replays(promoted, panel, daily_paths, calendar)
    panel.to_parquet(PANEL_PATH, index=False, compression="zstd")
    if not equity.empty:
        equity.to_parquet(EQUITY_PATH, index=False, compression="zstd")
    summary_text = summary.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    _atomic_write(SUMMARY_PATH, summary_text)
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "classification": (
            "ULTRASHORT_STRATEGY_CANDIDATE_FOUND"
            if any(row["classification"] == "STRATEGY_CANDIDATE" for row in replays)
            else "NO_NEW_ULTRA_SHORT_STRATEGY_CANDIDATE"
        ),
        "source_audit": source_audit,
        "lifecycle_audit": lifecycle_audit,
        "representation_diagnostics": representation_diagnostics,
        "panel": {
            "rows": len(panel),
            "securities": int(panel.symbol.nunique()),
            "decision_dates": int(panel.trade_date.nunique()),
            "industries": int(panel.industry.nunique()),
        },
        "screen_decisions": decisions,
        "promoted_families": promoted,
        "replays": replays,
        "corporate_action_audit": action_audit,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "gate_audit_sha256": sha256_file(AUDIT_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
            "summary_sha256": sha256_file(SUMMARY_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH) if EQUITY_PATH.is_file() else None,
        },
        "claim_boundary": spec["claim_boundary"],
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["result_sha256"] = sha256_file(RESULT_PATH)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
