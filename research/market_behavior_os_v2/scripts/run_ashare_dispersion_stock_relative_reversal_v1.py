#!/usr/bin/env python3
"""Run frozen high-dispersion stock-relative reversal information screen."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-DISPERSION-STOCK-RELATIVE-REVERSAL-V1_spec.json"
TABLE_PATH = PROGRAM / "artifacts/ASHARE-DISPERSION-STOCK-RELATIVE-REVERSAL-V1_event_table.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-DISPERSION-STOCK-RELATIVE-REVERSAL-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-DISPERSION-STOCK-RELATIVE-REVERSAL-V1_report.md"
EXPECTED_SPEC_SHA256 = "f8b20d535792dbe24879617831dd666e0786dc1741436b4972c0aeb65df512d0"


class DispersionStockRelativeReversalError(RuntimeError):
    """Fail-closed experiment error."""


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
    if isinstance(value, (np.floating,)):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            raise DispersionStockRelativeReversalError("non-finite result")
        return value
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%d")
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DispersionStockRelativeReversalError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_AGGREGATION":
        raise DispersionStockRelativeReversalError("spec is not frozen")
    for binding in spec["inputs"].values():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionStockRelativeReversalError(f"bound input changed: {path}")
    return spec


def _attach_exact_h3(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach t+1..t+3 response only when all calendar steps are consecutive."""
    ordered = frame.sort_values(["symbol", "cal_idx"], kind="mergesort").copy()
    groups = ordered.groupby("symbol", sort=False)
    response = np.zeros(len(ordered), dtype=float)
    complete = np.ones(len(ordered), dtype=bool)
    for offset in (1, 2, 3):
        future_idx = groups["cal_idx"].shift(-offset)
        future_return = groups["step_return"].shift(-offset)
        valid = future_idx.eq(ordered["cal_idx"] + offset) & future_return.notna()
        complete &= valid.to_numpy()
        response += future_return.fillna(0.0).to_numpy()
    ordered["response_complete"] = complete
    ordered["gross_h3"] = np.where(complete, np.expm1(response), np.nan)
    return ordered.sort_values(["trade_date", "industry", "symbol"], kind="mergesort")


def _select_arms(frame: pd.DataFrame) -> pd.DataFrame:
    """Select one lowest and one highest signal per date/industry without outcomes."""
    keys = ["trade_date", "industry"]
    ordered = frame.sort_values([*keys, "signal", "symbol"], kind="mergesort").copy()
    ordered["arm"] = "CONTROL"
    low_index = ordered.groupby(keys, sort=False).head(1).index
    high_index = ordered.groupby(keys, sort=False).tail(1).index
    ordered.loc[low_index, "arm"] = "CANDIDATE"
    ordered.loc[high_index, "arm"] = "OPPOSITE"
    return ordered


def _event_table(frame: pd.DataFrame, cost: float) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for trade_date, date_frame in frame.groupby("trade_date", sort=True):
        complete = date_frame.loc[date_frame.response_complete].copy()
        candidate_all = date_frame.loc[date_frame.arm.eq("CANDIDATE")]
        opposite_all = date_frame.loc[date_frame.arm.eq("OPPOSITE")]
        candidate = complete.loc[complete.arm.eq("CANDIDATE")]
        opposite = complete.loc[complete.arm.eq("OPPOSITE")]
        if complete.empty or candidate.empty or opposite.empty:
            continue
        candidate_net = candidate.gross_h3 - cost
        opposite_net = opposite.gross_h3 - cost
        control_net = complete.gross_h3 - cost
        records.append(
            {
                "trade_date": trade_date,
                "calendar_year": int(trade_date.year),
                "dispersion_state": float(date_frame.dispersion_state.iloc[0]),
                "candidate_selected": len(candidate_all),
                "candidate_complete": len(candidate),
                "opposite_selected": len(opposite_all),
                "opposite_complete": len(opposite),
                "control_complete": len(complete),
                "candidate_mean_net": float(candidate_net.mean()),
                "candidate_median_net": float(candidate_net.median()),
                "candidate_positive_rate": float(candidate_net.gt(0).mean()),
                "candidate_severe_rate": float(candidate_net.le(-0.10).mean()),
                "control_mean_net": float(control_net.mean()),
                "control_severe_rate": float(control_net.le(-0.10).mean()),
                "opposite_mean_net": float(opposite_net.mean()),
                "candidate_minus_control": float(candidate_net.mean() - control_net.mean()),
                "candidate_minus_opposite": float(candidate_net.mean() - opposite_net.mean()),
            }
        )
    return pd.DataFrame.from_records(records).sort_values("trade_date").reset_index(drop=True)


def _summarize(events: pd.DataFrame, members: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        raise DispersionStockRelativeReversalError("empty period summary")
    date_set = set(events.trade_date)
    period_members = members.loc[members.trade_date.isin(date_set)]
    candidate = period_members.loc[period_members.arm.eq("CANDIDATE")]
    complete_candidate = candidate.loc[candidate.response_complete]
    complete_control = period_members.loc[period_members.response_complete]
    candidate_net = complete_candidate.gross_h3 - 0.004
    control_net = complete_control.gross_h3 - 0.004
    return {
        "dates": len(events),
        "first_date": events.trade_date.min(),
        "last_date": events.trade_date.max(),
        "candidate_selected": len(candidate),
        "candidate_complete": len(complete_candidate),
        "candidate_response_retention": float(len(complete_candidate) / len(candidate)),
        "industries": int(complete_candidate.industry.nunique()),
        "symbols": int(complete_candidate.symbol.nunique()),
        "candidate_mean_net": float(events.candidate_mean_net.mean()),
        "candidate_median_event_net": float(events.candidate_mean_net.median()),
        "candidate_security_median_net": float(candidate_net.median()),
        "candidate_positive_rate": float(candidate_net.gt(0).mean()),
        "candidate_severe_rate": float(candidate_net.le(-0.10).mean()),
        "control_mean_net": float(events.control_mean_net.mean()),
        "control_severe_rate": float(control_net.le(-0.10).mean()),
        "opposite_mean_net": float(events.opposite_mean_net.mean()),
        "candidate_minus_control": float(events.candidate_minus_control.mean()),
        "candidate_minus_opposite": float(events.candidate_minus_opposite.mean()),
    }


def _generation_checks(
    summary: dict[str, Any], yearly: dict[str, Any], spec: dict[str, Any]
) -> dict[str, bool]:
    gate = spec["generation_gate_all_required"]
    severe_limit = gate["candidate_severe_loss_not_more_than_event_by_pp"]
    return {
        "minimum_high_state_dates": summary["dates"] >= gate["minimum_high_state_dates"],
        "candidate_mean_net_positive": summary["candidate_mean_net"] > 0,
        "candidate_minus_event_mean": summary["candidate_minus_control"]
        >= gate["candidate_minus_event_mean_minimum"],
        "candidate_minus_opposite_arm": summary["candidate_minus_opposite"]
        >= gate["candidate_minus_opposite_arm_minimum"],
        "candidate_median_event_net_positive": summary["candidate_median_event_net"] > 0,
        "both_calendar_years_positive": len(yearly) == 2
        and all(item["candidate_minus_control"] > 0 for item in yearly.values()),
        "severe_loss_not_worse": summary["candidate_severe_rate"] - summary["control_severe_rate"]
        <= severe_limit,
        "response_retention": summary["candidate_response_retention"]
        >= gate["minimum_candidate_response_retention"],
    }


def _validation_checks(
    summary: dict[str, Any], yearly: dict[str, Any], spec: dict[str, Any]
) -> dict[str, bool]:
    gate = spec["validation_gate_all_required"]
    severe_limit = gate["candidate_severe_loss_not_more_than_event_by_pp"]
    return {
        "candidate_mean_net_positive": summary["candidate_mean_net"] > 0,
        "candidate_minus_event_mean_positive": summary["candidate_minus_control"] > 0,
        "candidate_minus_opposite_arm_positive": summary["candidate_minus_opposite"] > 0,
        "both_calendar_years_nonnegative": len(yearly) == 2
        and all(item["candidate_minus_control"] >= 0 for item in yearly.values()),
        "severe_loss_not_worse": summary["candidate_severe_rate"] - summary["control_severe_rate"]
        <= severe_limit,
        "response_retention": summary["candidate_response_retention"]
        >= gate["minimum_candidate_response_retention"],
    }


def _render(result: dict[str, Any]) -> str:
    generation = result["generation"]
    lines = [
        "# A-share high-dispersion stock-relative reversal V1",
        "",
        (
            "This frozen information screen buys no portfolio and does not modify "
            "Strategy A or Industry-Consensus Q1."
        ),
        "",
        f"Generation gate: **{'PASS' if result['generation_passed'] else 'FAIL'}**.",
        f"Validation opened: **{result['validation_opened']}**.",
        f"Final classification: **{result['classification']}**.",
        "",
        "## Frozen mechanism",
        "",
        (
            "On an accepted ALL_A/ALL_STATUS high-dispersion close, choose the one "
            "lowest same-session stock-minus-leave-one-out-industry return in every "
            "industry with at least six eligible names. The screen response starts "
            "at t+1 and spans three exact action-aware sessions, net of 20 bps per side."
        ),
        "",
        "## Generation",
        "",
        (
            "| Dates | Candidate net | Control net | Candidate-control | Opposite net | "
            "Candidate-opposite | Median event | Severe candidate/control | Retention |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {generation['dates']} | {generation['candidate_mean_net']:.3%} | "
            f"{generation['control_mean_net']:.3%} | "
            f"{generation['candidate_minus_control']:.3%} | "
            f"{generation['opposite_mean_net']:.3%} | "
            f"{generation['candidate_minus_opposite']:.3%} | "
            f"{generation['candidate_median_event_net']:.3%} | "
            f"{generation['candidate_severe_rate']:.2%}/"
            f"{generation['control_severe_rate']:.2%} | "
            f"{generation['candidate_response_retention']:.2%} |"
        ),
        "",
        "## Chronology",
        "",
        (
            "| Period | Dates | Candidate net | Candidate-control | "
            "Candidate-opposite | Severe candidate/control |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for period_name, yearly in (
        ("generation", result["generation_yearly"]),
        ("validation", result.get("validation_yearly", {})),
    ):
        for year, item in yearly.items():
            lines.append(
                f"| {period_name} {year} | {item['dates']} | "
                f"{item['candidate_mean_net']:.3%} | "
                f"{item['candidate_minus_control']:.3%} | "
                f"{item['candidate_minus_opposite']:.3%} | "
                f"{item['candidate_severe_rate']:.2%}/"
                f"{item['control_severe_rate']:.2%} |"
            )
    if result["validation_opened"]:
        validation = result["validation"]
        lines.extend(
            [
                "",
                "## Fixed validation",
                "",
                (
                    f"Candidate net {validation['candidate_mean_net']:.3%}; "
                    "candidate-control "
                    f"{validation['candidate_minus_control']:.3%}; "
                    "candidate-opposite "
                    f"{validation['candidate_minus_opposite']:.3%}; severe "
                    f"{validation['candidate_severe_rate']:.2%}/"
                    f"{validation['control_severe_rate']:.2%}."
                ),
            ]
        )
    lines.extend(
        [
            "",
            (
                "No next-open portfolio replay, Strategy A combination, post-2023 "
                "outcome, or CY-011 field was opened unless explicitly stated above."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    daily_path = _resolve(spec["inputs"]["daily_feature_panel"]["path"])
    columns = [
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "industry",
        "step_return",
        "industry_return_loo",
    ]
    daily = pq.read_table(daily_path, columns=columns).to_pandas()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    if len(daily) != spec["inputs"]["daily_feature_panel"]["rows"]:
        raise DispersionStockRelativeReversalError("daily row identity mismatch")
    if daily.trade_date.max() > pd.Timestamp("2023-12-31"):
        raise DispersionStockRelativeReversalError("post-2023 daily row read")
    if (
        daily[["trade_date", "cal_idx", "symbol", "industry", "step_return", "industry_return_loo"]]
        .isna()
        .any()
        .any()
    ):
        raise DispersionStockRelativeReversalError("required daily input missing")
    if daily.duplicated(["trade_date", "symbol"]).any():
        raise DispersionStockRelativeReversalError("duplicate date/symbol rows")
    if daily.decision_at.isna().any() or daily.available_at.isna().any():
        raise DispersionStockRelativeReversalError("unknown availability clock")

    state_column = "industry_return_dispersion_iqr_pit_3y_pct"
    state = pd.read_csv(
        _resolve(spec["inputs"]["industry_state_panel"]["path"]),
        usecols=["trade_date", "market_view", "denominator", state_column],
        parse_dates=["trade_date"],
    )
    state = state.loc[
        state.market_view.eq(spec["population"]["market_view"])
        & state.denominator.eq(spec["population"]["denominator"]),
        ["trade_date", state_column],
    ].rename(columns={state_column: "dispersion_state"})
    if state.duplicated("trade_date").any():
        raise DispersionStockRelativeReversalError("duplicate state dates")

    daily = _attach_exact_h3(daily)
    daily["industry_size"] = daily.groupby(["trade_date", "industry"], sort=False).symbol.transform(
        "size"
    )
    daily = daily.loc[
        daily.industry_size.ge(spec["population"]["minimum_industry_members_at_t"])
    ].copy()
    daily["signal"] = daily.step_return - daily.industry_return_loo
    daily = daily.merge(state, on="trade_date", how="left", validate="many_to_one")
    high = daily.loc[daily.dispersion_state.ge(0.80)].copy()
    if high.empty:
        raise DispersionStockRelativeReversalError("no high-dispersion rows")
    members = _select_arms(high)
    events = _event_table(members, spec["response"]["round_trip_cost"])

    generation_events = events.loc[
        events.trade_date.between(pd.Timestamp("2020-07-01"), pd.Timestamp("2021-12-31"))
    ].copy()
    generation = _summarize(generation_events, members)
    generation_yearly = {
        str(year): _summarize(year_frame, members)
        for year, year_frame in generation_events.groupby("calendar_year", sort=True)
    }
    generation_checks = _generation_checks(generation, generation_yearly, spec)
    generation_passed = all(generation_checks.values())

    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE",
        "classification": "GENERATION_REJECTED_NO_VALIDATION_OR_REPLAY",
        "generation": generation,
        "generation_yearly": generation_yearly,
        "generation_checks": generation_checks,
        "generation_passed": generation_passed,
        "validation_opened": False,
        "portfolio_replay_opened": False,
        "strategy_a_modified": False,
        "industry_consensus_q1_modified": False,
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "maximum_outcome_date": "2023-12-31",
        "same_bar_fill_assumed": False,
        "input_rows": len(daily),
        "high_state_rows": len(high),
    }
    if generation_passed:
        validation_events = events.loc[
            events.trade_date.between(pd.Timestamp("2022-01-01"), pd.Timestamp("2023-12-31"))
        ].copy()
        validation = _summarize(validation_events, members)
        validation_yearly = {
            str(year): _summarize(year_frame, members)
            for year, year_frame in validation_events.groupby("calendar_year", sort=True)
        }
        validation_checks = _validation_checks(validation, validation_yearly, spec)
        validation_passed = all(validation_checks.values())
        result.update(
            {
                "validation_opened": True,
                "validation": validation,
                "validation_yearly": validation_yearly,
                "validation_checks": validation_checks,
                "validation_passed": validation_passed,
                "classification": (
                    "INFORMATION_GATES_PASS_FREEZE_EXECUTABLE_CONTRACT"
                    if validation_passed
                    else "VALIDATION_REJECTED_NO_REPLAY"
                ),
            }
        )

    output_events = events.loc[events.trade_date.le(pd.Timestamp("2023-12-31"))].copy()
    event_csv = output_events.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    _atomic_write(TABLE_PATH, event_csv)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "event_table_sha256": sha256_file(TABLE_PATH),
    }
    report = _render(_clean(result))
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n"
    )
    return _clean(result)


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True, default=str))
