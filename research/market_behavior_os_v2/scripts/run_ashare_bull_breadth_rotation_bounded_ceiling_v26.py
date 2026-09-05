#!/usr/bin/env python3
"""Causal breadth-rotation bounded-ceiling bull strategy development."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-BREADTH80-NONCROWDED-CEILING-RELAY-V26"
EXT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_breadth80_noncrowded_ceiling_relay_v26"
)
SOURCE = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_idiosyncratic_ceiling_breakout_v18/stage_a/candidates.parquet"
)
SOURCE_OUTCOMES = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_idiosyncratic_ceiling_breakout_v18/stage_b/outcomes.parquet"
)
V24_ACCEPTED = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_bull_quiet_platform_dual_demand_v24/stage_b/portfolio_accepted.parquet"
)
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

# The selected values are frozen together as one economic rule.  They are not
# re-estimated by year or by portfolio collision state.
MARKET_BREADTH_MIN = 0.80
PRIOR120_RANGE_MAX = 0.60
STEP_RETURN_MIN = 0.02
STEP_RETURN_MAX = 0.07


class ResearchError(RuntimeError):
    """Fail-closed V26 research error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "When at least eighty percent of the executable A-share cross-section "
            "has a positive completed twenty-session return, demand is broad rather "
            "than index-concentrated. Inside that breadth bull, a healthy but still "
            "noncrowded PIT industry can receive rotation capital. A stock's first "
            "causal escape through a bounded 120-session holder-cost ceiling, on a "
            "moderate rather than euphoric demand bar, can continue while old holders "
            "are relieved rather than creating overwhelming new supply."
        ),
        "complementarity_to_v24": (
            "V24 requires a quiet forty-session platform plus an upward information "
            "gap and dual-demand confirmation. V26 uses no information-gap identity: "
            "its bull definition is extreme twenty-session market breadth and its "
            "stock mechanism is rotation through a bounded 120-session ceiling."
        ),
        "four_simple_rules": {
            "BREADTH80_BULL": (
                "completed-session executable-universe positive-ret20 share >= 80%"
            ),
            "HEALTHY_NONCROWDED_INDUSTRY": (
                "PIT industry members >=5, median ret20 >0, positive-ret20 share >50%, "
                "and industry median-ret20 percentile <=50%"
            ),
            "FIRST_CAUSAL_CEILING_RELAY": (
                "completed close crosses its prior 120-session high from below; "
                "signal closes in the top 30% of its bar, turnover is >=1.5x prior20 "
                "mean, prior20 return is between -8% and +15%, and the frozen mother "
                "population enforces a 30-session same-symbol cooldown"
            ),
            "BOUNDED_MODERATE_DEMAND": (
                "prior 120-session high/low range <=60% and signal step return is "
                "between +2% and +7% inclusive"
            ),
        },
        "source_population": {
            "identity": "frozen causal V18 idiosyncratic 120-session ceiling-breakout mother",
            "source_sha256": v1.sha256(SOURCE),
            "role": "candidate representation, not accepted strategy evidence",
        },
        "decision_clock": "completed signal-session close",
        "entry": "first legal next daily open within three market sessions",
        "target": "+15% coordinate standing target from the first T+1-sellable session",
        "failure_stop": "none",
        "time_stop": "completed H15 state, then next legal daily open",
        "round_trip_cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "collision_rank": v1.contract_value()["portfolio"]["collision_rank"],
        "required_gate": {
            "capacity_accepted_completed_trades_2014_2023_gt": 500,
            "capacity_accepted_completed_trades_per_year_gt": 50,
            "mean_net_return_gt": 0.05,
            "mean_holding_sessions_lt": 15,
            "active_2019_2023_years_have_positive_mean": True,
            "mean_excluding_best_five_signal_dates_positive": True,
            "top_five_signal_date_positive_pnl_share_max": 0.25,
            "both_boards_positive_mean": True,
        },
        "evidence_governance": {
            "2014_2018": "iterative mechanism discovery",
            "2019_2023": "observed chronological robustness, not pristine validation",
            "reason_not_pristine": (
                "later outcomes were inspected during autonomous strategy discovery"
            ),
            "signals_or_features_after_2023": False,
            "post_2023_rows": "permitted only to resolve positions signaled by 2023-12-31",
        },
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "FROZEN_CAUSAL_BREADTH80_ROTATION_CEILING_CONTRACT",
            "contract_sha256": v1.sha256(CONTRACT),
            "runner_sha256": v1.sha256(Path(__file__)),
            "source_sha256": v1.sha256(SOURCE),
            "daily_sha256": v1.sha256(v1.DAILY),
            "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
            "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL),
            "execution_engine_sha256": v1.sha256(Path(v2.__file__)),
            "portfolio_engine_sha256": v1.sha256(Path(v1.__file__)),
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def rule_mask(frame: pd.DataFrame) -> pd.Series:
    value = (
        frame.market_regime.eq("BULL")
        & frame.market_positive_ret20_share.ge(MARKET_BREADTH_MIN)
        & frame.industry_n20.ge(5)
        & frame.industry_median_ret20.gt(0)
        & frame.industry_positive_ret20_share.gt(0.50)
        & frame.industry_ret20_percentile.le(0.50)
        & frame.history_n120.eq(120)
        & frame.coord_close.ge(frame.prior120_high)
        & frame.previous_close.lt(frame.previous_prior120_high)
        & frame.signal_close_location.ge(0.70)
        & frame.turnover_expansion.ge(1.50)
        & frame.prior_ret20.between(-0.08, 0.15, inclusive="both")
        & frame.prior120_range.le(PRIOR120_RANGE_MAX)
        & frame.step_return.between(
            STEP_RETURN_MIN, STEP_RETURN_MAX, inclusive="both"
        )
    )
    return value.fillna(False)


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    source = v1.read_parquet_duckdb(SOURCE)
    for column in (
        "trade_date",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp",
    ):
        source[column] = pd.to_datetime(source[column])
    source = source.sort_values(["symbol", "signal_date", "event_id"]).reset_index(drop=True)
    source["prior_source_signal_date"] = source.groupby("symbol").signal_date.shift(1)
    source["prior_source_cal_idx"] = source.groupby("symbol").cal_idx.shift(1)
    source["source_cooldown_sessions"] = source.cal_idx - source.prior_source_cal_idx
    selected = source.loc[rule_mask(source)].copy()
    selected["admission_lane"] = "BREADTH80_NONCROWDED_CEILING_RELAY"
    selected["feature_latest_timestamp_v26"] = selected[
        ["feature_latest_timestamp", "market_latest_source", "industry_latest_source"]
    ].max(axis=1)
    selected = selected.sort_values(["signal_date", "symbol", "event_id"]).reset_index(drop=True)
    v1.write_parquet(selected, CANDIDATES)
    return selected


def candidate_audit(frame: pd.DataFrame) -> dict[str, int]:
    source = v1.read_parquet_duckdb(SOURCE)
    source["signal_date"] = pd.to_datetime(source.signal_date)
    source = source.sort_values(["symbol", "signal_date", "event_id"])
    prior_cal_idx = source.groupby("symbol").cal_idx.shift(1)
    cooldown_le30 = int(((source.cal_idx - prior_cal_idx).le(30)).fillna(False).sum())
    return {
        "candidate_identity_duplicate_count": int(frame.event_id.duplicated().sum()),
        "rule_mask_false_count": int((~rule_mask(frame)).sum()),
        "available_after_decision_count": int(frame.available_at.gt(frame.decision_at).sum()),
        "market_state_after_decision_count": int(
            frame.market_latest_source.gt(frame.decision_at).sum()
        ),
        "industry_state_after_decision_count": int(
            frame.industry_latest_source.gt(frame.decision_at).sum()
        ),
        "feature_after_decision_count": int(
            frame.feature_latest_timestamp_v26.gt(frame.decision_at).sum()
        ),
        "source_same_symbol_cooldown_le30_sessions_count": cooldown_le30,
        "post_2023_signal_count": int(
            frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "invalid_required_lineage_count": int(
            (
                ~frame.hard_valid.fillna(False)
                | ~frame.history_valid.fillna(False)
                | ~frame.current_valid.fillna(False)
                | ~frame.corporate_action_valid.fillna(False)
                | frame.corporate_action_blocking.fillna(True)
                | ~frame.current_day_data_tradable.fillna(False)
                | frame.is_st.fillna(True)
                | frame.industry_snapshot_id.isna()
            ).sum()
        ),
        **independent_feature_audit(),
    }


def independent_feature_audit() -> dict[str, int]:
    """Recompute every binding rolling/state input from PIT source rows."""
    con = duckdb.connect()
    try:
        rolling = con.execute(
            f"""
            WITH symbols AS (
              SELECT DISTINCT symbol FROM read_parquet('{CANDIDATES}')
            ), eligible_daily AS (
              SELECT d.* FROM read_parquet('{v1.DAILY}') d
              SEMI JOIN symbols s USING(symbol)
              WHERE hard_valid AND history_valid AND current_valid
                AND corporate_action_valid AND NOT corporate_action_blocking
                AND current_day_data_tradable AND market_rule_valid
                AND trade_status=1 AND NOT is_st
            ), calculated AS (
              SELECT symbol,trade_date,
                count(*) OVER(PARTITION BY symbol ORDER BY cal_idx
                  ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING) AS calc_n120,
                max(coord_high) OVER(PARTITION BY symbol ORDER BY cal_idx
                  ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING) AS calc_high120,
                min(coord_low) OVER(PARTITION BY symbol ORDER BY cal_idx
                  ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING) AS calc_low120,
                max(coord_high) OVER(PARTITION BY symbol ORDER BY cal_idx
                  ROWS BETWEEN 121 PRECEDING AND 2 PRECEDING) AS calc_previous_high120,
                avg(turnover_fraction) OVER(PARTITION BY symbol ORDER BY cal_idx
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) AS calc_turnover20,
                lag(coord_close) OVER(PARTITION BY symbol ORDER BY cal_idx) AS calc_previous_close,
                coord_close/nullif(prior_coord_close,0)-1 AS calc_step_return,
                (coord_close-coord_low)/nullif(coord_high-coord_low,0)
                  AS calc_close_location
              FROM eligible_daily
            ), checked AS (
              SELECT c.*,
                z.calc_n120,z.calc_high120,z.calc_low120,z.calc_previous_high120,
                z.calc_turnover20,z.calc_previous_close,z.calc_step_return,
                z.calc_close_location
              FROM read_parquet('{CANDIDATES}') c
              LEFT JOIN calculated z
                ON c.symbol=z.symbol AND c.signal_date=z.trade_date
            )
            SELECT
              count(*) FILTER (WHERE calc_n120 IS NULL) AS join_missing,
              count(*) FILTER (WHERE history_n120<>calc_n120) AS n120_mismatch,
              count(*) FILTER (WHERE abs(prior120_high-calc_high120)>1e-12)
                AS high120_mismatch,
              count(*) FILTER (WHERE abs(prior120_low-calc_low120)>1e-12)
                AS low120_mismatch,
              count(*) FILTER (
                WHERE abs(previous_prior120_high-calc_previous_high120)>1e-12
              ) AS previous_high120_mismatch,
              count(*) FILTER (WHERE abs(prior20_turnover-calc_turnover20)>1e-12)
                AS turnover20_mismatch,
              count(*) FILTER (WHERE abs(previous_close-calc_previous_close)>1e-12)
                AS previous_close_mismatch,
              count(*) FILTER (WHERE abs(step_return-calc_step_return)>1e-12)
                AS step_return_mismatch,
              count(*) FILTER (
                WHERE abs(signal_close_location-calc_close_location)>1e-12
              ) AS close_location_mismatch
            FROM checked
            """
        ).fetchdf().iloc[0]
        state = con.execute(
            f"""
            SELECT
              count(*) FILTER (
                WHERE abs(c.market_positive_ret20_share-r.market_positive_ret20_share)>1e-12
                  OR c.market_regime<>r.market_regime
              ) AS market_state_mismatch,
              count(*) FILTER (
                WHERE abs(c.industry_median_ret20-i.industry_median_ret20)>1e-12
                  OR abs(c.industry_positive_ret20_share-i.industry_positive_ret20_share)>1e-12
                  OR abs(c.industry_ret20_percentile-i.industry_ret20_percentile)>1e-12
                  OR c.industry_n20<>i.industry_n20
              ) AS industry_state_mismatch
            FROM read_parquet('{CANDIDATES}') c
            LEFT JOIN read_parquet('{v1.SOURCE_REGIME}') r
              ON c.signal_date=r.trade_date
            LEFT JOIN read_parquet('{v1.INDUSTRY_PANEL}') i
              ON c.signal_date=i.trade_date AND c.causal_industry=i.causal_industry
            """
        ).fetchdf().iloc[0]
    finally:
        con.close()
    return {
        "independent_daily_join_missing_count": int(rolling.join_missing),
        "independent_history_n120_mismatch_count": int(rolling.n120_mismatch),
        "independent_prior120_high_mismatch_count": int(rolling.high120_mismatch),
        "independent_prior120_low_mismatch_count": int(rolling.low120_mismatch),
        "independent_previous_high120_mismatch_count": int(
            rolling.previous_high120_mismatch
        ),
        "independent_prior20_turnover_mismatch_count": int(rolling.turnover20_mismatch),
        "independent_previous_close_mismatch_count": int(rolling.previous_close_mismatch),
        "independent_step_return_mismatch_count": int(rolling.step_return_mismatch),
        "independent_close_location_mismatch_count": int(rolling.close_location_mismatch),
        "independent_market_state_mismatch_count": int(state.market_state_mismatch),
        "independent_industry_state_mismatch_count": int(state.industry_state_mismatch),
    }


def blind_sample(frame: pd.DataFrame, count: int = 60) -> pd.DataFrame:
    work = frame.copy()
    work["year"] = work.signal_date.dt.year
    work["hash_order"] = work.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    pieces = [
        part.sort_values("hash_order").head(2)
        for _, part in work.groupby(["year", "sleeve"], sort=True)
    ]
    sample = pd.concat(pieces, ignore_index=True).sort_values("hash_order").head(count)
    if len(sample) < count:
        remaining = work.loc[~work.event_id.isin(sample.event_id)]
        sample = pd.concat(
            [sample, remaining.sort_values("hash_order").head(count - len(sample))],
            ignore_index=True,
        )
    sample = sample.sort_values(["signal_date", "symbol", "event_id"]).reset_index(drop=True)
    if len(sample) != count:
        raise ResearchError(f"blind sample contains {len(sample)} rows, expected {count}")
    sample.insert(0, "chart_id", [f"BREADTH80-BLIND-{i:03d}" for i in range(1, count + 1)])
    sample.to_csv(BLIND_INDEX, index=False)
    return sample


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.astype(str).unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    daily = con.execute(
        f"""
        SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,
          d.coord_close,d.turnover_fraction,d.ret20
        FROM read_parquet('{v1.DAILY}') d JOIN symbols USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    con.close()
    daily.trade_date = pd.to_datetime(daily.trade_date)
    groups = {str(key): part.reset_index(drop=True) for key, part in daily.groupby("symbol")}
    regime = v1.read_parquet_duckdb(v1.SOURCE_REGIME)
    regime.trade_date = pd.to_datetime(regime.trade_date)
    industry = v1.read_parquet_duckdb(v1.INDUSTRY_PANEL)
    industry.trade_date = pd.to_datetime(industry.trade_date)
    metadata = {
        "Title": f"{EXPERIMENT} no-post-signal chart audit",
        "Author": "CY research",
        "Creator": "deterministic matplotlib renderer",
        "CreationDate": datetime(2000, 1, 1, tzinfo=timezone.utc),
        "ModDate": datetime(2000, 1, 1, tzinfo=timezone.utc),
    }
    with v1.PdfPages(BLIND_PDF, metadata=metadata) as pdf:
        for event in sample.itertuples(index=False):
            part = groups[str(event.symbol)]
            positions = np.flatnonzero(
                part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy()
            )
            if len(positions) != 1:
                raise ResearchError(f"missing chart signal {event.event_id}")
            signal_pos = int(positions[0])
            stock = part.iloc[max(0, signal_pos - 120) : signal_pos + 1].copy()
            start = stock.trade_date.min()
            market = regime.loc[regime.trade_date.between(start, event.signal_date)]
            sector = industry.loc[
                industry.trade_date.between(start, event.signal_date)
                & industry.causal_industry.eq(event.causal_industry)
            ]
            fig, axes = v1.plt.subplots(
                4, 1, figsize=(11.7, 8.3), gridspec_kw={"height_ratios": [2.7, 0.7, 1, 1]}
            )
            x = v1.mdates.date2num(stock.trade_date)
            colors = np.where(stock.coord_close.ge(stock.coord_open), "#dc2626", "#059669")
            axes[0].vlines(x, stock.coord_low, stock.coord_high, color=colors, linewidth=0.65)
            body_low = np.minimum(stock.coord_open, stock.coord_close)
            body_height = np.maximum(
                abs(stock.coord_close - stock.coord_open), stock.coord_close.abs() * 0.0005
            )
            axes[0].bar(
                x,
                body_height,
                bottom=body_low,
                width=0.65,
                color=colors,
                edgecolor=colors,
                linewidth=0.3,
            )
            axes[0].axhline(
                float(event.prior120_high), color="#ea580c", linestyle="--", label="Prior-120 ceiling"
            )
            axes[0].axhline(
                float(event.prior120_low), color="#0284c7", linestyle=":", label="Prior-120 support"
            )
            axes[0].axvline(
                pd.Timestamp(event.signal_date), color="#7c3aed", linestyle="--", label="Signal close"
            )
            axes[0].set_title(
                f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",
                fontproperties=v1.CJK_FONT,
            )
            axes[0].legend(loc="upper left", fontsize=8, ncol=3)
            axes[0].grid(alpha=0.20)
            axes[1].bar(stock.trade_date, stock.turnover_fraction, width=0.75, color=colors)
            axes[1].axhline(float(event.prior20_turnover), color="#ea580c", linestyle=":")
            axes[1].axvline(pd.Timestamp(event.signal_date), color="#7c3aed", linestyle="--")
            axes[1].set_ylabel("Turnover")
            axes[1].grid(alpha=0.20)
            axes[2].plot(
                market.trade_date,
                market.market_positive_ret20_share,
                color="#166534",
                label="Market positive-ret20 share",
            )
            axes[2].axhline(0.80, color="#dc2626", linestyle="--", label="Breadth80 gate")
            axes[2].plot(
                market.trade_date,
                market.market_median_ret20,
                color="#0284c7",
                alpha=0.75,
                label="Market median ret20",
            )
            axes[2].axhline(0, color="black", linewidth=0.7)
            axes[2].legend(loc="upper left", fontsize=8, ncol=3)
            axes[2].grid(alpha=0.20)
            axes[3].plot(
                sector.trade_date,
                sector.industry_positive_ret20_share,
                color="#7c3aed",
                label="Industry positive-ret20 share",
            )
            axes[3].plot(
                sector.trade_date,
                sector.industry_ret20_percentile,
                color="#b45309",
                label="Industry ret20 percentile",
            )
            axes[3].axhline(0.50, color="black", linestyle=":", linewidth=0.8)
            axes[3].legend(loc="upper left", fontsize=8, ncol=2)
            axes[3].grid(alpha=0.20)
            axes[3].xaxis.set_major_formatter(v1.mdates.DateFormatter("%Y-%m"))
            fig.text(
                0.01,
                0.01,
                (
                    f"No post-signal bars. Prior-120 range {event.prior120_range:.1%}; "
                    f"signal return {event.step_return:.1%}; turnover expansion "
                    f"{event.turnover_expansion:.2f}x; market breadth "
                    f"{event.market_positive_ret20_share:.1%}; industry percentile "
                    f"{event.industry_ret20_percentile:.1%}."
                ),
                fontsize=8,
            )
            fig.tight_layout(rect=[0, 0.035, 1, 1])
            pdf.savefig(fig, dpi=160)
            v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    frame = build_candidates()
    audit = candidate_audit(frame)
    if any(audit.values()):
        raise ResearchError(f"Stage-A audit failed: {audit}")
    sample = blind_sample(frame)
    render_blind_charts(sample)
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": v1.sha256(Path(__file__)),
        "source_sha256": v1.sha256(SOURCE),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_index_sha256": v1.sha256(BLIND_INDEX),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
        "candidate_count": len(frame),
        "annual_candidate_counts": (
            frame.groupby(frame.signal_date.dt.year)
            .size()
            .reindex(YEARS, fill_value=0)
            .astype(int)
            .to_dict()
        ),
        "blind_chart_count": len(sample),
        "audit": audit,
        "outcomes_opened_by_stage_a": False,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "source_sha256": v1.sha256(SOURCE),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_index_sha256": v1.sha256(BLIND_INDEX),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A contract drift: {drift}")
    return freeze


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "completed_trades": 0,
            "mean_net": None,
            "median_net": None,
            "win_rate": None,
            "severe_loss10": None,
            "mean_holding_sessions": None,
            "target_hit_rate": None,
        }
    return {
        "completed_trades": len(frame),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "target_hit_rate": float(frame.exit_reason.eq("TARGET_15").mean()),
    }


def reproduce_outcomes(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES = {PROFILE: {"horizon": 15, "target": 0.15}}
        v2.OUTCOMES = OUTCOMES
        outcomes, execution_audit = v2.build_outcomes(frame)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes
    source = v1.read_parquet_duckdb(SOURCE_OUTCOMES)
    source = source.loc[
        source.profile.eq(PROFILE) & source.event_id.isin(frame.event_id)
    ].copy()
    for data in (outcomes, source):
        for column in ("signal_date", "entry_date", "exit_date"):
            data[column] = pd.to_datetime(data[column])
    check = outcomes.merge(
        source,
        on=["event_id", "profile"],
        how="outer",
        validate="one_to_one",
        suffixes=("_new", "_source"),
        indicator=True,
    )
    completed = check.status_new.eq("COMPLETED") & check.status_source.eq("COMPLETED")
    numeric_mismatch = pd.Series(False, index=check.index)
    for column in ("entry_price", "exit_price", "net_return", "holding_sessions"):
        numeric_mismatch |= completed & ~np.isclose(
            check[f"{column}_new"], check[f"{column}_source"], rtol=0, atol=1e-12
        )
    audit = {
        **execution_audit,
        "outcome_identity_mismatch_count": int(check._merge.ne("both").sum()),
        "outcome_status_mismatch_count": int(
            check.status_new.fillna("MISSING").ne(check.status_source.fillna("MISSING")).sum()
        ),
        "outcome_date_mismatch_count": int(
            (
                completed
                & (
                    check.entry_date_new.ne(check.entry_date_source)
                    | check.exit_date_new.ne(check.exit_date_source)
                )
            ).sum()
        ),
        "outcome_numeric_mismatch_count": int(numeric_mismatch.sum()),
    }
    return outcomes, audit


def overlap_with_v24(accepted: pd.DataFrame) -> dict[str, Any]:
    v24 = v1.read_parquet_duckdb(V24_ACCEPTED)
    for data in (accepted, v24):
        data["signal_date"] = pd.to_datetime(data.signal_date)
        data["entry_date"] = pd.to_datetime(data.entry_date)
    signal_keys = accepted[["symbol", "signal_date"]].merge(
        v24[["symbol", "signal_date"]].drop_duplicates(),
        on=["symbol", "signal_date"],
        how="inner",
    )
    entry_keys = accepted[["symbol", "entry_date"]].merge(
        v24[["symbol", "entry_date"]].drop_duplicates(),
        on=["symbol", "entry_date"],
        how="inner",
    )
    return {
        "v24_accepted_trades": len(v24),
        "same_symbol_signal_date_count": len(signal_keys),
        "same_symbol_entry_date_count": len(entry_keys),
        "v26_unique_entry_share": float(1 - len(entry_keys) / len(accepted)),
    }


def render_report(result: dict[str, Any]) -> None:
    full = result["full_2014_2023"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Outcome",
        "",
        f"- Verdict: **{result['verdict']}**",
        f"- Capacity-accepted completed trades: {full['completed_trades']} "
        f"({result['average_trades_per_year']:.1f}/year)",
        f"- Mean / median net trade: {full['mean_net']:.3%} / {full['median_net']:.3%}",
        f"- Win / severe-loss10: {full['win_rate']:.2%} / {full['severe_loss10']:.2%}",
        f"- Mean holding: {full['mean_holding_sessions']:.2f} sessions",
        f"- CAGR / MaxDD / Sharpe: {result['portfolio']['cagr']:.2%} / "
        f"{result['portfolio']['max_drawdown']:.2%} / {result['portfolio']['sharpe']:.3f}",
        "",
        "## Four simple economic rules",
        "",
        "1. Breadth bull: at least 80% of the executable market has positive completed ret20.",
        "2. Rotation state: PIT industry is internally positive but remains in the lower half of industries.",
        "3. Holder-pressure release: first causal close above the prior 120-session ceiling, with demand confirmation.",
        "4. Controlled launch: the prior 120-session range is at most 60% and the breakout bar is +2% to +7%.",
        "",
        "The entry is the first legal next open, target is +15%, time stop is H15, "
        "and round-trip cost is 40 bp. There is no failure stop.",
        "",
        "## Annual capacity-accepted evidence",
        "",
        "| Year | Trades | Mean net | Median net | Win | Mean hold |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        metrics = result["annual"][str(year)]
        if metrics["completed_trades"]:
            lines.append(
                f"| {year} | {metrics['completed_trades']} | {metrics['mean_net']:.2%} | "
                f"{metrics['median_net']:.2%} | {metrics['win_rate']:.2%} | "
                f"{metrics['mean_holding_sessions']:.2f} |"
            )
        else:
            lines.append(f"| {year} | 0 | — | — | — | — |")
    lines += [
        "",
        "## Robustness and complementarity",
        "",
        f"- Signal-date equal mean: {result['concentration']['signal_date_equal_mean_net']:.3%}.",
        f"- Mean excluding best five signal dates: "
        f"{result['concentration']['mean_excluding_best_five_signal_dates']:.3%}.",
        f"- Top-five signal-date share of positive PnL: "
        f"{result['concentration']['top_five_signal_date_positive_pnl_share']:.2%}.",
        f"- Same-symbol/same-entry-date overlap with preserved V24: "
        f"{result['v24_overlap']['same_symbol_entry_date_count']} trades; "
        f"{result['v24_overlap']['v26_unique_entry_share']:.2%} of V26 entries are distinct.",
        "",
        "## Evidence governance",
        "",
        "All 2014–2023 outcomes belong to iterative Development. The 2019–2023 chronology "
        "is an observed robustness check, not pristine sealed validation. Years with no "
        "Breadth80 signal are cash years, not imputed trades. No signal or feature after "
        "2023 is used; later daily rows are used only when needed to close a pre-2024 trade.",
        "",
        f"No-post-signal chart audit: `{BLIND_PDF.relative_to(ROOT)}`",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp_v26"):
        frame[column] = pd.to_datetime(frame[column])
    outcomes, reproduction_audit = reproduce_outcomes(frame)
    if any(reproduction_audit.values()):
        raise ResearchError(f"outcome reproduction failed: {reproduction_audit}")
    features = frame[
        [
            "event_id",
            "admission_lane",
            "causal_industry",
            "market_positive_ret20_share",
            "industry_positive_ret20_share",
            "industry_ret20_percentile",
            "stock_minus_industry_ret20",
            "turnover_expansion",
            "prior120_range",
            "step_return",
        ]
    ]
    trades = outcomes.loc[outcomes.profile.eq(PROFILE)].merge(
        features, on="event_id", how="left", validate="one_to_one"
    )
    symbols = trades.loc[trades.status.eq("COMPLETED"), "symbol"].astype(str).unique().tolist()
    daily = v1.load_trade_daily(symbols)
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, _nav, portfolio = v1.replay_portfolio(trades, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    full = _summary(accepted)
    annual = {
        str(year): _summary(accepted.loc[accepted.signal_date.dt.year.eq(year)])
        for year in YEARS
    }
    board = {name: _summary(part) for name, part in accepted.groupby("sleeve", sort=True)}
    concentration = v1.concentration_metrics(accepted)
    concentration["signal_date_equal_mean_net"] = float(
        accepted.groupby(accepted.signal_date.dt.normalize()).net_return.mean().mean()
    )
    concentration["top_symbol_trade_share"] = float(
        accepted.symbol.value_counts(normalize=True).iloc[0]
    )
    concentration["top_industry_trade_share"] = float(
        accepted.causal_industry.value_counts(normalize=True).iloc[0]
    )
    active_later = [
        annual[str(year)] for year in range(2019, 2024) if annual[str(year)]["completed_trades"]
    ]
    gate = {
        "capacity_accepted_completed_trades_gt_500": len(accepted) > 500,
        "average_completed_trades_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_gt_5pct": full["mean_net"] is not None and full["mean_net"] > 0.05,
        "mean_holding_lt_15": (
            full["mean_holding_sessions"] is not None
            and full["mean_holding_sessions"] < 15
        ),
        "all_active_2019_2023_years_positive": bool(active_later)
        and all(value["mean_net"] > 0 for value in active_later),
        "at_least_three_active_later_years": len(active_later) >= 3,
        "mean_excluding_best_five_signal_dates_positive": (
            concentration["mean_excluding_best_five_signal_dates"] > 0
        ),
        "top_five_signal_date_positive_pnl_share_le_25pct": (
            concentration["top_five_signal_date_positive_pnl_share"] <= 0.25
        ),
        "both_boards_positive_mean": set(board) == {"MAIN", "CHINEXT"}
        and all(value["mean_net"] > 0 for value in board.values()),
    }
    audit = {
        **reproduction_audit,
        **candidate_audit(frame),
        "signal_or_feature_after_2023_count": int(
            frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
        ),
        "signal_bar_fill_count": int(
            (accepted.entry_date <= accepted.signal_date).sum()
        ),
        "t1_same_day_exit_count": int(
            (accepted.exit_cal_idx <= accepted.entry_cal_idx).sum()
        ),
        "negative_cash_count": portfolio["negative_cash_count"],
        "max_k_violation_count": portfolio["max_k_violation_count"],
    }
    if any(audit.values()):
        raise ResearchError(f"final audit failed: {audit}")
    result = {
        "experiment": EXPERIMENT,
        "contract_sha256": freeze["contract_sha256"],
        "spec_sha256": freeze["spec_sha256"],
        "selected_rule": "BREADTH80 + NONCROWDED_INDUSTRY + RANGE60 + STEP_2_7",
        "profile": PROFILE,
        "source_candidates": len(frame),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "average_trades_per_year": len(accepted) / 10,
        "full_2014_2023": full,
        "annual": annual,
        "board": board,
        "portfolio": portfolio,
        "concentration": concentration,
        "v24_overlap": overlap_with_v24(accepted),
        "gate": gate,
        "audit": audit,
        "repository_2024_plus_rows_used_for_signal_or_feature": 0,
        "post_2023_rows_used_only_for_pre_2024_trade_resolution": True,
        "verdict": (
            "BULL_BREADTH80_NONCROWDED_CEILING_RELAY_TARGET_MET"
            if all(gate.values())
            else "BULL_BREADTH80_NONCROWDED_CEILING_RELAY_FAILS_TARGET"
        ),
        "hashes": {
            "source": v1.sha256(SOURCE),
            "candidates": v1.sha256(CANDIDATES),
            "outcomes": v1.sha256(OUTCOMES),
            "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED),
            "nav": v1.sha256(NAV),
            "blind_pdf": v1.sha256(BLIND_PDF),
        },
    }
    v1.write_json(RESULT, result)
    render_report(result)
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
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
