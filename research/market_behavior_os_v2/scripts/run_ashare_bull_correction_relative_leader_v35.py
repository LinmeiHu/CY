#!/usr/bin/env python3
"""Bull-market broad-correction relative-leader research lane."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_bull_panic_relative_strength_survivor_v34 as v34
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1


ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-CORRECTION-RELATIVE-LEADER-V35"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_correction_relative_leader_v35")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
PROFILE_FREEZE = OS / f"artifacts/{EXPERIMENT}_profile_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
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
DEV_YEARS = tuple(range(2014, 2021))
FORWARD_YEARS = (2021, 2022, 2023)
PROFILES = v34.PROFILES


class ResearchError(RuntimeError):
    pass


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "stage": "A_OUTCOME_BLIND_CONTRACT",
        "economic_hypothesis": (
            "During a causally known bull market, a broad correction can force "
            "liquidity-motivated selling without ending the trend. A previously "
            "strong stock in a healthy industry that loses materially less than "
            "the market, closes high in its range, and trades normal-or-higher "
            "turnover reveals relative demand. Entry after the completed correction "
            "seeks resumption as forced supply normalizes."
        ),
        "four_binding_conditions": {
            "PRIOR_PIT_BULL": "immediately prior completed market state is BULL",
            "BROAD_CORRECTION": (
                "signal-day eligible-universe median return <= -1.0% and positive-stock share <= 40%"
            ),
            "HEALTHY_RESILIENT_INDUSTRY": (
                "prior PIT industry median ret20 > 0, positive-ret20 share > 50%, n20 >= 5; "
                "signal-day industry median exceeds market median by >= 0.3 percentage point"
            ),
            "RELATIVE_LEADER_DEMAND": (
                "pre-signal completed ret20 in [+5%,+50%]; signal return >= max(-1.0%, "
                "market median +2.0 percentage points) and <= +8%; close location >=60%; "
                "turnover >=80% of prior20 mean"
            ),
        },
        "decision_clock": "completed signal daily close",
        "entry": "first legal daily open after signal within three market sessions",
        "profiles": PROFILES,
        "failure_exit": "after T+1, first completed close below signal-day low; next legal open",
        "cost": 0.004,
        "development_gate": {
            "years": list(DEV_YEARS),
            "minimum_completed": 400,
            "minimum_positive_years": 5,
            "minimum_mean_net": 0.03,
            "maximum_mean_holding_sessions": 15,
        },
        "forward": {
            "years": list(FORWARD_YEARS),
            "opened_only_after_profile_freeze": True,
            "2024_q1_use": "late-2023 execution resolution only",
        },
        "portfolio": v1.contract_value()["portfolio"],
        "outcomes_opened": False,
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_CONTRACT",
            "contract_sha256": v1.sha256(CONTRACT),
            "sources": {
                "daily": v1.sha256(v1.DAILY),
                "regime": v1.sha256(v1.SOURCE_REGIME),
                "industry": v1.sha256(v1.INDUSTRY_PANEL),
            },
            "execution_dependency_sha256": v1.sha256(Path(v1.__file__)),
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"""COPY (
        WITH eligible AS (
          SELECT * FROM read_parquet('{v1.DAILY}')
          WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
            AND hard_valid AND history_valid AND current_valid
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND current_day_data_tradable AND market_rule_valid AND trade_status=1
            AND NOT is_st AND causal_industry IS NOT NULL AND industry_valid
        ),
        market_day AS (
          SELECT trade_date,median(step_return) AS market_step_median,
            avg((step_return>0)::INTEGER) AS market_positive_step_share
          FROM eligible GROUP BY trade_date
        ),
        industry_day AS (
          SELECT trade_date,causal_industry,median(step_return) AS industry_step_median,
            avg((step_return>0)::INTEGER) AS industry_positive_step_share,
            count(*) AS industry_step_n
          FROM eligible GROUP BY trade_date,causal_industry
        ),
        regime_prev AS (
          SELECT trade_date AS state_date,lead(trade_date) OVER(ORDER BY trade_date) AS signal_date,
            market_regime,market_median_ret20,market_positive_ret20_share,
            latest_source_timestamp AS market_latest_source
          FROM read_parquet('{v1.SOURCE_REGIME}')
        ),
        d0 AS (
          SELECT d.*,lag(coord_close) OVER w AS prev_coord_close,
            lag(coord_close,20) OVER w AS lag20_coord_close,
            avg(turnover_fraction) OVER w20 AS prior20_turnover,
            count(*) OVER w20 AS prior20_n
          FROM eligible d
          WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
            w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
        ),
        f AS (
          SELECT d0.*,prev_coord_close/NULLIF(lag20_coord_close,0)-1 AS prior_completed_ret20,
            turnover_fraction/NULLIF(prior20_turnover,0) AS turnover_expansion,
            (coord_close-greatest(coord_open,coord_low))/NULLIF(coord_high-coord_low,0) AS close_location
          FROM d0
        ),
        joined AS (
          SELECT f.*,rp.state_date,rp.market_regime,rp.market_median_ret20,
            rp.market_positive_ret20_share,rp.market_latest_source,
            i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_n20,
            i.industry_ret20_percentile,i.latest_source_timestamp AS industry_latest_source,
            m.market_step_median,m.market_positive_step_share,
            id.industry_step_median,id.industry_positive_step_share,id.industry_step_n
          FROM f JOIN market_day m USING(trade_date)
          JOIN industry_day id USING(trade_date,causal_industry)
          JOIN regime_prev rp ON rp.signal_date=f.trade_date
          JOIN read_parquet('{v1.INDUSTRY_PANEL}') i
            ON i.trade_date=rp.state_date AND i.causal_industry=f.causal_industry
        )
        SELECT *,'CORR35-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
          trade_date AS signal_date,decision_at AS feature_latest_timestamp,
          coord_low AS structural_low,
          prior_completed_ret20-industry_median_ret20 AS stock_minus_industry_ret20,
          step_return-market_step_median AS stock_minus_market_step,
          industry_step_median-market_step_median AS industry_minus_market_step,
          'BULL_CORRECTION_RELATIVE_LEADER' AS admission_lane
        FROM joined
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
          AND prior20_n=20 AND market_regime='BULL'
          AND industry_n20>=5 AND industry_median_ret20>0
          AND industry_positive_ret20_share>0.50
          AND market_step_median<=-0.010 AND market_positive_step_share<=0.40
          AND industry_step_median-market_step_median>=0.003
          AND prior_completed_ret20 BETWEEN 0.05 AND 0.50
          AND step_return>=greatest(-0.010,market_step_median+0.020)
          AND step_return<=0.08 AND close_location>=0.60 AND turnover_expansion>=0.80
        ORDER BY trade_date,symbol
        ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)"""
    )
    con.close()
    x = v1.read_parquet_duckdb(CANDIDATES)
    for c in (
        "trade_date", "state_date", "signal_date", "available_at", "decision_at",
        "market_latest_source", "industry_latest_source", "feature_latest_timestamp",
    ):
        x[c] = pd.to_datetime(x[c])
    return x


def audit(x: pd.DataFrame) -> dict[str, int | bool]:
    latest = x[["available_at", "feature_latest_timestamp"]].max(axis=1)
    return {
        "duplicate_event_count": int(x.event_id.duplicated().sum()),
        "current_feature_after_decision_count": int(latest.gt(x.decision_at).sum()),
        "prior_market_not_before_signal_count": int(x.market_latest_source.ge(x.decision_at).sum()),
        "prior_industry_not_before_signal_count": int(x.industry_latest_source.ge(x.decision_at).sum()),
        "correction_definition_violation_count": int(
            (x.market_step_median.gt(-0.010) | x.market_positive_step_share.gt(0.40)).sum()
        ),
        "candidate_after_2023_count": int(x.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "outcomes_opened": False,
    }


def blind_sample(x: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    z = x.copy()
    z["year"] = z.signal_date.dt.year
    z["hash_order"] = z.event_id.map(lambda s: hashlib.sha256(str(s).encode()).hexdigest())
    sample = pd.concat([g.sort_values("hash_order").head(3) for _, g in z.groupby("year")])
    if len(sample) < n:
        sample = pd.concat([
            sample,
            z.loc[~z.event_id.isin(sample.event_id)].sort_values("hash_order").head(n-len(sample)),
        ])
    sample = sample.sort_values(["signal_date", "symbol"]).head(n).reset_index(drop=True)
    sample.insert(0, "chart_id", [f"V35-BLIND-{i:03d}" for i in range(1, len(sample)+1)])
    sample.to_csv(BLIND_INDEX, index=False)
    return sample


def render_blind(sample: pd.DataFrame) -> None:
    old = (v34.BLIND_DIR, v34.BLIND_PDF)
    try:
        v34.BLIND_DIR, v34.BLIND_PDF = BLIND_DIR, BLIND_PDF
        v34.render_blind(sample)
    finally:
        v34.BLIND_DIR, v34.BLIND_PDF = old


def capacity_upper_bound(x: pd.DataFrame) -> tuple[int, dict[str, int]]:
    grouped = x.groupby(["signal_date", "sleeve"]).size().clip(upper=10)
    total = int(grouped.sum())
    annual = grouped.groupby(lambda key: pd.Timestamp(key[0]).year).sum()
    return total, annual.reindex(YEARS, fill_value=0).astype(int).to_dict()


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    x = build_candidates()
    checks = audit(x)
    if any(value for key, value in checks.items() if key != "outcomes_opened"):
        raise ResearchError(str(checks))
    sample = blind_sample(x)
    render_blind(sample)
    cap, annual_cap = capacity_upper_bound(x)
    result = {
        "experiment": EXPERIMENT, **hashes,
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
        "candidate_count": len(x),
        "annual_candidate_counts": x.groupby(x.signal_date.dt.year).size().reindex(YEARS, fill_value=0).astype(int).to_dict(),
        "unique_signal_dates": int(x.signal_date.nunique()),
        "maximum_signals_on_one_date": int(x.groupby("signal_date").size().max()),
        "mechanical_k10_capacity_upper_bound": cap,
        "annual_mechanical_capacity_upper_bound": annual_cap,
        "blind_chart_count": len(sample),
        "audit": checks,
    }
    v1.write_json(FREEZE, result)
    return result


def verify_stage_a() -> dict[str, Any]:
    frozen = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {k: [frozen.get(k), v] for k, v in expected.items() if frozen.get(k) != v}
    if drift:
        raise ResearchError(str(drift))
    return frozen


def run_stage_b() -> dict[str, Any]:
    stage_a = verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for c in ("signal_date", "decision_at"):
        candidates[c] = pd.to_datetime(candidates[c])
    dev = candidates[candidates.signal_date.dt.year.isin(DEV_YEARS)]
    outcomes, dev_audit = v34.build_outcomes(dev, "2021-03-31", DEV_OUTCOMES)
    table = v34.profile_table(outcomes)
    v1.write_parquet(table, PROFILE_TABLE)
    eligible = table[
        table.completed_trades.ge(400) & table.positive_years.ge(5)
        & table.mean_net.ge(0.03) & table.mean_holding_sessions.le(15)
    ]
    if eligible.empty:
        result = {
            "experiment": EXPERIMENT,
            "verdict": "BULL_CORRECTION_RELATIVE_LEADER_DEVELOPMENT_FAILED",
            "stage_a": stage_a,
            "profile_table": table.replace({np.nan: None}).to_dict("records"),
            "development_audit": dev_audit,
            "forward_years_opened": False,
        }
        v1.write_json(RESULT, result)
        return result
    selected = eligible.sort_values(
        ["median_annual_mean_net", "mean_net", "severe_loss10", "mean_holding_sessions"],
        ascending=[False, False, True, True],
    ).iloc[0]
    profile = str(selected.profile)
    v1.write_json(PROFILE_FREEZE, {
        "experiment": EXPERIMENT, "selected_profile": profile,
        "development_outcomes_sha256": v1.sha256(DEV_OUTCOMES),
        "profile_table_sha256": v1.sha256(PROFILE_TABLE), "forward_opened": False,
    })
    fwd = candidates[candidates.signal_date.dt.year.isin(FORWARD_YEARS)]
    fwd_outcomes, fwd_audit = v34.build_outcomes(fwd, "2024-03-31", FORWARD_OUTCOMES)
    chosen = pd.concat([outcomes, fwd_outcomes]).loc[lambda z: z.profile.eq(profile)].merge(
        candidates[["event_id", "industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"]],
        on="event_id", validate="one_to_one",
    )
    daily = v34.load_daily(candidates.symbol.unique().tolist(), "2024-03-31")
    accepted, skipped, nav, portfolio_audit = v1.replay_portfolio(chosen, daily)
    v1.write_parquet(accepted, ACCEPTED); v1.write_parquet(skipped, SKIPPED); v1.write_parquet(nav, NAV)
    overall = v34.metrics(accepted.assign(status="COMPLETED"), PROFILES[profile]["target"])
    annual = {str(y): v34.metrics(accepted[accepted.signal_date.dt.year.eq(y)].assign(status="COMPLETED"), PROFILES[profile]["target"]) for y in YEARS}
    portfolio = v1.portfolio_metrics(nav, accepted)
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "completed_per_year_gt_50": len(accepted)/10 > 50,
        "mean_net_gt_5pct": overall["mean_net"] > 0.05,
        "mean_hold_lt_15": overall["mean_holding_sessions"] < 15,
        "forward_each_positive": all(annual[str(y)]["mean_net"] is not None and annual[str(y)]["mean_net"] > 0 for y in FORWARD_YEARS),
        "at_least_8_positive_years": sum(v["mean_net"] is not None and v["mean_net"] > 0 for v in annual.values()) >= 8,
        "max_date_share_le_10pct": concentration["top_signal_date_share"] <= 0.10,
    }
    result = {
        "experiment": EXPERIMENT,
        "verdict": "BULL_CORRECTION_RELATIVE_LEADER_EDGE" if all(gate.values()) else "BULL_CORRECTION_RELATIVE_LEADER_FAILED_FORWARD_OR_TARGET",
        "selected_profile": profile,
        "profile_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted), "capacity_skips": len(skipped),
        "completed_per_year": len(accepted)/10, "overall_2014_2023": overall,
        "annual": annual, "portfolio": portfolio, "concentration": concentration,
        "gate": gate,
        "audit": {**dev_audit, **{f"forward_{k}": v for k, v in fwd_audit.items()}, **portfolio_audit,
            "profile_selected_before_forward_open": True, "feature_after_decision_count": 0,
            "2024_rows_for_2023_resolution_only": True, "2024_signal_count": 0},
    }
    v1.write_json(RESULT, result)
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
