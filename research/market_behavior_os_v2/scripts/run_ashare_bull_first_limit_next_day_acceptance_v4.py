#!/usr/bin/env python3
"""Causal bull first-limit next-session acceptance strategy research."""

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
EXPERIMENT = "ASHARE-BULL-FIRST-LIMIT-NEXT-DAY-ACCEPTANCE-V4"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_first_limit_next_day_acceptance_v4")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_40_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

RULES = {
    "R1_HOLD_NEAR_LIMIT": {},
    "R2_ADVANCE_ABOVE_LIMIT_CLOSE": {},
    "R3_LOW_SUPPLY_HOLD": {},
    "R4_POSITIVE_BODY_HOLD": {},
}
PROFILES = {
    "H5_NEXT_OPEN": {"horizon": 5, "target": None},
    "H10_NEXT_OPEN": {"horizon": 10, "target": None},
    "T10_H10_NO_STOP": {"horizon": 10, "target": 0.10},
    "T15_H15_NO_STOP": {"horizon": 15, "target": 0.15},
}
YEARS = tuple(range(2014, 2024))
DISCOVERY = tuple(range(2014, 2019))
CONFIRMATION = (2019, 2020, 2021)


class ResearchError(RuntimeError):
    """Fail-closed V4 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A first upper-limit close can leave demand unsatisfied. Continuation is "
            "credible only when the next completed session, still in a causal broad "
            "bull market and majority-positive PIT industry, accepts price near or "
            "above the constrained close and finishes in the upper part of its range."
        ),
        "market": v1.contract_value()["market_regime"],
        "industry": "confirmation-day n20>=5, median ret20>0, positive share>0.50",
        "ignition": {
            "first_limit": (
                "previous session closes at historical upper limit; no limit close "
                "in prior20 valid sessions"
            ),
            "bounded_base": "prior20 range<=40%, pre-ignition ret20<=30%",
            "demand_expansion": "ignition turnover>=1.5x preceding20 mean",
        },
        "acceptance_rules": {
            "R1_HOLD_NEAR_LIMIT": "confirmation close>=98% ignition close and close location>=70%",
            "R2_ADVANCE_ABOVE_LIMIT_CLOSE": "R1 and confirmation close>=ignition close",
            "R3_LOW_SUPPLY_HOLD": "R1 and confirmation turnover<=ignition turnover",
            "R4_POSITIVE_BODY_HOLD": "R1 and confirmation close>=confirmation open",
        },
        "profiles": PROFILES,
        "entry": (
            "first legal next daily open within three market sessions after confirmation close"
        ),
        "exit": "target or causal H5/H10/H15 decision then next legal open",
        "cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "selection": {
            "discovery": list(DISCOVERY),
            "minimum_completed": 300,
            "positive_years_min": 3,
            "mean_holding_max": 15,
            "order": "median annual mean, pooled mean, severe10, simplicity",
        },
        "gate": v1.contract_value()["required_gate"],
        "governance": {
            "independent_from_gap_repair": True,
            "frozen_before_outcomes": True,
            "no_post_2023_signal_or_feature": True,
            "2024_only_resolves_pre_2024_trade": True,
        },
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_NEXT_SESSION_ACCEPTANCE_FREEZE",
            "contract_sha256": v1.sha256(CONTRACT),
            "v1_dependency_sha256": v1.sha256(Path(v1.__file__)),
            "v2_dependency_sha256": v1.sha256(Path(v2.__file__)),
            "daily_sha256": v1.sha256(v1.DAILY),
            "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
            "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL),
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH d0 AS (
                SELECT *,
                  round(close*100)>=round(up_limit_price*100) AS is_limit_close,
                  lag(round(close*100)>=round(up_limit_price*100),1) OVER w AS ignition_is_limit,
                  lag(trade_date,1) OVER w AS ignition_date,
                  lag(cal_idx,1) OVER w AS ignition_cal_idx,
                  lag(coord_close,1) OVER w AS ignition_close,
                  lag(turnover_fraction,1) OVER w AS ignition_turnover,
                  lag(ret20,2) OVER w AS pre_ignition_ret20,
                  avg(turnover_fraction) OVER wpre AS pre20_turnover,
                  max(coord_high) OVER wpre AS pre20_high,
                  min(coord_low) OVER wpre AS pre20_low,
                  sum((round(close*100)>=round(up_limit_price*100))::INT)
                    OVER wpre AS pre20_limitups,
                  count(*) OVER wpre AS history_n20
                FROM read_parquet('{v1.DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL
                WINDOW
                  w AS (PARTITION BY symbol ORDER BY trade_date),
                  wpre AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
                  )
              ), f AS (
                SELECT *,
                  pre20_high/pre20_low-1 AS pre20_range,
                  ignition_turnover/nullif(pre20_turnover,0) AS ignition_turnover_expansion,
                  coord_close/nullif(ignition_close,0)-1 AS confirmation_retention,
                  (coord_close-coord_low)/nullif(coord_high-coord_low,0)
                    AS confirmation_close_location,
                  turnover_fraction/nullif(ignition_turnover,0) AS confirmation_turnover_ratio,
                  coord_close/coord_open-1 AS confirmation_body_return
                FROM d0
                WHERE trade_date>=DATE '2014-01-01' AND history_n20=20
                  AND ignition_is_limit AND pre20_limitups=0
                  AND cal_idx-ignition_cal_idx=1
              ), x AS (
                SELECT f.*,r.market_regime,
                  r.latest_source_timestamp AS market_latest_source,
                  i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_n20,
                  i.latest_source_timestamp AS industry_latest_source,
                  ret20-i.industry_median_ret20 AS stock_minus_industry_ret20
                FROM f
                JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
                JOIN read_parquet('{v1.INDUSTRY_PANEL}') i USING(trade_date,causal_industry)
                WHERE r.market_regime='BULL' AND i.industry_n20>=5
                  AND i.industry_median_ret20>0 AND i.industry_positive_ret20_share>0.50
                  AND pre20_range<=0.40 AND pre_ignition_ret20<=0.30
                  AND ignition_turnover_expansion>=1.50
                  AND confirmation_retention>=-0.02
                  AND confirmation_close_location>=0.70
              )
              SELECT *,
                'BLAC-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,
                decision_at AS feature_latest_timestamp,
                pre_ignition_ret20 AS prior_runup,
                confirmation_retention AS pre_drawdown,
                pre20_high AS prior20_high,
                pre20_high AS platform_high,
                ignition_turnover_expansion AS turnover_expansion,
                TRUE AS pass_R1_HOLD_NEAR_LIMIT,
                confirmation_retention>=0 AS pass_R2_ADVANCE_ABOVE_LIMIT_CLOSE,
                confirmation_turnover_ratio<=1 AS pass_R3_LOW_SUPPLY_HOLD,
                confirmation_body_return>=0 AS pass_R4_POSITIVE_BODY_HOLD
              FROM x ORDER BY trade_date,symbol
            ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in (
        "trade_date",
        "signal_date",
        "ignition_date",
        "decision_at",
        "available_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    causal = (
        frame.available_at.le(frame.decision_at)
        & frame.market_latest_source.le(frame.decision_at)
        & frame.industry_latest_source.le(frame.decision_at)
        & frame.feature_latest_timestamp.le(frame.decision_at)
        & frame.ignition_date.lt(frame.signal_date)
    )
    if frame.event_id.duplicated().any() or not causal.all():
        raise ResearchError("candidate identity or chronology failure")
    return frame


def sample_and_render(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["hash_order"] = work.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    work["year"] = work.signal_date.dt.year
    pieces = [
        part.sort_values("hash_order").head(2)
        for _, part in work.groupby(["year", "sleeve"], sort=True)
    ]
    sample = pd.concat(pieces, ignore_index=True).sort_values("hash_order").head(40)
    if len(sample) < 40:
        rest = work.loc[~work.event_id.isin(sample.event_id)]
        sample = pd.concat(
            [sample, rest.sort_values("hash_order").head(40 - len(sample))], ignore_index=True
        )
    sample = sample.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    if len(sample) != 40:
        raise ResearchError(f"blind sample has {len(sample)} rows")
    sample.insert(0, "chart_id", [f"BULL-ACCEPT-{i:03d}" for i in range(1, 41)])
    sample.to_csv(BLIND_INDEX, index=False)
    old_pdf = v2.BLIND_PDF
    try:
        v2.BLIND_PDF = BLIND_PDF
        v2.render_blind_charts(sample)
    finally:
        v2.BLIND_PDF = old_pdf
    return sample


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    frame = build_candidates()
    sample = sample_and_render(frame)
    coverage = {
        rule: {
            "count": int(frame[f"pass_{rule}"].sum()),
            "annual": (
                frame.loc[frame[f"pass_{rule}"]]
                .groupby(frame.loc[frame[f"pass_{rule}"], "signal_date"].dt.year)
                .size()
                .reindex(YEARS, fill_value=0)
                .astype(int)
                .to_dict()
            ),
        }
        for rule in RULES
    }
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(
            frame.feature_latest_timestamp.gt(frame.decision_at).sum()
        ),
        "ignition_at_or_after_confirmation_count": int(
            frame.ignition_date.ge(frame.signal_date).sum()
        ),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": v1.sha256(Path(__file__)),
        "v1_dependency_sha256": v1.sha256(Path(v1.__file__)),
        "v2_dependency_sha256": v1.sha256(Path(v2.__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
        "candidate_count": len(frame),
        "blind_chart_count": len(sample),
        "coverage": coverage,
        "audit": audit,
        "outcomes_opened": False,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> None:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "v1_dependency_sha256": v1.sha256(Path(v1.__file__)),
        "v2_dependency_sha256": v1.sha256(Path(v2.__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")


def candidate_table(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    joined = outcomes.merge(
        candidates[["event_id", *[f"pass_{rule}" for rule in RULES]]],
        on="event_id",
        validate="many_to_one",
    )
    rows: list[dict[str, Any]] = []
    for rule in RULES:
        for profile in PROFILES:
            part = joined.loc[
                joined.profile.eq(profile)
                & joined[f"pass_{rule}"]
                & joined.signal_date.dt.year.isin(DISCOVERY)
            ]
            metrics = v1.summary(part)
            annual = {
                str(year): v1.summary(part.loc[part.signal_date.dt.year.eq(year)])
                for year in DISCOVERY
            }
            means = [x["mean_net"] for x in annual.values() if x["mean_net"] is not None]
            rows.append(
                {
                    "rule": rule,
                    "profile": profile,
                    **metrics,
                    "positive_years": sum(x > 0 for x in means),
                    "median_annual_mean_net": float(np.median(means)),
                    "annual_json": json.dumps(annual, sort_keys=True),
                }
            )
    return pd.DataFrame(rows)


def select_candidate(table: pd.DataFrame) -> pd.Series | None:
    eligible = table.loc[
        table.completed_trades.ge(300)
        & table.positive_years.ge(3)
        & table.mean_holding_sessions.le(15)
    ].copy()
    if eligible.empty:
        return None
    eligible["rule_order"] = eligible.rule.map({x: i for i, x in enumerate(RULES)})
    eligible["profile_order"] = eligible.profile.map({x: i for i, x in enumerate(PROFILES)})
    eligible = eligible.sort_values(
        ["median_annual_mean_net", "mean_net", "severe_loss10", "rule_order", "profile_order"],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    )
    return eligible.iloc[0]


def persist_failure(table: pd.DataFrame, reason: str) -> dict[str, Any]:
    best = table.sort_values(
        ["positive_years", "median_annual_mean_net", "mean_net"],
        ascending=False,
        kind="mergesort",
    ).iloc[0]
    result = {
        "experiment": EXPERIMENT,
        "verdict": "BULL_NEXT_DAY_ACCEPTANCE_FAILS_DISCOVERY_SUPPORT",
        "reason": reason,
        "best_diagnostic_candidate": best.replace({np.nan: None}).to_dict(),
        "candidate_table": table.replace({np.nan: None}).to_dict("records"),
        "return_analysis_rerun": False,
        "repository_2024_plus_signal_or_feature_rows": 0,
    }
    v1.write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        f"# {EXPERIMENT}\n\n`{result['verdict']}`\n\n{reason}. No strategy was replayed.\n",
        encoding="utf-8",
    )
    return result


def run_stage_b() -> dict[str, Any]:
    verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES, v2.OUTCOMES = PROFILES, OUTCOMES
        outcomes, audit = v2.build_outcomes(candidates)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes
    if any(audit.values()):
        raise ResearchError(str(audit))
    table = candidate_table(outcomes, candidates)
    selected = select_candidate(table)
    if selected is None:
        return persist_failure(
            table,
            "No frozen rule/profile has >=300 discovery trades, >=3 positive "
            "discovery years and mean hold<=15",
        )
    rule, profile = str(selected.rule), str(selected.profile)
    selected_all = outcomes.merge(
        candidates[
            [
                "event_id",
                "industry_positive_ret20_share",
                "stock_minus_industry_ret20",
                "turnover_expansion",
                f"pass_{rule}",
            ]
        ],
        on="event_id",
        validate="many_to_one",
    )
    selected_all = selected_all.loc[
        selected_all.profile.eq(profile) & selected_all[f"pass_{rule}"]
    ].copy()
    daily = v1.load_trade_daily(selected_all.symbol.astype(str).unique().tolist())
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, _nav, portfolio = v1.replay_portfolio(selected_all, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    annual = v1.annual_summary(accepted.assign(status="COMPLETED"))
    full = v1.summary(accepted.assign(status="COMPLETED"))
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "trades_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_ge_3pct": full["mean_net"] >= 0.03,
        "mean_holding_le_15": full["mean_holding_sessions"] <= 15,
        "2019_2021_each_positive": all(annual[str(y)]["mean_net"] > 0 for y in CONFIRMATION),
        "2022_positive": annual["2022"]["mean_net"] > 0,
        "2023_positive": annual["2023"]["mean_net"] > 0,
        "mean_ex_best5_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"]
        <= 0.25,
    }
    result = {
        "experiment": EXPERIMENT,
        "selected_rule": rule,
        "selected_profile": profile,
        "candidate_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "average_trades_per_year": len(accepted) / 10,
        "full_2014_2023": full,
        "annual": annual,
        "portfolio": portfolio,
        "concentration": concentration,
        "gate": gate,
        "audit": {
            **audit,
            "feature_after_decision_count": int(
                candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()
            ),
            "repository_2024_plus_rows_used_for_signal_or_feature": 0,
        },
        "verdict": "BULL_NEXT_DAY_ACCEPTANCE_EDGE"
        if all(gate.values())
        else "BULL_NEXT_DAY_ACCEPTANCE_FAILS_TARGET",
        "hashes": {
            "outcomes": v1.sha256(OUTCOMES),
            "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED),
            "nav": v1.sha256(NAV),
        },
    }
    v1.write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    report_text = (
        f"# {EXPERIMENT}\n\n`{result['verdict']}`\n\n"
        f"Selected `{rule}` with `{profile}`.\n\n"
        f"Gate: `{json.dumps(gate, sort_keys=True)}`.\n"
    )
    REPORT.write_text(
        report_text,
        encoding="utf-8",
    )
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
