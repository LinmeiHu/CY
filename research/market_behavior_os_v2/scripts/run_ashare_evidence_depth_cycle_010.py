#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen A-share revised-momentum and low-risk depth cycle."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-EVIDENCE-DEPTH-CYCLE-010_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-EVIDENCE-DEPTH-CYCLE-010_result.json"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-EVIDENCE-DEPTH-CYCLE-010_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-EVIDENCE-DEPTH-CYCLE-010_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-EVIDENCE-DEPTH-CYCLE-010_risk_exits.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-EVIDENCE-DEPTH-CYCLE-010_report.md"
CYCLE8_PATH = PROGRAM / "scripts/run_ashare_skew_breakdown_discovery_cycle_008.py"
EXPECTED_SPEC_SHA256 = "d3ebd67b4d597f06e00a510d103cf437a80b5d43ee24c10dab851ac9718ba44b"
COST = 0.002


class Cycle010Error(RuntimeError):
    """Fail-closed cycle-010 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise Cycle010Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE8 = _load_module("ashare_cycle_008_for_010", CYCLE8_PATH)
CYCLE5 = CYCLE8.CYCLE5


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle010Error("frozen cycle-010 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CYCLE_010_FORWARD_OUTCOME_ACCESS":
        raise Cycle010Error("cycle-010 spec was not frozen before outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle010Error(f"bound input changed: {name}")
    if spec["low_risk"]["canonical_ivol"] != "CANONICAL_IVOL_DATA_LIMITED":
        raise Cycle010Error("canonical IVOL must fail closed")
    return spec


def _revised_exclusion_contract(upper_limit_close: pd.Series) -> pd.Series:
    """Paper rule: remove each upper-limit session and its next stock session."""
    flags = upper_limit_close.astype(bool)
    return flags | flags.shift(1, fill_value=False)


def _build_frame(daily_paths: list[Path], temp_path: Path) -> tuple[pd.DataFrame, list[date], dict[str, Any]]:
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    con.from_parquet([str(path) for path in daily_paths], union_by_name=True).create_view("daily")
    audit_row = con.execute(
        """SELECT count(*),count(DISTINCT symbol),min(trade_date),max(trade_date),
        sum((available_at>decision_at)::INTEGER),
        sum((hard_valid AND (available_at IS NULL OR snapshot_id IS NULL))::INTEGER),
        sum((hard_valid AND market_rule_valid AND (limit_pct IS NULL OR up_limit_price IS NULL))::INTEGER)
        FROM daily"""
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
        raise Cycle010Error(f"source audit changed: {audit}")
    con.execute(
        """CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 cal_idx,
        lead(month(trade_date)) OVER (ORDER BY trade_date)<>month(trade_date) month_end
        FROM (SELECT DISTINCT trade_date FROM daily) ORDER BY trade_date"""
    )
    calendar = [row[0] for row in con.execute("SELECT trade_date FROM calendar ORDER BY cal_idx").fetchall()]
    con.execute(
        """CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,c.month_end,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.snapshot_id IS NOT NULL AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0
         AND d.limit_pct IS NOT NULL AND d.up_limit_price IS NOT NULL) history_valid,
        (d.hard_valid IS TRUE AND d.trade_status=1 AND d.current_day_data_tradable IS TRUE
         AND d.is_st IS FALSE) current_valid,
        lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.snapshot_id IS NOT NULL AND d.close>0 AND d.limit_pct IS NOT NULL
         AND d.up_limit_price IS NOT NULL) OVER w previous_history_valid
        FROM daily d JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)"""
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
        ELSE NULL END step_return,
        (history_valid AND close=up_limit_price) upper_limit_close
        FROM base"""
    )
    con.execute(
        """CREATE TEMP TABLE steps AS SELECT *,
        (upper_limit_close OR lag(upper_limit_close,1,false) OVER
          (PARTITION BY symbol ORDER BY trade_date)) revised_excluded
        FROM steps0"""
    )
    con.execute(
        """CREATE TEMP TABLE features AS SELECT *,
        sum(step_return) OVER w120 conventional_120,
        sum(step_return) OVER w180 conventional_180,
        sum(step_return) OVER w240 conventional_240,
        sum(CASE WHEN NOT revised_excluded THEN step_return ELSE 0 END) OVER w120 revised_120,
        sum(CASE WHEN NOT revised_excluded THEN step_return ELSE 0 END) OVER w180 revised_180,
        sum(CASE WHEN NOT revised_excluded THEN step_return ELSE 0 END) OVER w240 revised_240,
        sum(CASE WHEN revised_excluded THEN step_return ELSE 0 END) OVER w240 excluded_return_mass_240,
        sum(upper_limit_close::INTEGER) OVER w240 upper_limit_count_240,
        sum(revised_excluded::INTEGER) OVER w240 revised_excluded_count_240,
        count(step_return) OVER w120 valid_steps120,
        count(step_return) OVER w180 valid_steps180,
        count(step_return) OVER w240 valid_steps240,
        max(step_return) OVER w20 max_return20,
        min(step_return) OVER w20 min_return20,
        avg(amount) OVER p20 avg_amount20,
        count(*) OVER p20 prior_count20,
        count(*) FILTER (WHERE history_valid) OVER p10 prior_valid10
        FROM steps WINDOW
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
        w180 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 179 PRECEDING AND CURRENT ROW),
        w240 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 239 PRECEDING AND CURRENT ROW),
        p20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
        p10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING)"""
    )
    frame = con.execute(
        """SELECT trade_date,cal_idx,decision_at,available_at,snapshot_id,symbol,industry,
        avg_amount20,close,limit_pct,conventional_120,conventional_180,conventional_240,
        revised_120,revised_180,revised_240,excluded_return_mass_240,upper_limit_count_240,
        revised_excluded_count_240,max_return20,min_return20
        FROM features WHERE month_end AND current_valid AND history_valid AND close>=5
        AND prior_count20=20 AND prior_valid10=10 AND avg_amount20>=50000000
        AND valid_steps120=120 AND valid_steps180=180 AND valid_steps240=240
        AND isfinite(conventional_120) AND isfinite(conventional_180) AND isfinite(conventional_240)
        AND isfinite(revised_120) AND isfinite(revised_180) AND isfinite(revised_240)
        AND isfinite(max_return20) AND isfinite(min_return20)
        ORDER BY trade_date,symbol"""
    ).fetchdf()
    con.close()
    if frame.empty or frame.duplicated(["symbol", "trade_date"]).any():
        raise Cycle010Error("invalid monthly feature frame")
    return frame, calendar, audit


def _extreme_legs(
    frame: pd.DataFrame,
    family_prefix: str,
    score_column: str,
    groups: int,
    track: str,
    metadata: dict[str, Any],
) -> list[pd.DataFrame]:
    work = frame.loc[np.isfinite(frame[score_column])].copy()
    work["signal_score"] = work[score_column]
    work["pct_rank"] = work.groupby("trade_date")[score_column].rank(method="first", pct=True)
    work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
    outputs = []
    for leg, mask, ascending in (
        ("low", work.pct_rank <= 1 / groups, True),
        ("high", work.pct_rank > 1 - 1 / groups, False),
    ):
        selected = work.loc[mask].copy()
        selected = selected.sort_values(
            ["trade_date", "signal_score", "symbol"], ascending=[True, ascending, True]
        )
        selected["signal_rank"] = selected.groupby("trade_date").cumcount() + 1
        selected["family"] = f"{family_prefix}_{leg}"
        selected["leg"] = leg
        selected["track"] = track
        for key, value in metadata.items():
            selected[key] = value
        outputs.append(selected)
    return outputs


def _selections(frame: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    outputs: list[pd.DataFrame] = []
    diagnostics = []
    designs = [spec["revised_momentum"]["primary"], *spec["revised_momentum"]["paper_specified_sensitivities"]]
    for design in designs:
        sessions = int(design["formation_sessions"])
        label = {120: "6m", 180: "9m", 240: "12m"}[sessions]
        for variant in ("conventional", "revised"):
            prefix = f"{variant}_momentum_{label}_1m"
            legs = _extreme_legs(
                frame,
                prefix,
                f"{variant}_{sessions}",
                10,
                "revised_momentum",
                {"design": design["id"], "variant": variant, "formation_sessions": sessions},
            )
            outputs.extend(legs)
            diagnostics.append(
                {
                    "family_prefix": prefix,
                    "decision_dates": int(frame.trade_date.nunique()),
                    "symbols": int(frame.symbol.nunique()),
                    "median_candidates": float(frame.groupby("trade_date").size().median()),
                }
            )
    outputs.extend(
        _extreme_legs(frame, "wan_max_1m", "max_return20", 5, "low_risk", {"design": "wan_max_1m", "variant": "source_defined", "formation_sessions": 20})
    )
    outputs.extend(
        _extreme_legs(frame, "wan_min_1m", "min_return20", 5, "low_risk", {"design": "wan_min_1m", "variant": "source_defined", "formation_sessions": 20})
    )
    diagnostics.extend(
        [
            {"family_prefix": "wan_max_1m", "decision_dates": int(frame.trade_date.nunique()), "symbols": int(frame.symbol.nunique()), "median_candidates": float(frame.groupby("trade_date").size().median())},
            {"family_prefix": "wan_min_1m", "decision_dates": int(frame.trade_date.nunique()), "symbols": int(frame.symbol.nunique()), "median_candidates": float(frame.groupby("trade_date").size().median())},
        ]
    )
    control = frame.copy()
    control["hash_order"] = control.apply(
        lambda row: hashlib.sha256(f"{row.symbol}|010|{row.trade_date}".encode()).hexdigest(), axis=1
    )
    control = control.sort_values(["trade_date", "hash_order", "symbol"]).groupby("trade_date").head(20)
    control["signal_rank"] = control.groupby("trade_date").cumcount() + 1
    control["signal_score"] = np.nan
    control["candidate_count"] = control.groupby("trade_date").symbol.transform("size")
    control["family"], control["leg"], control["track"] = "date_control", "control", "control"
    control["design"], control["variant"], control["formation_sessions"] = "control", "control", 20
    outputs.append(control)
    selections = pd.concat(outputs, ignore_index=True)
    selections["natural_horizon"] = 20
    selections["rebalance_sessions"] = 20
    selections["decision_at"] = pd.to_datetime(selections.trade_date) + pd.Timedelta(hours=15)
    columns = [
        "family", "track", "leg", "design", "variant", "formation_sessions", "trade_date", "cal_idx",
        "decision_at", "available_at", "symbol", "industry", "signal_score", "signal_rank", "candidate_count",
        "avg_amount20", "natural_horizon", "rebalance_sessions", "excluded_return_mass_240", "upper_limit_count_240",
        "revised_excluded_count_240",
    ]
    selections = selections[columns].sort_values(["family", "trade_date", "signal_rank", "symbol"]).reset_index(drop=True)
    if selections.duplicated(["family", "trade_date", "symbol"]).any():
        raise Cycle010Error("duplicate selection")
    return selections, pd.DataFrame(diagnostics)


def _summary(panel: pd.DataFrame) -> pd.DataFrame:
    years = pd.to_datetime(panel.trade_date).dt.year
    masks = {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years <= 2020,
        "late_2021_2023": years >= 2021,
    }
    controls = panel.loc[panel.family == "date_control"]
    complete_controls = controls.loc[controls.status_h20 == "COMPLETE"]
    control_mean = complete_controls.groupby("trade_date").net_return_h20.mean()
    control_severe = complete_controls.groupby("trade_date").net_return_h20.apply(
        lambda values: float((values <= -0.10).mean())
    )
    rows = []
    for family, group in panel.loc[panel.family != "date_control"].groupby("family", sort=True):
        for period, mask in masks.items():
            subset = group.loc[mask.loc[group.index]]
            valid = subset.loc[subset.status_h20 == "COMPLETE"].copy()
            valid["control"] = valid.trade_date.map(control_mean)
            valid["control_severe"] = valid.trade_date.map(control_severe)
            valid = valid.dropna(subset=["control", "control_severe"])
            returns = valid.net_return_h20.astype(float)
            control_severe_fraction = float(
                valid.groupby("trade_date").control_severe.first().mean()
            )
            rows.append(
                {
                    "family": family,
                    "track": group.track.iloc[0],
                    "leg": group.leg.iloc[0],
                    "design": group.design.iloc[0],
                    "variant": group.variant.iloc[0],
                    "formation_sessions": int(group.formation_sessions.iloc[0]),
                    "period": period,
                    "count": len(valid),
                    "signal_dates": int(valid.trade_date.nunique()),
                    "mean_gross_return": float(valid.gross_return_h20.mean()),
                    "mean_net_return": float(returns.mean()),
                    "median_net_return": float(returns.median()),
                    "mean_excess_vs_date_control": float((returns - valid.control).mean()),
                    "severe_loss_fraction": float((returns <= -0.10).mean()),
                    "control_severe_loss_fraction": control_severe_fraction,
                    "severe_loss_disadvantage": float(
                        (returns <= -0.10).mean() - control_severe_fraction
                    ),
                    "entry_executable_fraction": float(subset.entry_status.eq("EXECUTABLE").mean()),
                    "median_candidate_count": float(subset.candidate_count.median()),
                    "median_avg_amount20_cny": float(subset.avg_amount20.median()),
                    "p10_entry_amount_cny": float(valid.entry_amount_h20.quantile(0.10)),
                }
            )
    return pd.DataFrame(rows).sort_values(["family", "period"]).reset_index(drop=True)


def _row(summary: pd.DataFrame, family: str, period: str) -> pd.Series:
    rows = summary.loc[(summary.family == family) & (summary.period == period)]
    if len(rows) != 1:
        raise Cycle010Error(f"missing summary row:{family}:{period}")
    return rows.iloc[0]


def _momentum_evidence(summary: pd.DataFrame, panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    cells = []
    for sessions, label in ((240, "12m"), (120, "6m"), (180, "9m")):
        periods = {}
        for period in ("full", "early_2018_2020", "late_2021_2023"):
            values = {}
            for variant in ("conventional", "revised"):
                top = _row(summary, f"{variant}_momentum_{label}_1m_high", period)
                bottom = _row(summary, f"{variant}_momentum_{label}_1m_low", period)
                values[variant] = {
                    "top_net": float(top.mean_net_return),
                    "bottom_net": float(bottom.mean_net_return),
                    "top_minus_bottom": float(top.mean_net_return - bottom.mean_net_return),
                    "top_excess_vs_control": float(top.mean_excess_vs_date_control),
                    "top_severe_loss_fraction": float(top.severe_loss_fraction),
                    "top_severe_loss_disadvantage": float(top.severe_loss_disadvantage),
                    "entry_execution_fraction": float(top.entry_executable_fraction),
                    "count_top": int(top["count"]),
                    "decision_dates": int(top.signal_dates),
                    "median_candidate_count": float(top.median_candidate_count),
                }
            values["spread_improvement_revised_minus_conventional"] = float(
                values["revised"]["top_minus_bottom"] - values["conventional"]["top_minus_bottom"]
            )
            periods[period] = values
        cells.append({"formation_sessions": sessions, "label": label, "periods": periods})
    primary = next(cell for cell in cells if cell["formation_sessions"] == 240)
    full = primary["periods"]["full"]
    early = primary["periods"]["early_2018_2020"]
    late = primary["periods"]["late_2021_2023"]
    gate = spec["revised_momentum"]["promotion_all_required"]
    promotion_gates = {
        "revised_top_minus_bottom_positive": full["revised"]["top_minus_bottom"] > 0,
        "revised_long_excess_positive": full["revised"]["top_excess_vs_control"] > 0,
        "revised_long_excess_nonnegative_both_blocks": min(early["revised"]["top_excess_vs_control"], late["revised"]["top_excess_vs_control"]) >= 0,
        "spread_improvement": full["spread_improvement_revised_minus_conventional"] >= gate["top_minus_bottom_improvement_vs_conventional_min"],
        "severe_loss": full["revised"]["top_severe_loss_disadvantage"] <= gate["severe_loss_disadvantage_max"],
        "execution": full["revised"]["entry_execution_fraction"] >= gate["entry_execution_fraction_min"],
        "dates_each_block": min(early["revised"]["decision_dates"], late["revised"]["decision_dates"]) >= gate["decision_dates_each_block_min"],
    }
    common = panel.loc[panel.family.isin(["conventional_momentum_12m_1m_high", "revised_momentum_12m_1m_high"])].copy()
    membership = common.pivot_table(index=["trade_date", "symbol"], columns="family", values="net_return_h20", aggfunc="first")
    membership["membership"] = np.select(
        [membership.notna().all(axis=1), membership.iloc[:, 0].notna(), membership.iloc[:, 1].notna()],
        ["common", "conventional_only", "revised_only"], default="neither"
    )
    decomposition = {}
    for group_name, rows in membership.groupby("membership"):
        values = rows.iloc[:, :2].stack()
        decomposition[group_name] = {"stock_dates": int(len(rows)), "mean_net_return": float(values.mean()) if len(values) else None}
    score_fields = common.groupby("family").agg(
        selected_rows=("symbol", "size"),
        mean_upper_limit_count=("upper_limit_count_240", "mean"),
        mean_excluded_return_mass=("excluded_return_mass_240", "mean"),
    ).to_dict("index")
    mechanism_a = full["revised"]["top_minus_bottom"] > 0 and full["spread_improvement_revised_minus_conventional"] > 0
    robustness_b = all(
        cell["periods"]["full"]["revised"]["top_minus_bottom"] > 0
        and cell["periods"]["full"]["spread_improvement_revised_minus_conventional"] > 0
        for cell in cells
    )
    long_c = promotion_gates["revised_long_excess_positive"] and promotion_gates["revised_long_excess_nonnegative_both_blocks"]
    chronological_stability = min(
        early["revised"]["top_minus_bottom"], late["revised"]["top_minus_bottom"]
    ) >= 0
    if not mechanism_a:
        classification = "MECHANISM_NOT_REPLICATED"
    elif not chronological_stability:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif not long_c:
        classification = "MECHANISM_CONFIRMED_LONG_LEG_WEAK"
    elif not robustness_b:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    else:
        classification = "MECHANISM_CONFIRMED_LONG_LEG_WEAK"
    return {
        "cells": cells,
        "promotion_gates": promotion_gates,
        "promote_replay": all(promotion_gates.values()),
        "decomposition": {"membership_outcomes": decomposition, "selected_limit_exposure": score_fields},
        "evidence_ladder": {"level_a_mechanism": mechanism_a, "level_b_construction_robustness": robustness_b, "chronological_stability": chronological_stability, "level_c_long_only_value": long_c, "level_d_executable": None},
        "classification_before_replay": classification,
    }


def _low_risk_evidence(summary: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    tests = {}
    for variable in ("max", "min"):
        periods = {}
        for period in ("full", "early_2018_2020", "late_2021_2023"):
            low = _row(summary, f"wan_{variable}_1m_low", period)
            high = _row(summary, f"wan_{variable}_1m_high", period)
            periods[period] = {
                "low_net": float(low.mean_net_return),
                "high_net": float(high.mean_net_return),
                "low_minus_high": float(low.mean_net_return - high.mean_net_return),
                "low_excess_vs_control": float(low.mean_excess_vs_date_control),
                "low_severe_loss_fraction": float(low.severe_loss_fraction),
                "low_severe_loss_disadvantage": float(low.severe_loss_disadvantage),
                "entry_execution_fraction": float(low.entry_executable_fraction),
                "count_low": int(low["count"]),
                "decision_dates": int(low.signal_dates),
                "median_candidate_count": float(low.median_candidate_count),
            }
        tests[variable] = periods
    max_full, max_early, max_late = tests["max"]["full"], tests["max"]["early_2018_2020"], tests["max"]["late_2021_2023"]
    gate = spec["low_risk"]["authorized_replay_only_if_all"]
    replay_gates = {
        "long_excess_positive": max_full["low_excess_vs_control"] > 0,
        "both_blocks": min(max_early["low_excess_vs_control"], max_late["low_excess_vs_control"]) >= 0,
        "severe_loss": max_full["low_severe_loss_disadvantage"] <= gate["severe_loss_disadvantage_max"],
        "execution": max_full["entry_execution_fraction"] >= gate["entry_execution_fraction_min"],
        "dates_each_block": min(max_early["decision_dates"], max_late["decision_dates"]) >= gate["decision_dates_each_block_min"],
    }
    max_mechanism = max_full["low_minus_high"] > 0
    min_mechanism = tests["min"]["full"]["low_minus_high"] != 0 and np.sign(tests["min"]["early_2018_2020"]["low_minus_high"]) == np.sign(tests["min"]["late_2021_2023"]["low_minus_high"])
    return {
        "canonical_ivol": "CANONICAL_IVOL_DATA_LIMITED",
        "canonical_matrix": "DATA_BLOCKED",
        "standalone_tests": tests,
        "max_mechanism_expected_low_minus_high_positive": max_mechanism,
        "min_direction_stable": bool(min_mechanism),
        "low_max_replay_gates": replay_gates,
        "promote_low_max_replay": all(replay_gates.values()),
        "internal_mapping": "NOT_RUN_CANONICAL_IVOL_ABSENT",
        "classification": "DATA_BLOCKED",
    }


def _render(result: dict[str, Any]) -> str:
    momentum = result["revised_momentum"]
    low = result["low_risk"]
    lines = [
        "# A-share evidence-backed depth cycle 010",
        "",
        "> Consumed 2018–2023 development evidence only. Post-2023 outcomes and CY-011 were not read.",
        "",
        "## Shallow versus deep conclusion",
        "",
        f"The prior JT-style 12-minus-1 Top-20 result remains adverse for that exact formulation. The matched upper-limit-corrected family is `{momentum['classification']}`; the correction was tested directly rather than inferred from the old result.",
        "",
        f"The prior Low-Idio result remains a proxy. Wan canonical IVOL is `{low['canonical_ivol']}` because PIT RMRF/SMB/HML/WML histories are not registered; MAX/MIN standalone evidence is reported without pretending the mechanism matrix was completed.",
        "",
        "## Source and execution contract",
        "",
        "Liu, Wu, and Zhu (2022) motivate removal of upper-limit closes and their next trading session; Wan (2018) motivates the IVOL-versus-MAX/MIN separation. Full recovered methods and unresolved source details are frozen in `A_SHARE_DEPTH_CYCLE_010_SOURCE_METHOD.md`.",
        "",
        f"The monthly domain contains {result['feature_frame']['rows']:,} eligible rows, {result['feature_frame']['symbols']:,} symbols, and {result['feature_frame']['decision_dates']} decision dates from {result['feature_frame']['first']} through {result['feature_frame']['last']}. Signals use completed 15:00 data and no fill before the next legal open; historical board/ST price limits, T+1, suspensions, corporate actions, and 20 bps/side are preserved.",
        "",
        "## Revised momentum",
        "",
        "| formation | period | conventional top | conventional bottom | conventional spread | revised top | revised bottom | revised spread | spread improvement |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in momentum["cells"]:
        for period, values in cell["periods"].items():
            c, r = values["conventional"], values["revised"]
            lines.append(f"| {cell['label']} | {period} | {c['top_net']:.3%} | {c['bottom_net']:.3%} | {c['top_minus_bottom']:.3%} | {r['top_net']:.3%} | {r['bottom_net']:.3%} | {r['top_minus_bottom']:.3%} | {values['spread_improvement_revised_minus_conventional']:.3%} |")
    lines.extend([
        "",
        f"Promotion gates: `{momentum['promotion_gates']}`.",
        "",
        f"Evidence ladder: `{momentum['evidence_ladder']}`.",
        "",
        f"Primary revised-top coverage is {momentum['cells'][0]['periods']['full']['revised']['count_top']:,} complete stock-months across {momentum['cells'][0]['periods']['full']['revised']['decision_dates']} dates, with {momentum['cells'][0]['periods']['full']['revised']['entry_execution_fraction']:.2%} next-open executability and median breadth {momentum['cells'][0]['periods']['full']['revised']['median_candidate_count']:.0f}.",
        "",
        "## Low-risk / lottery mechanisms",
        "",
        "| variable | period | low net | high net | low-minus-high | low excess vs control | low severe disadvantage |",
        "|---|---|---:|---:|---:|---:|---:|",
    ])
    for variable, periods in low["standalone_tests"].items():
        for period, values in periods.items():
            lines.append(f"| {variable.upper()} | {period} | {values['low_net']:.3%} | {values['high_net']:.3%} | {values['low_minus_high']:.3%} | {values['low_excess_vs_control']:.3%} | {values['low_severe_loss_disadvantage']:.3%} |")
    lines.extend([
        "",
        f"Low-MAX replay gates: `{low['low_max_replay_gates']}`.",
        "",
        f"Low-MAX has {low['standalone_tests']['max']['full']['count_low']:,} complete stock-months across {low['standalone_tests']['max']['full']['decision_dates']} dates, {low['standalone_tests']['max']['full']['entry_execution_fraction']:.2%} next-open executability, and median breadth {low['standalone_tests']['max']['full']['median_candidate_count']:.0f}.",
        "",
        "The canonical IVOL × MAX/MIN two-way sort, residual challenge, and mapping of internal defensive leads were not run because canonical IVOL inputs failed the data gate.",
        "",
        "## Executable replays",
        "",
    ])
    if result["replays"]:
        for replay in result["replays"]:
            if replay.get("status") == "REPLAY_BLOCKED":
                lines.append(f"- `{replay['family']}`: blocked fail-closed — {replay['error']}")
            else:
                lines.append(f"- `{replay['family']}`: total {replay['total_return']:.2%}, annualized {replay['annualized_return']:.2%}, excess vs control {replay['total_return_excess_vs_control']:.2%}, max drawdown {replay['maximum_drawdown']:.2%}, Sharpe {replay['daily_sharpe']:.3f}, severe {replay['severe_trade_fraction']:.2%}, turnover {replay['turnover_multiple']:.2f}x, entries {replay['entries']}, classification `{replay['classification']}`.")
    else:
        lines.append("No replay was authorized by the frozen gates.")
    lines.extend([
        "",
        "## Optional third family",
        "",
        "Not run. Exact left-tail reversal was not recovered; canonical residual momentum remains factor-data blocked.",
        "",
        "## Final classifications",
        "",
        f"- Revised momentum: `{momentum['classification']}`",
        f"- Canonical IVOL mechanism matrix: `{low['classification']}`",
        f"- MAX standalone: `{result['family_classifications']['max']}`",
        f"- MIN standalone: `{result['family_classifications']['min']}`",
        "",
    ])
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = CYCLE5.CYCLE4._input_paths()
    external_temp_root = Path("/Volumes/quant")
    if not external_temp_root.is_dir() or not os.access(external_temp_root, os.W_OK):
        raise Cycle010Error("verified external temp root unavailable")
    with tempfile.TemporaryDirectory(prefix="ashare-depth-cycle-010-", dir=external_temp_root) as temporary:
        frame, calendar, audit = _build_frame(daily_paths, Path(temporary))
    selections, diagnostics = _selections(frame, spec)
    panel, path_rows = CYCLE5._attach_outcomes(daily_paths, selections, calendar)
    summary = _summary(panel)
    momentum = _momentum_evidence(summary, panel, spec)
    low_risk = _low_risk_evidence(summary, spec)
    replay_families = []
    if momentum["promote_replay"]:
        replay_families.append("revised_momentum_12m_1m_high")
    if low_risk["promote_low_max_replay"]:
        replay_families.append("wan_max_1m_low")
    replays, equity, risk_exits = CYCLE8._replay_families(panel, replay_families, daily_paths, calendar)
    replay_by_family = {row["family"]: row for row in replays}
    momentum_replay = replay_by_family.get("revised_momentum_12m_1m_high")
    momentum["replay"] = momentum_replay
    if momentum_replay is not None:
        momentum["evidence_ladder"]["level_d_executable"] = momentum_replay.get("classification") in {"STRATEGY_CANDIDATE", "PROMISING_BUT_MIXED"}
        if momentum_replay.get("classification") == "STRATEGY_CANDIDATE":
            momentum["classification"] = "MECHANISM_CONFIRMED_STRATEGY_CANDIDATE"
        elif momentum_replay.get("status") == "REPLAY_BLOCKED":
            momentum["classification"] = "MECHANISM_CONFIRMED_IMPLEMENTATION_CONFLICT"
    else:
        momentum["classification"] = momentum["classification_before_replay"]
    max_full = low_risk["standalone_tests"]["max"]["full"]
    max_early = low_risk["standalone_tests"]["max"]["early_2018_2020"]
    max_late = low_risk["standalone_tests"]["max"]["late_2021_2023"]
    if max_full["low_minus_high"] <= 0:
        max_class = "MECHANISM_NOT_REPLICATED"
    elif min(max_early["low_minus_high"], max_late["low_minus_high"]) < 0:
        max_class = "CHRONOLOGICALLY_UNSTABLE"
    else:
        max_class = "MECHANISM_CONFIRMED_LONG_LEG_WEAK"
    min_full = low_risk["standalone_tests"]["min"]["full"]
    min_early = low_risk["standalone_tests"]["min"]["early_2018_2020"]
    min_late = low_risk["standalone_tests"]["min"]["late_2021_2023"]
    min_class = "CHRONOLOGICALLY_UNSTABLE" if np.sign(min_early["low_minus_high"]) != np.sign(min_late["low_minus_high"]) else ("MECHANISM_CONFIRMED_LONG_LEG_WEAK" if min_full["low_minus_high"] != 0 else "MECHANISM_NOT_REPLICATED")
    result = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "honesty_boundary": spec["honesty_boundary"],
        "source_reconciliation": {
            "document": str(SPEC_PATH.parent.parent / "A_SHARE_DEPTH_CYCLE_010_SOURCE_METHOD.md"),
            "revised_momentum_main_cell_uncertainty": "unique Table-3 horizon/weighting not exposed; 12m/1m EW is labeled a paper-specified representative primary cell",
            "canonical_ivol": "CANONICAL_IVOL_DATA_LIMITED",
            "third_family": "NOT_RUN_EXACT_METHOD_NOT_RECOVERED",
            "residual_momentum": "DATA_BLOCKED_FOR_CANONICAL_REPLICATION",
        },
        "input_audit": audit,
        "feature_frame": {"rows": len(frame), "symbols": int(frame.symbol.nunique()), "decision_dates": int(frame.trade_date.nunique()), "first": str(frame.trade_date.min()), "last": str(frame.trade_date.max())},
        "selection_diagnostics": diagnostics.to_dict("records"),
        "outcome_path_rows": path_rows,
        "revised_momentum": momentum,
        "low_risk": low_risk,
        "replays": replays,
        "family_classifications": {"revised_momentum": momentum["classification"], "canonical_ivol": "DATA_BLOCKED", "max": max_class, "min": min_class, "optional_third_family": "DATA_BLOCKED"},
        "preserved_exact_results": {
            "jt_momentum_12_1_top20": "ADVERSE_UNCHANGED",
            "max_lottery_20_top20": "ADVERSE_UNCHANGED",
            "low_idio": "PROMISING_BUT_MIXED_PROXY_UNCHANGED",
            "low_vol_of_vol": "COMPLEMENTARY_LOW_RISK_INFORMATION_UNCHANGED",
            "low_skewness": "COMPLEMENTARY_DEFENSIVE_INFORMATION_UNCHANGED",
        },
        "questions": {
            "what_market_behavior_are_we_still_not_studying": "Canonical PIT factor-residual risk, immutable-vintage fundamentals, order-book/queue pressure, borrow-feasible short legs, and independent post-development confirmation.",
            "new_strategy_archetype_implied": False,
        },
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(SUMMARY_PATH, index=False)
    equity.to_csv(EQUITY_PATH, index=False)
    risk_exits.to_csv(EXIT_PATH, index=False)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "summary_sha256": sha256_file(SUMMARY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(EXIT_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
