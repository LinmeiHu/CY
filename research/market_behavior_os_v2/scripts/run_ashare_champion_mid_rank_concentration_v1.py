#!/usr/bin/env python3
"""Replay the one frozen Champion ranks-3-to-5 concentration rule."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-MID-RANK-CONCENTRATION-V1_spec.json"
EQUITY_PATH = (
    PROGRAM / "artifacts/ASHARE-CHAMPION-MID-RANK-CONCENTRATION-V1_equity.csv"
)
RESULT_PATH = (
    PROGRAM / "artifacts/ASHARE-CHAMPION-MID-RANK-CONCENTRATION-V1_result.json"
)
REPORT_PATH = (
    PROGRAM / "reports/ASHARE-CHAMPION-MID-RANK-CONCENTRATION-V1_report.md"
)
CYCLE016_PATH = PROGRAM / "scripts/run_ashare_champion_anatomy_cycle_016.py"
EXPECTED_SPEC_SHA256 = "6c6eb74250ab3d3882ba16c45665d4dc76ac0df7211e266ff5a60a7490f64150"
FAMILY = "industry_diffusion_low_max_ranks_3_5"
INITIAL_CAPITAL = 10_000_000.0


class MidRankConcentrationError(RuntimeError):
    """Fail-closed concentrated replay error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise MidRankConcentrationError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


CYCLE016 = _load_module("ashare_cycle016_for_mid_rank", CYCLE016_PATH)
CONSTRUCTION = CYCLE016.CONSTRUCTION
CA = CYCLE016.CA


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise MidRankConcentrationError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_POST_HOC_TRANSLATION_BEFORE_CONCENTRATED_REPLAY":
        raise MidRankConcentrationError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise MidRankConcentrationError(f"bound input changed: {name}")
    CYCLE016._load_spec()
    return spec


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


def _baseline(spec: dict[str, Any]) -> dict[str, Any]:
    authoritative = json.loads(
        _resolve(spec["inputs"]["champion_authoritative_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    return authoritative["track_a"]["matched_cost_comparisons"]["20bps"]["low_max"]


def _comparison(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_return_delta": float(candidate["total_return"] - baseline["total_return"]),
        "annualized_return_delta": float(
            candidate["annualized_return"] - baseline["annualized_return"]
        ),
        "maximum_drawdown_improvement": float(
            candidate["maximum_drawdown"] - baseline["maximum_drawdown"]
        ),
        "daily_sharpe_delta": float(candidate["daily_sharpe"] - baseline["daily_sharpe"]),
        "calmar_delta": float(candidate["calmar"] - baseline["calmar"]),
        "severe_trade_fraction_improvement": float(
            baseline["severe_trade_fraction"] - candidate["severe_trade_fraction"]
        ),
        "turnover_delta": float(
            candidate["turnover_multiple_initial_capital"]
            - baseline["turnover_multiple_initial_capital"]
        ),
        "capacity_ratio": float(
            candidate["p10_capacity_cny_at_5pct_amount"]
            / baseline["p10_capacity_cny_at_5pct_amount"]
        ),
    }


def _render(result: dict[str, Any]) -> str:
    baseline = result["baseline"]
    candidate = result["candidate"]
    delta = result["comparison"]
    return "\n".join(
        [
            "# Champion mid-rank concentration",
            "",
            f"Status: `{result['status']}`.",
            "",
            (
                "This is a post-hoc development translation of Cycle-016's already "
                "observed ranks-3-to-5 payoff advantage, not independent confirmation."
            ),
            "",
            "## Frozen rule",
            "",
            (
                "On each exact Champion weekly signal, retain only emitted ranks 3, 4, "
                "and 5; split the unchanged one-quarter cohort capital equally, enter "
                "at the next legal open, and retain the exact 20-session lifecycle."
            ),
            "",
            "## Executable result",
            "",
            (
                "| Portfolio | Total | Annualized | Max DD | Sharpe | Calmar | "
                "Severe | Trades | Positions | Industries | P10 capacity |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            (
                f"| Baseline Top-10 | {baseline['total_return']:.2%} | "
                f"{baseline['annualized_return']:.2%} | "
                f"{baseline['maximum_drawdown']:.2%} | "
                f"{baseline['daily_sharpe']:.3f} | {baseline['calmar']:.3f} | "
                f"{baseline['severe_trade_fraction']:.2%} | "
                f"{baseline['completed_trades']} | {baseline['mean_positions']:.1f} | "
                f"{baseline['mean_industries']:.1f} | "
                f"CNY {baseline['p10_capacity_cny_at_5pct_amount']:,.0f} |"
            ),
            (
                f"| Ranks 3-5 | {candidate['total_return']:.2%} | "
                f"{candidate['annualized_return']:.2%} | "
                f"{candidate['maximum_drawdown']:.2%} | "
                f"{candidate['daily_sharpe']:.3f} | {candidate['calmar']:.3f} | "
                f"{candidate['severe_trade_fraction']:.2%} | "
                f"{candidate['completed_trades']} | {candidate['mean_positions']:.1f} | "
                f"{candidate['mean_industries']:.1f} | "
                f"CNY {candidate['p10_capacity_cny_at_5pct_amount']:,.0f} |"
            ),
            "",
            (
                f"Delta: annualized {delta['annualized_return_delta']:+.2%}, maximum-"
                f"drawdown quality {delta['maximum_drawdown_improvement']:+.2%}, "
                f"Sharpe {delta['daily_sharpe_delta']:+.3f}, severe-trade quality "
                f"{delta['severe_trade_fraction_improvement']:+.2%}."
            ),
            "",
            f"User return-and-drawdown target met: `{result['target_met']}`.",
            "",
            "No alternative rank set, weight, horizon, filter, or rescue replay was run.",
            "Post-2023 outcomes and CY-011 were not read.",
            "",
        ]
    )


def run() -> dict[str, Any]:
    spec = _load_spec()
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    construction_spec = CONSTRUCTION._load_spec()
    daily = pd.read_parquet(_resolve(spec["inputs"]["causal_daily_panel"]["path"]))
    _, champion = CYCLE016.CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.copy()
    champion["family"] = FAMILY
    plans = CONSTRUCTION._make_plans(champion, calendar)
    metadata = champion[["trade_date", "symbol", "signal_rank"]].copy()
    metadata["signal_date"] = pd.to_datetime(metadata.pop("trade_date")).dt.date
    plans = plans.merge(
        metadata, on=["signal_date", "symbol"], how="left", validate="one_to_one"
    )
    if plans.signal_rank.isna().any():
        raise MidRankConcentrationError("champion signal rank missing")
    plans["signal_rank"] = plans.signal_rank.astype(int)
    counts = plans.groupby("signal_date").signal_rank.apply(lambda x: sorted(x.tolist()))
    if not all(values == list(range(1, 11)) for values in counts):
        raise MidRankConcentrationError("frozen Champion rank domain changed")
    plans = plans.loc[plans.signal_rank.between(3, 5)].copy()
    if not plans.groupby("signal_date").size().eq(3).all():
        raise MidRankConcentrationError("frozen three-name breadth changed")
    plans["family"] = FAMILY
    market_rows = CA.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    candidate, equity, exits = CA._replay(FAMILY, plans, market_rows, calendar, events)
    baseline = _baseline(spec)
    comparison = _comparison(candidate, baseline)
    target = spec["success_target"]
    target_met = (
        candidate["annualized_return"] >= target["minimum_annualized_return"]
        and candidate["maximum_drawdown"]
        > target["maximum_drawdown_must_be_greater_than"]
    )
    status = "TARGET_ACHIEVED" if target_met else "SIMPLE_RULE_IMPROVES_BUT_TARGET_NOT_MET"
    equity = equity.sort_values("trade_date")
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "input_identity": input_identity,
        "action_audit": action_audit,
        "frozen_signal_ranks": [3, 4, 5],
        "signal_dates": int(plans.signal_date.nunique()),
        "planned_rows": len(plans),
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "calendar_year_returns": _year_returns(equity),
        "forced_exit_rows": len(exits),
        "target": target,
        "target_met": target_met,
    }
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
