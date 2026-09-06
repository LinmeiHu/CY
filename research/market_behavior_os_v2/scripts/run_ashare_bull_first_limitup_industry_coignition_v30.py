#!/usr/bin/env python3
"""Outcome-blind first-limit-up industry co-ignition research lane."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-FIRST-LIMITUP-INDUSTRY-COIGNITION-V30"
EXT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_first_limitup_industry_coignition_v30"
)
DAILY = v1.DAILY
REGIME = v1.SOURCE_REGIME
INDUSTRY = v1.INDUSTRY_PANEL

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
PROFILE_FREEZE = OS / f"artifacts/{EXPERIMENT}_profile_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
PROFILE_TABLE = EXT / "stage_b/profile_table.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

YEARS = tuple(range(2014, 2024))
DEVELOPMENT_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
PROFILES = {
    "H10_BREAKOUT_FAILURE": {"horizon": 10, "target": None},
    "H15_BREAKOUT_FAILURE": {"horizon": 15, "target": None},
    "T15_H15_BREAKOUT_FAILURE": {"horizon": 15, "target": 0.15},
    "T20_H15_BREAKOUT_FAILURE": {"horizon": 15, "target": 0.20},
}


class ResearchError(RuntimeError):
    """Fail-closed V30 research error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "stage": "A_OUTCOME_BLIND_SEMANTIC_PREFLIGHT",
        "economic_hypothesis": (
            "In a causally known broad bull market, two or more same-industry "
            "stocks making their first limit-up close through a completed 60-session "
            "ceiling on the same day is observable sector-level information arrival. "
            "For a stock that was bounded rather than already extended, the first "
            "limit-up is a price-discovery event backed by synchronized capital, not "
            "a one-candle inference of absorption."
        ),
        "four_grouped_conditions": {
            "PIT_BULL_MARKET": "frozen causal market_regime equals BULL at signal close",
            "HEALTHY_INDUSTRY": (
                "PIT industry n20 >= 5, median completed ret20 > 0, and "
                "positive-ret20 share > 50% at signal close"
            ),
            "FIRST_LIMITUP_PLATFORM_BREAK": (
                "close equals the historical price-limit coordinate; no prior limit-up "
                "close in 20 completed sessions; current coordinate close >= prior "
                "60-session coordinate high while previous close was below it; the "
                "ceiling was approached within 3% on at least three completed sessions "
                "during the prior 60; prior completed 20-session high/low range <=25%; "
                "prior completed 20-session return in [-15%,+15%]; prior 60-session "
                "high/low range <= 40%"
            ),
            "INDUSTRY_COIGNITION": (
                "at least two stocks in the same PIT industry make a first limit-up "
                "60-session ceiling break from bounded prior state on the same signal "
                "close; the traded stock must additionally satisfy the repeated-ceiling "
                "and compact-last20 platform semantics"
            ),
        },
        "decision_clock": "completed daily close",
        "candidate_identity": "signal_date + symbol; one row per symbol/date",
        "entry": "first legal daily open after signal, within three market sessions",
        "translation_profiles": PROFILES,
        "failure_exit": (
            "after T+1, first completed daily close below the frozen prior60 platform "
            "ceiling; exit at the next legal open"
        ),
        "profit_target": "profile target, standing only from the first T+1 session",
        "time_stop": "profile H10 or H15 decision, then next legal open",
        "round_trip_cost": 0.004,
        "profile_selection": {
            "development_years": list(DEVELOPMENT_YEARS),
            "minimum_completed": 400,
            "minimum_positive_years": 5,
            "maximum_mean_holding_sessions": 15,
            "order": [
                "median annual mean net return",
                "pooled mean net return",
                "lower severe-loss10",
                "shorter horizon",
            ],
        },
        "chronology": {
            "2014_2020": "profile development and selection",
            "2021_2023": "predetermined forward check opened only after profile freeze",
        },
        "portfolio": v1.contract_value()["portfolio"],
        "blind_chart": (
            "130 completed stock sessions ending at signal close, plus PIT market and "
            "industry state; no post-signal bar and no outcome"
        ),
        "outcomes_opened": False,
        "post_2023_signal_or_feature_used": False,
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_HIGH_RECALL_CONTRACT",
            "contract_sha256": v1.sha256(CONTRACT),
            "source_hashes": {
                "daily": v1.sha256(DAILY),
                "regime": v1.sha256(REGIME),
                "industry": v1.sha256(INDUSTRY),
            },
            "execution_dependency_sha256": v1.sha256(Path(v1.__file__)),
        },
    )
    return {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
    }


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH d0 AS (
                SELECT d.*,
                  lag(coord_close) OVER w AS prev_coord_close,
                  lag(coord_close,20) OVER w AS lag20_coord_close,
                  max(coord_high) OVER w60 AS prior60_high,
                  min(coord_low) OVER w60 AS prior60_low,
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w20 AS prior20_low,
                  avg(turnover_fraction) OVER w20 AS prior20_turnover,
                  list(coord_high) OVER w60 AS prior60_high_list,
                  count(*) OVER w60 AS prior60_n,
                  sum(
                    CASE WHEN round(close*100)=round(up_limit_price*100)
                    THEN 1 ELSE 0 END
                  ) OVER w20 AS prior20_limitup_count
                FROM read_parquet('{DAILY}') d
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL AND industry_valid
                WINDOW
                  w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                  ),
                  w60 AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
                  )
              ), joined AS (
                SELECT d0.*,
                  lag20_coord_close/NULLIF(coord_close,0)-1 AS unused_guard,
                  prev_coord_close/NULLIF(lag20_coord_close,0)-1 AS prior_completed_ret20,
                  prior60_high/NULLIF(prior60_low,0)-1 AS prior60_range,
                  prior20_high/NULLIF(prior20_low,0)-1 AS prior20_range,
                  turnover_fraction/NULLIF(prior20_turnover,0) AS turnover_expansion,
                  list_count(
                    list_filter(prior60_high_list, value -> value>=0.97*prior60_high)
                  ) AS prior60_ceiling_touch_count,
                  r.market_regime,
                  r.market_median_ret20,
                  r.market_positive_ret20_share,
                  r.latest_source_timestamp AS market_latest_source,
                  i.industry_median_ret20,
                  i.industry_positive_ret20_share,
                  i.industry_median_ret60,
                  i.industry_n20,
                  i.industry_ret20_percentile,
                  i.latest_source_timestamp AS industry_latest_source
                FROM d0
                JOIN read_parquet('{REGIME}') r USING(trade_date)
                JOIN read_parquet('{INDUSTRY}') i USING(trade_date,causal_industry)
                WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
                  AND prior60_n=60
              ), coignition_source AS (
                SELECT *
                FROM joined
                WHERE market_regime='BULL'
                  AND industry_n20>=5
                  AND industry_median_ret20>0
                  AND industry_positive_ret20_share>0.50
                  AND round(close*100)=round(up_limit_price*100)
                  AND prior20_limitup_count=0
                  AND coord_close>=prior60_high
                  AND prev_coord_close<prior60_high
                  AND prior_completed_ret20 BETWEEN -0.15 AND 0.15
                  AND prior60_range<=0.50
              ), base AS (
                SELECT *,
                  count(*) OVER(PARTITION BY trade_date,causal_industry)
                    AS industry_coignition_count,
                  string_agg(symbol, ',' ORDER BY symbol)
                    OVER(PARTITION BY trade_date,causal_industry)
                    AS industry_coignition_symbols
                FROM coignition_source
              )
              SELECT *,
                'FLU30-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,
                decision_at AS feature_latest_timestamp,
                prior60_high AS platform_ceiling,
                ret20-industry_median_ret20 AS stock_minus_industry_ret20,
                'FIRST_LIMITUP_INDUSTRY_COIGNITION' AS admission_lane
              FROM base
              WHERE industry_coignition_count>=2
                AND prior60_ceiling_touch_count>=3
                AND prior20_range<=0.25
                AND prior60_range<=0.40
              ORDER BY trade_date,symbol
            ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in (
        "trade_date",
        "signal_date",
        "available_at",
        "decision_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    causal = (
        frame.available_at.le(frame.decision_at)
        & frame.market_latest_source.le(frame.decision_at)
        & frame.industry_latest_source.le(frame.decision_at)
        & frame.feature_latest_timestamp.le(frame.decision_at)
    )
    if not causal.all():
        raise ResearchError("feature timestamp after signal decision")
    return frame


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    sample = frame.copy()
    sample["year"] = sample.signal_date.dt.year
    sample["hash_order"] = sample.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    rows = [part.sort_values("hash_order").head(3) for _, part in sample.groupby("year")]
    chosen = pd.concat(rows, ignore_index=True)
    if len(chosen) < count:
        remaining = sample.loc[~sample.event_id.isin(chosen.event_id)]
        chosen = pd.concat(
            [chosen, remaining.sort_values("hash_order").head(count - len(chosen))],
            ignore_index=True,
        )
    chosen = chosen.sort_values(["signal_date", "symbol"]).head(count).reset_index(drop=True)
    chosen.insert(0, "chart_id", [f"V30-BLIND-{index:03d}" for index in range(1, len(chosen) + 1)])
    chosen.to_csv(BLIND_INDEX, index=False)
    return chosen


def _load_chart_data(sample: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.astype(str).unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    stock = con.execute(
        f"""
        SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,
          d.coord_close,d.turnover_fraction,d.ret20
        FROM read_parquet('{DAILY}') d JOIN symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    con.close()
    stock["trade_date"] = pd.to_datetime(stock.trade_date)
    regime = v1.read_parquet_duckdb(REGIME)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    industry = v1.read_parquet_duckdb(INDUSTRY)
    industry["trade_date"] = pd.to_datetime(industry.trade_date)
    return (
        {str(symbol): part.reset_index(drop=True) for symbol, part in stock.groupby("symbol")},
        regime,
        industry,
    )


def _draw_chart(
    event: Any,
    stock: pd.DataFrame,
    regime: pd.DataFrame,
    industry: pd.DataFrame,
    compact: bool = False,
) -> Any:
    position = np.flatnonzero(stock.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
    if len(position) != 1:
        raise ResearchError(f"missing chart signal row {event.event_id}")
    end = int(position[0])
    view = stock.iloc[max(0, end - 129) : end + 1].copy()
    start = view.trade_date.min()
    market = regime.loc[regime.trade_date.between(start, event.signal_date)]
    ind = industry.loc[
        industry.causal_industry.eq(event.causal_industry)
        & industry.trade_date.between(start, event.signal_date)
    ]
    figsize = (10, 7.1) if compact else (11.7, 8.3)
    fig, axes = v1.plt.subplots(
        4,
        1,
        figsize=figsize,
        gridspec_kw={"height_ratios": [2.5, 0.65, 0.9, 0.9]},
    )
    x = v1.mdates.date2num(view.trade_date)
    colors = np.where(view.coord_close.ge(view.coord_open), "#dc2626", "#059669")
    axes[0].vlines(x, view.coord_low, view.coord_high, color=colors, linewidth=0.6)
    axes[0].bar(
        x,
        np.maximum(abs(view.coord_close - view.coord_open), view.coord_close.abs() * 0.0005),
        bottom=np.minimum(view.coord_open, view.coord_close),
        color=colors,
        edgecolor=colors,
        width=0.65,
        linewidth=0.25,
    )
    axes[0].axhline(float(event.platform_ceiling), color="#f59e0b", linestyle=":", label="Prior 60d ceiling")
    axes[0].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--", label="First limit-up breakout")
    axes[0].set_title(
        f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry} | co-ignite {event.industry_coignition_count}",
        fontproperties=v1.CJK_FONT,
        fontsize=10 if compact else 12,
    )
    axes[0].legend(loc="upper left", fontsize=7, ncol=2)
    axes[0].grid(alpha=0.2)
    axes[1].bar(view.trade_date, view.turnover_fraction, color=colors, width=0.75, alpha=0.75)
    axes[1].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--")
    axes[1].set_ylabel("Turnover", fontsize=8)
    axes[1].grid(alpha=0.2)
    axes[2].plot(market.trade_date, market.market_median_ret20, color="#166534", label="Market median20")
    axes[2].plot(market.trade_date, market.market_positive_ret20_share, color="#0f766e", label="Market breadth20")
    axes[2].axhline(0, color="black", linewidth=0.6)
    axes[2].legend(loc="upper left", fontsize=7, ncol=2)
    axes[2].set_ylabel("Market", fontsize=8)
    axes[2].grid(alpha=0.2)
    axes[3].plot(ind.trade_date, ind.industry_median_ret20, color="#7c3aed", label="Industry median20")
    axes[3].plot(view.trade_date, view.ret20, color="#b45309", label="Stock ret20")
    axes[3].axhline(0, color="black", linewidth=0.6)
    axes[3].legend(loc="upper left", fontsize=7, ncol=2)
    axes[3].set_ylabel("Industry/stock", fontsize=8)
    axes[3].grid(alpha=0.2)
    axes[3].xaxis.set_major_locator(v1.mdates.MonthLocator(interval=1))
    axes[3].xaxis.set_major_formatter(v1.mdates.DateFormatter("%Y-%m"))
    members = str(event.industry_coignition_symbols)
    if len(members) > 100:
        members = members[:97] + "..."
    fig.text(
        0.01,
        0.01,
        "Outcome-blind; no post-signal bar. "
        f"prior20={event.prior_completed_ret20:+.1%}; prior60 range={event.prior60_range:.1%}; "
        f"prior20 range={event.prior20_range:.1%}; ceiling touches={event.prior60_ceiling_touch_count}; "
        f"industry co-ignition members: {members}",
        fontsize=7,
    )
    fig.tight_layout(rect=[0, 0.035, 1, 1])
    return fig


def render_blind_charts(sample: pd.DataFrame) -> list[Path]:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    stocks, regime, industry = _load_chart_data(sample)
    pngs: list[Path] = []
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            fig = _draw_chart(event, stocks[str(event.symbol)], regime, industry)
            pdf.savefig(fig, dpi=150)
            png = BLIND_DIR / f"{event.chart_id}.png"
            fig.savefig(png, dpi=135)
            pngs.append(png)
            v1.plt.close(fig)
    for group_index in range(0, len(sample), 10):
        chunk = sample.iloc[group_index : group_index + 10]
        fig = v1.plt.figure(figsize=(18, 24))
        outer = fig.add_gridspec(5, 2, hspace=0.38, wspace=0.16)
        for offset, event in enumerate(chunk.itertuples(index=False)):
            stock = stocks[str(event.symbol)]
            position = np.flatnonzero(stock.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
            end = int(position[0])
            view = stock.iloc[max(0, end - 99) : end + 1]
            ax = fig.add_subplot(outer[offset // 2, offset % 2])
            x = v1.mdates.date2num(view.trade_date)
            colors = np.where(view.coord_close.ge(view.coord_open), "#dc2626", "#059669")
            ax.vlines(x, view.coord_low, view.coord_high, color=colors, linewidth=0.5)
            ax.bar(
                x,
                np.maximum(abs(view.coord_close - view.coord_open), view.coord_close.abs() * 0.0005),
                bottom=np.minimum(view.coord_open, view.coord_close),
                color=colors,
                width=0.65,
                linewidth=0,
            )
            ax.axhline(float(event.platform_ceiling), color="#f59e0b", linestyle=":")
            ax.axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--")
            ax.set_title(
                f"{event.chart_id} {event.symbol} {event.causal_industry} co={event.industry_coignition_count}",
                fontsize=9,
                fontproperties=v1.CJK_FONT,
            )
            ax.grid(alpha=0.18)
            ax.xaxis.set_major_locator(v1.mdates.MonthLocator(interval=2))
            ax.xaxis.set_major_formatter(v1.mdates.DateFormatter("%y-%m"))
        contact = BLIND_DIR / f"CONTACT_{group_index // 10 + 1:02d}.png"
        fig.savefig(contact, dpi=145, bbox_inches="tight")
        v1.plt.close(fig)
    return pngs


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    frame = build_candidates()
    sample = blind_sample(frame)
    pngs = render_blind_charts(sample)
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(
            frame[["available_at", "market_latest_source", "industry_latest_source", "feature_latest_timestamp"]]
            .max(axis=1)
            .gt(frame.decision_at)
            .sum()
        ),
        "candidate_after_2023_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "industry_coignition_below_two_count": int(frame.industry_coignition_count.lt(2).sum()),
        "blind_chart_post_signal_bar_count": 0,
        "outcomes_opened": False,
    }
    if any(value for key, value in audit.items() if key != "outcomes_opened"):
        raise ResearchError(str(audit))
    annual = (
        frame.groupby(frame.signal_date.dt.year).size().reindex(YEARS, fill_value=0).astype(int).to_dict()
    )
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_index_sha256": v1.sha256(BLIND_INDEX),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
        "candidate_count": len(frame),
        "annual_candidate_counts": annual,
        "unique_signal_dates": int(frame.signal_date.nunique()),
        "unique_symbols": int(frame.symbol.nunique()),
        "blind_chart_count": len(pngs),
        "audit": audit,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_index_sha256": v1.sha256(BLIND_INDEX),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in expected.items()
        if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def load_trade_daily_bounded(symbols: list[str], *, through: str) -> pd.DataFrame:
    through_date = pd.Timestamp(through)
    registry = pd.DataFrame({"symbol": sorted(set(map(str, symbols)))})
    con = duckdb.connect()
    con.register("registry", registry)
    if through_date <= pd.Timestamp("2023-12-31"):
        query = f"""
            SELECT d.* FROM read_parquet('{DAILY}') d JOIN registry r USING(symbol)
            WHERE d.trade_date BETWEEN DATE '2014-01-01' AND DATE '{through_date.date()}'
            ORDER BY d.symbol,d.trade_date
        """
    else:
        query = f"""
            WITH old AS (
              SELECT * FROM read_parquet('{DAILY}')
              WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
            ), tail AS (
              SELECT * FROM read_parquet('{v1.DAILY_TAIL}')
              WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '{through_date.date()}'
            ), d AS (SELECT * FROM old UNION ALL BY NAME SELECT * FROM tail)
            SELECT d.* FROM d JOIN registry r USING(symbol)
            ORDER BY d.symbol,d.trade_date
        """
    frame = con.execute(query).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def build_outcomes(
    candidates: pd.DataFrame,
    *,
    through: str,
    output: Path,
) -> tuple[pd.DataFrame, dict[str, int]]:
    daily = load_trade_daily_bounded(candidates.symbol.astype(str).unique().tolist(), through=through)
    groups = {
        str(symbol): part.sort_values("trade_date").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        part = groups.get(str(event.symbol))
        if part is None:
            raise ResearchError(f"missing trade history {event.event_id}")
        positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
        if len(positions) != 1:
            raise ResearchError(f"missing signal row {event.event_id}")
        signal_pos = int(positions[0])
        lineage = float(event.invalid_step_cum)
        entry_pos: int | None = None
        for pos in range(signal_pos + 1, len(part)):
            row = part.iloc[pos]
            if int(row.cal_idx) > int(event.cal_idx) + 3:
                break
            if v1.legal_buy(row, lineage):
                entry_pos = pos
                break
        for profile, settings in PROFILES.items():
            base = {
                "event_id": event.event_id,
                "symbol": event.symbol,
                "sleeve": event.sleeve,
                "signal_date": event.signal_date,
                "signal_cal_idx": int(event.cal_idx),
                "profile": profile,
                "platform_ceiling": float(event.platform_ceiling),
            }
            if entry_pos is None:
                rows.append({**base, "status": "NO_LEGAL_ENTRY"})
                continue
            entry = part.iloc[entry_pos]
            entry_price = float(entry.coord_open)
            horizon_idx = int(entry.cal_idx) + int(settings["horizon"])
            target = (
                None
                if settings["target"] is None
                else entry_price * (1 + float(settings["target"]))
            )
            exit_pos: int | None = None
            exit_price: float | None = None
            exit_reason: str | None = None
            exit_decision_idx: int | None = None
            for pos in range(entry_pos + 1, len(part)):
                row = part.iloc[pos]
                if not v1.legal_state(row, lineage):
                    continue
                if target is not None and float(row.coord_high) >= target:
                    exit_pos = pos
                    exit_price = target
                    exit_reason = f"TARGET_{int(float(settings['target']) * 100)}"
                    exit_decision_idx = int(row.cal_idx)
                    break
                if float(row.coord_close) < float(event.platform_ceiling):
                    exit_decision_idx = int(row.cal_idx)
                    for sell_pos in range(pos + 1, len(part)):
                        if v1.legal_sell_open(part.iloc[sell_pos], lineage):
                            exit_pos = sell_pos
                            exit_price = float(part.iloc[sell_pos].coord_open)
                            exit_reason = "PLATFORM_BREAK_FAILURE"
                            break
                    break
                if int(row.cal_idx) >= horizon_idx:
                    exit_decision_idx = int(row.cal_idx)
                    for sell_pos in range(pos + 1, len(part)):
                        if v1.legal_sell_open(part.iloc[sell_pos], lineage):
                            exit_pos = sell_pos
                            exit_price = float(part.iloc[sell_pos].coord_open)
                            exit_reason = f"H{settings['horizon']}_TIME_STOP"
                            break
                    break
            if exit_pos is None or exit_price is None:
                rows.append(
                    {
                        **base,
                        "status": "INCOMPLETE_OUTCOME_TAIL",
                        "entry_date": entry.trade_date,
                        "entry_cal_idx": int(entry.cal_idx),
                        "entry_price": entry_price,
                    }
                )
                continue
            exit_row = part.iloc[exit_pos]
            path = part.iloc[entry_pos : exit_pos + 1]
            if path.invalid_step_cum.ne(lineage).any():
                rows.append(
                    {
                        **base,
                        "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                        "entry_date": entry.trade_date,
                        "entry_cal_idx": int(entry.cal_idx),
                        "entry_price": entry_price,
                    }
                )
                continue
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
                    "exit_decision_cal_idx": exit_decision_idx,
                    "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
                    "gross_return": gross,
                    "net_return": gross - 0.004,
                }
            )
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    v1.write_parquet(outcomes, output)
    audit = {
        "signal_bar_fill_count": int(
            (outcomes.entry_date.notna() & outcomes.entry_date.le(outcomes.signal_date)).sum()
        ),
        "t1_same_day_exit_count": int(
            (
                outcomes.status.eq("COMPLETED")
                & outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)
            ).sum()
        ),
        "invalid_lineage_completed_count": 0,
    }
    return outcomes, audit


def metrics(frame: pd.DataFrame, target: float | None = None) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    if completed.empty:
        return {
            "completed_trades": 0,
            "mean_net": None,
            "median_net": None,
            "win_rate": None,
            "severe_loss10": None,
            "target_hit_rate": None,
            "mean_holding_sessions": None,
            "median_holding_sessions": None,
        }
    target_reason = None if target is None else f"TARGET_{int(target * 100)}"
    return {
        "completed_trades": len(completed),
        "mean_net": float(completed.net_return.mean()),
        "median_net": float(completed.net_return.median()),
        "win_rate": float(completed.net_return.gt(0).mean()),
        "severe_loss10": float(completed.net_return.le(-0.10).mean()),
        "target_hit_rate": (
            None if target_reason is None else float(completed.exit_reason.eq(target_reason).mean())
        ),
        "mean_holding_sessions": float(completed.holding_sessions.mean()),
        "median_holding_sessions": float(completed.holding_sessions.median()),
    }


def profile_table(outcomes: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for profile, settings in PROFILES.items():
        part = outcomes.loc[outcomes.profile.eq(profile)]
        annual = {
            str(year): metrics(
                part.loc[part.signal_date.dt.year.eq(year)], settings["target"]
            )
            for year in DEVELOPMENT_YEARS
        }
        means = [value["mean_net"] for value in annual.values() if value["mean_net"] is not None]
        rows.append(
            {
                "profile": profile,
                **metrics(part, settings["target"]),
                "positive_years": int(sum(value > 0 for value in means)),
                "median_annual_mean_net": float(np.median(means)),
                "annual_json": json.dumps(annual, sort_keys=True),
            }
        )
    table = pd.DataFrame(rows)
    v1.write_parquet(table, PROFILE_TABLE)
    return table


def select_profile(table: pd.DataFrame) -> pd.Series | None:
    eligible = table.loc[
        table.completed_trades.ge(400)
        & table.positive_years.ge(5)
        & table.mean_holding_sessions.le(15)
    ].copy()
    if eligible.empty:
        return None
    eligible["profile_order"] = eligible.profile.map(
        {profile: index for index, profile in enumerate(PROFILES)}
    )
    eligible = eligible.sort_values(
        ["median_annual_mean_net", "mean_net", "severe_loss10", "profile_order"],
        ascending=[False, False, True, True],
        kind="mergesort",
    )
    return eligible.iloc[0]


def annual_metrics(frame: pd.DataFrame, target: float | None) -> dict[str, Any]:
    return {
        str(year): metrics(frame.loc[frame.signal_date.dt.year.eq(year)], target)
        for year in YEARS
    }


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    development = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT_YEARS)].copy()
    dev_outcomes, dev_audit = build_outcomes(
        development,
        through="2021-03-31",
        output=DEV_OUTCOMES,
    )
    if any(dev_audit.values()):
        raise ResearchError(f"development execution audit failed: {dev_audit}")
    table = profile_table(dev_outcomes)
    selected = select_profile(table)
    if selected is None:
        result = {
            "experiment": EXPERIMENT,
            "verdict": "FIRST_LIMITUP_COIGNITION_DEVELOPMENT_FAILED",
            "stage_a": stage_a,
            "profile_table": table.replace({np.nan: None}).to_dict("records"),
            "development_audit": dev_audit,
            "forward_years_opened": False,
            "post_2023_rows_opened": False,
        }
        v1.write_json(RESULT, result)
        return result
    profile = str(selected.profile)
    profile_freeze = {
        "experiment": EXPERIMENT,
        "selected_profile": profile,
        "selected_from_years": list(DEVELOPMENT_YEARS),
        "profile_table_sha256": v1.sha256(PROFILE_TABLE),
        "development_outcomes_sha256": v1.sha256(DEV_OUTCOMES),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "contract_sha256": v1.sha256(CONTRACT),
        "forward_outcomes_opened": False,
    }
    v1.write_json(PROFILE_FREEZE, profile_freeze)
    forward = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)].copy()
    forward_outcomes, forward_audit = build_outcomes(
        forward,
        through="2024-03-31",
        output=FORWARD_OUTCOMES,
    )
    if any(forward_audit.values()):
        raise ResearchError(f"forward execution audit failed: {forward_audit}")
    outcomes = pd.concat([dev_outcomes, forward_outcomes], ignore_index=True)
    selected_all = outcomes.loc[outcomes.profile.eq(profile)].merge(
        candidates[
            [
                "event_id",
                "industry_positive_ret20_share",
                "stock_minus_industry_ret20",
                "turnover_expansion",
                "industry_coignition_count",
                "prior60_ceiling_touch_count",
                "prior20_range",
            ]
        ],
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    daily = load_trade_daily_bounded(
        selected_all.symbol.astype(str).unique().tolist(), through="2024-03-31"
    )
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, _nav, portfolio = v1.replay_portfolio(selected_all, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    settings = PROFILES[profile]
    overall = metrics(accepted.assign(status="COMPLETED"), settings["target"])
    annual = annual_metrics(accepted.assign(status="COMPLETED"), settings["target"])
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "capacity_completed_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_gt_5pct": overall["mean_net"] > 0.05,
        "mean_holding_lt_15": overall["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(annual[str(year)]["mean_net"] > 0 for year in FORWARD_YEARS),
        "at_least_8_of_10_positive_years": sum(
            annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0
            for year in YEARS
        )
        >= 8,
        "mean_excluding_best5_dates_positive": concentration[
            "mean_excluding_best_five_signal_dates"
        ]
        > 0,
        "top5_date_positive_pnl_share_le_25pct": concentration[
            "top_five_signal_date_positive_pnl_share"
        ]
        <= 0.25,
    }
    verdict = (
        "FIRST_LIMITUP_INDUSTRY_COIGNITION_EDGE"
        if all(gate.values())
        else "FIRST_LIMITUP_INDUSTRY_COIGNITION_FAILS_TARGET"
    )
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "selected_profile": profile,
        "profile_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "completed_trades_per_year": len(accepted) / 10,
        "overall_2014_2023": overall,
        "annual": annual,
        "portfolio": portfolio,
        "concentration": concentration,
        "gate": gate,
        "audit": {
            **dev_audit,
            **{f"forward_{key}": value for key, value in forward_audit.items()},
            "feature_after_decision_count": int(
                candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()
            ),
            "profile_selected_before_2021_2023_open": True,
            "post_2023_rows_used_only_to_resolve_2023_trades": True,
        },
        "hashes": {
            "profile_freeze": v1.sha256(PROFILE_FREEZE),
            "development_outcomes": v1.sha256(DEV_OUTCOMES),
            "forward_outcomes": v1.sha256(FORWARD_OUTCOMES),
            "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED),
            "nav": v1.sha256(NAV),
        },
    }
    v1.write_json(RESULT, result)
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{verdict}`",
        "",
        f"Selected profile: `{profile}`.",
        "",
        "|Year|Trades|Mean net|Median net|Win|Severe10|Mean hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = annual[str(year)]
        lines.append(
            f"|{year}|{item['completed_trades']}|{v1.pct(item['mean_net'])}|"
            f"{v1.pct(item['median_net'])}|{v1.pct(item['win_rate'])}|"
            f"{v1.pct(item['severe_loss10'])}|"
            f"{item['mean_holding_sessions'] if item['mean_holding_sessions'] is not None else '—'}|"
        )
    lines += ["", f"Gate: `{json.dumps(gate, sort_keys=True)}`.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, default=str))
    else:
        parser.error("choose --stage-a")


if __name__ == "__main__":
    main()
