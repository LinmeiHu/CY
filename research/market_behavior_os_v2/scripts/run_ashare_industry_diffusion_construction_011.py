#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen Industry Diffusion stock-quality construction experiment."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_candidate_attribution.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_risk_exits.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-INDUSTRY-DIFFUSION-CONSTRUCTION-011_report.md"
BASELINE_RUNNER = PROGRAM / "scripts/run_ashare_ca_replay_003.py"
EXPECTED_SPEC_SHA256 = "0d9f809a9e19bd000f559c4c64cb73e7f6010883b82ebc4f625c9ba845c11ac0"


class DiffusionConstructionError(RuntimeError):
    """Fail-closed error for the frozen construction experiment."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise DiffusionConstructionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


BASELINE = _load_module("ashare_ca_replay_003_for_011", BASELINE_RUNNER)
CYCLE2 = BASELINE.PRIOR


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DiffusionConstructionError("frozen construction spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_CONSTRUCTION_AND_MATERIALITY_BEFORE_NEW_ARM_OUTCOMES":
        raise DiffusionConstructionError("construction contract was not frozen before outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DiffusionConstructionError(f"bound input changed: {name}")
    if list(spec["arms"]) != [
        "arm0_baseline",
        "arm1_upper_limit_clean",
        "arm2_low_max",
        "arm3_optional_equal_rank",
    ]:
        raise DiffusionConstructionError("arm identity changed")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "signal, clock", "full replay", "optional arm 3"):
        if phrase not in prohibited:
            raise DiffusionConstructionError(f"missing prohibition: {phrase}")
    return spec


def _build_opportunity_frame(
    paths: list[Path], temp_path: Path
) -> tuple[pd.DataFrame, dict[str, Any]]:
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    con.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    audit_row = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
        sum((hard_valid AND market_rule_valid AND (limit_pct IS NULL OR up_limit_price IS NULL))::INTEGER)
        FROM source"""
    ).fetchone()
    audit = {
        "rows": int(audit_row[0]),
        "symbols": int(audit_row[1]),
        "first": str(audit_row[2]),
        "last": str(audit_row[3]),
        "time_travel": int(audit_row[4]),
        "lineage_failures": int(audit_row[5]),
        "limit_rule_failures": int(audit_row[6]),
    }
    expected = {
        "rows": 6155390,
        "symbols": 5262,
        "first": "2018-01-02",
        "last": "2023-12-29",
        "time_travel": 0,
        "lineage_failures": 0,
        "limit_rule_failures": 0,
    }
    if audit != expected:
        raise DiffusionConstructionError(f"source audit changed: {audit}")
    con.execute(
        """CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 cal_idx
        FROM (SELECT DISTINCT trade_date FROM source) ORDER BY trade_date"""
    )
    con.execute(
        """CREATE TEMP TABLE base AS SELECT s.*,c.cal_idx,
        (s.hard_valid IS TRUE AND s.bar_valid IS TRUE AND s.trading_state_valid IS TRUE
         AND s.industry_valid IS TRUE AND s.float_valid IS TRUE
         AND s.corporate_action_valid IS TRUE AND s.market_valid IS TRUE
         AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
         AND s.corporate_action_blocking IS FALSE AND coalesce(s.rights_ratio,0)=0
         AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
         AND s.open>0 AND s.high>=greatest(s.open,s.close)
         AND s.low<=least(s.open,s.close) AND s.close>0 AND s.volume>=0 AND s.amount>=0) history_valid,
        (s.hard_valid IS TRUE AND s.trade_status=1
         AND s.current_day_data_tradable IS TRUE AND s.is_st IS FALSE) current_valid,
        lag(s.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(s.hard_valid IS TRUE AND s.bar_valid IS TRUE AND s.trading_state_valid IS TRUE
         AND s.industry_valid IS TRUE AND s.float_valid IS TRUE
         AND s.corporate_action_valid IS TRUE AND s.market_valid IS TRUE
         AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
         AND s.corporate_action_blocking IS FALSE AND coalesce(s.rights_ratio,0)=0
         AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
         AND s.open>0 AND s.high>=greatest(s.open,s.close)
         AND s.low<=least(s.open,s.close) AND s.close>0
         AND s.volume>=0 AND s.amount>=0) OVER w previous_history_valid
        FROM source s JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY s.symbol ORDER BY s.trade_date)"""
    )
    con.execute(
        """CREATE TEMP TABLE steps0 AS SELECT *,CASE
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
        ELSE NULL END step_log_return,
        (history_valid AND limit_pct IS NOT NULL AND up_limit_price IS NOT NULL) limit_quality_valid,
        (history_valid AND limit_pct IS NOT NULL AND up_limit_price IS NOT NULL
         AND close=up_limit_price) upper_limit_close
        FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE steps AS SELECT *,
        (upper_limit_close OR lag(upper_limit_close,1,false) OVER
          (PARTITION BY symbol ORDER BY trade_date)) revised_excluded,
        median(step_log_return) OVER (PARTITION BY trade_date) market_median_step
        FROM steps0"""
    )
    con.execute(
        """CREATE TEMP TABLE coordinates AS SELECT *,
        step_log_return-market_median_step residual_step,
        sum(coalesce(step_log_return,0)) OVER
          (PARTITION BY symbol ORDER BY trade_date ROWS UNBOUNDED PRECEDING) log_coordinate
        FROM steps"""
    )
    con.execute(
        """CREATE TEMP TABLE rolling AS SELECT *,exp(log_coordinate) coordinate_close,
        exp(log_coordinate)*open/close coordinate_open,
        lag(exp(log_coordinate)) OVER ws previous_coordinate_close,
        sum(step_log_return) OVER w5 r5,sum(step_log_return) OVER w20 r20,
        max(step_log_return) OVER w20 max_return20,
        sum(CASE WHEN NOT revised_excluded THEN step_log_return ELSE 0 END) OVER w240 revised_240,
        count(step_log_return) OVER w120 valid_steps120,
        count(step_log_return) OVER w240 valid_steps240,
        count(*) FILTER (WHERE limit_quality_valid) OVER w240 limit_valid240,
        lag(cal_idx,120) OVER ws cal_idx_lag120,
        avg(amount) OVER p20 avg_amount20,avg(volume) OVER p20 avg_volume20,
        count(*) OVER p20 prior_count20,count(residual_step) OVER w20 residual_count20,
        stddev_samp(residual_step) OVER w20 idio_vol20,
        sum(CASE WHEN step_log_return>0 THEN volume WHEN step_log_return<0 THEN -volume ELSE 0 END) OVER w20
          / nullif(sum(volume) OVER w20,0) signed_volume_share20
        FROM coordinates WINDOW
        ws AS (PARTITION BY symbol ORDER BY trade_date),
        w5 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
        w240 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 239 PRECEDING AND CURRENT ROW),
        p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)"""
    )
    con.execute(
        """CREATE TEMP TABLE eligible0 AS SELECT * FROM rolling
        WHERE current_valid AND history_valid AND cal_idx>=120 AND cal_idx%5=4
        AND valid_steps120=120 AND cal_idx-cal_idx_lag120=120
        AND prior_count20=20 AND avg_amount20>=50000000 AND avg_volume20>0
        AND isfinite(r5) AND isfinite(r20) AND residual_count20=20
        AND isfinite(idio_vol20) AND isfinite(signed_volume_share20)
        AND previous_coordinate_close>0 AND coordinate_open>0"""
    )
    frame = con.execute(
        """SELECT *,count(*) OVER (PARTITION BY trade_date,industry) industry_count,
        (sum((r20>0)::INTEGER) OVER (PARTITION BY trade_date,industry)-(r20>0)::INTEGER)
          / nullif(count(*) OVER (PARTITION BY trade_date,industry)-1,0) diffusion_score,
        CASE WHEN valid_steps240=240 AND limit_valid240=240 AND isfinite(revised_240)
             THEN revised_240 ELSE NULL END upper_limit_clean_score
        FROM eligible0
        QUALIFY industry_count>=6
        ORDER BY trade_date,industry,symbol"""
    ).fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise DiffusionConstructionError("invalid opportunity frame")
    return frame, audit


def _frozen_baseline(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    panel = pd.read_csv(
        _resolve(spec["inputs"]["baseline_candidate_panel"]["path"]),
        parse_dates=["trade_date", "decision_at", "available_at"],
    )
    baseline = panel.loc[
        panel.family.eq("industry_diffusion_20") & panel.signal_rank.le(10)
    ].copy()
    baseline["trade_date"] = pd.to_datetime(baseline.trade_date)
    joined = baseline.merge(
        frame,
        on=["trade_date", "symbol", "industry"],
        how="left",
        suffixes=("_frozen", ""),
        validate="one_to_one",
    )
    if len(joined) != len(baseline) or joined.diffusion_score.isna().any():
        raise DiffusionConstructionError("frozen baseline names absent from opportunity frame")
    generated = (
        frame.sort_values(["trade_date", "diffusion_score", "symbol"], ascending=[True, False, True])
        .groupby("trade_date", sort=False)
        .head(10)
    )
    left = set(zip(joined.trade_date, joined.symbol, strict=True))
    right = set(zip(generated.trade_date, generated.symbol, strict=True))
    if left != right:
        raise DiffusionConstructionError("baseline Top-10 identity does not reproduce")
    joined["family"] = "arm0_baseline"
    joined["signal_score"] = joined.diffusion_score
    joined["signal_rank"] = joined.signal_rank.astype(int)
    return joined


def _select_modifier(
    candidates: pd.DataFrame,
    baseline: pd.DataFrame,
    family: str,
    score_column: str,
    ascending: bool,
) -> pd.DataFrame:
    allocations = (
        baseline.groupby(["trade_date", "industry"], sort=True)
        .size()
        .rename("target")
        .reset_index()
    )
    opportunity = candidates.merge(allocations, on=["trade_date", "industry"], how="inner")
    baseline_order = {
        (row.trade_date, row.industry, row.symbol): int(row.signal_rank)
        for row in baseline.itertuples(index=False)
    }
    outputs: list[pd.DataFrame] = []
    for (trade_date, industry), group in opportunity.groupby(["trade_date", "industry"], sort=True):
        target = int(group.target.iloc[0])
        valid = group.loc[group[score_column].notna()].sort_values(
            [score_column, "symbol"], ascending=[ascending, True]
        )
        chosen = valid.head(target).copy()
        chosen_symbols = set(chosen.symbol)
        if len(chosen) < target:
            fallback_symbols = [
                symbol
                for _, _, symbol in sorted(
                    (key for key in baseline_order if key[0] == trade_date and key[1] == industry),
                    key=lambda key: baseline_order[key],
                )
                if symbol not in chosen_symbols
            ]
            fallback = group.loc[group.symbol.isin(fallback_symbols)].copy()
            fallback["_fallback_order"] = fallback.symbol.map(
                {symbol: index for index, symbol in enumerate(fallback_symbols)}
            )
            fallback = fallback.sort_values("_fallback_order").head(target - len(chosen))
            chosen = pd.concat([chosen, fallback.drop(columns="_fallback_order")], ignore_index=True)
        if len(chosen) != target:
            raise DiffusionConstructionError(f"modifier cannot preserve allocation:{family}:{trade_date}:{industry}")
        chosen["quality_available"] = chosen[score_column].notna()
        outputs.append(chosen)
    selected = pd.concat(outputs, ignore_index=True)
    selected["family"] = family
    selected["signal_score"] = -selected[score_column] if ascending else selected[score_column]
    selected = selected.sort_values(
        ["trade_date", "industry", "signal_score", "symbol"],
        ascending=[True, True, False, True],
    )
    selected["signal_rank"] = selected.groupby("trade_date").cumcount() + 1
    return selected


def _select_equal_rank(candidates: pd.DataFrame, baseline: pd.DataFrame) -> pd.DataFrame:
    work = candidates.copy()
    work["clean_rank"] = work.groupby("trade_date").upper_limit_clean_score.rank(
        method="average", pct=True, ascending=True
    )
    work["low_max_rank"] = work.groupby("trade_date").max_return20.rank(
        method="average", pct=True, ascending=False
    )
    work["equal_rank_quality"] = (work.clean_rank + work.low_max_rank) / 2
    return _select_modifier(
        work,
        baseline,
        "arm3_equal_rank",
        "equal_rank_quality",
        ascending=False,
    )


def _allocation_difference(baseline: pd.DataFrame, arm: pd.DataFrame) -> float:
    base = baseline.groupby(["trade_date", "industry"]).size()
    other = arm.groupby(["trade_date", "industry"]).size()
    aligned = pd.concat([base.rename("base"), other.rename("arm")], axis=1).fillna(0)
    return float((aligned.base - aligned.arm).abs().max())


def _selection_headroom(
    baseline: pd.DataFrame, arm: pd.DataFrame, candidates: pd.DataFrame, score_column: str
) -> dict[str, Any]:
    base_sets = baseline.groupby("trade_date").symbol.apply(set)
    arm_sets = arm.groupby("trade_date").symbol.apply(set)
    dates = base_sets.index.intersection(arm_sets.index)
    changed = pd.Series(
        [len(arm_sets.loc[day] - base_sets.loc[day]) / 10 for day in dates], index=dates
    )
    opportunity = candidates.loc[
        candidates.set_index(["trade_date", "industry"]).index.isin(
            baseline.groupby(["trade_date", "industry"]).size().index
        )
    ]
    return {
        "decision_dates": len(dates),
        "changed_selections": round(float(changed.sum() * 10)),
        "changed_fraction": float(changed.mean()),
        "overlap_fraction": float(1 - changed.mean()),
        "median_eligible_stocks_per_date": float(opportunity.groupby("trade_date").size().median()),
        "median_industries_per_date": float(baseline.groupby("trade_date").industry.nunique().median()),
        "quality_available_fraction": float(opportunity[score_column].notna().mean()),
        "industry_allocation_max_difference": _allocation_difference(baseline, arm),
    }


def _screen_selections(selections: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "family", "trade_date", "cal_idx", "decision_at", "available_at", "symbol",
        "industry", "signal_score", "signal_rank", "avg_amount20", "r5", "r20",
    ]
    screen = selections[columns].copy()
    screen["leg"] = "top"
    screen["candidate_count"] = screen.groupby(["family", "trade_date"]).symbol.transform("size")
    screen["industry_rank"] = np.nan
    screen["liquidity_rank"] = np.nan
    return screen


def _candidate_metrics(
    panel: pd.DataFrame,
    family: str,
    baseline_family: str,
    headroom: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    def period_metrics(rows: pd.DataFrame) -> dict[str, Any]:
        valid = rows.loc[rows.status_h20.eq("COMPLETE")]
        values = valid.net_return_h20.astype(float)
        return {
            "complete_selections": len(valid),
            "decision_dates": int(valid.trade_date.nunique()),
            "mean_net_return": float(values.mean()),
            "median_net_return": float(values.median()),
            "winner_fraction": float((values > 0).mean()),
            "severe_loss_fraction": float((values <= -0.10).mean()),
            "entry_execution_fraction": float(rows.entry_status.eq("EXECUTABLE").mean()),
        }

    arm = panel.loc[panel.family.eq(family)].copy()
    base = panel.loc[panel.family.eq(baseline_family)].copy()
    arm_year = pd.to_datetime(arm.trade_date).dt.year
    base_year = pd.to_datetime(base.trade_date).dt.year
    periods = {
        "full": (arm, base),
        "early": (arm.loc[arm_year <= 2020], base.loc[base_year <= 2020]),
        "late": (arm.loc[arm_year >= 2021], base.loc[base_year >= 2021]),
    }
    output: dict[str, Any] = {}
    for period, (arm_rows, base_rows) in periods.items():
        arm_stats = period_metrics(arm_rows)
        base_stats = period_metrics(base_rows)
        output[period] = {
            "arm": arm_stats,
            "baseline": base_stats,
            "mean_net_improvement": arm_stats["mean_net_return"] - base_stats["mean_net_return"],
            "winner_capture_improvement": arm_stats["winner_fraction"] - base_stats["winner_fraction"],
            "severe_loss_improvement": base_stats["severe_loss_fraction"] - arm_stats["severe_loss_fraction"],
        }
    base_keys = set(zip(base.trade_date, base.symbol, strict=True))
    arm_keys = set(zip(arm.trade_date, arm.symbol, strict=True))
    baseline_only_mask = pd.Series(
        [
            (day, symbol) not in arm_keys
            for day, symbol in zip(base.trade_date, base.symbol, strict=True)
        ],
        index=base.index,
    )
    arm_only_mask = pd.Series(
        [
            (day, symbol) not in base_keys
            for day, symbol in zip(arm.trade_date, arm.symbol, strict=True)
        ],
        index=arm.index,
    )
    baseline_only = base.loc[baseline_only_mask & base.status_h20.eq("COMPLETE")]
    arm_only = arm.loc[arm_only_mask & arm.status_h20.eq("COMPLETE")]
    gates = spec["candidate_attribution"]["authorization_all_required"]
    checks = {
        "complete_selections": output["full"]["arm"]["complete_selections"] >= gates["minimum_complete_selections"],
        "dates_each_block": min(output["early"]["arm"]["decision_dates"], output["late"]["arm"]["decision_dates"]) >= gates["minimum_decision_dates_each_block"],
        "quality_available": headroom["quality_available_fraction"] >= gates["minimum_quality_available_fraction"],
        "changed_lower": headroom["changed_fraction"] >= gates["minimum_changed_fraction"],
        "changed_upper": headroom["changed_fraction"] <= gates["maximum_changed_fraction"],
        "full_payoff": output["full"]["mean_net_improvement"] >= gates["minimum_full_mean_net_improvement"],
        "both_blocks": min(output["early"]["mean_net_improvement"], output["late"]["mean_net_improvement"]) >= gates["minimum_each_block_mean_net_improvement"],
        "severe_loss": output["full"]["severe_loss_improvement"] >= gates["minimum_severe_loss_improvement"],
        "industry_allocation": headroom["industry_allocation_max_difference"] <= gates["maximum_industry_allocation_difference"],
    }
    return {
        "headroom": headroom,
        "periods": output,
        "changed_selection_attribution": {
            "baseline_only_complete": len(baseline_only),
            "arm_only_complete": len(arm_only),
            "severe_losers_avoided_net": int((baseline_only.net_return_h20 <= -0.10).sum() - (arm_only.net_return_h20 <= -0.10).sum()),
            "winners_captured_net": int((arm_only.net_return_h20 > 0).sum() - (baseline_only.net_return_h20 > 0).sum()),
            "positive_upside_sacrificed_net": float(baseline_only.net_return_h20.clip(lower=0).sum() - arm_only.net_return_h20.clip(lower=0).sum()),
        },
        "authorization_gates": checks,
        "authorized_replay": all(checks.values()),
    }


def _make_plans(selections: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    index = {day: position for position, day in enumerate(calendar)}
    rows = []
    for item in selections.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        entry_index = index[signal_date] + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        rows.append(
            {
                "family": item.family,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": 20,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.groupby(["family", "signal_date"]).size().max() != 10:
        raise DiffusionConstructionError("plan breadth changed")
    return plans


def _assert_baseline_identity(replay: dict[str, Any], authoritative: dict[str, Any]) -> None:
    prior = next(row for row in authoritative["replays"] if row["family"] == "industry_diffusion_20")
    exact_fields = ["completed_trades", "entries", "planned_entries", "forced_pre_effective_exits", "terminal_open_lots"]
    float_fields = [
        "total_return", "annualized_return", "maximum_drawdown", "daily_sharpe", "calmar",
        "turnover_multiple_initial_capital", "entry_execution_fraction", "severe_trade_fraction",
        "mean_positions", "mean_industries", "mean_industry_hhi_invested_days",
        "p10_capacity_cny_at_5pct_amount", "median_capacity_cny_at_5pct_amount",
    ]
    for field in exact_fields:
        if replay[field] != prior[field]:
            raise DiffusionConstructionError(f"baseline identity mismatch:{field}")
    for field in float_fields:
        if not math.isclose(float(replay[field]), float(prior[field]), rel_tol=0, abs_tol=1e-12):
            raise DiffusionConstructionError(f"baseline identity mismatch:{field}")


def _portfolio_comparison(
    baseline: dict[str, Any], arm: dict[str, Any], headroom: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    turnover_increase = arm["turnover_multiple_initial_capital"] / baseline["turnover_multiple_initial_capital"] - 1
    capacity_ratio = arm["p10_capacity_cny_at_5pct_amount"] / baseline["p10_capacity_cny_at_5pct_amount"]
    deltas = {
        "total_return": arm["total_return"] - baseline["total_return"],
        "annualized_return": arm["annualized_return"] - baseline["annualized_return"],
        "maximum_drawdown_improvement": arm["maximum_drawdown"] - baseline["maximum_drawdown"],
        "daily_sharpe": arm["daily_sharpe"] - baseline["daily_sharpe"],
        "calmar": arm["calmar"] - baseline["calmar"],
        "severe_trade_fraction_improvement": baseline["severe_trade_fraction"] - arm["severe_trade_fraction"],
        "turnover_increase_fraction": turnover_increase,
        "mean_positions": arm["mean_positions"] - baseline["mean_positions"],
        "mean_industries": arm["mean_industries"] - baseline["mean_industries"],
        "industry_hhi": arm["mean_industry_hhi_invested_days"] - baseline["mean_industry_hhi_invested_days"],
        "capacity_ratio": capacity_ratio,
    }
    gates = spec["portfolio_materiality"]["all_required"]
    risk = gates["risk_improvement_any"]
    risk_checks = {
        "sharpe": deltas["daily_sharpe"] >= risk["minimum_sharpe_improvement"],
        "drawdown": deltas["maximum_drawdown_improvement"] >= risk["minimum_drawdown_improvement"],
        "severe_loss": deltas["severe_trade_fraction_improvement"] >= risk["minimum_severe_trade_fraction_improvement"],
    }
    checks = {
        "execution": arm["entry_execution_fraction"] >= gates["minimum_entry_execution_fraction"],
        "return_preservation": deltas["total_return"] >= gates["minimum_total_return_delta"],
        "changed_lower": headroom["changed_fraction"] >= gates["minimum_changed_fraction"],
        "changed_upper": headroom["changed_fraction"] <= gates["maximum_changed_fraction"],
        "turnover": turnover_increase <= gates["maximum_turnover_increase_fraction"],
        "industry_hhi": deltas["industry_hhi"] <= gates["maximum_industry_hhi_increase"],
        "capacity": capacity_ratio >= gates["minimum_capacity_ratio"],
        "risk_improvement": any(risk_checks.values()),
    }
    absolute = spec["portfolio_materiality"]["absolute_strategy_candidate_all_required"]
    absolute_checks = {
        "return": arm["total_return"] > absolute["minimum_total_return"],
        "sharpe": arm["daily_sharpe"] >= absolute["minimum_daily_sharpe"],
        "drawdown": arm["maximum_drawdown"] >= absolute["minimum_maximum_drawdown"],
        "severe_loss": arm["severe_trade_fraction"] <= absolute["maximum_severe_trade_fraction"],
        "liquidated": arm["terminal_open_lots"] == absolute["terminal_open_lots"],
    }
    return {
        "deltas": deltas,
        "risk_improvement_checks": risk_checks,
        "materiality_checks": checks,
        "materiality_pass": all(checks.values()),
        "absolute_candidate_checks": absolute_checks,
        "absolute_candidate_pass": all(absolute_checks.values()),
    }


def _render(result: dict[str, Any]) -> str:
    baseline = result["portfolio_replays"][0]
    lines = [
        "# Industry Diffusion stock-quality strategy construction",
        "",
        "> Consumed 2018–2023 development evidence only. Post-2023 outcomes and CY-011 were not read.",
        "",
        "## Baseline reproduction",
        "",
        f"The frozen `industry_diffusion_20` replay reproduces exactly: total {baseline['total_return']:.2%}, annualized {baseline['annualized_return']:.2%}, maximum drawdown {baseline['maximum_drawdown']:.2%}, Sharpe {baseline['daily_sharpe']:.3f}, Calmar {baseline['calmar']:.3f}, severe trades {baseline['severe_trade_fraction']:.2%}, turnover {baseline['turnover_multiple_initial_capital']:.2f}x, and {baseline['completed_trades']:,} completed trades.",
        "",
        "## Candidate-level attribution",
        "",
        "| Arm | Changed | Overlap | Quality coverage | Full payoff delta | Early / late delta | Severe improvement | Winner capture | Replay gate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for family, row in result["candidate_attribution"].items():
        lines.append(
            f"| {family} | {row['headroom']['changed_fraction']:.2%} | {row['headroom']['overlap_fraction']:.2%} | "
            f"{row['headroom']['quality_available_fraction']:.2%} | {row['periods']['full']['mean_net_improvement']:.3%} | "
            f"{row['periods']['early']['mean_net_improvement']:.3%} / {row['periods']['late']['mean_net_improvement']:.3%} | "
            f"{row['periods']['full']['severe_loss_improvement']:.3%} | {row['periods']['full']['winner_capture_improvement']:.3%} | "
            f"{'PASS' if row['authorized_replay'] else 'FAIL'} |"
        )
    lines.append("")
    for family, row in result["candidate_attribution"].items():
        headroom = row["headroom"]
        changed = row["changed_selection_attribution"]
        lines.append(
            f"- `{family}`: {headroom['decision_dates']} dates, {headroom['changed_selections']:,} changed selections, "
            f"median {headroom['median_eligible_stocks_per_date']:.0f} eligible stocks / "
            f"{headroom['median_industries_per_date']:.0f} industries; net severe losers avoided "
            f"{changed['severe_losers_avoided_net']}, net winners captured {changed['winners_captured_net']}, "
            f"and aggregate positive-payoff sum sacrificed "
            f"{changed['positive_upside_sacrificed_net']:+.3f}."
        )
    lines.extend([
        "",
        "Industry allocation counts are identical to baseline by construction; the diagnostic is within-industry and cannot create an industry-composition result.",
        "",
        "## Full executable comparison",
        "",
        "| Arm | Total | Annualized | Max DD | Sharpe | Calmar | Severe | Turnover | Trades | Entry coverage | Positions | Industries | HHI | P10 capacity |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for replay in result["portfolio_replays"]:
        lines.append(
            f"| {replay['family']} | {replay['total_return']:.2%} | {replay['annualized_return']:.2%} | "
            f"{replay['maximum_drawdown']:.2%} | {replay['daily_sharpe']:.3f} | {replay['calmar']:.3f} | "
            f"{replay['severe_trade_fraction']:.2%} | {replay['turnover_multiple_initial_capital']:.2f}x | "
            f"{replay['completed_trades']} | {replay['entry_execution_fraction']:.2%} | "
            f"{replay['mean_positions']:.1f} | {replay['mean_industries']:.1f} | "
            f"{replay['mean_industry_hhi_invested_days']:.3f} | CNY {replay['p10_capacity_cny_at_5pct_amount']:,.0f} |"
        )
    if result["portfolio_comparisons"]:
        lines.extend(["", "Portfolio materiality:"])
        for family, row in result["portfolio_comparisons"].items():
            failed = [name for name, passed in row["materiality_checks"].items() if not passed]
            lines.append(
                f"- `{family}`: return delta {row['deltas']['total_return']:+.2%}, drawdown improvement "
                f"{row['deltas']['maximum_drawdown_improvement']:+.2%}, Sharpe delta {row['deltas']['daily_sharpe']:+.3f}, "
                f"severe improvement {row['deltas']['severe_trade_fraction_improvement']:+.2%}; materiality "
                f"`{'PASS' if row['materiality_pass'] else 'FAIL'}`"
                f"{f'; failed: {', '.join(failed)}' if failed else ''}."
            )
    else:
        lines.extend(["", "No modifier passed the frozen candidate-level gate, so no modifier received a full replay."])
    lines.extend([
        "",
        "## Complexity decision",
        "",
        result["complexity_decision"],
        "",
        f"Family-level classification: `{result['classification']}`.",
        "",
        "## Next Price–Volume–Path questions",
        "",
    ])
    for index, question in enumerate(result["next_frontier"], start=1):
        lines.append(f"{index}. **{question['family']}** — {question['question']} Rationale: {question['rationale']}")
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    baseline_spec = BASELINE._load_spec()
    paths, calendar, input_identity = BASELINE._load_market_inputs(baseline_spec)
    external = Path("/Volumes/quant")
    if not external.is_dir() or not os.access(external, os.W_OK):
        raise DiffusionConstructionError("verified external temporary root unavailable")
    with tempfile.TemporaryDirectory(prefix="industry-diffusion-construction-011-", dir=external) as temporary:
        frame, audit = _build_opportunity_frame(paths, Path(temporary))
    baseline = _frozen_baseline(frame, spec)
    arm1 = _select_modifier(frame, baseline, "arm1_upper_limit_clean", "upper_limit_clean_score", ascending=False)
    arm2 = _select_modifier(frame, baseline, "arm2_low_max", "max_return20", ascending=True)
    headroom = {
        "arm1_upper_limit_clean": _selection_headroom(baseline, arm1, frame, "upper_limit_clean_score"),
        "arm2_low_max": _selection_headroom(baseline, arm2, frame, "max_return20"),
    }
    candidate_selections = pd.concat([baseline, arm1, arm2], ignore_index=True)
    panel, outcome_rows = CYCLE2._attach_screen_outcomes(
        paths, _screen_selections(candidate_selections), calendar
    )
    attribution = {
        family: _candidate_metrics(panel, family, "arm0_baseline", headroom[family], spec)
        for family in ("arm1_upper_limit_clean", "arm2_low_max")
    }
    arm3_authorized = all(row["authorized_replay"] for row in attribution.values())
    arm3: pd.DataFrame | None = None
    if arm3_authorized:
        arm3 = _select_equal_rank(frame, baseline)
        arm3_headroom = _selection_headroom(baseline, arm3, frame, "equal_rank_quality")
        arm3_panel, arm3_rows = CYCLE2._attach_screen_outcomes(
            paths, _screen_selections(pd.concat([baseline, arm3], ignore_index=True)), calendar
        )
        outcome_rows += arm3_rows
        arm3_metrics = _candidate_metrics(
            arm3_panel, "arm3_equal_rank", "arm0_baseline", arm3_headroom, spec
        )
        attribution["arm3_equal_rank"] = arm3_metrics
        panel = pd.concat(
            [panel, arm3_panel.loc[arm3_panel.family.eq("arm3_equal_rank")]], ignore_index=True
        )
    replay_selections = [baseline]
    for family, selection in (("arm1_upper_limit_clean", arm1), ("arm2_low_max", arm2)):
        if attribution[family]["authorized_replay"]:
            replay_selections.append(selection)
    if arm3 is not None and attribution["arm3_equal_rank"]["authorized_replay"]:
        replay_selections.append(arm3)
    replay_selection_frame = pd.concat(replay_selections, ignore_index=True)
    plans = _make_plans(replay_selection_frame, calendar)
    market_rows = CYCLE2._query_execution_rows(paths, plans, calendar)
    events, action_audit = BASELINE._load_risk_events(baseline_spec, calendar)
    replays: list[dict[str, Any]] = []
    equity_frames: list[pd.DataFrame] = []
    exit_frames: list[pd.DataFrame] = []
    for family in replay_selection_frame.family.drop_duplicates():
        replay, equity, exits = BASELINE._replay(family, plans, market_rows, calendar, events)
        replays.append(replay)
        equity_frames.append(equity)
        exit_frames.append(exits)
    authoritative = json.loads(
        _resolve(spec["inputs"]["baseline_result"]["path"]).read_text(encoding="utf-8")
    )
    _assert_baseline_identity(replays[0], authoritative)
    comparisons: dict[str, Any] = {}
    for replay in replays[1:]:
        comparisons[replay["family"]] = _portfolio_comparison(
            replays[0], replay, attribution[replay["family"]]["headroom"], spec
        )
    material = [family for family, row in comparisons.items() if row["materiality_pass"]]
    absolute = [
        family for family in material if comparisons[family]["absolute_candidate_pass"]
    ]
    if absolute:
        classification = "INDUSTRY_DIFFUSION_STRATEGY_CANDIDATE"
    elif material:
        classification = "PROMISING_BUT_MIXED"
    else:
        classification = "STRATEGY_CONSTRUCTION_NOT_IMPROVED"
    complexity = (
        f"Permanent stock-quality modifier earned: {', '.join(material)}. Industry Alpha and stock quality remain separately attributed."
        if material
        else "Neither frozen stock-quality mechanism earned a permanent place. Preserve the baseline Industry Diffusion result as mixed and park further construction refinement absent new independent evidence."
    )
    compact = panel.copy()
    compact["natural_status"] = compact.status_h20
    compact["natural_net_return"] = compact.net_return_h20
    compact_columns = [
        "family", "trade_date", "decision_at", "available_at", "symbol", "industry",
        "signal_score", "signal_rank", "candidate_count", "avg_amount20", "entry_status",
        "natural_status", "natural_net_return",
    ]
    _atomic_write(
        PANEL_PATH,
        compact[compact_columns].sort_values(["family", "trade_date", "signal_rank", "symbol"]).to_csv(
            index=False, lineterminator="\n", float_format="%.10g"
        ),
    )
    equity_output = pd.concat(equity_frames, ignore_index=True).sort_values(["family", "trade_date"])
    _atomic_write(EQUITY_PATH, equity_output.to_csv(index=False, lineterminator="\n", float_format="%.10g"))
    if exit_frames and any(not frame.empty for frame in exit_frames):
        exit_output = pd.concat(exit_frames, ignore_index=True).sort_values(["family", "fill_date", "symbol"])
    else:
        exit_output = pd.DataFrame(columns=["family", "symbol", "event_id", "effective_date", "fill_date", "fill_price", "shares"])
    _atomic_write(EXIT_PATH, exit_output.to_csv(index=False, lineterminator="\n", float_format="%.10g"))
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "baseline_reproduced_exactly": True,
        "input_identity": input_identity,
        "input_audit": audit,
        "action_audit": action_audit,
        "domain": {
            "opportunity_rows": len(frame),
            "symbols": int(frame.symbol.nunique()),
            "decision_dates": int(frame.trade_date.nunique()),
            "outcome_path_rows": outcome_rows,
        },
        "candidate_attribution": attribution,
        "optional_arm3_authorized": arm3_authorized,
        "portfolio_replays": replays,
        "portfolio_comparisons": comparisons,
        "complexity_decision": complexity,
        "classification": classification,
        "next_frontier": [
            {
                "family": "Price-limit event lifecycle and acceptance",
                "question": "After an objectively known limit-state event, which predeclared acceptance/rejection paths separate durable demand from temporary attention?",
                "rationale": "High economic value and existing historical-limit/minute data; materially different from another momentum lookback or limit-event count.",
            },
            {
                "family": "Industry leader–follower convergence and leadership turnover",
                "question": "Does causal convergence between leaders and followers forecast continuation or industry reversal beyond frozen diffusion level and acceleration?",
                "rationale": "Uses registered industry structure while asking a distinct mechanism question with broad opportunity breadth.",
            },
            {
                "family": "Liquidity-transition shock assimilation",
                "question": "Do predeclared turnover/liquidity state transitions distinguish informed continuation from temporary attention without repeating low-turnover levels?",
                "rationale": "Price-volume information remains underexploited at the transition layer and is cheap to test with existing data.",
            },
        ],
        "questions": {
            "what_market_behavior_are_we_still_not_studying": "Event-lifecycle acceptance, leader-follower convergence, and liquidity-transition shock assimilation within registered Price-Volume-Path data.",
            "new_strategy_archetype_implied": bool(material),
        },
        "boundaries": {
            "post_2023_read": False,
            "cy011_data_read": False,
            "industry_signal_changed": False,
            "exposure_or_exit_changed": False,
            "new_factor_discovery": False,
            "oos_claim": False,
        },
    }
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "candidate_panel_sha256": sha256_file(PANEL_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(EXIT_PATH),
    }
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
