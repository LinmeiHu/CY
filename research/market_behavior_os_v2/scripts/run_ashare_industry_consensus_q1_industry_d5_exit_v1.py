#!/usr/bin/env python3
"""Test one frozen industry-level d5 continuation-failure exit."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-INDUSTRY-CONSENSUS-Q1-INDUSTRY-D5-EXIT-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
SCREEN_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_screen.csv"
DECISION_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_decisions.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
TRADES_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_trades.csv"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "e8ebfe2ff8744141622d77c7b2d2419b3f007aff954c29199f213ee250b2fd26"


class IndustryD5ExitError(RuntimeError):
    """Fail-closed error for the frozen industry d5 exit."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise IndustryD5ExitError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise IndustryD5ExitError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != (
        "FROZEN_POST_HOC_SINGLE_INDUSTRY_EXIT_BEFORE_2018_2023_OUTCOME_JOIN"
    ):
        raise IndustryD5ExitError("experiment is not frozen")
    if spec["single_candidate_rule"]["trigger"] != "industry_d5_return <= 0":
        raise IndustryD5ExitError("d5 exit rule changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise IndustryD5ExitError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("2024 or 2025", "2026 market", "CY-011", "d3, d10"):
        if phrase not in prohibited:
            raise IndustryD5ExitError(f"missing prohibition: {phrase}")
    return spec


def _event_features(
    corrected: pd.DataFrame, plans: pd.DataFrame, calendar: list[date]
) -> pd.DataFrame:
    work = corrected[["cal_idx", "industry", "step_return"]].copy()
    work["simple_return"] = np.expm1(work.step_return.astype(float))
    industry_daily = (
        work.groupby(["cal_idx", "industry"], sort=True)
        .simple_return.mean()
        .to_dict()
    )
    rows: list[dict[str, Any]] = []
    event_rows = plans[
        ["signal_date", "industry", "entry_index", "due_index"]
    ].drop_duplicates()
    for event in event_rows.itertuples(index=False):
        returns: list[float] = []
        for index in range(int(event.entry_index), int(event.entry_index) + 5):
            value = industry_daily.get((index, str(event.industry)))
            if value is None or not math.isfinite(float(value)):
                raise IndustryD5ExitError(
                    f"missing d5 industry return:{event.signal_date}:{event.industry}:{index}"
                )
            returns.append(float(value))
        industry_d5 = float(np.prod(1.0 + np.asarray(returns)) - 1.0)
        decision_index = int(event.entry_index) + 4
        early_exit_index = int(event.entry_index) + 5
        if not decision_index < early_exit_index <= int(event.due_index):
            raise IndustryD5ExitError("d5 chronology failed")
        rows.append(
            {
                "signal_date": event.signal_date,
                "industry": str(event.industry),
                "entry_index": int(event.entry_index),
                "normal_due_index": int(event.due_index),
                "d5_decision_index": decision_index,
                "d5_decision_date": calendar[decision_index],
                "early_exit_index": early_exit_index,
                "early_exit_date": calendar[early_exit_index],
                "industry_d5_return": industry_d5,
                "triggered": industry_d5 <= 0.0,
                "block": "2018-2020" if event.signal_date.year <= 2020 else "2021-2023",
            }
        )
    features = pd.DataFrame(rows).sort_values(["signal_date", "industry"])
    if features.duplicated(["signal_date", "industry"]).any():
        raise IndustryD5ExitError("duplicate d5 event feature")
    return features.reset_index(drop=True)


def _screen(
    mapped_trades: pd.DataFrame, features: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = mapped_trades.merge(
        features,
        on=["signal_date", "industry"],
        how="left",
        validate="many_to_one",
    )
    if work[["industry_d5_return", "triggered", "block"]].isna().any().any():
        raise IndustryD5ExitError("screen lineage incomplete")
    rows: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    for block, block_rows in work.groupby("block", sort=True):
        triggered = block_rows.loc[block_rows.triggered]
        continued = block_rows.loc[~block_rows.triggered]
        triggered_dates = int(triggered.signal_date.nunique())
        triggered_mean = float(triggered.net_return.mean())
        continued_mean = float(continued.net_return.mean())
        triggered_severe = float(triggered.net_return.le(-0.10).mean())
        continued_severe = float(continued.net_return.le(-0.10).mean())
        rows.append(
            {
                "block": block,
                "triggered_event_dates": triggered_dates,
                "continued_event_dates": int(continued.signal_date.nunique()),
                "triggered_trades": len(triggered),
                "continued_trades": len(continued),
                "triggered_h20_mean_trade_payoff": triggered_mean,
                "continued_h20_mean_trade_payoff": continued_mean,
                "continued_minus_triggered": continued_mean - triggered_mean,
                "triggered_severe_loss_fraction": triggered_severe,
                "continued_severe_loss_fraction": continued_severe,
            }
        )
        checks[f"{block}_minimum_triggered_dates"] = triggered_dates >= 15
        checks[f"{block}_triggered_h20_nonpositive"] = triggered_mean <= 0.0
        checks[f"{block}_continued_minus_triggered_positive"] = continued_mean > triggered_mean
        checks[f"{block}_triggered_severe_worse"] = triggered_severe > continued_severe
    screen = pd.DataFrame(rows)
    return screen, {"checks": checks, "passed": all(checks.values())}


def _candidate_plans(plans: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    output = plans.merge(
        features[["signal_date", "industry", "triggered", "early_exit_index"]],
        on=["signal_date", "industry"],
        how="left",
        validate="many_to_one",
    )
    if output[["triggered", "early_exit_index"]].isna().any().any():
        raise IndustryD5ExitError("candidate decision lineage incomplete")
    output["due_index"] = np.where(
        output.triggered,
        output.early_exit_index,
        output.due_index,
    ).astype(int)
    return output.drop(columns=["triggered", "early_exit_index"])


def _render(result: dict[str, Any]) -> str:
    rows = result["screen"]["rows"]
    lines = [
        "# Industry-Consensus Q1 industry d5 exit V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "This is a post-hoc development repair generated from the consumed temporal-"
            "transfer anatomy and the failed entry-veto result. It is not confirmation."
        ),
        "",
        "## Frozen rule",
        "",
        (
            "After the fifth completed holding-session close, exit the same-industry pair "
            "at the next legal open only when its PIT industry's compounded d5 equal-weight "
            "return is nonpositive. Otherwise keep the exact h20 exit."
        ),
        "",
        "## Sequential screen",
        "",
        "| Block | Triggered / continued dates | Triggered / continued h20 mean | "
        "Spread | Severe triggered / continued |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['block']} | {row['triggered_event_dates']} / "
            f"{row['continued_event_dates']} | "
            f"{row['triggered_h20_mean_trade_payoff']:.3%} / "
            f"{row['continued_h20_mean_trade_payoff']:.3%} | "
            f"{row['continued_minus_triggered']:.3%} | "
            f"{row['triggered_severe_loss_fraction']:.2%} / "
            f"{row['continued_severe_loss_fraction']:.2%} |"
        )
    lines.extend(["", f"Screen passed: `{result['screen']['passed']}`.", ""])
    if result["candidate"] is None:
        lines.extend(
            [
                "The frozen gate failed, so no dynamic-exit portfolio replay was run.",
                "No alternate checkpoint, threshold, stock stop, or rescue was tested.",
            ]
        )
    else:
        candidate = result["candidate"]
        delta = result["comparison"]
        years = " | ".join(
            f"{year} {value:+.2%}"
            for year, value in result["calendar_year_returns"].items()
        )
        lines.extend(
            [
                "## Single executable replay",
                "",
                (
                    f"Annualized {candidate['annualized_return']:.2%}; total "
                    f"{candidate['total_return']:.2%}; max drawdown "
                    f"{candidate['maximum_drawdown']:.2%}; Sharpe "
                    f"{candidate['daily_sharpe']:.3f}; severe trades "
                    f"{candidate['severe_trade_fraction']:.2%}."
                ),
                (
                    f"Versus corrected baseline: annualized "
                    f"{delta['annualized_return_delta']:+.2%}; drawdown quality "
                    f"{delta['maximum_drawdown_improvement']:+.2%}; Sharpe "
                    f"{delta['daily_sharpe_delta']:+.3f}; severe-loss quality "
                    f"{delta['severe_trade_fraction_improvement']:+.2%}."
                ),
                f"Calendar years: {years}.",
                "",
                f"User return-and-drawdown target met: `{result['target_met']}`.",
            ]
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            (
                "The runner read only 2018--2023 market outcomes. 2024--2025 remain consumed "
                "diagnostic history and were not replayed. No 2026 market outcome or CY-011 "
                "was read."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    helper = _load_module(
        "overextension_helpers_for_d5",
        _resolve(spec["inputs"]["overextension_helper_runner"]["path"]),
    )
    numeric = _load_module(
        "numeric_erratum_for_d5",
        _resolve(spec["inputs"]["causal_numeric_erratum_runner"]["path"]),
    )
    base = _load_module(
        "event_baseline_for_d5",
        _resolve(spec["inputs"]["frozen_event_runner"]["path"]),
    )
    q1 = _load_module(
        "q1_for_d5", _resolve(spec["inputs"]["q1_runner"]["path"])
    )
    q1_spec = q1._load_spec()
    cycle016 = q1._load_module(
        "cycle016_for_d5",
        q1._resolve(q1_spec["inputs"]["champion_anatomy_runner"]["path"]),
    )
    panel_path = _resolve(spec["inputs"]["accepted_pre2024_daily_feature_panel"]["path"])
    daily = pd.read_parquet(panel_path)
    maximum_date = pd.to_datetime(daily.trade_date).max().date()
    if maximum_date > date(2023, 12, 31):
        raise IndustryD5ExitError("post-2023 feature row entered experiment")
    corrected, same_industry = helper._corrected_selection(
        daily, numeric, q1, cycle016
    )

    ca = cycle016.CA
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    partition_years: list[int] = []
    for path in paths:
        match = re.search(r"partition_year=(\d{4})", str(path))
        if match is None:
            raise IndustryD5ExitError(f"unparseable market partition: {path}")
        partition_years.append(int(match.group(1)))
    if partition_years != list(range(2018, 2024)):
        raise IndustryD5ExitError("post-2023 market partition resolved")

    plans = base._plans(same_industry, calendar)
    features = _event_features(corrected, plans, calendar)
    market_rows = ca.PRIOR._query_execution_rows(paths, plans, calendar)
    risk_events, action_audit = ca._load_risk_events(ca_spec, calendar)
    baseline, _, baseline_trades = base._replay(
        plans, market_rows, calendar, risk_events, ca
    )
    expected = spec["frozen_baseline"]
    if not math.isclose(
        baseline["annualized_return"],
        expected["corrected_2018_2023_annualized_return"],
        rel_tol=0.0,
        abs_tol=1e-12,
    ) or not math.isclose(
        baseline["maximum_drawdown"],
        expected["corrected_2018_2023_maximum_drawdown"],
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise IndustryD5ExitError("corrected baseline replay mismatch")

    mapped = helper._attach_plans_to_trades(baseline_trades, plans, calendar)
    screen, gate = _screen(mapped, features)
    helper._atomic_write(
        SCREEN_PATH,
        screen.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    decision_rows = features.copy()
    decision_rows["planned_exit_index"] = np.where(
        decision_rows.triggered,
        decision_rows.early_exit_index,
        decision_rows.normal_due_index,
    )
    decision_rows["planned_exit_date"] = decision_rows.planned_exit_index.map(
        lambda index: calendar[int(index)]
    )
    helper._atomic_write(
        DECISION_PATH,
        decision_rows.to_csv(
            index=False, lineterminator="\n", float_format="%.12g"
        ),
    )

    candidate: dict[str, Any] | None = None
    comparison: dict[str, float] | None = None
    calendar_year_returns: dict[str, float] | None = None
    target_checks: dict[str, bool] | None = None
    target_met = False
    if gate["passed"]:
        candidate_plans = _candidate_plans(plans, features)
        candidate, equity, trades = base._replay(
            candidate_plans, market_rows, calendar, risk_events, ca
        )
        comparison = helper._comparison(candidate, baseline)
        calendar_year_returns = base._year_returns(equity)
        target = spec["evaluation"]["user_target"]
        target_checks = {
            "annualized_return": candidate["annualized_return"]
            >= target["minimum_annualized_return"],
            "maximum_drawdown": candidate["maximum_drawdown"]
            > target["maximum_drawdown_must_be_greater_than"],
        }
        target_met = all(target_checks.values())
        helper._atomic_write(
            EQUITY_PATH,
            equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
        )
        helper._atomic_write(
            TRADES_PATH,
            trades.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
        )
        status = (
            "USER_TARGET_ACHIEVED_POST_HOC_DEVELOPMENT"
            if target_met
            else "INDUSTRY_D5_EXIT_REPLAY_TARGET_NOT_MET"
        )
    else:
        helper._atomic_write(
            EQUITY_PATH,
            "trade_date,family,nav,cash,positions,industries,industry_hhi\n",
        )
        helper._atomic_write(
            TRADES_PATH,
            "symbol,industry,exit_date,exit_reason,invested_cost,net_return\n",
        )
        status = "INDUSTRY_D5_EXIT_SCREEN_FAILED"

    result = {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "market_2026_outcome_read": "NO",
        "cy011_read": "NO",
        "maximum_market_outcome_date": str(maximum_date),
        "frozen_rule": spec["single_candidate_rule"],
        "baseline": baseline,
        "screen": {
            "rows": screen.to_dict(orient="records"),
            "checks": gate["checks"],
            "passed": gate["passed"],
        },
        "candidate": candidate,
        "comparison": comparison,
        "calendar_year_returns": calendar_year_returns,
        "target": spec["evaluation"]["user_target"],
        "target_checks": target_checks,
        "target_met": target_met,
        "decision_summary": {
            "events": len(features),
            "triggered_events": int(features.triggered.sum()),
            "continued_events": int((~features.triggered).sum()),
            "minimum_industry_d5_return": float(features.industry_d5_return.min()),
            "median_industry_d5_return": float(features.industry_d5_return.median()),
            "maximum_industry_d5_return": float(features.industry_d5_return.max()),
        },
        "input_identity": input_identity,
        "action_audit": action_audit,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "screen_sha256": sha256_file(SCREEN_PATH),
            "decision_sha256": sha256_file(DECISION_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
            "trades_sha256": sha256_file(TRADES_PATH),
        },
    }
    helper._atomic_write(
        RESULT_PATH, json.dumps(helper._clean(result), indent=2, sort_keys=True) + "\n"
    )
    helper._atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(
        json.dumps(
            run(),
            indent=2,
            sort_keys=True,
            default=lambda value: (
                value.item()
                if isinstance(value, np.generic)
                else value.isoformat()
                if isinstance(value, (date, pd.Timestamp))
                else str(value)
            ),
        )
    )
