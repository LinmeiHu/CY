#!/usr/bin/env python3
"""Test the frozen industry-first Industry Diffusion plus Low-MAX construction."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-INDUSTRY-FIRST-DIFFUSION-LOW-MAX-V1_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-FIRST-DIFFUSION-LOW-MAX-V1_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-INDUSTRY-FIRST-DIFFUSION-LOW-MAX-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-INDUSTRY-FIRST-DIFFUSION-LOW-MAX-V1_report.md"
EXPECTED_SPEC_SHA256 = "caa1db9c38366da07cabdbdc93d257a005517c6b3ceb1f6c3416fe6a9e8d21db"
SEVERE = -0.10


class IndustryFirstError(RuntimeError):
    """Fail-closed industry-first construction error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
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
        raise IndustryFirstError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise IndustryFirstError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_INDUSTRY_FIRST_OUTCOMES":
        raise IndustryFirstError("spec is not frozen")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise IndustryFirstError(f"bound input changed: {role}")
    return spec


def _build_selections(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    trade_path = _resolve(spec["inputs"]["champion_trade_panel"]["path"])
    date_frame = pd.read_parquet(trade_path, columns=["signal_date", "symbol", "industry"])
    date_frame["signal_date"] = pd.to_datetime(date_frame.signal_date)
    signal_dates = date_frame.signal_date.drop_duplicates()
    daily = pd.read_parquet(
        _resolve(spec["inputs"]["daily_feature_panel"]["path"]),
        columns=[
            "trade_date",
            "cal_idx",
            "decision_at",
            "available_at",
            "symbol",
            "industry",
            "r20",
            "max_return20",
            "avg_amount20",
        ],
    )
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.trade_date.isin(signal_dates)].copy()
    daily = daily.loc[daily.industry.notna() & daily.industry.ne("") & daily.industry.ne("UNKNOWN")]
    daily["positive_r20"] = daily.r20 > 0
    industries = (
        daily.groupby(["trade_date", "industry"], sort=True)
        .agg(industry_score=("positive_r20", "mean"), member_count=("symbol", "size"))
        .reset_index()
    )
    industries = industries.loc[industries.member_count.ge(6)].sort_values(
        ["trade_date", "industry_score", "industry"], ascending=[True, False, True]
    )
    industries["industry_rank"] = industries.groupby("trade_date").cumcount() + 1
    chosen_industries = industries.loc[industries.industry_rank.le(10)]
    opportunity = daily.merge(
        chosen_industries,
        on=["trade_date", "industry"],
        how="inner",
        validate="many_to_one",
    )
    new = (
        opportunity.sort_values(["trade_date", "industry_rank", "max_return20", "symbol"])
        .groupby(["trade_date", "industry"], sort=False)
        .head(1)
        .sort_values(["trade_date", "industry_rank", "symbol"])
        .reset_index(drop=True)
    )
    new["family"] = "industry_first_diffusion_low_max"
    new["signal_score"] = new.industry_score
    new["signal_rank"] = new.groupby("trade_date").cumcount() + 1
    new["r5"] = np.nan
    baseline = date_frame.rename(columns={"signal_date": "trade_date"}).merge(
        daily[
            [
                "trade_date",
                "symbol",
                "cal_idx",
                "decision_at",
                "available_at",
                "r20",
                "max_return20",
                "avg_amount20",
            ]
        ],
        on=["trade_date", "symbol"],
        validate="one_to_one",
    )
    if len(baseline) != len(date_frame):
        raise IndustryFirstError("baseline identity coverage changed")
    baseline = baseline.sort_values(["trade_date", "industry", "max_return20", "symbol"])
    baseline["family"] = "champion_baseline"
    baseline["signal_score"] = -baseline.max_return20
    baseline["signal_rank"] = baseline.groupby("trade_date").cumcount() + 1
    baseline["r5"] = np.nan
    if (
        new.groupby("trade_date").size().nunique() != 1
        or new.groupby("trade_date").size().iloc[0] != 10
    ):
        raise IndustryFirstError("industry-first breadth changed")
    if new.groupby("trade_date").industry.nunique().min() != 10:
        raise IndustryFirstError("industry-first selection contains repeated industry")
    return new, baseline


def _screen_frame(construction: Any, frame: pd.DataFrame) -> pd.DataFrame:
    return construction._screen_selections(frame)


def _period_metrics(panel: pd.DataFrame, start: int, end: int) -> dict[str, Any]:
    years = pd.to_datetime(panel.trade_date).dt.year
    subset = panel.loc[years.between(start, end)].copy()
    complete = subset.loc[subset.status_h20.eq("COMPLETE")]
    cohorts = (
        complete.groupby(["family", "trade_date"], sort=True)
        .agg(net_return=("net_return_h20", "mean"), names=("symbol", "size"))
        .reset_index()
    )
    pivot = cohorts.pivot(index="trade_date", columns="family", values="net_return").dropna()
    improvement = pivot.industry_first_diffusion_low_max - pivot.champion_baseline
    output: dict[str, Any] = {
        "decision_dates": len(pivot),
        "new_mean_cohort_return": float(pivot.industry_first_diffusion_low_max.mean()),
        "baseline_mean_cohort_return": float(pivot.champion_baseline.mean()),
        "mean_improvement": float(improvement.mean()),
        "median_improvement": float(improvement.median()),
        "positive_improvement_fraction": float(improvement.gt(0).mean()),
    }
    for family in ("industry_first_diffusion_low_max", "champion_baseline"):
        rows = complete.loc[complete.family.eq(family)]
        output[f"{family}_severe_fraction"] = float(rows.net_return_h20.le(SEVERE).mean())
        family_rows = subset.loc[subset.family.eq(family)]
        output[f"{family}_entry_execution_fraction"] = float(
            family_rows.entry_status.eq("EXECUTABLE").mean()
        )
    return output


def _screen(
    construction: Any,
    paths: list[Path],
    calendar: list[date],
    new: pd.DataFrame,
    baseline: pd.DataFrame,
    start_year: int,
    end_year: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frames = []
    for frame in (new, baseline):
        years = pd.to_datetime(frame.trade_date).dt.year
        frames.append(frame.loc[years.between(start_year, end_year)])
    selections = _screen_frame(construction, pd.concat(frames, ignore_index=True))
    panel, _ = construction.CYCLE2._attach_screen_outcomes(paths, selections, calendar)
    return panel, _period_metrics(panel, start_year, end_year)


def _generation_passes(metrics: dict[str, dict[str, Any]], spec: dict[str, Any]) -> bool:
    gate = spec["screen_gate_generation_all_required"]
    full = metrics["generation_2018_2020"]
    return (
        full["mean_improvement"] >= gate["minimum_new_cohort_mean_net_improvement"]
        and metrics["generation_2018_2019"]["mean_improvement"]
        >= gate["minimum_each_subblock_improvement"]
        and metrics["generation_2020"]["mean_improvement"]
        >= gate["minimum_each_subblock_improvement"]
        and full["industry_first_diffusion_low_max_severe_fraction"]
        <= full["champion_baseline_severe_fraction"]
        and full["industry_first_diffusion_low_max_entry_execution_fraction"]
        >= gate["minimum_entry_execution_fraction"]
    )


def _validation_passes(metrics: dict[str, dict[str, Any]], spec: dict[str, Any]) -> bool:
    gate = spec["screen_gate_validation_all_required"]
    full = metrics["validation_2021_2023"]
    return (
        full["mean_improvement"] >= gate["minimum_new_cohort_mean_net_improvement"]
        and all(
            metrics[f"validation_{year}"]["mean_improvement"]
            >= gate["minimum_each_calendar_year_improvement"]
            for year in range(2021, 2024)
        )
        and full["industry_first_diffusion_low_max_severe_fraction"]
        <= full["champion_baseline_severe_fraction"]
        and full["industry_first_diffusion_low_max_entry_execution_fraction"]
        >= gate["minimum_entry_execution_fraction"]
    )


def _plans(selection: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    index = {day: position for position, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for item in selection.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        entry_index = index[signal_date] + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        rows.append(
            {
                "family": "industry_first_diffusion_low_max",
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": 20,
            }
        )
    plans = pd.DataFrame(rows)
    if (
        plans.groupby("signal_date").size().nunique() != 1
        or plans.groupby("signal_date").size().iloc[0] != 10
    ):
        raise IndustryFirstError("execution plan breadth changed")
    return plans


def _replay(
    construction: Any,
    spec: dict[str, Any],
    paths: list[Path],
    calendar: list[date],
    selection: pd.DataFrame,
    baseline_spec: dict[str, Any],
) -> dict[str, Any]:
    plans = _plans(selection, calendar)
    rows = construction.CYCLE2._query_execution_rows(paths, plans, calendar)
    events, _ = construction.BASELINE._load_risk_events(baseline_spec, calendar)
    replay, _, _ = construction.BASELINE._replay(
        "industry_first_diffusion_low_max", plans, rows, calendar, events
    )
    champion = json.loads(_resolve(spec["inputs"]["champion_anatomy_result"]["path"]).read_text())[
        "champion_identity"
    ]
    replay["delta_vs_champion"] = {
        "annualized_return": replay["annualized_return"] - champion["annualized_return"],
        "total_return": replay["total_return"] - champion["total_return"],
        "maximum_drawdown_improvement": replay["maximum_drawdown"] - champion["maximum_drawdown"],
        "daily_sharpe": replay["daily_sharpe"] - champion["daily_sharpe"],
    }
    replay["target_annualized_met"] = (
        replay["annualized_return"] >= spec["success_target"]["minimum_annualized_return"]
    )
    replay["target_drawdown_met"] = (
        replay["maximum_drawdown"] > spec["success_target"]["maximum_drawdown_must_be_greater_than"]
    )
    return replay


def _report(result: dict[str, Any]) -> str:
    lines = [
        "# Industry-first Industry Diffusion plus Low-MAX V1",
        "",
        "The baseline chooses ten stocks and averages only 4.44 represented industries; "
        "the frozen candidate chooses ten industries and one lowest-MAX stock per industry.",
        "",
        "| Period | Dates | New mean | Champion mean | Improvement | Win-improvement |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    metrics = dict(result["generation"]["metrics"])
    metrics.update(result["validation"].get("metrics", {}))
    for label, row in metrics.items():
        lines.append(
            f"| {label} | {row['decision_dates']} | {row['new_mean_cohort_return']:.3%} | "
            f"{row['baseline_mean_cohort_return']:.3%} | {row['mean_improvement']:.3%} | "
            f"{row['positive_improvement_fraction']:.2%} |"
        )
    lines.extend(
        [
            "",
            f"Generation passed: `{result['generation']['passed']}`.",
            f"Validation opened: `{result['validation']['opened']}`.",
            f"Validation passed: `{result['validation'].get('passed')}`.",
            "",
            "## Executable replay",
            "",
        ]
    )
    if result["replay"] is None:
        lines.append("A sequential gate failed; no strategy replay was run.")
    else:
        replay = result["replay"]
        lines.extend(
            [
                f"- Annualized return: {replay['annualized_return']:.2%}",
                f"- Maximum drawdown: {replay['maximum_drawdown']:.2%}",
                f"- Total return: {replay['total_return']:.2%}",
                f"- Sharpe: {replay['daily_sharpe']:.3f}",
                f"- Return target met: `{replay['target_annualized_met']}`",
                f"- Drawdown target met: `{replay['target_drawdown_met']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            result["interpretation"],
            "",
            "No post-2023 outcome or CY-011 was read.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    construction = _load_module(
        "construction_011_for_industry_first",
        _resolve(spec["inputs"]["construction_runner"]["path"]),
    )
    construction._load_spec()
    baseline_spec = construction.BASELINE._load_spec()
    paths, calendar, _ = construction.BASELINE._load_market_inputs(baseline_spec)
    new, baseline = _build_selections(spec)
    generation_panel, full_generation = _screen(
        construction, paths, calendar, new, baseline, 2018, 2020
    )
    generation_metrics = {
        "generation_2018_2020": full_generation,
        "generation_2018_2019": _period_metrics(generation_panel, 2018, 2019),
        "generation_2020": _period_metrics(generation_panel, 2020, 2020),
    }
    generation_passed = _generation_passes(generation_metrics, spec)
    validation: dict[str, Any] = {"opened": False, "passed": None}
    replay = None
    output_panel = generation_panel
    if generation_passed:
        validation_panel, full_validation = _screen(
            construction, paths, calendar, new, baseline, 2021, 2023
        )
        validation_metrics = {"validation_2021_2023": full_validation}
        for year in range(2021, 2024):
            validation_metrics[f"validation_{year}"] = _period_metrics(validation_panel, year, year)
        validation_passed = _validation_passes(validation_metrics, spec)
        validation = {
            "opened": True,
            "passed": validation_passed,
            "metrics": validation_metrics,
        }
        output_panel = pd.concat([generation_panel, validation_panel], ignore_index=True)
        if validation_passed:
            replay = _replay(construction, spec, paths, calendar, new, baseline_spec)
    compact_columns = [
        "family",
        "trade_date",
        "symbol",
        "industry",
        "signal_score",
        "signal_rank",
        "entry_status",
        "status_h20",
        "net_return_h20",
        "adverse_excursion_h20",
    ]
    _atomic_write(
        PANEL_PATH,
        output_panel[compact_columns].to_csv(index=False, float_format="%.12g"),
    )
    if not generation_passed:
        classification = "INDUSTRY_FIRST_FAILED_GENERATION"
        interpretation = (
            "Industry-first allocation did not improve the Champion in the frozen "
            "generation period; validation remained unopened."
        )
    elif not validation["passed"]:
        classification = "INDUSTRY_FIRST_FAILED_VALIDATION"
        interpretation = (
            "Industry-first allocation did not survive fixed validation. No neighboring "
            "industry count or weighting will be tested."
        )
    elif replay and replay["target_annualized_met"] and replay["target_drawdown_met"]:
        classification = "USER_OPTIMIZATION_TARGET_MET"
        interpretation = "The single industry-first construction met both user objectives."
    else:
        classification = "INDUSTRY_FIRST_TARGET_NOT_MET"
        interpretation = (
            "Industry-first allocation survived the screen but its single replay did not "
            "meet both user objectives."
        )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "classification": classification,
        "generation": {"passed": generation_passed, "metrics": generation_metrics},
        "validation": validation,
        "replay": replay,
        "selection_audit": {
            "decision_dates": int(new.trade_date.nunique()),
            "names_per_date": 10,
            "industries_per_date": 10,
            "baseline_mean_industries": float(
                baseline.groupby("trade_date").industry.nunique().mean()
            ),
        },
        "interpretation": interpretation,
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "post_2023_outcome_read": False,
        "cy011_read": False,
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _report(result))
    print(json.dumps(_clean(result), indent=2, sort_keys=True))
    return result


if __name__ == "__main__":
    run()
