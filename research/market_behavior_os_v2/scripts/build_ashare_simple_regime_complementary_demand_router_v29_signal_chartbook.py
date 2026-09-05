#!/usr/bin/env python3
"""Build an outcome-blind 36-page semantic chartbook for V29 signal identities."""

from __future__ import annotations

import hashlib
import sys
import textwrap
from pathlib import Path

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_causal_regime_complementary_mechanism_router_v28 as v28  # noqa: E402
import run_ashare_simple_regime_complementary_demand_router_v29 as v29  # noqa: E402


ROOT = Path(__file__).resolve().parents[3]
PDF = ROOT / "output/pdf/ASHARE-SIMPLE-REGIME-COMPLEMENTARY-DEMAND-ROUTER-V29_36_SIGNAL_SEMANTIC_AUDIT.pdf"
INDEX = v29.EXT / "stage_b/signal_semantic_chart_index.csv"
PER_LANE = 12


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def choose_round_robin(frame: pd.DataFrame, count: int) -> pd.DataFrame:
    work = frame.copy()
    work["year"] = pd.to_datetime(work.signal_date).dt.year
    work["hash_key"] = work.event_id.astype(str).map(hash_key)
    groups = {
        int(year): part.sort_values("hash_key", kind="mergesort").reset_index(drop=True)
        for year, part in work.groupby("year", sort=True)
    }
    selected: list[pd.Series] = []
    depth = 0
    while len(selected) < count:
        added = False
        for year in sorted(groups):
            part = groups[year]
            if depth < len(part):
                selected.append(part.iloc[depth])
                added = True
                if len(selected) == count:
                    break
        if not added:
            break
        depth += 1
    return pd.DataFrame(selected).reset_index(drop=True)


def sample_events() -> pd.DataFrame:
    bull = pd.read_parquet(v29.CANDIDATES)
    bull["signal_date"] = pd.to_datetime(bull.signal_date)
    bull["audit_lane"] = "BULL_SIMPLE_5_GROUP"
    bull["source_event_id"] = bull.event_id.astype(str)
    bull["event_id"] = "CHART|BULL|" + bull.source_event_id
    bear = pd.read_parquet(v29.V28_FROZEN_SOURCE)
    bear = bear.loc[bear.source.eq("V27_BEAR")].copy()
    bear["signal_date"] = pd.to_datetime(bear.signal_date)
    bear["audit_lane"] = np.where(
        bear.lane.eq("BEAR_WORSENING_FAST_CAPITULATION"),
        "BEAR_FAST_CAPITULATION",
        "BEAR_SLOW_EXHAUSTION",
    )
    bear["event_id"] = "CHART|BEAR|" + bear.source_event_id.astype(str)
    fields = [
        "event_id",
        "source_event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "audit_lane",
        "market_breadth20",
        "industry20",
        "industry_breadth20",
        "industry_breadth20_delta5",
        "ret60",
        "step_return",
        "close_location",
        "turnover_ratio",
        "market_median_ret20",
        "market_median_ret60",
    ]
    for column in fields:
        if column not in bull:
            bull[column] = np.nan
        if column not in bear:
            bear[column] = np.nan
    population = pd.concat([bull[fields], bear[fields]], ignore_index=True)
    selected = pd.concat(
        [
            choose_round_robin(part, PER_LANE)
            for _lane, part in population.groupby("audit_lane", sort=True)
        ],
        ignore_index=True,
    )
    selected = selected.sort_values(["audit_lane", "signal_date", "event_id"]).reset_index(
        drop=True
    )
    selected["chart_id"] = [f"V29-SEM-{index:03d}" for index in range(1, len(selected) + 1)]
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    selected.to_csv(INDEX, index=False)
    return selected


def load_bars(events: pd.DataFrame) -> pd.DataFrame:
    keys = events[["event_id", "symbol", "signal_date"]].copy()
    keys["signal_date"] = pd.to_datetime(keys.signal_date).dt.date
    con = duckdb.connect()
    con.register("events", keys)
    daily_cte = f"""
      hist AS (
        SELECT * FROM read_parquet('{v28.DAILY_HIST.as_posix()}')
        WHERE trade_date<=DATE '2023-12-31'
      ), base_post AS (
        SELECT * FROM read_parquet('{v28.DAILY_POST_BASE.as_posix()}')
        WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '2026-08-12'
      ), compact_tail AS (
        SELECT p.* FROM read_parquet('{v28.DAILY_POST_COMPACT.as_posix()}') p
        WHERE p.trade_date>DATE '2026-08-12'
          AND NOT EXISTS (
            SELECT 1 FROM read_parquet('{v28.DAILY_V27_TAIL.as_posix()}') t
            WHERE t.symbol=p.symbol AND CAST(t.trade_date AS DATE)=CAST(p.trade_date AS DATE)
          )
      ), v27_tail AS (
        SELECT * FROM read_parquet('{v28.DAILY_V27_TAIL.as_posix()}')
        WHERE trade_date>DATE '2026-08-12'
      ), d AS (
        SELECT * FROM hist
        UNION ALL BY NAME SELECT * FROM base_post
        UNION ALL BY NAME SELECT * FROM compact_tail
        UNION ALL BY NAME SELECT * FROM v27_tail
      ), signal AS (
        SELECT e.*,d.cal_idx AS signal_cal_idx
        FROM events e JOIN d
          ON e.symbol=d.symbol AND CAST(d.trade_date AS DATE)=e.signal_date
      )
    """
    bars = con.execute(
        f"""
        WITH {daily_cte}
        SELECT s.event_id,d.symbol,CAST(d.trade_date AS DATE) AS trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.turnover_fraction,
          s.signal_cal_idx
        FROM signal s JOIN d
          ON s.symbol=d.symbol
         AND d.cal_idx BETWEEN s.signal_cal_idx-90 AND s.signal_cal_idx
        ORDER BY s.event_id,d.cal_idx
        """
    ).fetchdf()
    con.close()
    bars["trade_date"] = pd.to_datetime(bars.trade_date)
    return bars


def draw_candles(axis: plt.Axes, bars: pd.DataFrame) -> None:
    x = np.arange(len(bars))
    for index, row in enumerate(bars.itertuples(index=False)):
        rising = float(row.coord_close) >= float(row.coord_open)
        color = "#d62728" if rising else "#159957"
        axis.vlines(index, row.coord_low, row.coord_high, color=color, linewidth=0.75)
        lower = min(row.coord_open, row.coord_close)
        height = max(abs(row.coord_close - row.coord_open), 1e-5)
        axis.add_patch(
            Rectangle(
                (index - 0.32, lower),
                0.64,
                height,
                facecolor=color,
                edgecolor=color,
                linewidth=0.5,
            )
        )
    axis.set_xlim(-1, len(bars))
    ticks = np.linspace(0, len(bars) - 1, 7).astype(int)
    axis.set_xticks(ticks)
    axis.set_xticklabels(
        [bars.trade_date.iloc[index].strftime("%Y-%m-%d") for index in ticks],
        rotation=20,
        ha="right",
        fontsize=8,
    )
    axis.grid(axis="y", color="#dfe6ee", linewidth=0.6)


def signal_details(event: pd.Series, bars: pd.DataFrame) -> list[str]:
    prior5 = bars.iloc[-6:-1].coord_high.max() if len(bars) >= 6 else np.nan
    prior20 = bars.iloc[-21:-1].coord_high.max() if len(bars) >= 21 else np.nan
    if event.audit_lane == "BULL_SIMPLE_5_GROUP":
        return [
            f"Market breadth20 {event.market_breadth20:.1%}",
            f"Industry ret20 {event.industry20:.2%}; breadth20 {event.industry_breadth20:.1%}; delta5 {event.industry_breadth20_delta5:.1%}",
            f"Stock ret60 {event.ret60:.2%}; signal {event.step_return:.2%}; close location {event.close_location:.1%}",
            f"Turnover ratio {event.turnover_ratio:.2f}; known prior20 high {prior20:.3f}",
        ]
    state = "worsening" if event.audit_lane == "BEAR_FAST_CAPITULATION" else "stabilizing"
    return [
        f"Causal Bear state: {state}",
        f"Market median ret20 {event.market_median_ret20:.2%}; ret60 {event.market_median_ret60:.2%}",
        f"Known prior5 high {prior5:.3f}; known prior20 high {prior20:.3f}",
        "Source detector: frozen V27 lane; no post-signal bar used in this chart",
    ]


def build() -> None:
    events = sample_events()
    bars = load_bars(events)
    PDF.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(PDF, metadata={"Title": "V29 signal semantic audit", "Author": "CY Research OS"}) as pdf:
        for page, event in enumerate(events.itertuples(index=False), start=1):
            event_series = pd.Series(event._asdict())
            part = bars.loc[bars.event_id.eq(event.event_id)].sort_values("cal_idx").reset_index(drop=True)
            if part.empty or pd.Timestamp(part.trade_date.iloc[-1]) != pd.Timestamp(event.signal_date):
                raise RuntimeError(f"chart path mismatch: {event.event_id}")
            fig = plt.figure(figsize=(11.69, 8.27), facecolor="white")
            grid = fig.add_gridspec(6, 1, left=0.07, right=0.97, top=0.82, bottom=0.10, hspace=0.08)
            price_axis = fig.add_subplot(grid[:5, 0])
            volume_axis = fig.add_subplot(grid[5, 0], sharex=price_axis)
            draw_candles(price_axis, part)
            signal_x = len(part) - 1
            price_axis.axvline(signal_x, color="#2369bd", linestyle="--", linewidth=1.2)
            lookback = 20 if event.audit_lane == "BULL_SIMPLE_5_GROUP" else 5
            known_level = part.iloc[-lookback - 1 : -1].coord_high.max()
            price_axis.axhline(known_level, color="#7a3db8", linestyle=":", linewidth=1.2)
            price_axis.text(
                signal_x - 0.35,
                part.coord_high.iloc[-1],
                "Signal close ",
                color="#2369bd",
                fontsize=9,
                ha="right",
                va="bottom",
            )
            price_axis.set_ylabel("QD-010 coordinate price")
            price_axis.set_title(
                f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.audit_lane}",
                loc="left",
                fontsize=13,
                fontweight="bold",
            )
            volume_axis.bar(
                np.arange(len(part)),
                part.turnover_fraction.fillna(0),
                color="#829ab1",
                width=0.70,
            )
            volume_axis.set_ylabel("Turnover", fontsize=8)
            volume_axis.grid(axis="y", color="#e8edf3", linewidth=0.5)
            plt.setp(price_axis.get_xticklabels(), visible=False)
            details = " | ".join(signal_details(event_series, part))
            header = f"Signal date {pd.Timestamp(event.signal_date):%Y-%m-%d} | {details}"
            fig.text(
                0.07,
                0.945,
                "\n".join(textwrap.wrap(header, width=145)),
                fontsize=8.3,
                va="top",
                linespacing=1.25,
            )
            fig.text(
                0.07,
                0.035,
                "Outcome-blind semantic audit: deterministic event-id sample; exactly 90 prior sessions through signal close; no entry, exit, return, or post-signal bar displayed.",
                fontsize=8,
                color="#4c5a67",
            )
            fig.text(0.97, 0.035, f"Page {page}/{len(events)}", ha="right", fontsize=8)
            pdf.savefig(fig, dpi=180)
            plt.close(fig)
    print(PDF)
    print(INDEX)


if __name__ == "__main__":
    build()
