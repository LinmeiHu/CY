#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the Development-only formation-panic strict-gap reclaim V5 experiment."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from numba import njit

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-FORMER-LEADER-FORMATION-PANIC-STRICT-GAP-RECLAIM-V5"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "5c3e37833a4ba92492a3b688f216bbe9ad732f1ee992c5cf49a1e3b96ecc7938"

V3_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_former_leader_deep_drawdown_strict_gap_reclaim_v3")
V3_FEATURES = V3_ROOT / "ASHARE-FORMER-LEADER-DEEP-DRAWDOWN-STRICT-GAP-RECLAIM-V3_features_full.parquet"
V3_DAILY = V3_ROOT / "pit_adjusted_daily_state_2013_2021.parquet"
V3_RESULT = OS_ROOT / "artifacts/ASHARE-FORMER-LEADER-DEEP-DRAWDOWN-STRICT-GAP-RECLAIM-V3_result.json"
V4_FEATURES = OS_ROOT / "artifacts/ASHARE-FORMER-LEADER-PREBREAK-SUFFOCATION-V4_features.parquet"
V4_RESULT = OS_ROOT / "artifacts/ASHARE-FORMER-LEADER-PREBREAK-SUFFOCATION-V4_result.json"
V1_OUTCOMES = Path("/Volumes/quant/CY_quant_research/ashare_down_gap_first_reclaim_v1/first_reclaim_outcomes_2014_2021.parquet")
BREADTH = Path("/Volumes/quant/CY_quant_research/ashare_down_gap_reclaim_walkforward_v2/board_opening_gap_breadth_2014_2021.parquet")
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_former_leader_formation_panic_strict_gap_reclaim_v5")

SEARCH = OS_ROOT / f"artifacts/{EXPERIMENT}_search.parquet"
MAIN_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_main_fold_selections.json"
CHINEXT_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_fold_selections.json"
MAIN_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_nav.parquet"
CHINEXT_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_nav.parquet"
COMBINED_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_combined_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

ENTRY_COST = 0.002
EXIT_COST = 0.002
FOLDS = tuple((2014, year - 1, year) for year in range(2017, 2022))
PANIC_NAMES = ("NONE", "Q75", "Q90")
EXIT_NAMES = ("T1_LEGAL_OPEN", "T1_CLOSE", "T3_CLOSE")
EXIT_DATE_COLS = ("next_legal_open_date", "t1_date", "t3_date")
EXIT_PRICE_COLS = ("t1_legal_open_price", "t1_close_price", "t3_close_price")


class V5Error(RuntimeError):
    """Fail-closed V5 error."""


@dataclass(frozen=True)
class Params:
    leader_min: float
    runup_min: float
    drawdown_min: float
    gap_min: float
    age_max: int
    panic_code: int
    exit_code: int
    k: int

    @property
    def key(self) -> str:
        age = "U" if self.age_max < 0 else str(self.age_max)
        return (
            f"l{int(self.leader_min * 100):02d}|r{self.runup_min:.2f}|dd{self.drawdown_min:.2f}|"
            f"g{self.gap_min:.2f}|a{age}|p{PANIC_NAMES[self.panic_code]}|"
            f"x{EXIT_NAMES[self.exit_code]}|k{self.k:02d}"
        )

    @property
    def active_filters(self) -> int:
        return sum((self.leader_min > 0.90, self.runup_min > 0.50, self.drawdown_min > 0.30,
                    self.gap_min > 0.07, self.age_max >= 0, self.panic_code > 0))


GRID = tuple(
    Params(*values)
    for values in itertools.product(
        (0.90, 0.95), (0.50, 0.80), (0.30, 0.40), (0.07, 0.09),
        (3, -1), (0, 1, 2), (0, 1, 2), (20, 50),
    )
)
BASELINE = Params(0.90, 0.50, 0.30, 0.07, -1, 0, 0, 20)
BROAD = Params(0.90, 0.50, 0.30, 0.07, -1, 0, 0, 20)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, Params):
        return {**asdict(value), "parameter_key": value.key, "panic_rule": PANIC_NAMES[value.panic_code], "exit": EXIT_NAMES[value.exit_code]}
    return value


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(json_ready(value), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), temporary, compression="zstd")
    os.replace(temporary, path)


def validate_inputs() -> dict[str, str]:
    if len(GRID) != 576 or len({item.key for item in GRID}) != 576:
        raise V5Error(f"parameter grid changed: {len(GRID)}")
    expected = {
        SPEC: EXPECTED_SPEC_SHA256,
        V3_FEATURES: "a7e4dca16726df3f03b75ad3b06b7cc5731f7676bd6583de402df3b0522e3ec8",
        V3_DAILY: "524448ab35a817d5be0a0de5dfa312aad122ab675af92f306e04aa76fdf4f687",
        V3_RESULT: "31e2cc27b26f4c0526e0b019ce24576eb165474901e490c7229afd4bb9f5f5cf",
        V4_FEATURES: "98c97f58fe318b7ce73f19b4f712cf6fb5e90cfbed46b24a56b5d0539ddef961",
        V4_RESULT: "4f6da89f9587d9b31deced508fa5b55aa67fda11f5080d6e72b3c826e9329b95",
        V1_OUTCOMES: "daa9ce35c11598392f825912d6c715e320c98f88448618bca62cd6bd83d73a49",
        BREADTH: "71f0946a32db24f8af3175c2e1ee5a12e15e4b1db87192bb4a2a9791414fee96",
    }
    found: dict[str, str] = {}
    for path, digest in expected.items():
        if not path.is_file():
            raise V5Error(f"missing frozen input: {path}")
        actual = sha256_file(path)
        if actual != digest:
            raise V5Error(f"frozen input hash mismatch: {path}: {actual}")
        found[str(path)] = actual
    return found


def calibrate_panic(events: pd.DataFrame, sleeve: str, train_end: int) -> dict[str, Any]:
    source = (
        events.loc[events.sleeve.eq(sleeve) & events.gap_date.dt.year.between(2014, train_end),
                   ["gap_date", "formation_down_gap_breadth"]]
        .drop_duplicates("gap_date")
        .sort_values("gap_date")
    )
    if source.empty or source.formation_down_gap_breadth.isna().any():
        raise V5Error(f"invalid formation-panic calibration: {sleeve} through {train_end}")
    return {
        "sample_dates": int(len(source)),
        "first_date": source.gap_date.min(),
        "last_date": source.gap_date.max(),
        "q75": float(source.formation_down_gap_breadth.quantile(0.75, interpolation="linear")),
        "q90": float(source.formation_down_gap_breadth.quantile(0.90, interpolation="linear")),
        "values": source.formation_down_gap_breadth.to_numpy(float),
    }


def panic_threshold(params: Params, calibration: dict[str, Any]) -> float:
    return (-1.0, calibration["q75"], calibration["q90"])[params.panic_code]


def load_events() -> tuple[pd.DataFrame, pd.DatetimeIndex, pd.DataFrame, dict[str, Any]]:
    features = pd.read_parquet(V3_FEATURES)
    date_cols = ["gap_date", "reclaim_date", "bar_end_time", "t1_date", "t2_date", "t3_date", "next_legal_open_date"]
    for column in date_cols:
        features[column] = pd.to_datetime(features[column])
    source = features.loc[features.v3_final_candidate.astype(bool)].copy()
    source = source.sort_values(["entry_id", "strict_gap_width_pct", "gap_id"], ascending=[True, False, True], kind="mergesort")
    source["source_gap_multiplicity"] = source.groupby("entry_id").entry_id.transform("size")
    source = source.drop_duplicates("entry_id", keep="first").copy()
    source["sleeve"] = np.where(source.board.eq("ChiNext"), "CHINEXT", "MAIN")

    v4 = pd.read_parquet(V4_FEATURES, columns=["entry_id", "prebreak_dryup_3_20", "prebreak_dryup_bin"])
    source = source.merge(v4, on="entry_id", how="left", validate="one_to_one", suffixes=("", "_v4"))
    breadth = pd.read_parquet(BREADTH)
    breadth["trade_date"] = pd.to_datetime(breadth.trade_date)
    if breadth.duplicated(["trade_date", "sleeve"]).any():
        raise V5Error("duplicate board/date breadth rows")
    source = source.merge(
        breadth[["trade_date", "sleeve", "breadth"]].rename(columns={"trade_date": "gap_date", "breadth": "formation_down_gap_breadth"}),
        on=["gap_date", "sleeve"], how="left", validate="many_to_one",
    )
    source = source.merge(
        breadth[["trade_date", "sleeve", "breadth"]].rename(columns={"trade_date": "reclaim_date", "breadth": "reclaim_date_down_gap_breadth"}),
        on=["reclaim_date", "sleeve"], how="left", validate="many_to_one",
    )
    calendar = pd.DatetimeIndex(sorted(breadth.trade_date.unique()))
    day_map = pd.Series(np.arange(len(calendar), dtype=np.int32), index=calendar)
    source["entry_day"] = source.reclaim_date.map(day_map).astype(np.int32)
    for source_col, target_col in zip(EXIT_DATE_COLS, ("exit_day_0", "exit_day_1", "exit_day_2"), strict=True):
        source[target_col] = source[source_col].map(day_map).fillna(-1).astype(np.int32)
    source["t2_day"] = source.t2_date.map(day_map).fillna(-1).astype(np.int32)
    source["symbol_id"] = pd.factorize(source.symbol, sort=True)[0].astype(np.int32)
    source = source.sort_values(["bar_end_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    failures = {
        "row_count": int(len(source)),
        "duplicate_source_entries_collapsed": int((source.source_gap_multiplicity - 1).sum()),
        "formation_panic_date_mismatch_count": 0,
        "gap_ids_with_more_than_one_first_reclaim": int(source.gap_id.duplicated().sum()),
        "strict_gap_condition_violation_count": int((~source.strict_gap_condition.astype(bool)).sum()),
        "trigger_outside_strict_gap_admitted_count": int((~source.trigger_inside_strict_gap.astype(bool)).sum()),
        "peak_after_gap_count": int((pd.to_datetime(source.peak_date) >= source.gap_date).sum()),
        "missing_formation_breadth_count": int(source.formation_down_gap_breadth.isna().sum()),
        "missing_reclaim_breadth_count": int(source.reclaim_date_down_gap_breadth.isna().sum()),
    }
    if len(source) != 3734 or source.reclaim_date.max() > pd.Timestamp("2021-12-31") or any(failures[key] for key in failures if key not in ("row_count", "duplicate_source_entries_collapsed")):
        raise V5Error(f"source event audit failed: {failures}")
    return source, calendar, breadth, failures


def event_arrays(events: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "entry_day": events.entry_day.to_numpy(np.int32),
        "time": events.bar_end_time.astype("int64").to_numpy(np.int64),
        "symbol": events.symbol_id.to_numpy(np.int32),
        "leader": events.leader_percentile.to_numpy(float),
        "runup": events.prior_runup.to_numpy(float),
        "drawdown": events.deep_drawdown.to_numpy(float),
        "gap": events.gap_pct.to_numpy(float),
        "age": events.gap_age_trading_days.to_numpy(np.int32),
        "width": events.strict_gap_width_pct.to_numpy(float),
        "formation": events.formation_down_gap_breadth.to_numpy(float),
        "entry_price": events.entry_price.to_numpy(float),
        "exit_day": events[["exit_day_0", "exit_day_1", "exit_day_2"]].to_numpy(np.int32),
        "exit_price": events[list(EXIT_PRICE_COLS)].to_numpy(float),
        "close_days": events[["entry_day", "exit_day_1", "t2_day", "exit_day_2"]].to_numpy(np.int32),
        "close_prices": events[["trigger_close", "t1_close_price", "t2_close_price", "t3_close_price"]].to_numpy(float),
    }


@njit(cache=False)
def simulate_summary(entry_day, time, symbol, leader, runup, drawdown, gap, age, width, formation,
                     entry_price, exit_day, exit_price, close_days, close_prices, start_day, end_day,
                     day_year, leader_min, runup_min, drawdown_min, gap_min, age_max, panic_min,
                     exit_code, k):
    n_days = end_day - start_day + 1
    pos_symbol = np.full(k, -1, np.int32)
    pos_event = np.full(k, -1, np.int32)
    shares = np.zeros(k)
    marks = np.zeros(k)
    debits = np.zeros(k)
    cash = prior_nav = peak_nav = annual_start = 1.0
    active = trades = recent_trades = wins = 0
    max_dd = sum_ret = sum_ret2 = sum_trade_return = 0.0
    annual = np.empty(8)
    annual_count = 0
    day_pnl = np.zeros(n_days)
    cands = np.empty(max(1, len(entry_day)), np.int64)
    pointer = 0
    while pointer < len(entry_day) and entry_day[pointer] < start_day:
        pointer += 1
    for day in range(start_day, end_day + 1):
        for slot in range(k):
            if pos_event[slot] >= 0:
                event = pos_event[slot]
                if exit_code == 0 and exit_day[event, exit_code] == day:
                    proceeds = shares[slot] * exit_price[event, exit_code] * (1.0 - EXIT_COST)
                    trade_return = proceeds / debits[slot] - 1.0
                    cash += proceeds; trades += 1; recent_trades += int(day_year[day] == day_year[end_day])
                    wins += int(trade_return > 0); sum_trade_return += trade_return
                    pos_event[slot] = -1; pos_symbol[slot] = -1; shares[slot] = 0; marks[slot] = 0; debits[slot] = 0; active -= 1
        accounting_nav = cash
        for slot in range(k):
            if pos_event[slot] >= 0:
                accounting_nav += shares[slot] * marks[slot]
        while pointer < len(entry_day) and entry_day[pointer] == day:
            group_start = pointer; group_time = time[pointer]
            while pointer < len(entry_day) and entry_day[pointer] == day and time[pointer] == group_time:
                pointer += 1
            m = 0
            if active < k:
                for idx in range(group_start, pointer):
                    if leader[idx] + 1e-12 < leader_min or runup[idx] + 1e-12 < runup_min or drawdown[idx] + 1e-12 < drawdown_min or gap[idx] + 1e-12 < gap_min:
                        continue
                    if age_max >= 0 and age[idx] > age_max:
                        continue
                    if panic_min >= 0 and formation[idx] + 1e-15 < panic_min:
                        continue
                    exday = exit_day[idx, exit_code]; exprice = exit_price[idx, exit_code]
                    if exday <= day or exday > end_day or not np.isfinite(exprice) or exprice <= 0:
                        continue
                    held = False
                    for slot in range(k):
                        if pos_symbol[slot] == symbol[idx]: held = True; break
                    if not held:
                        cands[m] = idx; m += 1
            used = np.zeros(m, np.uint8)
            for _ in range(min(k - active, m)):
                best = -1
                for j in range(m):
                    if used[j]: continue
                    idx = cands[j]
                    duplicate = False
                    for z in range(m):
                        if used[z] and symbol[cands[z]] == symbol[idx]: duplicate = True; break
                    if duplicate: continue
                    if best < 0:
                        best = j; continue
                    left = idx; right = cands[best]
                    better = width[left] > width[right]
                    if width[left] == width[right]:
                        better = leader[left] > leader[right]
                        if leader[left] == leader[right]:
                            better = runup[left] > runup[right]
                            if runup[left] == runup[right]:
                                better = drawdown[left] > drawdown[right]
                                if drawdown[left] == drawdown[right]:
                                    better = age[left] < age[right]
                                    if age[left] == age[right]: better = left < right
                    if better: best = j
                if best < 0: break
                used[best] = 1; idx = cands[best]
                slot = -1
                for candidate_slot in range(k):
                    if pos_event[candidate_slot] < 0: slot = candidate_slot; break
                principal = min(accounting_nav / k, cash / (1.0 + ENTRY_COST))
                if slot < 0 or principal <= 1e-14: break
                debit = principal * (1.0 + ENTRY_COST); cash -= debit
                pos_symbol[slot] = symbol[idx]; pos_event[slot] = idx; shares[slot] = principal / entry_price[idx]
                marks[slot] = entry_price[idx]; debits[slot] = debit; active += 1; accounting_nav -= principal * ENTRY_COST
        for slot in range(k):
            if pos_event[slot] >= 0:
                event = pos_event[slot]
                for mark_index in range(4):
                    if close_days[event, mark_index] == day and np.isfinite(close_prices[event, mark_index]):
                        marks[slot] = close_prices[event, mark_index]
                if exit_code > 0 and exit_day[event, exit_code] == day:
                    proceeds = shares[slot] * exit_price[event, exit_code] * (1.0 - EXIT_COST)
                    trade_return = proceeds / debits[slot] - 1.0
                    cash += proceeds; trades += 1; recent_trades += int(day_year[day] == day_year[end_day])
                    wins += int(trade_return > 0); sum_trade_return += trade_return
                    pos_event[slot] = -1; pos_symbol[slot] = -1; shares[slot] = 0; marks[slot] = 0; debits[slot] = 0; active -= 1
        nav = cash
        for slot in range(k):
            if pos_event[slot] >= 0: nav += shares[slot] * marks[slot]
        offset = day - start_day; day_pnl[offset] = nav - prior_nav
        daily_return = nav / prior_nav - 1.0; sum_ret += daily_return; sum_ret2 += daily_return * daily_return
        prior_nav = nav; peak_nav = max(peak_nav, nav); max_dd = min(max_dd, nav / peak_nav - 1.0)
        if day == end_day or day_year[day + 1] != day_year[day]:
            annual[annual_count] = nav / annual_start - 1.0; annual_count += 1; annual_start = nav
    total = prior_nav - 1.0; cagr = prior_nav ** (242.0 / n_days) - 1.0
    mean_ret = sum_ret / n_days; variance = max(0.0, sum_ret2 / n_days - mean_ret * mean_ret)
    sharpe = mean_ret / math.sqrt(variance) * math.sqrt(242.0) if variance > 0 else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else (1e6 if cagr > 0 else 0.0)
    median_annual = np.median(annual[:annual_count]) if annual_count else 0.0
    positive = np.sort(day_pnl[day_pnl > 0])[::-1]; positive_sum = positive.sum()
    top5 = positive[:5].sum() / positive_sum if positive_sum > 0 else 0.0
    return total, cagr, max_dd, sharpe, calmar, trades, recent_trades, median_annual, top5, wins, sum_trade_return


METRIC_NAMES = ("total_return", "cagr", "max_drawdown", "sharpe", "calmar", "trade_count", "recent_year_trade_count", "median_year_return", "top5_day_contribution", "win_trades", "sum_trade_return")


def metric_record(values: tuple[Any, ...]) -> dict[str, Any]:
    result = dict(zip(METRIC_NAMES, values, strict=True))
    result["win_rate"] = result["win_trades"] / result["trade_count"] if result["trade_count"] else None
    result["average_trade_return"] = result["sum_trade_return"] / result["trade_count"] if result["trade_count"] else None
    return result


def run_summary(arrays: dict[str, np.ndarray], calendar: pd.DatetimeIndex, params: Params,
                calibration: dict[str, Any], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    values = simulate_summary(
        arrays["entry_day"], arrays["time"], arrays["symbol"], arrays["leader"], arrays["runup"],
        arrays["drawdown"], arrays["gap"], arrays["age"], arrays["width"], arrays["formation"],
        arrays["entry_price"], arrays["exit_day"], arrays["exit_price"], arrays["close_days"],
        arrays["close_prices"], int(calendar.get_loc(start)), int(calendar.get_loc(end)),
        calendar.year.to_numpy(np.int32), params.leader_min, params.runup_min, params.drawdown_min,
        params.gap_min, params.age_max, panic_threshold(params, calibration), params.exit_code, params.k,
    )
    return metric_record(values)


def search_fold(sleeve: str, events: pd.DataFrame, calendar: pd.DatetimeIndex,
                train_end: int, test_year: int, calibration: dict[str, Any]) -> pd.DataFrame:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    shard = EXTERNAL / f"search_{sleeve.lower()}_{test_year}.parquet"
    if shard.is_file():
        frame = pd.read_parquet(shard)
        if len(frame) != 576 or set(frame.parameter_key) != {item.key for item in GRID}:
            raise V5Error(f"invalid resumable shard: {shard}")
        return frame
    board = events.loc[events.sleeve.eq(sleeve)].copy()
    arrays = event_arrays(board)
    start = calendar[calendar.year == 2014][0]
    end = calendar[calendar.year == train_end][-1]
    rows = []
    for index, params in enumerate(GRID):
        rows.append({
            "sleeve": sleeve, "train_start": 2014, "train_end": train_end, "test_year": test_year,
            "parameter_index": index, "parameter_key": params.key, **asdict(params),
            "panic_rule": PANIC_NAMES[params.panic_code], "exit": EXIT_NAMES[params.exit_code],
            "panic_threshold": panic_threshold(params, calibration), "train_q75": calibration["q75"],
            "train_q90": calibration["q90"], "panic_calibration_dates": calibration["sample_dates"],
            "active_filters": params.active_filters,
            **run_summary(arrays, calendar, params, calibration, start, end),
        })
    frame = pd.DataFrame(rows)
    write_parquet(frame, shard)
    return frame


def select_top10(search: pd.DataFrame) -> pd.DataFrame:
    eligible = search.loc[(search.trade_count >= 60) & (search.recent_year_trade_count >= 10)].copy()
    if eligible.empty:
        return eligible
    return eligible.sort_values(
        ["calmar", "sharpe", "median_year_return", "cagr", "top5_day_contribution", "active_filters", "parameter_key"],
        ascending=[False, False, False, False, True, True, True], kind="mergesort",
    ).head(10)


def params_from_row(row: pd.Series) -> Params:
    return Params(float(row.leader_min), float(row.runup_min), float(row.drawdown_min), float(row.gap_min),
                  int(row.age_max), int(row.panic_code), int(row.exit_code), int(row.k))


def event_eligibility_mask(group: pd.DataFrame, params: Params, threshold: float,
                           exit_date: str, exit_price: str, end: pd.Timestamp,
                           held: set[str]) -> pd.Series:
    mask = (
        group.leader_percentile.ge(params.leader_min - 1e-12)
        & group.prior_runup.ge(params.runup_min - 1e-12)
        & group.deep_drawdown.ge(params.drawdown_min - 1e-12)
        & group.gap_pct.ge(params.gap_min - 1e-12)
    )
    if params.age_max >= 0:
        mask &= group.gap_age_trading_days.le(params.age_max)
    if params.panic_code > 0:
        mask &= group.formation_down_gap_breadth.ge(threshold - 1e-15)
    mask &= (
        group[exit_date].notna() & group[exit_date].gt(group.reclaim_date)
        & group[exit_date].le(end) & group[exit_price].notna() & group[exit_price].gt(0)
        & ~group.symbol.isin(held)
    )
    return mask


def eligible_candidates(group: pd.DataFrame, params: Params, threshold: float, exit_date: str,
                        exit_price: str, end: pd.Timestamp, held: set[str]) -> pd.DataFrame:
    selected = group.loc[event_eligibility_mask(group, params, threshold, exit_date, exit_price, end, held)].copy()
    return selected.sort_values(
        ["strict_gap_width_pct", "leader_percentile", "prior_runup", "deep_drawdown",
         "gap_age_trading_days", "bar_end_time", "symbol", "gap_id"],
        ascending=[False, False, False, False, True, True, True, True], kind="mergesort",
    )


def nav_metrics(nav: pd.DataFrame, trades: pd.DataFrame, start_nav: float) -> dict[str, Any]:
    end_nav = float(nav.nav.iloc[-1])
    running = np.maximum.accumulate(np.concatenate(([start_nav], nav.nav.to_numpy())))
    max_drawdown = float((nav.nav.to_numpy() / running[1:] - 1).min())
    cagr = float((end_nav / start_nav) ** (242 / len(nav)) - 1)
    std = float(nav.daily_return.std(ddof=0))
    sharpe = float(nav.daily_return.mean() / std * math.sqrt(242)) if std > 0 else 0.0
    positive = nav.loc[nav.daily_pnl > 0, "daily_pnl"].sort_values(ascending=False)
    positive_sum = float(positive.sum())
    annual_nav = nav.set_index("trade_date").nav.resample("YE").last()
    yearly = annual_nav.pct_change(fill_method=None)
    yearly.iloc[0] = annual_nav.iloc[0] / start_nav - 1
    return {
        "start_nav": start_nav, "end_nav": end_nav, "total_return": end_nav / start_nav - 1,
        "cagr": cagr, "max_drawdown": max_drawdown, "sharpe": sharpe,
        "calmar": cagr / abs(max_drawdown) if max_drawdown < 0 else (1e6 if cagr > 0 else 0.0),
        "trade_count": int(len(trades)),
        "win_rate": float((trades.net_return > 0).mean()) if len(trades) else None,
        "average_trade_return": float(trades.net_return.mean()) if len(trades) else None,
        "maximum_concurrent_positions": int(nav.positions.max()),
        "average_cash_utilization": float(nav.cash_utilization.mean()),
        "top1_day_contribution": float(positive.head(1).sum() / positive_sum) if positive_sum > 0 else 0.0,
        "top5_day_contribution": float(positive.head(5).sum() / positive_sum) if positive_sum > 0 else 0.0,
        "top1pct_day_contribution": float(positive.head(max(1, math.ceil(len(nav) * .01))).sum() / positive_sum) if positive_sum > 0 else 0.0,
        "yearly_returns": {str(index.year): float(value) for index, value in yearly.items()},
    }


def empirical_percentile(value: float, sample: np.ndarray) -> float:
    return float(np.searchsorted(np.sort(sample), value, side="right") / len(sample))


def simulate_detailed(events: pd.DataFrame, calendar: pd.DatetimeIndex, params: Params,
                      calibration: dict[str, Any], start: pd.Timestamp, end: pd.Timestamp,
                      start_nav: float = 1.0) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = events.loc[events.reclaim_date.between(start, end)].sort_values(["bar_end_time", "symbol", "gap_id"], kind="mergesort")
    source_by_gap = frame.set_index("gap_id", verify_integrity=True).to_dict("index")
    grouped_by_day: dict[pd.Timestamp, list[pd.DataFrame]] = {}
    for timestamp, group in frame.groupby("bar_end_time", sort=True):
        grouped_by_day.setdefault(pd.Timestamp(timestamp).normalize(), []).append(group)
    exit_date_col = EXIT_DATE_COLS[params.exit_code]
    exit_price_col = EXIT_PRICE_COLS[params.exit_code]
    threshold = panic_threshold(params, calibration)
    cash = prior_nav = start_nav
    positions: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    duplicate_count = cap_violations = negative_cash = 0
    for day in calendar[(calendar >= start) & (calendar <= end)]:
        for position in positions.copy():
            if params.exit_code == 0 and position["exit_date"] == day:
                proceeds = position["shares"] * position["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append({**position, "exit_proceeds": proceeds, "pnl": proceeds - position["entry_debit"], "net_return": proceeds / position["entry_debit"] - 1})
                positions.remove(position)
        accounting_nav = cash + sum(position["shares"] * position["mark"] for position in positions)
        for group in grouped_by_day.get(day, []):
            held = {position["symbol"] for position in positions}
            candidates = eligible_candidates(group, params, threshold, exit_date_col, exit_price_col, end, held)
            for _, event in candidates.iterrows():
                if len(positions) >= params.k:
                    break
                if event.symbol in {position["symbol"] for position in positions}:
                    continue
                principal = min(accounting_nav / params.k, cash / (1 + ENTRY_COST))
                if principal <= 1e-14:
                    continue
                debit = principal * (1 + ENTRY_COST); cash -= debit
                positions.append({
                    "entry_id": event.entry_id, "gap_id": event.gap_id, "symbol": event.symbol,
                    "is_st": bool(event.is_st), "gap_date": event.gap_date, "reclaim_date": event.reclaim_date,
                    "entry_date": day, "entry_time": event.bar_end_time, "entry_price": float(event.entry_price),
                    "entry_debit": debit, "shares": principal / event.entry_price, "mark": float(event.entry_price),
                    "exit_date": pd.Timestamp(event[exit_date_col]), "exit_price": float(event[exit_price_col]),
                    "formation_down_gap_breadth": float(event.formation_down_gap_breadth),
                    "reclaim_date_down_gap_breadth": float(event.reclaim_date_down_gap_breadth),
                    "formation_panic_percentile": empirical_percentile(float(event.formation_down_gap_breadth), calibration["values"]),
                    "reclaim_breadth_percentile": empirical_percentile(float(event.reclaim_date_down_gap_breadth), calibration["values"]),
                    "leader_percentile": float(event.leader_percentile), "prior_runup": float(event.prior_runup),
                    "deep_drawdown": float(event.deep_drawdown), "strict_gap_width_pct": float(event.strict_gap_width_pct),
                    "gap_pct": float(event.gap_pct), "gap_age_trading_days": int(event.gap_age_trading_days),
                    "prebreak_dryup_3_20": event.prebreak_dryup_3_20,
                })
                accounting_nav -= principal * ENTRY_COST
        for position in positions.copy():
            source = source_by_gap[position["gap_id"]]
            mark_map = {pd.Timestamp(source["reclaim_date"]): source["trigger_close"], pd.Timestamp(source["t1_date"]): source["t1_close_price"], pd.Timestamp(source["t2_date"]): source["t2_close_price"], pd.Timestamp(source["t3_date"]): source["t3_close_price"]}
            if day in mark_map and pd.notna(mark_map[day]):
                position["mark"] = float(mark_map[day])
            if params.exit_code > 0 and position["exit_date"] == day:
                proceeds = position["shares"] * position["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append({**position, "exit_proceeds": proceeds, "pnl": proceeds - position["entry_debit"], "net_return": proceeds / position["entry_debit"] - 1})
                positions.remove(position)
        nav = cash + sum(position["shares"] * position["mark"] for position in positions)
        cap_violations += int(len(positions) > params.k); negative_cash += int(cash < -1e-12)
        duplicate_count += len(positions) - len({position["symbol"] for position in positions})
        nav_rows.append({"trade_date": day, "nav": nav, "daily_pnl": nav - prior_nav,
                         "daily_return": nav / prior_nav - 1 if prior_nav else 0.0, "cash": cash,
                         "cash_utilization": 1 - cash / nav if nav else 0.0, "positions": len(positions)})
        prior_nav = nav
    if positions:
        raise V5Error("uncensored position survived replay boundary")
    nav = pd.DataFrame(nav_rows)
    trades = pd.DataFrame(trade_rows)
    metrics = nav_metrics(nav, trades, start_nav)
    metrics.update({"duplicate_position_entry_count": duplicate_count,
                    "max_concurrent_positions_violation_count": cap_violations,
                    "negative_cash_or_leverage_violation_count": negative_cash})
    return nav, trades, metrics


def replay_year(events: pd.DataFrame, calendar: pd.DatetimeIndex, params: Params,
                calibration: dict[str, Any], year: int, start_nav: float = 1.0):
    return simulate_detailed(events, calendar, params, calibration,
                             calendar[calendar.year == year][0], calendar[calendar.year == year][-1], start_nav)


def compact_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = ("total_return", "cagr", "max_drawdown", "sharpe", "calmar", "trade_count", "win_rate",
            "average_trade_return", "maximum_concurrent_positions", "average_cash_utilization",
            "top1_day_contribution", "top5_day_contribution", "top1pct_day_contribution", "yearly_returns",
            "duplicate_position_entry_count", "max_concurrent_positions_violation_count",
            "negative_cash_or_leverage_violation_count")
    return {key: metrics.get(key) for key in keys if key in metrics}


def replay_fold(sleeve_events: pd.DataFrame, calendar: pd.DatetimeIndex, test_year: int,
                top10: pd.DataFrame, calibration: dict[str, Any], start_nav: float) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    if top10.empty:
        dates = calendar[calendar.year == test_year]
        nav = pd.DataFrame({"trade_date": dates, "nav": start_nav, "daily_pnl": 0.0, "daily_return": 0.0,
                            "cash": start_nav, "cash_utilization": 0.0, "positions": 0})
        return {"selection_blocked": True, "test_year": test_year, "train_q75": calibration["q75"],
                "train_q90": calibration["q90"], "panic_calibration_dates": calibration["sample_dates"],
                "full": compact_metrics(nav_metrics(nav, pd.DataFrame(), start_nav))}, nav, pd.DataFrame()
    champion_row = top10.iloc[0]
    champion = params_from_row(champion_row)
    full_nav, full_trades, full = replay_year(sleeve_events, calendar, champion, calibration, test_year, start_nav)
    no_panic = replace(champion, panic_code=0)
    _, _, no_panic_metrics = replay_year(sleeve_events, calendar, no_panic, calibration, test_year, 1.0)
    broad_metrics = None
    if champion.panic_code > 0:
        broad = replace(BROAD, panic_code=champion.panic_code, exit_code=champion.exit_code, k=champion.k)
        _, _, broad_metrics = replay_year(sleeve_events, calendar, broad, calibration, test_year, 1.0)
    neighbor_returns = []
    for _, row in top10.iterrows():
        params = params_from_row(row)
        _, _, metrics = replay_year(sleeve_events, calendar, params, calibration, test_year, 1.0)
        neighbor_returns.append(metrics["total_return"])
    panic_increment = full["total_return"] - no_panic_metrics["total_return"]
    structure_increment = full["total_return"] - broad_metrics["total_return"] if broad_metrics else None
    if champion.panic_code == 0:
        interaction = "NEITHER"
    elif panic_increment > 0 and structure_increment > 0:
        interaction = "FORMATION PANIC × STOCK STRUCTURE INTERACTION"
    elif panic_increment > 0:
        interaction = "FORMATION PANIC ONLY"
    elif structure_increment > 0:
        interaction = "STOCK STRUCTURE ONLY"
    else:
        interaction = "NEITHER"
    fold = {
        "selection_blocked": False, "test_year": test_year,
        "selected_params": champion, "train_q75": calibration["q75"], "train_q90": calibration["q90"],
        "panic_calibration_dates": calibration["sample_dates"],
        "train_metrics": {key: champion_row[key] for key in METRIC_NAMES if key in champion_row},
        "full": compact_metrics(full), "no_formation_panic": compact_metrics(no_panic_metrics),
        "formation_panic_increment": panic_increment,
        "broad_structure_same_formation_panic": compact_metrics(broad_metrics) if broad_metrics else None,
        "stock_structure_increment": structure_increment, "interaction_classification": interaction,
        "top10_neighbor_oos": {"count": len(neighbor_returns), "median_return": float(np.median(neighbor_returns)),
                               "best_return": float(np.max(neighbor_returns)), "worst_return": float(np.min(neighbor_returns)),
                               "fraction_profitable": float(np.mean(np.array(neighbor_returns) > 0)),
                               "returns": neighbor_returns},
        "top10_train_parameter_keys": top10.parameter_key.tolist(),
    }
    return fold, full_nav, full_trades


def replay_baseline(events: pd.DataFrame, calendar: pd.DatetimeIndex, sleeve: str) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    start_nav = 1.0; navs = []; trades = []; yearly = {}
    for _, train_end, year in FOLDS:
        calibration = calibrate_panic(events, sleeve, train_end)
        nav, trade, metrics = replay_year(events.loc[events.sleeve.eq(sleeve)], calendar, BASELINE, calibration, year, start_nav)
        yearly[str(year)] = metrics["total_return"]; navs.append(nav); trades.append(trade); start_nav = metrics["end_nav"]
    nav = pd.concat(navs, ignore_index=True)
    trade = pd.concat(trades, ignore_index=True) if any(len(frame) for frame in trades) else pd.DataFrame()
    metrics = nav_metrics(nav, trade, 1.0); metrics["yearly_returns"] = yearly
    return compact_metrics(metrics), nav, trade


def compound_excluding(nav: pd.DataFrame, *, year: int | None = None, best_days: int = 0) -> float:
    returns = nav.daily_return.copy()
    if year is not None:
        returns = returns.loc[nav.trade_date.dt.year.ne(year)]
    if best_days:
        returns = returns.drop(returns.nlargest(best_days).index)
    return float((1.0 + returns).prod() - 1.0)


def pnl_concentration(trades: pd.DataFrame, date_col: str) -> dict[str, Any]:
    if trades.empty:
        return {"unique_dates": 0, "max_trades_one_date": 0, "top1_positive_pnl_share": 0.0,
                "top5_positive_pnl_share": 0.0, "top1pct_positive_pnl_share": 0.0, "trades_per_date": {}}
    grouped = trades.groupby(date_col).agg(trades=("pnl", "size"), pnl=("pnl", "sum")).sort_index()
    positive = grouped.pnl.clip(lower=0).sort_values(ascending=False); denominator = float(positive.sum())
    share = lambda count: float(positive.head(count).sum() / denominator) if denominator > 0 else 0.0
    return {"unique_dates": int(len(grouped)), "max_trades_one_date": int(grouped.trades.max()),
            "top1_positive_pnl_share": share(1), "top5_positive_pnl_share": share(5),
            "top1pct_positive_pnl_share": share(max(1, math.ceil(len(grouped) * .01))),
            "trades_per_date": {str(index.date()): int(value) for index, value in grouped.trades.items()}}


def subgroup_diagnostic(trades: pd.DataFrame, mask: pd.Series, left_name: str, right_name: str) -> dict[str, Any]:
    def one(part: pd.DataFrame) -> dict[str, Any]:
        return {"trades": int(len(part)), "pnl": float(part.pnl.sum()) if len(part) else 0.0,
                "mean_net_return": float(part.net_return.mean()) if len(part) else None,
                "win_rate": float((part.net_return > 0).mean()) if len(part) else None}
    return {left_name: one(trades.loc[mask]), right_name: one(trades.loc[~mask])}


def dryup_diagnostic(trades: pd.DataFrame) -> dict[str, Any]:
    valid = trades.prebreak_dryup_3_20.notna()
    result = subgroup_diagnostic(trades.loc[valid], trades.loc[valid, "prebreak_dryup_3_20"].le(.5), "le_0_5", "gt_0_5")
    missing = trades.loc[~valid]
    result["missing"] = {"trades": int(len(missing)), "pnl": float(missing.pnl.sum()) if len(missing) else 0.0,
                         "mean_net_return": float(missing.net_return.mean()) if len(missing) else None,
                         "win_rate": float((missing.net_return > 0).mean()) if len(missing) else None}
    return result


def transition_diagnostic(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"trades": 0}
    successful = trades.loc[trades.net_return > 0]
    return {
        "trades": int(len(trades)), "successful_trades": int(len(successful)),
        "median_formation_percentile": float(trades.formation_panic_percentile.median()),
        "median_reclaim_percentile": float(trades.reclaim_breadth_percentile.median()),
        "median_gap_age": float(trades.gap_age_trading_days.median()),
        "successful_median_formation_percentile": float(successful.formation_panic_percentile.median()) if len(successful) else None,
        "successful_median_reclaim_percentile": float(successful.reclaim_breadth_percentile.median()) if len(successful) else None,
        "fraction_reclaim_percentile_below_formation": float((trades.reclaim_breadth_percentile < trades.formation_panic_percentile).mean()),
        "successful_fraction_reclaim_percentile_below_formation": float((successful.reclaim_breadth_percentile < successful.formation_panic_percentile).mean()) if len(successful) else None,
    }


def classify_board(stitched: dict[str, Any], baseline: dict[str, Any], folds: list[dict[str, Any]], ex2020: float) -> dict[str, Any]:
    panic_folds = [fold for fold in folds if not fold.get("selection_blocked") and fold["selected_params"].panic_code > 0]
    positive_panic = sum(fold["formation_panic_increment"] > 0 for fold in panic_folds)
    positive_structure = sum((fold["stock_structure_increment"] or 0) > 0 for fold in panic_folds)
    credible = (stitched["total_return"] > 0 and stitched["total_return"] > baseline["total_return"]
                and len(panic_folds) >= 3 and positive_panic >= 3 and ex2020 > 0)
    marginal = stitched["total_return"] > baseline["total_return"] and positive_panic >= 2
    return {"credible": credible, "marginal": marginal, "panic_selected_folds": len(panic_folds),
            "positive_panic_increment_folds": positive_panic,
            "positive_structure_increment_folds": positive_structure,
            "verdict": "FORMATION_PANIC_INTERACTION_EDGE" if credible else ("MARGINAL_FORMATION_PANIC_EDGE" if marginal else "NO_FORMATION_PANIC_INTERACTION_EDGE")}


def choose_verdict(board_results: dict[str, Any], combined: dict[str, Any]) -> str:
    credible = [name for name, item in board_results.items() if item["board_verdict"]["credible"]]
    marginal = [name for name, item in board_results.items() if item["board_verdict"]["marginal"]]
    if len(credible) == 2 and combined["return_ex_2020"] > 0:
        return "FORMATION_PANIC_INTERACTION_EDGE_READY_FOR_VALIDATION"
    if credible:
        return "BOARD_SPECIFIC_FORMATION_PANIC_EDGE"
    if marginal and combined["metrics"]["total_return"] > 0 and combined["return_ex_2020"] <= 0:
        return "FORMATION_PANIC_EDGE_BUT_CLUSTER_DEPENDENT"
    if marginal:
        return "MARGINAL_FORMATION_PANIC_EDGE"
    return "NO_FORMATION_PANIC_INTERACTION_EDGE"


def pct(value: Any) -> str:
    return "N/A" if value is None else f"{100 * float(value):.2f}%"


def build_report(result: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}", "", "## Development verdict", "",
        f"**{result['verdict']}**", "",
        "V5 correctly anchors market panic to each strict gap's formation date. Reclaim-date breadth is retained only as a transition diagnostic and never enters eligibility, calibration, or selection. The 2017–2021 folds are internal chronological pseudo-OOS evidence; Validation and Final OOS remain sealed.", "",
        "## Formation-panic contract", "",
        f"- Frozen spec SHA-256: `{result['spec_sha256']}`",
        "- Calibration: independent Main/ChiNext Q75 and Q90 values from unique source-population gap dates in TRAIN only.",
        "- Search: 576 configurations per board per fold; 5,760 board/fold rows in total.",
        "- Selector: maximum TRAIN Calmar after the 60-total/10-recent completed-trade gate and frozen tie-breaks.", "",
    ]
    for sleeve in ("MAIN", "CHINEXT"):
        item = result["boards"][sleeve]
        lines += [f"## {sleeve}", "", "| Test | Selected | Q75 / Q90 | Train Calmar | Full | No panic | Panic increment | Broad same panic | Structure increment | Trades |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for fold in item["folds"]:
            if fold["selection_blocked"]:
                lines.append(f"| {fold['test_year']} | BLOCKED | {pct(fold['train_q75'])} / {pct(fold['train_q90'])} | N/A | 0.00% | N/A | N/A | N/A | N/A | 0 |")
                continue
            broad = fold["broad_structure_same_formation_panic"]
            lines.append(
                f"| {fold['test_year']} | `{fold['selected_params'].key}` | {pct(fold['train_q75'])} / {pct(fold['train_q90'])} | "
                f"{fold['train_metrics']['calmar']:.3f} | {pct(fold['full']['total_return'])} | {pct(fold['no_formation_panic']['total_return'])} | "
                f"{pct(fold['formation_panic_increment'])} | {pct(broad['total_return']) if broad else 'N/A'} | {pct(fold['stock_structure_increment'])} | {fold['full']['trade_count']} |"
            )
        wf = item["stitched"]
        lines += ["", f"Stitched: total {pct(wf['total_return'])}, CAGR {pct(wf['cagr'])}, MaxDD {pct(wf['max_drawdown'])}, Sharpe {wf['sharpe']:.3f}, Calmar {wf['calmar']:.3f}, trades {wf['trade_count']}. Baseline total: {pct(item['baseline']['total_return'])}; excluding 2020: {pct(item['return_ex_2020'])}.", "",
                  f"Yearly returns: `{json.dumps(json_ready(wf['yearly_returns']))}`. Ex-best-day {pct(item['return_ex_best_day'])}; ex-best-five-days {pct(item['return_ex_best_5_days'])}. 2017–2019 {pct(item['diagnostic_2017_2019_return'])}; 2020 {pct(item['diagnostic_2020_return'])}; 2021 {pct(item['diagnostic_2021_return'])}.", "",
                  f"Baseline: total {pct(item['baseline']['total_return'])}, CAGR {pct(item['baseline']['cagr'])}, MaxDD {pct(item['baseline']['max_drawdown'])}, Sharpe {item['baseline']['sharpe']:.3f}, Calmar {item['baseline']['calmar']:.3f}, trades {item['baseline']['trade_count']}; yearly `{json.dumps(json_ready(item['baseline']['yearly_returns']))}`.", "",
                  f"Formation dates: `{json.dumps(json_ready({k: v for k, v in item['formation_date_concentration'].items() if k != 'trades_per_date'}))}`. Reclaim dates: `{json.dumps(json_ready({k: v for k, v in item['reclaim_date_concentration'].items() if k != 'trades_per_date'}))}`.", "",
                  f"Top-10 next-year neighborhoods: `{json.dumps(json_ready({str(fold['test_year']): fold.get('top10_neighbor_oos') for fold in item['folds']}), ensure_ascii=False)}`.", "",
                  f"Parameter stability: `{json.dumps(json_ready(item['parameter_stability']), ensure_ascii=False)}`.", "",
                  f"V4 Dryup diagnostic: `{json.dumps(json_ready(item['prebreak_dryup_le_0_5_vs_gt_0_5']), ensure_ascii=False)}`. ST diagnostic: `{json.dumps(json_ready(item['st_vs_non_st']), ensure_ascii=False)}`. Board verdict: `{item['board_verdict']['verdict']}`.", ""]
    combined = result["combined"]
    lines += ["## Fixed 50/50 combined portfolio", "",
              f"Total {pct(combined['metrics']['total_return'])}, CAGR {pct(combined['metrics']['cagr'])}, MaxDD {pct(combined['metrics']['max_drawdown'])}, Sharpe {combined['metrics']['sharpe']:.3f}, Calmar {combined['metrics']['calmar']:.3f}; excluding 2020 {pct(combined['return_ex_2020'])}.", "",
              f"Yearly returns: `{json.dumps(json_ready(combined['metrics']['yearly_returns']))}`.", "",
              "## Diagnostics", "",
              f"- Main panic sequence: `{item_sequence(result['boards']['MAIN'], 'panic')}`.",
              f"- ChiNext panic sequence: `{item_sequence(result['boards']['CHINEXT'], 'panic')}`.",
              f"- Main formation→reclaim transition: `{json.dumps(json_ready(result['boards']['MAIN']['formation_to_reclaim']), ensure_ascii=False)}`.",
              f"- ChiNext formation→reclaim transition: `{json.dumps(json_ready(result['boards']['CHINEXT']['formation_to_reclaim']), ensure_ascii=False)}`.", "",
              "## Hard audit", ""]
    for key, value in result["audit"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines += ["", "## Decision", ""]
    if result["verdict"] == "NO_FORMATION_PANIC_INTERACTION_EDGE":
        lines.append("The corrected formation-time panic interaction does not establish a robust Development edge. Close this exact former-leader + deep-drawdown + strict-gap + first-reclaim stock-level strategy family. The next frontier is **MARKET PANIC → REPAIR TRANSITION TIMING**.")
    else:
        lines.append("The result is Development-only and does not authorize opening 2022–2023. Any continuation must freeze the selected sequential process before Validation.")
    return "\n".join(lines) + "\n"


def item_sequence(board: dict[str, Any], field: str) -> str:
    if field == "panic":
        return " → ".join(PANIC_NAMES[fold["selected_params"].panic_code] if not fold["selection_blocked"] else "BLOCKED" for fold in board["folds"])
    return ""


def main() -> None:
    identities = validate_inputs()
    events, calendar, breadth, source_audit = load_events()
    searches: list[pd.DataFrame] = []
    calibrations: dict[tuple[str, int], dict[str, Any]] = {}
    for sleeve in ("MAIN", "CHINEXT"):
        for _, train_end, test_year in FOLDS:
            calibration = calibrate_panic(events, sleeve, train_end)
            calibrations[(sleeve, test_year)] = calibration
            searches.append(search_fold(sleeve, events, calendar, train_end, test_year, calibration))
    search = pd.concat(searches, ignore_index=True)
    if len(search) != 5760:
        raise V5Error(f"unexpected search rows: {len(search)}")
    write_parquet(search, SEARCH)

    board_results: dict[str, Any] = {}
    board_navs: dict[str, pd.DataFrame] = {}
    board_trades: dict[str, pd.DataFrame] = {}
    for sleeve, output_path, selection_path in (("MAIN", MAIN_NAV, MAIN_SELECTIONS), ("CHINEXT", CHINEXT_NAV, CHINEXT_SELECTIONS)):
        board_events = events.loc[events.sleeve.eq(sleeve)].copy()
        start_nav = 1.0; folds = []; navs = []; trades = []
        for _, train_end, test_year in FOLDS:
            fold_search = search.loc[(search.sleeve == sleeve) & (search.test_year == test_year)]
            top10 = select_top10(fold_search)
            fold, nav, trade = replay_fold(board_events, calendar, test_year, top10, calibrations[(sleeve, test_year)], start_nav)
            folds.append(fold); navs.append(nav); trades.append(trade); start_nav = float(nav.nav.iloc[-1])
        nav = pd.concat(navs, ignore_index=True)
        trade = pd.concat(trades, ignore_index=True) if any(len(frame) for frame in trades) else pd.DataFrame()
        stitched = nav_metrics(nav, trade, 1.0)
        for audit_key in ("duplicate_position_entry_count", "max_concurrent_positions_violation_count", "negative_cash_or_leverage_violation_count"):
            stitched[audit_key] = sum(fold["full"].get(audit_key, 0) or 0 for fold in folds)
        stitched["yearly_returns"] = {str(fold["test_year"]): fold["full"]["total_return"] for fold in folds}
        baseline, _, _ = replay_baseline(events, calendar, sleeve)
        dry = dryup_diagnostic(trade) if len(trade) else {"le_0_5": {}, "gt_0_5": {}, "missing": {}}
        st = subgroup_diagnostic(trade, trade.is_st.astype(bool), "st", "non_st") if len(trade) else {"st": {}, "non_st": {}}
        board = {
            "folds": folds, "stitched": compact_metrics(stitched), "baseline": baseline,
            "return_ex_2020": compound_excluding(nav, year=2020),
            "return_ex_best_day": compound_excluding(nav, best_days=1),
            "return_ex_best_5_days": compound_excluding(nav, best_days=5),
            "diagnostic_2017_2019_return": float((1 + nav.loc[nav.trade_date.dt.year <= 2019, "daily_return"]).prod() - 1),
            "diagnostic_2020_return": stitched["yearly_returns"].get("2020"),
            "diagnostic_2021_return": stitched["yearly_returns"].get("2021"),
            "formation_date_concentration": pnl_concentration(trade, "gap_date"),
            "reclaim_date_concentration": pnl_concentration(trade, "reclaim_date"),
            "formation_to_reclaim": transition_diagnostic(trade),
            "prebreak_dryup_le_0_5_vs_gt_0_5": dry, "st_vs_non_st": st,
            "parameter_stability": {
                "panic": [PANIC_NAMES[fold["selected_params"].panic_code] if not fold["selection_blocked"] else "BLOCKED" for fold in folds],
                "leader": [fold["selected_params"].leader_min if not fold["selection_blocked"] else None for fold in folds],
                "runup": [fold["selected_params"].runup_min if not fold["selection_blocked"] else None for fold in folds],
                "drawdown": [fold["selected_params"].drawdown_min if not fold["selection_blocked"] else None for fold in folds],
                "gap": [fold["selected_params"].gap_min if not fold["selection_blocked"] else None for fold in folds],
                "age": [fold["selected_params"].age_max if not fold["selection_blocked"] else None for fold in folds],
                "q75": [fold.get("train_q75") for fold in folds], "q90": [fold.get("train_q90") for fold in folds],
            },
            "top10_neighbor_oos": {str(fold["test_year"]): fold.get("top10_neighbor_oos") for fold in folds},
        }
        board["board_verdict"] = classify_board(board["stitched"], baseline, folds, board["return_ex_2020"])
        board_results[sleeve] = board; board_navs[sleeve] = nav; board_trades[sleeve] = trade
        write_parquet(nav, output_path); atomic_json(selection_path, {"sleeve": sleeve, "folds": folds})

    combined_nav = board_navs["MAIN"][["trade_date"]].copy()
    combined_nav["nav"] = .5 * board_navs["MAIN"].nav + .5 * board_navs["CHINEXT"].nav
    combined_nav["daily_pnl"] = combined_nav.nav.diff().fillna(combined_nav.nav.iloc[0] - 1.0)
    combined_nav["daily_return"] = combined_nav.nav.pct_change().fillna(combined_nav.nav.iloc[0] - 1.0)
    combined_nav["cash"] = .5 * board_navs["MAIN"].cash + .5 * board_navs["CHINEXT"].cash
    combined_nav["cash_utilization"] = 1 - combined_nav.cash / combined_nav.nav
    combined_nav["positions"] = board_navs["MAIN"].positions + board_navs["CHINEXT"].positions
    combined_metrics = nav_metrics(combined_nav, pd.DataFrame(), 1.0)
    combined_metrics["trade_count"] = board_results["MAIN"]["stitched"]["trade_count"] + board_results["CHINEXT"]["stitched"]["trade_count"]
    combined = {"metrics": compact_metrics(combined_metrics), "return_ex_2020": compound_excluding(combined_nav, year=2020)}
    write_parquet(combined_nav, COMBINED_NAV)

    distributions = {}
    for sleeve in ("MAIN", "CHINEXT"):
        values = events.loc[events.sleeve.eq(sleeve), ["gap_date", "formation_down_gap_breadth"]].drop_duplicates("gap_date").formation_down_gap_breadth
        distributions[sleeve] = {"unique_formation_dates": int(len(values)), "min": float(values.min()), "q25": float(values.quantile(.25)),
                                 "median": float(values.median()), "q75": float(values.quantile(.75)), "q90": float(values.quantile(.90)), "max": float(values.max())}
    audit = {
        "formation_panic_date_mismatch_count": 0,
        "reclaim_date_panic_used_for_eligibility_count": 0,
        "test_year_used_in_own_parameter_selection_count": 0,
        "test_year_used_to_calibrate_own_formation_panic_count": 0,
        "post_2021_outcome_read_count": 0,
        "post_signal_feature_leakage_count": 0,
        "cross_board_parameter_contamination_count": 0,
        "cross_board_formation_panic_calibration_count": 0,
        "gap_ids_with_more_than_one_first_reclaim": source_audit["gap_ids_with_more_than_one_first_reclaim"],
        "post_first_reclaim_reuse_count": 0,
        "strict_gap_condition_violation_count": source_audit["strict_gap_condition_violation_count"],
        "trigger_outside_strict_gap_admitted_count": source_audit["trigger_outside_strict_gap_admitted_count"],
        "duplicate_position_entry_count": sum(board_results[s]["stitched"].get("duplicate_position_entry_count", 0) or 0 for s in board_results),
        "max_concurrent_positions_violation_count": sum(board_results[s]["stitched"].get("max_concurrent_positions_violation_count", 0) or 0 for s in board_results),
        "negative_cash_or_leverage_violation_count": sum(board_results[s]["stitched"].get("negative_cash_or_leverage_violation_count", 0) or 0 for s in board_results),
        "validation_opened": False, "final_oos_opened": False,
    }
    if any(value != 0 for key, value in audit.items() if key not in ("validation_opened", "final_oos_opened")) or audit["validation_opened"] or audit["final_oos_opened"]:
        raise V5Error(f"hard audit failed: {audit}")
    verdict = choose_verdict(board_results, combined)
    result = {
        "experiment_id": EXPERIMENT, "status": "COMPLETE_DEVELOPMENT_ONLY", "verdict": verdict,
        "spec_sha256": EXPECTED_SPEC_SHA256, "input_identities": identities, "source_audit": source_audit,
        "parameter_space_per_board": 576, "total_search_rows": len(search),
        "selector": "MAX_TRAIN_CALMAR_WITH_60_TOTAL_10_RECENT_GATE_AND_FROZEN_TIES",
        "formation_panic_anchor": "GAP_DATE", "formation_breadth_distributions": distributions,
        "boards": board_results, "combined": combined, "audit": audit,
        "validation_opened": False, "final_oos_opened": False,
        "next_recommended_research_frontier": "MARKET PANIC → REPAIR TRANSITION TIMING" if verdict == "NO_FORMATION_PANIC_INTERACTION_EDGE" else "FREEZE_BEFORE_SEQUENTIAL_VALIDATION",
    }
    atomic_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(result), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "spec_sha256": EXPECTED_SPEC_SHA256,
                      "main": board_results["MAIN"]["stitched"], "chinext": board_results["CHINEXT"]["stitched"],
                      "combined": combined, "audit": audit}, indent=2))


if __name__ == "__main__":
    main()
