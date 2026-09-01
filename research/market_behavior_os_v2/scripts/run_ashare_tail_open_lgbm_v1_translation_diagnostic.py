#!/usr/bin/env python3
"""Frozen-prediction translation diagnostic for Tail-to-Open LightGBM V1.

This program intentionally reads only the accepted 2018--2021 Stage-B OOF
prediction artifact and its embedded realized labels.  It never loads the
model panel, fits/scorers, Validation, or Final-OOS paths.
"""

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
RESULT_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_translation_diagnostic.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-TAIL-OPEN-LGBM-V1_translation_diagnostic.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/ashare_tail_open_lgbm_v1")
PREDICTION_PATH = EXTERNAL_ROOT / "stage_b_predictions.parquet"
EXPECTED_PREDICTION_SHA256 = "d99f0771bb104535607b3c489c252eb0a80c6489f7aa68edc33d01a9b9ce4c19"
DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
LEADING_MODEL = "moderately_richer"
RIDGE_MODEL = "ridge"
SIDE_COST = 0.002
TAILS = (0.20, 0.10, 0.05, 0.02, 0.01)
CONFIDENCE_STATISTICS = (
    "maximum_prediction",
    "mean_top10_prediction",
    "top10_minus_median_prediction",
    "mean_top1pct_prediction",
)


class TranslationDiagnosticError(RuntimeError):
    """Fail-closed frozen-prediction diagnostic error."""


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
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _load_inputs() -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame, dict[str, Any]]:
    if _sha256(PREDICTION_PATH) != EXPECTED_PREDICTION_SHA256:
        raise TranslationDiagnosticError("accepted Stage-B prediction hash changed")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    stage_b = json.loads(STAGE_B_PATH.read_text(encoding="utf-8"))
    if stage_b["classification"] != "ML_EXECUTION_FAILURE":
        raise TranslationDiagnosticError("Stage-B classification identity changed")
    if stage_b["modeling"]["development"]["selected_profile"] != LEADING_MODEL:
        raise TranslationDiagnosticError("development-leading model identity changed")
    if stage_b["modeling"]["prediction_sha256"] != EXPECTED_PREDICTION_SHA256:
        raise TranslationDiagnosticError("Stage-B result does not certify the prediction artifact")
    if stage_b["modeling"]["validation"] is not None or stage_b["boundaries"]["final_oos_opened"]:
        raise TranslationDiagnosticError("validation or Final OOS boundary is not sealed")
    if spec["label"]["name"] != "tail_to_first_legal_open_net_return" or SIDE_COST != 0.002:
        raise TranslationDiagnosticError("frozen label/cost contract changed")
    fields = [
        "trade_date", "exit_date", "symbol", "industry", "entry_executable", "label_valid",
        "label_net", "label_gross", "entry_vwap", "post_entry_tail_low", "score", "model", "fold",
    ]
    frame = pq.read_table(PREDICTION_PATH, columns=fields, use_threads=False).to_pandas()
    frame["trade_date"] = pd.to_datetime(frame.trade_date, errors="raise")
    frame["exit_date"] = pd.to_datetime(frame.exit_date, errors="raise")
    frame = frame.loc[frame.model.isin((LEADING_MODEL, RIDGE_MODEL))].copy()
    if frame.empty or set(frame.model.unique()) != {LEADING_MODEL, RIDGE_MODEL}:
        raise TranslationDiagnosticError("required frozen model predictions missing")
    years = set(frame.trade_date.dt.year.unique())
    if years != set(DEVELOPMENT_YEARS) or frame.trade_date.max().year > 2021:
        raise TranslationDiagnosticError(f"non-development prediction rows entered diagnostic: {years}")
    expected_folds = {2018: 0, 2019: 1, 2020: 2, 2021: 3}
    fold_check = frame.assign(year=frame.trade_date.dt.year).groupby("year").fold.unique().to_dict()
    if any(set(values) != {expected_folds[year]} for year, values in fold_check.items()):
        raise TranslationDiagnosticError("walk-forward fold identity changed")
    keys = ["trade_date", "symbol"]
    duplicate = frame.duplicated([*keys, "model"]).any()
    if duplicate:
        raise TranslationDiagnosticError("OOF prediction keys are not unique")
    paired = frame.pivot(index=keys, columns="model", values=["label_net", "label_gross", "label_valid", "entry_executable"])
    for field in ("label_net", "label_gross", "label_valid", "entry_executable"):
        left, right = paired[field][LEADING_MODEL], paired[field][RIDGE_MODEL]
        if field.startswith("label_") and field != "label_valid":
            left_values = left.to_numpy(dtype=float)
            right_values = right.to_numpy(dtype=float)
            same = np.array_equal(np.nan_to_num(left_values, nan=0.0), np.nan_to_num(right_values, nan=0.0)) and np.array_equal(np.isnan(left_values), np.isnan(right_values))
        else:
            same = left.equals(right)
        if not same:
            raise TranslationDiagnosticError(f"{field} differs across frozen models")
    identity = {
        "prediction_path": str(PREDICTION_PATH),
        "prediction_sha256": EXPECTED_PREDICTION_SHA256,
        "models": sorted(frame.model.unique().tolist()),
        "rows": int(len(frame)),
        "rows_by_model": {str(key): int(value) for key, value in frame.model.value_counts().items()},
        "dates": int(frame.trade_date.nunique()),
        "date_range": [str(frame.trade_date.min().date()), str(frame.trade_date.max().date())],
        "symbols": int(frame.symbol.nunique()),
        "years": sorted(int(year) for year in years),
        "label": spec["label"],
        "validation_rows_read": False,
        "final_oos_rows_read": False,
        "new_model_scoring_generated": False,
    }
    return spec, stage_b, frame, identity


def _daily_assignments(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    assigned: list[pd.DataFrame] = []
    confidence: list[dict[str, Any]] = []
    for trade_date, raw in frame.groupby("trade_date", sort=True):
        group = raw.sort_values(["score", "symbol"], ascending=[True, True]).copy()
        size = len(group)
        group["score_bucket"] = ((np.arange(size) * 20) // size + 1).astype(np.int8)
        descending = group.sort_values(["score", "symbol"], ascending=[False, True])
        rank_high = np.empty(size, dtype=np.int32)
        rank_high[descending.index.get_indexer(group.index)] = np.arange(1, size + 1)
        group["rank_high"] = rank_high
        top10 = descending.head(10)
        gross = np.where(top10.label_valid, top10.label_gross.fillna(0.0), 0.0)
        net = np.where(top10.label_valid, top10.label_net.fillna(0.0), 0.0)
        top1 = descending.head(max(1, int(math.ceil(size * 0.01))))
        confidence.append(
            {
                "trade_date": trade_date,
                "year": int(trade_date.year),
                "maximum_prediction": float(descending.score.iloc[0]),
                "mean_top10_prediction": float(top10.score.mean()),
                "top10_minus_median_prediction": float(top10.score.mean() - group.score.median()),
                "mean_top1pct_prediction": float(top1.score.mean()),
                "top10_gross_return": float(gross.sum() / 10.0),
                "top10_net_return": float(net.sum() / 10.0),
            }
        )
        assigned.append(group)
    return pd.concat(assigned, ignore_index=True), pd.DataFrame(confidence)


def _periods(frame: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    return [("pooled", frame), *[(str(year), frame.loc[frame.trade_date.dt.year.eq(year)]) for year in DEVELOPMENT_YEARS]]


def _recover_cost_coordinates(rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Recover exit/entry and cash/entry from the two frozen label coordinates."""
    gross = rows.label_gross.to_numpy(dtype=float)
    net = rows.label_net.to_numpy(dtype=float)
    total_proceeds = 1.0 + gross
    exit_ratio = (total_proceeds - (1.0 + net) * (1.0 + SIDE_COST)) / SIDE_COST
    cash_ratio = total_proceeds - exit_ratio
    return exit_ratio, cash_ratio


def _aggregate_selection(rows: pd.DataFrame, mask: pd.Series) -> dict[str, Any]:
    selected = rows.loc[mask].copy()
    executable = selected.loc[selected.label_valid].copy()
    if selected.empty:
        return {"observations": 0, "unique_dates": 0, "unique_securities": 0}
    universe = (
        rows.loc[rows.label_valid]
        .groupby("trade_date", sort=True)
        .label_net.mean()
        .rename("universe_net")
    )
    daily = executable.groupby("trade_date", sort=True).agg(gross=("label_gross", "mean"), net=("label_net", "mean"))
    daily = daily.join(universe, how="inner")
    result: dict[str, Any] = {
        "observations": int(len(selected)),
        "unique_dates": int(selected.trade_date.nunique()),
        "unique_securities": int(selected.symbol.nunique()),
        "executable_observations": int(len(executable)),
        "entry_coverage": float(len(executable) / len(selected)),
        "gross_executable_return": float(daily.gross.mean()) if len(daily) else None,
        "net_return": float(daily.net.mean()) if len(daily) else None,
        "eligible_universe_excess": float((daily.net - daily.universe_net).mean()) if len(daily) else None,
        "severe_loss10": None,
        "severe_loss10_status": "UNAVAILABLE_IN_FROZEN_OOF_PREDICTION_ARTIFACT",
    }
    if len(executable):
        exit_ratio, cash_ratio = _recover_cost_coordinates(executable)
        average_exit = float(np.mean(exit_ratio))
        average_cash = float(np.mean(cash_ratio))
        per_side = (average_exit + average_cash - 1.0) / (average_exit + 1.0)
        result["implied_max_round_trip_cost"] = float(2.0 * per_side)
    else:
        result["implied_max_round_trip_cost"] = None
    return result


def _shape(rows: pd.DataFrame) -> dict[str, Any]:
    outputs: dict[str, Any] = {"buckets": {}, "upper_tails": {}, "decomposition": {}}
    for period, period_rows in _periods(rows):
        buckets = {
            str(bucket): _aggregate_selection(period_rows, period_rows.score_bucket.eq(bucket))
            for bucket in range(1, 21)
        }
        tails = {
            f"top_{int(tail * 100)}pct": _aggregate_selection(
                period_rows,
                period_rows.rank_high.le(np.ceil(period_rows.groupby("trade_date").rank_high.transform("max") * tail)),
            )
            for tail in TAILS
        }
        median_mask = period_rows.score_bucket.isin((10, 11))
        bottom = _aggregate_selection(period_rows, period_rows.score_bucket.eq(1))
        median = _aggregate_selection(period_rows, median_mask)
        top = _aggregate_selection(period_rows, period_rows.score_bucket.eq(20))
        universe_net = (
            period_rows.loc[period_rows.label_valid].groupby("trade_date").label_net.mean().mean()
        )
        outputs["buckets"][period] = buckets
        outputs["upper_tails"][period] = tails
        outputs["decomposition"][period] = {
            "median_to_top": top.get("net_return") - median.get("net_return"),
            "median_to_bottom_deterioration": median.get("net_return") - bottom.get("net_return"),
            "top_minus_universe": top.get("net_return") - float(universe_net),
            "universe_minus_bottom": float(universe_net) - bottom.get("net_return"),
        }
    pooled = outputs["decomposition"]["pooled"]
    top_side, bottom_side = pooled["median_to_top"], pooled["median_to_bottom_deterioration"]
    if top_side is not None and bottom_side is not None and top_side > 0 and bottom_side > 0:
        classification = "BOTH_SIDES"
    elif top_side is not None and top_side > 0:
        classification = "POSITIVE_LONG_ALPHA_DOMINANT"
    elif bottom_side is not None and bottom_side > 0:
        classification = "NEGATIVE_AVOIDANCE_DOMINANT"
    else:
        classification = "WEAK_RELATIVE_ORDERING"
    outputs["descriptive_classification"] = classification
    return outputs


def _expanding_quintiles(confidence: pd.DataFrame, statistic: str) -> pd.Series:
    values = confidence[statistic].to_numpy(dtype=float)
    buckets = np.full(len(values), -1, dtype=np.int8)
    for index, value in enumerate(values):
        history = values[:index]
        if len(history) < 20:
            continue
        buckets[index] = min(5, int(math.floor(np.mean(history < value) * 5.0)) + 1)
    return pd.Series(buckets, index=confidence.index)


def _confidence_diagnostic(confidence: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for statistic in CONFIDENCE_STATISTICS:
        frame = confidence.copy()
        frame["quintile"] = _expanding_quintiles(frame, statistic)
        period_rows: dict[str, Any] = {}
        for period, rows in [("pooled", frame), *[(str(year), frame.loc[frame.year.eq(year)]) for year in DEVELOPMENT_YEARS]]:
            quintiles: dict[str, Any] = {}
            for quintile in range(1, 6):
                selected = rows.loc[rows.quintile.eq(quintile)]
                quintiles[str(quintile)] = {
                    "dates": int(len(selected)),
                    "mean_gross_return": float(selected.top10_gross_return.mean()) if len(selected) else None,
                    "mean_net_return": float(selected.top10_net_return.mean()) if len(selected) else None,
                }
            period_rows[period] = quintiles
        high_days = {str(year): int(((frame.year == year) & (frame.quintile == 5)).sum()) for year in DEVELOPMENT_YEARS}
        result[statistic] = {"quintiles": period_rows, "high_confidence_days_by_year": high_days}
    return result


def _opportunity_classification(confidence: dict[str, Any]) -> str:
    support = 0
    for statistic in CONFIDENCE_STATISTICS:
        yearly = confidence[statistic]["quintiles"]
        signs = [
            yearly[str(year)]["5"]["mean_net_return"] > yearly[str(year)]["1"]["mean_net_return"]
            for year in DEVELOPMENT_YEARS
            if yearly[str(year)]["5"]["mean_net_return"] is not None and yearly[str(year)]["1"]["mean_net_return"] is not None
        ]
        if sum(signs) >= 3:
            support += 1
    if support >= 3:
        return "STRONG_OPPORTUNITY_CONDITIONALITY"
    if support >= 1:
        return "POSSIBLE_OPPORTUNITY_CONDITIONALITY"
    return "NO_OPPORTUNITY_STRUCTURE"


def _stopping_classification(shape: dict[str, Any], confidence_classification: str) -> str:
    tails = shape["upper_tails"]
    top1 = tails["pooled"]["top_1pct"]
    top1_by_year = [tails[str(year)]["top_1pct"]["gross_executable_return"] for year in DEVELOPMENT_YEARS]
    stable_long = sum(value is not None and value >= 0.004 for value in top1_by_year) >= 3
    if stable_long:
        return "ML_SPARSE_LONG_HEADROOM"
    if confidence_classification == "STRONG_OPPORTUNITY_CONDITIONALITY":
        return "ML_OPPORTUNITY_CONDITIONALITY"
    if shape["descriptive_classification"] == "NEGATIVE_AVOIDANCE_DOMINANT":
        return "ML_BAD_STOCK_AVOIDANCE_SIGNAL"
    if shape["descriptive_classification"] == "BOTH_SIDES" and top1["gross_executable_return"] is not None and top1["gross_executable_return"] > 0:
        return "ML_MIXED_TRANSLATION_HEADROOM"
    return "ML_RELATIVE_RANKING_ONLY"


def _render(result: dict[str, Any]) -> str:
    leading = result["lightgbm"]
    tails = leading["shape"]["upper_tails"]["pooled"]
    lines = [
        "# A-share Tail-to-Open LightGBM V1 — Development-only translation diagnostic",
        "",
        f"Classification: `{result['stopping_classification']}`.",
        "",
        "Only the accepted 2018–2021 OOF prediction artifact was read. No model was fit or scored; 2022–2023 Validation and 2024–2026 Final OOS remain unread.",
        "",
        "## Fixed upper tails (pooled)",
        "",
        "| Tail | Gross | Net | Universe excess | Break-even round-trip cost | Coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in tails.items():
        lines.append(
            f"| {name} | {row['gross_executable_return']:.3%} | {row['net_return']:.3%} | "
            f"{row['eligible_universe_excess']:.3%} | {row['implied_max_round_trip_cost']:.3%} | {row['entry_coverage']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Pooled 20-bucket score curve",
            "",
            "| Bucket (low→high) | Observations | Gross | Net | Universe excess | Coverage |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for bucket, row in leading["shape"]["buckets"]["pooled"].items():
        lines.append(
            f"| {bucket} | {row['observations']:,} | {row['gross_executable_return']:.3%} | "
            f"{row['net_return']:.3%} | {row['eligible_universe_excess']:.3%} | {row['entry_coverage']:.2%} |"
        )
    lines.extend(
        [
            "",
            "## Chronological fixed tails",
            "",
            "| Year | Top 20% gross / net | Top 10% gross / net | Top 5% gross / net | Top 2% gross / net | Top 1% gross / net |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for year in DEVELOPMENT_YEARS:
        year_tails = leading["shape"]["upper_tails"][str(year)]
        rendered = []
        for percent in (20, 10, 5, 2, 1):
            row = year_tails[f"top_{percent}pct"]
            rendered.append(f"{row['gross_executable_return']:.3%} / {row['net_return']:.3%}")
        lines.append(f"| {year} | " + " | ".join(rendered) + " |")
    lines.extend(
        [
            "",
            f"Score-shape classification: `{leading['shape']['descriptive_classification']}`. "
            f"Opportunity classification: `{leading['opportunity_classification']}`.",
            "",
            "`severe_loss10` is explicitly unavailable: the accepted OOF artifact retains terminal labels but not the complete intraholding low path. It was not reconstructed from Validation-era raw paths.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> dict[str, Any]:
    _, _, all_predictions, identity = _load_inputs()
    output: dict[str, Any] = {"input_identity": identity, "models": {}}
    for model in (LEADING_MODEL, RIDGE_MODEL):
        frame = all_predictions.loc[all_predictions.model.eq(model)].copy()
        assigned, confidence = _daily_assignments(frame)
        shape = _shape(assigned)
        model_result: dict[str, Any] = {"shape": shape}
        if model == LEADING_MODEL:
            confidence_result = _confidence_diagnostic(confidence)
            model_result["confidence"] = confidence_result
            model_result["opportunity_classification"] = _opportunity_classification(confidence_result)
            model_result["no_trade_headroom"] = {
                "maximum_prediction_le_zero_fraction": float((confidence.maximum_prediction <= 0).mean()),
                "mean_top10_prediction_le_zero_fraction": float((confidence.mean_top10_prediction <= 0).mean()),
                "classification": model_result["opportunity_classification"],
            }
        output["models"][model] = model_result
    output["lightgbm"] = output["models"][LEADING_MODEL]
    output["ridge"] = output["models"][RIDGE_MODEL]
    output["stopping_classification"] = _stopping_classification(
        output["lightgbm"]["shape"], output["lightgbm"]["opportunity_classification"]
    )
    output["boundaries"] = {
        "ridge_refit": False,
        "lightgbm_refit": False,
        "new_model_scoring": False,
        "validation_opened": False,
        "final_oos_opened": False,
        "new_strategy_replay": False,
        "severe_loss10_reconstructed_from_raw_paths": False,
    }
    clean = _clean(output)
    _atomic_write(RESULT_PATH, json.dumps(clean, indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(clean))
    return clean


if __name__ == "__main__":
    answer = run()
    print(json.dumps({"classification": answer["stopping_classification"], "boundaries": answer["boundaries"]}, sort_keys=True))
