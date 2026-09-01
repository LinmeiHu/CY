#!/usr/bin/env python3
"""Diagnose 2018 and 2022 failure modes of the frozen champion."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_result.json"
ANNUAL_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_annual.csv"
MONTHLY_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_monthly.csv"
DIAGNOSTIC_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_diagnostics.csv"
CONTRIBUTION_PATH = (
    PROGRAM / "artifacts/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_loss_contributors.csv"
)
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/champion_failure_anatomy_cycle_017")
PATH_PANEL = EXTERNAL_ROOT / "industry_path_panel.parquet"
EXPECTED_SPEC_SHA256 = "b88512e612e8c36347c99f5b0ad2999d74ffd18c4c9ab3ae0e0aad25c9b17448"
INITIAL_CAPITAL = 10_000_000.0
COST = 0.002
SEVERE = -0.10
YEARS = tuple(range(2018, 2024))
LOSING_YEARS = (2018, 2022)
PROFITABLE_YEARS = (2019, 2020, 2021, 2023)
CHECKPOINTS = (5, 10, 15, 20)


class FailureAnatomyError(RuntimeError):
    """Fail-closed Cycle 017 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise FailureAnatomyError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


ANATOMY = _load_module(
    "cycle016_for_failure017",
    PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py",
)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise FailureAnatomyError("frozen Cycle-017 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_DIAGNOSTIC_FAILURE_ANATOMY_BEFORE_CYCLE_017_OUTCOMES":
        raise FailureAnatomyError("Cycle-017 contract was not frozen before outcomes")
    for role, binding in spec["bound_inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise FailureAnatomyError(f"bound input changed: {role}")
    if spec["champion"]["changes_authorized"] is not False:
        raise FailureAnatomyError("failure anatomy unexpectedly authorizes champion changes")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "champion modification", "classifier"):
        if phrase not in prohibited:
            raise FailureAnatomyError(f"missing prohibition: {phrase}")
    return spec


def _daily_nav_returns(equity: pd.DataFrame, family: str) -> pd.DataFrame:
    frame = equity.loc[equity.family.eq(family), ["trade_date", "nav"]].copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame = frame.sort_values("trade_date").reset_index(drop=True)
    previous = frame.nav.shift(1).fillna(INITIAL_CAPITAL)
    frame["daily_return"] = frame.nav / previous - 1.0
    frame["year"] = frame.trade_date.dt.year
    frame["month"] = frame.trade_date.dt.to_period("M").astype(str)
    return frame


def _drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min())


def _chronology(equity: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    annual_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    for family in ("arm0_baseline", "arm2_low_max"):
        frame = _daily_nav_returns(equity, family)
        for month, group in frame.groupby("month", sort=True):
            monthly_rows.append(
                {
                    "family": family,
                    "month": month,
                    "year": int(month[:4]),
                    "return": float((1.0 + group.daily_return).prod() - 1.0),
                }
            )
        for year, group in frame.groupby("year", sort=True):
            annual_rows.append(
                {
                    "family": family,
                    "year": int(year),
                    "return": float((1.0 + group.daily_return).prod() - 1.0),
                    "maximum_drawdown": _drawdown(group.daily_return),
                    "sessions": len(group),
                }
            )
    return pd.DataFrame(annual_rows), pd.DataFrame(monthly_rows)


def _calendar_paths(
    daily: pd.DataFrame, selected: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = daily[["trade_date", "cal_idx", "industry", "step_return", "diffusion_score"]].copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.date
    market_daily = frame.groupby(["trade_date", "cal_idx"], as_index=False).agg(
        market_return=("step_return", "median"),
        market_breadth=("step_return", lambda values: float((values > 0).mean())),
        cross_sectional_dispersion=("step_return", "std"),
    )
    industry_daily = frame.groupby(["trade_date", "cal_idx", "industry"], as_index=False).agg(
        industry_return=("step_return", "mean"),
        diffusion_score=("diffusion_score", "mean"),
    )
    industry_daily["industry_rank"] = industry_daily.groupby("trade_date")[
        "diffusion_score"
    ].rank(method="first", ascending=False)
    industry_daily["industry_percentile"] = industry_daily.groupby("trade_date")[
        "diffusion_score"
    ].rank(pct=True, ascending=True)
    market_map = market_daily.set_index("cal_idx").market_return.to_dict()
    industry_map = industry_daily.set_index(["cal_idx", "industry"]).industry_return.to_dict()
    rank_map = industry_daily.set_index(["cal_idx", "industry"])[
        ["industry_rank", "industry_percentile"]
    ].to_dict(orient="index")
    cal_by_date = market_daily.set_index("trade_date").cal_idx.to_dict()
    rows: list[dict[str, Any]] = []
    groups = selected[["signal_date", "industry"]].drop_duplicates()
    for row in groups.itertuples(index=False):
        start = int(cal_by_date[row.signal_date])
        market_log = 0.0
        industry_log = 0.0
        complete = True
        for step in range(1, 21):
            market_value = market_map.get(start + step)
            industry_value = industry_map.get((start + step, row.industry))
            if market_value is None or industry_value is None:
                complete = False
                break
            market_log += math.log1p(float(market_value))
            industry_log += math.log1p(float(industry_value))
            if step in CHECKPOINTS:
                rank = rank_map.get((start + step, row.industry), {})
                rows.append(
                    {
                        "signal_date": row.signal_date,
                        "industry": row.industry,
                        "year": row.signal_date.year,
                        "checkpoint": step,
                        "industry_return": math.expm1(industry_log),
                        "market_return": math.expm1(market_log),
                        "industry_relative_return": math.expm1(industry_log)
                        - math.expm1(market_log),
                        "industry_rank": rank.get("industry_rank", math.nan),
                        "industry_percentile": rank.get("industry_percentile", math.nan),
                        "industry_top10": bool(rank and rank["industry_rank"] <= 10),
                    }
                )
        if not complete:
            continue
    panel = pd.DataFrame(rows)
    environment = _market_environment(market_daily, industry_daily, daily)
    return panel, environment


def _market_environment(
    market_daily: pd.DataFrame, industry_daily: pd.DataFrame, daily: pd.DataFrame
) -> pd.DataFrame:
    market = market_daily.copy()
    market["year"] = pd.to_datetime(market.trade_date).dt.year
    industries = industry_daily.copy()
    industries["year"] = pd.to_datetime(industries.trade_date).dt.year
    industry_day = industries.groupby(["trade_date", "year"], as_index=False).agg(
        industry_dispersion=("industry_return", "std"),
        positive_industries=("industry_return", lambda values: float((values > 0).mean())),
    )
    stock = daily[["trade_date", "symbol", "step_return", "r20"]].copy()
    stock["year"] = pd.to_datetime(stock.trade_date).dt.year
    stock_year = stock.groupby(["year", "symbol"], as_index=False).agg(
        compound=("step_return", lambda values: float(np.prod(1.0 + values) - 1.0))
    )
    median_stock = stock_year.groupby("year").compound.median().to_dict()
    rows: list[dict[str, Any]] = []
    for year, group in market.groupby("year", sort=True):
        ind = industry_day.loc[industry_day.year.eq(year)]
        year_stock = stock.loc[stock.year.eq(year)]
        rows.append(
            {
                "year": int(year),
                "broad_proxy_return": float(np.prod(1.0 + group.market_return) - 1.0),
                "median_stock_return": float(median_stock[year]),
                "mean_daily_market_breadth": float(group.market_breadth.mean()),
                "market_realized_volatility": float(group.market_return.std(ddof=1) * np.sqrt(252)),
                "mean_cross_sectional_dispersion": float(group.cross_sectional_dispersion.mean()),
                "mean_industry_return_dispersion": float(ind.industry_dispersion.mean()),
                "positive_industry_fraction": float(ind.positive_industries.mean()),
                "market_downside_frequency": float((group.market_return < 0).mean()),
                "positive_r20_stock_fraction": float((year_stock.r20 > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def _annual_trade_metrics(trades: pd.DataFrame, plans: pd.DataFrame) -> pd.DataFrame:
    frame = trades.copy()
    frame["year"] = pd.to_datetime(frame.signal_date).dt.year
    planned = pd.Series(pd.to_datetime(plans.signal_date).dt.year).value_counts()
    rows: list[dict[str, Any]] = []
    for year, group in frame.groupby("year", sort=True):
        winners = group.loc[group.final_net_return > 0, "final_net_return"]
        losers = group.loc[group.final_net_return <= 0, "final_net_return"]
        gross_buy = group.invested_cost / (1.0 + COST)
        gross_sell = (group.invested_cost + group.profit) / (1.0 - COST)
        rows.append(
            {
                "year": int(year),
                "cohorts": int(group.signal_date.nunique()),
                "trades": len(group),
                "planned": int(planned.get(year, 0)),
                "execution_coverage": float(len(group) / planned.get(year, len(group))),
                "winner_rate": float((group.final_net_return > 0).mean()),
                "mean_winner": float(winners.mean()),
                "median_winner": float(winners.median()),
                "loser_rate": float((group.final_net_return <= 0).mean()),
                "mean_loser": float(losers.mean()),
                "severe_loss_fraction": float((group.final_net_return <= SEVERE).mean()),
                "upper_tail_contribution": float(group.final_net_return.quantile(0.90)),
                "lower_tail_contribution": float(group.final_net_return.quantile(0.10)),
                "round_trip_turnover_proxy": float(
                    (gross_buy.sum() + gross_sell.sum()) / INITIAL_CAPITAL
                ),
                "estimated_cost_drag": float(
                    COST * (gross_buy.sum() + gross_sell.sum()) / INITIAL_CAPITAL
                ),
                "forced_exits": int(group.exit_reason.eq("FORCED_PRE_EFFECTIVE").sum()),
                "delayed_exits": int((group.holding_sessions > 20).sum()),
                "p10_capacity_cny": float(group.capacity_cny.quantile(0.10)),
                "entry_cohort_profit_on_initial": float(group.profit.sum() / INITIAL_CAPITAL),
            }
        )
    return pd.DataFrame(rows)


def _candidate_layer_metrics(candidates: pd.DataFrame) -> pd.DataFrame:
    frame = candidates.loc[candidates.natural_status.eq("COMPLETE")].copy()
    frame["year"] = pd.to_datetime(frame.trade_date).dt.year
    rows: list[dict[str, Any]] = []
    for (family, year), group in frame.groupby(["family", "year"], sort=True):
        rows.append(
            {
                "family": family,
                "year": int(year),
                "candidate_trades": len(group),
                "candidate_mean_net_return": float(group.natural_net_return.mean()),
                "candidate_winner_fraction": float((group.natural_net_return > 0).mean()),
                "candidate_severe_fraction": float((group.natural_net_return <= SEVERE).mean()),
            }
        )
    return pd.DataFrame(rows)


def _loss_concentration(trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = trades.copy()
    frame["year"] = pd.to_datetime(frame.signal_date).dt.year
    panels: list[pd.DataFrame] = []
    summary: dict[str, Any] = {}
    for year in LOSING_YEARS:
        group = frame.loc[frame.year.eq(year)]
        cohort = group.groupby("signal_date", as_index=False).agg(
            profit=("profit", "sum"), trades=("trade_id", "size")
        )
        security = group.groupby("symbol", as_index=False).agg(
            profit=("profit", "sum"), trades=("trade_id", "size")
        )
        industry = group.groupby("industry", as_index=False).agg(
            profit=("profit", "sum"), trades=("trade_id", "size")
        )
        for label, table, key, count in (
            ("cohort", cohort, "signal_date", 10),
            ("security", security, "symbol", 10),
            ("industry", industry, "industry", 10),
        ):
            worst = table.nsmallest(count, "profit").copy()
            worst["year"] = year
            worst["dimension"] = label
            worst = worst.rename(columns={key: "group"})
            panels.append(worst[["year", "dimension", "group", "profit", "trades"]])
        sorted_trades = group.sort_values("profit")
        count = max(1, math.ceil(len(group) * 0.10))
        worst = sorted_trades.head(count)
        gross_negative = -float(group.loc[group.profit < 0, "profit"].sum())
        explained = -float(worst.profit.sum()) / gross_negative
        residual = float(group.profit.sum() - worst.profit.sum())
        worst10_cohort = float(cohort.nsmallest(10, "profit").profit.sum())
        if explained >= 0.60:
            classification = "TAIL_CONCENTRATED"
        elif explained <= 0.40 and residual < 0:
            classification = "BROAD_FAILURE"
        else:
            classification = "MIXED"
        summary[str(year)] = {
            "gross_negative_profit": gross_negative,
            "worst_10pct_trade_loss_share": explained,
            "residual_profit_after_worst_10pct_attribution": residual,
            "worst_5_cohort_profit": float(cohort.nsmallest(5, "profit").profit.sum()),
            "worst_10_cohort_profit": worst10_cohort,
            "worst_10_cohort_share_of_gross_loss": -worst10_cohort / gross_negative,
            "classification": classification,
        }
    return pd.concat(panels, ignore_index=True), summary


def _entry_quality(
    opportunity: pd.DataFrame, trades: pd.DataFrame, daily: pd.DataFrame
) -> pd.DataFrame:
    opp = opportunity.copy()
    opp["year"] = pd.to_datetime(opp.signal_date).dt.year
    selected = trades[["signal_date", "symbol", "industry"]].copy()
    daily_key = daily[["trade_date", "symbol", "max_return20", "diffusion_score"]].copy()
    daily_key["trade_date"] = pd.to_datetime(daily_key.trade_date).dt.date
    selected = selected.merge(
        daily_key,
        left_on=["signal_date", "symbol"],
        right_on=["trade_date", "symbol"],
        how="left",
        validate="many_to_one",
    )
    selected["year"] = pd.to_datetime(selected.signal_date).dt.year
    quality = selected.groupby("year", as_index=False).agg(
        mean_selected_max20=("max_return20", "mean"),
        mean_selected_diffusion=("diffusion_score", "mean"),
    )
    output = opp.groupby("year", as_index=False).agg(
        mean_eligible_industries=("eligible_industries", "mean"),
        mean_eligible_stocks=("eligible_stocks", "mean"),
        mean_quality_candidates=("quality_candidates_selected_industries", "mean"),
        mean_selected_industries=("selected_industries", "mean"),
        mean_diffusion_margin=("diffusion_rank10_11_margin", "mean"),
    )
    regimes = pd.crosstab(opp.year, opp.regime, normalize="index").reset_index()
    return output.merge(quality, on="year").merge(regimes, on="year", how="left")


def _year_path_summary(path: pd.DataFrame, persistence: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    persisted = persistence.copy()
    persisted["year"] = pd.to_datetime(persisted.signal_date).dt.year
    for (year, checkpoint), group in path.groupby(["year", "checkpoint"], sort=True):
        p = persisted.loc[
            persisted.year.eq(year) & persisted.checkpoint.eq(checkpoint)
        ]
        rows.append(
            {
                "year": int(year),
                "checkpoint": int(checkpoint),
                "industry_return": float(group.industry_return.mean()),
                "market_return": float(group.market_return.mean()),
                "industry_relative_return": float(group.industry_relative_return.mean()),
                "industry_top10_fraction": float(group.industry_top10.mean()),
                "mean_industry_percentile": float(group.industry_percentile.mean()),
                "cycle016_state_persistence": float(p.persistent.mean()),
            }
        )
    return pd.DataFrame(rows)


def _market_alpha_summary(trades: pd.DataFrame, path: pd.DataFrame) -> pd.DataFrame:
    terminal = path.loc[path.checkpoint.eq(20), [
        "signal_date", "industry", "market_return", "industry_return"
    ]]
    merged = trades.merge(terminal, on=["signal_date", "industry"], how="inner")
    merged["year"] = pd.to_datetime(merged.signal_date).dt.year
    return merged.groupby("year", as_index=False).agg(
        selected_net_payoff=("final_net_return", "mean"),
        broad_proxy_payoff=("market_return", "mean"),
        industry_proxy_payoff=("industry_return", "mean"),
        comparisons=("trade_id", "size"),
    )


def _classifications(
    annual: pd.DataFrame,
    trade_metrics: pd.DataFrame,
    market_alpha: pd.DataFrame,
    candidate: pd.DataFrame,
    paths: pd.DataFrame,
    concentration: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    nav = annual.pivot(index="year", columns="family", values="return")
    alpha = market_alpha.set_index("year")
    trades = trade_metrics.set_index("year")
    candidate_index = candidate.set_index(["family", "year"])
    path20 = paths.loc[paths.checkpoint.eq(20)].set_index("year")
    path5 = paths.loc[paths.checkpoint.eq(5)].set_index("year")
    profitable = trade_metrics.loc[trade_metrics.year.isin(PROFITABLE_YEARS)]
    decisions: dict[str, Any] = {}
    for year in LOSING_YEARS:
        row = alpha.loc[year]
        if (
            nav.loc[year, "arm2_low_max"] < 0
            and row.selected_net_payoff > row.broad_proxy_payoff
            and row.selected_net_payoff > row.industry_proxy_payoff
        ):
            market_exposure = "BETA_DOMINATED"
        elif (
            row.selected_net_payoff <= row.broad_proxy_payoff
            and row.selected_net_payoff <= row.industry_proxy_payoff
        ):
            market_exposure = "RELATIVE_ALPHA_FAILED"
        else:
            market_exposure = "MIXED"
        baseline_return = nav.loc[year, "arm0_baseline"]
        champion_return = nav.loc[year, "arm2_low_max"]
        increment = champion_return - baseline_return
        if baseline_return < 0 and increment > 0:
            layer = "UPSTREAM_INDUSTRY_FAILURE_LOWMAX_STILL_HELPFUL"
        elif baseline_return >= 0 and increment < 0:
            layer = "LOWMAX_SELECTION_FAILURE"
        elif baseline_return < 0 and increment <= 0:
            layer = "BOTH_LAYERS_WEAK"
        else:
            layer = "MIXED"
        collapse = bool(
            trades.loc[year, "winner_rate"] < profitable.winner_rate.min()
            or trades.loc[year, "mean_winner"] < profitable.mean_winner.min()
        )
        expansion = bool(
            trades.loc[year, "severe_loss_fraction"] > profitable.severe_loss_fraction.max()
            or trades.loc[year, "mean_loser"] < profitable.mean_loser.min()
        )
        tail = "BOTH" if collapse and expansion else (
            "WINNER_COLLAPSE" if collapse else "LOSER_EXPANSION"
        )
        profitable_path = paths.loc[paths.year.isin(PROFITABLE_YEARS)]
        fast = bool(
            path5.loc[year, "industry_top10_fraction"]
            < profitable_path.loc[profitable_path.checkpoint.eq(5), "industry_top10_fraction"].min()
            and path20.loc[year, "industry_top10_fraction"]
            < profitable_path.loc[
                profitable_path.checkpoint.eq(20), "industry_top10_fraction"
            ].min()
        )
        continuation = bool(
            path20.loc[year, "industry_relative_return"]
            < profitable_path.loc[
                profitable_path.checkpoint.eq(20), "industry_relative_return"
            ].min()
        )
        opportunity = "MIXED" if fast and continuation else (
            "FAST_ROTATION" if fast else ("CONTINUATION_FAILURE" if continuation else "NORMAL")
        )
        lowmax = candidate_index.loc[("arm2_low_max", year)]
        baseline = candidate_index.loc[("arm0_baseline", year)]
        decisions[str(year)] = {
            "market_exposure": market_exposure,
            "strategy_layer": layer,
            "pnl_shape": concentration[str(year)]["classification"],
            "opportunity_behavior": opportunity,
            "tail_mechanism": tail,
            "baseline_return": float(baseline_return),
            "champion_return": float(champion_return),
            "low_max_return_increment": float(increment),
            "low_max_candidate_mean_improvement": float(
                lowmax.candidate_mean_net_return - baseline.candidate_mean_net_return
            ),
            "low_max_severe_quality": float(
                baseline.candidate_severe_fraction - lowmax.candidate_severe_fraction
            ),
            "low_max_winner_quality": float(
                lowmax.candidate_winner_fraction - baseline.candidate_winner_fraction
            ),
        }
    first, second = decisions["2018"], decisions["2022"]
    if first["market_exposure"] == second["market_exposure"] == "BETA_DOMINATED":
        common = "COMMON_MARKET_BETA_FAILURE"
    elif (
        first["opportunity_behavior"]
        == second["opportunity_behavior"]
        == "CONTINUATION_FAILURE"
    ):
        common = "COMMON_INDUSTRY_CONTINUATION_FAILURE"
    elif first["opportunity_behavior"] == second["opportunity_behavior"] == "FAST_ROTATION":
        common = "COMMON_FAST_ROTATION_FAILURE"
    elif first["tail_mechanism"] == second["tail_mechanism"] == "LOSER_EXPANSION":
        common = "COMMON_TAIL_LOSS_FAILURE"
    elif first["strategy_layer"] == second["strategy_layer"] == "LOWMAX_SELECTION_FAILURE":
        common = "COMMON_STOCK_SELECTION_FAILURE"
    elif (
        first["market_exposure"] != second["market_exposure"]
        or first["strategy_layer"] != second["strategy_layer"]
        or first["opportunity_behavior"] != second["opportunity_behavior"]
    ):
        common = "MULTIPLE_FAILURE_MECHANISMS"
    else:
        common = "NO_CLEAR_FAILURE_STRUCTURE"
    return decisions, common


def _fmt(value: float) -> str:
    return f"{value:.2%}"


def _render_report(result: dict[str, Any]) -> str:
    annual = {row["year"]: row for row in result["annual_chronology"]}
    decisions = result["failure_classification"]
    lines = [
        "# Cycle 017 — champion failure-mode anatomy",
        "",
        "## Executive conclusion",
        "",
        result["executive_conclusion"],
        "",
        f"Cross-year classification: `{result['common_failure_conclusion']}`.",
        "",
        (
            "No information discovered in this failure anatomy has been used to "
            "modify, filter, or improve the frozen champion."
        ),
        "",
        "## Annual chronology",
        "",
        (
            "| Year | Champion | Baseline | Broad proxy | Positive/negative months | "
            "Worst/best month | Drawdown | Cohorts/trades | Severe | Turnover proxy |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        row = annual[year]
        lines.append(
            f"| {year} | {_fmt(row['champion_return'])} | {_fmt(row['baseline_return'])} | "
            f"{_fmt(row['broad_proxy_return'])} | "
            f"{row['positive_months']}/{row['negative_months']} | "
            f"{row['worst_month']} {_fmt(row['worst_month_return'])} / "
            f"{row['best_month']} {_fmt(row['best_month_return'])} | "
            f"{_fmt(row['maximum_drawdown'])} | {row['cohorts']}/{row['trades']} | "
            f"{_fmt(row['severe_loss_fraction'])} | {_fmt(row['round_trip_turnover_proxy'])} |"
        )
    monthly = result["monthly_chronology"]
    lines.extend(
        [
            "",
            "The broad series is the preregistered causal cross-sectional median-return "
            "proxy, not a formal index benchmark.",
            "",
            "### Monthly champion returns",
            "",
            "| Year | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for year in YEARS:
        values = {
            int(row["month"].split("-")[1]): row["return"]
            for row in monthly
            if row["year"] == year
        }
        cells = [(_fmt(values[month]) if month in values else "—") for month in range(1, 13)]
        lines.append(f"| {year} | " + " | ".join(cells) + " |")
    lines.extend(["", "## Market versus Alpha decomposition", ""])
    for row in result["market_alpha"]:
        lines.append(
            f"- {row['year']}: selected {_fmt(row['selected_net_payoff'])}; broad "
            f"{_fmt(row['broad_proxy_payoff'])}; PIT-industry {_fmt(row['industry_proxy_payoff'])}."
        )
    lines.extend(["", "## Market environment", ""])
    for year in YEARS:
        row = annual[year]
        lines.append(
            f"- {year}: median stock {_fmt(row['median_stock_return'])}; breadth "
            f"{_fmt(row['mean_daily_market_breadth'])}; realized volatility "
            f"{_fmt(row['market_realized_volatility'])}; cross-sectional/industry "
            f"dispersion {_fmt(row['mean_cross_sectional_dispersion'])}/"
            f"{_fmt(row['mean_industry_return_dispersion'])}; downside frequency "
            f"{_fmt(row['market_downside_frequency'])}."
        )
    lines.extend(["", "## Industry Diffusion versus Low-MAX", ""])
    for year in YEARS:
        row = annual[year]
        lines.append(
            f"- {year}: baseline {_fmt(row['baseline_return'])}; champion "
            f"{_fmt(row['champion_return'])}; arithmetic Low-MAX increment "
            f"{_fmt(row['low_max_return_increment'])}; candidate payoff increment "
            f"{_fmt(row['low_max_candidate_improvement'])}; severe/winner quality "
            f"{_fmt(row['low_max_severe_quality'])}/{_fmt(row['low_max_winner_quality'])}."
        )
    lines.extend(["", "## Continuation / rotation anatomy", ""])
    for year in YEARS:
        rows = [row for row in result["continuation_rotation"] if row["year"] == year]
        d5 = next(row for row in rows if row["checkpoint"] == 5)
        d20 = next(row for row in rows if row["checkpoint"] == 20)
        lines.append(
            f"- {year}: industry absolute d5/d20 {_fmt(d5['industry_return'])}/"
            f"{_fmt(d20['industry_return'])}; relative "
            f"{_fmt(d5['industry_relative_return'])}/{_fmt(d20['industry_relative_return'])}; "
            f"top-10-industry persistence "
            f"{_fmt(d5['industry_top10_fraction'])}/{_fmt(d20['industry_top10_fraction'])}."
        )
    lines.extend(["", "## Loss concentration", ""])
    for year in LOSING_YEARS:
        row = result["loss_concentration"][str(year)]
        lines.append(
            f"- {year}: worst 10% of trades explain {_fmt(row['worst_10pct_trade_loss_share'])} "
            f"of gross loss; worst ten cohorts explain "
            f"{_fmt(row['worst_10_cohort_share_of_gross_loss'])}; `{row['classification']}`."
        )
        worst = result["loss_contributors"]
        worst_industry = next(
            item
            for item in worst
            if item["year"] == year and item["dimension"] == "industry"
        )
        worst_security = next(
            item
            for item in worst
            if item["year"] == year and item["dimension"] == "security"
        )
        worst_cohort = next(
            item
            for item in worst
            if item["year"] == year and item["dimension"] == "cohort"
        )
        lines.append(
            f"  Worst cohort/security/industry: {worst_cohort['group']} / "
            f"{worst_security['group']} / {worst_industry['group']}; the compact "
            "attribution artifact records all requested worst contributors."
        )
    lines.extend(["", "## Winner versus loser decomposition", ""])
    for year in YEARS:
        row = annual[year]
        lines.append(
            f"- {year}: winners {_fmt(row['winner_rate'])} at mean "
            f"{_fmt(row['mean_winner'])}; mean loser {_fmt(row['mean_loser'])}; "
            f"severe {_fmt(row['severe_loss_fraction'])}."
        )
    control = result["profitable_year_control"]
    lines.append(
        f"- Profitable-year median: winners {_fmt(control['winner_rate_median'])}, "
        f"mean winner {_fmt(control['mean_winner_median'])}, mean loser "
        f"{_fmt(control['mean_loser_median'])}, severe "
        f"{_fmt(control['severe_loss_fraction_median'])}."
    )
    lines.extend(["", "## Entry quality", ""])
    for row in result["entry_quality"]:
        lines.append(
            f"- {row['year']}: quality candidates {row['mean_quality_candidates']:.1f}; "
            f"selected MAX20 {_fmt(row['mean_selected_max20'])}; diffusion "
            f"{row['mean_selected_diffusion']:.3f}; selected industries "
            f"{row['mean_selected_industries']:.1f}."
        )
    lines.extend(
        [
            "",
            "2018 entries were materially sparser and had weaker diffusion than the "
            "profitable-year range, so part of its vulnerability was visible descriptively "
            "at entry. 2022 had the richest candidate pool and normal diffusion strength; "
            "its failure was predominantly post-entry and not cheaply identified by the "
            "existing setup variables.",
        ]
    )
    lines.extend(["", "## Execution check", ""])
    for year in YEARS:
        row = annual[year]
        lines.append(
            f"- {year}: coverage {_fmt(row['execution_coverage'])}; blocked "
            f"{row['planned'] - row['trades']}; delayed exits {row['delayed_exits']}; "
            f"corporate-action exits {row['forced_exits']}; estimated cost drag "
            f"{_fmt(row['estimated_cost_drag'])}; p10 capacity CNY {row['p10_capacity_cny']:,.0f}."
        )
    lines.append(
        "Execution is not the dominant failure: both losing years retain near-complete "
        "coverage, zero delayed exits, few corporate-action exits, and usable capacity; "
        "later profitable years carry greater turnover/cost drag."
    )
    lines.extend(
        [
            "",
            "## 2018 versus 2022",
            "",
            (
                "Both years have negative broad and selected-industry absolute paths, "
                "positive relative selection, a losing Industry Diffusion baseline, and "
                "a helpful Low-MAX increment. They are not identical: 2018 is a broad, "
                "persistent loss with only one positive observed month and sparse/weaker "
                "entry opportunity; 2022 is milder, partly cohort-concentrated, and follows "
                "apparently normal-to-rich entry conditions. Opportunity rotation is not "
                "unusually fast in either year."
            ),
        ]
    )
    for year in LOSING_YEARS:
        row = decisions[str(year)]
        lines.extend(
            [
                "",
                f"## {year} classification",
                "",
                f"- Market exposure: `{row['market_exposure']}`",
                f"- Strategy layer: `{row['strategy_layer']}`",
                f"- P&L shape: `{row['pnl_shape']}`",
                f"- Opportunity behavior: `{row['opportunity_behavior']}`",
                f"- Tail mechanism: `{row['tail_mechanism']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Common failure conclusion",
            "",
            f"`{result['common_failure_conclusion']}`",
            "",
            "## Research-capital implication",
            "",
        ]
    )
    for index, direction in enumerate(result["next_alpha_directions"], start=1):
        lines.append(f"{index}. {direction}")
    lines.extend(
        [
            "",
            (
                "All evidence is consumed 2018--2023 development history. Post-2023 "
                "outcomes and CY-011 remained unread. This is not independent validation."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    equity = pd.read_csv(_resolve(spec["bound_inputs"]["construction_equity"]["path"]))
    candidates = pd.read_csv(_resolve(spec["bound_inputs"]["construction_candidates"]["path"]))
    trades = pd.read_parquet(_resolve(spec["bound_inputs"]["cycle_016_trade_panel"]["path"]))
    opportunity = pd.read_parquet(
        _resolve(spec["bound_inputs"]["cycle_016_opportunity_panel"]["path"])
    )
    persistence = pd.read_parquet(
        _resolve(spec["bound_inputs"]["cycle_016_persistence_panel"]["path"])
    )
    daily = pd.read_parquet(_resolve(spec["bound_inputs"]["causal_daily_panel"]["path"]))
    for column in ("signal_date", "entry_date", "exit_date"):
        trades[column] = pd.to_datetime(trades[column]).dt.date
    opportunity["signal_date"] = pd.to_datetime(opportunity.signal_date).dt.date
    persistence["signal_date"] = pd.to_datetime(persistence.signal_date).dt.date
    construction_spec = ANATOMY.CONSTRUCTION._load_spec()
    _baseline, champion = ANATOMY.CYCLE015._weekly_selections(daily, construction_spec)
    ca_spec = ANATOMY.CA._load_spec()
    _paths, calendar, _identity = ANATOMY.CA._load_market_inputs(ca_spec)
    plans = ANATOMY.CONSTRUCTION._make_plans(champion, calendar)
    annual_base, monthly = _chronology(equity)
    path_raw, environment = _calendar_paths(daily, trades)
    path_summary = _year_path_summary(path_raw, persistence)
    trade_metrics = _annual_trade_metrics(trades, plans)
    candidate_metrics = _candidate_layer_metrics(candidates)
    market_alpha = _market_alpha_summary(trades, path_raw)
    contributors, concentration = _loss_concentration(trades)
    entry_quality = _entry_quality(opportunity, trades, daily)
    decisions, common = _classifications(
        annual_base,
        trade_metrics,
        market_alpha,
        candidate_metrics,
        path_summary,
        concentration,
    )
    nav = annual_base.pivot(index="year", columns="family", values="return")
    dd = annual_base.loc[annual_base.family.eq("arm2_low_max")].set_index("year")
    env = environment.set_index("year")
    tm = trade_metrics.set_index("year")
    monthly_champion = monthly.loc[monthly.family.eq("arm2_low_max")]
    candidate_index = candidate_metrics.set_index(["family", "year"])
    annual_rows: list[dict[str, Any]] = []
    for year in YEARS:
        months = monthly_champion.loc[monthly_champion.year.eq(year)]
        worst = months.loc[months["return"].idxmin()]
        best = months.loc[months["return"].idxmax()]
        row = {
            "year": year,
            "champion_return": float(nav.loc[year, "arm2_low_max"]),
            "baseline_return": float(nav.loc[year, "arm0_baseline"]),
            "low_max_return_increment": float(
                nav.loc[year, "arm2_low_max"] - nav.loc[year, "arm0_baseline"]
            ),
            "low_max_candidate_improvement": float(
                candidate_index.loc[("arm2_low_max", year), "candidate_mean_net_return"]
                - candidate_index.loc[("arm0_baseline", year), "candidate_mean_net_return"]
            ),
            "low_max_severe_quality": float(
                candidate_index.loc[("arm0_baseline", year), "candidate_severe_fraction"]
                - candidate_index.loc[("arm2_low_max", year), "candidate_severe_fraction"]
            ),
            "low_max_winner_quality": float(
                candidate_index.loc[("arm2_low_max", year), "candidate_winner_fraction"]
                - candidate_index.loc[("arm0_baseline", year), "candidate_winner_fraction"]
            ),
            "maximum_drawdown": float(dd.loc[year, "maximum_drawdown"]),
            "positive_months": int((months["return"] > 0).sum()),
            "negative_months": int((months["return"] < 0).sum()),
            "worst_month": str(worst.month),
            "worst_month_return": float(worst["return"]),
            "best_month": str(best.month),
            "best_month_return": float(best["return"]),
            **tm.loc[year].to_dict(),
            **env.loc[year].to_dict(),
        }
        annual_rows.append(_clean(row))
    if not math.isclose(
        float(np.prod(1.0 + monthly_champion["return"]) - 1.0),
        1.224346371517719,
        rel_tol=0,
        abs_tol=1e-9,
    ):
        raise FailureAnatomyError("champion chronology does not reproduce terminal return")
    if tuple(year for year in YEARS if nav.loc[year, "arm2_low_max"] < 0) != LOSING_YEARS:
        raise FailureAnatomyError("losing-year identity changed")
    first = decisions["2018"]
    second = decisions["2022"]
    if common == "COMMON_MARKET_BETA_FAILURE":
        executive = (
            "Both losing years were dominated by negative absolute market and selected-"
            "industry paths, while selected stocks retained relative value and Low-MAX "
            "improved the losing Industry Diffusion baseline. 2018 was a broad, persistent "
            "failure with sparse/weaker entry opportunity; 2022 was milder, more episodic, "
            "and followed normal-to-rich setups. The common vulnerability is long-beta/"
            "absolute continuation, not Low-MAX selection or execution."
        )
    elif common == "MULTIPLE_FAILURE_MECHANISMS":
        executive = (
            "2018 and 2022 are not one stable bad regime. 2018 is "
            f"{first['market_exposure'].lower().replace('_', ' ')} with "
            f"{first['strategy_layer'].lower().replace('_', ' ')}; 2022 is "
            f"{second['market_exposure'].lower().replace('_', ' ')} with "
            f"{second['strategy_layer'].lower().replace('_', ' ')}. The evidence favors "
            "mechanism diversification over a champion regime filter."
        )
    else:
        executive = (
            "The two losing years share the same measured failure dimensions, but this "
            "six-year consumed sample cannot establish a tradable regime."
        )
    directions = [
        (
            "A return-generating cross-sectional or relative-value engine with lower "
            "broad long-beta dependence."
        ),
        (
            "A genuinely independent mean-reversion/event-asymmetry engine that does "
            "not rely on industry continuation."
        ),
        (
            "A downside-aware Alpha family whose return source is independent of "
            "Low-MAX, rather than another champion filter."
        ),
    ]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "claim_boundary": spec["claim_boundary"],
        "domain": {
            "trades": len(trades),
            "cohorts": int(trades.signal_date.nunique()),
            "years": list(YEARS),
            "daily_rows": len(daily),
            "industry_path_rows": len(path_raw),
        },
        "annual_chronology": annual_rows,
        "monthly_chronology": monthly.loc[monthly.family.eq("arm2_low_max")].to_dict(
            orient="records"
        ),
        "market_alpha": market_alpha.to_dict(orient="records"),
        "candidate_layer_metrics": candidate_metrics.to_dict(orient="records"),
        "continuation_rotation": path_summary.to_dict(orient="records"),
        "entry_quality": entry_quality.to_dict(orient="records"),
        "loss_concentration": concentration,
        "loss_contributors": contributors.to_dict(orient="records"),
        "profitable_year_control": {
            "winner_rate_median": float(
                trade_metrics.loc[trade_metrics.year.isin(PROFITABLE_YEARS), "winner_rate"].median()
            ),
            "mean_winner_median": float(
                trade_metrics.loc[trade_metrics.year.isin(PROFITABLE_YEARS), "mean_winner"].median()
            ),
            "mean_loser_median": float(
                trade_metrics.loc[trade_metrics.year.isin(PROFITABLE_YEARS), "mean_loser"].median()
            ),
            "severe_loss_fraction_median": float(
                trade_metrics.loc[
                    trade_metrics.year.isin(PROFITABLE_YEARS), "severe_loss_fraction"
                ].median()
            ),
        },
        "failure_classification": decisions,
        "common_failure_conclusion": common,
        "executive_conclusion": executive,
        "next_alpha_directions": directions,
        "boundaries": {
            "post_2023_read": False,
            "cy011_read": False,
            "champion_changed": False,
            "filter_tested": False,
            "hypothetical_improved_return_reported": False,
            "new_alpha_implemented": False,
            "oos_claim": False,
        },
    }
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    path_raw.to_parquet(PATH_PANEL, index=False, compression="zstd")
    diagnostics = pd.concat(
        [
            environment.assign(dimension="market_environment"),
            path_summary.assign(dimension="continuation_rotation"),
            entry_quality.assign(dimension="entry_quality"),
            candidate_metrics.assign(dimension="candidate_layer"),
        ],
        ignore_index=True,
        sort=False,
    )
    _atomic_write(
        ANNUAL_PATH,
        pd.DataFrame(annual_rows).to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        MONTHLY_PATH,
        monthly.loc[monthly.family.eq("arm2_low_max")].to_csv(
            index=False, lineterminator="\n", float_format="%.10g"
        ),
    )
    _atomic_write(
        DIAGNOSTIC_PATH,
        diagnostics.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    _atomic_write(
        CONTRIBUTION_PATH,
        contributors.to_csv(index=False, lineterminator="\n", float_format="%.10g"),
    )
    result["external_artifact"] = {
        "path": str(PATH_PANEL),
        "rows": len(path_raw),
        "bytes": PATH_PANEL.stat().st_size,
        "sha256": sha256_file(PATH_PANEL),
    }
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["artifacts"] = {
        path.name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256_file(path),
        }
        for path in (ANNUAL_PATH, MONTHLY_PATH, DIAGNOSTIC_PATH, CONTRIBUTION_PATH, REPORT_PATH)
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
