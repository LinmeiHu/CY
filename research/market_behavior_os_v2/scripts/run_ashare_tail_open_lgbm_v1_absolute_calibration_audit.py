#!/usr/bin/env python3
"""Development-only absolute-calibration audit of accepted Tail-to-Open OOF scores."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_stage_a_spec.json"
STAGE_B_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_stage_b_result.json"
STAGE_B_RUNNER = PROGRAM / "scripts/run_ashare_tail_open_lgbm_v1_stage_b.py"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_absolute_calibration_audit.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-TAIL-OPEN-LGBM-V1_absolute_calibration_audit.md"
PREDICTION_PATH = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1/stage_b_predictions.parquet")
EXPECTED_PREDICTION_SHA256 = "d99f0771bb104535607b3c489c252eb0a80c6489f7aa68edc33d01a9b9ce4c19"
LEADING_MODEL = "moderately_richer"
RIDGE_MODEL = "ridge"
YEARS = (2018, 2019, 2020, 2021)

ECONOMIC_BINS = (
    ("le_minus_100bp", -math.inf, -0.010, True, True),
    ("minus_100_to_minus_50bp", -0.010, -0.005, False, True),
    ("minus_50_to_minus_20bp", -0.005, -0.002, False, True),
    ("minus_20_to_0bp", -0.002, 0.0, False, True),
    ("0_to_plus_10bp", 0.0, 0.001, False, True),
    ("plus_10_to_plus_20bp", 0.001, 0.002, False, True),
    ("plus_20_to_plus_40bp", 0.002, 0.004, False, True),
    ("gt_plus_40bp", 0.004, math.inf, False, True),
)
THRESHOLDS = (("gt_0bp", 0.0), ("gt_10bp", 0.001), ("gt_20bp", 0.002), ("gt_40bp", 0.004))


class CalibrationAuditError(RuntimeError):
    """Fail-closed development OOF calibration error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


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
    return value


def _load() -> tuple[pd.DataFrame, dict[str, Any]]:
    if _sha256(PREDICTION_PATH) != EXPECTED_PREDICTION_SHA256:
        raise CalibrationAuditError("accepted OOF prediction hash changed")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    stage_b = json.loads(STAGE_B_PATH.read_text(encoding="utf-8"))
    source = STAGE_B_RUNNER.read_text(encoding="utf-8")
    required_source = (
        "model.fit(train[features], train.label_net)",
        'predicted["score"] = model.predict(predict[features])',
    )
    if any(item not in source for item in required_source):
        raise CalibrationAuditError("raw-label fit/prediction contract is not identifiable")
    if stage_b["modeling"]["prediction_sha256"] != EXPECTED_PREDICTION_SHA256:
        raise CalibrationAuditError("Stage-B result hash does not match prediction artifact")
    if stage_b["modeling"]["development"]["selected_profile"] != LEADING_MODEL:
        raise CalibrationAuditError("accepted leading profile changed")
    if stage_b["modeling"]["validation"] is not None or stage_b["boundaries"]["final_oos_opened"]:
        raise CalibrationAuditError("sealed Validation/OOS boundary changed")
    label = spec["label"]
    if label["name"] != "tail_to_first_legal_open_net_return" or label["buy_cost_per_side"] != 0.002 or label["sell_cost_per_side"] != 0.002:
        raise CalibrationAuditError("frozen net-label contract changed")
    fields = ["trade_date", "symbol", "industry", "entry_executable", "label_valid", "label_gross", "label_net", "score", "model", "fold"]
    frame = pq.read_table(PREDICTION_PATH, columns=fields, use_threads=False).to_pandas()
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    frame = frame.loc[frame.model.isin((LEADING_MODEL, RIDGE_MODEL))].copy()
    if set(frame.model.unique()) != {LEADING_MODEL, RIDGE_MODEL}:
        raise CalibrationAuditError("required OOF model rows missing")
    if set(frame.trade_date.dt.year.unique()) != set(YEARS) or frame.trade_date.max().year > 2021:
        raise CalibrationAuditError("Validation or OOS prediction rows entered audit")
    expected_fold = {2018: 0, 2019: 1, 2020: 2, 2021: 3}
    observed = frame.assign(year=frame.trade_date.dt.year).groupby("year").fold.unique().to_dict()
    if any(set(values) != {expected_fold[year]} for year, values in observed.items()):
        raise CalibrationAuditError("OOF fold chronology changed")
    identity = {
        "prediction_path": str(PREDICTION_PATH),
        "prediction_sha256": EXPECTED_PREDICTION_SHA256,
        "models": sorted(frame.model.unique().tolist()),
        "rows": int(len(frame)),
        "date_range": [str(frame.trade_date.min().date()), str(frame.trade_date.max().date())],
        "years": list(YEARS),
        "label": label,
        "unit_audit": {
            "prediction_is_rank": False,
            "prediction_is_standardized_or_z_scored": False,
            "un-inverted_target_transformation": False,
            "fit_target": "label_net",
            "prediction_assignment": "direct LightGBM prediction; no post-prediction transform",
            "consistent_walk_forward_units": True,
            "conclusion": "DIRECT_NET_EXECUTABLE_RETURN_UNITS",
        },
    }
    return frame, identity


def _periods(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    return [("pooled", frame), *[(str(year), frame.loc[frame.trade_date.dt.year.eq(year)]) for year in YEARS]]


def _return_summary(rows: pd.DataFrame) -> dict[str, Any]:
    executable = rows.loc[rows.label_valid]
    return {
        "observations": int(len(rows)),
        "unique_dates": int(rows.trade_date.nunique()),
        "unique_securities": int(rows.symbol.nunique()),
        "mean_predicted_net_return": float(rows.score.mean()) if len(rows) else None,
        "mean_realized_gross_return": float(executable.label_gross.mean()) if len(executable) else None,
        "mean_realized_net_return": float(executable.label_net.mean()) if len(executable) else None,
        "median_realized_net_return": float(executable.label_net.median()) if len(executable) else None,
        "realized_win_rate": float((executable.label_net > 0).mean()) if len(executable) else None,
        "entry_coverage": float(len(executable) / len(rows)) if len(rows) else None,
    }


def _distribution(frame: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for period, rows in _periods(frame):
        score = rows.score
        output[period] = {
            "mean": float(score.mean()), "median": float(score.median()), "standard_deviation": float(score.std(ddof=1)),
            "p1": float(score.quantile(0.01)), "p5": float(score.quantile(0.05)), "p25": float(score.quantile(0.25)),
            "p75": float(score.quantile(0.75)), "p95": float(score.quantile(0.95)), "p99": float(score.quantile(0.99)), "maximum": float(score.max()),
        }
    return output


def _bin_mask(score: pd.Series, lower: float, upper: float, lower_inclusive: bool) -> pd.Series:
    lower_check = score.ge(lower) if lower_inclusive else score.gt(lower)
    return lower_check & score.le(upper)


def _economic_bins(frame: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {}
    total = len(frame)
    for name, lower, upper, lower_inclusive, _ in ECONOMIC_BINS:
        rows = frame.loc[_bin_mask(frame.score, lower, upper, lower_inclusive)]
        summary = _return_summary(rows)
        summary["fraction_all_oof_observations"] = float(len(rows) / total)
        summary["sparse"] = bool(len(rows) < 100)
        summary["yearly_realized_net_return"] = {
            period: _return_summary(period_rows)["mean_realized_net_return"]
            for period, period_rows in _periods(rows) if period != "pooled"
        }
        output[name] = summary
    return output


def _threshold_summary(frame: pd.DataFrame, threshold: float) -> dict[str, Any]:
    rows = frame.loc[frame.score.gt(threshold)]
    result = _return_summary(rows)
    total_dates = int(frame.trade_date.nunique())
    active_dates = int(rows.trade_date.nunique())
    executable = rows.loc[rows.label_valid]
    security_share = executable.symbol.value_counts(normalize=True) if len(executable) else pd.Series(dtype=float)
    industry_share = executable.industry.value_counts(normalize=True) if len(executable) else pd.Series(dtype=float)
    result.update(
        {
            "active_dates": active_dates,
            "observations_per_active_day": float(len(rows) / active_dates) if active_dates else None,
            "fraction_all_dates_active": float(active_dates / total_dates),
            "yearly_realized_net_return": {
                period: _return_summary(period_rows.loc[period_rows.score.gt(threshold)])["mean_realized_net_return"]
                for period, period_rows in _periods(frame) if period != "pooled"
            },
            "concentration": {
                "max_security_share": float(security_share.iloc[0]) if len(security_share) else None,
                "max_industry_share": float(industry_share.iloc[0]) if len(industry_share) else None,
                "security_hhi": float(np.square(security_share).sum()) if len(security_share) else None,
                "industry_hhi": float(np.square(industry_share).sum()) if len(industry_share) else None,
            },
        }
    )
    return result


def _daily_counts(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    daily = frame.groupby("trade_date", sort=True).agg(maximum_prediction=("score", "max"))
    for name, threshold in THRESHOLDS:
        selected = frame.loc[frame.score.gt(threshold)]
        counts = selected.groupby("trade_date").score.agg(["count", "mean"])
        daily[f"count_{name}"] = counts["count"].reindex(daily.index, fill_value=0).astype(int)
        daily[f"mean_{name}"] = counts["mean"].reindex(daily.index)
    zero_counts = daily["count_gt_0bp"]
    categories = {
        "zero": zero_counts.eq(0), "one": zero_counts.eq(1), "two_to_three": zero_counts.between(2, 3),
        "four_to_ten": zero_counts.between(4, 10), "greater_than_ten": zero_counts.gt(10),
    }
    output = {
        "count_distribution": {
            name: {"mean": float(daily[f"count_{name}"].mean()), "median": float(daily[f"count_{name}"].median()), "p95": float(daily[f"count_{name}"].quantile(0.95)), "maximum": int(daily[f"count_{name}"].max())}
            for name, _ in THRESHOLDS
        },
        "canonical_gt_0bp_day_categories": {name: int(mask.sum()) for name, mask in categories.items()},
    }
    return daily, output


def _count_economics(frame: pd.DataFrame, daily: pd.DataFrame) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    positive = frame.loc[frame.score.gt(0)].copy()
    for trade_date, group in positive.groupby("trade_date", sort=True):
        count = len(group)
        category = "one" if count == 1 else "two_to_three" if count <= 3 else "four_to_ten" if count <= 10 else "greater_than_ten"
        ranked = group.sort_values(["score", "symbol"], ascending=[False, True])
        result: dict[str, Any] = {"trade_date": trade_date, "category": category, "pool_observations": count}
        result["pool_net"] = ranked.loc[ranked.label_valid, "label_net"].mean()
        for top_n in (1, 3, 10):
            selected = ranked.head(top_n) if len(ranked) >= top_n else pd.DataFrame()
            valid = selected.loc[selected.label_valid] if len(selected) else selected
            result[f"top{top_n}_net"] = valid.label_net.mean() if len(valid) == top_n else np.nan
        rows.append(result)
    detail = pd.DataFrame(rows)
    output: dict[str, Any] = {}
    for category in ("one", "two_to_three", "four_to_ten", "greater_than_ten"):
        subset = detail.loc[detail.category.eq(category)]
        output[category] = {
            "dates": int(len(subset)), "observations": int(subset.pool_observations.sum()) if len(subset) else 0,
            "average_predicted_positive_pool_net_return": float(subset.pool_net.mean()) if len(subset) else None,
            "highest_prediction_net_return": float(subset.top1_net.mean()) if len(subset) else None,
            "highest_three_net_return": float(subset.top3_net.mean()) if len(subset) else None,
            "highest_ten_net_return": float(subset.top10_net.mean()) if len(subset) else None,
        }
    return output


def _ols(rows: pd.DataFrame) -> dict[str, Any]:
    sample = rows.loc[rows.label_valid, ["score", "label_net"]].dropna()
    x = sample.score.to_numpy(dtype=float)
    y = sample.label_net.to_numpy(dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = intercept + slope * x
    residual = float(np.square(y - fitted).sum())
    total = float(np.square(y - y.mean()).sum())
    return {"observations": int(len(sample)), "intercept": float(intercept), "slope": float(slope), "r_squared": float(1.0 - residual / total) if total else None}


def _calibration(frame: pd.DataFrame) -> dict[str, Any]:
    sample = frame.loc[frame.label_valid].copy().sort_values(["score", "symbol", "trade_date"])
    sample["decile"] = ((np.arange(len(sample)) * 10) // len(sample) + 1).astype(int)
    return {
        "pooled": _ols(frame),
        "yearly": {str(year): _ols(frame.loc[frame.trade_date.dt.year.eq(year)]) for year in YEARS},
        "prediction_deciles": {
            str(decile): {"mean_predicted_net_return": float(rows.score.mean()), "mean_realized_net_return": float(rows.label_net.mean()), "observations": int(len(rows))}
            for decile, rows in sample.groupby("decile", sort=True)
        },
    }


def _relative_top_one_percent(frame: pd.DataFrame) -> dict[str, Any]:
    selected: list[pd.DataFrame] = []
    for _, group in frame.groupby("trade_date", sort=True):
        selected.append(group.sort_values(["score", "symbol"], ascending=[False, True]).head(max(1, int(math.ceil(len(group) * 0.01)))))
    rows = pd.concat(selected, ignore_index=True)
    result = _return_summary(rows)
    result["yearly_realized_net_return"] = {str(year): _return_summary(rows.loc[rows.trade_date.dt.year.eq(year)])["mean_realized_net_return"] for year in YEARS}
    result["active_dates"] = int(rows.trade_date.nunique())
    return result


def _classify(lightgbm: dict[str, Any]) -> str:
    zero = lightgbm["canonical_zero_threshold"]
    yearly = zero["yearly_realized_net_return"]
    values = [yearly[str(year)] for year in YEARS]
    if zero["mean_realized_net_return"] is None:
        return "ABSOLUTE_SCORE_NOT_CALIBRATED"
    if zero["mean_realized_net_return"] > 0 and sum(value is not None and value > 0 for value in values) >= 3:
        return "ABSOLUTE_SPARSE_OPPORTUNITY_PROMISING" if zero["fraction_all_dates_active"] < 0.25 else "ABSOLUTE_POSITIVE_POOL_PROMISING"
    if zero["mean_realized_net_return"] > 0:
        return "ABSOLUTE_POSITIVE_POOL_WEAK"
    if lightgbm["calibration_regression"]["pooled"]["slope"] > 0:
        return "ABSOLUTE_SCORE_RANKING_ONLY"
    return "ABSOLUTE_SCORE_NOT_CALIBRATED"


def _render(result: dict[str, Any]) -> str:
    lightgbm = result["lightgbm"]
    zero = lightgbm["canonical_zero_threshold"]
    lines = [
        "# A-share Tail-to-Open LightGBM V1 — Absolute-prediction calibration audit",
        "",
        f"Classification: `{result['classification']}`.",
        "",
        "Only accepted 2018–2021 OOF predictions and embedded realized labels were read. No refit, rescore, Validation, Final OOS, threshold search, or strategy replay occurred.",
        "",
        "## Canonical predicted-net > 0 condition",
        "",
        "| Period | Observations | Active days | Stocks / active day | Gross | Net | Win rate | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for period, rows in [("pooled", zero), *[(str(year), lightgbm["zero_by_year"][str(year)]) for year in YEARS]]:
        lines.append(f"| {period} | {rows['observations']:,} | {rows['active_dates']} | {rows['observations_per_active_day']:.2f} | {rows['mean_realized_gross_return']:.3%} | {rows['mean_realized_net_return']:.3%} | {rows['realized_win_rate']:.2%} | {rows['entry_coverage']:.2%} |")
    lines.extend(["", "## Fixed threshold diagnostics (pooled)", "", "| Threshold | Observations | Active days | Gross | Net |", "|---|---:|---:|---:|---:|"])
    for name, rows in lightgbm["fixed_thresholds"].items():
        lines.append(f"| {name} | {rows['observations']:,} | {rows['active_dates']} | {rows['mean_realized_gross_return']:.3%} | {rows['mean_realized_net_return']:.3%} |")
    lines.extend(["", "## Calibration regression", "", f"Pooled intercept `{lightgbm['calibration_regression']['pooled']['intercept']:.4%}`, slope `{lightgbm['calibration_regression']['pooled']['slope']:.3f}`, R² `{lightgbm['calibration_regression']['pooled']['r_squared']:.4f}`.", ""])
    return "\n".join(lines)


def run() -> dict[str, Any]:
    all_predictions, identity = _load()
    light = all_predictions.loc[all_predictions.model.eq(LEADING_MODEL)].copy()
    ridge = all_predictions.loc[all_predictions.model.eq(RIDGE_MODEL)].copy()
    zero_by_year = {str(year): _threshold_summary(light.loc[light.trade_date.dt.year.eq(year)], 0.0) for year in YEARS}
    daily, count_distribution = _daily_counts(light)
    light_result = {
        "prediction_distribution": _distribution(light),
        "absolute_economic_bins": _economic_bins(light),
        "canonical_zero_threshold": _threshold_summary(light, 0.0),
        "zero_by_year": zero_by_year,
        "fixed_thresholds": {name: _threshold_summary(light, threshold) for name, threshold in THRESHOLDS if threshold > 0},
        "daily_opportunity_count": count_distribution,
        "opportunity_count_economics": _count_economics(light, daily),
        "calibration_regression": _calibration(light),
        "relative_daily_top_1pct": _relative_top_one_percent(light),
    }
    ridge_zero = _threshold_summary(ridge, 0.0)
    ridge_zero["yearly_realized_net_return"] = {str(year): _threshold_summary(ridge.loc[ridge.trade_date.dt.year.eq(year)], 0.0)["mean_realized_net_return"] for year in YEARS}
    result = {
        "input_identity": identity,
        "lightgbm": light_result,
        "ridge_zero_threshold": ridge_zero,
        "classification": _classify(light_result),
        "boundaries": {"ridge_refit": False, "lightgbm_refit": False, "new_model_scoring": False, "validation_opened": False, "final_oos_opened": False, "threshold_optimization": False, "new_strategy_replay": False},
    }
    clean = _clean(result)
    _atomic_write(RESULT_PATH, json.dumps(clean, indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(clean))
    return clean


if __name__ == "__main__":
    outcome = run()
    print(json.dumps({"classification": outcome["classification"], "boundaries": outcome["boundaries"]}, sort_keys=True))
