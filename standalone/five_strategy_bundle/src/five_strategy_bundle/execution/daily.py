from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from ..errors import ReproductionError
from ..io import _sql_path


ENTRY_COST = 0.002
EXIT_COST = 0.002


def load_daily(paths: list[Path], symbols: list[str]) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    con = duckdb.connect()
    con.register("registry", registry)
    pieces = " UNION ALL BY NAME ".join(
        f"SELECT *, {priority} AS _source_priority FROM read_parquet('{_sql_path(path)}')"
        for priority, path in enumerate(paths)
    )
    try:
        frame = con.execute(
            f"WITH d AS ({pieces}) SELECT d.* FROM d JOIN registry USING(symbol) "
            "QUALIFY row_number() OVER(PARTITION BY symbol,trade_date ORDER BY _source_priority)=1 "
            "ORDER BY symbol,trade_date"
        ).fetchdf()
    finally:
        con.close()
    frame = frame.drop(columns="_source_priority")
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def legal_state(row: pd.Series, lineage: float) -> bool:
    required = (
        "hard_valid",
        "history_valid",
        "current_valid",
        "corporate_action_valid",
        "current_day_data_tradable",
        "market_rule_valid",
    )
    return bool(
        all(not pd.isna(row.get(field)) and bool(row.get(field)) for field in required)
        and not pd.isna(row.get("corporate_action_blocking"))
        and not bool(row.get("corporate_action_blocking"))
        and not pd.isna(row.get("trade_status"))
        and int(row.trade_status) == 1
        and not pd.isna(row.get("invalid_step_cum"))
        and float(row.invalid_step_cum) == float(lineage)
    )


def legal_buy(row: pd.Series, lineage: float) -> bool:
    return legal_state(row, lineage) and round(float(row.open) * 100) < round(
        float(row.up_limit_price) * 100
    )


def legal_sell_open(row: pd.Series, lineage: float) -> bool:
    return legal_state(row, lineage) and round(float(row.open) * 100) > round(
        float(row.down_limit_price) * 100
    )


def strict_legal_state(row: pd.Series, lineage: float) -> bool:
    """Older Bear-lane legality contract, including zero action events."""
    return bool(
        legal_state(row, lineage)
        and not pd.isna(row.get("corporate_action_count"))
        and int(row.corporate_action_count) == 0
        and float(row.open) > 0
        and float(row.coord_open) > 0
    )


def strict_fixed_target_outcomes(
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    target: float,
    horizon: int,
    profile: str,
    max_path_sessions: int | None = None,
) -> pd.DataFrame:
    """Exact legacy Bear replay: abort on the first changed coordinate lineage."""
    groups = {
        str(symbol): part.sort_values("cal_idx").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        part = groups[str(event.symbol)]
        signal_idx = int(event.signal_cal_idx if hasattr(event, "signal_cal_idx") else event.cal_idx)
        lineage = float(event.invalid_step_cum)
        base = {
            "event_id": event.event_id,
            "mechanism": getattr(event, "mechanism", None),
            "symbol": event.symbol,
            "sleeve": event.sleeve,
            "signal_date": event.signal_date,
            "signal_cal_idx": signal_idx,
            "market_regime": getattr(event, "market_regime", None),
            "profile": profile,
        }
        pool = part.loc[part.cal_idx.gt(signal_idx) & part.cal_idx.le(signal_idx + 3)]
        entry = next(
            (
                row for row in pool.itertuples(index=False)
                if strict_legal_state(pd.Series(row._asdict()), lineage)
                and round(float(row.open) * 100) < round(float(row.up_limit_price) * 100)
            ),
            None,
        )
        if entry is None:
            rows.append({**base, "status": "NO_LEGAL_ENTRY"})
            continue
        entry_idx, entry_price = int(entry.cal_idx), float(entry.coord_open)
        target_price = entry_price * (1 + target)
        result: dict[str, Any] | None = None
        path = part.loc[part.cal_idx.gt(entry_idx)]
        if max_path_sessions is not None:
            path = path.loc[path.cal_idx.le(signal_idx + max_path_sessions)]
        for row in path.itertuples(index=False):
            series = pd.Series(row._asdict())
            if pd.isna(row.invalid_step_cum) or float(row.invalid_step_cum) != lineage:
                result = {**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", "entry_date": entry.trade_date, "entry_cal_idx": entry_idx, "entry_price": entry_price}
                break
            if strict_legal_state(series, lineage) and float(row.coord_high) >= target_price:
                exit_price, reason = target_price, f"TARGET_{int(target * 100)}"
            elif int(row.cal_idx) > entry_idx + horizon and strict_legal_state(series, lineage) and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100):
                exit_price, reason = float(row.coord_open), f"H{horizon}_TIME_STOP"
            else:
                continue
            gross = exit_price / entry_price - 1
            result = {
                **base, "status": "COMPLETED", "entry_date": entry.trade_date,
                "entry_cal_idx": entry_idx, "entry_price": entry_price,
                "exit_date": row.trade_date, "exit_cal_idx": int(row.cal_idx),
                "exit_price": exit_price, "exit_reason": reason,
                "holding_sessions": int(row.cal_idx) - entry_idx,
                "gross_return": gross, "net_return": gross - 0.004,
            }
            break
        rows.append(result or {**base, "status": "INCOMPLETE_PATH", "entry_date": entry.trade_date, "entry_cal_idx": entry_idx, "entry_price": entry_price})
    frame = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def fixed_target_outcomes(
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    target: float,
    horizon: int,
    profile: str,
    split_cost: bool = False,
) -> pd.DataFrame:
    groups = {
        str(symbol): part.sort_values("trade_date").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        part = groups[str(event.symbol)]
        positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
        if len(positions) != 1:
            raise ReproductionError(f"missing signal day: {event.event_id}")
        signal_pos = int(positions[0])
        lineage = float(event.invalid_step_cum)
        entry_pos = next(
            (
                pos
                for pos in range(signal_pos + 1, len(part))
                if int(part.iloc[pos].cal_idx) <= int(event.cal_idx) + 3
                and legal_buy(part.iloc[pos], lineage)
            ),
            None,
        )
        base = {
            "event_id": event.event_id,
            "symbol": event.symbol,
            "sleeve": event.sleeve,
            "signal_date": event.signal_date,
            "signal_cal_idx": int(event.cal_idx),
            "profile": profile,
        }
        if entry_pos is None:
            rows.append({**base, "status": "NO_LEGAL_ENTRY"})
            continue
        entry = part.iloc[entry_pos]
        entry_price = float(entry.coord_open)
        target_price = entry_price * (1 + target)
        horizon_idx = int(entry.cal_idx) + horizon
        target_choice: tuple[int, float] | None = None
        decision_pos: int | None = None
        for pos in range(entry_pos + 1, len(part)):
            row = part.iloc[pos]
            state_valid = legal_state(row, lineage)
            if state_valid and float(row.coord_high) >= target_price:
                target_choice = (pos, target_price)
                break
            if state_valid and int(row.cal_idx) >= horizon_idx:
                decision_pos = pos
                break
        if target_choice is not None:
            exit_pos, exit_price = target_choice
            exit_reason = f"TARGET_{int(target * 100)}"
            exit_decision_idx = int(entry.cal_idx)
        else:
            if decision_pos is None:
                rows.append({**base, "status": "INCOMPLETE_OUTCOME_TAIL", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
                continue
            exit_pos = next(
                (
                    pos
                    for pos in range(decision_pos + 1, len(part))
                    if legal_sell_open(part.iloc[pos], lineage)
                ),
                None,
            )
            if exit_pos is None:
                rows.append({**base, "status": "INCOMPLETE_OUTCOME_TAIL", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
                continue
            exit_price = float(part.iloc[exit_pos].coord_open)
            exit_reason = f"H{horizon}_TIME_STOP"
            exit_decision_idx = int(part.iloc[decision_pos].cal_idx)
        exit_row = part.iloc[exit_pos]
        if part.iloc[entry_pos : exit_pos + 1].invalid_step_cum.ne(lineage).any():
            rows.append({**base, "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY", "entry_date": entry.trade_date, "entry_cal_idx": int(entry.cal_idx), "entry_price": entry_price})
            continue
        gross = exit_price / entry_price - 1
        rows.append(
            {
                **base,
                "status": "COMPLETED",
                "entry_date": entry.trade_date,
                "entry_cal_idx": int(entry.cal_idx),
                "entry_price": entry_price,
                "exit_date": exit_row.trade_date,
                "exit_cal_idx": int(exit_row.cal_idx),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "exit_decision_cal_idx": exit_decision_idx,
                "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
                "gross_return": gross,
                "net_return": gross - ENTRY_COST - EXIT_COST if split_cost else gross - 0.004,
            }
        )
    result = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        result[column] = pd.to_datetime(result[column])
    if (result.entry_date.notna() & result.entry_date.le(result.signal_date)).any():
        raise ReproductionError("same-bar entry")
    return result


def replay_sleeves(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    rank_columns: tuple[str, str, str],
    k_per_sleeve: int,
    daily_cap: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    completed = trades.loc[trades.status.eq("COMPLETED")].copy()
    completed = completed.sort_values(
        ["entry_date", *rank_columns, "event_id"],
        ascending=[True, False, False, False, True],
        kind="mergesort",
    )
    by_date = {date: part for date, part in completed.groupby("entry_date", sort=True)}
    daily_groups = {
        str(symbol): part.sort_values("trade_date").set_index("trade_date")
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    dates = sorted(set(daily.trade_date.unique()))
    states = {
        "MAIN": {"cash": 0.5, "active": {}, "last": {}},
        "CHINEXT": {"cash": 0.5, "active": {}, "last": {}},
    }
    accepted_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []

    def mark(symbol: str, date: pd.Timestamp, field: str) -> float | None:
        group = daily_groups.get(symbol)
        if group is None or date not in group.index:
            return None
        value = group.loc[date, field]
        if isinstance(value, pd.Series):
            value = value.iloc[-1]
        return None if pd.isna(value) else float(value)

    for value in dates:
        date = pd.Timestamp(value)
        if date < completed.entry_date.min() or date > completed.exit_date.max():
            continue
        for sleeve, state in states.items():
            exits = [p for p in state["active"].values() if pd.Timestamp(p["exit_date"]) == date]
            for position in sorted(exits, key=lambda item: item["symbol"]):
                state["cash"] += position["qty"] * float(position["exit_price"]) * (1 - EXIT_COST)
                del state["active"][position["symbol"]]
            # Keep the original producer's accumulation order exactly.  Starting
            # at 0.0 (rather than built-in sum's integer zero) matters at the
            # last bit and is therefore part of the frozen replay contract.
            open_value = 0.0
            for symbol, position in state["active"].items():
                price = mark(symbol, date, "coord_open")
                if price is None:
                    price = state["last"].get(symbol, position["entry_price"])
                open_value += position["qty"] * price
            sleeve_nav = state["cash"] + open_value
            candidates = by_date.get(date, pd.DataFrame())
            if len(candidates):
                candidates = candidates.loc[candidates.sleeve.eq(sleeve)]
            new_count = 0
            for row in candidates.itertuples(index=False):
                reason = None
                if row.symbol in state["active"]:
                    reason = "DUPLICATE_SYMBOL"
                elif len(state["active"]) >= k_per_sleeve:
                    reason = "MAX_K"
                elif new_count >= daily_cap:
                    reason = "DAILY_CAP"
                budget = sleeve_nav / k_per_sleeve
                if reason is None and state["cash"] + 1e-12 < budget:
                    reason = "INSUFFICIENT_CASH"
                if reason:
                    skipped_rows.append({**row._asdict(), "skip_reason": reason})
                    continue
                qty = budget / (float(row.entry_price) * (1 + ENTRY_COST))
                state["cash"] -= budget
                state["active"][row.symbol] = {**row._asdict(), "qty": qty, "entry_outlay": budget}
                accepted_rows.append({**row._asdict(), "qty": qty, "entry_outlay": budget})
                new_count += 1
            close_value = 0.0
            for symbol, position in state["active"].items():
                price = mark(symbol, date, "coord_close")
                if price is not None:
                    state["last"][symbol] = price
                close_value += position["qty"] * state["last"].get(symbol, position["entry_price"])
            nav_rows.append({"trade_date": date, "sleeve": sleeve, "nav": state["cash"] + close_value, "cash": state["cash"], "active": len(state["active"])})
            if state["cash"] < -1e-10 or len(state["active"]) > k_per_sleeve:
                raise ReproductionError("cash or capacity invariant violated")
    accepted, skipped, nav = pd.DataFrame(accepted_rows), pd.DataFrame(skipped_rows), pd.DataFrame(nav_rows)
    combined = nav.pivot(index="trade_date", columns="sleeve", values="nav").ffill().sum(axis=1)
    combined_frame = combined.rename("combined_nav").reset_index()
    returns = combined.pct_change(); returns.iloc[0] = combined.iloc[0] - 1
    drawdown = combined / combined.cummax().clip(lower=1.0) - 1
    years = max((combined.index.max() - combined.index.min()).days / 365.25, 1 / 252)
    metrics = {
        "total_return": float(combined.iloc[-1] - 1),
        "cagr": float(combined.iloc[-1] ** (1 / years) - 1),
        "max_drawdown": float(drawdown.min()),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * math.sqrt(252)) if returns.std(ddof=1) > 0 else 0.0,
    }
    return accepted, skipped, combined_frame, metrics


def replay_shared_router(
    trades: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    k_per_sleeve: int = 30,
    daily_cap: int = 10,
    nav_end: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Exact shared-account replay used by the frozen V28/V29 router."""
    ordered = trades.sort_values(
        ["entry_date", "sleeve", "signal_date", "source_rank_order", "event_id"],
        ascending=[True, True, False, True, True], kind="mergesort",
    )
    by_entry = {date: part for date, part in ordered.groupby("entry_date", sort=True)}
    groups = {
        str(symbol): part.sort_values("trade_date").set_index("trade_date")
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    dates = sorted(pd.to_datetime(daily.trade_date.unique()))
    states = {
        "MAIN": {"cash": 0.5, "active": {}, "last": {}},
        "CHINEXT": {"cash": 0.5, "active": {}, "last": {}},
    }
    accepted_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []

    def mark(symbol: str, date: pd.Timestamp, field: str) -> float | None:
        group = groups.get(symbol)
        if group is None or date not in group.index:
            return None
        value = group.loc[date, field]
        if isinstance(value, pd.Series):
            value = value.iloc[-1]
        return None if pd.isna(value) else float(value)

    first_entry = pd.Timestamp(ordered.entry_date.min())
    last_exit = pd.Timestamp(ordered.exit_date.max()) if nav_end is None else pd.Timestamp(nav_end)
    for date in dates:
        date = pd.Timestamp(date)
        if date < first_entry or date > last_exit:
            continue
        for state in states.values():
            exits = [p for p in state["active"].values() if pd.Timestamp(p["exit_date"]) == date and not str(p["exit_reason"]).startswith("TARGET_")]
            for position in sorted(exits, key=lambda item: item["event_id"]):
                state["cash"] += position["qty"] * float(position["exit_price"]) * (1 - EXIT_COST)
                del state["active"][position["symbol"]]
        open_nav: dict[str, float] = {}
        for sleeve, state in states.items():
            value = 0.0
            for symbol, position in state["active"].items():
                price = mark(symbol, date, "coord_open")
                if price is None:
                    price = state["last"].get(symbol, position["entry_price"])
                value += position["qty"] * price
            open_nav[sleeve] = float(state["cash"] + value)
        entry_rows = by_entry.get(date)
        if entry_rows is not None:
            for sleeve, cohort in entry_rows.groupby("sleeve", sort=True):
                state = states[str(sleeve)]
                new_count = 0
                budget = open_nav[str(sleeve)] / k_per_sleeve
                for row in cohort.itertuples(index=False):
                    reason = None
                    if str(row.symbol) in state["active"]:
                        reason = "ACTIVE_SYMBOL"
                    elif len(state["active"]) >= k_per_sleeve:
                        reason = "MAX_K_30"
                    elif new_count >= daily_cap:
                        reason = "DAILY_CAP_10"
                    elif state["cash"] + 1e-12 < budget:
                        reason = "INSUFFICIENT_CASH"
                    if reason:
                        skipped_rows.append({**row._asdict(), "skip_reason": reason})
                        continue
                    qty = budget / (float(row.entry_price) * (1 + ENTRY_COST))
                    state["cash"] -= budget
                    position = {**row._asdict(), "qty": qty, "entry_outlay": budget}
                    state["active"][str(row.symbol)] = position
                    accepted_rows.append(position)
                    new_count += 1
        for state in states.values():
            exits = [p for p in state["active"].values() if pd.Timestamp(p["exit_date"]) == date and str(p["exit_reason"]).startswith("TARGET_")]
            for position in sorted(exits, key=lambda item: item["event_id"]):
                state["cash"] += position["qty"] * float(position["exit_price"]) * (1 - EXIT_COST)
                del state["active"][position["symbol"]]
        row: dict[str, Any] = {"trade_date": date}
        total_nav = total_value = 0.0
        total_active = 0
        for sleeve, prefix in (("MAIN", "main"), ("CHINEXT", "chinext")):
            state = states[sleeve]
            close_value = 0.0
            for symbol, position in state["active"].items():
                price = mark(symbol, date, "coord_close")
                if price is not None:
                    state["last"][symbol] = price
                close_value += position["qty"] * state["last"].get(symbol, position["entry_price"])
            sleeve_nav = float(state["cash"] + close_value)
            row[f"{prefix}_nav"], row[f"{prefix}_cash"], row[f"{prefix}_active"] = sleeve_nav, float(state["cash"]), len(state["active"])
            total_nav += sleeve_nav; total_value += close_value; total_active += len(state["active"])
        row["combined_nav"], row["active_positions"] = total_nav, total_active
        row["utilization"] = 0.0 if total_nav == 0 else total_value / total_nav
        nav_rows.append(row)
    accepted, skipped, nav = pd.DataFrame(accepted_rows), pd.DataFrame(skipped_rows), pd.DataFrame(nav_rows)
    nav["ret"] = nav.combined_nav.pct_change().fillna(nav.combined_nav.iloc[0] - 1.0)
    if (nav[["main_cash", "chinext_cash"]] < -1e-10).any(axis=None):
        raise ReproductionError("router produced negative cash")
    return accepted, skipped, nav
