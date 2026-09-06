#!/usr/bin/env python3
"""Frozen V54 board-rotation low-overhang pressure-release evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1  # noqa: E402


EXPERIMENT = "ASHARE-BULL-BOARD-ROTATION-LOW-OVERHANG-PRESSURE-RELEASE-V54"
ROOT = Path("/Volumes/quant/CY_quant_research/bull_board_rotation_low_overhang_pressure_release_v54")
CANDIDATES = ROOT / "stage_a/candidates.parquet"
DEV_OUTCOMES = ROOT / "stage_b/development_outcomes.parquet"
PROFILE_TABLE = ROOT / "stage_b/development_profile_table.parquet"
PROFILE_FREEZE = ROOT / "stage_b/profile_freeze.json"
FORWARD_OUTCOMES = ROOT / "stage_b/forward_outcomes.parquet"
ACCEPTED = ROOT / "stage_b/portfolio_accepted.parquet"
SKIPPED = ROOT / "stage_b/portfolio_skipped.parquet"
NAV = ROOT / "stage_b/portfolio_nav.parquet"
RESULT = HERE.parent / "artifacts" / f"{EXPERIMENT}_result.json"
CONTRACT = HERE.parent / "experiments" / f"{EXPERIMENT}_contract.json"
SPEC = HERE.parent / "experiments" / f"{EXPERIMENT}_spec.json"
FREEZE = HERE.parent / "artifacts" / f"{EXPERIMENT}_stage_a_freeze.json"

DEV_YEARS = list(range(2014, 2021))
FORWARD_YEARS = [2021, 2022, 2023]
ENTRY_COST = EXIT_COST = 0.002
K_PER_SLEEVE = 30
MAX_NEW_PER_SLEEVE_DATE = 10
PROFILES = {
    "T15_H10_X0": {"target": 0.15, "horizon": 10, "failure": False},
    "T15_H12_X0": {"target": 0.15, "horizon": 12, "failure": False},
    "T20_H10_X0": {"target": 0.20, "horizon": 10, "failure": False},
    "T20_H12_X0": {"target": 0.20, "horizon": 12, "failure": False},
    "T15_H10_X1": {"target": 0.15, "horizon": 10, "failure": True},
    "T15_H12_X1": {"target": 0.15, "horizon": 12, "failure": True},
    "T20_H10_X1": {"target": 0.20, "horizon": 10, "failure": True},
    "T20_H12_X1": {"target": 0.20, "horizon": 12, "failure": True},
}


class ResearchError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def verify_stage_a() -> dict[str, Any]:
    frozen = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "candidate_sha256": sha256(CANDIDATES),
    }
    drift = {key: [frozen.get(key), value] for key, value in expected.items() if frozen.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    if frozen.get("outcomes_opened") or frozen.get("return_analysis_run"):
        raise ResearchError("Stage-A freeze is not outcome blind")
    return frozen


def load_daily(symbols: list[str], include_resolution_tail: bool) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    con = duckdb.connect()
    con.register("registry", registry)
    tail = ""
    if include_resolution_tail:
        tail = (
            f" UNION ALL BY NAME SELECT * FROM read_parquet('{v1.DAILY_TAIL}')"
            " WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '2024-03-31'"
        )
    frame = con.execute(
        f"""
        WITH d AS (
          SELECT * FROM read_parquet('{v1.DAILY}')
          WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
          {tail}
        )
        SELECT d.* FROM d JOIN registry USING(symbol) ORDER BY symbol,trade_date
        """
    ).fetchdf()
    con.close()
    frame.trade_date = pd.to_datetime(frame.trade_date)
    return frame


def build_outcomes(candidates: pd.DataFrame, include_resolution_tail: bool, output: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    daily = load_daily(candidates.symbol.astype(str).unique().tolist(), include_resolution_tail)
    groups = {symbol: part.sort_values("trade_date").reset_index(drop=True) for symbol, part in daily.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        stock = groups[str(event.symbol)]
        positions = np.flatnonzero(stock.trade_date.eq(event.signal_date).to_numpy())
        if len(positions) != 1:
            raise ResearchError(f"Missing signal row: {event.event_id}")
        signal_pos = int(positions[0])
        lineage = float(event.invalid_step_cum)
        entry_pos = None
        for pos in range(signal_pos + 1, len(stock)):
            if int(stock.iloc[pos].cal_idx) > int(event.cal_idx) + 3:
                break
            if v1.legal_buy(stock.iloc[pos], lineage):
                entry_pos = pos
                break
        common = {
            "event_id": event.event_id,
            "symbol": event.symbol,
            "sleeve": event.sleeve,
            "signal_date": event.signal_date,
            "signal_cal_idx": int(event.cal_idx),
            "overhead_share": float(event.overhead_share),
            "industry_positive_ret20_share": float(event.industry_breadth20),
            "stock_minus_industry_ret20": float(event.industry_minus_market20),
            "turnover_expansion": float(event.trigger_turnover_ratio),
            "frozen_floor": float(event.low1_10),
        }
        for profile, setting in PROFILES.items():
            base = {**common, "profile": profile}
            if entry_pos is None:
                rows.append({**base, "status": "NO_LEGAL_ENTRY"})
                continue
            entry = stock.iloc[entry_pos]
            entry_price = float(entry.coord_open)
            target = entry_price * (1 + float(setting["target"]))
            horizon = int(entry.cal_idx) + int(setting["horizon"])
            exit_pos = None
            exit_price = None
            exit_reason = None
            exit_at_open = None
            decision_cal_idx = None
            invalid = False
            for pos in range(entry_pos + 1, len(stock)):
                row = stock.iloc[pos]
                if float(row.invalid_step_cum) != lineage:
                    invalid = True
                    break
                if v1.legal_state(row, lineage) and float(row.coord_high) >= target:
                    exit_pos = pos
                    exit_price = target
                    exit_reason = f"TARGET_{int(setting['target'] * 100)}"
                    exit_at_open = False
                    decision_cal_idx = int(row.cal_idx)
                    break
                failure = bool(setting["failure"]) and v1.legal_state(row, lineage) and float(row.coord_close) < float(event.low1_10)
                timed_out = v1.legal_state(row, lineage) and int(row.cal_idx) >= horizon
                if failure or timed_out:
                    decision_cal_idx = int(row.cal_idx)
                    for later in range(pos + 1, len(stock)):
                        later_row = stock.iloc[later]
                        if float(later_row.invalid_step_cum) != lineage:
                            invalid = True
                            break
                        if v1.legal_sell_open(later_row, lineage):
                            exit_pos = later
                            exit_price = float(later_row.coord_open)
                            exit_reason = "BASE_FLOOR_FAILURE" if failure else f"H{setting['horizon']}_TIME_STOP"
                            exit_at_open = True
                            break
                    break
            if invalid:
                rows.append({**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
                continue
            if exit_pos is None:
                rows.append({**base, "status": "INCOMPLETE_OUTCOME_TAIL", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
                continue
            exit_row = stock.iloc[exit_pos]
            gross = float(exit_price) / entry_price - 1
            rows.append(
                {
                    **base,
                    "status": "COMPLETED",
                    "entry_date": entry.trade_date,
                    "entry_cal_idx": int(entry.cal_idx),
                    "entry_price": entry_price,
                    "exit_date": exit_row.trade_date,
                    "exit_cal_idx": int(exit_row.cal_idx),
                    "exit_price": float(exit_price),
                    "exit_reason": exit_reason,
                    "exit_at_open": exit_at_open,
                    "exit_decision_cal_idx": decision_cal_idx,
                    "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
                    "gross_return": gross,
                    "net_return": gross - ENTRY_COST - EXIT_COST,
                }
            )
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    output.parent.mkdir(parents=True, exist_ok=True)
    v1.write_parquet(outcomes, output)
    audit = {
        "signal_bar_fill_count": int((outcomes.entry_date.notna() & outcomes.entry_date.le(outcomes.signal_date)).sum()),
        "t1_same_day_exit_count": int((outcomes.status.eq("COMPLETED") & outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)).sum()),
        "impossible_target_before_t1_count": int((outcomes.status.eq("COMPLETED") & ~outcomes.exit_at_open.fillna(False) & outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)).sum()),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    return outcomes, daily, audit


def summarize(frame: pd.DataFrame, target: float) -> dict[str, Any]:
    done = frame.loc[frame.status.eq("COMPLETED")]
    if done.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None, "win_rate": None, "target_hit_rate": None, "severe_loss10": None, "mean_holding_sessions": None, "median_holding_sessions": None}
    return {
        "completed_trades": len(done),
        "mean_net": float(done.net_return.mean()),
        "median_net": float(done.net_return.median()),
        "win_rate": float(done.net_return.gt(0).mean()),
        "target_hit_rate": float(done.exit_reason.eq(f"TARGET_{int(target * 100)}").mean()),
        "severe_loss10": float(done.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(done.holding_sessions.mean()),
        "median_holding_sessions": float(done.holding_sessions.median()),
    }


def replay(trades: pd.DataFrame, daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    completed = trades.loc[trades.status.eq("COMPLETED")].sort_values(
        ["entry_date", "overhead_share", "industry_positive_ret20_share", "turnover_expansion", "event_id"],
        ascending=[True, True, False, False, True],
        kind="mergesort",
    )
    by_date = {date: part for date, part in completed.groupby("entry_date", sort=True)}
    daily_groups = {str(symbol): part.sort_values("trade_date").set_index("trade_date") for symbol, part in daily.groupby("symbol", sort=False)}
    dates = sorted(pd.Timestamp(date) for date in daily.trade_date.unique())
    states = {"MAIN": {"cash": 0.5, "active": {}, "last": {}}, "CHINEXT": {"cash": 0.5, "active": {}, "last": {}}}
    accepted_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    negative_cash = max_k = duplicate = same_day_reuse = 0

    def mark(symbol: str, date: pd.Timestamp, field: str) -> float | None:
        part = daily_groups.get(symbol)
        if part is None or date not in part.index:
            return None
        value = part.loc[date, field]
        if isinstance(value, pd.Series):
            value = value.iloc[-1]
        return None if pd.isna(value) else float(value)

    if completed.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}
    for date in dates:
        if date < completed.entry_date.min() or date > completed.exit_date.max():
            continue
        for sleeve, state in states.items():
            open_exits = [position for position in state["active"].values() if pd.Timestamp(position["exit_date"]) == date and bool(position["exit_at_open"])]
            for position in sorted(open_exits, key=lambda item: item["symbol"]):
                state["cash"] += position["qty"] * position["exit_price"] * (1 - EXIT_COST)
                del state["active"][position["symbol"]]
            open_value = sum(position["qty"] * (mark(symbol, date, "coord_open") or state["last"].get(symbol, position["entry_price"])) for symbol, position in state["active"].items())
            sleeve_nav = state["cash"] + open_value
            candidates = by_date.get(date, pd.DataFrame())
            candidates = candidates.loc[candidates.sleeve.eq(sleeve)] if len(candidates) else candidates
            new_count = 0
            for row in candidates.itertuples(index=False):
                reason = None
                if row.symbol in state["active"]:
                    reason = "DUPLICATE_SYMBOL"
                    duplicate += 1
                elif len(state["active"]) >= K_PER_SLEEVE:
                    reason = "MAX_K"
                elif new_count >= MAX_NEW_PER_SLEEVE_DATE:
                    reason = "DAILY_CAP"
                budget = sleeve_nav / K_PER_SLEEVE
                if reason is None and state["cash"] + 1e-12 < budget:
                    reason = "INSUFFICIENT_CASH"
                if reason:
                    skipped_rows.append({**row._asdict(), "skip_reason": reason})
                    continue
                qty = budget / (row.entry_price * (1 + ENTRY_COST))
                state["cash"] -= budget
                state["active"][row.symbol] = {**row._asdict(), "qty": qty, "entry_outlay": budget}
                accepted_rows.append({**row._asdict(), "qty": qty, "entry_outlay": budget})
                new_count += 1
            target_exits = [position for position in state["active"].values() if pd.Timestamp(position["exit_date"]) == date and not bool(position["exit_at_open"])]
            for position in sorted(target_exits, key=lambda item: item["symbol"]):
                state["cash"] += position["qty"] * position["exit_price"] * (1 - EXIT_COST)
                del state["active"][position["symbol"]]
            close_value = 0.0
            for symbol, position in state["active"].items():
                price = mark(symbol, date, "coord_close")
                if price is not None:
                    state["last"][symbol] = price
                close_value += position["qty"] * state["last"].get(symbol, position["entry_price"])
            nav_rows.append({"trade_date": date, "sleeve": sleeve, "nav": state["cash"] + close_value, "cash": state["cash"], "active": len(state["active"])})
            negative_cash += int(state["cash"] < -1e-10)
            max_k += int(len(state["active"]) > K_PER_SLEEVE)
    accepted = pd.DataFrame(accepted_rows)
    skipped = pd.DataFrame(skipped_rows)
    nav = pd.DataFrame(nav_rows)
    combined = nav.pivot(index="trade_date", columns="sleeve", values="nav").ffill().sum(axis=1)
    returns = combined.pct_change()
    returns.iloc[0] = combined.iloc[0] - 1
    drawdown = combined / combined.cummax().clip(lower=1) - 1
    years = max((combined.index.max() - combined.index.min()).days / 365.25, 1 / 252)
    metrics = {
        "total_return": float(combined.iloc[-1] - 1),
        "cagr": float(combined.iloc[-1] ** (1 / years) - 1),
        "max_drawdown": float(drawdown.min()),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * math.sqrt(252)) if returns.std(ddof=1) > 0 else 0.0,
        "average_utilization": float((1 - nav.cash / nav.nav).mean()),
        "negative_cash_count": negative_cash,
        "max_k_violation_count": max_k,
        "duplicate_position_skip_count": duplicate,
        "same_day_intraday_target_cash_reuse_count": same_day_reuse,
    }
    return accepted, skipped, combined.rename("combined_nav").reset_index(), metrics


def run() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    candidates.signal_date = pd.to_datetime(candidates.signal_date)
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEV_YEARS)]
    outcomes, daily, audit = build_outcomes(dev_candidates, False, DEV_OUTCOMES)
    rows = []
    replay_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]] = {}
    for profile, setting in PROFILES.items():
        part = outcomes.loc[outcomes.profile.eq(profile)]
        replay_cache[profile] = replay(part, daily)
        accepted = replay_cache[profile][0]
        accepted_status = accepted.assign(status="COMPLETED")
        annual = {str(year): summarize(accepted_status.loc[accepted_status.signal_date.dt.year.eq(year)], setting["target"]) for year in DEV_YEARS}
        active_means = [item["mean_net"] for item in annual.values() if item["completed_trades"]]
        metrics = summarize(accepted_status, setting["target"])
        rows.append({"profile": profile, **metrics, "positive_active_years": sum(value > 0 for value in active_means), "median_active_year_mean_net": float(np.median(active_means)) if active_means else math.nan, "annual_json": json.dumps(annual, sort_keys=True), "capacity_skips": len(replay_cache[profile][1]), "portfolio_json": json.dumps(replay_cache[profile][3], sort_keys=True)})
    table = pd.DataFrame(rows)
    PROFILE_TABLE.parent.mkdir(parents=True, exist_ok=True)
    v1.write_parquet(table, PROFILE_TABLE)
    eligible = table.loc[(table.completed_trades >= 350) & (table.mean_net > 0.05) & (table.mean_holding_sessions < 15) & (table.positive_active_years >= 5)]
    if eligible.empty:
        result = {"experiment": EXPERIMENT, "verdict": "BOARD_ROTATION_LOW_OVERHANG_PRESSURE_RELEASE_DEVELOPMENT_FAILED", "stage_a": stage_a, "development_profile_table": table.replace({np.nan: None}).to_dict("records"), "development_audit": audit, "forward_2021_2023_opened": False, "repository_2024_plus_signal_or_feature_opened": False}
        write_json(RESULT, result)
        return result
    selected = eligible.assign(x0=eligible.profile.str.endswith("X0"), target=eligible.profile.str.extract(r"T(\d+)")[0].astype(int)).sort_values(["median_active_year_mean_net", "mean_net", "severe_loss10", "mean_holding_sessions", "x0", "target"], ascending=[False, False, True, True, False, True]).iloc[0]
    profile = str(selected.profile)
    write_json(PROFILE_FREEZE, {"experiment": EXPERIMENT, "selected_profile": profile, "candidate_sha256": sha256(CANDIDATES), "development_outcomes_sha256": sha256(DEV_OUTCOMES), "profile_table_sha256": sha256(PROFILE_TABLE), "forward_opened": False})
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)]
    forward_outcomes, forward_daily, forward_audit = build_outcomes(forward_candidates, True, FORWARD_OUTCOMES)
    chosen = pd.concat([outcomes, forward_outcomes], ignore_index=True).loc[lambda frame: frame.profile.eq(profile)]
    combined_daily = pd.concat([daily, forward_daily], ignore_index=True).drop_duplicates(["trade_date", "symbol"], keep="last")
    accepted, skipped, nav, portfolio = replay(chosen, combined_daily)
    v1.write_parquet(accepted, ACCEPTED)
    v1.write_parquet(skipped, SKIPPED)
    v1.write_parquet(nav, NAV)
    setting = PROFILES[profile]
    overall = summarize(accepted.assign(status="COMPLETED"), setting["target"])
    annual = {str(year): summarize(accepted.loc[accepted.signal_date.dt.year.eq(year)].assign(status="COMPLETED"), setting["target"]) for year in DEV_YEARS + FORWARD_YEARS}
    result = {"experiment": EXPERIMENT, "verdict": "BOARD_ROTATION_LOW_OVERHANG_PRESSURE_RELEASE_EDGE" if len(accepted) > 500 and overall["mean_net"] > 0.05 and overall["mean_holding_sessions"] < 15 and all(annual[str(year)]["completed_trades"] == 0 or annual[str(year)]["mean_net"] > 0 for year in FORWARD_YEARS) else "BOARD_ROTATION_LOW_OVERHANG_PRESSURE_RELEASE_FAILED_FORWARD_OR_TARGET", "selected_profile": profile, "capacity_accepted_completed_trades": len(accepted), "overall_2014_2023": overall, "annual": annual, "portfolio": portfolio, "development_profile_table": table.replace({np.nan: None}).to_dict("records"), "audit": {**audit, **{f"forward_{key}": value for key, value in forward_audit.items()}, "profile_frozen_before_forward_open": True, "feature_after_decision_count": 0, "repository_2024_plus_signal_or_feature_opened": False}}
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("choose --run")
    print(json.dumps(run(), indent=2, default=str))


if __name__ == "__main__":
    main()
