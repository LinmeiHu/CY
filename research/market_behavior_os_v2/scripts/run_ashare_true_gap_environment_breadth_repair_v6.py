#!/usr/bin/env python3
# ruff: noqa: E501
"""Develop one compact environment-confirmed below-gap repair strategy.

All stock signals, entries, exits, and outcomes come unchanged from the causal
V4R1 replay.  This lane adds only completed-close market/industry state known at
the signal close.  Development selects among three predeclared two-condition
rules, freezes one, and only then opens its 2022-2023 row-level diagnostic.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_deep_mature_decline_repair_v5 as v5,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-ENVIRONMENT-BREADTH-REPAIR-V6"
START_HEAD = "6657e8d74a"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_environment_breadth_repair_v6"
)
FEATURES = EXT_ROOT / "signal_environment_features.parquet"

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FEATURE_DICTIONARY = OS / f"experiments/{EXPERIMENT}_feature_dictionary.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
RULES = (
    "BOARD_RET5_POS_AND_INDUSTRY_RET5_POS",
    "BOARD_MA5_MAJORITY_AND_INDUSTRY_RET5_POS",
    "BOARD_MA5_BREADTH_RISING_AND_INDUSTRY_RET5_POS",
)
TARGET_SIGNALS_PER_YEAR = 50.0


class V6Error(RuntimeError):
    """Fail-closed V6 research error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def feature_dictionary_value() -> dict[str, Any]:
    common = {
        "decision_clock": "completed signal-date daily close",
        "latest_source_timestamp": "signal_time",
        "missing_policy": "FAIL_CLOSED",
        "universe": "hard-valid and tradable Main/ChiNext daily rows",
        "coordinate": "QD-010 corporate-action-consistent coord_close",
    }
    return {
        "experiment": EXPERIMENT,
        "features": {
            "board_median_ret5": {
                **common,
                "definition": "cross-sectional median causal 5-session coordinate return within board",
            },
            "board_breadth_above_ma5": {
                **common,
                "definition": "share of board members with completed close above exact valid 5-session MA",
            },
            "board_breadth_ma5_change5": {
                **common,
                "definition": "current board_breadth_above_ma5 minus its value exactly 5 market sessions earlier",
            },
            "industry_median_ret5": {
                **common,
                "definition": "cross-sectional median causal 5-session coordinate return in PIT causal industry",
                "minimum_members": 5,
            },
        },
    }


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A stock-level below-gap MA5 reclaim is more likely to persist when it "
            "occurs during expanding board participation and a positive same-industry "
            "five-session state, rather than as an isolated rebound against continuing "
            "systematic liquidation."
        ),
        "source_strategy": repair.EXPERIMENT,
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "candidate_rules": {
            RULES[0]: ["board_median_ret5 > 0", "industry_median_ret5 > 0"],
            RULES[1]: ["board_breadth_above_ma5 >= 0.50", "industry_median_ret5 > 0"],
            RULES[2]: ["board_breadth_ma5_change5 > 0", "industry_median_ret5 > 0"],
        },
        "selector": {
            "eligibility": {
                "selected_signals_per_year": [40.0, 80.0],
                "portfolio_mean_net_min": 0.03,
                "portfolio_median_net_positive": True,
                "portfolio_severe10_max": 0.15,
                "positive_calendar_years_min": 4,
            },
            "order": [
                "minimum absolute distance from 50 selected signals per year",
                "lower severe_loss10",
                "lexicographic rule name",
            ],
        },
        "unchanged_v4r1": {
            "signal_and_vap": True,
            "entry": True,
            "target": "entry + 0.80*(L-entry)",
            "failure_stop": "NONE",
            "time_stop": "H20",
            "round_trip_cost": 0.004,
            "portfolio": "50/50 Main/ChiNext; K20 per sleeve",
            "execution_and_corporate_actions": True,
        },
        "post_2023_scope": "pre-2024 trade-resolution tail only; no post-2023 signal or feature",
    }


def persist_contracts() -> dict[str, str]:
    write_json(FEATURE_DICTIONARY, feature_dictionary_value())
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "feature_dictionary_sha256": sha256(FEATURE_DICTIONARY),
            "status": "THREE_PREDECLARED_TWO_CONDITION_ENVIRONMENT_RULES",
            "development_selection_disclosure": (
                "The environment-repair mechanism and the three bounded natural rules "
                "were specified after Development-only direct analysis."
            ),
            "diagnostic_disclosure": "2022-2023 remains post-observation evidence.",
        },
    )
    return {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "feature_dictionary_sha256": sha256(FEATURE_DICTIONARY),
    }


def build_signal_registry() -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for label in repair.PERIODS:
        signals = pd.read_parquet(
            repair.paths(label)["signals"],
            columns=["gap_id", "symbol", "board", "signal_date", "signal_time"],
        )
        signals["period_label"] = label
        pieces.append(signals)
    result = pd.concat(pieces, ignore_index=True)
    result["signal_date"] = pd.to_datetime(result.signal_date)
    result["signal_time"] = pd.to_datetime(result.signal_time)
    if result.gap_id.duplicated().any() or result.signal_date.gt(pd.Timestamp("2023-12-31")).any():
        raise V6Error("signal registry identity/cutoff failure")
    return result


def build_environment_features() -> pd.DataFrame:
    EXT_ROOT.mkdir(parents=True, exist_ok=True)
    registry = build_signal_registry()
    con = duckdb.connect()
    con.register("signal_registry", registry)
    query = f"""
    COPY (
      WITH d0 AS (
        SELECT trade_date,cal_idx,symbol,sleeve,causal_industry,coord_close,invalid_step_cum,
          (hard_valid AND history_valid AND current_valid AND corporate_action_valid
           AND NOT corporate_action_blocking AND current_day_data_tradable) AS valid
        FROM read_parquet('{repair.source.DAILY}')
        WHERE trade_date BETWEEN DATE '2016-01-01' AND DATE '2023-12-31'
      ), w AS (
        SELECT *,
          lag(coord_close,5) OVER sy AS close5,
          lag(cal_idx,5) OVER sy AS idx5,
          lag(invalid_step_cum,5) OVER sy AS lin5,
          lag(valid,5) OVER sy AS valid5,
          lag(coord_close,20) OVER sy AS close20,
          lag(cal_idx,20) OVER sy AS idx20,
          lag(invalid_step_cum,20) OVER sy AS lin20,
          lag(valid,20) OVER sy AS valid20,
          lag(cal_idx,4) OVER sy AS idx4,
          lag(invalid_step_cum,4) OVER sy AS lin4,
          avg(coord_close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5,
          min(valid::INT) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) AS ma5_valid,
          lag(cal_idx,19) OVER sy AS idx19,
          lag(invalid_step_cum,19) OVER sy AS lin19,
          avg(coord_close) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20,
          min(valid::INT) OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS ma20_valid
        FROM d0
        WINDOW sy AS (PARTITION BY symbol ORDER BY trade_date)
      ), d AS (
        SELECT *,
          CASE WHEN valid AND valid5 AND idx5=cal_idx-5 AND lin5=invalid_step_cum AND close5>0
            THEN coord_close/close5-1 END AS ret5,
          CASE WHEN valid AND valid20 AND idx20=cal_idx-20 AND lin20=invalid_step_cum AND close20>0
            THEN coord_close/close20-1 END AS ret20,
          CASE WHEN valid AND ma5_valid=1 AND idx4=cal_idx-4 AND lin4=invalid_step_cum
            THEN coord_close>ma5 END AS above_ma5,
          CASE WHEN valid AND ma20_valid=1 AND idx19=cal_idx-19 AND lin19=invalid_step_cum
            THEN coord_close>ma20 END AS above_ma20
        FROM w
      ), b0 AS (
        SELECT trade_date,cal_idx,sleeve,
          median(ret5) AS board_median_ret5,
          median(ret20) AS board_median_ret20,
          avg(CASE WHEN ret5 IS NOT NULL THEN (ret5>0)::INT END) AS board_positive_ret5_share,
          avg(CASE WHEN above_ma5 IS NOT NULL THEN above_ma5::INT END) AS board_breadth_above_ma5,
          avg(CASE WHEN above_ma20 IS NOT NULL THEN above_ma20::INT END) AS board_breadth_above_ma20,
          count(ret5) AS board_n
        FROM d GROUP BY trade_date,cal_idx,sleeve
      ), b AS (
        SELECT *,
          CASE WHEN lag(cal_idx,5) OVER (PARTITION BY sleeve ORDER BY trade_date)=cal_idx-5
            THEN board_breadth_above_ma5
              - lag(board_breadth_above_ma5,5) OVER (PARTITION BY sleeve ORDER BY trade_date)
          END AS board_breadth_ma5_change5
        FROM b0
      ), i AS (
        SELECT trade_date,causal_industry,
          median(ret5) AS industry_median_ret5,
          median(ret20) AS industry_median_ret20,
          avg(CASE WHEN ret5 IS NOT NULL THEN (ret5>0)::INT END) AS industry_positive_ret5_share,
          avg(CASE WHEN above_ma5 IS NOT NULL THEN above_ma5::INT END) AS industry_breadth_above_ma5,
          count(ret5) AS industry_n
        FROM d WHERE causal_industry IS NOT NULL
        GROUP BY trade_date,causal_industry
      )
      SELECT s.period_label,s.gap_id,s.symbol,s.board,s.signal_date,s.signal_time,
        d.causal_industry,d.ret5 AS stock_ret5,d.ret20 AS stock_ret20,
        b.board_median_ret5,b.board_median_ret20,b.board_positive_ret5_share,
        b.board_breadth_above_ma5,b.board_breadth_above_ma20,b.board_breadth_ma5_change5,b.board_n,
        CASE WHEN i.industry_n>=5 THEN i.industry_median_ret5 END AS industry_median_ret5,
        CASE WHEN i.industry_n>=5 THEN i.industry_median_ret20 END AS industry_median_ret20,
        CASE WHEN i.industry_n>=5 THEN i.industry_positive_ret5_share END AS industry_positive_ret5_share,
        CASE WHEN i.industry_n>=5 THEN i.industry_breadth_above_ma5 END AS industry_breadth_above_ma5,
        i.industry_n,
        d.ret5-b.board_median_ret5 AS stock_minus_board_ret5,
        d.ret20-b.board_median_ret20 AS stock_minus_board_ret20,
        CASE WHEN i.industry_n>=5 THEN d.ret5-i.industry_median_ret5 END AS stock_minus_industry_ret5,
        CASE WHEN i.industry_n>=5 THEN d.ret20-i.industry_median_ret20 END AS stock_minus_industry_ret20,
        s.signal_time AS latest_source_timestamp
      FROM signal_registry s
      JOIN d ON d.symbol=s.symbol AND d.trade_date=s.signal_date
      JOIN b ON b.sleeve=s.board AND b.trade_date=s.signal_date
      LEFT JOIN i ON i.causal_industry=d.causal_industry AND i.trade_date=s.signal_date
      ORDER BY s.signal_time,s.symbol,s.gap_id
    ) TO '{FEATURES}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """
    con.execute(query)
    con.close()
    features = pd.read_parquet(FEATURES)
    for column in ("signal_date", "signal_time", "latest_source_timestamp"):
        features[column] = pd.to_datetime(features[column])
    if len(features) != len(registry) or features.gap_id.duplicated().any():
        raise V6Error("environment feature identity failure")
    if features.latest_source_timestamp.gt(features.signal_time).any():
        raise V6Error("environment feature uses post-signal timestamp")
    return features


def rule_mask(frame: pd.DataFrame, rule: str) -> pd.Series:
    if rule == RULES[0]:
        value = frame.board_median_ret5.gt(0) & frame.industry_median_ret5.gt(0)
    elif rule == RULES[1]:
        value = frame.board_breadth_above_ma5.ge(0.50) & frame.industry_median_ret5.gt(0)
    elif rule == RULES[2]:
        value = frame.board_breadth_ma5_change5.gt(0) & frame.industry_median_ret5.gt(0)
    else:
        raise V6Error(f"unknown environment rule: {rule}")
    return value.fillna(False)


def replay_rule(
    label: str,
    rule: str,
    years: tuple[int, ...],
    entries: pd.DataFrame,
    outcomes: pd.DataFrame,
    daily: pd.DataFrame,
    features: pd.DataFrame,
) -> dict[str, Any]:
    feature_rows = features.loc[features.period_label.eq(label)].copy()
    enriched = entries.merge(
        feature_rows.drop(columns=["symbol", "board", "signal_date", "signal_time"]),
        on="gap_id",
        how="left",
        validate="one_to_one",
    )
    selected = enriched.loc[
        enriched.signal_date.dt.year.isin(years) & rule_mask(enriched, rule)
    ].copy()
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    trades = outcomes.loc[outcomes.gap_id.isin(executable.gap_id)].copy()
    if len(trades) != len(executable) or set(trades.gap_id.astype(str)) != set(executable.gap_id.astype(str)):
        raise V6Error(f"{label} {rule} outcome conservation failure")
    if trades.empty:
        raise V6Error(f"{label} {rule} empty")
    max_exit = pd.Timestamp(trades.exit_date.max()).normalize()
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    root = EXT_ROOT / label.lower() / rule.lower()
    root.mkdir(parents=True, exist_ok=True)
    repair.v1.configure_external(root, max_exit)
    portfolio = repair.v1.run_portfolio(
        trades, daily.loc[daily.trade_date.le(max_exit)].copy(), replay_years
    )
    event = repair.v1.trade_metrics(trades)
    combined = portfolio["COMBINED"]
    yearly = trades.assign(_year=trades.entry_date.dt.year).groupby("_year").net_return.agg(
        trades="size", mean_net="mean", median_net="median"
    )
    dates = trades.entry_date.dt.normalize().value_counts()
    return {
        "rule": rule,
        "condition_count": 2,
        "selected_signals": len(selected),
        "selected_signals_per_year": len(selected) / len(years),
        "selected_by_year": {
            str(year): int(selected.signal_date.dt.year.eq(year).sum()) for year in years
        },
        "entry_status": selected.entry_status.value_counts().astype(int).to_dict(),
        "executable_entries": len(executable),
        "complete_outcomes": len(trades),
        "event_metrics": event,
        "event_yearly": {
            str(int(index)): {
                "trades": int(row.trades),
                "mean_net": float(row.mean_net),
                "median_net": float(row.median_net),
            }
            for index, row in yearly.iterrows()
        },
        "attack_date_equal_mean": float(
            trades.assign(_date=trades.entry_date.dt.normalize())
            .groupby("_date")
            .net_return.mean()
            .mean()
        ),
        "top_five_entry_date_event_share": float(dates.head(5).sum() / len(trades)),
        "portfolio": portfolio,
        "portfolio_mean_net": float(combined["mean_net"]),
        "portfolio_median_net": float(combined["median_net"]),
        "portfolio_severe10": float(combined["severe10"]),
        "positive_calendar_years": int(
            sum(float(combined["annual_returns"].get(str(year), 0.0)) > 0 for year in years)
        ),
        "maximum_exit_date_used": str(max_exit.date()),
        "post_signal_period_exit_count": int(
            trades.exit_date.gt(pd.Timestamp(f"{max(years)}-12-31")).sum()
        ),
        "post_2023_signal_count": int(selected.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "hashes": {
            "fixed_trades": sha256(root / "fixed_trades.parquet"),
            "portfolio_nav": sha256(root / "portfolio_nav.parquet"),
            "portfolio_accepted": sha256(root / "portfolio_accepted.parquet"),
        },
    }


def candidate_eligible(item: dict[str, Any]) -> bool:
    return bool(
        40 <= item["selected_signals_per_year"] <= 80
        and item["portfolio_mean_net"] >= 0.03
        and item["portfolio_median_net"] > 0
        and item["portfolio_severe10"] <= 0.15
        and item["positive_calendar_years"] >= 4
    )


def select_rule(candidates: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible = [item for item in candidates.values() if candidate_eligible(item)]
    if not eligible:
        raise V6Error("no Development environment rule passes selector")
    return sorted(
        eligible,
        key=lambda item: (
            abs(item["selected_signals_per_year"] - TARGET_SIGNALS_PER_YEAR),
            item["portfolio_severe10"],
            item["rule"],
        ),
    )[0]


def source_hashes() -> dict[str, str]:
    hashes = v5.source_hashes()
    hashes["pit_daily_compact"] = sha256(repair.source.DAILY)
    hashes["environment_features"] = sha256(FEATURES)
    return hashes


def run_development_and_freeze() -> dict[str, Any]:
    hashes = persist_contracts()
    features = build_environment_features()
    entries, outcomes, daily = v5.load_source("DEVELOPMENT")
    candidates = {
        rule: replay_rule(
            "DEVELOPMENT", rule, DEVELOPMENT_YEARS, entries, outcomes, daily, features
        )
        for rule in RULES
    }
    selected = select_rule(candidates)
    identities = source_hashes()
    feature_audit = {
        "rows": len(features),
        "unique_gap_ids": int(features.gap_id.nunique()),
        "post_2023_feature_row_count": int(features.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "feature_latest_after_signal_count": int(
            features.latest_source_timestamp.gt(features.signal_time).sum()
        ),
        "development_missing_selected_rule_input_count": int(
            features.loc[features.period_label.eq("DEVELOPMENT"), [
                "board_breadth_ma5_change5", "industry_median_ret5"
            ]].isna().any(axis=1).sum()
        ),
    }
    result = {
        "experiment": EXPERIMENT,
        **hashes,
        "source_hashes": identities,
        "feature_audit": feature_audit,
        "candidate_results": candidates,
        "selected_rule": selected["rule"],
        "selector_passed": True,
        "diagnostic_specific_outcomes_opened": "NO",
        "post_2023_signal_feature_selection_use": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_FREEZE_BEFORE_SELECTED_RULE_OUTCOMES",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "source_hashes": identities,
        "selected_rule": selected["rule"],
        "diagnostic_specific_outcomes_opened": "NO",
        "post_2023_signal_feature_selection_use": "NO",
    }
    write_json(DIAGNOSTIC_FREEZE, freeze)
    return freeze


def verify_freeze() -> dict[str, Any]:
    if not DIAGNOSTIC_FREEZE.is_file():
        raise V6Error("diagnostic freeze missing")
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "feature_dictionary_sha256": sha256(FEATURE_DICTIONARY),
        "runner_sha256": sha256(Path(__file__)),
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    identities = source_hashes()
    if identities != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), identities]
    if drift:
        raise V6Error(f"freeze drift: {drift}")
    return {"verified": True, "checks": checks, "source_hashes": identities}


def run_diagnostic() -> dict[str, Any]:
    verification = verify_freeze()
    freeze = json.loads(DIAGNOSTIC_FREEZE.read_text(encoding="utf-8"))
    rule = str(freeze["selected_rule"])
    features = pd.read_parquet(FEATURES)
    for column in ("signal_date", "signal_time", "latest_source_timestamp"):
        features[column] = pd.to_datetime(features[column])
    entries, outcomes, daily = v5.load_source("POST_OBSERVATION_DIAGNOSTIC")
    diagnostic = replay_rule(
        "POST_OBSERVATION_DIAGNOSTIC",
        rule,
        DIAGNOSTIC_YEARS,
        entries,
        outcomes,
        daily,
        features,
    )
    yearly = diagnostic["event_yearly"]
    checks = {
        "event_mean_net_ge_3pct": diagnostic["event_metrics"]["mean_net"] >= 0.03,
        "portfolio_mean_net_ge_3pct": diagnostic["portfolio_mean_net"] >= 0.03,
        "portfolio_median_positive": diagnostic["portfolio_median_net"] > 0,
        "signals_per_year_40_to_80": 40 <= diagnostic["selected_signals_per_year"] <= 80,
        "severe10_le_15pct": diagnostic["portfolio_severe10"] <= 0.15,
        "both_year_event_means_positive": all(
            float(yearly.get(str(year), {}).get("mean_net", -1.0)) > 0
            for year in DIAGNOSTIC_YEARS
        ),
        "post_2023_signal_count_zero": diagnostic["post_2023_signal_count"] == 0,
    }
    verdict = (
        "ENVIRONMENT_BREADTH_REPAIR_POST_OBSERVATION_TARGET_RETAINED"
        if all(checks.values())
        else "ENVIRONMENT_BREADTH_REPAIR_POST_OBSERVATION_FAILED"
    )
    result = {
        "experiment": EXPERIMENT,
        "freeze_verification": verification,
        "selected_rule": rule,
        "diagnostic": diagnostic,
        "goal_checks": checks,
        "verdict": verdict,
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_ONLY",
        "post_2023_signal_feature_selection_use": "NO",
        "repository_2024_plus_data_opened": "INHERITED_AUTHORIZED_PRE_2024_TRADE_RESOLUTION_TAIL_ONLY",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    diagnostic = json.loads(DIAGNOSTIC_RESULT.read_text(encoding="utf-8"))
    selected = development["candidate_results"][development["selected_rule"]]
    observed = diagnostic["diagnostic"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Result",
        "",
        f"`{diagnostic['verdict']}`",
        "",
        f"Selected rule: `{development['selected_rule']}`.",
        "",
        "|Period|Signals|Signals/year|Trades|Event mean|Portfolio mean|Median|Severe10|Total return|MaxDD|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, item in (("Development 2017–2021", selected), ("Post-observation 2022–2023", observed)):
        combined = item["portfolio"]["COMBINED"]
        lines.append(
            f"|{label}|{item['selected_signals']}|{item['selected_signals_per_year']:.1f}|"
            f"{combined['trades']}|{pct(item['event_metrics']['mean_net'])}|{pct(combined['mean_net'])}|"
            f"{pct(combined['median_net'])}|{pct(combined['severe10'])}|{pct(combined['total_return'])}|"
            f"{pct(combined['max_drawdown'])}|"
        )
    lines += [
        "",
        "## Development rule trace",
        "",
        "|Rule|Signals/year|Portfolio mean|Median|Severe10|Positive years|",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for rule in RULES:
        item = development["candidate_results"][rule]
        lines.append(
            f"|{rule}|{item['selected_signals_per_year']:.1f}|{pct(item['portfolio_mean_net'])}|"
            f"{pct(item['portfolio_median_net'])}|{pct(item['portfolio_severe10'])}|"
            f"{item['positive_calendar_years']}/5|"
        )
    lines += [
        "",
        "## Governance",
        "",
        "- Every environment feature ends at the signal close and uses continuous, valid QD-010 coordinates.",
        "- Missing industry or breadth inputs fail closed.",
        "- 2022–2023 is post-observation diagnostic evidence, not pristine validation.",
        "- No post-2023 signal or feature row was opened.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=("development-freeze", "verify-freeze", "diagnostic", "report")
    )
    args = parser.parse_args()
    if args.stage == "development-freeze":
        payload = run_development_and_freeze()
    elif args.stage == "verify-freeze":
        payload = verify_freeze()
    elif args.stage == "diagnostic":
        payload = run_diagnostic()
    else:
        render_report()
        payload = {"report": str(REPORT)}
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
