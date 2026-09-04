#!/usr/bin/env python3
"""Test one frozen post-hoc industry-overextension veto on consumed history."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-INDUSTRY-CONSENSUS-Q1-OVEREXTENSION-VETO-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
SCREEN_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_screen.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
TRADES_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_trades.csv"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "2e1fbf5cf00703aa3cd0610a49dc8f3c02d85f1bf5e6fcd019d402643c936113"
OVEREXTENSION_THRESHOLD = 0.10


class OverextensionVetoError(RuntimeError):
    """Fail-closed error for the single frozen repair experiment."""


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
        raise OverextensionVetoError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise OverextensionVetoError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != (
        "FROZEN_POST_HOC_SINGLE_RULE_BEFORE_2018_2023_OUTCOME_JOIN"
    ):
        raise OverextensionVetoError("experiment is not frozen")
    if spec["single_candidate_rule"]["veto"] != (
        "industry_prior20_member_mean > 0.10"
    ):
        raise OverextensionVetoError("candidate rule changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise OverextensionVetoError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("2024 or 2025", "2026 market", "CY-011", "threshold grid"):
        if phrase not in prohibited:
            raise OverextensionVetoError(f"missing prohibition: {phrase}")
    return spec


def _corrected_selection(
    daily: pd.DataFrame, numeric: Any, q1: Any, cycle016: Any
) -> tuple[pd.DataFrame, pd.DataFrame]:
    corrected = numeric._canonicalize_diffusion(daily)
    champion = numeric._weekly_low_max(corrected, cycle016.CONSTRUCTION)
    selection = numeric._q1_selection(champion)
    if len(selection) != 534 or selection.trade_date.nunique() != 267:
        raise OverextensionVetoError("corrected Q1 selection breadth changed")
    same = selection.groupby("trade_date").industry.transform("nunique").eq(1)
    same_industry = selection.loc[same].copy()
    if not same_industry.groupby("trade_date").size().eq(2).all():
        raise OverextensionVetoError("same-industry pair breadth changed")
    return corrected, same_industry


def _event_features(
    corrected: pd.DataFrame, plans: pd.DataFrame
) -> pd.DataFrame:
    members = corrected[["trade_date", "industry", "r20"]].copy()
    if members.r20.isna().any():
        raise OverextensionVetoError("eligible r20 unexpectedly missing")
    members["member_return20"] = np.expm1(members.r20.astype(float))
    industry = (
        members.groupby(["trade_date", "industry"], sort=True)
        .member_return20.mean()
        .rename("industry_prior20_member_mean")
        .reset_index()
    )
    industry["signal_date"] = pd.to_datetime(industry.trade_date).dt.date
    events = plans[["signal_date", "industry"]].drop_duplicates().copy()
    events = events.merge(
        industry[["signal_date", "industry", "industry_prior20_member_mean"]],
        on=["signal_date", "industry"],
        how="left",
        validate="one_to_one",
    )
    if events.industry_prior20_member_mean.isna().any():
        raise OverextensionVetoError("event overextension feature missing")
    events["admitted"] = events.industry_prior20_member_mean.le(
        OVEREXTENSION_THRESHOLD
    )
    events["block"] = np.where(
        pd.to_datetime(events.signal_date).dt.year.le(2020),
        "2018-2020",
        "2021-2023",
    )
    return events.sort_values(["signal_date", "industry"]).reset_index(drop=True)


def _attach_plans_to_trades(
    trades: pd.DataFrame, plans: pd.DataFrame, calendar: list[date]
) -> pd.DataFrame:
    work = plans.copy().reset_index(drop=True)
    work["plan_id"] = np.arange(len(work), dtype=int)
    work["entry_date"] = work.entry_index.map(lambda index: calendar[int(index)])
    work["due_date"] = work.due_index.map(lambda index: calendar[int(index)])
    unused = set(work.plan_id.tolist())
    rows: list[dict[str, Any]] = []
    ordered = trades.copy()
    ordered["exit_date"] = pd.to_datetime(ordered.exit_date).dt.date
    ordered = ordered.sort_values(["exit_date", "symbol", "industry"])
    for trade in ordered.itertuples(index=False):
        candidates = work.loc[
            work.plan_id.isin(unused)
            & work.symbol.eq(trade.symbol)
            & work.industry.eq(trade.industry)
            & work.entry_date.le(trade.exit_date)
        ].copy()
        if trade.exit_reason == "DUE":
            candidates = candidates.loc[candidates.due_date.le(trade.exit_date)]
            candidates["distance"] = candidates.due_date.map(
                lambda item: (trade.exit_date - item).days
            )
        elif trade.exit_reason == "FORCED":
            candidates = candidates.loc[candidates.due_date.ge(trade.exit_date)]
            candidates["distance"] = candidates.due_date.map(
                lambda item: (item - trade.exit_date).days
            )
        else:
            raise OverextensionVetoError(f"unknown exit reason: {trade.exit_reason}")
        if candidates.empty:
            raise OverextensionVetoError(
                f"cannot map trade to plan: {trade.symbol}:{trade.exit_date}"
            )
        chosen = candidates.sort_values(["distance", "entry_index", "plan_id"]).iloc[0]
        unused.remove(int(chosen.plan_id))
        record = trade._asdict()
        record.update(
            {
                "plan_id": int(chosen.plan_id),
                "signal_date": chosen.signal_date,
                "entry_date": chosen.entry_date,
                "due_date": chosen.due_date,
            }
        )
        rows.append(record)
    output = pd.DataFrame(rows)
    if len(output) != len(trades) or output.plan_id.duplicated().any():
        raise OverextensionVetoError("trade-plan conservation failed")
    return output


def _screen(
    mapped_trades: pd.DataFrame, events: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    work = mapped_trades.merge(
        events,
        on=["signal_date", "industry"],
        how="left",
        validate="many_to_one",
    )
    if work[["industry_prior20_member_mean", "admitted", "block"]].isna().any().any():
        raise OverextensionVetoError("screen lineage incomplete")
    rows: list[dict[str, Any]] = []
    checks: dict[str, bool] = {}
    minimum = 20
    for block, block_rows in work.groupby("block", sort=True):
        retained = block_rows.loc[block_rows.admitted]
        vetoed = block_rows.loc[~block_rows.admitted]
        retained_dates = int(retained.signal_date.nunique())
        retained_mean = float(retained.net_return.mean())
        vetoed_mean = float(vetoed.net_return.mean())
        retained_severe = float(retained.net_return.le(-0.10).mean())
        vetoed_severe = float(vetoed.net_return.le(-0.10).mean())
        rows.append(
            {
                "block": block,
                "retained_event_dates": retained_dates,
                "vetoed_event_dates": int(vetoed.signal_date.nunique()),
                "retained_trades": len(retained),
                "vetoed_trades": len(vetoed),
                "retained_mean_trade_payoff": retained_mean,
                "vetoed_mean_trade_payoff": vetoed_mean,
                "retained_minus_vetoed": retained_mean - vetoed_mean,
                "retained_severe_loss_fraction": retained_severe,
                "vetoed_severe_loss_fraction": vetoed_severe,
            }
        )
        checks[f"{block}_minimum_retained_dates"] = retained_dates >= minimum
        checks[f"{block}_retained_mean_positive"] = retained_mean > 0
        checks[f"{block}_retained_minus_vetoed_positive"] = retained_mean > vetoed_mean
        checks[f"{block}_severe_no_worse"] = retained_severe <= vetoed_severe
    screen = pd.DataFrame(rows)
    return screen, {"checks": checks, "passed": all(checks.values())}


def _comparison(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    return {
        "annualized_return_delta": float(
            candidate["annualized_return"] - baseline["annualized_return"]
        ),
        "total_return_delta": float(
            candidate["total_return"] - baseline["total_return"]
        ),
        "maximum_drawdown_improvement": float(
            candidate["maximum_drawdown"] - baseline["maximum_drawdown"]
        ),
        "daily_sharpe_delta": float(
            candidate["daily_sharpe"] - baseline["daily_sharpe"]
        ),
        "severe_trade_fraction_improvement": float(
            baseline["severe_trade_fraction"] - candidate["severe_trade_fraction"]
        ),
    }


def _render(result: dict[str, Any]) -> str:
    screen = pd.DataFrame(result["screen"]["rows"])
    lines = [
        "# Industry-Consensus Q1 overextension veto V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "This is one post-hoc repair hypothesis generated after the consumed "
            "2024--2025 anatomy. It is not independent validation and the runner reads "
            "only consumed 2018--2023 outcomes."
        ),
        "",
        "## Frozen rule",
        "",
        (
            "Keep the exact Industry-Consensus Q1 event only when the signal-date PIT "
            "industry's mean member prior-20-session return is at most 10%. Everything "
            "else, including h20 and 20 bps per side, remains unchanged."
        ),
        "",
        "## Screen",
        "",
        "| Block | Retained / vetoed dates | Retained / vetoed mean | Spread | Severe retained / vetoed |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in screen.itertuples(index=False):
        lines.append(
            f"| {row.block} | {row.retained_event_dates} / {row.vetoed_event_dates} | "
            f"{row.retained_mean_trade_payoff:.3%} / {row.vetoed_mean_trade_payoff:.3%} | "
            f"{row.retained_minus_vetoed:.3%} | "
            f"{row.retained_severe_loss_fraction:.2%} / "
            f"{row.vetoed_severe_loss_fraction:.2%} |"
        )
    lines.extend(["", f"Screen passed: `{result['screen']['passed']}`.", ""])
    if result["candidate"] is None:
        lines.extend(
            [
                "The frozen sequential gate failed, so no candidate portfolio replay was run.",
                "No threshold, exit, sizing, saturation, or other rescue was tested.",
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
                    f"Versus the corrected baseline: annualized "
                    f"{delta['annualized_return_delta']:+.2%}; drawdown quality "
                    f"{delta['maximum_drawdown_improvement']:+.2%}; Sharpe "
                    f"{delta['daily_sharpe_delta']:+.3f}."
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
                "Post-2023 outcomes were not read by this experiment. 2024--2025 remain "
                "consumed diagnosis, not a reusable validation set. No 2026 market outcome "
                "or CY-011 was read."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    numeric = _load_module(
        "numeric_erratum_for_overextension",
        _resolve(spec["inputs"]["causal_numeric_erratum_runner"]["path"]),
    )
    base = _load_module(
        "event_baseline_for_overextension",
        _resolve(spec["inputs"]["frozen_event_runner"]["path"]),
    )
    q1 = _load_module(
        "q1_for_overextension", _resolve(spec["inputs"]["q1_runner"]["path"])
    )
    q1_spec = q1._load_spec()
    cycle016 = q1._load_module(
        "cycle016_for_overextension",
        q1._resolve(q1_spec["inputs"]["champion_anatomy_runner"]["path"]),
    )

    panel_path = _resolve(spec["inputs"]["accepted_pre2024_daily_feature_panel"]["path"])
    daily = pd.read_parquet(panel_path)
    maximum_date = pd.to_datetime(daily.trade_date).max().date()
    if maximum_date > date(2023, 12, 31):
        raise OverextensionVetoError("post-2023 feature row entered experiment")
    corrected, same_industry = _corrected_selection(daily, numeric, q1, cycle016)

    ca = cycle016.CA
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    partition_years = []
    for path in paths:
        match = re.search(r"partition_year=(\d{4})", str(path))
        if match is None:
            raise OverextensionVetoError(f"unparseable market partition: {path}")
        partition_years.append(int(match.group(1)))
    if partition_years != list(range(2018, 2024)):
        raise OverextensionVetoError("post-2023 market partition resolved")
    plans = base._plans(same_industry, calendar)
    features = _event_features(corrected, plans)
    market_rows = ca.PRIOR._query_execution_rows(paths, plans, calendar)
    risk_events, action_audit = ca._load_risk_events(ca_spec, calendar)
    baseline, baseline_equity, baseline_trades = base._replay(
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
        raise OverextensionVetoError("corrected baseline replay mismatch")

    mapped = _attach_plans_to_trades(baseline_trades, plans, calendar)
    screen, gate = _screen(mapped, features)
    screen_text = screen.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    _atomic_write(SCREEN_PATH, screen_text)

    candidate: dict[str, Any] | None = None
    comparison: dict[str, float] | None = None
    calendar_year_returns: dict[str, float] | None = None
    target_checks: dict[str, bool] | None = None
    target_met = False
    if gate["passed"]:
        admitted_dates = set(features.loc[features.admitted, "signal_date"])
        candidate_plans = plans.loc[plans.signal_date.isin(admitted_dates)].copy()
        candidate, equity, trades = base._replay(
            candidate_plans, market_rows, calendar, risk_events, ca
        )
        comparison = _comparison(candidate, baseline)
        calendar_year_returns = base._year_returns(equity)
        target = spec["evaluation"]["user_target"]
        target_checks = {
            "annualized_return": candidate["annualized_return"]
            >= target["minimum_annualized_return"],
            "maximum_drawdown": candidate["maximum_drawdown"]
            > target["maximum_drawdown_must_be_greater_than"],
        }
        target_met = all(target_checks.values())
        _atomic_write(
            EQUITY_PATH,
            equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
        )
        _atomic_write(
            TRADES_PATH,
            trades.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
        )
        status = (
            "USER_TARGET_ACHIEVED_POST_HOC_DEVELOPMENT"
            if target_met
            else "OVEREXTENSION_VETO_REPLAY_TARGET_NOT_MET"
        )
    else:
        _atomic_write(EQUITY_PATH, "trade_date,family,nav,cash,positions,industries,industry_hhi\n")
        _atomic_write(TRADES_PATH, "symbol,industry,exit_date,exit_reason,invested_cost,net_return\n")
        status = "OVEREXTENSION_VETO_SCREEN_FAILED"

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
        "event_feature_summary": {
            "events": len(features),
            "admitted_events": int(features.admitted.sum()),
            "vetoed_events": int((~features.admitted).sum()),
            "minimum": float(features.industry_prior20_member_mean.min()),
            "median": float(features.industry_prior20_member_mean.median()),
            "maximum": float(features.industry_prior20_member_mean.max()),
        },
        "input_identity": input_identity,
        "action_audit": action_audit,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "screen_sha256": sha256_file(SCREEN_PATH),
            "equity_sha256": sha256_file(EQUITY_PATH),
            "trades_sha256": sha256_file(TRADES_PATH),
        },
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
