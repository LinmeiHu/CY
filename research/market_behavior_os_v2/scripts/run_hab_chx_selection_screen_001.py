#!/usr/bin/env python3
"""Reproduce the fixed pre-2024 CHINEXT stock-selection cheap screen."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
CHX_SCRIPTS = ROOT / "research/chinext_v1/scripts"
SRC = ROOT / "src"
for import_root in (str(CHX_SCRIPTS), str(SRC)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)

from run_chinext_v1_full_survivor import read_jsonl  # noqa: E402
from run_chinext_v1_pit_replay import reconstruct_round_trips  # noqa: E402

SPEC_PATH = PROGRAM / "experiments/HAB-CHX-SELECTION-SCREEN-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-SELECTION-SCREEN-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-SELECTION-SCREEN-001_stock_selection_screen.md"
EXPECTED_SPEC_SHA256 = "8789448f23a1294541cc0d8939e4ef1e591917024b7cf3522aeda012fcc00ffc"
CUTOFF = date(2023, 12, 31)


class SelectionScreenError(RuntimeError):
    """Fail-closed exploration-screen contract error."""


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SelectionScreenError("selection-screen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FIXED_BEFORE_OUTCOME_SCREEN":
        raise SelectionScreenError("selection-screen honesty status changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SelectionScreenError(f"bound input identity mismatch: {name}")
    if "post-2023" not in "|".join(spec["prohibited"]):
        raise SelectionScreenError("post-2023 prohibition missing")
    return spec


def _events(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in read_jsonl(path):
        if row.get("event") != "ENTRY_SIGNAL_EVALUATED":
            continue
        signal_date = date.fromisoformat(str(row["signal_date"]))
        if signal_date > CUTOFF:
            raise SelectionScreenError("post-2023 event row encountered")
        key = (signal_date.isoformat(), str(row["symbol"]))
        if key in result:
            raise SelectionScreenError(f"duplicate signal event: {key}")
        result[key] = row
    return result


def _joined(event_path: Path, execution_path: Path) -> list[dict[str, Any]]:
    event_by_key = _events(event_path)
    executions = read_jsonl(execution_path)
    if any(date.fromisoformat(str(row["execution_date"])) > CUTOFF for row in executions):
        raise SelectionScreenError("post-2023 execution row encountered")
    trips = reconstruct_round_trips(executions)
    joined: list[dict[str, Any]] = []
    for trip in trips:
        key = (str(trip["entry_signal_date"]), str(trip["symbol"]))
        event = event_by_key.get(key)
        if event is None:
            raise SelectionScreenError(f"completed trip lacks exact signal event: {key}")
        joined.append({"trip": trip, "event": event})
    return joined


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = np.asarray([float(row["trip"]["round_trip_return"]) for row in rows])
    return {
        "n": len(rows),
        "mean_trade_return": float(np.mean(values)) if len(values) else None,
        "median_trade_return": float(np.median(values)) if len(values) else None,
        "win_rate": float(np.mean(values > 0)) if len(values) else None,
        "severe_loss_rate": float(np.mean(values <= -0.10)) if len(values) else None,
        "extreme_winner_rate": float(np.mean(values >= 0.20)) if len(values) else None,
    }


def _three_group(value: float, low: float, high: float) -> str:
    return "low" if value <= low else "high" if value >= high else "mid"


def _screen(
    rows: list[dict[str, Any]], grouper: Callable[[dict[str, Any]], str]
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[grouper(row["event"])].append(row)
    return {name: _metrics(groups[name]) for name in sorted(groups)}


def _screen_block(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "breakout_volume": _screen(
            rows, lambda event: "pass" if bool(event["breakout_volume"]["passed"]) else "fail"
        ),
        "relative_strength_score": _screen(
            rows, lambda event: _three_group(float(event["rs"]["score"]), 0.50, 0.70)
        ),
        "relative_strength_acceleration": _screen(
            rows,
            lambda event: (
                "low"
                if Decimal(str(event["rs"]["r20"]))
                - Decimal(str(event["rs"]["r120"]))
                <= Decimal("-0.20")
                else "high"
                if Decimal(str(event["rs"]["r20"]))
                - Decimal(str(event["rs"]["r120"]))
                >= Decimal("0.20")
                else "mid"
            ),
        ),
        "box_width": _screen(
            rows, lambda event: _three_group(float(event["full40"]["box_width"]), 0.15, 0.18)
        ),
        "direction_efficiency": _screen(
            rows,
            lambda event: _three_group(float(event["full40"]["direction_efficiency"]), 0.05, 0.15),
        ),
        "minimum_volume_location": _screen(
            rows, lambda event: _three_group(float(event["minvol"]["location"]), 0.10, 0.30)
        ),
        "minimum_volume_ratio": _screen(
            rows,
            lambda event: _three_group(float(event["minvol"]["minimum_volume_ratio"]), 0.40, 0.50),
        ),
    }


def _half_year_episodes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    episodes: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"high": [], "nonhigh": []})
    for row in rows:
        day = date.fromisoformat(str(row["trip"]["entry_signal_date"]))
        label = f"{day.year}H{1 if day.month <= 6 else 2}"
        event = row["event"]
        acceleration = Decimal(str(event["rs"]["r20"])) - Decimal(
            str(event["rs"]["r120"])
        )
        group = "high" if acceleration >= Decimal("0.20") else "nonhigh"
        episodes[label][group].append(float(row["trip"]["round_trip_return"]))
    result = []
    for label, groups in sorted(episodes.items()):
        if not groups["high"] or not groups["nonhigh"]:
            continue
        high_mean = float(np.mean(groups["high"]))
        nonhigh_mean = float(np.mean(groups["nonhigh"]))
        result.append(
            {
                "episode": label,
                "high_n": len(groups["high"]),
                "nonhigh_n": len(groups["nonhigh"]),
                "high_mean_return": high_mean,
                "nonhigh_mean_return": nonhigh_mean,
                "high_minus_nonhigh": high_mean - nonhigh_mean,
            }
        )
    return result


def _exit_attribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: dict[str, list[dict[str, Any]]] = defaultdict(list)
    durations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        trip = row["trip"]
        reasons[str(trip["exit_reason"])].append(row)
        entry = date.fromisoformat(str(trip["entry_execution_date"]))
        exit_day = date.fromisoformat(str(trip["exit_execution_date"]))
        holding_days = (exit_day - entry).days
        if holding_days <= 20:
            label = "le_20_calendar_days"
        elif holding_days <= 60:
            label = "21_to_60_calendar_days"
        else:
            label = "gt_60_calendar_days"
        durations[label].append(row)
    return {
        "claim_boundary": (
            "Descriptive realized attribution only; exit reason and duration are not "
            "entry-time or exit-time predictors."
        ),
        "by_exit_reason": {name: _metrics(group) for name, group in sorted(reasons.items())},
        "by_holding_duration": {name: _metrics(group) for name, group in sorted(durations.items())},
    }


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-SELECTION-SCREEN-001 — stock-selection cheap screen",
        "",
        "Seven fixed, signal-time descriptors were joined to completed pre-2024 "
        "CHINEXT V1 cycles. Only relative-strength acceleration advanced to an "
        "engine replay.",
        "",
        "| Screen | Development high mean | Consumed high mean | Decision |",
        "|---|---:|---:|---|",
    ]
    decisions = result["decisions"]
    for name, decision in decisions.items():
        dev = result["blocks"]["development_2018_2021"][name]
        later = result["blocks"]["consumed_2022_2023"][name]
        key = "pass" if name == "breakout_volume" else "high"
        lines.append(
            f"| {name} | {dev[key]['mean_trade_return']:.3%} | "
            f"{later[key]['mean_trade_return']:.3%} | {decision} |"
        )
    episode = result["relative_strength_acceleration_episode_check"]
    lines.extend(
        [
            "",
            f"The high-acceleration subgroup underperformed in "
            f"{episode['adverse_episode_count']} of "
            f"{episode['supported_episode_count']} supported half-year episodes. "
            "The sole reversal had only one high-subgroup trade.",
            "",
            "The exit summaries are outcome attribution only. They did not generate "
            "or promote an exit rule.",
            "",
            "Both blocks are consumed exploration. A repository-boundary incident "
            "exposed unrelated post-2023 summary metadata, so post-2023 data is "
            "quarantined from confirmation; no such row enters this result.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    if RESULT_PATH.exists() or REPORT_PATH.exists():
        raise SelectionScreenError("selection-screen output already exists")
    dev = _joined(
        _resolve(spec["inputs"]["development_event_ledger"]["path"]),
        _resolve(spec["inputs"]["development_execution_ledger"]["path"]),
    )
    later = _joined(
        _resolve(spec["inputs"]["consumed_event_ledger"]["path"]),
        _resolve(spec["inputs"]["consumed_execution_ledger"]["path"]),
    )
    episodes = _half_year_episodes(dev + later)
    adverse = sum(row["high_minus_nonhigh"] < 0 for row in episodes)
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_LEVEL_1_SCREEN",
        "honesty_boundary": spec["honesty_boundary"],
        "boundary_incident": spec["boundary_incident"],
        "blocks": {
            "development_2018_2021": _screen_block(dev),
            "consumed_2022_2023": _screen_block(later),
        },
        "completed_trip_counts": {
            "development_2018_2021": len(dev),
            "consumed_2022_2023": len(later),
        },
        "relative_strength_acceleration_episode_check": {
            "supported_episode_count": len(episodes),
            "adverse_episode_count": adverse,
            "episodes": episodes,
        },
        "exit_attribution": {
            "development_2018_2021": _exit_attribution(dev),
            "consumed_2022_2023": _exit_attribution(later),
        },
        "decisions": {
            "breakout_volume": "REJECT",
            "relative_strength_score": "PARK_PROMISING_NO_REPLAY",
            "relative_strength_acceleration": "ADVANCE_ONE_FIXED_REPLAY",
            "box_width": "REJECT_MIXED",
            "direction_efficiency": "REJECT_MIXED",
            "minimum_volume_location": "REJECT_MIXED",
            "minimum_volume_ratio": "REJECT_WEAK_MIXED",
        },
        "claim_boundary": {
            "untouched_validation": False,
            "post_2023_rows_read_by_experiment": False,
            "cy011_read": False,
            "exit_rule_established": False,
            "threshold_optimized": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {
                name: binding["sha256"] for name, binding in spec["inputs"].items()
            },
        },
    }
    if len(dev) != 194 or len(later) != 94 or len(episodes) != 11 or adverse != 10:
        raise SelectionScreenError("fixed screen invariants changed")
    _atomic_write(REPORT_PATH, _render(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
