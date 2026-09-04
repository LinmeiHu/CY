#!/usr/bin/env python3
"""Test the frozen h20 recurrence refinement of Industry-Consensus Q1."""

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

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = "ASHARE-INDUSTRY-CONSENSUS-Q1-RECURRENCE-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
SCHEDULE_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_schedule.csv"
SCREEN_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_screen.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
TRADE_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_trades.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
EXPECTED_SPEC_SHA256 = "7500b348e31c18539b377952cfa6d6a537a9ad49acc6dd75753d3741a721867f"


class Q1RecurrenceError(RuntimeError):
    """Fail-closed Q1 recurrence experiment error."""


def _sha256_file(path: Path) -> str:
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
        raise Q1RecurrenceError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> dict[str, Any]:
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise Q1RecurrenceError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_SEQUENTIAL_CHAMPION_DEEPENING_BEFORE_RECURRENCE_OUTCOMES":
        raise Q1RecurrenceError("spec is not frozen before recurrence outcomes")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or _sha256_file(path) != binding["sha256"]:
            raise Q1RecurrenceError(f"bound input changed: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("neighboring recurrence", "before every generation", "post-2023", "CY-011"):
        if phrase not in prohibited:
            raise Q1RecurrenceError(f"missing frozen prohibition: {phrase}")
    return spec


def _schedule(spec: dict[str, Any]) -> pd.DataFrame:
    panel_path = _resolve(spec["inputs"]["q1_trade_panel"]["path"])
    panel = pd.read_csv(
        panel_path,
        usecols=[
            "signal_date",
            "symbol",
            "industry",
            "diffusion_score",
            "max_return20",
            "intensity_bucket",
        ],
        parse_dates=["signal_date"],
    )
    q1 = panel.loc[panel.intensity_bucket.eq(1)].copy()
    q1 = q1.sort_values(
        ["signal_date", "diffusion_score", "max_return20", "symbol"],
        ascending=[True, False, True, True],
    )
    if q1.groupby("signal_date").size().ne(2).any():
        raise Q1RecurrenceError("exact Q1 pair breadth changed")
    accepted_dates = q1.groupby("signal_date").industry.nunique().eq(1)
    accepted = q1.loc[q1.signal_date.isin(accepted_dates.index[accepted_dates])].copy()
    if accepted.signal_date.nunique() != 99 or len(accepted) != 198:
        raise Q1RecurrenceError("accepted same-industry Q1 event set changed")

    feature_path = _resolve(spec["inputs"]["daily_feature_panel"]["path"])
    calendar = pd.read_parquet(feature_path, columns=["trade_date"])
    calendar = sorted(pd.to_datetime(calendar.trade_date).dt.date.unique())
    calendar_index = {day: index for index, day in enumerate(calendar)}
    event_dates = [pd.Timestamp(day).date() for day in sorted(accepted.signal_date.unique())]
    recurrent: dict[date, bool] = {}
    for current in event_dates:
        current_index = calendar_index[current]
        recurrent[current] = any(
            0 < current_index - calendar_index[prior] <= 20
            for prior in event_dates
            if prior < current
        )
    accepted["signal_date"] = accepted.signal_date.dt.date
    accepted["recurrence_h20"] = accepted.signal_date.map(recurrent)
    accepted["signal_year"] = pd.to_datetime(accepted.signal_date).dt.year
    if accepted.loc[accepted.recurrence_h20, "signal_date"].nunique() != 82:
        raise Q1RecurrenceError("frozen recurrence coverage changed")
    return accepted[
        [
            "signal_date",
            "symbol",
            "industry",
            "diffusion_score",
            "max_return20",
            "signal_year",
            "recurrence_h20",
        ]
    ].sort_values(
        ["signal_date", "diffusion_score", "max_return20", "symbol"],
        ascending=[True, False, True, True],
    )


def _phase_outcomes(
    spec: dict[str, Any], schedule: pd.DataFrame, years: list[int]
) -> pd.DataFrame:
    panel_path = _resolve(spec["inputs"]["q1_trade_panel"]["path"])
    connection = duckdb.connect()
    outcomes = connection.execute(
        """
        SELECT signal_date,symbol,final_net_return
        FROM read_csv_auto(?, header=true)
        WHERE signal_year IN (SELECT * FROM unnest(?)) AND intensity_bucket=1
        ORDER BY signal_date,symbol
        """,
        [str(panel_path), years],
    ).fetchdf()
    connection.close()
    outcomes["signal_date"] = pd.to_datetime(outcomes.signal_date).dt.date
    phase_schedule = schedule.loc[schedule.signal_year.isin(years)].copy()
    merged = phase_schedule.merge(
        outcomes,
        on=["signal_date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    if merged.final_net_return.isna().any():
        raise Q1RecurrenceError("missing accepted Q1 phase outcome")
    return merged


def _screen(phase: pd.DataFrame, required: dict[str, Any]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for label, flag in (("recurrent", True), ("isolated", False)):
        arm = phase.loc[phase.recurrence_h20.eq(flag)]
        groups[label] = {
            "event_dates": int(arm.signal_date.nunique()),
            "trades": len(arm),
            "mean_trade_return": float(arm.final_net_return.mean()),
            "median_trade_return": float(arm.final_net_return.median()),
            "positive_trade_fraction": float(arm.final_net_return.gt(0).mean()),
            "severe_trade_fraction": float(arm.final_net_return.le(-0.10).mean()),
        }
    recurrent = groups["recurrent"]
    isolated = groups["isolated"]
    yearly = {
        str(int(year)): float(group.final_net_return.mean())
        for year, group in phase.loc[phase.recurrence_h20].groupby("signal_year")
    }
    delta = recurrent["mean_trade_return"] - isolated["mean_trade_return"]
    checks = {
        "minimum_recurrent_dates": recurrent["event_dates"]
        >= required["minimum_recurrent_dates"],
        "minimum_isolated_dates": isolated["event_dates"]
        >= required["minimum_isolated_dates"],
        "recurrent_mean_positive": recurrent["mean_trade_return"]
        >= required["minimum_recurrent_mean_trade_return"],
        "recurrent_minus_isolated": delta
        >= required["minimum_recurrent_minus_isolated_mean_trade_return"],
        "severe_not_worse": recurrent["severe_trade_fraction"]
        <= isolated["severe_trade_fraction"],
        "positive_each_year": all(yearly.get(str(year), -1.0) > 0 for year in required["years"]),
    }
    return {
        "years": required["years"],
        "groups": groups,
        "recurrent_minus_isolated_mean_trade_return": float(delta),
        "recurrent_calendar_year_mean_trade_return": yearly,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _screen_rows(name: str, phase: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm, metrics in phase["groups"].items():
        rows.append({"phase": name, "arm": arm, **metrics})
    return rows


def _full_replay(
    spec: dict[str, Any], recurrence_dates: set[date]
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    base = _load_module(
        "baseline_for_q1_recurrence", _resolve(spec["inputs"]["baseline_runner"]["path"])
    )
    base_spec = base._load_spec()
    q1 = base._load_module(
        "q1_for_q1_recurrence", _resolve(base_spec["inputs"]["q1_runner"]["path"])
    )
    q1_spec = q1._load_spec()
    cycle016 = q1._load_module(
        "cycle016_for_q1_recurrence",
        q1._resolve(q1_spec["inputs"]["champion_anatomy_runner"]["path"]),
    )
    selection = q1._selection(q1_spec, cycle016)
    ca = cycle016.CA
    ca_spec = ca._load_spec()
    paths, calendar, input_identity = ca._load_market_inputs(ca_spec)
    plans = base._plans(selection, calendar)
    plans = plans.loc[plans.signal_date.isin(recurrence_dates)].copy()
    if plans.signal_date.nunique() != 82 or not plans.groupby("signal_date").size().eq(2).all():
        raise Q1RecurrenceError("replay recurrence plan set changed")
    market_rows = ca.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = ca._load_risk_events(ca_spec, calendar)
    base.FAMILY = "industry_consensus_q1_recurrence"
    candidate, equity, trades = base._replay(plans, market_rows, calendar, events, ca)
    return candidate, equity, trades, input_identity, action_audit


def _render(result: dict[str, Any]) -> str:
    lines = [
        "# Industry-Consensus Q1 h20 recurrence V1",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The frozen refinement keeps an exact same-industry Q1 event only when at "
            "least one earlier accepted Q1 event occurred in the preceding 20 market "
            "sessions. Entry, pair, h20 exit, one-half event capital, costs, and execution "
            "remain unchanged."
        ),
        "",
    ]
    for name in ("generation", "validation"):
        item = result.get(name)
        if not item:
            continue
        recurrent = item["groups"]["recurrent"]
        isolated = item["groups"]["isolated"]
        lines.extend(
            [
                f"## {name.title()}",
                "",
                (
                    f"Recurrent {recurrent['event_dates']} dates, mean "
                    f"{recurrent['mean_trade_return']:.2%}, severe "
                    f"{recurrent['severe_trade_fraction']:.2%}; isolated "
                    f"{isolated['event_dates']} dates, mean "
                    f"{isolated['mean_trade_return']:.2%}, severe "
                    f"{isolated['severe_trade_fraction']:.2%}; delta "
                    f"{item['recurrent_minus_isolated_mean_trade_return']:.2%}."
                ),
                f"Passed `{item['passed']}`; checks `{item['checks']}`.",
                "",
            ]
        )
    if result.get("candidate"):
        candidate = result["candidate"]
        lines.extend(
            [
                "## Full replay",
                "",
                (
                    f"Annualized {candidate['annualized_return']:.2%}; total "
                    f"{candidate['total_return']:.2%}; max drawdown "
                    f"{candidate['maximum_drawdown']:.2%}; Sharpe "
                    f"{candidate['daily_sharpe']:.3f}; events "
                    f"{candidate['event_dates']}."
                ),
                f"Improvement gates `{result['improvement_checks']}`.",
                "",
            ]
        )
    lines.extend(
        [
            "This is post-hoc sequential optimization on consumed 2018-2023 history, "
            "not OOS or independent confirmation. Post-2023 outcomes and CY-011 were "
            "not read. No neighboring recurrence window or rescue rule was tested.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    schedule = _schedule(spec)
    _atomic_write(
        SCHEDULE_PATH,
        schedule.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    protocol = spec["sequential_protocol"]
    generation_frame = _phase_outcomes(
        spec, schedule, protocol["generation"]["years"]
    )
    generation = _screen(generation_frame, protocol["generation"])
    screen_rows = _screen_rows("generation", generation)
    result: dict[str, Any] = {
        "experiment_id": EXPERIMENT_ID,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "event_dates": int(schedule.signal_date.nunique()),
        "recurrent_event_dates": int(
            schedule.loc[schedule.recurrence_h20, "signal_date"].nunique()
        ),
        "generation": generation,
        "validation_opened": False,
        "full_replay_opened": False,
    }
    if not generation["passed"]:
        result["status"] = "GENERATION_REJECTED_VALIDATION_UNOPENED"
    else:
        validation_frame = _phase_outcomes(
            spec, schedule, protocol["validation"]["years"]
        )
        validation = _screen(validation_frame, protocol["validation"])
        screen_rows.extend(_screen_rows("validation", validation))
        result.update({"validation_opened": True, "validation": validation})
        if not validation["passed"]:
            result["status"] = "VALIDATION_REJECTED_NO_FULL_REPLAY"
        else:
            recurrence_dates = set(
                schedule.loc[schedule.recurrence_h20, "signal_date"].unique()
            )
            candidate, equity, trades, input_identity, action_audit = _full_replay(
                spec, recurrence_dates
            )
            baseline = json.loads(
                _resolve(spec["inputs"]["baseline_result"]["path"]).read_text(
                    encoding="utf-8"
                )
            )["candidate"]
            full_gate = protocol["final_improvement_all_required"]
            calendar_year_returns = {
                str(int(year)): float(group.nav.iloc[-1] / group.nav.iloc[0] - 1.0)
                for year, group in equity.assign(
                    year=pd.to_datetime(equity.trade_date).dt.year
                ).groupby("year")
            }
            improvement_checks = {
                "annualized": candidate["annualized_return"]
                >= full_gate["minimum_annualized_return"],
                "drawdown": candidate["maximum_drawdown"]
                > full_gate["maximum_drawdown_must_be_greater_than"],
                "sharpe": candidate["daily_sharpe"]
                >= full_gate["minimum_daily_sharpe"],
                "positive_every_year": all(
                    value > 0 for value in calendar_year_returns.values()
                ),
            }
            _atomic_write(
                EQUITY_PATH,
                equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
            )
            _atomic_write(
                TRADE_PATH,
                trades.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
            )
            result.update(
                {
                    "full_replay_opened": True,
                    "candidate": candidate,
                    "baseline": baseline,
                    "comparison": {
                        "annualized_return_delta": candidate["annualized_return"]
                        - baseline["annualized_return"],
                        "maximum_drawdown_improvement": candidate["maximum_drawdown"]
                        - baseline["maximum_drawdown"],
                        "daily_sharpe_delta": candidate["daily_sharpe"]
                        - baseline["daily_sharpe"],
                    },
                    "calendar_year_returns": calendar_year_returns,
                    "improvement_checks": improvement_checks,
                    "input_identity": input_identity,
                    "action_audit": action_audit,
                    "status": (
                        "RECURRENCE_OPTIMIZATION_ACCEPTED"
                        if all(improvement_checks.values())
                        else "RECURRENCE_OPTIMIZATION_NOT_ACCEPTED"
                    ),
                }
            )
    _atomic_write(
        SCREEN_PATH,
        pd.DataFrame(screen_rows).to_csv(
            index=False, lineterminator="\n", float_format="%.12g"
        ),
    )
    hashes = {
        "spec_sha256": _sha256_file(SPEC_PATH),
        "schedule_sha256": _sha256_file(SCHEDULE_PATH),
        "screen_sha256": _sha256_file(SCREEN_PATH),
    }
    if result.get("full_replay_opened"):
        hashes.update(
            {
                "equity_sha256": _sha256_file(EQUITY_PATH),
                "trades_sha256": _sha256_file(TRADE_PATH),
            }
        )
    result["hashes"] = hashes
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
