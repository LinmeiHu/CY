#!/usr/bin/env python3
"""Causal local-bull low-inventory demand-expansion strategy."""

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
EXPERIMENT = "ASHARE-BULL-LOW-INVENTORY-DEMAND-EXPANSION-V61"
EXT = Path("/Volumes/quant/CY_quant_research/bull_low_inventory_demand_expansion_v61")
FEATURE_PANEL = Path(
    "/Volumes/quant/CY_quant_research/bull_industry_pullback_reacceleration_v44/"
    "stage_a/causal_feature_panel.parquet"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
FORWARD_FREEZE = OS / f"artifacts/{EXPERIMENT}_forward_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_DIR = EXT / "stage_a/blind_charts"
DEV_OUTCOMES = EXT / "stage_b/development_outcomes.parquet"
FORWARD_OUTCOMES = EXT / "stage_b/forward_outcomes.parquet"
DEV_ACCEPTED = EXT / "stage_b/development_accepted.parquet"
DEV_SKIPPED = EXT / "stage_b/development_skipped.parquet"
DEV_NAV = EXT / "stage_b/development_nav.parquet"
ACCEPTED = EXT / "stage_b/combined_accepted.parquet"
SKIPPED = EXT / "stage_b/combined_skipped.parquet"
NAV = EXT / "stage_b/combined_nav.parquet"
PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))
DEVELOPMENT_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)


class ResearchError(RuntimeError):
    """Fail closed on V61 chronology, identity, or execution drift."""


def sha(path: Path) -> str:
    return v1.sha256(path)


def write_spec() -> dict[str, str]:
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_CONTRACT",
            "contract_sha256": sha(CONTRACT),
            "runner_sha256": sha(Path(__file__)),
            "feature_panel_sha256": sha(FEATURE_PANEL),
            "daily_sha256": sha(v1.DAILY),
            "daily_tail_sha256": sha(v1.DAILY_TAIL),
            "execution_engine_sha256": sha(Path(v2.__file__)),
            "portfolio_engine_sha256": sha(Path(v1.__file__)),
        },
    )
    return {"contract_sha256": sha(CONTRACT), "spec_sha256": sha(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    query = f"""
    WITH base AS (
      SELECT f.*,
        avg((step_return>0)::INT) OVER w20 AS prior20_positive_share,
        max(abs(step_return)) OVER w20 AS prior20_max_abs_return,
        sum(CASE WHEN step_return<0 THEN turnover_fraction ELSE 0 END) OVER w20 /
          nullif(sum(CASE WHEN step_return>0 THEN turnover_fraction ELSE 0 END) OVER w20,0)
          AS downside_upside_turnover_ratio,
        median(turnover_fraction) OVER w20 AS prior20_turnover_median
      FROM read_parquet('{FEATURE_PANEL}') f
      WINDOW w20 AS (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      )
    ), raw0 AS (
      SELECT *,turnover_fraction/nullif(prior20_turnover_median,0) AS turnover_expansion,
        CASE WHEN current_valid AND hard_valid AND history_valid AND industry_valid
          AND historical_identity_valid AND industry_snapshot_id IS NOT NULL
          AND trade_status=1 AND current_day_data_tradable AND market_rule_valid
          AND corporate_action_valid AND NOT corporate_action_blocking
          AND industry_n>=10 AND industry20>0 AND industry60>0
          AND industry_breadth20>0.50 AND industry_breadth60>0.50
          AND prior20_return BETWEEN 0.05 AND 0.25
          AND prior20_positive_share>=0.60 AND prior20_max_abs_return<0.07
          AND downside_upside_turnover_ratio<=0.65
          AND step_return BETWEEN 0.02 AND 0.07 AND close_location>=0.75
          AND coord_close>prior20_high
          AND turnover_fraction/nullif(prior20_turnover_median,0) BETWEEN 1.20 AND 2.50
          AND round(close*100)<round(up_limit_price*100)
        THEN 1 ELSE 0 END AS raw_event
      FROM base
    ), raw AS (
      SELECT *,max(raw_event) OVER (
        PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
      ) AS prior20_same_event
      FROM raw0
    ), mother AS (
      SELECT * FROM raw
      WHERE raw_event=1 AND coalesce(prior20_same_event,0)=0
        AND trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
    ), market_state AS (
      SELECT cal_idx,any_value(market_breadth20) AS breadth20,
        any_value(market_n) AS n,any_value(market_state_latest_source) AS latest_source
      FROM raw0 GROUP BY cal_idx
    ), industry_state AS (
      SELECT cal_idx,causal_industry,any_value(industry_breadth20) AS breadth20,
        any_value(industry_n) AS n,any_value(industry_state_latest_source) AS latest_source
      FROM raw0 WHERE causal_industry IS NOT NULL GROUP BY cal_idx,causal_industry
    ), demand AS (
      SELECT m.*,ml.breadth20 AS market_breadth20_lag10,
        il.breadth20 AS industry_breadth20_lag10,
        ml.n AS market_n_lag10,il.n AS industry_n_lag10,
        ml.latest_source AS market_lag_latest_source,
        il.latest_source AS industry_lag_latest_source
      FROM mother m
      LEFT JOIN market_state ml ON ml.cal_idx=m.cal_idx-10
      LEFT JOIN industry_state il
        ON il.cal_idx=m.cal_idx-10 AND il.causal_industry=m.causal_industry
      WHERE m.market_breadth20>=0.70 AND m.industry_breadth20>=0.70
        AND m.market_breadth20-ml.breadth20>=0.10
        AND m.industry_breadth20-il.breadth20>=0.10
        AND m.market_n>=200 AND ml.n>=200 AND m.industry_n>=10 AND il.n>=10
    ), inventory AS (
      SELECT d.trade_date,d.symbol,d.cal_idx,
        count(h.cal_idx) AS prior126_rows,
        count(h.cal_idx) FILTER (
          WHERE h.coord_high>=d.coord_close AND h.coord_low<=d.coord_close*1.15
        ) AS target_corridor_touch_sessions,
        max(h.available_at) AS inventory_latest_source
      FROM demand d
      JOIN raw0 h ON h.symbol=d.symbol
        AND h.cal_idx BETWEEN d.cal_idx-126 AND d.cal_idx-1
        AND h.invalid_step_cum=d.invalid_step_cum
        AND h.current_valid AND h.hard_valid AND h.history_valid
        AND h.corporate_action_valid AND NOT h.corporate_action_blocking
        AND h.available_at<=d.decision_at
      GROUP BY d.trade_date,d.symbol,d.cal_idx
    )
    SELECT
      'BLIDE61-'||strftime(d.trade_date,'%Y%m%d')||'-'||replace(d.symbol,'.','') AS event_id,
      d.symbol,d.sleeve,d.causal_industry,d.trade_date AS signal_date,d.cal_idx,
      d.invalid_step_cum,d.coord_close AS signal_coord_close,d.available_at,d.decision_at,
      greatest(d.available_at,d.market_state_latest_source,d.industry_state_latest_source,
        d.market_lag_latest_source,d.industry_lag_latest_source,i.inventory_latest_source)
        AS feature_latest_timestamp,
      d.market_state_latest_source AS market_latest_source,
      d.industry_state_latest_source AS industry_latest_source,
      d.prior20_return,d.prior20_positive_share,d.prior20_max_abs_return,
      d.downside_upside_turnover_ratio,d.step_return,d.close_location,d.prior20_high,
      d.turnover_expansion,d.market20,d.market60,d.market_breadth20,d.market_breadth60,
      d.industry20,d.industry60,d.industry_breadth20,d.industry_breadth60,d.industry_n,
      d.market_breadth20_lag10,d.industry_breadth20_lag10,
      d.market_breadth20-d.market_breadth20_lag10 AS market_breadth_expansion10,
      d.industry_breadth20-d.industry_breadth20_lag10 AS industry_breadth_expansion10,
      i.prior126_rows,i.target_corridor_touch_sessions,i.inventory_latest_source,
      d.ret20-d.industry20 AS stock_minus_industry_ret20,
      'LOW_INVENTORY_AND_RENEWED_DEMAND' AS admission_lane
    FROM demand d JOIN inventory i USING(trade_date,symbol,cal_idx)
    WHERE i.prior126_rows=126 AND i.target_corridor_touch_sessions<=10
    ORDER BY signal_date,sleeve,symbol,event_id
    """
    frame = con.execute(query).fetchdf()
    con.close()
    for column in (
        "signal_date", "available_at", "decision_at", "feature_latest_timestamp",
        "market_latest_source", "industry_latest_source", "inventory_latest_source",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.event_id.duplicated().any():
        raise ResearchError("empty or duplicate V61 candidate identity")
    if frame.feature_latest_timestamp.gt(frame.decision_at).any():
        raise ResearchError("feature after decision")
    v1.write_parquet(frame, CANDIDATES)
    return frame


def blind_sample(frame: pd.DataFrame, count: int = 30) -> pd.DataFrame:
    work = frame.copy()
    work["year"] = work.signal_date.dt.year
    work["blind_key"] = work.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    pieces = []
    for year in YEARS:
        part = work.loc[work.year.eq(year)].sort_values("blind_key", kind="mergesort")
        if not part.empty:
            pieces.append(part.groupby("sleeve", sort=True, group_keys=False).head(2).head(3))
    picked = pd.concat(pieces, ignore_index=True)
    if len(picked) < count:
        rest = work.loc[~work.event_id.isin(picked.event_id)].sort_values("blind_key")
        picked = pd.concat([picked, rest.head(count-len(picked))], ignore_index=True)
    picked = picked.sort_values(["signal_date", "symbol"]).head(count).copy()
    picked.insert(0, "chart_id", [f"V61-BLIND-{i:03d}" for i in range(1, len(picked)+1)])
    BLIND_INDEX.parent.mkdir(parents=True, exist_ok=True)
    picked.to_csv(BLIND_INDEX, index=False)
    return picked


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_DIR.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.astype(str).unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    stock = con.execute(
        f"""SELECT f.trade_date,f.symbol,f.coord_open,f.coord_high,f.coord_low,f.coord_close,
          f.turnover_fraction,f.ret20,f.ret60 FROM read_parquet('{FEATURE_PANEL}') f
          JOIN symbols USING(symbol) ORDER BY symbol,trade_date"""
    ).fetchdf()
    con.close()
    stock.trade_date = pd.to_datetime(stock.trade_date)
    groups = {str(s): p.reset_index(drop=True) for s, p in stock.groupby("symbol", sort=False)}
    for event in sample.itertuples(index=False):
        part = groups[str(event.symbol)]
        positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
        if len(positions) != 1:
            raise ResearchError(f"missing chart clock {event.event_id}")
        end = int(positions[0])
        view = part.iloc[max(0, end-159):end+1]
        fig, axes = v1.plt.subplots(3, 1, figsize=(10, 7.2), gridspec_kw={"height_ratios": [3, 0.8, 1]})
        x = v1.mdates.date2num(view.trade_date)
        colors = np.where(view.coord_close.ge(view.coord_open), "#dc2626", "#059669")
        axes[0].vlines(x, view.coord_low, view.coord_high, color=colors, linewidth=0.65)
        axes[0].bar(
            x, np.maximum(abs(view.coord_close-view.coord_open), view.coord_close.abs()*0.0005),
            bottom=np.minimum(view.coord_open, view.coord_close), width=0.65,
            color=colors, edgecolor=colors,
        )
        axes[0].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--")
        axes[0].axhspan(float(event.signal_coord_close), float(event.signal_coord_close)*1.15,
            color="#f59e0b", alpha=0.10, label="Low-occupancy +15% corridor")
        axes[0].set_title(
            f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",
            fontproperties=v1.CJK_FONT,
        )
        axes[0].legend(loc="upper left", fontsize=8); axes[0].grid(alpha=0.2)
        axes[1].bar(view.trade_date, view.turnover_fraction, color=colors, width=0.75)
        axes[1].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--")
        axes[1].grid(alpha=0.2)
        axes[2].plot(view.trade_date, view.ret20, label="Stock ret20", color="#b45309")
        axes[2].plot(view.trade_date, view.ret60, label="Stock ret60", color="#7c3aed")
        axes[2].axhline(0, color="black", linewidth=0.7); axes[2].legend(fontsize=8)
        axes[2].grid(alpha=0.2); axes[2].xaxis.set_major_formatter(v1.mdates.DateFormatter("%Y-%m"))
        fig.text(
            0.01, 0.01,
            "Outcome-blind; no post-signal bar. "
            f"corridor touches={event.target_corridor_touch_sessions}; "
            f"market breadth +{event.market_breadth_expansion10:.1%}; "
            f"industry breadth +{event.industry_breadth_expansion10:.1%}.",
            fontsize=8,
        )
        fig.tight_layout(rect=[0, 0.035, 1, 1])
        fig.savefig(BLIND_DIR / f"{event.chart_id}.png", dpi=140)
        v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes = write_spec()
    frame = build_candidates()
    sample = blind_sample(frame)
    render_blind_charts(sample)
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
        "outcomes_opened": False,
    }
    if any(value for key, value in audit.items() if key != "outcomes_opened"):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT, **hashes,
        "runner_sha256": sha(Path(__file__)), "feature_panel_sha256": sha(FEATURE_PANEL),
        "candidate_sha256": sha(CANDIDATES), "blind_index_sha256": sha(BLIND_INDEX),
        "candidate_count": int(len(frame)), "blind_chart_count": int(len(sample)),
        "annual_candidate_counts": frame.groupby(frame.signal_date.dt.year).size()
            .reindex(YEARS, fill_value=0).astype(int).to_dict(),
        "unique_signal_dates": int(frame.signal_date.nunique()),
        "unique_symbols": int(frame.symbol.nunique()), "audit": audit,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": sha(CONTRACT), "spec_sha256": sha(SPEC),
        "runner_sha256": sha(Path(__file__)), "feature_panel_sha256": sha(FEATURE_PANEL),
        "candidate_sha256": sha(CANDIDATES), "blind_index_sha256": sha(BLIND_INDEX),
    }
    drift = {k: [freeze.get(k), v] for k, v in expected.items() if freeze.get(k) != v}
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")
    return freeze


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None,
                "win_rate": None, "target_hit_rate": None, "severe_loss10": None,
                "mean_holding_sessions": None}
    return {
        "completed_trades": int(len(frame)), "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "target_hit_rate": float(frame.exit_reason.eq("TARGET_15").mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
    }


def build_fixed_outcomes(frame: pd.DataFrame, output: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES = {PROFILE: {"horizon": 15, "target": 0.15}}
        v2.OUTCOMES = output
        return v2.build_outcomes(frame)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes


def replay(trades: pd.DataFrame, accepted_path: Path, skipped_path: Path, nav_path: Path):
    trades = trades.copy()
    trades["industry_positive_ret20_share"] = trades["industry_breadth20"]
    daily = v1.load_trade_daily(trades.loc[trades.status.eq("COMPLETED"), "symbol"].astype(str).unique().tolist())
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = accepted_path, skipped_path, nav_path
        return v1.replay_portfolio(trades, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    feature_columns = [
        "event_id", "industry_breadth20", "stock_minus_industry_ret20", "turnover_expansion"
    ]
    dev_candidates = candidates.loc[candidates.signal_date.dt.year.isin(DEVELOPMENT_YEARS)].copy()
    dev_outcomes, dev_audit = build_fixed_outcomes(dev_candidates, DEV_OUTCOMES)
    dev_trades = dev_outcomes.merge(
        dev_candidates[feature_columns], on="event_id", how="left", validate="many_to_one"
    )
    dev_accepted, dev_skipped, _dev_nav, dev_portfolio = replay(
        dev_trades, DEV_ACCEPTED, DEV_SKIPPED, DEV_NAV
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        dev_accepted[column] = pd.to_datetime(dev_accepted[column])
    dev_full = summary(dev_accepted)
    dev_annual = {
        str(year): summary(dev_accepted.loc[dev_accepted.signal_date.dt.year.eq(year)])
        for year in DEVELOPMENT_YEARS
    }
    dev_concentration = v1.concentration_metrics(dev_accepted)
    dev_gate = {
        "accepted_completed_at_least_300": len(dev_accepted) >= 300,
        "mean_net_gt_3pct": dev_full["mean_net"] is not None and dev_full["mean_net"] > 0.03,
        "mean_holding_lt_15": dev_full["mean_holding_sessions"] is not None and dev_full["mean_holding_sessions"] < 15,
        "at_least_4_positive_years": sum(
            item["mean_net"] is not None and item["mean_net"] > 0 for item in dev_annual.values()
        ) >= 4,
        "mean_excluding_best5_dates_positive": dev_concentration["mean_excluding_best_five_signal_dates"] > 0,
    }
    if not all(dev_gate.values()):
        result = {
            "experiment": EXPERIMENT, "verdict": "BULL_LOW_INVENTORY_DEMAND_EXPANSION_DEVELOPMENT_FAILED",
            "stage_a": stage_a, "development": dev_full, "development_annual": dev_annual,
            "development_portfolio": dev_portfolio, "development_concentration": dev_concentration,
            "development_gate": dev_gate, "development_capacity_skips": int(len(dev_skipped)),
            "audit": dev_audit, "forward_years_opened": False,
        }
        v1.write_json(RESULT, result)
        return result
    v1.write_json(
        FORWARD_FREEZE,
        {
            "experiment": EXPERIMENT, "profile": PROFILE,
            "development_outcomes_sha256": sha(DEV_OUTCOMES),
            "development_accepted_sha256": sha(DEV_ACCEPTED),
            "candidate_sha256": sha(CANDIDATES), "contract_sha256": sha(CONTRACT),
            "development_gate": dev_gate, "forward_outcomes_opened": False,
        },
    )
    forward_candidates = candidates.loc[candidates.signal_date.dt.year.isin(FORWARD_YEARS)].copy()
    forward_outcomes, forward_audit = build_fixed_outcomes(forward_candidates, FORWARD_OUTCOMES)
    all_outcomes = pd.concat([dev_outcomes, forward_outcomes], ignore_index=True)
    all_trades = all_outcomes.merge(
        candidates[feature_columns], on="event_id", how="left", validate="many_to_one"
    )
    accepted, skipped, _nav, portfolio = replay(all_trades, ACCEPTED, SKIPPED, NAV)
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    full = summary(accepted)
    annual = {str(year): summary(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in YEARS}
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "capacity_accepted_completed_gt_500": len(accepted) > 500,
        "mean_net_gt_3pct": full["mean_net"] is not None and full["mean_net"] > 0.03,
        "mean_holding_lt_15": full["mean_holding_sessions"] is not None and full["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(
            annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0
            for year in FORWARD_YEARS
        ),
        "mean_excluding_best5_dates_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_date_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
    }
    audit = {
        **dev_audit, **{f"forward_{k}": v for k, v in forward_audit.items()},
        "feature_after_decision_count": int(candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()),
        "post_2023_signal_or_feature_count": int(candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    verdict = "BULL_LOW_INVENTORY_DEMAND_EXPANSION_TARGET_MET" if all(gate.values()) else "BULL_LOW_INVENTORY_DEMAND_EXPANSION_TARGET_FAILED"
    result = {
        "experiment": EXPERIMENT, "verdict": verdict, "profile": PROFILE,
        "candidate_count": int(len(candidates)), "capacity_accepted_completed_trades": int(len(accepted)),
        "capacity_skips": int(len(skipped)), "average_trades_per_year": float(len(accepted)/10),
        "full": full, "annual": annual, "portfolio": portfolio, "concentration": concentration,
        "development": dev_full, "development_annual": dev_annual, "development_gate": dev_gate,
        "gate": gate, "audit": audit,
        "hashes": {"forward_freeze": sha(FORWARD_FREEZE), "accepted": sha(ACCEPTED), "nav": sha(NAV)},
    }
    v1.write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {EXPERIMENT}", "", f"`{verdict}`", "", "|Year|Trades|Mean net|Median net|Win|Severe10|Mean hold|", "|---:|---:|---:|---:|---:|---:|---:|"]
    for year in YEARS:
        item = annual[str(year)]
        lines.append(
            f"|{year}|{item['completed_trades']}|{v1.pct(item['mean_net'])}|{v1.pct(item['median_net'])}|"
            f"{v1.pct(item['win_rate'])}|{v1.pct(item['severe_loss10'])}|"
            f"{item['mean_holding_sessions'] if item['mean_holding_sessions'] is not None else '—'}|"
        )
    lines += ["", f"Gate: `{json.dumps(gate, sort_keys=True)}`.", ""]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
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
