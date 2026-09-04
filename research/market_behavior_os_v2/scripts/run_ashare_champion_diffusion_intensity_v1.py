#!/usr/bin/env python3
"""Test and, if earned, replay Champion diffusion-score concentration."""

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
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-DIFFUSION-INTENSITY-V1_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-DIFFUSION-INTENSITY-V1_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-DIFFUSION-INTENSITY-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-DIFFUSION-INTENSITY-V1_report.md"
EXPECTED_SPEC_SHA256 = "dd742a020c1dc5578d1ed8e9505b6cbd8a9a1732fa1f1298d08cf3a0c56300cd"
SEVERE = -0.10


class DiffusionIntensityError(RuntimeError):
    """Fail-closed diffusion-intensity error."""


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
        raise DiffusionIntensityError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DiffusionIntensityError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_DIFFUSION_INTENSITY_OUTCOMES":
        raise DiffusionIntensityError("spec is not frozen")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DiffusionIntensityError(f"bound input changed: {role}")
    return spec


def _read_period(spec: dict[str, Any], start: date, end: date) -> pd.DataFrame:
    trade_path = _resolve(spec["inputs"]["champion_trade_panel"]["path"])
    daily_path = _resolve(spec["inputs"]["daily_feature_panel"]["path"])
    trade_columns = [
        "trade_id",
        "signal_date",
        "symbol",
        "industry",
        "final_net_return",
        "invested_cost",
        "profit",
    ]
    trades = pd.read_parquet(
        trade_path,
        columns=trade_columns,
        filters=[("signal_date", ">=", start), ("signal_date", "<=", end)],
    )
    daily = pd.read_parquet(
        daily_path,
        columns=["trade_date", "symbol", "diffusion_score", "max_return20"],
        filters=[("trade_date", ">=", start), ("trade_date", "<=", end)],
    ).rename(columns={"trade_date": "signal_date"})
    trades["signal_date"] = pd.to_datetime(trades.signal_date)
    daily["signal_date"] = pd.to_datetime(daily.signal_date)
    panel = trades.merge(daily, on=["signal_date", "symbol"], validate="one_to_one")
    if len(panel) != len(trades) or panel[["diffusion_score", "max_return20"]].isna().any().any():
        raise DiffusionIntensityError("score coverage changed")
    panel["signal_year"] = pd.to_datetime(panel.signal_date).dt.year
    panel = panel.sort_values(
        ["signal_date", "diffusion_score", "max_return20", "symbol"],
        ascending=[True, False, True, True],
    ).reset_index(drop=True)
    panel["cohort_order"] = panel.groupby("signal_date").cumcount()
    panel["cohort_size"] = panel.groupby("signal_date").trade_id.transform("size")
    if panel.cohort_size.min() < 8 or panel.cohort_size.max() > 10:
        raise DiffusionIntensityError("unexpected executed Champion breadth")
    panel["intensity_bucket"] = (
        panel.cohort_order.mul(5).floordiv(panel.cohort_size).clip(upper=4).add(1)
    ).astype(int)
    panel["intensity_rank_pct"] = (panel.cohort_order + 0.5) / panel.cohort_size
    panel["retained_top5"] = panel.cohort_order < 5
    return panel


def _summary(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    buckets: dict[str, Any] = {}
    means: list[float] = []
    for bucket in range(1, 6):
        group = frame.loc[frame.intensity_bucket.eq(bucket)]
        mean = float(group.final_net_return.mean())
        means.append(mean)
        buckets[f"Q{bucket}"] = {
            "trades": len(group),
            "mean_payoff": mean,
            "median_payoff": float(group.final_net_return.median()),
            "winner_fraction": float(group.final_net_return.gt(0).mean()),
            "severe_fraction": float(group.final_net_return.le(SEVERE).mean()),
        }
    rhos = frame.groupby("signal_date", sort=True).apply(
        lambda group: spearmanr(group.intensity_rank_pct, group.final_net_return).statistic,
        include_groups=False,
    )
    high = frame.loc[frame.retained_top5]
    low = frame.loc[~frame.retained_top5]
    return {
        "label": label,
        "trades": len(frame),
        "decision_dates": int(frame.signal_date.nunique()),
        "buckets": buckets,
        "q1_minus_q5_mean": means[0] - means[4],
        "favorable_adjacent_steps": sum(means[index] > means[index + 1] for index in range(4)),
        "median_same_date_spearman": float(rhos.median()),
        "highest_half_mean": float(high.final_net_return.mean()),
        "lowest_half_mean": float(low.final_net_return.mean()),
        "highest_minus_lowest_half": float(
            high.final_net_return.mean() - low.final_net_return.mean()
        ),
        "highest_half_severe": float(high.final_net_return.le(SEVERE).mean()),
        "lowest_half_severe": float(low.final_net_return.le(SEVERE).mean()),
    }


def _generation(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    summaries = {
        "generation_2018_2020": _summary(panel, "generation_2018_2020"),
        "generation_2018_2019": _summary(
            panel.loc[panel.signal_year.le(2019)], "generation_2018_2019"
        ),
        "generation_2020": _summary(panel.loc[panel.signal_year.eq(2020)], "generation_2020"),
    }
    gate = spec["generation_gate_all_required"]
    full = summaries["generation_2018_2020"]
    checks = {
        "magnitude": full["q1_minus_q5_mean"] >= gate["highest_minus_lowest_bucket_mean_minimum"],
        "q1_positive": full["buckets"]["Q1"]["mean_payoff"] > 0,
        "adjacent_steps": full["favorable_adjacent_steps"]
        >= gate["minimum_favorable_adjacent_steps"],
        "2018_2019": summaries["generation_2018_2019"]["q1_minus_q5_mean"] > 0,
        "2020": summaries["generation_2020"]["q1_minus_q5_mean"] > 0,
    }
    return all(checks.values()), {"checks": checks, "summaries": summaries}


def _validation(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    summaries = {"validation_2021_2023": _summary(panel, "validation_2021_2023")}
    for year in range(2021, 2024):
        summaries[f"validation_{year}"] = _summary(
            panel.loc[panel.signal_year.eq(year)], f"validation_{year}"
        )
    gate = spec["validation_gate_all_required"]
    full = summaries["validation_2021_2023"]
    checks = {
        "q1_minus_q5": full["q1_minus_q5_mean"] > 0,
        "highest_half_positive": full["highest_half_mean"] > 0,
        "adjacent_steps": full["favorable_adjacent_steps"]
        >= gate["minimum_favorable_adjacent_steps"],
        "each_year_half_spread": all(
            summaries[f"validation_{year}"]["highest_minus_lowest_half"] >= 0
            for year in range(2021, 2024)
        ),
        "severe_loss": full["highest_half_severe"] <= full["lowest_half_severe"],
    }
    return all(checks.values()), {"checks": checks, "summaries": summaries}


def _plans(selection: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    calendar_index = {day: index for index, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for item in selection.itertuples(index=False):
        signal_date = pd.Timestamp(item.signal_date).date()
        entry_index = calendar_index[signal_date] + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        rows.append(
            {
                "family": "champion_diffusion_intensity_top5",
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": 20,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or plans.groupby("signal_date").size().nunique() != 1:
        raise DiffusionIntensityError("replay plan breadth changed")
    if plans.groupby("signal_date").size().iloc[0] != 5:
        raise DiffusionIntensityError("replay is not frozen Top-5")
    return plans


def _replay(spec: dict[str, Any], full_panel: pd.DataFrame) -> dict[str, Any]:
    construction_path = _resolve(spec["inputs"]["construction_runner"]["path"])
    construction = _load_module("construction_011_for_diffusion_intensity", construction_path)
    construction._load_spec()
    baseline_spec = construction.BASELINE._load_spec()
    paths, calendar, _ = construction.BASELINE._load_market_inputs(baseline_spec)
    selection = full_panel.loc[full_panel.retained_top5].copy()
    plans = _plans(selection, calendar)
    market_rows = construction.CYCLE2._query_execution_rows(paths, plans, calendar)
    events, _ = construction.BASELINE._load_risk_events(baseline_spec, calendar)
    replay, _, _ = construction.BASELINE._replay(
        "champion_diffusion_intensity_top5", plans, market_rows, calendar, events
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
        "# Champion Industry Diffusion intensity V1",
        "",
        "## Sequential result",
        "",
        f"- Generation passed: `{result['generation']['passed']}`",
        f"- Validation opened: `{result['validation']['opened']}`",
        f"- Validation passed: `{result['validation'].get('passed')}`",
        "",
        "| Period | Q1 | Q2 | Q3 | Q4 | Q5 | Q1-Q5 | Top-half gap | Steps |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    summaries = dict(result["generation"]["summaries"])
    summaries.update(result["validation"].get("summaries", {}))
    for summary in summaries.values():
        values = [summary["buckets"][f"Q{bucket}"]["mean_payoff"] for bucket in range(1, 6)]
        lines.append(
            f"| {summary['label']} | "
            + " | ".join(f"{value:.3%}" for value in values)
            + f" | {summary['q1_minus_q5_mean']:.3%} | "
            f"{summary['highest_minus_lowest_half']:.3%} | "
            f"{summary['favorable_adjacent_steps']}/4 |"
        )
    lines.extend(["", "## Executable translation", ""])
    if result["replay"] is None:
        lines.append("A sequential gate failed, so the frozen Top-5 replay remained unopened.")
    else:
        replay = result["replay"]
        lines.extend(
            [
                (
                    "Keep the five Champion names with the strongest original "
                    "Industry Diffusion score."
                ),
                "",
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
            "Post-2023 outcomes and CY-011 were not read.",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    generation_panel = _read_period(spec, date(2018, 1, 1), date(2020, 12, 31))
    generation_passed, generation_detail = _generation(generation_panel, spec)
    validation: dict[str, Any] = {"opened": False, "passed": None}
    replay = None
    output_panel = generation_panel
    if generation_passed:
        validation_panel = _read_period(spec, date(2021, 1, 1), date(2023, 12, 31))
        validation_passed, validation_detail = _validation(validation_panel, spec)
        validation = {"opened": True, "passed": validation_passed, **validation_detail}
        output_panel = pd.concat([generation_panel, validation_panel], ignore_index=True)
        if validation_passed:
            replay = _replay(spec, output_panel)
    _atomic_write(PANEL_PATH, output_panel.to_csv(index=False, float_format="%.12g"))
    if not generation_passed:
        classification = "NO_STABLE_DIFFUSION_INTENSITY_GRADIENT"
        interpretation = (
            "Original Industry Diffusion intensity did not order Champion payoff in the "
            "frozen generation period; validation and replay remained unopened."
        )
    elif not validation["passed"]:
        classification = "DIFFUSION_INTENSITY_FAILED_VALIDATION"
        interpretation = (
            "The intensity relation did not survive the fixed validation requirements; "
            "no alternative concentration level is allowed."
        )
    elif replay and replay["target_annualized_met"] and replay["target_drawdown_met"]:
        classification = "USER_OPTIMIZATION_TARGET_MET"
        interpretation = "The single frozen concentration rule met both user objectives."
    else:
        classification = "DIFFUSION_CONCENTRATION_TARGET_NOT_MET"
        interpretation = (
            "The intensity relation survived, but the single executable concentration "
            "did not meet both user objectives."
        )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "classification": classification,
        "generation": {"passed": generation_passed, **generation_detail},
        "validation": validation,
        "replay": replay,
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
