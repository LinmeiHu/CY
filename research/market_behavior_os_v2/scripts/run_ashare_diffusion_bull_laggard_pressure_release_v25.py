#!/usr/bin/env python3
"""Causal industry-diffusion bull laggard pressure-release strategy research."""

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
EXPERIMENT = "ASHARE-DIFFUSION-BULL-LAGGARD-PRESSURE-RELEASE-V25"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_diffusion_bull_laggard_pressure_release_v25")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_60_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"
PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail closed on contract, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    v1.write_json(path, value)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "When a PIT-healthy industry is already rising but one constituent is still in the "
            "bottom quartile of completed 20-session relative performance, a first high-location "
            "active-demand day followed by two completed sessions of price acceptance can mark "
            "leader-to-laggard capital diffusion. The move is tradable only when many such demand "
            "events occur together and either market participation is accelerating or the next "
            "15-percent price corridor contains little historical turnover pressure."
        ),
        "independence_from_v24": (
            "No V24 quiet-platform or upward information-gap identity is used. The stock starts as "
            "an industry laggard and is admitted by demand diffusion plus causal pressure release."
        ),
        "mother_event": {
            "industry": "PIT members>=10, median completed ret20>0, positive-ret20 share>=55%",
            "laggard": "previous completed session industry ret20 percentile<=25%",
            "active_demand": (
                "completed step return>=5%, close location>=80%, turnover>=1.5x prior-20 median, "
                "not locked at the upper limit"
            ),
            "first_event": "no identical active-demand event in the previous 20 sessions",
        },
        "diffusion_bull": {
            "short_cycle": "market median ret20>0 and positive-ret20 share>50%",
            "breadth": "at least 10 mother events on the completed signal session",
            "mature_exhaustion_veto": "not(market median ret60>=20% and median ret20<=10%)",
            "confirmation": (
                "the short-cycle market and PIT industry-health states remain positive at the "
                "second acceptance close"
            ),
            "bear": "market median ret20<=0 and positive-ret20 share<=50%",
            "transition": "all other states; no entry unless the diffusion-bull definition passes",
        },
        "pressure_proxy": {
            "window": "120 completed stock sessions strictly before the second acceptance close",
            "price": "daily coordinate typical price=(high+low+close)/3",
            "local_corridor": "[0.85*decision_close,1.15*decision_close]",
            "overhead_corridor": "(decision_close,1.15*decision_close]",
            "overhead_share": "overhead turnover divided by local-corridor turnover",
            "low_overhead": "overhead_share<=25%; missing/short history fails closed",
        },
        "admission_lanes": {
            "EARLY_BREADTH_ACCELERATION": (
                "market median ret20>=median ret60 and positive-ret20 share>=positive-ret60 share"
            ),
            "LOW_OVERHEAD_ROTATION": (
                "EARLY_BREADTH_ACCELERATION is false and overhead_share<=25%"
            ),
            "combination": "logical OR with mutually exclusive lane labels",
        },
        "price_acceptance": (
            "the next two exchange sessions are valid, tradable, corporate-action safe, on the "
            "same coordinate lineage, and each completed close is at least the mother close"
        ),
        "decision_at": "second acceptance-session close",
        "entry": "first legal next daily open within three market sessions",
        "target": "+15% coordinate standing target from the first T+1-sellable session",
        "time_stop": "completed H15 state followed by the next legal daily open",
        "failure_stop": "none",
        "round_trip_cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "evidence_governance": {
            "2014_2020": "consumed mechanism and chart-rule development",
            "2021_2023": "chronological extension opened only after this contract and blind charts freeze",
            "post_2023_signal_or_feature": False,
            "post_2023_execution_data": "permitted only to resolve pre-2024 positions",
        },
        "required_gate": {
            "capacity_accepted_completed_trades_gt": 500,
            "mean_net_gt": 0.05,
            "mean_holding_sessions_lt": 15,
            "each_2021_2023_mean_positive": True,
            "mean_excluding_best_five_signal_dates_positive": True,
            "top_five_signal_date_positive_pnl_share_le": 0.25,
        },
    }


def persist_contract() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "FROZEN_OUTCOME_BLIND_CAUSAL_CONTRACT",
            "contract_sha256": sha256(CONTRACT),
            "runner_sha256": sha256(Path(__file__)),
            "daily_sha256": sha256(v1.DAILY),
            "regime_sha256": sha256(v1.SOURCE_REGIME),
            "industry_sha256": sha256(v1.INDUSTRY_PANEL),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    query = f"""
    WITH descriptors AS (
      SELECT d.*,
        median(turnover_fraction) OVER (
          PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS prior20_turn,
        CASE WHEN coord_high>coord_low THEN (coord_close-coord_low)/(coord_high-coord_low) END
          AS close_location,
        (coord_high+coord_low+coord_close)/3.0 AS typical_price
      FROM read_parquet('{v1.DAILY}') d
      WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
    ), eligible_industry AS (
      SELECT trade_date,cal_idx,symbol,causal_industry,ret20,
        cume_dist() OVER (PARTITION BY trade_date,causal_industry ORDER BY ret20)
          AS industry_ret20_pct
      FROM descriptors
      WHERE current_valid AND hard_valid AND industry_valid AND historical_identity_valid
        AND causal_industry IS NOT NULL AND industry_snapshot_id IS NOT NULL AND ret20 IS NOT NULL
    ), industry_state AS (
      SELECT trade_date,causal_industry,count(*) AS industry_n20,
        median(ret20) AS industry_median_ret20,
        avg(CASE WHEN ret20>0 THEN 1.0 ELSE 0.0 END) AS industry_positive_ret20_share
      FROM eligible_industry GROUP BY trade_date,causal_industry
    ), joined AS (
      SELECT d.*,p.ret20 AS prior_session_ret20,p.industry_ret20_pct,
        p.trade_date AS prior_session_date,s.industry_n20,s.industry_median_ret20,
        s.industry_positive_ret20_share,r.market_regime,r.market_median_ret20,
        r.market_positive_ret20_share,r.market_median_ret60,r.market_positive_ret60_share,
        r.latest_source_timestamp AS market_latest_source_timestamp,
        CASE WHEN d.current_valid AND d.hard_valid AND d.trade_status=1
          AND d.current_day_data_tradable AND d.market_rule_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND d.industry_valid AND d.historical_identity_valid
          AND d.industry_snapshot_id IS NOT NULL
          AND p.cal_idx=d.cal_idx-1 AND p.causal_industry=d.causal_industry
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
      JOIN read_parquet('{v1.SOURCE_REGIME}') r ON r.trade_date=d.trade_date
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
      SELECT m.*,d1.trade_date AS acceptance_date_1,d1.coord_close AS acceptance_close_1,
        d1.invalid_step_cum AS acceptance_invalid_cum,d1.trade_status AS acceptance_status,
        d1.current_day_data_tradable AS acceptance_tradable,d1.market_rule_valid AS acceptance_rule,
        d1.corporate_action_valid AS acceptance_ca_valid,
        d1.corporate_action_blocking AS acceptance_ca_blocking,
        d1.current_valid AS acceptance_current,d1.hard_valid AS acceptance_hard,
        d2.trade_date AS confirmation_date,d2.cal_idx AS confirmation_cal_idx,
        d2.coord_close AS confirmation_close,d2.invalid_step_cum AS confirmation_invalid_cum,
        d2.trade_status AS confirmation_status,d2.current_day_data_tradable AS confirmation_tradable,
        d2.market_rule_valid AS confirmation_rule,d2.corporate_action_valid AS confirmation_ca_valid,
        d2.corporate_action_blocking AS confirmation_ca_blocking,
        d2.current_valid AS confirmation_current,d2.hard_valid AS confirmation_hard,
        d2.available_at AS confirmation_available_at,d2.decision_at AS confirmation_decision_at,
        r2.market_regime AS confirmation_market_regime,
        r2.market_median_ret20 AS confirmation_market_median_ret20,
        r2.market_positive_ret20_share AS confirmation_market_positive_ret20_share,
        r2.latest_source_timestamp AS confirmation_market_latest_source_timestamp,
        s2.industry_n20 AS confirmation_industry_n20,
        s2.industry_median_ret20 AS confirmation_industry_median_ret20,
        s2.industry_positive_ret20_share AS confirmation_industry_positive_ret20_share
      FROM mother m
      JOIN descriptors d1 ON d1.symbol=m.symbol AND d1.cal_idx=m.cal_idx+1
      JOIN descriptors d2 ON d2.symbol=m.symbol AND d2.cal_idx=m.cal_idx+2
      JOIN read_parquet('{v1.SOURCE_REGIME}') r2 ON r2.trade_date=d2.trade_date
      JOIN industry_state s2 ON s2.trade_date=d2.trade_date AND s2.causal_industry=m.causal_industry
    ), pressure AS (
      SELECT a.*,
        count(h.cal_idx) AS pressure_history_sessions,
        sum(CASE WHEN h.typical_price>=0.85*a.confirmation_close
                   AND h.typical_price<=1.15*a.confirmation_close
                 THEN coalesce(h.turnover_fraction,0) ELSE 0 END) AS local_corridor_turnover,
        sum(CASE WHEN h.typical_price>a.confirmation_close
                   AND h.typical_price<=1.15*a.confirmation_close
                 THEN coalesce(h.turnover_fraction,0) ELSE 0 END) AS overhead_corridor_turnover,
        sum(CASE WHEN h.typical_price>=0.85*a.confirmation_close
                   AND h.typical_price<=a.confirmation_close
                 THEN coalesce(h.turnover_fraction,0) ELSE 0 END) AS support_corridor_turnover,
        max(CASE WHEN h.cal_idx>=a.confirmation_cal_idx-60 THEN h.coord_high END) AS prior60_high,
        max(h.coord_high) AS prior120_high,
        min(CASE WHEN h.cal_idx>=a.confirmation_cal_idx-20 THEN h.coord_low END) AS prior20_low,
        min(CASE WHEN h.cal_idx>=a.confirmation_cal_idx-60 THEN h.coord_low END) AS prior60_low
      FROM accepted_clock a
      LEFT JOIN descriptors h ON h.symbol=a.symbol
        AND h.cal_idx BETWEEN a.confirmation_cal_idx-120 AND a.confirmation_cal_idx-1
      GROUP BY ALL
    ), flags AS (
      SELECT *,
        overhead_corridor_turnover/nullif(local_corridor_turnover,0) AS overhead_share,
        overhead_corridor_turnover/nullif(support_corridor_turnover,0) AS overhead_support_ratio,
        confirmation_close/nullif(prior60_high,0)-1 AS pressure_break60,
        confirmation_close/nullif(prior120_high,0)-1 AS pressure_break120,
        prior20_low/nullif(prior60_low,0)-1 AS support_rise20_vs60,
        market_median_ret20-market_median_ret60 AS market_return_acceleration,
        market_positive_ret20_share-market_positive_ret60_share AS market_breadth_acceleration,
        market_median_ret20>0 AND market_positive_ret20_share>0.50 AS mother_short_bull,
        confirmation_market_median_ret20>0
          AND confirmation_market_positive_ret20_share>0.50 AS confirmation_short_bull,
        NOT (market_median_ret60>=0.20 AND market_median_ret20<=0.10) AS not_mature_exhaustion,
        market_median_ret20>=market_median_ret60
          AND market_positive_ret20_share>=market_positive_ret60_share AS early_acceleration,
        pressure_history_sessions>=120 AND local_corridor_turnover>0
          AND overhead_corridor_turnover/nullif(local_corridor_turnover,0)<=0.25 AS low_overhead,
        acceptance_status=1 AND acceptance_tradable AND acceptance_rule
          AND acceptance_ca_valid AND NOT acceptance_ca_blocking
          AND acceptance_current AND acceptance_hard
          AND confirmation_status=1 AND confirmation_tradable AND confirmation_rule
          AND confirmation_ca_valid AND NOT confirmation_ca_blocking
          AND confirmation_current AND confirmation_hard AS two_session_data_valid,
        acceptance_invalid_cum=invalid_step_cum
          AND confirmation_invalid_cum=invalid_step_cum AS coordinate_lineage_valid,
        acceptance_close_1>=coord_close AND confirmation_close>=coord_close AS price_acceptance,
        confirmation_industry_n20>=10 AND confirmation_industry_median_ret20>0
          AND confirmation_industry_positive_ret20_share>=0.55 AS confirmation_industry_healthy
      FROM pressure
    )
    SELECT
      'DBLPR-' || strftime(confirmation_date,'%Y%m%d') || '-' || replace(symbol,'.','') AS event_id,
      symbol,sleeve,causal_industry,trade_date AS mother_signal_date,cal_idx AS mother_cal_idx,
      confirmation_date AS signal_date,confirmation_cal_idx AS cal_idx,
      confirmation_invalid_cum AS invalid_step_cum,confirmation_close AS signal_coord_close,
      confirmation_available_at AS available_at,confirmation_decision_at AS decision_at,
      confirmation_decision_at AS feature_latest_timestamp,
      prior_session_date,prior_session_ret20,industry_ret20_pct,
      industry_n20,industry_median_ret20,industry_positive_ret20_share,
      prior_session_ret20-industry_median_ret20 AS stock_minus_industry_ret20,
      market_regime,market_median_ret20,market_positive_ret20_share,
      market_median_ret60,market_positive_ret60_share,market_return_acceleration,
      market_breadth_acceleration,market_latest_source_timestamp,
      same_date_mother_count,coord_close AS mother_close,step_return,close_location,
      turnover_fraction/prior20_turn AS turnover_expansion,acceptance_date_1,
      acceptance_close_1,confirmation_close,confirmation_market_regime,
      confirmation_market_median_ret20,confirmation_market_positive_ret20_share,
      confirmation_market_latest_source_timestamp,confirmation_industry_n20,
      confirmation_industry_median_ret20,confirmation_industry_positive_ret20_share,
      pressure_history_sessions,local_corridor_turnover,overhead_corridor_turnover,
      support_corridor_turnover,prior60_high,prior120_high,prior20_low,prior60_low,
      overhead_share,overhead_support_ratio,pressure_break60,
      pressure_break120,support_rise20_vs60,mother_short_bull,confirmation_short_bull,
      not_mature_exhaustion,early_acceleration,low_overhead,two_session_data_valid,
      coordinate_lineage_valid,price_acceptance,confirmation_industry_healthy,
      CASE WHEN early_acceleration THEN 'EARLY_BREADTH_ACCELERATION'
           ELSE 'LOW_OVERHEAD_ROTATION' END AS admission_lane
    FROM flags
    WHERE same_date_mother_count>=10 AND mother_short_bull AND confirmation_short_bull
      AND not_mature_exhaustion AND confirmation_industry_healthy
      AND two_session_data_valid AND coordinate_lineage_valid AND price_acceptance
      AND pressure_history_sessions>=120 AND local_corridor_turnover>0
      AND (early_acceleration OR low_overhead)
    ORDER BY signal_date,sleeve,symbol,event_id
    """
    frame = con.execute(query).fetchdf()
    con.close()
    for column in (
        "mother_signal_date",
        "signal_date",
        "available_at",
        "decision_at",
        "feature_latest_timestamp",
        "prior_session_date",
        "market_latest_source_timestamp",
        "acceptance_date_1",
        "confirmation_market_latest_source_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.empty or frame.event_id.duplicated().any():
        raise ResearchError("empty or duplicate candidate identity")
    if not frame.signal_date.gt(frame.mother_signal_date).all():
        raise ResearchError("confirmation does not follow mother event")
    if not frame.cal_idx.eq(frame.mother_cal_idx + 2).all():
        raise ResearchError("confirmation is not the second exchange session")
    if frame[["available_at", "feature_latest_timestamp"]].gt(frame.decision_at, axis=0).any().any():
        raise ResearchError("stock feature arrives after decision")
    if frame.market_latest_source_timestamp.gt(frame.decision_at).any():
        raise ResearchError("mother market state arrives after decision")
    if frame.confirmation_market_latest_source_timestamp.gt(frame.decision_at).any():
        raise ResearchError("confirmation market state arrives after decision")
    if not frame.pressure_history_sessions.ge(120).all():
        raise ResearchError("short pressure history escaped")
    lane_count = frame.early_acceleration.astype(int) + (
        (~frame.early_acceleration) & frame.low_overhead
    ).astype(int)
    if not lane_count.eq(1).all():
        raise ResearchError("admission lanes overlap or are empty")
    return frame


def blind_sample(frame: pd.DataFrame, count: int = 60) -> pd.DataFrame:
    sample = frame.copy()
    sample["signal_year"] = sample.signal_date.dt.year
    sample["blind_key"] = sample.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    picked = (
        sample.sort_values("blind_key", kind="mergesort")
        .groupby(["signal_year", "admission_lane"], sort=True, group_keys=False)
        .head(3)
    )
    if len(picked) < count:
        remainder = sample.loc[~sample.event_id.isin(picked.event_id)].sort_values("blind_key")
        picked = pd.concat([picked, remainder.head(count - len(picked))], ignore_index=True)
    picked = picked.sort_values(["signal_date", "sleeve", "symbol"]).head(count).copy()
    picked.insert(0, "chart_id", [f"V25-BLIND-{i:03d}" for i in range(1, len(picked) + 1)])
    return picked


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    daily = con.execute(
        f"""SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.turnover_fraction,d.ret20 FROM read_parquet('{v1.DAILY}') d JOIN symbols s USING(symbol)
          WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
          ORDER BY d.symbol,d.trade_date"""
    ).fetchdf()
    con.close()
    daily.trade_date = pd.to_datetime(daily.trade_date)
    groups = {key: part.reset_index(drop=True) for key, part in daily.groupby("symbol")}
    regime = pd.read_parquet(v1.SOURCE_REGIME)
    regime.trade_date = pd.to_datetime(regime.trade_date)
    industry = pd.read_parquet(v1.INDUSTRY_PANEL)
    industry.trade_date = pd.to_datetime(industry.trade_date)
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            part = groups[event.symbol]
            positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
            if len(positions) != 1:
                raise ResearchError(f"chart clock missing {event.event_id}")
            end = int(positions[0])
            stock = part.iloc[max(0, end - 119) : end + 1].copy()
            start = stock.trade_date.min()
            market = regime.loc[regime.trade_date.between(start, event.signal_date)].copy()
            ind = industry.loc[
                industry.causal_industry.eq(event.causal_industry)
                & industry.trade_date.between(start, event.signal_date)
            ].sort_values("trade_date")
            fig, axes = v1.plt.subplots(
                4, 1, figsize=(11.7, 8.3), gridspec_kw={"height_ratios": [2.5, 0.7, 1, 1]}
            )
            x = v1.mdates.date2num(stock.trade_date)
            colors = np.where(stock.coord_close.ge(stock.coord_open), "#dc2626", "#059669")
            axes[0].vlines(x, stock.coord_low, stock.coord_high, color=colors, linewidth=0.65)
            body_low = np.minimum(stock.coord_open, stock.coord_close)
            body_height = np.maximum(
                np.abs(stock.coord_close - stock.coord_open), stock.coord_close.abs() * 0.0005
            )
            axes[0].bar(x, body_height, bottom=body_low, width=0.65, color=colors, edgecolor=colors)
            axes[0].axvline(pd.Timestamp(event.mother_signal_date), color="#f59e0b", linestyle=":", label="Mother demand")
            axes[0].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--", label="Decision close")
            axes[0].axhspan(
                float(event.signal_coord_close), float(event.signal_coord_close) * 1.15,
                color="#fb923c", alpha=0.12, label="15% overhead corridor",
            )
            axes[0].axhline(float(event.prior60_high), color="#7c3aed", linestyle=":", label="Prior 60d pressure")
            axes[0].set_title(
                f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry} | {event.admission_lane}",
                fontproperties=v1.CJK_FONT,
            )
            axes[0].legend(loc="upper left", fontsize=7, ncol=4)
            axes[0].grid(alpha=0.2)
            axes[1].bar(stock.trade_date, stock.turnover_fraction, color=colors, width=0.75, alpha=0.75)
            axes[1].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--")
            axes[1].set_ylabel("Turnover")
            axes[1].grid(alpha=0.2)
            axes[2].plot(market.trade_date, market.market_median_ret20, color="#166534", label="Market median ret20")
            axes[2].plot(market.trade_date, market.market_median_ret60, color="#0f766e", label="Market median ret60")
            axes[2].axhline(0, color="black", linewidth=0.7)
            axes[2].legend(loc="upper left", fontsize=8, ncol=2)
            axes[2].grid(alpha=0.2)
            axes[3].plot(ind.trade_date, ind.industry_median_ret20, color="#7c3aed", label="Industry median ret20")
            axes[3].plot(stock.trade_date, stock.ret20, color="#b45309", label="Stock ret20")
            axes[3].axhline(0, color="black", linewidth=0.7)
            axes[3].legend(loc="upper left", fontsize=8, ncol=2)
            axes[3].grid(alpha=0.2)
            axes[3].xaxis.set_major_locator(v1.mdates.MonthLocator(interval=1))
            axes[3].xaxis.set_major_formatter(v1.mdates.DateFormatter("%Y-%m"))
            fig.text(
                0.01, 0.012,
                f"Outcome-blind. Mother count {event.same_date_mother_count}; overhead share {event.overhead_share:.1%}; "
                f"market acceleration {event.market_return_acceleration:+.1%}; no post-decision bar.",
                fontsize=8,
            )
            fig.tight_layout(rect=[0, 0.035, 1, 1])
            pdf.savefig(fig, dpi=160)
            v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    frame = build_candidates()
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    v1.write_parquet(frame, CANDIDATES)
    sample = blind_sample(frame)
    sample.to_csv(BLIND_INDEX, index=False)
    render_blind_charts(sample)
    annual = frame.groupby(frame.signal_date.dt.year).size().reindex(YEARS, fill_value=0).astype(int)
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),
        "market_after_decision_count": int(frame.confirmation_market_latest_source_timestamp.gt(frame.decision_at).sum()),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "lane_overlap_count": int(
            (frame.early_acceleration & frame.admission_lane.eq("LOW_OVERHEAD_ROTATION")).sum()
        ),
        "blind_chart_post_decision_bar_count": 0,
        "outcomes_opened": False,
    }
    if any(value for key, value in audit.items() if key != "outcomes_opened"):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "daily_sha256": sha256(v1.DAILY),
        "regime_sha256": sha256(v1.SOURCE_REGIME),
        "industry_sha256": sha256(v1.INDUSTRY_PANEL),
        "candidate_sha256": sha256(CANDIDATES),
        "blind_pdf_sha256": sha256(BLIND_PDF),
        "candidate_count": int(len(frame)),
        "lane_counts": frame.admission_lane.value_counts().sort_index().astype(int).to_dict(),
        "annual_candidate_count": {str(year): int(value) for year, value in annual.items()},
        "audit": audit,
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "daily_sha256": sha256(v1.DAILY),
        "regime_sha256": sha256(v1.SOURCE_REGIME),
        "industry_sha256": sha256(v1.INDUSTRY_PANEL),
        "candidate_sha256": sha256(CANDIDATES),
        "blind_pdf_sha256": sha256(BLIND_PDF),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")
    return freeze


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"completed_trades": 0, "mean_net": None, "median_net": None, "win_rate": None, "severe_loss10": None, "mean_holding_sessions": None}
    return {
        "completed_trades": int(len(frame)),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
    }


def write_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Outcome",
        "",
        f"- Verdict: `{result['verdict']}`",
        f"- Accepted completed trades: {result['capacity_accepted_completed_trades']}",
        f"- Average trades/year: {result['average_trades_per_year']:.1f}",
        f"- Mean net/trade: {result['full_2014_2023']['mean_net']:.2%}",
        f"- Median net/trade: {result['full_2014_2023']['median_net']:.2%}",
        f"- Mean holding: {result['full_2014_2023']['mean_holding_sessions']:.2f} sessions",
        f"- Win rate: {result['full_2014_2023']['win_rate']:.2%}",
        "",
        "## Annual accepted trades",
        "",
        "| Year | Trades | Mean net | Mean hold |",
        "|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = result["annual"][str(year)]
        mean = "-" if item["mean_net"] is None else f"{item['mean_net']:.2%}"
        hold = "-" if item["mean_holding_sessions"] is None else f"{item['mean_holding_sessions']:.2f}"
        lines.append(f"| {year} | {item['completed_trades']} | {mean} | {hold} |")
    lines += ["", "## Gates", ""]
    lines += [f"- {key}: `{value}`" for key, value in result["gate"].items()]
    lines += ["", "## Audit", ""]
    lines += [f"- {key}: `{value}`" for key, value in result["audit"].items()]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    candidates = pd.read_parquet(CANDIDATES)
    candidates.signal_date = pd.to_datetime(candidates.signal_date)
    outcomes, outcome_audit = v2.build_outcomes(candidates)
    outcomes = outcomes.loc[outcomes.profile.eq(PROFILE)].copy()
    outcomes.signal_date = pd.to_datetime(outcomes.signal_date)
    v1.write_parquet(outcomes, OUTCOMES)
    trades = candidates.merge(outcomes, on=["event_id", "symbol", "sleeve", "signal_date"], validate="one_to_one")
    trades = trades.loc[trades.status.eq("COMPLETED")].copy()
    daily = v1.load_trade_daily(trades.symbol.astype(str).unique().tolist())
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
    lanes = {str(lane): summary(part) for lane, part in accepted.groupby("admission_lane", sort=True)}
    concentration = v1.concentration_metrics(accepted)
    v24_overlap = None
    v24_path = Path("/Volumes/quant/CY_quant_research/ashare_bull_quiet_platform_dual_demand_v24/stage_b/portfolio_accepted.parquet")
    if v24_path.is_file():
        v24 = pd.read_parquet(v24_path, columns=["symbol", "entry_date"])
        v24.entry_date = pd.to_datetime(v24.entry_date)
        v24_keys = set(zip(v24.symbol.astype(str), v24.entry_date))
        v24_overlap = int(sum((str(row.symbol), pd.Timestamp(row.entry_date)) in v24_keys for row in accepted.itertuples()))
    gate = {
        "capacity_accepted_completed_trades_gt_500": len(accepted) > 500,
        "mean_net_gt_5pct": full["mean_net"] is not None and full["mean_net"] > 0.05,
        "mean_holding_lt_15": full["mean_holding_sessions"] is not None and full["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0 for year in range(2021, 2024)),
        "mean_ex_best5_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
    }
    audit = {
        "signal_bar_fill_count": int((accepted.entry_date <= accepted.signal_date).sum()),
        "t1_same_day_exit_count": int((accepted.exit_cal_idx <= accepted.entry_cal_idx).sum()),
        "candidate_feature_after_decision_count": int(candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()),
        "post_2023_signal_or_feature_row_count": int(candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
        "outcome_signal_fill_violation_count": int(outcome_audit.get("signal_bar_fill_count", 0)),
        "outcome_t1_violation_count": int(outcome_audit.get("t1_same_day_exit_count", 0)),
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    result = {
        "experiment": EXPERIMENT,
        "contract_sha256": freeze["contract_sha256"],
        "spec_sha256": freeze["spec_sha256"],
        "profile": PROFILE,
        "raw_candidates": int(len(candidates)),
        "capacity_accepted_completed_trades": int(len(accepted)),
        "capacity_skips": int(len(skipped)),
        "average_trades_per_year": len(accepted) / 10,
        "full_2014_2023": full,
        "annual": annual,
        "admission_lanes": lanes,
        "portfolio": portfolio,
        "concentration": concentration,
        "v24_same_symbol_entry_date_overlap_count": v24_overlap,
        "gate": gate,
        "audit": audit,
        "repository_2024_plus_rows_used_for_signal_or_feature": 0,
        "post_2023_rows_used_only_for_pre_2024_trade_resolution": True,
        "verdict": "DIFFUSION_BULL_LAGGARD_PRESSURE_RELEASE_TARGET_MET" if all(gate.values()) else "DIFFUSION_BULL_LAGGARD_PRESSURE_RELEASE_FAILS_TARGET",
        "hashes": {
            "outcomes": sha256(OUTCOMES),
            "accepted": sha256(ACCEPTED),
            "skipped": sha256(SKIPPED),
            "nav": sha256(NAV),
            "blind_pdf": sha256(BLIND_PDF),
        },
    }
    write_json(RESULT, result)
    write_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        value = run_stage_a()
    elif args.stage_b:
        value = run_stage_b()
    else:
        parser.error("choose --stage-a or --stage-b")
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
