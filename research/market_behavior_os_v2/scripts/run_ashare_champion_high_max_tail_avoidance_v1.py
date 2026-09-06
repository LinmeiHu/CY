#!/usr/bin/env python3
"""Validate the data-generated high-MAX tail avoidance hypothesis."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-HIGH-MAX-TAIL-AVOIDANCE-V1_spec.json"
INTENSITY_RUNNER = PROGRAM / "scripts/run_ashare_champion_low_max_intensity_v1.py"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-HIGH-MAX-TAIL-AVOIDANCE-V1_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-HIGH-MAX-TAIL-AVOIDANCE-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-HIGH-MAX-TAIL-AVOIDANCE-V1_report.md"
SEVERE = -0.10


class HighMaxTailAvoidanceError(RuntimeError):
    """Fail-closed high-MAX tail validation error."""


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


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise HighMaxTailAvoidanceError(f"cannot load module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


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
    if spec.get("status") != "FROZEN_AFTER_2018_2020_GENERATION_BEFORE_2021_2023_VALIDATION":
        raise HighMaxTailAvoidanceError("tail-avoidance specification is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise HighMaxTailAvoidanceError(f"bound input changed: {name}")
    return spec


def _compare(frame: pd.DataFrame, label: str) -> dict[str, Any]:
    retained = frame.loc[frame.intensity_bucket.le(4)]
    avoided = frame.loc[frame.intensity_bucket.eq(5)]
    if retained.empty or avoided.empty:
        raise HighMaxTailAvoidanceError(f"empty comparison leg: {label}")
    return {
        "label": label,
        "decision_dates": int(frame.signal_date.nunique()),
        "retained_trades": len(retained),
        "avoided_trades": len(avoided),
        "retained_mean": float(retained.final_net_return.mean()),
        "avoided_mean": float(avoided.final_net_return.mean()),
        "mean_spread": float(
            retained.final_net_return.mean() - avoided.final_net_return.mean()
        ),
        "retained_median": float(retained.final_net_return.median()),
        "avoided_median": float(avoided.final_net_return.median()),
        "retained_winner_fraction": float(retained.final_net_return.gt(0).mean()),
        "avoided_winner_fraction": float(avoided.final_net_return.gt(0).mean()),
        "retained_severe_fraction": float(retained.final_net_return.le(SEVERE).mean()),
        "avoided_severe_fraction": float(avoided.final_net_return.le(SEVERE).mean()),
        "severe_improvement": float(
            avoided.final_net_return.le(SEVERE).mean()
            - retained.final_net_return.le(SEVERE).mean()
        ),
    }


def _report(result: dict[str, Any]) -> str:
    lines = [
        "# Champion high-MAX tail avoidance V1",
        "",
        "This is a data-generated development hypothesis, not confirmation.",
        "",
        "| Period | Retained mean | Avoided mean | Spread | Severe improvement |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in result["comparisons"]:
        lines.append(
            f"| {row['label']} | {row['retained_mean']:.3%} | {row['avoided_mean']:.3%} "
            f"| {row['mean_spread']:.3%} | {row['severe_improvement']:.3%} |"
        )
    lines.extend(
        [
            "",
            f"Validation: **{'PASS' if result['validation_passes'] else 'FAIL'}**.",
            f"Portfolio replay authorized: **{result['portfolio_replay_authorized']}**.",
            f"Classification: **{result['classification']}**.",
            "",
            "Post-2023 outcomes and CY-011 were not read.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec = _load_spec()
    intensity = _load_module("low_max_intensity_for_tail_v1", INTENSITY_RUNNER)
    intensity_spec = intensity._load_spec()
    panel = intensity._build_panel(intensity_spec)
    validation = panel.loc[panel.signal_year.ge(2021)].copy()
    comparisons = [_compare(validation, "fixed_validation_2021_2023")]
    for year in range(2021, 2024):
        comparisons.append(
            _compare(validation.loc[validation.signal_year.eq(year)], f"fixed_validation_{year}")
        )
    full = comparisons[0]
    gate = spec["fixed_validation"]["all_required"]
    validation_passes = (
        full["mean_spread"] >= float(gate["pooled_mean_spread_minimum"])
        and full["retained_mean"] > 0
        and full["severe_improvement"] > 0
        and all(row["mean_spread"] >= 0 for row in comparisons[1:])
    )
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    validation.to_csv(PANEL_PATH, index=False, float_format="%.12f")
    result = {
        "experiment_id": spec["experiment_id"],
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "comparisons": comparisons,
        "validation_passes": validation_passes,
        "portfolio_replay_authorized": validation_passes,
        "classification": (
            "HIGH_MAX_TAIL_AVOIDANCE_VALIDATED"
            if validation_passes
            else "HIGH_MAX_TAIL_AVOIDANCE_FAILED"
        ),
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "maximum_evaluation_outcome_date": "2023-12-31",
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), sort_keys=True, indent=2) + "\n")
    _atomic_write(REPORT_PATH, _report(result))
    print(json.dumps(_clean(result), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
