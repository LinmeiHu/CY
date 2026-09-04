#!/usr/bin/env python3
"""Causal bull-regime translation of the frozen quiet-inventory breakout."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.font_manager import FontProperties

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-QUIET-INVENTORY-INDUSTRY-ACCEPTANCE-V1"
START_HEAD = "617ec30a93fb0419a9b822495e5067e11209815e"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_quiet_inventory_industry_acceptance_v1")

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

CANDIDATES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_repricing_long_translation_v2/"
    "stage_a/candidates_features_2014_2023_frozen.parquet"
)
SOURCE_REGIME = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_causal_market_regime_routed_simple_strategy_v1/"
    "stage_a/causal_market_regime_2014_2023.parquet"
)
SOURCE_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_quiet_inventory_information_gap_breakout_v1/stage_b/outcomes.parquet"
)
DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
DAILY_TAIL = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)

ENRICHED = EXT / "stage_a/enriched_candidates.parquet"
INDUSTRY_PANEL = EXT / "stage_a/industry_state.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_40_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

RULES = (
    "BULL_ONLY",
    "BULL_INDUSTRY_POSITIVE",
    "BULL_INDUSTRY_MAJORITY",
    "BULL_INDUSTRY_LEADER",
)
PROFILES = ("H10_NEXT_OPEN", "T10_H20_NO_STOP")
DISCOVERY_YEARS = tuple(range(2014, 2019))
CONFIRMATION_YEARS = (2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
ALL_SIGNAL_YEARS = tuple(range(2014, 2024))
K_PER_SLEEVE = 30
MAX_NEW_PER_SLEEVE_DATE = 10
ENTRY_COST = 0.002
EXIT_COST = 0.002
CJK_FONT = FontProperties(fname="/System/Library/Fonts/STHeiti Light.ttc")


class ResearchError(RuntimeError):
    """Fail-closed research error."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(temp, index=False, compression="zstd")
    temp.replace(path)


def read_parquet_duckdb(path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT * FROM read_parquet('{path}')").fetchdf()
    finally:
        con.close()


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "In a causally observed broad bull market, a stock leaving a quiet "
            "forty-session inventory platform through an executable non-limit "
            "information gap and high-location volume expansion represents shared "
            "demand acceptance. Positive PIT industry participation should distinguish "
            "persistent thematic repricing from isolated stock noise."
        ),
        "independence": (
            "No downward gap, collapse zone, gap repair, V6, V7, V26 or V27 "
            "identity or outcome is used."
        ),
        "base_signal": (
            "Exact frozen ASHARE-QUIET-INVENTORY-INFORMATION-GAP-BREAKOUT-V1 "
            "outcome-blind identity."
        ),
        "market_regime": {
            "decision_at": "completed signal-session close",
            "BULL": (
                "market median ret20 > 0 AND positive-ret20 share > 0.50 AND "
                "market median ret60 > 0 AND positive-ret60 share > 0.50"
            ),
            "BEAR": ("both medians <= 0 AND both positive-return shares <= 0.50"),
            "TRANSITION": "all other combinations or missing required state",
            "strategy_action": "trade only BULL; BEAR and TRANSITION hold cash",
        },
        "industry_state": {
            "identity": "signal-day PIT causal_industry",
            "minimum_members": 5,
            "positive": "industry median completed ret20 > 0",
            "majority": "industry positive-ret20 share > 0.50",
            "leader": "stock completed ret20 >= industry median completed ret20",
            "latest_source": "completed signal-session close",
        },
        "bounded_rules": list(RULES),
        "bounded_translations": {
            "H10_NEXT_OPEN": "next legal open after ten completed holding sessions",
            "T10_H20_NO_STOP": (
                "+10% coordinate target from first T+1-sellable session; otherwise "
                "next legal open after twenty completed holding sessions"
            ),
            "round_trip_cost": 0.004,
        },
        "selection": {
            "discovery": [2014, 2015, 2016, 2017, 2018],
            "candidate_must_have_completed_trades": 150,
            "support_amendment": (
                "Outcome-blind correction from 250 to 150 because frozen Stage-A "
                "coverage proved the maximum possible BULL discovery population "
                "was 241; amended before any candidate performance was selected "
                "or inspected."
            ),
            "candidate_positive_discovery_years_min": 3,
            "candidate_mean_holding_sessions_max": 15,
            "order": [
                "highest median annual mean net return",
                "higher pooled mean net return",
                "higher completed trade count",
                "fewer industry conditions",
                "shorter profile",
            ],
            "confirmation": [2019, 2020, 2021],
            "post_observation_diagnostic": [2022, 2023],
        },
        "portfolio": {
            "Main_sleeve": 0.50,
            "ChiNext_sleeve": 0.50,
            "K_per_sleeve": K_PER_SLEEVE,
            "maximum_new_positions_per_sleeve_date": MAX_NEW_PER_SLEEVE_DATE,
            "position_size": "1/K of current sleeve NAV",
            "same_symbol_overlap": "forbidden",
            "leverage": False,
            "cross_sleeve_transfer": False,
            "collision_rank": [
                "industry_positive_ret20_share descending",
                "stock_minus_industry_ret20 descending",
                "turnover_expansion descending",
                "event_id ascending",
            ],
        },
        "required_gate": {
            "2014_2023_capacity_accepted_completed_trades_per_year_gt": 50,
            "2014_2023_mean_net_return_min": 0.03,
            "mean_holding_sessions_max": 15,
            "confirmation_each_year_mean_positive": True,
            "2022_mean_positive": True,
            "2023_mean_positive": True,
            "mean_excluding_best_five_signal_dates_positive": True,
            "top_five_signal_date_positive_pnl_share_max": 0.25,
        },
        "governance": {
            "rules_and_profiles_frozen_before_new_filtered_outcomes": True,
            "repository_2024_plus_signal_or_feature_use": False,
            "post_2023_rows_allowed_only_to_resolve_pre_2024_trades": True,
            "no_same_bar_fill": True,
            "missing_required_lineage": "fail closed",
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_BULL_REGIME_INDUSTRY_TRANSLATION_FREEZE",
            "contract_sha256": sha256(CONTRACT),
            "source_candidate_sha256": sha256(CANDIDATES),
            "source_regime_sha256": sha256(SOURCE_REGIME),
            "stage_order": "Stage A candidates/state/charts/freeze, then Stage B outcomes",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def build_industry_panel() -> pd.DataFrame:
    INDUSTRY_PANEL.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH d AS (
                SELECT trade_date,cal_idx,symbol,sleeve,causal_industry,ret20,ret60,
                  decision_at,available_at
                FROM read_parquet('{DAILY}')
                WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL
              ), i0 AS (
                SELECT trade_date,causal_industry,
                  median(ret20) AS industry_median_ret20,
                  avg((ret20>0)::INT) FILTER (WHERE ret20 IS NOT NULL)
                    AS industry_positive_ret20_share,
                  median(ret60) AS industry_median_ret60,
                  count(ret20) AS industry_n20,
                  max(decision_at) AS latest_source_timestamp
                FROM d GROUP BY trade_date,causal_industry
              ), i AS (
                SELECT *,percent_rank() OVER (
                  PARTITION BY trade_date ORDER BY industry_median_ret20,causal_industry
                ) AS industry_ret20_percentile
                FROM i0 WHERE industry_n20>=5
              )
              SELECT * FROM i ORDER BY trade_date,causal_industry
            ) TO '{INDUSTRY_PANEL}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    return pd.read_parquet(INDUSTRY_PANEL)


def build_enriched_candidates() -> tuple[pd.DataFrame, dict[str, Any]]:
    industry = build_industry_panel()
    candidates = read_parquet_duckdb(CANDIDATES)
    regime = pd.read_parquet(SOURCE_REGIME)
    for frame, columns in (
        (candidates, ("trade_date", "signal_date", "decision_at", "available_at")),
        (regime, ("trade_date", "latest_source_timestamp")),
        (industry, ("trade_date", "latest_source_timestamp")),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    enriched = candidates.merge(
        regime,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
        suffixes=("", "_market"),
    ).drop(columns=["trade_date_market"])
    enriched = enriched.merge(
        industry,
        left_on=["signal_date", "causal_industry"],
        right_on=["trade_date", "causal_industry"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_industry"),
    ).drop(columns=["trade_date_industry"])
    enriched["stock_minus_industry_ret20"] = enriched.ret20 - enriched.industry_median_ret20
    enriched["feature_latest_timestamp"] = enriched[
        ["decision_at", "latest_source_timestamp", "latest_source_timestamp_industry"]
    ].max(axis=1)
    enriched["causal_feature_valid"] = (
        enriched.feature_latest_timestamp.le(enriched.decision_at)
        & enriched.available_at.le(enriched.decision_at)
        & enriched.signal_date.le(pd.Timestamp("2023-12-31"))
        & enriched.hard_valid.fillna(False)
        & enriched.history_valid.fillna(False)
        & enriched.current_valid.fillna(False)
        & enriched.industry_valid.fillna(False)
        & enriched.historical_identity_valid.fillna(False)
        & enriched.industry_snapshot_id.notna()
        & enriched.market_regime.notna()
    )
    if enriched.event_id.duplicated().any() or len(enriched) != 1998:
        raise ResearchError("candidate identity conservation failure")
    if (~enriched.causal_feature_valid).any():
        raise ResearchError("candidate state chronology/lineage failure")
    for rule in RULES:
        enriched[f"pass_{rule}"] = rule_mask(enriched, rule)
    write_parquet(enriched, ENRICHED)
    coverage: dict[str, Any] = {}
    for rule in RULES:
        selected = enriched.loc[enriched[f"pass_{rule}"]]
        coverage[rule] = {
            "raw_candidates": len(selected),
            "average_per_year": len(selected) / 10,
            "annual": (
                selected.groupby(selected.signal_date.dt.year)
                .size()
                .reindex(ALL_SIGNAL_YEARS, fill_value=0)
                .astype(int)
                .to_dict()
            ),
        }
    return enriched, coverage


def rule_mask(frame: pd.DataFrame, rule: str) -> pd.Series:
    bull = frame.market_regime.eq("BULL")
    industry_positive = frame.industry_n20.ge(5) & frame.industry_median_ret20.gt(0)
    industry_majority = frame.industry_positive_ret20_share.gt(0.50)
    stock_leader = frame.stock_minus_industry_ret20.ge(0)
    if rule == "BULL_ONLY":
        value = bull
    elif rule == "BULL_INDUSTRY_POSITIVE":
        value = bull & industry_positive
    elif rule == "BULL_INDUSTRY_MAJORITY":
        value = bull & industry_positive & industry_majority
    elif rule == "BULL_INDUSTRY_LEADER":
        value = bull & industry_positive & industry_majority & stock_leader
    else:
        raise ResearchError(f"unknown rule {rule}")
    return value.fillna(False)


def deterministic_blind_sample(enriched: pd.DataFrame, count: int = 40) -> pd.DataFrame:
    eligible = enriched.loc[enriched.pass_BULL_ONLY].copy()
    eligible["year"] = eligible.signal_date.dt.year
    eligible["hash_order"] = eligible.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    rows: list[pd.DataFrame] = []
    for _, part in eligible.groupby(["year", "sleeve"], sort=True):
        rows.append(part.sort_values("hash_order").head(2))
    sample = pd.concat(rows, ignore_index=True).sort_values("hash_order").head(count)
    if len(sample) < count:
        remaining = eligible.loc[~eligible.event_id.isin(sample.event_id)]
        sample = pd.concat(
            [sample, remaining.sort_values("hash_order").head(count - len(sample))],
            ignore_index=True,
        )
    sample = sample.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    sample.insert(0, "chart_id", [f"BULL-BLIND-{i:03d}" for i in range(1, len(sample) + 1)])
    sample[
        [
            "chart_id",
            "event_id",
            "symbol",
            "sleeve",
            "causal_industry",
            "signal_date",
            "market_regime",
            "industry_median_ret20",
            "industry_positive_ret20_share",
            "ret20",
            "stock_minus_industry_ret20",
        ]
    ].to_csv(BLIND_INDEX, index=False)
    return sample


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    daily = con.execute(
        f"""
        SELECT d.trade_date,d.cal_idx,d.symbol,d.sleeve,d.causal_industry,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.volume,
          d.turnover_fraction,d.ret20
        FROM read_parquet('{DAILY}') d JOIN symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    groups = {key: part.reset_index(drop=True) for key, part in daily.groupby("symbol")}
    industry = pd.read_parquet(INDUSTRY_PANEL)
    industry["trade_date"] = pd.to_datetime(industry.trade_date)
    regime = pd.read_parquet(SOURCE_REGIME)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    with PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            part = groups[event.symbol]
            positions = np.flatnonzero(
                part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy()
            )
            if len(positions) != 1:
                raise ResearchError(f"chart signal row missing {event.event_id}")
            end = int(positions[0])
            stock = part.iloc[max(0, end - 119) : end + 1].copy()
            start_date = stock.trade_date.min()
            market = regime.loc[regime.trade_date.between(start_date, event.signal_date)].copy()
            ind = industry.loc[
                industry.causal_industry.eq(event.causal_industry)
                & industry.trade_date.between(start_date, event.signal_date)
            ].copy()
            fig, axes = plt.subplots(
                4,
                1,
                figsize=(11.7, 8.3),
                gridspec_kw={"height_ratios": [2.4, 0.7, 1, 1]},
            )
            ax = axes[0]
            x = mdates.date2num(stock.trade_date)
            rising = stock.coord_close.ge(stock.coord_open).to_numpy()
            colors = np.where(rising, "#dc2626", "#059669")
            ax.vlines(
                x,
                stock.coord_low,
                stock.coord_high,
                color=colors,
                linewidth=0.65,
                alpha=0.9,
            )
            body_low = np.minimum(stock.coord_open, stock.coord_close)
            body_height = np.maximum(
                np.abs(stock.coord_close - stock.coord_open),
                stock.coord_close.abs() * 0.0005,
            )
            ax.bar(
                x,
                body_height,
                bottom=body_low,
                width=0.65,
                color=colors,
                edgecolor=colors,
                linewidth=0.3,
                label="Daily candle",
            )
            ax.axvline(
                pd.Timestamp(event.signal_date),
                color="#dc2626",
                linestyle="--",
                linewidth=1.2,
                label="Signal close",
            )
            ax.axhline(
                float(event.platform_high),
                color="#ea580c",
                linestyle=":",
                label="Prior 40d ceiling",
            )
            ax.set_title(
                f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",
                fontproperties=CJK_FONT,
            )
            ax.legend(loc="upper left", ncol=3, fontsize=8)
            ax.grid(alpha=0.2)
            axes[1].bar(
                stock.trade_date,
                stock.turnover_fraction,
                color=colors,
                width=0.75,
                alpha=0.7,
            )
            axes[1].axvline(
                pd.Timestamp(event.signal_date),
                color="#dc2626",
                linestyle="--",
                linewidth=1.0,
            )
            axes[1].set_ylabel("Turnover")
            axes[1].grid(alpha=0.2)
            axes[2].plot(
                market.trade_date,
                market.market_median_ret20,
                label="Market median ret20",
                color="#166534",
            )
            axes[2].plot(
                market.trade_date,
                market.market_median_ret60,
                label="Market median ret60",
                color="#0f766e",
            )
            axes[2].axhline(0, color="black", linewidth=0.7)
            axes[2].set_ylabel("Market")
            axes[2].legend(loc="upper left", fontsize=8, ncol=2)
            axes[2].grid(alpha=0.2)
            axes[3].plot(
                ind.trade_date,
                ind.industry_median_ret20,
                label="Industry median ret20",
                color="#7c3aed",
            )
            axes[3].plot(
                stock.trade_date, stock.ret20, label="Stock ret20", color="#b45309", alpha=0.85
            )
            axes[3].axhline(0, color="black", linewidth=0.7)
            axes[3].set_ylabel("Industry / stock")
            axes[3].legend(loc="upper left", fontsize=8, ncol=2)
            axes[3].grid(alpha=0.2)
            axes[3].xaxis.set_major_locator(mdates.MonthLocator(interval=1))
            axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
            fig.text(
                0.01,
                0.01,
                "Signal-only chart. BULL at close. "
                f"Industry median20 {event.industry_median_ret20:+.2%}; "
                "industry positive share "
                f"{event.industry_positive_ret20_share:.1%}; "
                f"stock ret20 {event.ret20:+.2%}. No post-signal bar.",
                fontsize=8,
            )
            fig.tight_layout(rect=[0, 0.035, 1, 1])
            pdf.savefig(fig, dpi=160)
            plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    enriched, coverage = build_enriched_candidates()
    sample = deterministic_blind_sample(enriched)
    render_blind_charts(sample)
    audit = {
        "candidate_identity_duplicate_count": int(enriched.event_id.duplicated().sum()),
        "feature_after_decision_count": int(
            enriched.feature_latest_timestamp.gt(enriched.decision_at).sum()
        ),
        "availability_after_decision_count": int(
            enriched.available_at.gt(enriched.decision_at).sum()
        ),
        "post_2023_signal_count": int(enriched.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "noncausal_feature_row_count": int((~enriched.causal_feature_valid).sum()),
        "blind_chart_post_signal_bar_count": 0,
        "outcome_opened": False,
    }
    if any(value for key, value in audit.items() if key != "outcome_opened"):
        raise ResearchError(f"Stage-A audit failure {audit}")
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_BULL_REGIME_INDUSTRY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": {
            "candidates": sha256(CANDIDATES),
            "regime": sha256(SOURCE_REGIME),
            "daily": sha256(DAILY),
        },
        "candidate_count": len(enriched),
        "regime_counts": enriched.market_regime.value_counts().astype(int).to_dict(),
        "coverage": coverage,
        "blind_chart_count": len(sample),
        "blind_index_sha256": sha256(BLIND_INDEX),
        "blind_pdf_sha256": sha256(BLIND_PDF),
        "enriched_candidates_sha256": sha256(ENRICHED),
        "industry_panel_sha256": sha256(INDUSTRY_PANEL),
        "audit": audit,
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    current = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "enriched_candidates_sha256": sha256(ENRICHED),
        "industry_panel_sha256": sha256(INDUSTRY_PANEL),
        "blind_index_sha256": sha256(BLIND_INDEX),
        "blind_pdf_sha256": sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in current.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")
    return {"verified": True, "hashes": current}


def load_trade_daily(symbols: list[str]) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    con = duckdb.connect()
    con.register("registry", registry)
    frame = con.execute(
        f"""
        WITH old AS (
          SELECT * FROM read_parquet('{DAILY}')
          WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
        ), tail AS (
          SELECT * FROM read_parquet('{DAILY_TAIL}')
          WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '2024-03-31'
        ), d AS (SELECT * FROM old UNION ALL BY NAME SELECT * FROM tail)
        SELECT d.* FROM d JOIN registry r USING(symbol)
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def legal_state(row: pd.Series, lineage: float) -> bool:
    required_true = (
        "hard_valid",
        "history_valid",
        "current_valid",
        "corporate_action_valid",
        "current_day_data_tradable",
        "market_rule_valid",
    )
    if any(pd.isna(row.get(field)) or not bool(row.get(field)) for field in required_true):
        return False
    if pd.isna(row.get("corporate_action_blocking")) or bool(row.get("corporate_action_blocking")):
        return False
    if pd.isna(row.get("trade_status")) or int(row.trade_status) != 1:
        return False
    if pd.isna(row.get("invalid_step_cum")):
        return False
    return float(row.invalid_step_cum) == float(lineage)


def legal_buy(row: pd.Series, lineage: float) -> bool:
    return legal_state(row, lineage) and round(float(row.open) * 100) < round(
        float(row.up_limit_price) * 100
    )


def legal_sell_open(row: pd.Series, lineage: float) -> bool:
    return legal_state(row, lineage) and round(float(row.open) * 100) > round(
        float(row.down_limit_price) * 100
    )


def build_outcomes() -> tuple[pd.DataFrame, dict[str, Any]]:
    candidates = read_parquet_duckdb(CANDIDATES)
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    daily = load_trade_daily(candidates.symbol.astype(str).unique().tolist())
    groups = {
        str(symbol): part.sort_values("trade_date").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in candidates.itertuples(index=False):
        part = groups[str(event.symbol)]
        signal_positions = np.flatnonzero(
            part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy()
        )
        if len(signal_positions) != 1:
            raise ResearchError(f"signal day missing {event.event_id}")
        signal_pos = int(signal_positions[0])
        lineage = float(event.invalid_step_cum)
        entry_pos = None
        for pos in range(signal_pos + 1, len(part)):
            row = part.iloc[pos]
            if int(row.cal_idx) > int(event.cal_idx) + 3:
                break
            if legal_buy(row, lineage):
                entry_pos = pos
                break
        for profile in PROFILES:
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
            horizon = 10 if profile == "H10_NEXT_OPEN" else 20
            horizon_idx = int(entry.cal_idx) + horizon
            decision_pos = None
            target_choice: tuple[int, float] | None = None
            if profile == "T10_H20_NO_STOP":
                target = entry_price * 1.10
                for pos in range(entry_pos + 1, len(part)):
                    row = part.iloc[pos]
                    state_valid = legal_state(row, lineage)
                    if state_valid and float(row.coord_high) >= target:
                        target_choice = (pos, target)
                        break
                    if int(row.cal_idx) >= horizon_idx and state_valid:
                        decision_pos = pos
                        break
            else:
                for pos in range(entry_pos + 1, len(part)):
                    row = part.iloc[pos]
                    if int(row.cal_idx) >= horizon_idx and legal_state(row, lineage):
                        decision_pos = pos
                        break
            if target_choice is not None:
                exit_pos, exit_price = target_choice
                exit_reason = "TARGET_10"
                exit_decision_idx = int(entry.cal_idx)
            else:
                if decision_pos is None:
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
                decision_idx = int(part.iloc[decision_pos].cal_idx)
                exit_pos = None
                for pos in range(decision_pos + 1, len(part)):
                    row = part.iloc[pos]
                    if legal_sell_open(row, lineage):
                        exit_pos = pos
                        break
                if exit_pos is None:
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
                exit_price = float(part.coord_open.iloc[exit_pos])
                exit_reason = f"H{horizon}_TIME_STOP"
                exit_decision_idx = decision_idx
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
                    "net_return": gross - ENTRY_COST - EXIT_COST,
                }
            )
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    write_parquet(outcomes, OUTCOMES)
    source = read_parquet_duckdb(SOURCE_OUTCOMES)
    source = source.loc[source.profile.isin(PROFILES)].copy()
    source["signal_date"] = pd.to_datetime(source.signal_date)
    check = outcomes.loc[outcomes.signal_date.le(pd.Timestamp("2021-12-31"))].merge(
        source,
        on=["event_id", "profile"],
        how="outer",
        validate="one_to_one",
        suffixes=("_new", "_source"),
        indicator=True,
    )
    completed = check.loc[check.status_new.eq("COMPLETED") & check.status_source.eq("COMPLETED")]
    audit = {
        "source_identity_mismatch_count": int(check._merge.ne("both").sum()),
        "source_completed_status_mismatch_count": int(
            check.loc[check.status_source.eq("COMPLETED"), "status_new"].ne("COMPLETED").sum()
        ),
        "source_completed_entry_date_mismatch_count": int(
            pd.to_datetime(completed.entry_date_new)
            .ne(pd.to_datetime(completed.entry_date_source))
            .sum()
        ),
        "source_completed_exit_date_mismatch_count": int(
            pd.to_datetime(completed.exit_date_new)
            .ne(pd.to_datetime(completed.exit_date_source))
            .sum()
        ),
        "source_completed_net_return_mismatch_count": int(
            (completed.net_return_new.astype(float) - completed.net_return_source.astype(float))
            .abs()
            .gt(1e-10)
            .sum()
        ),
        "signal_bar_fill_count": int(
            (outcomes.entry_date.notna() & outcomes.entry_date.le(outcomes.signal_date)).sum()
        ),
        "t1_same_day_exit_count": int(
            (
                outcomes.status.eq("COMPLETED") & outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)
            ).sum()
        ),
    }
    return outcomes, audit


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    completed = frame.loc[frame.status.eq("COMPLETED")].copy()
    if completed.empty:
        return {
            "completed_trades": 0,
            "mean_net": None,
            "median_net": None,
            "win_rate": None,
            "severe_loss10": None,
            "mean_holding_sessions": None,
        }
    return {
        "completed_trades": len(completed),
        "mean_net": float(completed.net_return.mean()),
        "median_net": float(completed.net_return.median()),
        "win_rate": float(completed.net_return.gt(0).mean()),
        "severe_loss10": float(completed.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(completed.holding_sessions.mean()),
    }


def candidate_table(outcomes: pd.DataFrame, enriched: pd.DataFrame) -> pd.DataFrame:
    merged = outcomes.merge(
        enriched[
            [
                "event_id",
                "market_regime",
                "industry_median_ret20",
                "industry_positive_ret20_share",
                "stock_minus_industry_ret20",
                "turnover_expansion",
                *[f"pass_{rule}" for rule in RULES],
            ]
        ],
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    rows: list[dict[str, Any]] = []
    for rule in RULES:
        for profile in PROFILES:
            part = merged.loc[
                merged.profile.eq(profile)
                & merged[f"pass_{rule}"]
                & merged.signal_date.dt.year.isin(DISCOVERY_YEARS)
            ].copy()
            metrics = summary(part)
            yearly = {
                str(year): summary(part.loc[part.signal_date.dt.year.eq(year)])
                for year in DISCOVERY_YEARS
            }
            annual_means = [
                item["mean_net"] for item in yearly.values() if item["mean_net"] is not None
            ]
            rows.append(
                {
                    "rule": rule,
                    "profile": profile,
                    **metrics,
                    "positive_years": sum(value > 0 for value in annual_means),
                    "median_annual_mean_net": float(np.median(annual_means))
                    if annual_means
                    else math.nan,
                    "yearly_json": json.dumps(yearly, sort_keys=True),
                }
            )
    return pd.DataFrame(rows)


def select_candidate(table: pd.DataFrame) -> pd.Series:
    eligible = table.loc[
        table.completed_trades.ge(150)
        & table.positive_years.ge(3)
        & table.mean_holding_sessions.le(15)
    ].copy()
    if eligible.empty:
        raise ResearchError("no discovery candidate meets frozen minimum support")
    eligible["conditions"] = eligible.rule.map(
        {
            "BULL_ONLY": 1,
            "BULL_INDUSTRY_POSITIVE": 2,
            "BULL_INDUSTRY_MAJORITY": 3,
            "BULL_INDUSTRY_LEADER": 4,
        }
    )
    eligible["profile_order"] = eligible.profile.map({"H10_NEXT_OPEN": 0, "T10_H20_NO_STOP": 1})
    eligible = eligible.sort_values(
        [
            "median_annual_mean_net",
            "mean_net",
            "completed_trades",
            "conditions",
            "profile_order",
            "rule",
        ],
        ascending=[False, False, False, True, True, True],
        kind="mergesort",
    )
    return eligible.iloc[0]


def replay_portfolio(
    trades: pd.DataFrame, daily: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    completed = trades.loc[trades.status.eq("COMPLETED")].copy()
    completed = completed.sort_values(
        [
            "entry_date",
            "industry_positive_ret20_share",
            "stock_minus_industry_ret20",
            "turnover_expansion",
            "event_id",
        ],
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
    negative_cash = 0
    max_k = 0
    duplicate = 0

    def mark(symbol: str, date: pd.Timestamp, field: str) -> float | None:
        group = daily_groups.get(symbol)
        if group is None or date not in group.index:
            return None
        value = group.loc[date, field]
        if isinstance(value, pd.Series):
            value = value.iloc[-1]
        return None if pd.isna(value) else float(value)

    for date in dates:
        date = pd.Timestamp(date)
        if date < completed.entry_date.min() or date > completed.exit_date.max():
            continue
        for sleeve, state in states.items():
            exits = [
                position
                for position in state["active"].values()
                if pd.Timestamp(position["exit_date"]) == date
            ]
            for position in sorted(exits, key=lambda value: value["symbol"]):
                state["cash"] += position["qty"] * float(position["exit_price"]) * (1 - EXIT_COST)
                del state["active"][position["symbol"]]
            open_value = 0.0
            for symbol, position in state["active"].items():
                price = mark(symbol, date, "coord_open")
                if price is None:
                    price = state["last"].get(symbol, position["entry_price"])
                open_value += position["qty"] * price
            sleeve_nav = state["cash"] + open_value
            candidates = by_date.get(date, pd.DataFrame())
            candidates = (
                candidates.loc[candidates.sleeve.eq(sleeve)] if len(candidates) else candidates
            )
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
                if reason is not None:
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
                price = state["last"].get(symbol, position["entry_price"])
                close_value += position["qty"] * price
            nav_rows.append(
                {
                    "trade_date": date,
                    "sleeve": sleeve,
                    "nav": state["cash"] + close_value,
                    "cash": state["cash"],
                    "active": len(state["active"]),
                }
            )
            negative_cash += int(state["cash"] < -1e-10)
            max_k += int(len(state["active"]) > K_PER_SLEEVE)
    accepted = pd.DataFrame(accepted_rows)
    skipped = pd.DataFrame(skipped_rows)
    nav = pd.DataFrame(nav_rows)
    combined = nav.pivot(index="trade_date", columns="sleeve", values="nav").ffill().sum(axis=1)
    returns = combined.pct_change()
    returns.iloc[0] = combined.iloc[0] - 1.0
    drawdown = combined / combined.cummax().clip(lower=1.0) - 1
    years = max((combined.index.max() - combined.index.min()).days / 365.25, 1 / 252)
    metrics = {
        "total_return": float(combined.iloc[-1] - 1),
        "cagr": float(combined.iloc[-1] ** (1 / years) - 1),
        "max_drawdown": float(drawdown.min()),
        "sharpe": float(returns.mean() / returns.std(ddof=1) * math.sqrt(252))
        if returns.std(ddof=1) > 0
        else 0.0,
        "average_utilization": float((1 - nav.cash / nav.nav).mean()),
        "negative_cash_count": negative_cash,
        "max_k_violation_count": max_k,
        "duplicate_position_skip_count": duplicate,
    }
    combined_frame = combined.rename("combined_nav").reset_index()
    write_parquet(accepted, ACCEPTED)
    write_parquet(skipped, SKIPPED)
    write_parquet(combined_frame, NAV)
    return accepted, skipped, combined_frame, metrics


def annual_summary(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        str(year): summary(frame.loc[frame.signal_date.dt.year.eq(year)])
        for year in ALL_SIGNAL_YEARS
    }


def concentration_metrics(accepted: pd.DataFrame) -> dict[str, Any]:
    frame = accepted.copy()
    frame["pnl"] = frame.entry_outlay * frame.net_return
    by_date = frame.groupby(frame.signal_date.dt.normalize()).pnl.sum().sort_values(ascending=False)
    positive_total = float(by_date.loc[by_date.gt(0)].sum())
    best_dates = by_date.head(5).index
    remaining = frame.loc[~frame.signal_date.dt.normalize().isin(best_dates)]
    return {
        "signal_date_count": int(frame.signal_date.dt.normalize().nunique()),
        "top_five_signal_date_positive_pnl_share": (
            None
            if positive_total <= 0
            else float(by_date.head(5).clip(lower=0).sum() / positive_total)
        ),
        "mean_excluding_best_five_signal_dates": float(remaining.net_return.mean())
        if len(remaining)
        else None,
        "top_signal_date_trade_share": float(
            frame.signal_date.dt.normalize().value_counts(normalize=True).iloc[0]
        ),
    }


def run_stage_b() -> dict[str, Any]:
    verification = verify_stage_a()
    outcomes, reproduction_audit = build_outcomes()
    if any(reproduction_audit.values()):
        raise ResearchError(f"outcome reproduction audit failed {reproduction_audit}")
    enriched = pd.read_parquet(ENRICHED)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        enriched[column] = pd.to_datetime(enriched[column])
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    table = candidate_table(outcomes, enriched)
    selected = select_candidate(table)
    rule = str(selected.rule)
    profile = str(selected.profile)
    merged = outcomes.merge(
        enriched[
            [
                "event_id",
                "market_regime",
                "industry_median_ret20",
                "industry_positive_ret20_share",
                "stock_minus_industry_ret20",
                "turnover_expansion",
                f"pass_{rule}",
            ]
        ],
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    selected_all = merged.loc[merged.profile.eq(profile) & merged[f"pass_{rule}"]].copy()
    daily = load_trade_daily(selected_all.symbol.astype(str).unique().tolist())
    accepted, skipped, _nav, portfolio = replay_portfolio(selected_all, daily)
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in accepted:
            accepted[column] = pd.to_datetime(accepted[column])
    full_trade = summary(accepted.assign(status="COMPLETED"))
    annual = annual_summary(accepted.assign(status="COMPLETED"))
    confirmation = summary(
        accepted.loc[accepted.signal_date.dt.year.isin(CONFIRMATION_YEARS)].assign(
            status="COMPLETED"
        )
    )
    diagnostic = summary(
        accepted.loc[accepted.signal_date.dt.year.isin(DIAGNOSTIC_YEARS)].assign(status="COMPLETED")
    )
    concentration = concentration_metrics(accepted)
    gate = {
        "accepted_trades_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_ge_3pct": full_trade["mean_net"] is not None and full_trade["mean_net"] >= 0.03,
        "mean_holding_le_15": full_trade["mean_holding_sessions"] is not None
        and full_trade["mean_holding_sessions"] <= 15,
        "confirmation_each_year_positive": all(
            annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0
            for year in CONFIRMATION_YEARS
        ),
        "2022_positive": annual["2022"]["mean_net"] is not None and annual["2022"]["mean_net"] > 0,
        "2023_positive": annual["2023"]["mean_net"] is not None and annual["2023"]["mean_net"] > 0,
        "mean_ex_best5_positive": concentration["mean_excluding_best_five_signal_dates"] is not None
        and concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"]
        is not None
        and concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
    }
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "selected_rule": rule,
        "selected_profile": profile,
        "candidate_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "average_accepted_trades_per_year": len(accepted) / 10,
        "full_2014_2023": full_trade,
        "confirmation_2019_2021": confirmation,
        "post_observation_2022_2023": diagnostic,
        "annual": annual,
        "portfolio": portfolio,
        "concentration": concentration,
        "gate": gate,
        "audit": {
            **reproduction_audit,
            "feature_after_decision_count": int(
                enriched.feature_latest_timestamp.gt(enriched.decision_at).sum()
            ),
            "signal_bar_fill_count": int(accepted.entry_date.le(accepted.signal_date).sum()),
            "t1_same_day_exit_count": int(accepted.exit_cal_idx.le(accepted.entry_cal_idx).sum()),
            "post_2023_signal_or_feature_count": int(
                enriched.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
            ),
            "repository_2024_plus_rows_used_for_signal_or_feature": 0,
            "repository_2024_rows_used_only_for_pre_2024_trade_resolution": True,
        },
        "verdict": (
            "BULL_QUIET_INVENTORY_SIMPLE_EDGE"
            if all(gate.values())
            else "BULL_QUIET_INVENTORY_MECHANISM_FAILS_TARGET"
        ),
        "hashes": {
            "outcomes": sha256(OUTCOMES),
            "accepted": sha256(ACCEPTED),
            "skipped": sha256(SKIPPED),
            "nav": sha256(NAV),
        },
    }
    write_json(RESULT, result)
    render_report(result)
    return result


def pct(value: Any) -> str:
    return "-" if value is None else f"{float(value):.2%}"


def render_report(result: dict[str, Any]) -> None:
    full = result["full_2014_2023"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Frozen mechanism",
        "",
        "Trade the frozen quiet-inventory executable information breakout only "
        "when the completed-close broad market state is BULL. The bounded "
        "selector may add only the frozen PIT industry conditions. BEAR and "
        "TRANSITION hold cash. This is not downward-gap repair.",
        "",
        f"Selected rule: `{result['selected_rule']}`. Selected translation: "
        f"`{result['selected_profile']}`.",
        "",
        "## Full capacity-constrained result",
        "",
        "|Trades|Per year|Mean net|Median net|Win|Severe10|Mean hold|Total return|MaxDD|Sharpe|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"|{result['capacity_accepted_completed_trades']}|{result['average_accepted_trades_per_year']:.2f}|{pct(full['mean_net'])}|{pct(full['median_net'])}|{pct(full['win_rate'])}|{pct(full['severe_loss10'])}|{full['mean_holding_sessions']:.2f}|{pct(result['portfolio']['total_return'])}|{pct(result['portfolio']['max_drawdown'])}|{result['portfolio']['sharpe']:.3f}|",
        "",
        "## Annual trade evidence",
        "",
        "|Year|Trades|Mean|Median|Win|Severe10|Mean hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, item in result["annual"].items():
        mean_holding = item["mean_holding_sessions"]
        mean_holding_text = "-" if mean_holding is None else f"{mean_holding:.2f}"
        lines.append(
            f"|{year}|{item['completed_trades']}|{pct(item['mean_net'])}|"
            f"{pct(item['median_net'])}|{pct(item['win_rate'])}|"
            f"{pct(item['severe_loss10'])}|{mean_holding_text}|"
        )
    lines += [
        "",
        "## Causality and concentration",
        "",
        f"Gate: `{json.dumps(result['gate'], sort_keys=True)}`.",
        "",
        f"Concentration: `{json.dumps(result['concentration'], sort_keys=True)}`.",
        "",
        "All market and industry state is known by the completed signal close; "
        "entry is later. 2014-2021 outcomes reproduce the authoritative source "
        "before the same engine is extended to 2022-2023. Post-2023 rows are "
        "used only to close pre-2024 trades.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if not (args.stage_a or args.stage_b):
        parser.error("choose --stage-a or --stage-b")
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    if args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, default=str))


if __name__ == "__main__":
    main()
