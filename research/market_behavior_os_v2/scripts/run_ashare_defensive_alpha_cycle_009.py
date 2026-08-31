#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen defensive-independence audit and six-family alpha screen."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_result.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_panel.csv"
SUMMARY_PATH = PROGRAM / "artifacts/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_summary.csv"
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_equity.csv"
EXIT_PATH = PROGRAM / "artifacts/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_risk_exits.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-DEFENSIVE-ALPHA-DISCOVERY-CYCLE-009_report.md"
CYCLE8_PATH = PROGRAM / "scripts/run_ashare_skew_breakdown_discovery_cycle_008.py"
EXPECTED_SPEC_SHA256 = "6b061236608b4e24b6bd01908c16c5a203d5a9ebc6c33c4f4b864c05bcf9619f"


class Cycle009Error(RuntimeError):
    """Fail-closed cycle-009 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise Cycle009Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE8 = _load_module("ashare_cycle_008_for_009", CYCLE8_PATH)
CYCLE5 = CYCLE8.CYCLE5


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Cycle009Error("frozen cycle-009 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CYCLE_009_FORWARD_OUTCOME_ACCESS":
        raise Cycle009Error("cycle-009 was not frozen before outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise Cycle009Error(f"bound input changed: {name}")
    return spec


def _feature_frame(daily_paths: list[Path], temp_path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    con.execute("SET memory_limit='6GB'")
    con.execute("SET threads=1")
    con.execute(f"SET temp_directory='{temp_path.as_posix()}'")
    con.execute("SET preserve_insertion_order=false")
    con.from_parquet([str(path) for path in daily_paths], union_by_name=True).create_view("daily")
    con.execute("""CREATE TEMP TABLE calendar AS SELECT trade_date,
        row_number() OVER (ORDER BY trade_date)-1 cal_idx
        FROM (SELECT DISTINCT trade_date FROM daily)""")
    con.execute("""CREATE TEMP TABLE base AS SELECT d.*,c.cal_idx,
        (d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0) history_valid,
        lag(d.close) OVER w previous_close,lag(c.cal_idx) OVER w previous_cal_idx,
        lag(d.hard_valid IS TRUE AND d.bar_valid IS TRUE AND d.trading_state_valid IS TRUE
         AND d.industry_valid IS TRUE AND d.float_valid IS TRUE
         AND d.corporate_action_valid IS TRUE AND d.market_valid IS TRUE
         AND d.market_rule_valid IS TRUE AND d.historical_identity_valid IS TRUE
         AND d.corporate_action_blocking IS FALSE AND coalesce(d.rights_ratio,0)=0
         AND d.available_at IS NOT NULL AND d.available_at<=d.decision_at
         AND d.open>0 AND d.high>=greatest(d.open,d.close)
         AND d.low<=least(d.open,d.close) AND d.close>0 AND d.volume>=0 AND d.amount>=0) OVER w previous_history_valid
        FROM daily d JOIN calendar c USING(trade_date)
        WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)""")
    con.execute("""CREATE TEMP TABLE steps AS SELECT *,CASE
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
        WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
         AND corporate_action_count>0 AND corporate_action_available_date IS NOT NULL
         AND corporate_action_available_date<=trade_date AND coalesce(rights_ratio,0)=0
         AND coalesce(share_multiplier,1)>0 AND previous_close-coalesce(cash_per_share,0)>0
        THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
        ELSE NULL END step_return FROM base""")
    con.execute("""CREATE TEMP TABLE with_market AS SELECT *,
        median(step_return) OVER (PARTITION BY trade_date) market_step FROM steps""")
    con.execute("""CREATE TEMP TABLE paths AS SELECT *,step_return-market_step residual_step,
        sum(coalesce(step_return,0)) OVER (PARTITION BY symbol ORDER BY trade_date) log_coordinate
        FROM with_market""")
    con.execute("""CREATE TEMP TABLE components AS SELECT *,
        exp(log_coordinate)*open/close coordinate_open,
        lag(exp(log_coordinate)) OVER (PARTITION BY symbol ORDER BY trade_date) previous_coordinate_close,
        ln(close/open) daytime_return FROM paths""")
    features = con.execute("""SELECT trade_date,symbol,cal_idx,
        sum(residual_step) OVER w20 residual_return20,
        sum(residual_step) OVER w60 residual_return60,
        sum((residual_step>0)::INTEGER) OVER w60 positive_residual_days60,
        sum((residual_step<0)::INTEGER) OVER w60 negative_residual_days60,
        count(residual_step) OVER w60 residual_count60,
        avg(turnover_fraction) OVER w60 turnover_mean60,
        count(turnover_fraction) OVER w60 turnover_count60,
        sum((coordinate_open>previous_coordinate_close AND daytime_return<0)::INTEGER) OVER w20 tug_count20,
        count(previous_coordinate_close) OVER w20 tug_domain20
        FROM components WINDOW
        w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
        w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
        QUALIFY cal_idx%20=0 ORDER BY trade_date,symbol""").fetchdf()
    monthly = con.execute("""SELECT symbol,year(trade_date) report_year,month(trade_date) report_month,
        sum(step_return) same_month_return,count(step_return) month_count
        FROM steps WHERE step_return IS NOT NULL GROUP BY symbol,report_year,report_month""").fetchdf()
    con.close()
    prior = monthly.rename(
        columns={
            "report_year": "prior_year",
            "report_month": "month",
            "same_month_return": "seasonal_return",
            "month_count": "seasonal_count",
        }
    )
    features["year"] = pd.to_datetime(features.trade_date).dt.year
    features["month"] = pd.to_datetime(features.trade_date).dt.month
    features["prior_year"] = features.year - 1
    return features.merge(prior, on=["symbol", "prior_year", "month"], how="left")


def _ranks_and_scores(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = frame.sort_values(["symbol", "trade_date"]).copy()

    def pct(values: pd.Series) -> pd.Series:
        return values.rank(method="average", pct=True)

    work["vov_rank"] = work.groupby("trade_date").low_volatility_of_volatility_60.transform(pct)
    work["idio_rank"] = work.groupby("trade_date").low_idio_score.transform(pct)
    work["relative_rank"] = work.groupby("trade_date").residual_return20.transform(pct)
    work["industry_rank"] = work.groupby(["trade_date", "industry"]).residual_return20.transform(
        pct
    )
    for column in ("relative_rank", "industry_rank"):
        work[f"prior_{column}"] = work.groupby("symbol")[column].shift(1)
    work["prior_cal_idx"] = work.groupby("symbol").cal_idx.shift(1)
    exact_lag = work.cal_idx - work.prior_cal_idx == 20
    work["market_relative_rank_acceleration_20"] = (
        work.relative_rank - work.prior_relative_rank
    ).where(exact_lag)
    work["industry_follower_rank_acceleration_20"] = (
        work.industry_rank - work.prior_industry_rank
    ).where(exact_lag & (work.prior_industry_rank < 0.5))
    discreteness = np.sign(work.residual_return60) * (
        (work.negative_residual_days60 - work.positive_residual_days60) / work.residual_count60
    )
    work["fip_continuous_good_news_60"] = (-discreteness).where(
        (work.residual_return60 > 0) & (work.residual_count60 == 60)
    )
    work["same_month_seasonality_1y"] = work.seasonal_return.where(work.seasonal_count >= 15)
    work["overnight_daytime_tug_of_war_20"] = (work.tug_count20 / work.tug_domain20).where(
        work.tug_domain20 == 20
    )
    work["low_turnover_attention_60"] = (-work.turnover_mean60).where(work.turnover_count60 == 60)

    def residualize(group: pd.DataFrame) -> pd.Series:
        x, y = group.idio_rank.to_numpy(float), group.vov_rank.to_numpy(float)
        beta = 0.0 if np.var(x) == 0 else float(np.cov(x, y, ddof=0)[0, 1] / np.var(x))
        return pd.Series(y - (y.mean() - beta * x.mean()) - beta * x, index=group.index)

    work["vov_residual_rank"] = work.groupby("trade_date", group_keys=False).apply(
        residualize, include_groups=False
    )
    corr = work.groupby("trade_date").apply(
        lambda group: group.vov_rank.corr(group.idio_rank), include_groups=False
    )
    years = pd.to_datetime(pd.Series(corr.index)).dt.year.to_numpy()
    values = corr.to_numpy(float)
    relationship = {
        "median_same_date_rank_correlation": float(np.nanmedian(values)),
        "early_median": float(np.nanmedian(values[years <= 2020])),
        "late_median": float(np.nanmedian(values[years >= 2021])),
        "dates": int(np.isfinite(values).sum()),
    }
    work["idio_tertile"] = work.groupby("trade_date").idio_rank.transform(
        lambda x: pd.qcut(x.rank(method="first"), 3, labels=["low", "middle", "high"]).astype(str)
    )
    work["vov_tertile"] = work.groupby("trade_date").vov_rank.transform(
        lambda x: pd.qcut(x.rank(method="first"), 3, labels=["low", "middle", "high"]).astype(str)
    )
    return work, relationship


def _select(
    frame: pd.DataFrame,
    family: str,
    score: pd.Series,
    track: str,
    control: str,
    count: int = 20,
    ascending: bool = False,
) -> pd.DataFrame:
    work = frame.loc[np.isfinite(score)].copy()
    work["signal_score"] = score.loc[work.index]
    work["family"], work["track"], work["control_family"] = family, track, control
    work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
    work = (
        work.sort_values(
            ["trade_date", "signal_score", "symbol"], ascending=[True, ascending, True]
        )
        .groupby("trade_date")
        .head(count)
    )
    work["signal_rank"] = work.groupby("trade_date").cumcount() + 1
    return work


def _control(
    frame: pd.DataFrame, family: str, seed: str, track: str = "control", count: int = 20
) -> pd.DataFrame:
    work = frame.copy()
    work["hash_order"] = work.apply(
        lambda row: hashlib.sha256(f"{row.symbol}|{seed}|{row.trade_date}".encode()).hexdigest(),
        axis=1,
    )
    work = (
        work.sort_values(["trade_date", "hash_order", "symbol"]).groupby("trade_date").head(count)
    )
    work["family"], work["track"], work["control_family"] = family, track, family
    work["candidate_count"] = work.groupby("trade_date").symbol.transform("size")
    work["signal_score"], work["signal_rank"] = np.nan, work.groupby("trade_date").cumcount() + 1
    return work


def _selections(frame: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    output: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []

    def add(selection: pd.DataFrame) -> None:
        output.append(selection)
        diagnostics.append(
            {
                "family": selection.family.iloc[0],
                "track": selection.track.iloc[0],
                "selected_rows": len(selection),
                "decision_dates": int(selection.trade_date.nunique()),
                "symbols": int(selection.symbol.nunique()),
                "median_candidates": float(selection.candidate_count.median()),
                "median_avg_amount20_cny": float(selection.avg_amount20.median()),
            }
        )

    add(_control(frame, "date_control", "009"))
    add(
        _select(
            frame,
            "low_vov_residual_to_low_idio",
            frame.vov_residual_rank,
            "track_a_residual",
            "date_control",
        )
    )
    for stratum in ("low", "middle", "high"):
        a = frame.loc[frame.idio_tertile.eq(stratum)]
        control = f"control_idio_{stratum}"
        add(_control(a, control, f"009I{stratum}"))
        add(
            _select(
                a,
                f"low_vov_within_idio_{stratum}",
                a.low_volatility_of_volatility_60,
                "track_a_conditional",
                control,
            )
        )
        a = frame.loc[frame.vov_tertile.eq(stratum)]
        control = f"control_vov_{stratum}"
        add(_control(a, control, f"009V{stratum}"))
        add(
            _select(
                a,
                f"low_idio_within_vov_{stratum}",
                a.low_idio_score,
                "track_a_conditional",
                control,
            )
        )
    valid_industry = frame.groupby(["trade_date", "industry"]).symbol.transform("size") >= 10
    industry = frame.loc[valid_industry].copy()
    industry["within_vov"] = industry.groupby(
        ["trade_date", "industry"]
    ).low_volatility_of_volatility_60.transform(lambda x: x.rank(method="average", pct=True))
    high = (
        industry.sort_values(
            ["trade_date", "industry", "within_vov", "symbol"], ascending=[True, True, False, True]
        )
        .groupby(["trade_date", "industry"])
        .head(3)
    )
    low = (
        industry.sort_values(
            ["trade_date", "industry", "within_vov", "symbol"], ascending=[True, True, True, True]
        )
        .groupby(["trade_date", "industry"])
        .head(3)
    )
    for selection, family, control in (
        (high, "low_vov_within_industry_high", "low_vov_within_industry_low"),
        (low, "low_vov_within_industry_low", "low_vov_within_industry_low"),
    ):
        selection = selection.copy()
        selection["family"], selection["track"], selection["control_family"] = (
            family,
            "track_a_industry",
            control,
        )
        selection["candidate_count"] = selection.groupby("trade_date").symbol.transform("size")
        selection["signal_score"] = selection.within_vov
        selection["signal_rank"] = selection.groupby("trade_date").cumcount() + 1
        add(selection)
    low_idio_candidates = (
        frame.sort_values(["trade_date", "low_idio_score", "symbol"], ascending=[True, False, True])
        .groupby("trade_date")
        .head(20)
    )
    add(
        _select(
            low_idio_candidates,
            "low_vov_refinement_of_low_idio",
            low_idio_candidates.low_volatility_of_volatility_60,
            "track_a_translation",
            "date_control",
            count=10,
        )
    )
    for hypothesis in spec["track_b"]:
        family = hypothesis["id"]
        add(_select(frame, family, frame[family], "track_b", "date_control"))
    selection = pd.concat(output, ignore_index=True)
    selection["natural_horizon"], selection["rebalance_sessions"] = 20, 20
    selection["decision_at"] = pd.to_datetime(selection.trade_date) + pd.Timedelta(
        hours=15, minutes=30
    )
    columns = [
        "family",
        "track",
        "control_family",
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "signal_score",
        "signal_rank",
        "candidate_count",
        "avg_amount20",
        "natural_horizon",
        "rebalance_sessions",
    ]
    return selection[columns].sort_values(
        ["family", "trade_date", "signal_rank", "symbol"]
    ).reset_index(drop=True), pd.DataFrame(diagnostics)


def _summary(panel: pd.DataFrame) -> pd.DataFrame:
    years = pd.to_datetime(panel.trade_date).dt.year
    masks = {
        "full": pd.Series(True, index=panel.index),
        "early_2018_2020": years <= 2020,
        "late_2021_2023": years >= 2021,
    }
    daily: dict[str, dict[str, pd.Series]] = {}
    for family, group in panel.groupby("family"):
        valid = group.loc[group.status_h20.eq("COMPLETE")]
        daily[family] = {
            "return": valid.groupby("trade_date").net_return_h20.mean(),
            "severe": valid.groupby("trade_date").net_return_h20.apply(
                lambda x: float((x <= -0.10).mean())
            ),
        }
    rows = []
    for family, group in panel.loc[~panel.track.eq("control")].groupby("family", sort=True):
        control = str(group.control_family.iloc[0])
        comparison = daily[control]
        for period, mask in masks.items():
            subset = group.loc[mask.loc[group.index]]
            valid = subset.loc[subset.status_h20.eq("COMPLETE")].copy()
            valid["control"] = valid.trade_date.map(comparison["return"])
            valid["control_severe"] = valid.trade_date.map(comparison["severe"])
            valid = valid.dropna(subset=["control", "control_severe"])
            returns = valid.net_return_h20.astype(float)
            rows.append(
                {
                    "family": family,
                    "track": group.track.iloc[0],
                    "control_family": control,
                    "period": period,
                    "horizon": 20,
                    "count": len(valid),
                    "signal_dates": int(valid.trade_date.nunique()),
                    "mean_net_return": returns.mean(),
                    "median_net_return": returns.median(),
                    "net_excess_vs_control": (returns - valid.control).mean(),
                    "severe_loss_fraction": float((returns <= -0.10).mean()),
                    "control_severe_fraction": float(
                        valid.groupby("trade_date").control_severe.first().mean()
                    ),
                    "entry_executable_fraction": float(subset.entry_status.eq("EXECUTABLE").mean()),
                    "median_candidate_count": float(subset.candidate_count.median()),
                    "p10_entry_amount_cny": valid.entry_amount_h20.quantile(0.10),
                }
            )
    return pd.DataFrame(rows).sort_values(["family", "period"]).reset_index(drop=True)


def _period(summary: pd.DataFrame, family: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    rows = summary.loc[summary.family.eq(family)].set_index("period")
    return rows.loc["full"], rows.loc["early_2018_2020"], rows.loc["late_2021_2023"]


def _minute_overlap(frame: pd.DataFrame) -> dict[str, Any]:
    daily = (
        frame.groupby("trade_date")
        .agg(
            median_low_vov_rank=("vov_rank", "median"),
            median_low_idio_rank=("idio_rank", "median"),
        )
        .reset_index()
    )
    minute = pd.read_csv(
        PROGRAM / "artifacts/MKT-MIN-PATH-002_nonslope_panel.csv",
        usecols=[
            "trade_date",
            "market_view",
            "denominator",
            "hard_valid",
            "minute_realized_volatility__ordinal_progression__pit_3y_pct",
        ],
    )
    minute = minute.loc[
        minute.market_view.eq("ALL_A") & minute.denominator.eq("NON_ST") & minute.hard_valid
    ]
    daily["trade_date"] = pd.to_datetime(daily.trade_date).dt.date
    minute["trade_date"] = pd.to_datetime(minute.trade_date).dt.date
    merged = daily.merge(minute, on="trade_date", how="inner")
    vov_variation = float(merged.median_low_vov_rank.std())
    idio_variation = float(merged.median_low_idio_rank.std())
    return {
        "dates": len(merged),
        "median_low_vov_rank_time_series_std": vov_variation,
        "median_low_idio_rank_time_series_std": idio_variation,
        "spearman_median_low_vov_rank_vs_market_minute_path": None,
        "spearman_median_low_idio_rank_vs_market_minute_path": None,
        "classification": "NON_IDENTIFYING_INVARIANT_CROSS_SECTIONAL_MEDIAN",
        "interpretation_boundary": "the frozen cross-sectional percentile median is invariant by construction while the market state is constant within date; neither a temporal nor stock-level cross-sectional association is identified, and no combined rule was constructed",
    }


def _decisions(
    summary: pd.DataFrame, diagnostics: pd.DataFrame, spec: dict[str, Any]
) -> list[dict[str, Any]]:
    diag = diagnostics.set_index("family").to_dict("index")
    rows = []
    for hypothesis in spec["track_b"]:
        family = hypothesis["id"]
        full, early, late = _period(summary, family)
        severe = float(full.severe_loss_fraction - full.control_severe_fraction)
        gates = {
            "complete_positions": int(full["count"]) >= 300,
            "dates_each_block": int(early.signal_dates) >= 20 and int(late.signal_dates) >= 20,
            "execution": float(full.entry_executable_fraction) >= 0.90,
            "full_excess": float(full.net_excess_vs_control) > 0,
            "both_blocks": min(
                float(early.net_excess_vs_control), float(late.net_excess_vs_control)
            )
            >= 0,
            "severe_loss": severe <= 0.02,
            "breadth": float(full.median_candidate_count) >= 20,
        }
        if all(gates.values()):
            classification = "STANDALONE_ALPHA"
        elif float(early.net_excess_vs_control) * float(late.net_excess_vs_control) < 0:
            classification = "CHRONOLOGICALLY_MIXED"
        elif severe < -0.01 and float(full.net_excess_vs_control) >= 0:
            classification = "DEFENSIVE_INFORMATION"
        elif float(full.net_excess_vs_control) < 0:
            classification = "ADVERSE"
        else:
            classification = "ECONOMICALLY_NULL"
        rows.append(
            {
                "family": family,
                "source": hypothesis["source"],
                "mechanism": hypothesis["mechanism"],
                "classification": classification,
                "passes_all_screen_gates": all(gates.values()),
                "gates": gates,
                "net_excess": float(full.net_excess_vs_control),
                "early_excess": float(early.net_excess_vs_control),
                "late_excess": float(late.net_excess_vs_control),
                "severe_loss_disadvantage": severe,
                "complete_positions": int(full["count"]),
                "signal_dates": int(full.signal_dates),
                "diagnostics": diag[family],
                "replay_decision": "NO_REPLAY",
            }
        )
    eligible = sorted(
        [x for x in rows if x["passes_all_screen_gates"]],
        key=lambda x: (min(x["early_excess"], x["late_excess"]), x["net_excess"]),
        reverse=True,
    )
    for row in eligible[:3]:
        row["replay_decision"] = "PROMOTE_EXECUTABLE"
    return rows


def _track_a(
    summary: pd.DataFrame, relationship: dict[str, Any], minute: dict[str, Any]
) -> dict[str, Any]:
    residual, re, rl = _period(summary, "low_vov_residual_to_low_idio")
    residual_values = [
        float(residual.net_excess_vs_control),
        float(re.net_excess_vs_control),
        float(rl.net_excess_vs_control),
    ]
    conditional = {}
    reverse = {}
    for s in ("low", "middle", "high"):
        full, early, late = _period(summary, f"low_vov_within_idio_{s}")
        conditional[s] = {
            "full": float(full.net_excess_vs_control),
            "early": float(early.net_excess_vs_control),
            "late": float(late.net_excess_vs_control),
        }
        full, early, late = _period(summary, f"low_idio_within_vov_{s}")
        reverse[s] = {
            "full": float(full.net_excess_vs_control),
            "early": float(early.net_excess_vs_control),
            "late": float(late.net_excess_vs_control),
        }
    full, early, late = _period(summary, "low_vov_within_industry_high")
    industry = {
        "full_payoff_spread": float(full.net_excess_vs_control),
        "early_payoff_spread": float(early.net_excess_vs_control),
        "late_payoff_spread": float(late.net_excess_vs_control),
        "full_severe_loss_spread": float(full.severe_loss_fraction - full.control_severe_fraction),
        "coverage": int(full["count"]),
        "dates": int(full.signal_dates),
    }
    independent = (
        abs(relationship["median_same_date_rank_correlation"]) < 0.5 and min(residual_values) > 0
    )
    industry_pass = (
        min(
            industry["full_payoff_spread"],
            industry["early_payoff_spread"],
            industry["late_payoff_spread"],
        )
        > 0
        and industry["full_severe_loss_spread"] <= 0
    )
    if independent and industry_pass:
        classification = "DISTINCT_DEFENSIVE_INFORMATION"
    elif industry_pass and (
        min(residual_values) > 0 or sum(x["full"] > 0 for x in conditional.values()) >= 2
    ):
        classification = "COMPLEMENTARY_LOW_RISK_INFORMATION"
    elif abs(relationship["median_same_date_rank_correlation"]) >= 0.7:
        classification = "MOSTLY_REDUNDANT_WITH_LOW_IDIO"
    else:
        classification = "NO_INCREMENTAL_VALUE"
    return {
        "classification": classification,
        "independence_gate": independent,
        "industry_gate": industry_pass,
        "relationship": relationship,
        "residual": {
            "full": residual_values[0],
            "early": residual_values[1],
            "late": residual_values[2],
        },
        "low_vov_within_low_idio_tertiles": conditional,
        "low_idio_within_low_vov_tertiles": reverse,
        "industry_neutral": industry,
        "minute_overlap": minute,
        "translation_authorized": independent and industry_pass,
    }


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
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


def _atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _render(result: dict[str, Any]) -> str:
    a = result["track_a"]
    lines = [
        "# Defensive-factor independence audit and new alpha discovery",
        "",
        f"Status: `{result['status']}`.",
        "",
        "## Track A",
        "",
        f"Low Vol-of-Vol classification: `{a['classification']}`. Median rank correlation with Low Idio: {a['relationship']['median_same_date_rank_correlation']:.3f} ({a['relationship']['early_median']:.3f}/{a['relationship']['late_median']:.3f}).",
        f"Residual excess: {a['residual']['full']:.3%} full, {a['residual']['early']:.3%} early, {a['residual']['late']:.3%} late. Within-industry high-minus-low spread: {a['industry_neutral']['full_payoff_spread']:.3%} full, {a['industry_neutral']['early_payoff_spread']:.3%} early, {a['industry_neutral']['late_payoff_spread']:.3%} late. Translation authorized: `{a['translation_authorized']}`.",
        "",
        "## Track B",
        "",
        "| Family | Net excess | Early | Late | Severe disadvantage | Classification | Replay |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in result["track_b"]["decisions"]:
        lines.append(
            f"| {row['family']} | {row['net_excess']:.3%} | {row['early_excess']:.3%} | {row['late_excess']:.3%} | {row['severe_loss_disadvantage']:.3%} | {row['classification']} | {row['replay_decision']} |"
        )
    for row in result["replays"]:
        lines += [
            "",
            f"Executable `{row['family']}`: total {row.get('total_return', float('nan')):.2%}, annualized {row.get('annualized_return', float('nan')):.2%}, max drawdown {row.get('maximum_drawdown', float('nan')):.2%}, Sharpe {row.get('daily_sharpe', float('nan')):.3f}, classification `{row['classification']}`.",
        ]
    lines += [
        "",
        "All evidence is consumed 2018-2023 development research. Post-2023 outcomes and CY-011 were not read.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_paths, _ = CYCLE5.CYCLE4._input_paths()
    with tempfile.TemporaryDirectory(prefix="ashare-cycle-009-") as temporary:
        base, calendar, _, _, audit = CYCLE8._build_frame(daily_paths, Path(temporary))
        features = _feature_frame(daily_paths, Path(temporary))
    frame = base.merge(
        features, on=["trade_date", "symbol", "cal_idx"], how="left", validate="one_to_one"
    )
    frame, relationship = _ranks_and_scores(frame)
    selections, diagnostics = _selections(frame, spec)
    panel, path_rows = CYCLE5._attach_outcomes(daily_paths, selections, calendar)
    summary = _summary(panel)
    minute = _minute_overlap(frame)
    track_a = _track_a(summary, relationship, minute)
    decisions = _decisions(summary, diagnostics, spec)
    replay_families = [
        row["family"] for row in decisions if row["replay_decision"] == "PROMOTE_EXECUTABLE"
    ]
    if track_a["translation_authorized"]:
        replay_families.insert(0, "low_vov_refinement_of_low_idio")
    replays, equity, exits = CYCLE8._replay_families(panel, replay_families, daily_paths, calendar)
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_BOUNDED_AUDIT_AND_ALPHA_SCREEN",
        "honesty_boundary": spec["honesty_boundary"],
        "input_audit": audit,
        "eligible_rows": len(frame),
        "eligible_symbols": int(frame.symbol.nunique()),
        "decision_dates": int(frame.trade_date.nunique()),
        "future_path_rows_read": path_rows,
        "track_a": {
            **track_a,
            "definition": spec["track_a"],
            "replay": next(
                (x for x in replays if x["family"] == "low_vov_refinement_of_low_idio"), None
            ),
            "final_status": (
                "USEFUL_DEFENSIVE_COMPONENT"
                if track_a["translation_authorized"]
                and next(
                    (x for x in replays if x["family"] == "low_vov_refinement_of_low_idio"), {}
                ).get("classification")
                == "STRATEGY_CANDIDATE"
                else "PARKED_AUDIT_GATE"
            ),
        },
        "track_b": {"hypotheses": spec["track_b"], "decisions": decisions},
        "replays": [x for x in replays if x["family"] != "low_vov_refinement_of_low_idio"],
        "preserved_portfolio": {
            "low_idio": "PROMISING_BUT_MIXED_UNCHANGED",
            "low_skewness": "COMPLEMENTARY_DEFENSIVE_UNCHANGED",
            "confirmed_breakdown": "PARKED_NO_AFFECTED_DECISIONS_UNCHANGED",
            "chinext_rs_veto": "PROMISING_ADMISSION_COMPONENT_UNCHANGED",
            "industry_diffusion_family": "UNCHANGED",
            "minute_volatility_overlay": "COST_SENSITIVE_UNCHANGED",
            "pit_fundamentals": "DATA_BLOCKED_PARKED",
        },
        "questions": {
            "what_market_behavior_are_we_still_not_studying": "Order-book/queue pressure, borrow-feasible short legs, immutable-vintage fundamentals, investor-flow identity, and independent post-development confirmation.",
            "new_strategy_archetype_implied": None,
        },
    }
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False)
    summary.to_csv(SUMMARY_PATH, index=False)
    equity.to_csv(EQUITY_PATH, index=False)
    exits.to_csv(EXIT_PATH, index=False)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "summary_sha256": sha256_file(SUMMARY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
        "risk_exits_sha256": sha256_file(EXIT_PATH),
    }
    _atomic(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
