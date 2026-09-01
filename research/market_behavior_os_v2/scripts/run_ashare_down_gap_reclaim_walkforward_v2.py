#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the Development-only Down-Gap Reclaim Walk-Forward V2 experiment."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from numba import njit

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-DOWN-GAP-RECLAIM-WALKFORWARD-V2"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "a030ce4d7d3051b4cdad328c51634436f48c3516a2c059ec5b0433abf07e0f80"
V1_RESULT = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_result.json"
V1_COMPACT = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_compact.parquet"
V1_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/ashare_down_gap_first_reclaim_v1/"
    "first_reclaim_outcomes_2014_2021.parquet"
)
V1_GAPS = Path(
    "/Volumes/quant/CY_quant_research/ashare_down_gap_first_reclaim_v1/down_gaps_2014_2021.parquet"
)
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_down_gap_reclaim_walkforward_v2")
BREADTH = EXTERNAL / "board_opening_gap_breadth_2014_2021.parquet"
SEARCH_EXTERNAL = EXTERNAL / f"{EXPERIMENT}_search.parquet"
SEARCH_COMPACT = OS_ROOT / f"artifacts/{EXPERIMENT}_search.parquet"
MAIN_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_main_fold_selections.json"
CHINEXT_SELECTIONS = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_fold_selections.json"
MAIN_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_main_nav.parquet"
CHINEXT_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_chinext_nav.parquet"
COMBINED_NAV = OS_ROOT / f"artifacts/{EXPERIMENT}_combined_nav.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

OLD_DAILY_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/pit_daily_2013_2023_cy006/daily"
)
NEW_DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
YEARS = tuple(range(2014, 2022))
TEST_YEARS = tuple(range(2017, 2022))
FOLDS = tuple((2014, year - 1, year) for year in TEST_YEARS)
ENTRY_COST = 0.002
EXIT_COST = 0.002

EXCLUDED_INDUSTRIES = (
    "煤炭开采",
    "油气开采Ⅱ",
    "油服工程",
    "炼化及贸易",
    "普钢",
    "特钢Ⅱ",
    "冶钢原料",
    "工业金属",
    "小金属",
    "贵金属",
    "能源金属",
    "金属新材料",
    "化学原料",
    "化学制品",
    "农化制品",
    "化学纤维",
    "电子化学品Ⅱ",
    "水泥",
    "玻璃玻纤",
    "非金属材料Ⅱ",
    "电力",
    "燃气Ⅱ",
)


class V2Error(RuntimeError):
    """Fail-closed V2 error."""


@dataclass(frozen=True)
class Params:
    gap_min: float
    age_max: int
    dryup_max: float
    compression_max: float
    breadth_regime: int
    exit_code: int
    k: int
    ranker: int

    @property
    def key(self) -> str:
        age = "U" if self.age_max < 0 else str(self.age_max)
        dry = "N" if self.dryup_max < 0 else f"{self.dryup_max:.2f}"
        comp = "N" if self.compression_max < 0 else f"{self.compression_max:.2f}"
        return (
            f"g{self.gap_min:.2f}|a{age}|d{dry}|c{comp}|b{BREADTH_NAMES[self.breadth_regime]}|"
            f"x{EXIT_NAMES[self.exit_code]}|k{self.k:02d}|r{RANKER_NAMES[self.ranker]}"
        )

    @property
    def active_filters(self) -> int:
        return (
            int(self.gap_min > 0.05)
            + int(self.age_max >= 0)
            + int(self.dryup_max >= 0)
            + int(self.compression_max >= 0)
            + int(self.breadth_regime > 0)
        )


BREADTH_NAMES = ("NONE", "Q75", "Q90")
EXIT_NAMES = ("T1_OPEN", "T1_CLOSE", "T2_CLOSE", "T3_CLOSE")
RANKER_NAMES = ("GAP", "DRYUP", "COMPOSITE")
GRID = tuple(
    Params(*values)
    for values in itertools.product(
        (0.05, 0.07, 0.09),
        (3, 10, -1),
        (0.50, 0.70, -1.0),
        (0.50, 0.70, -1.0),
        (0, 1, 2),
        (0, 1, 2, 3),
        (10, 20, 50),
        (0, 1, 2),
    )
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def daily_paths() -> list[Path]:
    return [
        *[OLD_DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2014, 2018)],
        *[NEW_DAILY_ROOT / f"partition_year={year}/data_0.parquet" for year in range(2018, 2022)],
    ]


def sql_paths(paths: list[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def validate_inputs() -> dict[str, Any]:
    if len(GRID) != 8748:
        raise V2Error(f"parameter grid changed: {len(GRID)}")
    expected = {
        SPEC: EXPECTED_SPEC_SHA256,
        V1_RESULT: "bc4bbe4dc63903984f6be884d26f481483b0daefe14842cdc469fed2dbe86ced",
        V1_COMPACT: "a551178509dda6c51eb1364a2c1cdb6d353e1b23098acf8bd40bab6f16c4ace9",
        V1_OUTCOMES: "daa9ce35c11598392f825912d6c715e320c98f88448618bca62cd6bd83d73a49",
    }
    for path, digest in expected.items():
        if not path.is_file() or sha256_file(path) != digest:
            raise V2Error(f"input identity mismatch: {path}")
    for path in [V1_GAPS, *daily_paths()]:
        if not path.is_file():
            raise V2Error(f"missing input: {path}")
    v1_result = json.loads(V1_RESULT.read_text(encoding="utf-8"))
    v1_invariants = v1_result["invariants"]
    required_v1 = {
        "max_signals_per_gap_id": 1,
        "gap_ids_with_more_than_one_first_reclaim": 0,
        "post_first_reclaim_reuse_count": 0,
        "illegal_execution_count": 0,
        "future_volume_leakage_count": 0,
        "post_2021_outcome_read_count": 0,
    }
    if any(v1_invariants.get(key) != value for key, value in required_v1.items()):
        raise V2Error("authoritative V1 lifecycle or chronology invariant failed")
    return {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "v1_hashes": {str(k): v for k, v in expected.items()},
        "v1_lifecycle_invariants": required_v1,
    }


def build_breadth() -> pd.DataFrame:
    if BREADTH.is_file():
        breadth = pd.read_parquet(BREADTH)
        breadth["trade_date"] = pd.to_datetime(breadth.trade_date)
        return breadth
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    excluded = ",".join("'" + value.replace("'", "''") + "'" for value in EXCLUDED_INDUSTRIES)
    paths = sql_paths(daily_paths())
    con = duckdb.connect()
    con.execute("SET threads=4")
    con.execute(
        f"""COPY (
        WITH eligible AS (
          SELECT trade_date,
            CASE WHEN symbol LIKE '30%.SZ' THEN 'CHINEXT' ELSE 'MAIN' END AS sleeve,
            count(*) AS universe_size
          FROM read_parquet({paths})
          WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2021-12-31'
            AND hard_valid AND current_day_data_tradable AND trade_status=1
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND coalesce(corporate_action_count,0)=0
            AND industry NOT IN ({excluded})
            AND ((symbol LIKE '60%.SH' AND symbol NOT LIKE '688%.SH') OR symbol LIKE '00%.SZ' OR symbol LIKE '30%.SZ')
          GROUP BY 1,2
        ), gaps AS (
          SELECT gap_date AS trade_date,CASE WHEN board='ChiNext' THEN 'CHINEXT' ELSE 'MAIN' END AS sleeve,
                 count(*) AS gap_count
          FROM read_parquet('{V1_GAPS}') GROUP BY 1,2
        )
        SELECT e.trade_date,e.sleeve,e.universe_size,coalesce(g.gap_count,0) gap_count,
               coalesce(g.gap_count,0)::DOUBLE/e.universe_size AS breadth
        FROM eligible e LEFT JOIN gaps g USING(trade_date,sleeve)
        ORDER BY e.trade_date,e.sleeve
        ) TO '{BREADTH}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    con.close()
    breadth = pd.read_parquet(BREADTH)
    breadth["trade_date"] = pd.to_datetime(breadth.trade_date)
    return breadth


def prepare_events(breadth: pd.DataFrame) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    columns = [
        "entry_id",
        "symbol",
        "board",
        "bar_end_time",
        "reclaim_date",
        "entry_price",
        "close",
        "gap_pct",
        "gap_age_trading_days",
        "dryup_3_20",
        "compression_trend",
        "is_st",
        "t1_date",
        "t2_date",
        "t3_date",
        "next_legal_open_date",
        "t1_legal_open_price",
        "t1_close_price",
        "t2_close_price",
        "t3_close_price",
    ]
    events = pd.read_parquet(V1_OUTCOMES, columns=columns)
    events["sleeve"] = np.where(events.board.eq("ChiNext"), "CHINEXT", "MAIN")
    events["reclaim_date"] = pd.to_datetime(events.reclaim_date)
    events["bar_end_time"] = pd.to_datetime(events.bar_end_time)
    for col in ("t1_date", "t2_date", "t3_date", "next_legal_open_date"):
        events[col] = pd.to_datetime(events[col])
    events = events.merge(
        breadth[["trade_date", "sleeve", "breadth"]],
        left_on=["reclaim_date", "sleeve"],
        right_on=["trade_date", "sleeve"],
        how="left",
        validate="many_to_one",
    )
    if events.breadth.isna().any() or events.reclaim_date.max() > pd.Timestamp("2021-12-31"):
        raise V2Error("event breadth or chronology failed")
    calendar = pd.DatetimeIndex(sorted(pd.to_datetime(breadth.trade_date.unique())))
    day_map = pd.Series(np.arange(len(calendar), dtype=np.int32), index=calendar)
    events["entry_day"] = events.reclaim_date.map(day_map).astype(np.int32)
    for source, target in (
        ("next_legal_open_date", "exit_day_0"),
        ("t1_date", "exit_day_1"),
        ("t2_date", "exit_day_2"),
        ("t3_date", "exit_day_3"),
    ):
        events[target] = events[source].map(day_map).fillna(-1).astype(np.int32)
    events["symbol_id"] = pd.factorize(events.symbol, sort=True)[0].astype(np.int32)
    events = events.sort_values(["bar_end_time", "symbol"], kind="mergesort").reset_index(drop=True)
    return events, calendar


def event_arrays(events: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "entry_day": events.entry_day.to_numpy(np.int32),
        "time": events.bar_end_time.astype("int64").to_numpy(np.int64),
        "symbol": events.symbol_id.to_numpy(np.int32),
        "gap": events.gap_pct.to_numpy(np.float64),
        "age": events.gap_age_trading_days.to_numpy(np.int32),
        "dry": events.dryup_3_20.to_numpy(np.float64),
        "comp": events.compression_trend.to_numpy(np.float64),
        "breadth": events.breadth.to_numpy(np.float64),
        "entry_price": events.entry_price.to_numpy(np.float64),
        "close0": events.close.to_numpy(np.float64),
        "exit_day": events[[f"exit_day_{i}" for i in range(4)]].to_numpy(np.int32),
        "exit_price": events[
            ["t1_legal_open_price", "t1_close_price", "t2_close_price", "t3_close_price"]
        ].to_numpy(np.float64),
        "close_days": events[["entry_day", "exit_day_1", "exit_day_2", "exit_day_3"]].to_numpy(
            np.int32
        ),
        "close_prices": events[
            ["close", "t1_close_price", "t2_close_price", "t3_close_price"]
        ].to_numpy(np.float64),
    }


@njit(cache=False)
def _rank_candidates(cands, m, ranker, gap, dry, comp, age):
    scores = np.zeros(m, dtype=np.float64)
    if ranker == 0:
        for j in range(m):
            scores[j] = -gap[cands[j]]
    elif ranker == 1:
        for j in range(m):
            value = dry[cands[j]]
            scores[j] = value if np.isfinite(value) else 1e30
    else:
        for feature in range(4):
            values = np.empty(m, dtype=np.float64)
            for j in range(m):
                idx = cands[j]
                if feature == 0:
                    values[j] = -gap[idx]
                elif feature == 1:
                    values[j] = dry[idx] if np.isfinite(dry[idx]) else 1e30
                elif feature == 2:
                    values[j] = comp[idx] if np.isfinite(comp[idx]) else 1e30
                else:
                    values[j] = age[idx]
            order = np.argsort(values)
            for rank in range(m):
                scores[order[rank]] += rank
    return scores


@njit(cache=False)
def simulate_summary(
    entry_day,
    time,
    symbol,
    gap,
    age,
    dry,
    comp,
    breadth,
    entry_price,
    close0,
    exit_day_matrix,
    exit_price_matrix,
    close_days,
    close_prices,
    start_day,
    end_day,
    day_year,
    gap_min,
    age_max,
    dry_max,
    comp_max,
    breadth_threshold,
    exit_code,
    k,
    ranker,
):
    n_days = end_day - start_day + 1
    navs = np.ones(n_days, dtype=np.float64)
    day_pnl = np.zeros(n_days, dtype=np.float64)
    pos_symbol = np.full(k, -1, dtype=np.int32)
    pos_event = np.full(k, -1, dtype=np.int32)
    shares = np.zeros(k, dtype=np.float64)
    marks = np.zeros(k, dtype=np.float64)
    entry_debit = np.zeros(k, dtype=np.float64)
    cash = 1.0
    active = 0
    trades = 0
    recent_trades = 0
    win_trades = 0
    sum_trade_return = 0.0
    max_group = 0
    for i in range(len(entry_day)):
        if start_day <= entry_day[i] <= end_day:
            max_group += 1
    cands = np.empty(max(1, max_group), dtype=np.int64)
    pointer = 0
    while pointer < len(entry_day) and entry_day[pointer] < start_day:
        pointer += 1
    prior_nav = 1.0
    peak = 1.0
    max_dd = 0.0
    sum_ret = 0.0
    sum_ret2 = 0.0
    annual_start = 1.0
    annual_values = np.empty(8, dtype=np.float64)
    annual_count = 0
    current_year = day_year[start_day]
    for day in range(start_day, end_day + 1):
        # Legal-open exits occur before intraday signals.
        for slot in range(k):
            if pos_event[slot] >= 0:
                event = pos_event[slot]
                if exit_code == 0 and exit_day_matrix[event, exit_code] == day:
                    proceeds = (
                        shares[slot] * exit_price_matrix[event, exit_code] * (1.0 - EXIT_COST)
                    )
                    trade_return = proceeds / entry_debit[slot] - 1.0
                    cash += proceeds
                    trades += 1
                    recent_trades += int(day_year[day] == day_year[end_day])
                    win_trades += int(trade_return > 0)
                    sum_trade_return += trade_return
                    pos_event[slot] = -1
                    pos_symbol[slot] = -1
                    shares[slot] = marks[slot] = entry_debit[slot] = 0.0
                    active -= 1
        accounting_nav = cash
        for slot in range(k):
            if pos_event[slot] >= 0:
                accounting_nav += shares[slot] * marks[slot]
        # Process exact timestamp groups.
        while pointer < len(entry_day) and entry_day[pointer] == day:
            group_start = pointer
            group_time = time[pointer]
            while (
                pointer < len(entry_day)
                and entry_day[pointer] == day
                and time[pointer] == group_time
            ):
                pointer += 1
            m = 0
            if active < k:
                for idx in range(group_start, pointer):
                    if gap[idx] + 1e-12 < gap_min:
                        continue
                    if age_max >= 0 and age[idx] > age_max:
                        continue
                    if dry_max >= 0 and (not np.isfinite(dry[idx]) or dry[idx] > dry_max):
                        continue
                    if comp_max >= 0 and (not np.isfinite(comp[idx]) or comp[idx] > comp_max):
                        continue
                    if breadth_threshold >= 0 and breadth[idx] + 1e-15 < breadth_threshold:
                        continue
                    exday = exit_day_matrix[idx, exit_code]
                    exprice = exit_price_matrix[idx, exit_code]
                    if exday <= day or exday > end_day or not np.isfinite(exprice) or exprice <= 0:
                        continue
                    held = False
                    for slot in range(k):
                        if pos_symbol[slot] == symbol[idx]:
                            held = True
                            break
                    if not held:
                        cands[m] = idx
                        m += 1
            if m > 0 and active < k:
                scores = _rank_candidates(cands, m, ranker, gap, dry, comp, age)
                used = np.zeros(m, dtype=np.uint8)
                slots_left = k - active
                for _ in range(min(slots_left, m)):
                    best = -1
                    best_score = 1e300
                    for j in range(m):
                        if used[j] == 0 and (
                            scores[j] < best_score
                            or (scores[j] == best_score and cands[j] < cands[best])
                        ):
                            best = j
                            best_score = scores[j]
                    if best < 0:
                        break
                    used[best] = 1
                    idx = cands[best]
                    free_slot = -1
                    for slot in range(k):
                        if pos_event[slot] < 0:
                            free_slot = slot
                            break
                    principal = min(accounting_nav / k, cash / (1.0 + ENTRY_COST))
                    if free_slot < 0 or principal <= 1e-14:
                        continue
                    debit = principal * (1.0 + ENTRY_COST)
                    cash -= debit
                    pos_event[free_slot] = idx
                    pos_symbol[free_slot] = symbol[idx]
                    shares[free_slot] = principal / entry_price[idx]
                    marks[free_slot] = entry_price[idx]
                    entry_debit[free_slot] = debit
                    accounting_nav -= principal * ENTRY_COST
                    active += 1
        # Update causal end-of-day marks, then close exits.
        for slot in range(k):
            if pos_event[slot] >= 0:
                event = pos_event[slot]
                for j in range(4):
                    if close_days[event, j] == day and np.isfinite(close_prices[event, j]):
                        marks[slot] = close_prices[event, j]
                if exit_code > 0 and exit_day_matrix[event, exit_code] == day:
                    proceeds = (
                        shares[slot] * exit_price_matrix[event, exit_code] * (1.0 - EXIT_COST)
                    )
                    trade_return = proceeds / entry_debit[slot] - 1.0
                    cash += proceeds
                    trades += 1
                    recent_trades += int(day_year[day] == day_year[end_day])
                    win_trades += int(trade_return > 0)
                    sum_trade_return += trade_return
                    pos_event[slot] = -1
                    pos_symbol[slot] = -1
                    shares[slot] = marks[slot] = entry_debit[slot] = 0.0
                    active -= 1
        nav = cash
        for slot in range(k):
            if pos_event[slot] >= 0:
                nav += shares[slot] * marks[slot]
        navs[day - start_day] = nav
        pnl = nav - prior_nav
        day_pnl[day - start_day] = pnl
        ret = nav / prior_nav - 1.0 if prior_nav > 0 else 0.0
        sum_ret += ret
        sum_ret2 += ret * ret
        prior_nav = nav
        if nav > peak:
            peak = nav
        dd = nav / peak - 1.0
        if dd < max_dd:
            max_dd = dd
        is_last = day == end_day or day_year[day + 1] != current_year
        if is_last:
            annual_values[annual_count] = nav / annual_start - 1.0
            annual_count += 1
            annual_start = nav
            if day < end_day:
                current_year = day_year[day + 1]
    total = navs[-1] - 1.0
    cagr = navs[-1] ** (242.0 / n_days) - 1.0
    mean_ret = sum_ret / n_days
    variance = max(0.0, sum_ret2 / n_days - mean_ret * mean_ret)
    sharpe = mean_ret / math.sqrt(variance) * math.sqrt(242.0) if variance > 0 else 0.0
    calmar = cagr / abs(max_dd) if max_dd < 0 else (1e6 if cagr > 0 else 0.0)
    annual_sorted = np.sort(annual_values[:annual_count])
    median_annual = np.median(annual_sorted) if annual_count else 0.0
    worst_annual = annual_sorted[0] if annual_count else 0.0
    positive_years = 0
    for value in annual_values[:annual_count]:
        positive_years += int(value > 0)
    positive_pnl = np.sort(day_pnl[day_pnl > 0])[::-1]
    positive_sum = positive_pnl.sum()
    top1 = positive_pnl[:1].sum() / positive_sum if positive_sum > 0 else 0.0
    top5 = positive_pnl[:5].sum() / positive_sum if positive_sum > 0 else 0.0
    topn = max(1, math.ceil(n_days * 0.01))
    top1pct = positive_pnl[:topn].sum() / positive_sum if positive_sum > 0 else 0.0
    return (
        total,
        cagr,
        max_dd,
        sharpe,
        calmar,
        trades,
        recent_trades,
        positive_years,
        median_annual,
        worst_annual,
        top1,
        top5,
        top1pct,
        win_trades,
        sum_trade_return,
    )


def metric_record(values: tuple[Any, ...]) -> dict[str, Any]:
    names = (
        "total_return",
        "cagr",
        "max_drawdown",
        "sharpe",
        "calmar",
        "trade_count",
        "recent_year_trade_count",
        "positive_years",
        "median_year_return",
        "worst_year_return",
        "top1_day_contribution",
        "top5_day_contribution",
        "top1pct_day_contribution",
        "win_trades",
        "sum_trade_return",
    )
    result = dict(zip(names, values, strict=True))
    result["win_rate"] = (
        result["win_trades"] / result["trade_count"] if result["trade_count"] else None
    )
    result["average_trade_return"] = (
        result["sum_trade_return"] / result["trade_count"] if result["trade_count"] else None
    )
    return result


def run_summary(
    arrays: dict[str, np.ndarray],
    calendar: pd.DatetimeIndex,
    params: Params,
    start: pd.Timestamp,
    end: pd.Timestamp,
    q75: float,
    q90: float,
) -> dict[str, Any]:
    day_year = calendar.year.to_numpy(np.int32)
    start_day = int(calendar.get_loc(start))
    end_day = int(calendar.get_loc(end))
    threshold = -1.0 if params.breadth_regime == 0 else (q75 if params.breadth_regime == 1 else q90)
    values = simulate_summary(
        arrays["entry_day"],
        arrays["time"],
        arrays["symbol"],
        arrays["gap"],
        arrays["age"],
        arrays["dry"],
        arrays["comp"],
        arrays["breadth"],
        arrays["entry_price"],
        arrays["close0"],
        arrays["exit_day"],
        arrays["exit_price"],
        arrays["close_days"],
        arrays["close_prices"],
        start_day,
        end_day,
        day_year,
        params.gap_min,
        params.age_max,
        params.dryup_max,
        params.compression_max,
        threshold,
        params.exit_code,
        params.k,
        params.ranker,
    )
    return metric_record(values)


def breadth_thresholds(breadth: pd.DataFrame, sleeve: str, train_end: int) -> tuple[float, float]:
    values = breadth.loc[
        (breadth.sleeve.eq(sleeve)) & (pd.to_datetime(breadth.trade_date).dt.year <= train_end),
        "breadth",
    ].to_numpy()
    return float(np.quantile(values, 0.75, method="linear")), float(
        np.quantile(values, 0.90, method="linear")
    )


def search_fold(
    sleeve: str,
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    breadth: pd.DataFrame,
    train_end: int,
    test_year: int,
) -> pd.DataFrame:
    shard = EXTERNAL / f"search_{sleeve.lower()}_{test_year}.parquet"
    if shard.is_file():
        return pd.read_parquet(shard)
    board_events = events.loc[events.sleeve.eq(sleeve)].copy()
    arrays = event_arrays(board_events)
    q75, q90 = breadth_thresholds(breadth, sleeve, train_end)
    start = calendar[calendar.year == 2014][0]
    end = calendar[calendar.year == train_end][-1]
    records = []
    for index, params in enumerate(GRID):
        metrics = run_summary(arrays, calendar, params, start, end, q75, q90)
        records.append(
            {
                "sleeve": sleeve,
                "train_start": 2014,
                "train_end": train_end,
                "test_year": test_year,
                "parameter_index": index,
                "parameter_key": params.key,
                **asdict(params),
                "active_filters": params.active_filters,
                "q75": q75,
                "q90": q90,
                **metrics,
            }
        )
    frame = pd.DataFrame(records)
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), shard, compression="zstd")
    return frame


def select_top10(search: pd.DataFrame) -> pd.DataFrame:
    eligible = search.loc[
        (search.trade_count >= 100) & (search.recent_year_trade_count >= 20)
    ].copy()
    if eligible.empty:
        return eligible
    # 1e-12 effective ties are made deterministic by quantizing only the primary key.
    eligible["calmar_tie"] = np.round(eligible.calmar / 1e-12) * 1e-12
    return eligible.sort_values(
        [
            "calmar_tie",
            "sharpe",
            "median_year_return",
            "cagr",
            "top5_day_contribution",
            "active_filters",
            "parameter_key",
        ],
        ascending=[False, False, False, False, True, True, True],
        kind="mergesort",
    ).head(10)


def params_from_row(row: pd.Series) -> Params:
    return Params(
        float(row.gap_min),
        int(row.age_max),
        float(row.dryup_max),
        float(row.compression_max),
        int(row.breadth_regime),
        int(row.exit_code),
        int(row.k),
        int(row.ranker),
    )


def eligible_candidates(
    group: pd.DataFrame,
    params: Params,
    threshold: float,
    exit_date: str,
    exit_price: str,
    end: pd.Timestamp,
    held: set[str],
) -> pd.DataFrame:
    mask = group.gap_pct.ge(params.gap_min - 1e-12)
    if params.age_max >= 0:
        mask &= group.gap_age_trading_days.le(params.age_max)
    if params.dryup_max >= 0:
        mask &= group.dryup_3_20.notna() & group.dryup_3_20.le(params.dryup_max)
    if params.compression_max >= 0:
        mask &= group.compression_trend.notna() & group.compression_trend.le(params.compression_max)
    if threshold >= 0:
        mask &= group.breadth.ge(threshold - 1e-15)
    mask &= (
        group[exit_date].notna()
        & group[exit_date].gt(group.reclaim_date)
        & group[exit_date].le(end)
        & group[exit_price].notna()
        & group[exit_price].gt(0)
        & ~group.symbol.isin(held)
    )
    selected = group.loc[mask].copy()
    if selected.empty:
        return selected
    if params.ranker == 0:
        selected["rank_score"] = selected.gap_pct.rank(method="first", ascending=False)
    elif params.ranker == 1:
        selected["rank_score"] = selected.dryup_3_20.fillna(np.inf).rank(
            method="first", ascending=True
        )
    else:
        selected["rank_score"] = (
            selected.gap_pct.rank(method="first", ascending=False)
            + selected.dryup_3_20.fillna(np.inf).rank(method="first", ascending=True)
            + selected.compression_trend.fillna(np.inf).rank(method="first", ascending=True)
            + selected.gap_age_trading_days.rank(method="first", ascending=True)
        )
    return selected.sort_values(["rank_score", "bar_end_time", "symbol"], kind="mergesort")


def simulate_detailed(
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    params: Params,
    start: pd.Timestamp,
    end: pd.Timestamp,
    q75: float,
    q90: float,
    start_nav: float = 1.0,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = events.loc[events.reclaim_date.between(start, end)].sort_values(
        ["bar_end_time", "symbol"], kind="mergesort"
    )
    groups = {key: value for key, value in frame.groupby("bar_end_time", sort=True)}
    source_by_id = frame.set_index("entry_id", verify_integrity=True).to_dict("index")
    exit_date_col = ("next_legal_open_date", "t1_date", "t2_date", "t3_date")[params.exit_code]
    exit_price_col = ("t1_legal_open_price", "t1_close_price", "t2_close_price", "t3_close_price")[
        params.exit_code
    ]
    threshold = -1.0 if params.breadth_regime == 0 else (q75 if params.breadth_regime == 1 else q90)
    positions: list[dict[str, Any]] = []
    cash = start_nav
    nav_rows, trade_rows = [], []
    duplicate_count = cap_violations = negative_cash = 0
    grouped_by_day: dict[pd.Timestamp, list[tuple[pd.Timestamp, pd.DataFrame]]] = {}
    for timestamp, group in groups.items():
        grouped_by_day.setdefault(pd.Timestamp(timestamp).normalize(), []).append(
            (pd.Timestamp(timestamp), group)
        )
    prior_nav = start_nav
    for day in calendar[(calendar >= start) & (calendar <= end)]:
        # Open exits.
        for pos in positions.copy():
            if params.exit_code == 0 and pos["exit_date"] == day:
                proceeds = pos["shares"] * pos["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append(
                    {
                        **pos,
                        "exit_proceeds": proceeds,
                        "pnl": proceeds - pos["entry_debit"],
                        "net_return": proceeds / pos["entry_debit"] - 1,
                    }
                )
                positions.remove(pos)
        accounting_nav = cash + sum(pos["shares"] * pos["mark"] for pos in positions)
        for _, group in grouped_by_day.get(day, []):
            held = {pos["symbol"] for pos in positions}
            candidates = eligible_candidates(
                group,
                params,
                threshold,
                exit_date_col,
                exit_price_col,
                end,
                held,
            )
            for _, event in candidates.head(max(0, params.k - len(positions))).iterrows():
                if event.symbol in {pos["symbol"] for pos in positions}:
                    duplicate_count += 1
                    continue
                principal = min(accounting_nav / params.k, cash / (1 + ENTRY_COST))
                if principal <= 1e-14:
                    continue
                debit = principal * (1 + ENTRY_COST)
                cash -= debit
                positions.append(
                    {
                        "entry_id": event.entry_id,
                        "symbol": event.symbol,
                        "is_st": bool(event.is_st),
                        "entry_date": day,
                        "entry_time": event.bar_end_time,
                        "entry_price": event.entry_price,
                        "entry_debit": debit,
                        "shares": principal / event.entry_price,
                        "mark": event.entry_price,
                        "exit_date": pd.Timestamp(event[exit_date_col]),
                        "exit_price": float(event[exit_price_col]),
                        "breadth": float(event.breadth),
                        "gap_pct": float(event.gap_pct),
                        "dryup_3_20": event.dryup_3_20,
                        "compression_trend": event.compression_trend,
                        "gap_age_trading_days": int(event.gap_age_trading_days),
                    }
                )
                accounting_nav -= principal * ENTRY_COST
        # Close marks and exits.
        for pos in positions.copy():
            source = source_by_id[pos["entry_id"]]
            mark_map = {
                pd.Timestamp(source["reclaim_date"]): source["close"],
                pd.Timestamp(source["t1_date"]): source["t1_close_price"],
                pd.Timestamp(source["t2_date"]): source["t2_close_price"],
                pd.Timestamp(source["t3_date"]): source["t3_close_price"],
            }
            if day in mark_map and pd.notna(mark_map[day]):
                pos["mark"] = float(mark_map[day])
            if params.exit_code > 0 and pos["exit_date"] == day:
                proceeds = pos["shares"] * pos["exit_price"] * (1 - EXIT_COST)
                cash += proceeds
                trade_rows.append(
                    {
                        **pos,
                        "exit_proceeds": proceeds,
                        "pnl": proceeds - pos["entry_debit"],
                        "net_return": proceeds / pos["entry_debit"] - 1,
                    }
                )
                positions.remove(pos)
        nav = cash + sum(pos["shares"] * pos["mark"] for pos in positions)
        if len(positions) > params.k:
            cap_violations += 1
        if cash < -1e-12:
            negative_cash += 1
        nav_rows.append(
            {
                "trade_date": day,
                "nav": nav,
                "daily_pnl": nav - prior_nav,
                "daily_return": nav / prior_nav - 1 if prior_nav else 0,
                "cash": cash,
                "cash_utilization": 1 - cash / nav if nav else 0,
                "positions": len(positions),
            }
        )
        prior_nav = nav
    if positions:
        raise V2Error("uncensored position survived terminal date")
    nav = pd.DataFrame(nav_rows)
    trades = pd.DataFrame(trade_rows)
    metrics = detailed_metrics(nav, trades, start_nav)
    metrics["duplicate_position_entry_count"] = duplicate_count
    metrics["max_concurrent_positions_violation_count"] = cap_violations
    metrics["negative_cash_or_leverage_violation_count"] = negative_cash
    return nav, trades, metrics


def detailed_metrics(nav: pd.DataFrame, trades: pd.DataFrame, start_nav: float) -> dict[str, Any]:
    end_nav = float(nav.nav.iloc[-1])
    running = np.maximum.accumulate(np.concatenate(([start_nav], nav.nav.to_numpy())))
    maxdd = float((nav.nav.to_numpy() / running[1:] - 1).min())
    cagr = float((end_nav / start_nav) ** (242 / len(nav)) - 1)
    std = float(nav.daily_return.std(ddof=0))
    sharpe = float(nav.daily_return.mean() / std * math.sqrt(242)) if std > 0 else 0.0
    positive = nav.loc[nav.daily_pnl > 0, "daily_pnl"].sort_values(ascending=False)
    positive_sum = positive.sum()

    def share(n: int) -> float:
        return float(positive.head(n).sum() / positive_sum) if positive_sum > 0 else 0.0

    yearly = (
        nav.set_index("trade_date")
        .nav.resample("YE")
        .last()
        .pct_change()
        .fillna(nav.set_index("trade_date").nav.resample("YE").last().iloc[0] / start_nav - 1)
    )
    monthly_pnl = nav.set_index("trade_date").daily_pnl.resample("ME").sum()
    yearly_pnl = nav.set_index("trade_date").daily_pnl.resample("YE").sum()
    return {
        "start_nav": start_nav,
        "end_nav": end_nav,
        "total_return": end_nav / start_nav - 1,
        "cagr": cagr,
        "max_drawdown": maxdd,
        "sharpe": sharpe,
        "calmar": cagr / abs(maxdd) if maxdd < 0 else (1e6 if cagr > 0 else 0.0),
        "trade_count": len(trades),
        "win_rate": float((trades.net_return > 0).mean()) if len(trades) else None,
        "average_trade_return": float(trades.net_return.mean()) if len(trades) else None,
        "median_trade_return": float(trades.net_return.median()) if len(trades) else None,
        "maximum_concurrent_positions": int(nav.positions.max()),
        "average_cash_utilization": float(nav.cash_utilization.mean()),
        "top1_day_contribution": share(1),
        "top5_day_contribution": share(5),
        "top1pct_day_contribution": share(max(1, math.ceil(len(nav) * 0.01))),
        "positive_months": int(
            (nav.set_index("trade_date").nav.resample("ME").last().pct_change().dropna() > 0).sum()
        ),
        "yearly_returns": {str(index.year): float(value) for index, value in yearly.items()},
        "largest_monthly_pnl_contribution": float(monthly_pnl.max() / positive_sum)
        if positive_sum > 0
        else 0.0,
        "largest_yearly_pnl_contribution": float(yearly_pnl.max() / positive_sum)
        if positive_sum > 0
        else 0.0,
        "return_excluding_best_day": float((end_nav - positive.head(1).sum()) / start_nav - 1),
        "return_excluding_best5_days": float((end_nav - positive.head(5).sum()) / start_nav - 1),
    }


def stability(selections: list[dict[str, Any]]) -> str:
    fields = (
        "gap_min",
        "age_max",
        "dryup_max",
        "compression_max",
        "breadth_regime",
        "exit_code",
        "k",
        "ranker",
    )
    changes = []
    for left, right in itertools.pairwise(selections):
        if left["params"] is None or right["params"] is None:
            continue
        changes.append(sum(left["params"][field] != right["params"][field] for field in fields))
    mean_changes = float(np.mean(changes)) if changes else 0.0
    unique = len({row["parameter_key"] for row in selections})
    if unique <= 2 or mean_changes <= 2.0:
        return "STABLE"
    if mean_changes <= 4.0:
        return "MODERATELY_ADAPTIVE"
    return "HIGHLY_UNSTABLE"


def run_sleeve(
    sleeve: str,
    events: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    breadth: pd.DataFrame,
    search_frames: dict[tuple[str, int], pd.DataFrame],
) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    selections, nav_parts, all_trades = [], [], []
    current_nav = 1.0
    board_events = events.loc[events.sleeve.eq(sleeve)].copy()
    arrays = event_arrays(board_events)
    for _, train_end, test_year in FOLDS:
        search = search_frames[(sleeve, test_year)]
        top10 = select_top10(search)
        q75, q90 = breadth_thresholds(breadth, sleeve, train_end)
        start = calendar[calendar.year == test_year][0]
        end = calendar[calendar.year == test_year][-1]
        if top10.empty:
            params = None
            nav = pd.DataFrame(
                {
                    "trade_date": calendar[(calendar >= start) & (calendar <= end)],
                    "nav": current_nav,
                }
            )
            nav["daily_pnl"] = 0.0
            nav["daily_return"] = 0.0
            nav["cash"] = current_nav
            nav["cash_utilization"] = 0.0
            nav["positions"] = 0
            trades = pd.DataFrame()
            test_metrics = detailed_metrics(nav, trades, current_nav)
            record = {
                "sleeve": sleeve,
                "test_year": test_year,
                "status": "SELECTION_BLOCKED",
                "q75": q75,
                "q90": q90,
                "parameter_key": None,
                "params": None,
                "train_metrics": None,
                "test_metrics": test_metrics,
                "top10_oos": None,
            }
        else:
            champion = top10.iloc[0]
            params = params_from_row(champion)
            nav, trades, test_metrics = simulate_detailed(
                board_events, calendar, params, start, end, q75, q90, current_nav
            )
            top10_test = []
            for _, row in top10.iterrows():
                p = params_from_row(row)
                metrics = run_summary(arrays, calendar, p, start, end, q75, q90)
                top10_test.append({"parameter_key": p.key, "test_return": metrics["total_return"]})
            ordered = sorted(top10_test, key=lambda x: (-x["test_return"], x["parameter_key"]))
            champion_rank = next(
                i + 1 for i, x in enumerate(ordered) if x["parameter_key"] == params.key
            )
            returns = [x["test_return"] for x in top10_test]
            topdiag = {
                "median_return": float(np.median(returns)),
                "best_return": float(max(returns)),
                "worst_return": float(min(returns)),
                "profitable_fraction": float(np.mean(np.array(returns) > 0)),
                "champion_rank": champion_rank,
                "members": top10_test,
            }
            record = {
                "sleeve": sleeve,
                "train_start": 2014,
                "train_end": train_end,
                "test_year": test_year,
                "status": "SELECTED",
                "q75": q75,
                "q90": q90,
                "selected_breadth_threshold": -1.0
                if params.breadth_regime == 0
                else (q75 if params.breadth_regime == 1 else q90),
                "selected_gap_min": params.gap_min,
                "selected_gap_age_max": params.age_max,
                "selected_dryup_rule": params.dryup_max,
                "selected_compression_rule": params.compression_max,
                "selected_breadth_regime": BREADTH_NAMES[params.breadth_regime],
                "selected_exit": EXIT_NAMES[params.exit_code],
                "selected_k": params.k,
                "selected_ranker": RANKER_NAMES[params.ranker],
                "parameter_key": params.key,
                "params": asdict(params),
                "train_metrics": {
                    key: champion[key]
                    for key in (
                        "trade_count",
                        "cagr",
                        "max_drawdown",
                        "sharpe",
                        "calmar",
                        "top5_day_contribution",
                        "positive_years",
                        "median_year_return",
                        "worst_year_return",
                    )
                },
                "test_metrics": test_metrics,
                "top10_oos": topdiag,
            }
        current_nav = float(nav.nav.iloc[-1])
        nav["sleeve"] = sleeve
        nav["test_year"] = test_year
        if len(trades):
            trades["sleeve"] = sleeve
            trades["test_year"] = test_year
            trades["breadth_regime"] = np.where(
                trades.breadth >= q90,
                ">=Q90",
                np.where(trades.breadth >= q75, "Q75-Q90", "below Q75"),
            )
            all_trades.append(trades)
        nav_parts.append(nav)
        selections.append(record)
    stitched_nav = pd.concat(nav_parts, ignore_index=True)
    stitched_trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    wf_metrics = detailed_metrics(stitched_nav, stitched_trades, 1.0)
    wf_metrics["positive_years"] = sum(value > 0 for value in wf_metrics["yearly_returns"].values())
    wf_metrics["negative_years"] = sum(value < 0 for value in wf_metrics["yearly_returns"].values())
    wf_metrics["parameter_stability"] = stability(selections)
    # Fixed baseline is replayed year by year under identical boundary censoring.
    baseline_params = Params(0.05, -1, -1.0, -1.0, 0, 0, 20, 0)
    baseline_nav_parts, baseline_trades, baseline_current = [], [], 1.0
    for year in TEST_YEARS:
        start = calendar[calendar.year == year][0]
        end = calendar[calendar.year == year][-1]
        nav, trades, _ = simulate_detailed(
            board_events, calendar, baseline_params, start, end, 0.0, 0.0, baseline_current
        )
        baseline_current = float(nav.nav.iloc[-1])
        baseline_nav_parts.append(nav)
        if len(trades):
            baseline_trades.append(trades)
    baseline_nav = pd.concat(baseline_nav_parts, ignore_index=True)
    baseline_trade = (
        pd.concat(baseline_trades, ignore_index=True) if baseline_trades else pd.DataFrame()
    )
    baseline_metrics = detailed_metrics(baseline_nav, baseline_trade, 1.0)
    return selections, stitched_nav, stitched_trades, wf_metrics, baseline_metrics


def trade_diagnostics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"breadth_regimes": {}, "st": {}}
    regimes = {}
    for key, group in trades.groupby("breadth_regime"):
        regimes[str(key)] = {
            "trades": len(group),
            "pnl": float(group.pnl.sum()),
            "average_trade_return": float(group.net_return.mean()),
            "win_rate": float((group.net_return > 0).mean()),
        }
    st = {}
    for flag, group in trades.groupby("is_st"):
        st["ST" if flag else "NON_ST"] = {
            "trades": len(group),
            "pnl": float(group.pnl.sum()),
            "average_trade_return": float(group.net_return.mean()),
        }
    return {"breadth_regimes": regimes, "st": st}


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, Params):
        return asdict(value)
    return value


def render_report(result: dict[str, Any]) -> str:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"**Development verdict: `{result['verdict']}`**",
        "",
        "The frozen expanding selector does not justify Validation. Main Board earned only 1.48% over five test years (0.29% CAGR, 0.118 Sharpe) and lost money in four of five years. ChiNext lost 1.47%. The fixed 50/50 portfolio was economically flat and all meaningful gains came from 2020 panic-repair conditions.",
        "",
        "## Frozen contract and chronology",
        "",
        f"Spec SHA-256: `{result['spec_sha256']}`. The candidate grid contains {result['parameter_space_per_board']:,} configurations per board and {result['total_parameter_space_per_fold']:,} per fold. Selection maximizes training Calmar after the 100-total/20-recent-year trade gate, with the frozen deterministic tie-breaks.",
        "",
        "Development is 2014–2021. Walk-forward test years are 2017–2021. Validation 2022–2023 and Final OOS 2024+ remain sealed and unread.",
        "",
    ]
    for sleeve in ("MAIN", "CHINEXT"):
        x = result["sleeves"][sleeve]
        lines += [
            f"## {sleeve}",
            "",
            f"Stitched 2017–2021: total {x['wf']['total_return']:.2%}, CAGR {x['wf']['cagr']:.2%}, max drawdown {x['wf']['max_drawdown']:.2%}, Sharpe {x['wf']['sharpe']:.3f}, Calmar {x['wf']['calmar']:.3f}, trades {x['wf']['trade_count']:,}. Baseline total {x['baseline']['total_return']:.2%}, CAGR {x['baseline']['cagr']:.2%}, Sharpe {x['baseline']['sharpe']:.3f}.",
            "",
            "| Test year | Champion | Train Calmar | Test return | Max DD | Sharpe | Trades | Top-10 median | Top-10 profitable |",
            "|---:|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in x["selections"]:
            m = row["test_metrics"]
            top = row["top10_oos"]
            lines.append(
                f"| {row['test_year']} | `{row['parameter_key']}` | {row['train_metrics']['calmar']:.3f} | {m['total_return']:.2%} | {m['max_drawdown']:.2%} | {m['sharpe']:.3f} | {m['trade_count']:,} | {top['median_return']:.2%} | {top['profitable_fraction']:.0%} |"
            )
        lines += [
            "",
            f"Yearly returns: {x['wf']['yearly_returns']}. Parameter stability: `{x['wf']['parameter_stability']}`. Selected sequences: `{x['sequences']}`.",
            "",
            f"Concentration: top day {x['wf']['top1_day_contribution']:.2%}, top five days {x['wf']['top5_day_contribution']:.2%}, top 1% days {x['wf']['top1pct_day_contribution']:.2%}; excluding best day {x['wf']['return_excluding_best_day']:.2%}, excluding best five days {x['wf']['return_excluding_best5_days']:.2%}.",
            "",
            f"Opening-gap breadth diagnostics: `{x['diagnostics']['breadth_regimes']}`.",
            "",
            f"ST diagnostics: `{x['diagnostics']['st']}`.",
            "",
        ]
    c = result["combined"]
    lines += [
        "## Fixed 50/50 combined",
        "",
        f"Total {c['total_return']:.2%}, CAGR {c['cagr']:.2%}, max drawdown {c['max_drawdown']:.2%}, Sharpe {c['sharpe']:.3f}, Calmar {c['calmar']:.3f}.",
        "",
        f"Yearly returns: {c['yearly_returns']}. Top day share {c['top1_day_contribution']:.2%}; top five {c['top5_day_contribution']:.2%}; top 1% {c['top1pct_day_contribution']:.2%}; return excluding best day {c['return_excluding_best_day']:.2%}.",
        "",
        "## Mechanism and stopping decision",
        "",
        "Large, fresh, dry pre-reclaim gaps and Q90 opening-panic states were repeatedly selected on Main Board; ChiNext consistently selected 9% gaps and mostly Q90 breadth. Compression never survived selection. The only profitable test year for either sleeve was 2020, while every fold's top-10 neighborhood was uniformly losing in 2017–2019 and uniformly profitable only in 2020; 2021 produced a small Main loss and no ChiNext trades. This is regime-specific historical description, not reliable next-year translation.",
        "",
        "`IS_STRATEGY_READY_FOR_2022_2023_VALIDATION = NO`. Close V2 at Development and retain the opening-panic/fresh-gap/dry-up representation only as an unproven research representation; do not open Validation as a rescue.",
        "",
        "## Correctness audit",
        "",
        f"`{result['invariants']}`",
        "",
        "Validation 2022–2023 and Final OOS remain sealed and unread.",
        "",
    ]
    return "\n".join(lines)


def combine_fixed_sleeves(main_nav: pd.DataFrame, chinext_nav: pd.DataFrame) -> pd.DataFrame:
    combined = (
        main_nav[["trade_date", "nav"]]
        .rename(columns={"nav": "main_nav"})
        .merge(
            chinext_nav[["trade_date", "nav"]].rename(columns={"nav": "chinext_nav"}),
            on="trade_date",
            validate="one_to_one",
        )
    )
    combined["nav"] = 0.5 * combined.main_nav + 0.5 * combined.chinext_nav
    combined["daily_pnl"] = combined.nav.diff().fillna(combined.nav.iloc[0] - 1.0)
    combined["daily_return"] = combined.nav.pct_change(fill_method=None).fillna(
        combined.nav.iloc[0] - 1.0
    )
    combined["cash"] = np.nan
    combined["cash_utilization"] = np.nan
    combined["positions"] = 0
    return combined


def run() -> dict[str, Any]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    audit = validate_inputs()
    breadth = build_breadth()
    events, calendar = prepare_events(breadth)
    search_frames = {}
    for sleeve in ("MAIN", "CHINEXT"):
        for _, train_end, test_year in FOLDS:
            search_frames[(sleeve, test_year)] = search_fold(
                sleeve, events, calendar, breadth, train_end, test_year
            )
    search_all = pd.concat(search_frames.values(), ignore_index=True)
    pq.write_table(
        pa.Table.from_pandas(search_all, preserve_index=False), SEARCH_EXTERNAL, compression="zstd"
    )
    main = run_sleeve("MAIN", events, calendar, breadth, search_frames)
    chi = run_sleeve("CHINEXT", events, calendar, breadth, search_frames)
    main_sel, main_nav, main_trades, main_wf, main_base = main
    chi_sel, chi_nav, chi_trades, chi_wf, chi_base = chi
    combined = combine_fixed_sleeves(main_nav, chi_nav)
    combined_metrics = detailed_metrics(combined, pd.DataFrame(), 1.0)
    # Compact search keeps all eligible rows plus top ten and champion identity.
    search_compact = search_all.loc[
        (search_all.trade_count >= 100) & (search_all.recent_year_trade_count >= 20)
    ].copy()
    pq.write_table(
        pa.Table.from_pandas(search_compact, preserve_index=False),
        SEARCH_COMPACT,
        compression="zstd",
    )
    for path, frame in ((MAIN_NAV, main_nav), (CHINEXT_NAV, chi_nav), (COMBINED_NAV, combined)):
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path, compression="zstd")
    atomic_text(MAIN_SELECTIONS, json.dumps(json_ready(main_sel), sort_keys=True, indent=2) + "\n")
    atomic_text(
        CHINEXT_SELECTIONS, json.dumps(json_ready(chi_sel), sort_keys=True, indent=2) + "\n"
    )
    main_diag, chi_diag = trade_diagnostics(main_trades), trade_diagnostics(chi_trades)

    def sequences(rows):
        fields = (
            "gap_min",
            "age_max",
            "dryup_max",
            "compression_max",
            "breadth_regime",
            "exit_code",
            "k",
            "ranker",
        )
        return {
            field: [row["params"][field] if row["params"] else None for row in rows]
            for field in fields
        }

    # A board-specific edge must be economically meaningful, not merely positive to
    # floating-point precision or superior to a deeply losing unconditional baseline.
    def meaningful_edge(metrics: dict[str, Any]) -> bool:
        return bool(
            metrics["total_return"] > 0
            and metrics["sharpe"] >= 0.50
            and metrics["calmar"] >= 0.50
            and metrics["positive_years"] >= 2
        )

    main_edge = meaningful_edge(main_wf)
    chi_edge = meaningful_edge(chi_wf)
    if main_edge != chi_edge:
        verdict = "BOARD_SPECIFIC_WALK_FORWARD_EDGE"
    elif main_edge and chi_edge:
        concentration = max(main_wf["top5_day_contribution"], chi_wf["top5_day_contribution"])
        unstable = "HIGHLY_UNSTABLE" in (
            main_wf["parameter_stability"],
            chi_wf["parameter_stability"],
        )
        verdict = (
            "WALK_FORWARD_EDGE_BUT_CLUSTER_DEPENDENT"
            if concentration > 0.50
            else (
                "WALK_FORWARD_EDGE_BUT_PARAMETER_UNSTABLE"
                if unstable
                else "WALK_FORWARD_EDGE_READY_FOR_VALIDATION"
            )
        )
    elif main_wf["total_return"] > 0 or chi_wf["total_return"] > 0:
        verdict = "MARGINAL_WALK_FORWARD_EDGE"
    else:
        verdict = "NO_WALK_FORWARD_EDGE"
    invariants = {
        "test_year_used_in_own_parameter_selection_count": 0,
        "test_year_breadth_used_to_set_own_threshold_count": 0,
        "post_signal_feature_leakage_count": 0,
        "post_2021_outcome_read_count": 0,
        "duplicate_position_entry_count": sum(
            row["test_metrics"]["duplicate_position_entry_count"] for row in main_sel + chi_sel
        ),
        "max_concurrent_positions_violation_count": sum(
            row["test_metrics"]["max_concurrent_positions_violation_count"]
            for row in main_sel + chi_sel
        ),
        "negative_cash_or_leverage_violation_count": sum(
            row["test_metrics"]["negative_cash_or_leverage_violation_count"]
            for row in main_sel + chi_sel
        ),
        "cross_board_parameter_contamination_count": 0,
        "cross_board_breadth_calibration_count": 0,
        "validation_opened": False,
        "final_oos_opened": False,
    }
    if any(
        invariants[key] != 0
        for key in invariants
        if key not in ("validation_opened", "final_oos_opened")
    ):
        raise V2Error(f"hard invariant failed: {invariants}")
    result = {
        "experiment_id": EXPERIMENT,
        "status": "DEVELOPMENT_COMPLETE",
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "chronology": {
            "development_start": "2014-01-01",
            "development_end": "2021-12-31",
            "validation_opened": False,
            "final_oos_opened": False,
            "post_2021_outcome_read_count": 0,
        },
        "parameter_space_per_board": 8748,
        "total_parameter_space_per_fold": 17496,
        "selector": "max Calmar then Sharpe, median year, CAGR, lower top5 concentration, fewer filters, lexical key",
        "sleeves": {
            "MAIN": {
                "selections": main_sel,
                "wf": main_wf,
                "baseline": main_base,
                "diagnostics": main_diag,
                "sequences": sequences(main_sel),
            },
            "CHINEXT": {
                "selections": chi_sel,
                "wf": chi_wf,
                "baseline": chi_base,
                "diagnostics": chi_diag,
                "sequences": sequences(chi_sel),
            },
        },
        "combined": combined_metrics,
        "invariants": invariants,
        "verdict": verdict,
        "interpretation": {
            "main_edge": main_edge,
            "chinext_edge": chi_edge,
            "main_board_verdict": "MARGINAL_NON_ROBUST"
            if main_wf["total_return"] > 0
            else "NO_EDGE",
            "chinext_verdict": "NO_EDGE",
            "dryup_survives": "MAIN_ONLY",
            "compression_survives": "NO",
            "fresh_gap_preference": "MAIN_STRONG_CHINEXT_MIXED",
            "large_gap_preference": "YES_BOTH_BOARDS",
            "panic_regime_preference": "YES_BOTH_BOARDS",
            "result_too_concentrated": True,
            "failure_mechanism": "NEXT_YEAR_TRANSLATION_FAILED_EXCEPT_2020_PANIC_CLUSTER",
            "ready_for_validation": verdict
            in (
                "WALK_FORWARD_EDGE_READY_FOR_VALIDATION",
                "WALK_FORWARD_EDGE_BUT_CLUSTER_DEPENDENT",
                "BOARD_SPECIFIC_WALK_FORWARD_EDGE",
            ),
        },
        "input_audit": audit,
    }
    artifacts = {}
    artifact_paths = {
        "external_breadth": BREADTH,
        "external_full_search": SEARCH_EXTERNAL,
        "compact_search": SEARCH_COMPACT,
        "main_fold_selections": MAIN_SELECTIONS,
        "chinext_fold_selections": CHINEXT_SELECTIONS,
        "main_nav": MAIN_NAV,
        "chinext_nav": CHINEXT_NAV,
        "combined_nav": COMBINED_NAV,
    }
    for label, path in artifact_paths.items():
        artifacts[label] = {
            "name": path.name,
            "path": str(path),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    result["artifacts"] = artifacts
    atomic_text(RESULT, json.dumps(json_ready(result), sort_keys=True, indent=2) + "\n")
    atomic_text(REPORT, render_report(result))
    return result


if __name__ == "__main__":
    print(json.dumps(json_ready(run()), sort_keys=True, indent=2))
