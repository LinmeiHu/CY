#!/usr/bin/env python3
"""Run frozen medium-term overnight-strength A-share screen."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-MEDIUM-TERM-OVERNIGHT-STRENGTH-V1_spec.json"
TABLE_PATH = PROGRAM / "artifacts/ASHARE-MEDIUM-TERM-OVERNIGHT-STRENGTH-V1_event_table.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-MEDIUM-TERM-OVERNIGHT-STRENGTH-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-MEDIUM-TERM-OVERNIGHT-STRENGTH-V1_report.md"
EXPECTED_SPEC_SHA256 = "fd28f74cb733262c3b13e01b7ce44afafbea32608b71ee836b63e1c8ac194fe9"


class OvernightStrengthError(RuntimeError):
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
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        if not np.isfinite(value):
            raise OvernightStrengthError("non-finite result")
        return value
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise OvernightStrengthError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_AGGREGATION":
        raise OvernightStrengthError("spec is not frozen")
    for binding in spec["inputs"].values():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise OvernightStrengthError(f"bound input changed: {path}")
    return spec


def _attach_formation_and_response(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach exact 20-row formation and t+1..t+20 response windows."""
    ordered = frame.sort_values(["symbol", "cal_idx"], kind="mergesort").copy()
    groups = ordered.groupby("symbol", sort=False)
    prior_idx = groups["cal_idx"].shift(19)
    formation_complete = prior_idx.eq(ordered.cal_idx - 19)
    for source, target in (("gap_return", "overnight20"), ("intraday_return", "intraday20")):
        cumulative = groups[source].cumsum()
        prior_cumulative = cumulative.groupby(ordered.symbol, sort=False).shift(20)
        total = cumulative - prior_cumulative.fillna(0.0)
        ordered[target] = np.where(formation_complete, total, np.nan)

    cumulative_return = groups["step_return"].cumsum()
    future_cumulative = cumulative_return.groupby(ordered.symbol, sort=False).shift(-20)
    future_idx = groups["cal_idx"].shift(-20)
    response_complete = future_idx.eq(ordered.cal_idx + 20) & future_cumulative.notna()
    response_log = future_cumulative - cumulative_return
    ordered["response_complete"] = response_complete
    ordered["gross_h20"] = np.where(response_complete, np.expm1(response_log), np.nan)
    return ordered.sort_values(["trade_date", "symbol"], kind="mergesort")


def _month_end_dates(frame: pd.DataFrame) -> set[pd.Timestamp]:
    dates = pd.Series(frame.trade_date.drop_duplicates().sort_values())
    return set(dates.groupby(dates.dt.to_period("M")).max())


def _select_arms(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(
        ["trade_date", "overnight20", "symbol"],
        ascending=[True, False, True],
        kind="mergesort",
    ).copy()
    ordered["arm"] = "CONTROL"
    top_index = ordered.groupby("trade_date", sort=False).head(20).index
    bottom_index = ordered.groupby("trade_date", sort=False).tail(20).index
    ordered.loc[top_index, "arm"] = "TOP20"
    ordered.loc[bottom_index, "arm"] = "BOTTOM20"
    return ordered


def _safe_spearman(left: pd.Series, right: pd.Series) -> float:
    return float(left.rank(method="average").corr(right.rank(method="average")))


def _event_table(frame: pd.DataFrame, cost: float, minimum_candidates: int) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for trade_date, date_frame in frame.groupby("trade_date", sort=True):
        if len(date_frame) < minimum_candidates:
            continue
        complete = date_frame.loc[date_frame.response_complete]
        top_all = date_frame.loc[date_frame.arm.eq("TOP20")]
        bottom_all = date_frame.loc[date_frame.arm.eq("BOTTOM20")]
        top = complete.loc[complete.arm.eq("TOP20")]
        bottom = complete.loc[complete.arm.eq("BOTTOM20")]
        if top.empty or bottom.empty or complete.empty:
            continue
        top_net = top.gross_h20 - cost
        bottom_net = bottom.gross_h20 - cost
        control_net = complete.gross_h20 - cost
        records.append(
            {
                "trade_date": trade_date,
                "calendar_year": int(trade_date.year),
                "candidate_count": len(date_frame),
                "top_selected": len(top_all),
                "top_complete": len(top),
                "bottom_selected": len(bottom_all),
                "bottom_complete": len(bottom),
                "control_complete": len(complete),
                "top_mean_net": float(top_net.mean()),
                "top_median_net": float(top_net.median()),
                "top_positive_rate": float(top_net.gt(0).mean()),
                "top_severe_rate": float(top_net.le(-0.20).mean()),
                "control_mean_net": float(control_net.mean()),
                "control_severe_rate": float(control_net.le(-0.20).mean()),
                "bottom_mean_net": float(bottom_net.mean()),
                "top_minus_control": float(top_net.mean() - control_net.mean()),
                "top_minus_bottom": float(top_net.mean() - bottom_net.mean()),
                "signal_r20_rank_correlation": _safe_spearman(
                    date_frame.overnight20, date_frame.r20
                ),
                "signal_intraday20_rank_correlation": _safe_spearman(
                    date_frame.overnight20, date_frame.intraday20
                ),
            }
        )
    return pd.DataFrame.from_records(records).sort_values("trade_date").reset_index(drop=True)


def _summarize(events: pd.DataFrame, members: pd.DataFrame) -> dict[str, Any]:
    if events.empty:
        raise OvernightStrengthError("empty period summary")
    dates = set(events.trade_date)
    period = members.loc[members.trade_date.isin(dates)]
    top = period.loc[period.arm.eq("TOP20")]
    complete_top = top.loc[top.response_complete]
    complete_control = period.loc[period.response_complete]
    top_net = complete_top.gross_h20 - 0.004
    control_net = complete_control.gross_h20 - 0.004
    return {
        "dates": len(events),
        "first_date": events.trade_date.min(),
        "last_date": events.trade_date.max(),
        "top_selected": len(top),
        "top_complete": len(complete_top),
        "top_response_retention": float(len(complete_top) / len(top)),
        "symbols": int(complete_top.symbol.nunique()),
        "top_mean_net": float(events.top_mean_net.mean()),
        "top_security_median_net": float(top_net.median()),
        "top_positive_rate": float(top_net.gt(0).mean()),
        "top_severe_rate": float(top_net.le(-0.20).mean()),
        "control_mean_net": float(events.control_mean_net.mean()),
        "control_severe_rate": float(control_net.le(-0.20).mean()),
        "bottom_mean_net": float(events.bottom_mean_net.mean()),
        "top_minus_control": float(events.top_minus_control.mean()),
        "top_minus_bottom": float(events.top_minus_bottom.mean()),
        "median_signal_r20_rank_correlation": float(events.signal_r20_rank_correlation.median()),
        "median_signal_intraday20_rank_correlation": float(
            events.signal_intraday20_rank_correlation.median()
        ),
    }


def _generation_checks(
    summary: dict[str, Any], yearly: dict[str, Any], spec: dict[str, Any]
) -> dict[str, bool]:
    gate = spec["generation_gate_all_required"]
    return {
        "minimum_decision_dates": summary["dates"] >= gate["minimum_decision_dates"],
        "top20_mean_net_positive": summary["top_mean_net"] > 0,
        "top20_minus_event_mean": summary["top_minus_control"]
        >= gate["top20_minus_event_mean_minimum"],
        "top20_minus_bottom20": summary["top_minus_bottom"] >= gate["top20_minus_bottom20_minimum"],
        "both_calendar_years_positive": len(yearly) == 2
        and all(item["top_minus_control"] > 0 for item in yearly.values()),
        "severe_loss_not_worse": summary["top_severe_rate"] - summary["control_severe_rate"]
        <= gate["top20_severe_loss_not_more_than_event_by_pp"],
        "response_retention": summary["top_response_retention"]
        >= gate["minimum_top20_response_retention"],
        "distinct_from_r20": abs(summary["median_signal_r20_rank_correlation"])
        <= gate["maximum_absolute_median_signal_r20_rank_correlation"],
    }


def _validation_checks(
    summary: dict[str, Any], yearly: dict[str, Any], spec: dict[str, Any]
) -> dict[str, bool]:
    gate = spec["validation_gate_all_required"]
    nonnegative_years = sum(item["top_minus_control"] >= 0 for item in yearly.values())
    return {
        "top20_mean_net_positive": summary["top_mean_net"] > 0,
        "top20_minus_event_mean_positive": summary["top_minus_control"] > 0,
        "top20_minus_bottom20_positive": summary["top_minus_bottom"] > 0,
        "at_least_two_years_nonnegative": len(yearly) == 3 and nonnegative_years >= 2,
        "severe_loss_not_worse": summary["top_severe_rate"] - summary["control_severe_rate"]
        <= gate["top20_severe_loss_not_more_than_event_by_pp"],
        "response_retention": summary["top_response_retention"]
        >= gate["minimum_top20_response_retention"],
    }


def _render(result: dict[str, Any]) -> str:
    generation = result["generation"]
    lines = [
        "# A-share medium-term overnight-strength V1",
        "",
        (
            "This is a frozen local approximation of the cited 2026 A-share "
            "overnight-return prior, not an exact paper replication or independent "
            "confirmation."
        ),
        "",
        f"Generation gate: **{'PASS' if result['generation_passed'] else 'FAIL'}**.",
        f"Validation opened: **{result['validation_opened']}**.",
        f"Final classification: **{result['classification']}**.",
        "",
        "## Generation",
        "",
        (
            "| Dates | Top-20 net | Control net | Excess | Bottom-20 net | Top-bottom | "
            "Severe top/control | Retention | rho(signal,r20) | "
            "rho(signal,intraday20) |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {generation['dates']} | {generation['top_mean_net']:.3%} | "
            f"{generation['control_mean_net']:.3%} | "
            f"{generation['top_minus_control']:.3%} | "
            f"{generation['bottom_mean_net']:.3%} | "
            f"{generation['top_minus_bottom']:.3%} | "
            f"{generation['top_severe_rate']:.2%}/"
            f"{generation['control_severe_rate']:.2%} | "
            f"{generation['top_response_retention']:.2%} | "
            f"{generation['median_signal_r20_rank_correlation']:.3f} | "
            f"{generation['median_signal_intraday20_rank_correlation']:.3f} |"
        ),
        "",
        "## Chronology",
        "",
        "| Period | Dates | Top-20 net | Excess | Top-bottom | Severe top/control |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for period, yearly in (
        ("generation", result["generation_yearly"]),
        ("validation", result.get("validation_yearly", {})),
    ):
        for year, item in yearly.items():
            lines.append(
                f"| {period} {year} | {item['dates']} | "
                f"{item['top_mean_net']:.3%} | "
                f"{item['top_minus_control']:.3%} | "
                f"{item['top_minus_bottom']:.3%} | "
                f"{item['top_severe_rate']:.2%}/"
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
                    f"Top-20 net {validation['top_mean_net']:.3%}; excess "
                    f"{validation['top_minus_control']:.3%}; top-bottom "
                    f"{validation['top_minus_bottom']:.3%}; severe "
                    f"{validation['top_severe_rate']:.2%}/"
                    f"{validation['control_severe_rate']:.2%}."
                ),
            ]
        )
    lines.extend(
        [
            "",
            (
                "No portfolio replay, Strategy A/Q1 combination, post-2023 outcome, "
                "or CY-011 field was opened."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    columns = [
        "trade_date",
        "cal_idx",
        "decision_at",
        "available_at",
        "symbol",
        "step_return",
        "gap_return",
        "intraday_return",
        "r20",
    ]
    daily = pq.read_table(
        _resolve(spec["inputs"]["daily_feature_panel"]["path"]), columns=columns
    ).to_pandas()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    if len(daily) != spec["inputs"]["daily_feature_panel"]["rows"]:
        raise OvernightStrengthError("daily row identity mismatch")
    if daily.trade_date.max() > pd.Timestamp("2023-12-31"):
        raise OvernightStrengthError("post-2023 daily row read")
    required = [
        "trade_date",
        "cal_idx",
        "symbol",
        "step_return",
        "gap_return",
        "intraday_return",
        "r20",
    ]
    if (
        daily[required].isna().any().any()
        or daily.decision_at.isna().any()
        or daily.available_at.isna().any()
    ):
        raise OvernightStrengthError("required input or clock missing")
    if daily.duplicated(["trade_date", "symbol"]).any():
        raise OvernightStrengthError("duplicate date/symbol rows")

    daily = _attach_formation_and_response(daily)
    month_ends = _month_end_dates(daily)
    eligible = daily.loc[daily.trade_date.isin(month_ends) & daily.overnight20.notna()].copy()
    selected = _select_arms(eligible)
    events = _event_table(
        selected,
        spec["response"]["round_trip_cost"],
        spec["population"]["minimum_candidates_per_date"],
    )

    generation_events = events.loc[
        events.trade_date.between(pd.Timestamp("2019-01-01"), pd.Timestamp("2020-12-31"))
    ]
    generation = _summarize(generation_events, selected)
    generation_yearly = {
        str(year): _summarize(year_frame, selected)
        for year, year_frame in generation_events.groupby("calendar_year", sort=True)
    }
    generation_checks = _generation_checks(generation, generation_yearly, spec)
    generation_passed = all(generation_checks.values())

    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE",
        "classification": "GENERATION_REJECTED_NO_VALIDATION_OR_REPLAY",
        "external_prior": spec["external_prior"],
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
        "eligible_month_end_rows": len(eligible),
    }
    if generation_passed:
        validation_events = events.loc[
            events.trade_date.between(pd.Timestamp("2021-01-01"), pd.Timestamp("2023-12-31"))
        ]
        validation = _summarize(validation_events, selected)
        validation_yearly = {
            str(year): _summarize(year_frame, selected)
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

    event_csv = events.to_csv(index=False, lineterminator="\n", float_format="%.12g")
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
