#!/usr/bin/env python3
"""Test exact Weekly Low-MAX intensity within frozen champion cohorts."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-LOW-MAX-INTENSITY-V1_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-LOW-MAX-INTENSITY-V1_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-LOW-MAX-INTENSITY-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-LOW-MAX-INTENSITY-V1_report.md"
SEVERE = -0.10


class LowMaxIntensityError(RuntimeError):
    """Fail-closed Low-MAX intensity error."""


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
    if value is None or pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_WITHIN_COHORT_INTENSITY_OUTCOMES":
        raise LowMaxIntensityError("intensity specification is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise LowMaxIntensityError(f"bound input changed: {name}")
    return spec


def _build_panel(spec: dict[str, Any]) -> pd.DataFrame:
    trades = pd.read_parquet(_resolve(spec["inputs"]["champion_trade_panel"]["path"]))
    daily = pd.read_parquet(
        _resolve(spec["inputs"]["daily_feature_panel"]["path"]),
        columns=["trade_date", "symbol", "max_return20"],
    )
    daily["signal_date"] = pd.to_datetime(daily.pop("trade_date")).dt.date
    fields = [
        "trade_id",
        "signal_date",
        "symbol",
        "industry",
        "final_net_return",
        "invested_cost",
        "profit",
    ]
    panel = trades[fields].merge(daily, on=["signal_date", "symbol"], validate="one_to_one")
    if len(panel) != len(trades) or panel.max_return20.isna().any():
        raise LowMaxIntensityError("champion intensity coverage changed")
    panel["signal_year"] = pd.to_datetime(panel.signal_date).dt.year
    if panel.signal_year.max() > 2023:
        raise LowMaxIntensityError("post-2023 trade reached intensity analysis")
    panel = panel.sort_values(["signal_date", "max_return20", "symbol"]).reset_index(drop=True)
    panel["cohort_order"] = panel.groupby("signal_date").cumcount()
    panel["cohort_size"] = panel.groupby("signal_date").trade_id.transform("size")
    panel["intensity_bucket"] = (
        panel.cohort_order.mul(5).floordiv(panel.cohort_size).clip(upper=4).add(1)
    ).astype(int)
    panel["intensity_rank_pct"] = (panel.cohort_order + 0.5) / panel.cohort_size
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
    by_date = frame.groupby("signal_date", sort=True)
    rhos = by_date.apply(
        lambda group: spearmanr(group.intensity_rank_pct, group.final_net_return).statistic,
        include_groups=False,
    )
    adjacent = sum(means[index] > means[index + 1] for index in range(4))
    return {
        "label": label,
        "trades": len(frame),
        "decision_dates": int(frame.signal_date.nunique()),
        "buckets": buckets,
        "q1_minus_q5_mean": means[0] - means[4],
        "favorable_adjacent_steps": adjacent,
        "median_same_date_spearman": float(rhos.median()),
    }


def _generation_passes(summaries: dict[str, Any], spec: dict[str, Any]) -> bool:
    gate = spec["generation_gate_all_required"]
    full = summaries["generation_2018_2020"]
    return (
        full["q1_minus_q5_mean"]
        >= float(gate["lowest_minus_highest_bucket_mean_minimum"])
        and full["buckets"]["Q1"]["mean_payoff"] > 0
        and full["favorable_adjacent_steps"] >= 3
        and summaries["generation_2018_2019"]["q1_minus_q5_mean"] > 0
        and summaries["generation_2020"]["q1_minus_q5_mean"] > 0
    )


def _validation_passes(summaries: dict[str, Any]) -> bool:
    full = summaries["fixed_validation_2021_2023"]
    return (
        full["q1_minus_q5_mean"] > 0
        and full["buckets"]["Q1"]["mean_payoff"] > 0
        and full["favorable_adjacent_steps"] >= 3
        and all(
            summaries[f"fixed_validation_{year}"]["q1_minus_q5_mean"] >= 0
            for year in range(2021, 2024)
        )
    )


def _report(result: dict[str, Any]) -> str:
    lines = [
        "# Champion Weekly Low-MAX intensity V1",
        "",
        f"Generation: **{'PASS' if result['generation_passes'] else 'FAIL'}**. ",
        f"Validation opened: **{result['validation_opened']}**. ",
        f"Classification: **{result['classification']}**.",
        "",
        "| Period | Q1 | Q2 | Q3 | Q4 | Q5 | Q1-Q5 | Favorable steps |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in result["summaries"].values():
        values = [summary["buckets"][f"Q{bucket}"]["mean_payoff"] for bucket in range(1, 6)]
        lines.append(
            f"| {summary['label']} | "
            + " | ".join(f"{value:.3%}" for value in values)
            + f" | {summary['q1_minus_q5_mean']:.3%} | {summary['favorable_adjacent_steps']}/4 |"
        )
    lines.extend(
        [
            "",
            "Q1 is the lowest exact max_return20 and therefore the strongest Low-MAX intensity.",
            "No portfolio replay is authorized unless both temporal gates pass.",
            "Post-2023 outcomes and CY-011 were not read.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec = _load_spec()
    panel = _build_panel(spec)
    summaries = {
        "generation_2018_2020": _summary(
            panel.loc[panel.signal_year.le(2020)], "generation_2018_2020"
        ),
        "generation_2018_2019": _summary(
            panel.loc[panel.signal_year.le(2019)], "generation_2018_2019"
        ),
        "generation_2020": _summary(
            panel.loc[panel.signal_year.eq(2020)], "generation_2020"
        ),
    }
    generation_passes = _generation_passes(summaries, spec)
    validation_opened = False
    validation_passes = False
    if generation_passes:
        validation_opened = True
        summaries["fixed_validation_2021_2023"] = _summary(
            panel.loc[panel.signal_year.ge(2021)], "fixed_validation_2021_2023"
        )
        for year in range(2021, 2024):
            summaries[f"fixed_validation_{year}"] = _summary(
                panel.loc[panel.signal_year.eq(year)], f"fixed_validation_{year}"
            )
        validation_passes = _validation_passes(summaries)
    output = panel.loc[
        panel.signal_year.le(2020) if not validation_opened else panel.signal_year.le(2023)
    ].copy()
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12f")
    classification = (
        "LOW_MAX_INTENSITY_VALIDATED_TRANSLATION_AUTHORIZED"
        if generation_passes and validation_passes
        else "LOW_MAX_INTENSITY_FAILED_VALIDATION"
        if generation_passes
        else "NO_STABLE_LOW_MAX_INTENSITY_GRADIENT"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "generation_passes": generation_passes,
        "validation_opened": validation_opened,
        "validation_passes": validation_passes,
        "portfolio_replay_authorized": generation_passes and validation_passes,
        "classification": classification,
        "summaries": summaries,
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "maximum_evaluation_outcome_date": "2023-12-31" if validation_opened else "2020-12-31",
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), sort_keys=True, indent=2) + "\n")
    _atomic_write(REPORT_PATH, _report(result))
    print(json.dumps(_clean(result), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
