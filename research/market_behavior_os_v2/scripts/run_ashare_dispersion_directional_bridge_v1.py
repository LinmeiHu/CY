#!/usr/bin/env python3
"""Bounded directional bridge for the resource-parked dispersion family."""

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
SPEC_PATH = PROGRAM / "experiments/ASHARE-DISPERSION-DIRECTIONAL-BRIDGE-V1_spec.json"
PANEL_PATH = PROGRAM / "artifacts/ASHARE-DISPERSION-DIRECTIONAL-BRIDGE-V1_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-DISPERSION-DIRECTIONAL-BRIDGE-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-DISPERSION-DIRECTIONAL-BRIDGE-V1_report.md"


class DispersionDirectionalBridgeError(RuntimeError):
    """Fail-closed bounded dispersion bridge error."""


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
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_DIRECTIONAL_RESPONSE":
        raise DispersionDirectionalBridgeError("bridge specification is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionDirectionalBridgeError(f"bound input changed: {name}")
    forbidden = "|".join(spec["prohibited"])
    for phrase in ("same-session fill", "post-2023", "CY-011", "portfolio PnL"):
        if phrase not in forbidden:
            raise DispersionDirectionalBridgeError(f"missing prohibition: {phrase}")
    return spec


def _load_stock_panel(path: Path, start: str | None, end: str) -> pd.DataFrame:
    filters: list[tuple[str, str, pd.Timestamp]] = [
        ("trade_date", "<=", pd.Timestamp(end))
    ]
    if start is not None:
        filters.append(("trade_date", ">=", pd.Timestamp(start)))
    frame = pd.read_parquet(
        path,
        columns=["trade_date", "cal_idx", "symbol", "industry", "step_return"],
        filters=filters,
    )
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    if frame.empty or frame.duplicated(["trade_date", "symbol"]).any():
        raise DispersionDirectionalBridgeError("invalid compact stock panel")
    if frame.trade_date.max() > pd.Timestamp("2023-12-31"):
        raise DispersionDirectionalBridgeError("post-2023 row reached bridge")
    if not np.isfinite(frame.step_return.to_numpy(float)).all():
        raise DispersionDirectionalBridgeError("nonfinite step return")
    return frame.sort_values(["symbol", "cal_idx"]).reset_index(drop=True)


def _industry_responses(
    stocks: pd.DataFrame,
    decision_start: str,
    decision_end: str,
    horizons: list[int],
) -> pd.DataFrame:
    grouped = stocks.groupby("symbol", sort=False)
    for offset in range(1, max(horizons) + 1):
        stocks[f"lead_idx_{offset}"] = grouped.cal_idx.shift(-offset)
        stocks[f"lead_return_{offset}"] = grouped.step_return.shift(-offset)
    decision_mask = stocks.trade_date.between(decision_start, decision_end)
    anchor = stocks.loc[decision_mask].copy()
    totals = (
        anchor.groupby(["trade_date", "industry"], sort=True)
        .agg(t_members=("symbol", "size"), current_industry_return=("step_return", "median"))
        .reset_index()
    )
    outputs: list[pd.DataFrame] = []
    for horizon in horizons:
        valid = pd.Series(True, index=anchor.index)
        response = pd.Series(0.0, index=anchor.index)
        for offset in range(1, horizon + 1):
            valid &= anchor[f"lead_idx_{offset}"].eq(anchor.cal_idx + offset)
            valid &= anchor[f"lead_return_{offset}"].notna()
            response += anchor[f"lead_return_{offset}"].fillna(0.0)
        work = anchor.loc[valid, ["trade_date", "industry"]].copy()
        work["security_response"] = response.loc[valid]
        future = (
            work.groupby(["trade_date", "industry"], sort=True)
            .agg(
                future_members=("security_response", "size"),
                future_industry_return=("security_response", "median"),
            )
            .reset_index()
        )
        item = totals.merge(future, on=["trade_date", "industry"], validate="one_to_one")
        item["retention"] = item.future_members / item.t_members
        item = item.loc[
            item.t_members.ge(6) & item.future_members.ge(5) & item.retention.ge(0.8)
        ].copy()
        item["horizon"] = horizon
        outputs.append(item)
    output = pd.concat(outputs, ignore_index=True)
    if output.empty or output.duplicated(["trade_date", "industry", "horizon"]).any():
        raise DispersionDirectionalBridgeError("invalid industry response panel")
    return output


def _daily_diagnostics(industry: pd.DataFrame, states: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (trade_date, horizon), group in industry.groupby(["trade_date", "horizon"], sort=True):
        if len(group) < 10:
            continue
        rank_ic = float(
            spearmanr(group.current_industry_return, group.future_industry_return).statistic
        )
        ranks = group.current_industry_return.rank(method="average", pct=True)
        top = group.loc[ranks.gt(0.8), "future_industry_return"]
        bottom = group.loc[ranks.le(0.2), "future_industry_return"]
        rows.append(
            {
                "trade_date": trade_date,
                "horizon": horizon,
                "industries": len(group),
                "rank_ic": rank_ic,
                "top_bottom_spread": float(top.median() - bottom.median()),
                "top_return": float(top.median()),
                "bottom_return": float(bottom.median()),
            }
        )
    output = pd.DataFrame(rows).merge(states, on="trade_date", validate="many_to_one")
    output["dispersion_state"] = np.select(
        [output.dispersion_pct.ge(0.8), output.dispersion_pct.le(0.2)],
        ["HIGH", "LOW"],
        default="MID",
    )
    output["year"] = output.trade_date.dt.year
    return output.sort_values(["trade_date", "horizon"]).reset_index(drop=True)


def _summarize(panel: pd.DataFrame, label: str) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for state in ("HIGH", "MID", "LOW"):
        rows[state] = {}
        for horizon in (1, 3, 5):
            frame = panel.loc[
                panel.dispersion_state.eq(state) & panel.horizon.eq(horizon)
            ]
            rows[state][f"h{horizon}"] = {
                "dates": int(frame.trade_date.nunique()),
                "median_rank_ic": float(frame.rank_ic.median()),
                "mean_rank_ic": float(frame.rank_ic.mean()),
                "mean_top_bottom_spread": float(frame.top_bottom_spread.mean()),
                "median_top_return": float(frame.top_return.median()),
                "median_bottom_return": float(frame.bottom_return.median()),
            }
    yearly: dict[str, Any] = {}
    high_h3 = panel.loc[panel.dispersion_state.eq("HIGH") & panel.horizon.eq(3)]
    for year, frame in high_h3.groupby("year", sort=True):
        yearly[str(year)] = {
            "dates": int(frame.trade_date.nunique()),
            "median_rank_ic": float(frame.rank_ic.median()),
            "mean_top_bottom_spread": float(frame.top_bottom_spread.mean()),
        }
    return {"label": label, "states": rows, "high_h3_by_year": yearly}


def _generation_passes(summary: dict[str, Any], spec: dict[str, Any]) -> bool:
    gate = spec["generation_gate_all_required"]
    high = summary["states"]["HIGH"]
    years = summary["high_h3_by_year"]
    return (
        high["h3"]["dates"] >= int(gate["minimum_high_state_dates"])
        and high["h3"]["median_rank_ic"]
        >= float(gate["high_dispersion_primary_median_rank_ic_minimum"])
        and high["h3"]["mean_top_bottom_spread"] > 0
        and high["h1"]["median_rank_ic"] >= 0
        and high["h5"]["median_rank_ic"] >= 0
        and len(years) >= 2
        and all(row["median_rank_ic"] > 0 for row in years.values())
    )


def _validation_passes(summary: dict[str, Any]) -> bool:
    high = summary["states"]["HIGH"]
    years = summary["high_h3_by_year"]
    return (
        high["h3"]["median_rank_ic"] > 0
        and high["h3"]["mean_top_bottom_spread"] > 0
        and high["h1"]["median_rank_ic"] >= 0
        and high["h5"]["median_rank_ic"] >= 0
        and set(years) == {"2022", "2023"}
        and all(row["median_rank_ic"] >= 0 for row in years.values())
    )


def _report(result: dict[str, Any]) -> str:
    lines = [
        "# A-share dispersion directional bridge V1",
        "",
        "This bounded bridge uses the accepted compact Cycle-015 PIT panel; "
        "it does not rerun either failed raw dispersion builder.",
        "",
        f"Generation gate: **{'PASS' if result['generation_passes'] else 'FAIL'}**.",
        f"Fixed validation opened: **{result['validation_opened']}**.",
        f"Final classification: **{result['classification']}**.",
        "",
        "## Directional anatomy",
        "",
        "| Period | State | Horizon | Dates | Median rank IC | Mean top-bottom spread "
        "| Median top / bottom |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for summary in result["summaries"]:
        for state, horizons in summary["states"].items():
            for horizon in (1, 3, 5):
                row = horizons[f"h{horizon}"]
                lines.append(
                    f"| {summary['label']} | {state} | {horizon} | {row['dates']} | "
                    f"{row['median_rank_ic']:.4f} | {row['mean_top_bottom_spread']:.4%} | "
                    f"{row['median_top_return']:.4%} / {row['median_bottom_return']:.4%} |"
                )
    lines.extend(
        [
            "",
            "No strategy or portfolio PnL is authorized unless both temporal gates pass.",
            "Post-2023 outcomes and CY-011 were not read.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec = _load_spec()
    stock_path = _resolve(spec["inputs"]["daily_feature_panel"]["path"])
    state_columns = [
        "trade_date",
        "market_view",
        "denominator",
        "industry_return_dispersion_iqr_pit_3y_pct",
    ]
    states = pd.read_csv(
        _resolve(spec["inputs"]["industry_state_panel"]["path"]),
        usecols=state_columns,
        parse_dates=["trade_date"],
    )
    states = states.loc[
        states.market_view.eq("ALL_A") & states.denominator.eq("ALL_STATUS")
    ][["trade_date", "industry_return_dispersion_iqr_pit_3y_pct"]].dropna()
    states = states.rename(
        columns={"industry_return_dispersion_iqr_pit_3y_pct": "dispersion_pct"}
    )

    generation_stocks = _load_stock_panel(stock_path, None, "2021-12-31")
    generation_industry = _industry_responses(
        generation_stocks, "2020-07-28", "2021-12-23", [1, 3, 5]
    )
    generation_panel = _daily_diagnostics(generation_industry, states)
    generation_summary = _summarize(generation_panel, "generation_2020H2_2021")
    generation_passes = _generation_passes(generation_summary, spec)

    panels = [generation_panel.assign(period="generation_2020H2_2021")]
    summaries = [generation_summary]
    validation_opened = False
    validation_passes = False
    if generation_passes:
        validation_opened = True
        validation_stocks = _load_stock_panel(stock_path, "2021-12-01", "2023-12-29")
        validation_industry = _industry_responses(
            validation_stocks, "2022-01-04", "2023-12-21", [1, 3, 5]
        )
        validation_panel = _daily_diagnostics(validation_industry, states)
        validation_summary = _summarize(validation_panel, "fixed_validation_2022_2023")
        panels.append(validation_panel.assign(period="fixed_validation_2022_2023"))
        summaries.append(validation_summary)
        validation_passes = _validation_passes(validation_summary)

    output = pd.concat(panels, ignore_index=True)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12f")
    classification = (
        "DIRECTIONAL_BRIDGE_VALIDATED"
        if generation_passes and validation_passes
        else "DIRECTIONAL_BRIDGE_FAILED_VALIDATION"
        if generation_passes
        else "NO_GENERATION_DIRECTION"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "spec_sha256": sha256_file(SPEC_PATH),
        "panel_sha256": sha256_file(PANEL_PATH),
        "generation_passes": generation_passes,
        "validation_opened": validation_opened,
        "validation_passes": validation_passes,
        "strategy_authorized": generation_passes and validation_passes,
        "classification": classification,
        "summaries": summaries,
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "maximum_evaluation_outcome_date": "2023-12-29" if validation_opened else "2021-12-31",
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), sort_keys=True, indent=2) + "\n")
    _atomic_write(REPORT_PATH, _report(result))
    print(json.dumps(_clean(result), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
