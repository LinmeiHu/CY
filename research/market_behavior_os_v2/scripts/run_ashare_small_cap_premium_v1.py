#!/usr/bin/env python3
"""Run the frozen canonical A-share small-cap-premium experiment."""

from __future__ import annotations

import hashlib
import json
import math
import os
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
SPEC_PATH = PROGRAM / "experiments/ASHARE-SMALL-CAP-PREMIUM-V1_spec.json"
TABLE_PATH = PROGRAM / "artifacts/ASHARE-SMALL-CAP-PREMIUM-V1_bucket_table.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-SMALL-CAP-PREMIUM-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-SMALL-CAP-PREMIUM-V1_report.md"
EXPECTED_SPEC_SHA256 = "2587418845f3c80baead66e86133d7978b34e0864fa28b6e91add54096b10c1c"
START = date(2018, 1, 2)
END = date(2023, 12, 29)
GEN_END = date(2020, 12, 31)
VALIDATION_START = date(2021, 1, 1)
HORIZON = 20
MEMORY_LIMIT = "6GB"
THREADS = 2


class SmallCapPremiumError(RuntimeError):
    """Fail-closed experiment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise SmallCapPremiumError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_FORWARD_OUTCOME_ACCESS":
        raise SmallCapPremiumError("spec is not frozen")
    for binding in spec["inputs"].values():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SmallCapPremiumError(f"bound input changed: {path}")
    return spec


def _validate_input(spec: dict[str, Any]) -> tuple[list[Path], dict[str, Any]]:
    registry = json.loads(_resolve(spec["inputs"]["data_asset_registry"]["path"]).read_text())
    asset = {row["asset_id"]: row for row in registry["assets"]}.get("CY-006")
    if (
        asset is None
        or asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or not asset.get("quality_evidence", {}).get("gate_pass")
    ):
        raise SmallCapPremiumError("CY-006 activation changed")
    manifest_path = _resolve(spec["inputs"]["cy006_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text())
    root = Path(manifest["root"])
    by_year = {
        int(row["path"].split("partition_year=")[1].split("/")[0]): row for row in manifest["files"]
    }
    paths: list[Path] = []
    identities: list[dict[str, Any]] = []
    for year in range(2018, 2024):
        binding = by_year.get(year)
        if binding is None:
            raise SmallCapPremiumError(f"manifest lacks {year}")
        path = root / binding["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(binding["size"])
            or sha256_file(path) != binding["sha256"]
        ):
            raise SmallCapPremiumError(f"partition mismatch: {year}")
        paths.append(path)
        identities.append(
            {
                "year": year,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": binding["sha256"],
            }
        )
    return paths, {
        "asset_id": "CY-006",
        "manifest_sha256": sha256_file(manifest_path),
        "partitions": identities,
    }


def _connect(temp_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    connection.execute(f"SET threads={THREADS}")
    connection.execute("SET preserve_insertion_order=false")
    if temp_path is not None:
        connection.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    return connection


def _build_signal_panel(
    paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    connection = _connect(temp_path)
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    audit = connection.execute(
        """
        SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
          sum((available_at>decision_at)::INTEGER),
          sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
          sum((trade_date>DATE '2023-12-29')::INTEGER)
        FROM source
        """
    ).fetchone()
    input_audit = {
        "rows": int(audit[0]),
        "symbols": int(audit[1]),
        "first_date": str(audit[2]),
        "last_date": str(audit[3]),
        "time_travel_rows": int(audit[4]),
        "hard_valid_lineage_failures": int(audit[5]),
        "post_2023_rows_read": int(audit[6]),
    }
    if (
        input_audit["first_date"] != START.isoformat()
        or input_audit["last_date"] != END.isoformat()
        or input_audit["time_travel_rows"]
        or input_audit["hard_valid_lineage_failures"]
        or input_audit["post_2023_rows_read"]
    ):
        raise SmallCapPremiumError(f"input audit failed: {input_audit}")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source)
        """
    )
    calendar = [
        row[0]
        for row in connection.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()
    ]
    connection.execute(
        """
        CREATE TEMP TABLE base AS
        SELECT s.*,c.cal_idx,
          (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
           AND s.trading_state_valid IS TRUE AND s.industry_valid IS TRUE
           AND s.float_valid IS TRUE AND s.corporate_action_valid IS TRUE
           AND s.market_valid IS TRUE AND s.market_rule_valid IS TRUE
           AND s.historical_identity_valid IS TRUE
           AND s.corporate_action_blocking IS FALSE AND coalesce(s.rights_ratio,0)=0
           AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
           AND s.open>0 AND s.close>0 AND s.high>=greatest(s.open,s.close)
           AND s.low<=least(s.open,s.close) AND s.volume>=0 AND s.amount>=0) AS history_valid,
          (s.hard_valid IS TRUE AND s.trade_status=1
           AND s.current_day_data_tradable IS TRUE AND s.is_st IS FALSE) AS current_valid,
          lag(s.close) OVER w AS prior_close,
          lag(s.circulating_shares) OVER w AS prior_circulating_shares,
          lag(s.float_available_date) OVER w AS prior_float_available_date,
          lag(c.cal_idx) OVER w AS prior_cal_idx,
          lag(s.hard_valid IS TRUE AND s.float_valid IS TRUE
              AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at) OVER w
            AS prior_size_valid,
          count(*) FILTER (WHERE s.hard_valid IS TRUE) OVER w120 AS hard_valid_count120,
          lag(c.cal_idx,119) OVER w AS cal_idx_lag119,
          avg(s.amount) OVER p20 AS avg_amount20,
          count(*) OVER p20 AS prior_count20
        FROM source s JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY s.symbol ORDER BY s.trade_date),
          w120 AS (PARTITION BY s.symbol ORDER BY s.trade_date
                   ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
          p20 AS (PARTITION BY s.symbol ORDER BY s.trade_date
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
        """
    )
    selections = connection.execute(
        """
        WITH eligible AS (
          SELECT *,prior_close*prior_circulating_shares AS size_cny
          FROM base
          WHERE cal_idx>=120 AND cal_idx%20=19
            AND history_valid AND current_valid AND prior_size_valid
            AND prior_cal_idx=cal_idx-1 AND hard_valid_count120=120
            AND cal_idx-cal_idx_lag119=119 AND prior_count20=20
            AND avg_amount20>=50000000 AND prior_close>0
            AND prior_circulating_shares>0
            AND prior_float_available_date IS NOT NULL
            AND prior_float_available_date<=trade_date
        ), ranked AS (
          SELECT trade_date,cal_idx,decision_at,available_at,symbol,industry,
            size_cny,avg_amount20,count(*) OVER (PARTITION BY trade_date) AS candidate_count,
            ntile(5) OVER (PARTITION BY trade_date ORDER BY size_cny,symbol) AS size_quintile,
            ntile(10) OVER (PARTITION BY trade_date ORDER BY size_cny,symbol) AS size_decile,
            row_number() OVER (PARTITION BY trade_date ORDER BY size_cny,symbol) AS size_rank
          FROM eligible WHERE isfinite(size_cny)
        )
        SELECT * FROM ranked ORDER BY trade_date,size_rank
        """
    ).fetchdf()
    connection.close()
    if selections.empty or selections.duplicated(["trade_date", "symbol"]).any():
        raise SmallCapPremiumError("invalid signal panel")
    if (selections.candidate_count < 100).any():
        raise SmallCapPremiumError("insufficient candidate breadth")
    return selections, calendar, input_audit


def _path_links(panel: pd.DataFrame, calendar: list[date], maximum: int) -> pd.DataFrame:
    cal_index = {day: index for index, day in enumerate(calendar)}
    rows: list[tuple[int, str, date, int]] = []
    for candidate in panel.itertuples():
        signal = pd.Timestamp(candidate.trade_date).date()
        index = cal_index[signal]
        if index + HORIZON >= len(calendar):
            continue
        available_maximum = min(maximum, len(calendar) - index - 1)
        rows.extend(
            (candidate.Index, candidate.symbol, calendar[index + horizon], horizon)
            for horizon in range(1, available_maximum + 1)
        )
    return pd.DataFrame(rows, columns=["candidate_row", "symbol", "trade_date", "horizon"])


def _query_path_rows(paths: list[Path], links: pd.DataFrame) -> pd.DataFrame:
    if links.empty:
        return pd.DataFrame()
    connection = _connect()
    connection.register("links", links)
    rows = connection.execute(
        """
        SELECT l.candidate_row,l.horizon,d.trade_date,d.symbol,d.open,d.high,d.low,d.close,d.amount,
          d.hard_valid,d.trade_status,d.current_day_data_tradable,
          d.buy_blocked_open,d.sell_blocked_open,d.corporate_action_count,
          d.corporate_action_valid,d.corporate_action_blocking,
          d.corporate_action_available_date,d.share_multiplier,d.cash_per_share,
          d.rights_ratio,d.available_at
        FROM read_parquet(?) d JOIN links l USING(symbol,trade_date)
        ORDER BY l.candidate_row,l.horizon
        """,
        [[str(path) for path in paths]],
    ).fetchdf()
    connection.close()
    return rows


def _visible_action(row: Any) -> tuple[float, float] | None:
    rights = 0.0 if pd.isna(row.rights_ratio) else float(row.rights_ratio)
    multiplier = 1.0 if pd.isna(row.share_multiplier) else float(row.share_multiplier)
    cash_per_share = 0.0 if pd.isna(row.cash_per_share) else float(row.cash_per_share)
    available = (
        None
        if pd.isna(row.corporate_action_available_date)
        else pd.Timestamp(row.corporate_action_available_date).date()
    )
    day = pd.Timestamp(row.trade_date).date()
    valid = (
        bool(row.corporate_action_valid)
        and not bool(row.corporate_action_blocking)
        and rights == 0.0
        and multiplier > 0
        and available is not None
        and available <= day
        and all(math.isfinite(value) for value in (multiplier, cash_per_share))
    )
    return (multiplier, cash_per_share) if valid else None


def _outcome(group: pd.DataFrame, cost: float) -> dict[str, Any]:
    group = group.sort_values("horizon")
    empty = {"entry_status": "MISSING_PATH", "outcome_status": "INCOMPLETE"}
    if len(group) != HORIZON or group.horizon.tolist() != list(range(1, HORIZON + 1)):
        return empty
    entry = group.iloc[0]
    if not (
        bool(entry.hard_valid)
        and int(entry.trade_status) == 1
        and bool(entry.current_day_data_tradable)
        and not bool(entry.buy_blocked_open)
        and pd.Timestamp(entry.available_at).date() <= pd.Timestamp(entry.trade_date).date()
        and math.isfinite(float(entry.open))
        and float(entry.open) > 0
    ):
        return {"entry_status": "NEXT_OPEN_NOT_EXECUTABLE", "outcome_status": "INCOMPLETE"}
    shares, cash, adverse = 1.0, 0.0, math.inf
    entry_open = float(entry.open)
    for row in group.itertuples(index=False):
        if not (
            bool(row.hard_valid)
            and pd.Timestamp(row.available_at).date() <= pd.Timestamp(row.trade_date).date()
            and all(
                math.isfinite(float(value)) and float(value) > 0
                for value in (row.high, row.low, row.close)
            )
        ):
            return {"entry_status": "EXECUTABLE", "outcome_status": "INCOMPLETE"}
        if row.horizon > 1 and int(row.corporate_action_count or 0) > 0:
            action = _visible_action(row)
            if action is None:
                return {"entry_status": "EXECUTABLE", "outcome_status": "INCOMPLETE"}
            multiplier, cash_per_share = action
            cash += shares * cash_per_share
            shares *= multiplier
        adverse = min(adverse, (cash + shares * float(row.low)) / entry_open - 1.0)
    final = group.iloc[-1]
    net = (cash + shares * float(final.close) * (1.0 - cost)) / (entry_open * (1.0 + cost)) - 1.0
    return {
        "entry_status": "EXECUTABLE",
        "outcome_status": "COMPLETE",
        "net_return": net,
        "adverse_excursion": adverse,
        "entry_amount": float(entry.amount),
    }


def _attach_outcomes(panel: pd.DataFrame, rows: pd.DataFrame, cost: float) -> pd.DataFrame:
    outcomes = {
        int(index): _outcome(group, cost)
        for index, group in rows.groupby("candidate_row", sort=True)
    }
    result = panel.join(pd.DataFrame.from_dict(outcomes, orient="index"), how="left")
    result["entry_status"] = result.entry_status.fillna("MISSING_PATH")
    result["outcome_status"] = result.outcome_status.fillna("INCOMPLETE")
    return result


def _bucket_table(panel: pd.DataFrame, period: str) -> pd.DataFrame:
    valid = panel.loc[panel.outcome_status.eq("COMPLETE")].copy()
    rows: list[dict[str, Any]] = []
    for quintile, group in valid.groupby("size_quintile", sort=True):
        returns = group.net_return.astype(float)
        rows.append(
            {
                "period": period,
                "size_quintile": int(quintile),
                "N": len(group),
                "decision_dates": int(group.trade_date.nunique()),
                "mean_net_return": returns.mean(),
                "median_net_return": returns.median(),
                "positive_fraction": (returns > 0).mean(),
                "severe_loss_fraction": (returns <= -0.10).mean(),
                "mean_adverse_excursion": group.adverse_excursion.mean(),
                "entry_execution_coverage": panel.loc[
                    panel.size_quintile.eq(quintile), "entry_status"
                ]
                .eq("EXECUTABLE")
                .mean(),
                "median_candidate_count": group.candidate_count.median(),
                "median_avg_amount20_cny": group.avg_amount20.median(),
                "p10_entry_amount_cny": group.entry_amount.quantile(0.10),
            }
        )
    return pd.DataFrame(rows)


def _spread(table: pd.DataFrame) -> dict[str, Any]:
    indexed = table.set_index("size_quintile")
    means = [float(indexed.loc[index, "mean_net_return"]) for index in range(1, 6)]
    return {
        "q1_mean": means[0],
        "q5_mean": means[-1],
        "q1_minus_q5": means[0] - means[-1],
        "favorable_adjacent_steps": sum(means[index] > means[index + 1] for index in range(4)),
        "q1_median": float(indexed.loc[1, "median_net_return"]),
        "q1_severe_loss": float(indexed.loc[1, "severe_loss_fraction"]),
        "q5_severe_loss": float(indexed.loc[5, "severe_loss_fraction"]),
        "entry_execution_coverage": float(indexed.entry_execution_coverage.min()),
        "decision_dates": int(indexed.decision_dates.min()),
    }


def _period_panel(panel: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    days = pd.to_datetime(panel.trade_date).dt.date
    return panel.loc[(days >= start) & (days <= end)].copy()


def _generation_decision(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[bool, dict[str, Any], pd.DataFrame]:
    periods = {
        "generation_2018_2020": (START, GEN_END),
        "generation_2018_2019": (START, date(2019, 12, 31)),
        "generation_2020": (date(2020, 1, 1), GEN_END),
    }
    tables = []
    stats: dict[str, Any] = {}
    for name, (start, end) in periods.items():
        table = _bucket_table(_period_panel(panel, start, end), name)
        tables.append(table)
        stats[name] = _spread(table)
    gate = spec["generation_gate"]
    full = stats["generation_2018_2020"]
    checks = {
        "minimum_decision_dates": full["decision_dates"] >= gate["minimum_decision_dates"],
        "entry_execution_coverage": full["entry_execution_coverage"]
        >= gate["minimum_entry_execution_coverage"],
        "q1_mean": full["q1_mean"] >= gate["minimum_q1_mean_net_return"],
        "q1_minus_q5": full["q1_minus_q5"] >= gate["minimum_q1_minus_q5"],
        "adjacent_steps": full["favorable_adjacent_steps"]
        >= gate["minimum_favorable_adjacent_steps"],
        "2018_2019_spread": stats["generation_2018_2019"]["q1_minus_q5"] > 0,
        "2020_spread": stats["generation_2020"]["q1_minus_q5"] > 0,
    }
    return all(checks.values()), {"statistics": stats, "checks": checks}, pd.concat(tables)


def _validation_decision(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[bool, dict[str, Any], pd.DataFrame]:
    periods = {"validation_2021_2023": (VALIDATION_START, END)}
    periods.update(
        {f"year_{year}": (date(year, 1, 1), date(year, 12, 31)) for year in range(2021, 2024)}
    )
    tables = []
    stats: dict[str, Any] = {}
    for name, (start, end) in periods.items():
        table = _bucket_table(_period_panel(panel, start, end), name)
        tables.append(table)
        stats[name] = _spread(table)
    gate = spec["validation_gate"]
    full = stats["validation_2021_2023"]
    checks = {
        "q1_minus_q5": full["q1_minus_q5"] >= gate["minimum_q1_minus_q5"],
        "q1_mean": full["q1_mean"] >= gate["minimum_q1_mean_net_return"],
        "each_year_spread": all(
            stats[f"year_{year}"]["q1_minus_q5"] > 0 for year in (2021, 2022, 2023)
        ),
        "severe_loss": full["q1_severe_loss"] - full["q5_severe_loss"]
        <= gate["maximum_q1_severe_loss_disadvantage_vs_q5"],
    }
    return all(checks.values()), {"statistics": stats, "checks": checks}, pd.concat(tables)


@dataclass
class Lot:
    symbol: str
    due_index: int
    shares: float
    action_cash: float = 0.0


def _row_valid(row: Any) -> bool:
    return (
        bool(row.hard_valid)
        and pd.Timestamp(row.available_at).date() <= pd.Timestamp(row.trade_date).date()
        and math.isfinite(float(row.open))
        and float(row.open) > 0
        and math.isfinite(float(row.close))
        and float(row.close) > 0
    )


def _replay(
    selected: pd.DataFrame, path_rows: pd.DataFrame, calendar: list[date], spec: dict[str, Any]
) -> dict[str, Any]:
    cal_index = {day: index for index, day in enumerate(calendar)}
    row_map = {
        (int(row.candidate_row), int(row.horizon)): row for row in path_rows.itertuples(index=False)
    }
    candidate_by_symbol_date = {
        (row.symbol, pd.Timestamp(row.trade_date).date()): int(row.Index)
        for row in selected.itertuples()
    }
    market_map: dict[tuple[str, date], Any] = {}
    for row in path_rows.itertuples(index=False):
        key = (row.symbol, pd.Timestamp(row.trade_date).date())
        market_map.setdefault(key, row)
    entry_map: dict[int, list[Any]] = {}
    final_due = 0
    for signal_date, group in selected.groupby("trade_date", sort=True):
        signal_index = cal_index[pd.Timestamp(signal_date).date()]
        if signal_index + HORIZON + 1 >= len(calendar):
            continue
        entry_map[signal_index + 1] = list(group.itertuples())
        final_due = max(final_due, signal_index + HORIZON + 1)
    initial = float(spec["executable_translation"]["initial_capital_cny"])
    cost = float(spec["executable_translation"]["cost_per_side_bps"]) / 10000.0
    cash, turnover, entries, blocked_exit_delays = initial, 0.0, 0, 0
    lots: list[Lot] = []
    nav_rows: list[dict[str, Any]] = []
    capacities: list[float] = []
    start_index = min(entry_map)
    for index in range(start_index, min(final_due + 21, len(calendar))):
        day = calendar[index]
        for lot in lots:
            row = market_map.get((lot.symbol, day))
            if row is None or not _row_valid(row):
                raise SmallCapPremiumError(f"invalid holding row: {lot.symbol}:{day}")
            if int(row.corporate_action_count or 0) > 0:
                action = _visible_action(row)
                if action is None:
                    raise SmallCapPremiumError(f"unsupported action: {lot.symbol}:{day}")
                multiplier, cash_per_share = action
                lot.action_cash += lot.shares * cash_per_share
                lot.shares *= multiplier
        survivors: list[Lot] = []
        for lot in lots:
            row = market_map[(lot.symbol, day)]
            if index < lot.due_index:
                survivors.append(lot)
            elif (
                int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.sell_blocked_open)
            ):
                value = lot.shares * float(row.open)
                cash += lot.action_cash + value * (1.0 - cost)
                turnover += value
            else:
                blocked_exit_delays += 1
                survivors.append(lot)
        lots = survivors
        planned = entry_map.get(index, [])
        executable: list[tuple[Any, Any]] = []
        for candidate in planned:
            candidate_index = candidate_by_symbol_date[
                (candidate.symbol, pd.Timestamp(candidate.trade_date).date())
            ]
            row = row_map.get((candidate_index, 1))
            if (
                row is not None
                and _row_valid(row)
                and int(row.trade_status) == 1
                and bool(row.current_day_data_tradable)
                and not bool(row.buy_blocked_open)
            ):
                executable.append((candidate, row))
        if executable and cash > 0:
            per_name = cash / len(executable)
            cash_before = cash
            for candidate, row in executable:
                shares = per_name / (float(row.open) * (1.0 + cost))
                value = shares * float(row.open)
                cash -= value * (1.0 + cost)
                turnover += value
                signal_index = cal_index[pd.Timestamp(candidate.trade_date).date()]
                lots.append(Lot(candidate.symbol, signal_index + HORIZON + 1, shares))
                entries += 1
                capacities.append(float(row.amount) * 0.05 * len(executable))
            if cash < -max(1e-6, cash_before * 1e-10):
                raise SmallCapPremiumError("negative replay cash")
        nav = cash
        for lot in lots:
            row = market_map[(lot.symbol, day)]
            nav += lot.action_cash + lot.shares * float(row.close)
        nav_rows.append({"trade_date": day, "nav": nav, "cash": cash, "positions": len(lots)})
        if index >= final_due and not lots and index not in entry_map:
            break
    nav = pd.DataFrame(nav_rows)
    daily = nav.nav.pct_change().fillna(nav.nav.iloc[0] / initial - 1.0)
    drawdown = nav.nav / nav.nav.cummax() - 1.0
    years = len(nav) / 252.0
    annualized = (nav.nav.iloc[-1] / initial) ** (1.0 / years) - 1.0
    sharpe = math.sqrt(252.0) * daily.mean() / daily.std(ddof=1)
    return {
        "start_date": str(nav.trade_date.iloc[0]),
        "end_date": str(nav.trade_date.iloc[-1]),
        "total_return": float(nav.nav.iloc[-1] / initial - 1.0),
        "annualized_return": annualized,
        "maximum_drawdown": float(drawdown.min()),
        "daily_sharpe": sharpe,
        "turnover_multiple_initial_capital": turnover / initial,
        "entries": entries,
        "blocked_exit_delays": blocked_exit_delays,
        "terminal_open_lots": len(lots),
        "mean_positions": float(nav.positions.mean()),
        "mean_invested_fraction": float((1.0 - nav.cash / nav.nav).mean()),
        "p10_capacity_cny_at_5pct_amount": float(np.quantile(capacities, 0.10)),
        "median_capacity_cny_at_5pct_amount": float(np.median(capacities)),
        "target_annualized_met": annualized >= spec["success_target"]["minimum_annualized_return"],
        "target_drawdown_met": float(drawdown.min())
        > spec["success_target"]["maximum_drawdown_must_be_greater_than"],
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# A-share canonical small-cap premium V1",
        "",
        "## Boundary",
        "",
        (
            "This is consumed 2018--2023 development research, not OOS confirmation. "
            "Post-2023 outcomes and CY-011 were not read."
        ),
        "",
        "## Sequential decision",
        "",
        f"- Generation: `{result['generation']['passed']}`",
        f"- Fixed validation opened: `{result['validation']['opened']}`",
        f"- Fixed validation passed: `{result['validation'].get('passed')}`",
        f"- Executable replay run: `{result['replay'] is not None}`",
        "",
        "## Bucket anatomy",
        "",
        "| Period | Q | N | Mean net | Median net | Win rate | Severe loss |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["bucket_records"]:
        lines.append(
            f"| {row['period']} | {row['size_quintile']} | {row['N']:,} | "
            f"{row['mean_net_return']:.3%} | {row['median_net_return']:.3%} | "
            f"{row['positive_fraction']:.2%} | {row['severe_loss_fraction']:.2%} |"
        )
    lines.extend(["", "## Executable translation", ""])
    if result["replay"] is None:
        lines.append("The frozen sequential gate failed, so no portfolio outcome was opened.")
    else:
        replay = result["replay"]
        lines.extend(
            [
            (
                "Frozen rule: equal-weight the smallest size decile every 20 sessions; "
                "next-open entry and post-h20 next-legal-open exit."
            ),
                "",
                f"- Annualized return: {replay['annualized_return']:.2%}",
                f"- Maximum drawdown: {replay['maximum_drawdown']:.2%}",
                f"- Total return: {replay['total_return']:.2%}",
                f"- Daily Sharpe: {replay['daily_sharpe']:.3f}",
                f"- Entries: {replay['entries']:,}",
                f"- User return target met: `{replay['target_annualized_met']}`",
                f"- User drawdown target met: `{replay['target_drawdown_met']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            result["interpretation"],
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Bucket table SHA-256: `{result['hashes']['bucket_table_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    paths, identity = _validate_input(spec)
    with tempfile.TemporaryDirectory(prefix="ashare-small-cap-") as temporary:
        signals, calendar, input_audit = _build_signal_panel(paths, Path(temporary))
    generation_signals = _period_panel(signals, START, GEN_END)
    generation_rows = _query_path_rows(paths, _path_links(generation_signals, calendar, HORIZON))
    generation_panel = _attach_outcomes(
        generation_signals, generation_rows, spec["screen"]["cost_per_side_bps"] / 10000.0
    )
    generation_passed, generation, bucket_table = _generation_decision(generation_panel, spec)
    validation: dict[str, Any] = {"opened": False, "passed": None}
    replay = None
    validation_rows = pd.DataFrame()
    if generation_passed:
        validation_signals = _period_panel(signals, VALIDATION_START, END)
        validation_rows = _query_path_rows(
            paths, _path_links(validation_signals, calendar, HORIZON)
        )
        validation_panel = _attach_outcomes(
            validation_signals,
            validation_rows.loc[validation_rows.horizon <= HORIZON],
            spec["screen"]["cost_per_side_bps"] / 10000.0,
        )
        validation_passed, validation_detail, validation_table = _validation_decision(
            validation_panel, spec
        )
        validation = {"opened": True, "passed": validation_passed, **validation_detail}
        bucket_table = pd.concat([bucket_table, validation_table], ignore_index=True)
        if validation_passed:
            selected = signals.loc[signals.size_decile.eq(1)].copy()
            all_rows = _query_path_rows(paths, _path_links(selected, calendar, HORIZON + 21))
            replay = _replay(selected, all_rows, calendar, spec)
    table_text = bucket_table.to_csv(index=False, lineterminator="\n", float_format="%.10g")
    _atomic_write(TABLE_PATH, table_text)
    if not generation_passed:
        classification = "GENERATION_FAILED_CANONICAL_SMALL_CAP_CLOSED"
        interpretation = (
            "The canonical small-cap premium failed its frozen generation gate. "
            "Validation and replay remained unread."
        )
    elif not validation["passed"]:
        classification = "VALIDATION_FAILED_CANONICAL_SMALL_CAP_CLOSED"
        interpretation = (
            "The canonical small-cap relation did not survive the fixed 2021--2023 "
            "development validation; no quantile or timing rescue is allowed."
        )
    elif replay and replay["target_annualized_met"] and replay["target_drawdown_met"]:
        classification = "USER_OPTIMIZATION_TARGET_MET"
        interpretation = (
            "The independent small-cap engine met both the user's return and drawdown "
            "objectives on consumed development history."
        )
    else:
        classification = "VALIDATED_DEVELOPMENT_ALPHA_TARGET_NOT_MET"
        interpretation = (
            "The small-cap engine survived the sequential screen but did not satisfy "
            "both user-level portfolio objectives."
        )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "classification": classification,
        "claim_boundary": spec["claim_boundary"],
        "input_identity": identity,
        "input_audit": input_audit,
        "signal_domain": {
            "rows": len(signals),
            "decision_dates": int(signals.trade_date.nunique()),
            "securities": int(signals.symbol.nunique()),
            "first_date": str(signals.trade_date.min().date()),
            "last_date": str(signals.trade_date.max().date()),
            "median_candidates_per_date": float(signals.candidate_count.median()),
        },
        "generation": {"passed": generation_passed, **generation},
        "validation": validation,
        "replay": replay,
        "bucket_records": [_clean(row) for row in bucket_table.to_dict("records")],
        "interpretation": interpretation,
        "boundaries": {"post_2023_read": False, "cy011_read": False, "oos_claim": False},
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "bucket_table_sha256": sha256_file(TABLE_PATH),
        },
    }
    _atomic_write(REPORT_PATH, _render_report(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
