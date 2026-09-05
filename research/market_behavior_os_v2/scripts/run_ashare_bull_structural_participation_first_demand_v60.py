#!/usr/bin/env python3
"""Structural two-horizon bull participation and first-demand strategy."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-STRUCTURAL-PARTICIPATION-FIRST-DEMAND-V60"
EXT = Path("/Volumes/quant/CY_quant_research/bull_structural_participation_first_demand_v60")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
INDUSTRY_STATE = EXT / "stage_a/industry_state.parquet"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"
PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail closed on V60 chronology, identity, or execution drift."""


def _sha(path: Path) -> str:
    return v1.sha256(path)


def _write_spec() -> dict[str, str]:
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_CONTRACT",
            "contract_sha256": _sha(CONTRACT),
            "runner_sha256": _sha(Path(__file__)),
            "daily_sha256": _sha(v1.DAILY),
            "daily_tail_sha256": _sha(v1.DAILY_TAIL),
            "execution_engine_sha256": _sha(Path(v2.__file__)),
            "portfolio_engine_sha256": _sha(Path(v1.__file__)),
        },
    )
    return {"contract_sha256": _sha(CONTRACT), "spec_sha256": _sha(SPEC)}


def build_candidates() -> tuple[pd.DataFrame, pd.DataFrame]:
    INDUSTRY_STATE.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    daily = str(v1.DAILY)
    query = f"""
    WITH descriptors AS (
      SELECT d.*,
        median(turnover_fraction) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_turn,
        CASE WHEN coord_high>coord_low THEN (coord_close-coord_low)/(coord_high-coord_low) END AS close_location
      FROM read_parquet('{daily}') d
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
    ), eligible_industry AS (
      SELECT trade_date,cal_idx,symbol,causal_industry,ret20,ret60,decision_at,
        cume_dist() OVER (PARTITION BY trade_date,causal_industry ORDER BY ret20) AS industry_ret20_pct
      FROM descriptors
      WHERE current_valid AND hard_valid AND history_valid AND industry_valid
        AND historical_identity_valid AND causal_industry IS NOT NULL
        AND industry_snapshot_id IS NOT NULL AND ret20 IS NOT NULL AND ret60 IS NOT NULL
    ), industry_state AS (
      SELECT trade_date,causal_industry,count(*) AS industry_n,
        median(ret20) AS industry_median_ret20,
        avg((ret20>0)::INT) AS industry_positive_ret20_share,
        median(ret60) AS industry_median_ret60,
        avg((ret60>0)::INT) AS industry_positive_ret60_share,
        max(decision_at) AS industry_latest_source
      FROM eligible_industry GROUP BY trade_date,causal_industry
    ), joined AS (
      SELECT d.*,p.trade_date AS prior_session_date,p.industry_ret20_pct,
        s.industry_n,s.industry_median_ret20,s.industry_positive_ret20_share,
        s.industry_median_ret60,s.industry_positive_ret60_share,s.industry_latest_source,
        r.market_median_ret20,r.market_positive_ret20_share,
        r.market_median_ret60,r.market_positive_ret60_share,
        r.latest_source_timestamp AS market_latest_source,
        CASE WHEN d.current_valid AND d.hard_valid AND d.history_valid
          AND d.trade_status=1 AND d.current_day_data_tradable AND d.market_rule_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND d.industry_valid AND d.historical_identity_valid
          AND d.industry_snapshot_id IS NOT NULL
          AND p.cal_idx=d.cal_idx-1 AND p.causal_industry=d.causal_industry
          AND r.market_median_ret20>0 AND r.market_positive_ret20_share>0.50
          AND r.market_median_ret60>0 AND r.market_positive_ret60_share>0.50
          AND s.industry_n>=10 AND s.industry_median_ret20>0
          AND s.industry_positive_ret20_share>=0.55
          AND s.industry_median_ret60>0 AND s.industry_positive_ret60_share>=0.50
          AND p.industry_ret20_pct<=0.50
          AND d.step_return>=0.05 AND d.close_location>=0.80
          AND d.prior20_turn>0 AND d.turnover_fraction>=1.5*d.prior20_turn
          AND round(d.close*100)<round(d.up_limit_price*100)
        THEN 1 ELSE 0 END AS raw_event
      FROM descriptors d
      JOIN eligible_industry p ON p.symbol=d.symbol AND p.cal_idx=d.cal_idx-1
      JOIN industry_state s USING(trade_date,causal_industry)
      JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
    ), first_event AS (
      SELECT *,max(raw_event) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS prior20_same_event
      FROM joined
    ), mother AS (
      SELECT *,count(*) OVER (PARTITION BY trade_date) AS same_date_mother_count
      FROM first_event
      WHERE raw_event=1 AND coalesce(prior20_same_event,0)=0
        AND trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
    ), accepted_clock AS (
      SELECT m.*,
        d1.trade_date AS acceptance_date_1,d1.coord_close AS acceptance_close_1,
        d1.invalid_step_cum AS acceptance_invalid_cum,d1.trade_status AS acceptance_status,
        d1.current_day_data_tradable AS acceptance_tradable,d1.market_rule_valid AS acceptance_rule,
        d1.corporate_action_valid AS acceptance_ca_valid,d1.corporate_action_blocking AS acceptance_ca_blocking,
        d1.current_valid AS acceptance_current,d1.hard_valid AS acceptance_hard,
        d2.trade_date AS confirmation_date,d2.cal_idx AS confirmation_cal_idx,
        d2.coord_close AS confirmation_close,d2.invalid_step_cum AS confirmation_invalid_cum,
        d2.trade_status AS confirmation_status,d2.current_day_data_tradable AS confirmation_tradable,
        d2.market_rule_valid AS confirmation_rule,d2.corporate_action_valid AS confirmation_ca_valid,
        d2.corporate_action_blocking AS confirmation_ca_blocking,
        d2.current_valid AS confirmation_current,d2.hard_valid AS confirmation_hard,
        d2.available_at AS confirmation_available_at,d2.decision_at AS confirmation_decision_at,
        r2.market_median_ret20 AS confirmation_market_median_ret20,
        r2.market_positive_ret20_share AS confirmation_market_positive_ret20_share,
        r2.market_median_ret60 AS confirmation_market_median_ret60,
        r2.market_positive_ret60_share AS confirmation_market_positive_ret60_share,
        r2.latest_source_timestamp AS confirmation_market_latest_source,
        s2.industry_n AS confirmation_industry_n,
        s2.industry_median_ret20 AS confirmation_industry_median_ret20,
        s2.industry_positive_ret20_share AS confirmation_industry_positive_ret20_share,
        s2.industry_median_ret60 AS confirmation_industry_median_ret60,
        s2.industry_positive_ret60_share AS confirmation_industry_positive_ret60_share,
        s2.industry_latest_source AS confirmation_industry_latest_source
      FROM mother m
      JOIN descriptors d1 ON d1.symbol=m.symbol AND d1.cal_idx=m.cal_idx+1
      JOIN descriptors d2 ON d2.symbol=m.symbol AND d2.cal_idx=m.cal_idx+2
      JOIN read_parquet('{v1.SOURCE_REGIME}') r2 ON r2.trade_date=d2.trade_date
      JOIN industry_state s2 ON s2.trade_date=d2.trade_date AND s2.causal_industry=m.causal_industry
    ), flags AS (
      SELECT *,
        acceptance_status=1 AND acceptance_tradable AND acceptance_rule
          AND acceptance_ca_valid AND NOT acceptance_ca_blocking
          AND acceptance_current AND acceptance_hard
          AND confirmation_status=1 AND confirmation_tradable AND confirmation_rule
          AND confirmation_ca_valid AND NOT confirmation_ca_blocking
          AND confirmation_current AND confirmation_hard AS confirmation_data_valid,
        acceptance_invalid_cum=invalid_step_cum
          AND confirmation_invalid_cum=invalid_step_cum AS coordinate_lineage_valid,
        acceptance_close_1>=coord_close AND confirmation_close>=coord_close AS price_acceptance,
        confirmation_market_median_ret20>0 AND confirmation_market_positive_ret20_share>0.50
          AND confirmation_market_median_ret60>0 AND confirmation_market_positive_ret60_share>0.50
          AS confirmation_market_structural_bull,
        confirmation_industry_n>=10 AND confirmation_industry_median_ret20>0
          AND confirmation_industry_positive_ret20_share>=0.55
          AND confirmation_industry_median_ret60>0
          AND confirmation_industry_positive_ret60_share>=0.50
          AS confirmation_industry_structural_bull
      FROM accepted_clock
    )
    SELECT
      'BSPFD-' || strftime(confirmation_date,'%Y%m%d') || '-' || replace(symbol,'.','') AS event_id,
      symbol,sleeve,causal_industry,trade_date AS mother_signal_date,cal_idx AS mother_cal_idx,
      confirmation_date AS signal_date,confirmation_cal_idx AS cal_idx,
      confirmation_invalid_cum AS invalid_step_cum,confirmation_close AS signal_coord_close,
      confirmation_available_at AS available_at,confirmation_decision_at AS decision_at,
      greatest(confirmation_decision_at,confirmation_market_latest_source,
        confirmation_industry_latest_source) AS feature_latest_timestamp,
      prior_session_date,industry_ret20_pct,
      CASE WHEN industry_ret20_pct<=0.25 THEN 'BOTTOM_QUARTILE' ELSE 'SECOND_QUARTILE' END AS relative_lane,
      industry_n,industry_median_ret20,industry_positive_ret20_share,
      industry_median_ret60,industry_positive_ret60_share,
      market_median_ret20,market_positive_ret20_share,market_median_ret60,market_positive_ret60_share,
      same_date_mother_count,coord_close AS mother_close,step_return,close_location,
      turnover_fraction/prior20_turn AS turnover_expansion,
      acceptance_date_1,acceptance_close_1,confirmation_close,
      confirmation_market_median_ret20,confirmation_market_positive_ret20_share,
      confirmation_market_median_ret60,confirmation_market_positive_ret60_share,
      confirmation_industry_n,confirmation_industry_median_ret20,
      confirmation_industry_positive_ret20_share,confirmation_industry_median_ret60,
      confirmation_industry_positive_ret60_share,
      confirmation_market_latest_source,confirmation_industry_latest_source,
      confirmation_data_valid,coordinate_lineage_valid,price_acceptance,
      confirmation_market_structural_bull,confirmation_industry_structural_bull,
      ret20-industry_median_ret20 AS stock_minus_industry_ret20
    FROM flags
    WHERE same_date_mother_count>=10 AND confirmation_data_valid
      AND coordinate_lineage_valid AND price_acceptance
      AND confirmation_market_structural_bull AND confirmation_industry_structural_bull
    ORDER BY signal_date,sleeve,symbol,event_id
    """
    frame = con.execute(query).fetchdf()
    industry = con.execute(
        f"""
        SELECT trade_date,causal_industry,count(*) AS industry_n,
          median(ret20) AS industry_median_ret20,
          avg((ret20>0)::INT) AS industry_positive_ret20_share,
          median(ret60) AS industry_median_ret60,
          avg((ret60>0)::INT) AS industry_positive_ret60_share,
          max(decision_at) AS industry_latest_source
        FROM read_parquet('{daily}')
        WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
          AND current_valid AND hard_valid AND history_valid AND industry_valid
          AND historical_identity_valid AND causal_industry IS NOT NULL
          AND industry_snapshot_id IS NOT NULL AND ret20 IS NOT NULL AND ret60 IS NOT NULL
        GROUP BY trade_date,causal_industry
        ORDER BY trade_date,causal_industry
        """
    ).fetchdf()
    con.close()
    for column in (
        "mother_signal_date", "signal_date", "available_at", "decision_at",
        "feature_latest_timestamp", "prior_session_date", "acceptance_date_1",
        "confirmation_market_latest_source", "confirmation_industry_latest_source",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.event_id.duplicated().any():
        raise ResearchError("empty or duplicate V60 candidate identity")
    if not frame.cal_idx.eq(frame.mother_cal_idx + 2).all():
        raise ResearchError("confirmation clock is not mother plus two exchange sessions")
    if frame.feature_latest_timestamp.gt(frame.decision_at).any():
        raise ResearchError("feature arrives after decision")
    if not frame.price_acceptance.all() or not frame.coordinate_lineage_valid.all():
        raise ResearchError("acceptance or coordinate lineage failure")
    v1.write_parquet(industry, INDUSTRY_STATE)
    v1.write_parquet(frame, CANDIDATES)
    return frame, industry


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    work = frame.copy()
    work["year"] = work.signal_date.dt.year
    work["blind_key"] = work.event_id.map(lambda value: hashlib.sha256(str(value).encode()).hexdigest())
    picked = (
        work.sort_values("blind_key", kind="mergesort")
        .groupby(["year", "sleeve", "relative_lane"], sort=True, group_keys=False)
        .head(1)
    )
    if len(picked) < count:
        remainder = work.loc[~work.event_id.isin(picked.event_id)].sort_values("blind_key")
        picked = pd.concat([picked, remainder.head(count - len(picked))], ignore_index=True)
    picked = picked.sort_values(["signal_date", "symbol"]).head(count).copy()
    picked.insert(0, "chart_id", [f"V60-BLIND-{index:03d}" for index in range(1, len(picked) + 1)])
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True)
    picked.to_csv(BLIND_INDEX, index=False)
    return picked


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.astype(str).unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    daily = con.execute(
        f"""SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.turnover_fraction,d.ret20,d.ret60 FROM read_parquet('{v1.DAILY}') d
          JOIN symbols USING(symbol) WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
          ORDER BY d.symbol,d.trade_date"""
    ).fetchdf()
    con.close()
    daily.trade_date = pd.to_datetime(daily.trade_date)
    groups = {str(symbol): part.reset_index(drop=True) for symbol, part in daily.groupby("symbol", sort=False)}
    for event in sample.itertuples(index=False):
        part = groups[str(event.symbol)]
        positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
        if len(positions) != 1:
            raise ResearchError(f"chart signal clock missing {event.event_id}")
        end = int(positions[0])
        stock = part.iloc[max(0, end - 119):end + 1].copy()
        figure, axes = v1.plt.subplots(3, 1, figsize=(10, 7), gridspec_kw={"height_ratios": [3, 0.8, 1]})
        x = v1.mdates.date2num(stock.trade_date)
        colors = np.where(stock.coord_close.ge(stock.coord_open), "#dc2626", "#059669")
        axes[0].vlines(x, stock.coord_low, stock.coord_high, color=colors, linewidth=0.65)
        body_low = np.minimum(stock.coord_open, stock.coord_close)
        body_height = np.maximum(abs(stock.coord_close-stock.coord_open), stock.coord_close.abs()*0.0005)
        axes[0].bar(x, body_height, bottom=body_low, width=0.65, color=colors, edgecolor=colors)
        axes[0].axvline(pd.Timestamp(event.mother_signal_date), color="#f59e0b", linestyle=":", label="First demand")
        axes[0].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--", label="Two-day acceptance")
        axes[0].set_title(f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry} | {event.relative_lane}")
        axes[0].legend(loc="upper left", fontsize=8); axes[0].grid(alpha=0.2)
        axes[1].bar(stock.trade_date, stock.turnover_fraction, color=colors, width=0.75)
        axes[1].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--"); axes[1].grid(alpha=0.2)
        axes[2].plot(stock.trade_date, stock.ret20, label="Stock ret20", color="#b45309")
        axes[2].plot(stock.trade_date, stock.ret60, label="Stock ret60", color="#7c3aed")
        axes[2].axhline(0, color="black", linewidth=0.7); axes[2].legend(fontsize=8); axes[2].grid(alpha=0.2)
        axes[2].xaxis.set_major_formatter(v1.mdates.DateFormatter("%Y-%m"))
        figure.text(0.01, 0.01, f"Outcome-blind; market20 {event.market_median_ret20:+.1%}; market60 {event.market_median_ret60:+.1%}; cluster {event.same_date_mother_count}; no post-signal bar.", fontsize=8)
        figure.tight_layout(rect=[0, 0.035, 1, 1])
        figure.savefig(BLIND_DIR / f"{event.chart_id}.png", dpi=140)
        v1.plt.close(figure)


def run_stage_a() -> dict[str, Any]:
    hashes = _write_spec()
    frame, industry = build_candidates()
    sample = blind_sample(frame)
    render_blind_charts(sample)
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT, **hashes,
        "runner_sha256": _sha(Path(__file__)), "daily_sha256": _sha(v1.DAILY),
        "candidate_sha256": _sha(CANDIDATES), "industry_state_sha256": _sha(INDUSTRY_STATE),
        "blind_index_sha256": _sha(BLIND_INDEX), "candidate_count": int(len(frame)),
        "blind_chart_count": int(len(sample)),
        "annual_candidate_counts": frame.groupby(frame.signal_date.dt.year).size().reindex(YEARS, fill_value=0).astype(int).to_dict(),
        "relative_lane_counts": frame.relative_lane.value_counts().sort_index().astype(int).to_dict(),
        "industry_state_rows": int(len(industry)), "outcomes_opened": False, "audit": audit,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": _sha(CONTRACT), "spec_sha256": _sha(SPEC),
        "runner_sha256": _sha(Path(__file__)), "daily_sha256": _sha(v1.DAILY),
        "candidate_sha256": _sha(CANDIDATES), "industry_state_sha256": _sha(INDUSTRY_STATE),
        "blind_index_sha256": _sha(BLIND_INDEX),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")
    return freeze


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None, "win_rate": None, "target_hit_rate": None, "severe_loss10": None, "mean_holding_sessions": None}
    return {
        "completed_trades": int(len(frame)), "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()), "win_rate": float(frame.net_return.gt(0).mean()),
        "target_hit_rate": float(frame.exit_reason.eq("TARGET_15").mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
    }


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES = {PROFILE: {"horizon": 15, "target": 0.15}}
        v2.OUTCOMES = OUTCOMES
        outcomes, outcome_audit = v2.build_outcomes(candidates)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes
    features = candidates[["event_id", "relative_lane", "industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"]]
    trades = outcomes.loc[outcomes.profile.eq(PROFILE)].merge(features, on="event_id", how="left", validate="one_to_one")
    daily = v1.load_trade_daily(trades.loc[trades.status.eq("COMPLETED"), "symbol"].astype(str).unique().tolist())
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, nav, portfolio = v1.replay_portfolio(trades, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    full = summary(accepted)
    annual = {str(year): summary(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in YEARS}
    lanes = {str(lane): summary(part) for lane, part in accepted.groupby("relative_lane", sort=True)}
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "capacity_accepted_completed_trades_gt_500": len(accepted) > 500,
        "mean_net_gt_3pct": full["mean_net"] is not None and full["mean_net"] > 0.03,
        "mean_holding_lt_15": full["mean_holding_sessions"] is not None and full["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0 for year in (2021, 2022, 2023)),
        "mean_excluding_best_five_dates_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top_five_date_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
    }
    audit = {
        **outcome_audit,
        "candidate_feature_after_decision_count": int(candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()),
        "post_2023_signal_or_feature_count": int(candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    result = {
        "experiment": EXPERIMENT, "contract_sha256": freeze["contract_sha256"],
        "spec_sha256": freeze["spec_sha256"], "candidate_count": int(len(candidates)),
        "capacity_accepted_completed_trades": int(len(accepted)), "capacity_skips": int(len(skipped)),
        "average_trades_per_year": float(len(accepted)/10), "full": full, "annual": annual,
        "relative_lanes": lanes, "portfolio": portfolio, "concentration": concentration,
        "gate": gate, "gate_passed": all(gate.values()), "audit": audit,
        "verdict": "BULL_STRUCTURAL_PARTICIPATION_TARGET_MET" if all(gate.values()) else "BULL_STRUCTURAL_PARTICIPATION_TARGET_FAILED",
        "hashes": {"outcomes": _sha(OUTCOMES), "accepted": _sha(ACCEPTED), "skipped": _sha(SKIPPED), "nav": _sha(NAV)},
    }
    v1.write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, sort_keys=True, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, sort_keys=True, default=str))
    else:
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
