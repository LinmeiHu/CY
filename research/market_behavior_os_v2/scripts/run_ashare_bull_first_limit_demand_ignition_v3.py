#!/usr/bin/env python3
"""Causal bull/industry first-limit demand ignition strategy research."""

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
EXPERIMENT = "ASHARE-BULL-FIRST-LIMIT-DEMAND-IGNITION-V3"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_first_limit_demand_ignition_v3")
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
    "R1_RANGE30_RET20_TO15": {},
    "R2_RANGE40_RET30_TO15": {},
    "R3_RANGE30_RET20_TO20": {},
    "R4_RANGE40_RET30_TO20": {},
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
    """Fail-closed V3 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "In a causal broad BULL state with majority-positive PIT industry "
            "participation, the first upper-limit close in twenty completed "
            "sessions can reveal demand left unsatisfied by the price-limit "
            "constraint. A bounded prior range, limited prior appreciation and "
            "turnover expansion distinguish fresh ignition from late acceleration."
        ),
        "market": v1.contract_value()["market_regime"],
        "industry": "n20>=5, median ret20>0, positive-ret20 share>0.50",
        "signal": {
            "limit_close": "raw close rounded to cents >= historical upper limit",
            "first_in_20": "zero upper-limit closes in prior20 completed valid sessions",
            "prior_range": "prior20 coordinate high / prior20 coordinate low - 1",
            "prior_return": "completed prior-session ret20",
            "turnover": "signal turnover / prior20 mean turnover",
        },
        "rules": {
            "R1": "range<=30%, prior ret20<=20%, turnover>=1.5x",
            "R2": "range<=40%, prior ret20<=30%, turnover>=1.5x",
            "R3": "range<=30%, prior ret20<=20%, turnover>=2.0x",
            "R4": "range<=40%, prior ret20<=30%, turnover>=2.0x",
        },
        "profiles": PROFILES,
        "entry": "first legal next daily open within three market sessions",
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
            "not_downward_gap_repair": True,
            "rules_frozen_before_outcomes": True,
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
            "status": "OUTCOME_BLIND_FIRST_LIMIT_IGNITION_FREEZE",
            "contract_sha256": v1.sha256(CONTRACT),
            "v1_dependency_sha256": v1.sha256(Path(v1.__file__)),
            "v2_execution_dependency_sha256": v1.sha256(Path(v2.__file__)),
            "daily_sha256": v1.sha256(v1.DAILY),
            "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
            "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL),
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
                SELECT *,
                  lag(ret20) OVER w AS prior_ret20,
                  avg(turnover_fraction) OVER w20 AS prior20_turnover,
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w20 AS prior20_low,
                  sum((round(close*100)>=round(up_limit_price*100))::INT)
                    OVER w20 AS prior20_limitups,
                  count(*) OVER w20 AS history_n20
                FROM read_parquet('{v1.DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL
                WINDOW
                  w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                  )
              ), f AS (
                SELECT d0.*,
                  prior20_high/prior20_low-1 AS prior20_range,
                  turnover_fraction/nullif(prior20_turnover,0)
                    AS signal_turnover_expansion
                FROM d0
                WHERE trade_date>=DATE '2014-01-01' AND history_n20=20
              ), x AS (
                SELECT f.*,r.market_regime,
                  r.latest_source_timestamp AS market_latest_source,
                  i.industry_median_ret20,i.industry_positive_ret20_share,
                  i.industry_n20,i.latest_source_timestamp AS industry_latest_source,
                  ret20-i.industry_median_ret20 AS stock_minus_industry_ret20
                FROM f
                JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
                JOIN read_parquet('{v1.INDUSTRY_PANEL}') i
                  USING(trade_date,causal_industry)
                WHERE r.market_regime='BULL'
                  AND i.industry_n20>=5
                  AND i.industry_median_ret20>0
                  AND i.industry_positive_ret20_share>0.50
                  AND round(close*100)>=round(up_limit_price*100)
                  AND prior20_limitups=0
              )
              SELECT *,
                'BLIM-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,
                decision_at AS feature_latest_timestamp,
                prior_ret20 AS prior_runup,
                coord_close/prior20_high-1 AS pre_drawdown,
                prior20_high AS platform_high,
                signal_turnover_expansion AS turnover_expansion,
                prior20_range<=0.30 AND prior_ret20<=0.20
                  AND signal_turnover_expansion>=1.50
                  AS pass_R1_RANGE30_RET20_TO15,
                prior20_range<=0.40 AND prior_ret20<=0.30
                  AND signal_turnover_expansion>=1.50
                  AS pass_R2_RANGE40_RET30_TO15,
                prior20_range<=0.30 AND prior_ret20<=0.20
                  AND signal_turnover_expansion>=2.00
                  AS pass_R3_RANGE30_RET20_TO20,
                prior20_range<=0.40 AND prior_ret20<=0.30
                  AND signal_turnover_expansion>=2.00
                  AS pass_R4_RANGE40_RET30_TO20
              FROM x
              WHERE pass_R1_RANGE30_RET20_TO15 OR pass_R2_RANGE40_RET30_TO15
                OR pass_R3_RANGE30_RET20_TO20 OR pass_R4_RANGE40_RET30_TO20
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
    rows = [
        part.sort_values("hash_order").head(2)
        for _, part in work.groupby(["year", "sleeve"], sort=True)
    ]
    sample = pd.concat(rows, ignore_index=True).sort_values("hash_order").head(40)
    if len(sample) < 40:
        rest = work.loc[~work.event_id.isin(sample.event_id)]
        sample = pd.concat(
            [sample, rest.sort_values("hash_order").head(40 - len(sample))],
            ignore_index=True,
        )
    sample = sample.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    sample.insert(0, "chart_id", [f"BULL-LIMIT-{i:03d}" for i in range(1, 41)])
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
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
        "outcomes_opened": False,
    }
    if any(value for key, value in audit.items() if key != "outcomes_opened"):
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
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> None:
    freeze = json.loads(FREEZE.read_text())
    current = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "v1_dependency_sha256": v1.sha256(Path(v1.__file__)),
        "v2_dependency_sha256": v1.sha256(Path(v2.__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in current.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")


def build_outcomes(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES, v2.OUTCOMES = PROFILES, OUTCOMES
        return v2.build_outcomes(frame)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes


def select(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    old = (v2.RULES, v2.PROFILES, v2.DISCOVERY)
    try:
        v2.RULES, v2.PROFILES, v2.DISCOVERY = RULES, PROFILES, DISCOVERY
        return v2.select_candidate(outcomes, candidates)
    finally:
        v2.RULES, v2.PROFILES, v2.DISCOVERY = old


def run_stage_b() -> dict[str, Any]:
    verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    outcomes, audit = build_outcomes(candidates)
    if any(audit.values()):
        raise ResearchError(str(audit))
    table, selected = select(outcomes, candidates)
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
            "post_2023_signal_count": int(
                candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
            ),
            "repository_2024_plus_rows_used_for_signal_or_feature": 0,
        },
        "verdict": "BULL_FIRST_LIMIT_IGNITION_EDGE"
        if all(gate.values())
        else "BULL_FIRST_LIMIT_IGNITION_FAILS_TARGET",
        "hashes": {
            "outcomes": v1.sha256(OUTCOMES),
            "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED),
            "nav": v1.sha256(NAV),
        },
    }
    v1.write_json(RESULT, result)
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        f"Selected `{rule}` with `{profile}`.",
        "",
        "|Year|Trades|Mean net|Median net|Win|Mean hold|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year, values in annual.items():
        lines.append(
            f"|{year}|{values['completed_trades']}|{v1.pct(values['mean_net'])}|"
            f"{v1.pct(values['median_net'])}|{v1.pct(values['win_rate'])}|"
            f"{values['mean_holding_sessions']:.2f}|"
        )
    lines.extend(["", f"Gate: `{json.dumps(gate, sort_keys=True)}`.", ""])
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
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
