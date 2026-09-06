#!/usr/bin/env python3
"""Freeze, replay, and render the pre-2021 bull-industry laggard diffusion mother event."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_first_active_demand_takeover_after_weakness_12m_chart_discovery_v1 as base


EXPERIMENT = "ASHARE-BULL-INDUSTRY-LAGGARD-FIRST-DEMAND-DIFFUSION-12M-CHART-DISCOVERY-V1"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
EXPECTED_FREEZE_SHA256 = "43b2af9315d33040146858c6be8c9601d3fad6f5777ef1199e1e1545d92e4a34"
DATA_ROOT = Path("/Volumes/quant/CY_quant_research")
DAILY = DATA_ROOT / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/pit_daily_compact_2013_2023.parquet"
REGIME = DATA_ROOT / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/causal_market_regime_2014_2023.parquet"
EXPECTED_INPUT_HASHES = {
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
    REGIME: "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}
EXT_ROOT = DATA_ROOT / "ashare_bull_industry_laggard_first_demand_diffusion_12m_chart_discovery_v1/development_2014_2020"
CANDIDATES = EXT_ROOT / "candidates_frozen.parquet"
OUTCOMES = EXT_ROOT / "outcomes.parquet"
WINDOW_PANEL = EXT_ROOT / "chart_window_panel.parquet"
REVIEW_LEDGER = EXT_ROOT / "review_ledger.parquet"
REVIEW_CSV = EXT_ROOT / "review_ledger.csv"
CHART_DIR = EXT_ROOT / "individual_charts"
CHART_INDEX = EXT_ROOT / "chart_index.csv"
SHEET_DIR = EXT_ROOT / "contact_sheets"
OUTCOME_SHEET_ROOT = EXT_ROOT / "review_sheets_by_outcome"
MANIFEST = EXT_ROOT / "manifest.json"


class ResearchError(RuntimeError):
    """Fail closed on input identity, PIT chronology, or event/execution semantics."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    connection.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def verify_inputs() -> dict[str, str]:
    expected = {FREEZE: EXPECTED_FREEZE_SHA256, **EXPECTED_INPUT_HASHES}
    actual: dict[str, str] = {}
    for path, identity in expected.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != identity:
            raise ResearchError(f"input drift: {path}: {value} != {identity}")
    return actual


def build_candidates() -> pd.DataFrame:
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=4")
    result = connection.execute(
        f"""
        WITH descriptors AS (
          SELECT d.*,
            median(turnover_fraction) OVER (
              PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            ) AS prior20_turn,
            CASE WHEN coord_high>coord_low
              THEN (coord_close-coord_low)/(coord_high-coord_low) ELSE NULL END AS close_location
          FROM read_parquet('{DAILY.as_posix()}') d
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2020-12-31'
        ), eligible_industry AS (
          SELECT trade_date,cal_idx,symbol,causal_industry,ret20,
            cume_dist() OVER (
              PARTITION BY trade_date,causal_industry ORDER BY ret20
            ) AS industry_ret20_pct
          FROM descriptors
          WHERE current_valid AND hard_valid AND industry_valid AND historical_identity_valid
            AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL
            AND ret20 IS NOT NULL
        ), industry_state AS (
          SELECT trade_date,causal_industry,count(*) AS industry_n20,
            median(ret20) AS industry_median_ret20,
            avg(CASE WHEN ret20>0 THEN 1.0 ELSE 0.0 END) AS industry_positive_ret20_share
          FROM eligible_industry
          GROUP BY trade_date,causal_industry
        ), joined AS (
          SELECT d.*,
            p.ret20 AS prior_session_ret20,
            p.industry_ret20_pct AS prior_session_industry_ret20_pct,
            p.trade_date AS prior_session_date,
            s.industry_n20,s.industry_median_ret20,s.industry_positive_ret20_share,
            r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
            r.market_median_ret60,r.market_positive_ret60_share,
            r.latest_source_timestamp AS market_latest_source_timestamp,
            CASE WHEN
              d.current_valid AND d.hard_valid AND d.trade_status=1
              AND d.current_day_data_tradable AND d.market_rule_valid
              AND d.corporate_action_valid AND NOT d.corporate_action_blocking
              AND d.industry_valid AND d.historical_identity_valid
              AND d.industry_snapshot_id IS NOT NULL
              AND p.cal_idx=d.cal_idx-1 AND p.causal_industry=d.causal_industry
              AND r.market_regime='BULL'
              AND s.industry_n20>=10 AND s.industry_median_ret20>0
              AND s.industry_positive_ret20_share>=0.55
              AND p.industry_ret20_pct<=0.25
              AND d.step_return>=0.05 AND d.close_location>=0.80
              AND d.prior20_turn>0 AND d.turnover_fraction>=1.5*d.prior20_turn
              AND round(d.close*100)<round(d.up_limit_price*100)
            THEN 1 ELSE 0 END AS raw_event
          FROM descriptors d
          JOIN eligible_industry p ON p.symbol=d.symbol AND p.cal_idx=d.cal_idx-1
          JOIN industry_state s ON s.trade_date=d.trade_date AND s.causal_industry=d.causal_industry
          JOIN read_parquet('{REGIME.as_posix()}') r ON r.trade_date=d.trade_date
        ), first_event AS (
          SELECT *,max(raw_event) OVER (
            PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
          ) AS prior20_same_event
          FROM joined
        )
        SELECT
          'BILFD-' || strftime(trade_date,'%Y%m%d') || '-' || replace(symbol,'.','') AS event_id,
          symbol,sleeve,causal_industry AS industry,trade_date AS signal_date,cal_idx,
          invalid_step_cum,coord_open,coord_high,coord_low,coord_close,
          turnover_fraction,prior20_turn AS turn20,step_return,ret20,ret60,close_location,
          coord_open/prior_coord_close-1 AS open_gap,available_at,decision_at,
          prior_session_date,prior_session_ret20,prior_session_industry_ret20_pct,
          industry_n20,industry_median_ret20,industry_positive_ret20_share,
          market_regime,market_median_ret20,market_positive_ret20_share,
          market_median_ret60,market_positive_ret60_share,
          market_median_ret20-market_median_ret60 AS market_return_acceleration,
          market_positive_ret20_share-market_positive_ret60_share AS market_breadth_acceleration,
          market_latest_source_timestamp
        FROM first_event
        WHERE raw_event=1 AND coalesce(prior20_same_event,0)=0
          AND trade_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY trade_date,sleeve,symbol
        """
    ).fetch_df()
    connection.close()
    for column in (
        "signal_date", "available_at", "decision_at", "prior_session_date",
        "market_latest_source_timestamp",
    ):
        result[column] = pd.to_datetime(result[column])
    if result.empty or result.event_id.duplicated().any():
        raise ResearchError("empty or duplicate candidate identities")
    if result.available_at.gt(result.decision_at).any():
        raise ResearchError("stock input available after decision")
    if result.market_latest_source_timestamp.gt(result.decision_at).any():
        raise ResearchError("market state available after decision")
    if not result.market_regime.eq("BULL").all():
        raise ResearchError("non-BULL candidate escaped frozen router")
    if not result.prior_session_date.lt(result.signal_date).all():
        raise ResearchError("laggard structure is not pre-existing")
    if result.signal_date.max() > pd.Timestamp("2020-12-31"):
        raise ResearchError("post-2020 signal entered development")
    return result


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    complete = frame.loc[frame.status.eq("COMPLETED")].copy()
    values = pd.to_numeric(complete.net_return, errors="coerce")
    dates = frame.groupby("signal_date").size() if not frame.empty else pd.Series(dtype=float)
    return {
        "signals": int(len(frame)),
        "completed": int(len(complete)),
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "mean_net": None if complete.empty else float(values.mean()),
        "median_net": None if complete.empty else float(values.median()),
        "positive_rate": None if complete.empty else float(values.gt(0).mean()),
        "ge_4pct_rate": None if complete.empty else float(values.ge(0.04).mean()),
        "severe10": None if complete.empty else float(values.le(-0.10).mean()),
        "target_hit": None if complete.empty else float(complete.exit_reason.fillna("").str.startswith("TARGET").mean()),
        "mean_holding_sessions": None if complete.empty else float(complete.holding_sessions.mean()),
        "largest_date_share": None if frame.empty else float(dates.max() / len(frame)),
        "top_five_date_share": None if frame.empty else float(dates.nlargest(5).sum() / len(frame)),
    }


def configure_base() -> None:
    base.EXPERIMENT = EXPERIMENT
    base.DAILY = DAILY
    base.EXT_ROOT = EXT_ROOT
    base.CANDIDATES = CANDIDATES
    base.OUTCOMES = OUTCOMES
    base.WINDOW_PANEL = WINDOW_PANEL
    base.REVIEW_LEDGER = REVIEW_LEDGER
    base.REVIEW_CSV = REVIEW_CSV
    base.CHART_DIR = CHART_DIR
    base.CHART_INDEX = CHART_INDEX
    base.SHEET_DIR = SHEET_DIR
    base.OUTCOME_SHEET_ROOT = OUTCOME_SHEET_ROOT
    base.configure_charts()


def run(workers: int, skip_render: bool) -> dict[str, Any]:
    input_hashes = verify_inputs()
    candidates = build_candidates()
    configure_base()
    outcomes = base.replay(candidates)
    write_parquet(candidates, CANDIDATES)
    write_parquet(outcomes, OUTCOMES)
    windows = base.charts.load_windows(candidates)
    ledger = base.build_chart_ledger(candidates, outcomes, windows)
    extras = candidates[[
        "event_id", "industry", "prior_session_ret20", "prior_session_industry_ret20_pct",
        "industry_n20", "industry_median_ret20", "industry_positive_ret20_share",
        "market_regime", "market_median_ret20", "market_positive_ret20_share",
        "market_median_ret60", "market_positive_ret60_share",
        "market_return_acceleration", "market_breadth_acceleration",
    ]]
    ledger = ledger.merge(extras, on="event_id", how="left", validate="one_to_one")
    write_parquet(windows, WINDOW_PANEL)
    write_parquet(ledger, REVIEW_LEDGER)
    ledger.to_csv(REVIEW_CSV, index=False, float_format="%.10g")
    contact_sheets: list[Path] = []
    outcome_sheets: list[Path] = []
    if not skip_render:
        groups = {key: part for key, part in windows.groupby("event_id", sort=False)}
        tasks = []
        for _, event in ledger.iterrows():
            target = CHART_DIR / f"{int(event.chart_number):04d}_{event.symbol.replace('.', '_')}_{pd.Timestamp(event.signal_date):%Y%m%d}.png"
            tasks.append((event.to_dict(), groups[str(event.event_id)], str(target)))
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            chart_index = pd.DataFrame(list(executor.map(base.render_worker, tasks, chunksize=1)))
        chart_index.to_csv(CHART_INDEX, index=False, float_format="%.10g")
        contact_sheets = base.build_nine_up(chart_index, SHEET_DIR, EXPERIMENT)
        for bucket in (
            "SEVERE_LOSS", "LOSS_0_TO_10PCT", "PROFIT_0_TO_4PCT", "PROFIT_GE_4PCT", "NO_COMPLETED_TRADE",
        ):
            subset = chart_index.loc[chart_index.outcome_bucket.eq(bucket)].sort_values(
                ["signal_date", "symbol", "event_id"], kind="mergesort"
            )
            outcome_sheets.extend(base.build_nine_up(subset, OUTCOME_SHEET_ROOT / bucket.lower(), bucket))
    joined = candidates.merge(outcomes, on="event_id", how="left", suffixes=("", "_out"), validate="one_to_one")
    joined["signal_date"] = pd.to_datetime(joined.signal_date)
    pooled = metrics(joined)
    annual = {
        str(year): metrics(joined.loc[joined.signal_date.dt.year.eq(year)])
        for year in range(2014, 2021)
    }
    gate = {
        "completed_gt_50_each_year": all(item["completed"] > 50 for item in annual.values()),
        "pooled_mean_net_gt_4pct": bool(pooled["mean_net"] is not None and pooled["mean_net"] > 0.04),
    }
    payload = {
        "experiment": EXPERIMENT,
        "scientific_status": "PRE_2021_MOTHER_EVENT_CHART_ANATOMY_COMPLETE",
        "input_hashes": input_hashes,
        "runner_sha256": sha256(Path(__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "outcomes_sha256": sha256(OUTCOMES),
        "review_ledger_sha256": sha256(REVIEW_LEDGER),
        "signals": len(candidates),
        "charts": 0 if skip_render else len(candidates),
        "contact_sheets": len(contact_sheets),
        "outcome_sheets": len(outcome_sheets),
        "pooled": pooled,
        "annual": annual,
        "gate": gate,
        "passes_gate": all(gate.values()),
        "max_signal_date": str(candidates.signal_date.max().date()),
        "max_exit_date": str(pd.to_datetime(joined.exit_date).max().date()),
        "max_chart_bar_date": str(pd.to_datetime(windows.trade_date).max().date()),
        "post_2020_signal_or_rule_read": "NO",
        "2022_2024_read": "NO",
        "future_market_function": False,
        "later_period_status": "AUTHORIZED" if all(gate.values()) else "CLOSED_UNLESS_CHART_RULES_EARN_NEW_FREEZE",
    }
    write_json(MANIFEST, payload)
    payload["manifest_sha256"] = sha256(MANIFEST)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.workers, args.skip_render), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
