#!/usr/bin/env python3
"""Replay the single frozen post-hoc Champion diffusion-Q1 concentration."""

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
EXPERIMENT_ID = "ASHARE-CHAMPION-DIFFUSION-Q1-CONCENTRATION-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
EXIT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_risk_exits.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "7b1896d8ba98ecf7ade27ea548994cec959987728334693dc9dc12e92e22036c"
FAMILY = "champion_diffusion_q1_top2"
INITIAL_CAPITAL = 10_000_000.0


class DiffusionQ1Error(RuntimeError):
    """Fail-closed diffusion-Q1 translation error."""


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
        raise DiffusionQ1Error(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DiffusionQ1Error("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SINGLE_POST_HOC_TRANSLATION_BEFORE_EXECUTABLE_REPLAY":
        raise DiffusionQ1Error("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DiffusionQ1Error(f"bound input changed: {name}")
    return spec


def _selection(spec: dict[str, Any], cycle016: Any) -> pd.DataFrame:
    cycle016._load_spec()
    construction_spec = cycle016.CONSTRUCTION._load_spec()
    daily = pd.read_parquet(_resolve(spec["inputs"]["causal_daily_panel"]["path"]))
    _, champion = cycle016.CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.sort_values(
        ["trade_date", "diffusion_score", "max_return20", "symbol"],
        ascending=[True, False, True, True],
    ).copy()
    champion["q1_order"] = champion.groupby("trade_date").cumcount() + 1
    counts = champion.groupby("trade_date").size()
    if not counts.eq(10).all():
        raise DiffusionQ1Error("frozen Champion signal breadth changed")
    selection = champion.loc[champion.q1_order.le(2)].copy()
    if not selection.groupby("trade_date").size().eq(2).all():
        raise DiffusionQ1Error("Q1 signal breadth changed")
    return selection


def _plans(selection: pd.DataFrame, calendar: list[date]) -> pd.DataFrame:
    calendar_index = {day: index for index, day in enumerate(calendar)}
    rows: list[dict[str, Any]] = []
    for item in selection.itertuples(index=False):
        signal_date = pd.Timestamp(item.trade_date).date()
        entry_index = calendar_index[signal_date] + 1
        due_index = entry_index + 20
        if due_index >= len(calendar):
            continue
        rows.append(
            {
                "family": FAMILY,
                "signal_date": signal_date,
                "symbol": item.symbol,
                "industry": str(item.industry),
                "entry_index": entry_index,
                "due_index": due_index,
                "horizon": 20,
            }
        )
    plans = pd.DataFrame(rows)
    if plans.empty or not plans.groupby("signal_date").size().eq(2).all():
        raise DiffusionQ1Error("Q1 plan breadth changed")
    return plans


def _year_returns(equity: pd.DataFrame) -> dict[str, float]:
    work = equity.copy()
    work["year"] = pd.to_datetime(work.trade_date).dt.year
    ending = work.groupby("year").nav.last().sort_index()
    output: dict[str, float] = {}
    prior = INITIAL_CAPITAL
    for year, nav in ending.items():
        output[str(int(year))] = float(nav / prior - 1.0)
        prior = float(nav)
    return output


def _monthly_returns(equity: pd.DataFrame) -> dict[str, float]:
    work = equity.copy()
    work["month"] = pd.to_datetime(work.trade_date).dt.to_period("M").astype(str)
    ending = work.groupby("month").nav.last().sort_index()
    prior = INITIAL_CAPITAL
    output: dict[str, float] = {}
    for month, nav in ending.items():
        output[month] = float(nav / prior - 1.0)
        prior = float(nav)
    return output


def _overlap_audit(spec: dict[str, Any], selection: pd.DataFrame) -> dict[str, Any]:
    observed = pd.read_csv(_resolve(spec["inputs"]["intensity_panel"]["path"]))
    observed["signal_date"] = pd.to_datetime(observed.signal_date)
    observed = observed.loc[observed.intensity_bucket.eq(1)]
    chosen = selection[["trade_date", "symbol"]].copy()
    chosen["signal_date"] = pd.to_datetime(chosen.pop("trade_date"))
    joined = observed.merge(chosen, on=["signal_date", "symbol"], how="inner")
    return {
        "observed_executed_q1_rows": len(observed),
        "causal_signal_q1_rows": len(chosen),
        "overlap_rows": len(joined),
        "observed_q1_covered_by_causal_signal_fraction": float(len(joined) / len(observed)),
    }


def _render(result: dict[str, Any]) -> str:
    baseline = result["baseline"]
    candidate = result["candidate"]
    delta = result["comparison"]
    years = " | ".join(
        f"{year} {value:+.2%}" for year, value in result["calendar_year_returns"].items()
    )
    return "\n".join(
        [
            "# Champion diffusion-Q1 concentration V1",
            "",
            f"Status: `{result['status']}`.",
            "",
            (
                "At each unchanged weekly Champion signal, retain only the two names with "
                "the highest causal Industry Diffusion score; ties use lower prior-20-day "
                "MAX and symbol. Keep the unchanged one-quarter cohort capital, next-open "
                "entry, h20 due-open exit, and 20 bps per side."
            ),
            "",
            (
                f"Baseline: annualized {baseline['annualized_return']:.2%}, max drawdown "
                f"{baseline['maximum_drawdown']:.2%}, Sharpe {baseline['daily_sharpe']:.3f}."
            ),
            (
                f"Q1 Top-2: annualized {candidate['annualized_return']:.2%}, max drawdown "
                f"{candidate['maximum_drawdown']:.2%}, Sharpe {candidate['daily_sharpe']:.3f}."
            ),
            (
                f"Delta: annualized {delta['annualized_return_delta']:+.2%}, drawdown "
                f"quality {delta['maximum_drawdown_improvement']:+.2%}, Sharpe "
                f"{delta['daily_sharpe_delta']:+.3f}."
            ),
            "",
            f"Calendar years: {years}.",
            "",
            (
                "The direction and Q1 breadth were generated after observing the original "
                "intensity surface. This is consumed-history post-hoc development evidence, "
                "not independent validation. Post-2023 outcomes and CY-011 were not read."
            ),
            "",
        ]
    )


def run() -> dict[str, Any]:
    spec = _load_spec()
    cycle016 = _load_module(
        "cycle016_for_diffusion_q1",
        _resolve(spec["inputs"]["champion_anatomy_runner"]["path"]),
    )
    selection = _selection(spec, cycle016)
    ca = cycle016.CA
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    plans = _plans(selection, calendar)
    market_rows = ca.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = ca._load_risk_events(ca_spec, calendar)
    replay, equity, risk_exits = ca._replay(FAMILY, plans, market_rows, calendar, events)
    baseline_result = json.loads(
        _resolve(spec["inputs"]["champion_authoritative_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    baseline = baseline_result["track_a"]["matched_cost_comparisons"]["20bps"]["low_max"]
    comparison = {
        "annualized_return_delta": float(
            replay["annualized_return"] - baseline["annualized_return"]
        ),
        "total_return_delta": float(replay["total_return"] - baseline["total_return"]),
        "maximum_drawdown_improvement": float(
            replay["maximum_drawdown"] - baseline["maximum_drawdown"]
        ),
        "daily_sharpe_delta": float(replay["daily_sharpe"] - baseline["daily_sharpe"]),
        "severe_trade_fraction_improvement": float(
            baseline["severe_trade_fraction"] - replay["severe_trade_fraction"]
        ),
    }
    target = spec["success_target"]
    target_checks = {
        "annualized": replay["annualized_return"] >= target["minimum_annualized_return"],
        "drawdown": replay["maximum_drawdown"]
        > target["maximum_drawdown_must_be_greater_than"],
    }
    target_met = all(target_checks.values())
    status = "USER_TARGET_ACHIEVED" if target_met else "Q1_CONCENTRATION_TARGET_NOT_MET"
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        EXIT_PATH,
        risk_exits.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "selection_dates": int(plans.signal_date.nunique()),
        "planned_entries": len(plans),
        "causal_selection_overlap_audit": _overlap_audit(spec, selection),
        "baseline": baseline,
        "candidate": replay,
        "comparison": comparison,
        "calendar_year_returns": _year_returns(equity),
        "monthly_returns": _monthly_returns(equity),
        "target": target,
        "target_checks": target_checks,
        "target_met": target_met,
        "input_identity": input_identity,
        "action_audit": action_audit,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
            "risk_exits_sha256": sha256_file(EXIT_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
