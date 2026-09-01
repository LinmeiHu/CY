#!/usr/bin/env python3
"""Run frozen post-hoc anatomy of the V1.1 adverse recovery surface."""

from __future__ import annotations

import hashlib
import json
import math
import os
import warnings
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-POST-SHOCK-ADVERSE-RECOVERY-ANATOMY-V1_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-POST-SHOCK-ADVERSE-RECOVERY-ANATOMY-V1_result.json"
BUCKET_PATH = PROGRAM / "artifacts/ASHARE-POST-SHOCK-ADVERSE-RECOVERY-ANATOMY-V1_bucket_table.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-POST-SHOCK-ADVERSE-RECOVERY-ANATOMY-V1_report.md"
EXPECTED_SPEC_SHA256 = "1d6e8bf0bd7ef9d2a16fede7c8c22db592301822ad87e9f88b8e988aa8288197"
HORIZONS = (1, 3, 5, 10, 20)
PRIMARY_HORIZONS = (5, 10, 20)
BUCKETS = (1, 2, 3, 4, 5)
TARGET = "ABS_m06_REL_m04_W3"
SEVERE = -0.10


class AdverseRecoveryAnatomyError(RuntimeError):
    """Fail-closed error for the frozen anatomy."""


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
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise AdverseRecoveryAnatomyError("frozen anatomy specification changed")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_NEW_POST_HOC_ANATOMY_OUTCOME_AGGREGATION":
        raise AdverseRecoveryAnatomyError("invalid anatomy freeze status")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise AdverseRecoveryAnatomyError(f"bound input changed: {role}")
    if spec["sample"]["parameter_cells"] != 18:
        raise AdverseRecoveryAnatomyError("anatomy grid changed")
    return spec


def validate_outcome_boundary(panel: pd.DataFrame) -> date:
    if panel.empty or pd.to_datetime(panel.signal_date).dt.year.max() > 2023:
        raise AdverseRecoveryAnatomyError("empty or post-2023 signal panel")
    dates = pd.concat(
        [pd.to_datetime(panel[f"outcome_date_h{horizon}"]) for horizon in HORIZONS]
    ).dropna()
    if dates.empty:
        raise AdverseRecoveryAnatomyError("no complete outcome dates")
    maximum = dates.max().date()
    if maximum > pd.Timestamp("2023-12-31").date():
        raise AdverseRecoveryAnatomyError("post-2023 outcome detected")
    return maximum


def _read_panel(spec: dict[str, Any]) -> pd.DataFrame:
    columns = [
        "event_id",
        "cell_id",
        "window",
        "signal_date",
        "symbol",
        "industry",
        "sample_type",
        "recovery_fraction",
        "further_drawdown_ratio",
        "recovery_quintile",
        "absolute_shock_magnitude",
        "relative_shock_magnitude",
        "pre_shock_trend20",
        "pre_shock_volatility20",
        "shock_avg_amount20",
        "entry_status",
        "mae_h20",
    ]
    for horizon in HORIZONS:
        columns.extend(
            [
                f"net_return_h{horizon}",
                f"industry_relative_h{horizon}",
                f"outcome_date_h{horizon}",
            ]
        )
    path = _resolve(spec["inputs"]["evaluation_panel"]["path"])
    panel = pd.read_parquet(path, columns=columns)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["year"] = panel.signal_date.dt.year
    return panel


def _validate_panel(panel: pd.DataFrame, expected_cells: list[str]) -> date:
    maximum = validate_outcome_boundary(panel)
    shock = panel.loc[panel.sample_type.eq("SHOCK")]
    if len(shock) != 709_981:
        raise AdverseRecoveryAnatomyError(f"shock event count changed: {len(shock)}")
    if sorted(shock.cell_id.unique()) != sorted(expected_cells):
        raise AdverseRecoveryAnatomyError("exact V1.1 cells changed")
    if set(shock.recovery_quintile.dropna().astype(int).unique()) != set(BUCKETS):
        raise AdverseRecoveryAnatomyError("Q1-Q5 mapping changed")
    if shock.duplicated("event_id").any():
        raise AdverseRecoveryAnatomyError("duplicate shock event identity")
    return maximum


def bucket_metrics(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    absolute_column = f"net_return_h{horizon}"
    relative_column = f"industry_relative_h{horizon}"
    complete = group.dropna(subset=[absolute_column, relative_column])
    absolute = complete[absolute_column]
    relative = complete[relative_column]
    return {
        "n": len(complete),
        "absolute_mean": absolute.mean(),
        "absolute_median": absolute.median(),
        "absolute_positive_rate": absolute.gt(0).mean(),
        "industry_relative_mean": relative.mean(),
        "industry_relative_median": relative.median(),
        "severe_loss_incidence": (complete.mae_h20.le(SEVERE).mean() if horizon == 20 else np.nan),
    }


def baseline_decomposition(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    absolute_column = f"net_return_h{horizon}"
    relative_column = f"industry_relative_h{horizon}"
    complete = group.dropna(subset=[absolute_column, relative_column])
    q1 = complete.loc[complete.recovery_quintile.eq(1)]
    q5 = complete.loc[complete.recovery_quintile.eq(5)]

    def coordinate(column: str) -> dict[str, Any]:
        event_mean = complete[column].mean()
        q1_mean = q1[column].mean()
        q5_mean = q5[column].mean()
        spread = q1_mean - q5_mean
        q1_strength = q1_mean - event_mean
        q5_delta = q5_mean - event_mean
        q1_share = max(q1_strength, 0.0) / spread if spread > 0 else np.nan
        return {
            "event_mean": event_mean,
            "q1_mean": q1_mean,
            "q5_mean": q5_mean,
            "q1_minus_event": q1_strength,
            "q5_minus_event": q5_delta,
            "q1_minus_q5": spread,
            "q1_strength_contribution_share": q1_share,
            "q5_weakness_contribution_share": 1.0 - q1_share if spread > 0 else np.nan,
        }

    return {
        "n": len(complete),
        "absolute": coordinate(absolute_column),
        "industry_relative": coordinate(relative_column),
        "event_severe_loss_incidence_h20": (
            complete.mae_h20.le(SEVERE).mean() if horizon == 20 else np.nan
        ),
        "q1_severe_loss_incidence_h20": (q1.mae_h20.le(SEVERE).mean() if horizon == 20 else np.nan),
    }


def monotonicity(bucket_rows: pd.DataFrame) -> dict[str, Any]:
    ordered = bucket_rows.sort_values("bucket")

    def coordinate(column: str) -> dict[str, Any]:
        values = ordered[column].to_numpy(dtype=float)
        adjacent = int(np.sum(values[:-1] > values[1:]))
        rho = pd.Series(BUCKETS, dtype=float).corr(pd.Series(values), method="spearman")
        return {
            "adjacent_favorable_steps": adjacent,
            "bucket_spearman": rho,
            "broadly_monotonic": bool(adjacent >= 3 and rho <= -0.70),
        }

    absolute = coordinate("absolute_mean")
    relative = coordinate("industry_relative_mean")
    return {
        "absolute": absolute,
        "industry_relative": relative,
        "both_coordinates_broadly_monotonic": bool(
            absolute["broadly_monotonic"] and relative["broadly_monotonic"]
        ),
    }


def _bucket_table(shock: pd.DataFrame, cells: list[str]) -> pd.DataFrame:
    rows = []
    scopes: list[tuple[str, str, pd.Series, tuple[int, ...]]] = [
        ("FULL", "2018_2023", pd.Series(True, index=shock.index), BUCKETS),
        ("BLOCK", "EARLY_2018_2021", shock.year.le(2021), (1,)),
        ("BLOCK", "LATE_2022_2023", shock.year.ge(2022), (1,)),
    ]
    scopes.extend(("YEAR", str(year), shock.year.eq(year), (1,)) for year in range(2018, 2024))
    for scope, period, mask, buckets in scopes:
        sample = shock.loc[mask]
        for cell in cells:
            cell_sample = sample.loc[sample.cell_id.eq(cell)]
            for horizon in HORIZONS:
                for bucket in buckets:
                    metrics = bucket_metrics(
                        cell_sample.loc[cell_sample.recovery_quintile.eq(bucket)], horizon
                    )
                    rows.append(
                        {
                            "scope": scope,
                            "period": period,
                            "cell_id": cell,
                            "horizon": horizon,
                            "bucket": bucket,
                            **metrics,
                        }
                    )
    return pd.DataFrame(rows)


def _full_anatomy(
    shock: pd.DataFrame, bucket_table: pd.DataFrame, cells: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    full = bucket_table.loc[bucket_table.scope.eq("FULL")]
    baseline_rows = []
    monotonic_rows = []
    for cell in cells:
        sample = shock.loc[shock.cell_id.eq(cell)]
        for horizon in HORIZONS:
            baseline_rows.append(
                {
                    "cell_id": cell,
                    "horizon": horizon,
                    **baseline_decomposition(sample, horizon),
                }
            )
            rows = full.loc[full.cell_id.eq(cell) & full.horizon.eq(horizon)]
            monotonic_rows.append({"cell_id": cell, "horizon": horizon, **monotonicity(rows)})
    return pd.DataFrame(baseline_rows), pd.DataFrame(monotonic_rows)


def _continuous_diagnostics(shock: pd.DataFrame, cells: list[str]) -> pd.DataFrame:
    rows = []
    scores = ("recovery_fraction", "further_drawdown_ratio")
    for cell in cells:
        sample = shock.loc[shock.cell_id.eq(cell)].copy()
        dates = sample.signal_date
        columns = list(scores)
        for horizon in HORIZONS:
            columns.extend([f"net_return_h{horizon}", f"industry_relative_h{horizon}"])
        ranked = sample[columns].groupby(dates).rank(method="average")
        for score in scores:
            for horizon in HORIZONS:
                for coordinate, outcome in (
                    ("absolute", f"net_return_h{horizon}"),
                    ("industry_relative", f"industry_relative_h{horizon}"),
                ):
                    valid = sample[score].notna() & sample[outcome].notna()
                    counts = valid.groupby(dates).sum()
                    with warnings.catch_warnings():
                        warnings.filterwarnings(
                            "ignore", message="invalid value encountered in divide"
                        )
                        correlation = (
                            ranked[score]
                            .where(valid)
                            .groupby(dates)
                            .corr(ranked[outcome].where(valid))
                        )
                    accepted = correlation.loc[counts.ge(5)].dropna()
                    rows.append(
                        {
                            "cell_id": cell,
                            "score": score,
                            "horizon": horizon,
                            "coordinate": coordinate,
                            "dates": len(accepted),
                            "mean_same_date_spearman": accepted.mean(),
                            "median_same_date_spearman": accepted.median(),
                        }
                    )
    return pd.DataFrame(rows)


def _family_summary(
    bucket_table: pd.DataFrame,
    baseline: pd.DataFrame,
    monotonic: pd.DataFrame,
) -> dict[str, Any]:
    full = bucket_table.loc[bucket_table.scope.eq("FULL") & bucket_table.bucket.eq(1)]
    output = {}
    for horizon in HORIZONS:
        q1 = full.loc[full.horizon.eq(horizon)]
        base = baseline.loc[baseline.horizon.eq(horizon)]
        mono = monotonic.loc[monotonic.horizon.eq(horizon)]
        output[f"h{horizon}"] = {
            "q1_absolute_mean_equal_cell": q1.absolute_mean.mean(),
            "q1_industry_relative_mean_equal_cell": q1.industry_relative_mean.mean(),
            "q1_absolute_median_equal_cell": q1.absolute_median.mean(),
            "q1_positive_rate_equal_cell": q1.absolute_positive_rate.mean(),
            "q1_positive_absolute_cells": int(q1.absolute_mean.gt(0).sum()),
            "q1_positive_industry_relative_cells": int(q1.industry_relative_mean.gt(0).sum()),
            "q1_both_positive_cells": int(
                (q1.absolute_mean.gt(0) & q1.industry_relative_mean.gt(0)).sum()
            ),
            "q1_positive_absolute_median_cells": int(q1.absolute_median.gt(0).sum()),
            "both_coordinate_monotonic_cells": int(mono.both_coordinates_broadly_monotonic.sum()),
            "q1_minus_event_absolute_equal_cell": float(
                np.mean([row["absolute"]["q1_minus_event"] for row in base.to_dict("records")])
            ),
            "q5_minus_event_absolute_equal_cell": float(
                np.mean([row["absolute"]["q5_minus_event"] for row in base.to_dict("records")])
            ),
            "q1_minus_event_industry_relative_equal_cell": float(
                np.mean(
                    [row["industry_relative"]["q1_minus_event"] for row in base.to_dict("records")]
                )
            ),
            "q5_minus_event_industry_relative_equal_cell": float(
                np.mean(
                    [row["industry_relative"]["q5_minus_event"] for row in base.to_dict("records")]
                )
            ),
            "q5_below_event_both_coordinates_cells": int(
                sum(
                    row["absolute"]["q5_minus_event"] < 0
                    and row["industry_relative"]["q5_minus_event"] < 0
                    for row in base.to_dict("records")
                )
            ),
            "q1_strength_contribution_share_equal_cell": float(
                np.nanmean(
                    [
                        row["absolute"]["q1_strength_contribution_share"]
                        for row in base.to_dict("records")
                    ]
                )
            ),
        }
    return output


def _chronology(bucket_table: pd.DataFrame) -> dict[str, Any]:
    q1 = bucket_table.loc[bucket_table.bucket.eq(1)]
    output: dict[str, Any] = {"blocks": {}, "years": {}}
    for period in ("EARLY_2018_2021", "LATE_2022_2023"):
        period_rows = q1.loc[q1.scope.eq("BLOCK") & q1.period.eq(period)]
        output["blocks"][period] = {
            f"h{horizon}": {
                "absolute_mean_equal_cell": group.absolute_mean.mean(),
                "industry_relative_mean_equal_cell": group.industry_relative_mean.mean(),
                "positive_absolute_cells": int(group.absolute_mean.gt(0).sum()),
                "positive_industry_relative_cells": int(group.industry_relative_mean.gt(0).sum()),
            }
            for horizon in HORIZONS
            for group in [period_rows.loc[period_rows.horizon.eq(horizon)]]
        }
    for year in range(2018, 2024):
        year_rows = q1.loc[q1.scope.eq("YEAR") & q1.period.eq(str(year))]
        output["years"][str(year)] = {
            f"h{horizon}": {
                "absolute_mean_equal_cell": group.absolute_mean.mean(),
                "industry_relative_mean_equal_cell": group.industry_relative_mean.mean(),
                "positive_absolute_cells": int(group.absolute_mean.gt(0).sum()),
                "positive_industry_relative_cells": int(group.industry_relative_mean.gt(0).sum()),
            }
            for horizon in HORIZONS
            for group in [year_rows.loc[year_rows.horizon.eq(horizon)]]
        }
    return output


def _q1_control_metrics(group: pd.DataFrame) -> dict[str, Any]:
    q1 = group.loc[group.recovery_quintile.eq(1)]
    output = {"observations": len(q1), "horizons": {}}
    for horizon in PRIMARY_HORIZONS:
        metrics = bucket_metrics(q1, horizon)
        output["horizons"][f"h{horizon}"] = metrics
    output["pass"] = bool(
        len(q1) >= 100
        and all(
            output["horizons"][f"h{horizon}"]["absolute_mean"] > 0
            and output["horizons"][f"h{horizon}"]["industry_relative_mean"] > 0
            for horizon in PRIMARY_HORIZONS
        )
    )
    return output


def _controls(panel: pd.DataFrame) -> dict[str, Any]:
    target = panel.loc[panel.cell_id.eq(TARGET) & panel.sample_type.eq("SHOCK")].copy()
    target["absolute_bin"] = np.select(
        [target.absolute_shock_magnitude.lt(0.08), target.absolute_shock_magnitude.lt(0.10)],
        ["threshold_to_8pct", "8_to_10pct"],
        default="at_least_10pct",
    )
    target["relative_bin"] = np.select(
        [target.relative_shock_magnitude.lt(0.06), target.relative_shock_magnitude.lt(0.08)],
        ["threshold_to_6pct", "6_to_8pct"],
        default="at_least_8pct",
    )
    severity = []
    for (absolute_bin, relative_bin), group in target.groupby(
        ["absolute_bin", "relative_bin"], sort=True
    ):
        severity.append(
            {
                "absolute_bin": absolute_bin,
                "relative_bin": relative_bin,
                **_q1_control_metrics(group),
            }
        )
    coarse = {}
    definitions = {
        "PRE_SHOCK_TREND": "pre_shock_trend20",
        "REALIZED_VOLATILITY": "pre_shock_volatility20",
        "LIQUIDITY": "shock_avg_amount20",
    }
    for name, column in definitions.items():
        ranks = target.groupby("signal_date", sort=False)[column].rank(method="average", pct=True)
        terciles = np.ceil(ranks * 3).clip(1, 3).astype("Int64")
        coarse[name] = [
            {"tercile": tercile, **_q1_control_metrics(target.loc[terciles.eq(tercile)])}
            for tercile in range(1, 4)
        ]
    generic = {}
    for window in (2, 3, 5):
        generic[f"W{window}"] = {
            "shock": _q1_control_metrics(
                panel.loc[
                    panel.cell_id.eq(f"ABS_m06_REL_m04_W{window}") & panel.sample_type.eq("SHOCK")
                ]
            ),
            "generic": _q1_control_metrics(
                panel.loc[panel.cell_id.eq(f"GENERIC_W{window}") & panel.sample_type.eq("NONSHOCK")]
            ),
        }
    return {"target": TARGET, "severity": severity, "coarse": coarse, "generic": generic}


def classify(
    family: dict[str, Any], chronology: dict[str, Any], baseline: pd.DataFrame
) -> tuple[str, dict[str, Any]]:
    early = chronology["blocks"]["EARLY_2018_2021"]
    late = chronology["blocks"]["LATE_2022_2023"]
    sign_reversal_horizons = sum(
        (
            np.sign(early[f"h{horizon}"]["absolute_mean_equal_cell"])
            != np.sign(late[f"h{horizon}"]["absolute_mean_equal_cell"])
        )
        or (
            np.sign(early[f"h{horizon}"]["industry_relative_mean_equal_cell"])
            != np.sign(late[f"h{horizon}"]["industry_relative_mean_equal_cell"])
        )
        for horizon in PRIMARY_HORIZONS
    )
    every_primary = [family[f"h{horizon}"] for horizon in PRIMARY_HORIZONS]
    blocks_positive = all(
        block[f"h{horizon}"]["absolute_mean_equal_cell"] > 0
        and block[f"h{horizon}"]["industry_relative_mean_equal_cell"] > 0
        for block in (early, late)
        for horizon in PRIMARY_HORIZONS
    )
    relative_blocks_positive = all(
        block[f"h{horizon}"]["industry_relative_mean_equal_cell"] > 0
        for block in (early, late)
        for horizon in PRIMARY_HORIZONS
    )
    contribution = float(
        np.mean([item["q1_strength_contribution_share_equal_cell"] for item in every_primary])
    )
    candidate = bool(
        all(
            item["q1_positive_absolute_cells"] >= 12
            and item["q1_positive_industry_relative_cells"] >= 12
            and item["q1_both_positive_cells"] >= 12
            and item["q1_positive_absolute_median_cells"] >= 12
            and item["both_coordinate_monotonic_cells"] >= 12
            for item in every_primary
        )
        and blocks_positive
        and contribution >= 0.25
    )
    relative_only = bool(
        all(item["q1_positive_industry_relative_cells"] >= 12 for item in every_primary)
        and relative_blocks_positive
        and not candidate
    )
    avoidance = bool(
        all(item["q1_both_positive_cells"] < 12 for item in every_primary)
        and all(item["q5_below_event_both_coordinates_cells"] >= 12 for item in every_primary)
        and contribution < 0.25
    )
    h20 = baseline.loc[baseline.horizon.eq(20)]
    defensive_cells = sum(
        row["q1_severe_loss_incidence_h20"] < row["event_severe_loss_incidence_h20"]
        for row in h20.to_dict("records")
    )
    defensive = bool(
        not all(item["q1_absolute_mean_equal_cell"] > 0 for item in every_primary)
        and defensive_cells >= 12
    )
    nonmonotonic_horizons = sum(
        item["both_coordinate_monotonic_cells"] < 9 for item in every_primary
    )
    if sign_reversal_horizons >= 2:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif candidate:
        classification = "POST_HOC_LONG_REVERSAL_CANDIDATE"
    elif relative_only:
        classification = "RELATIVE_REVERSAL_ONLY"
    elif avoidance:
        classification = "STRONG_RECOVERY_AVOIDANCE_ONLY"
    elif defensive:
        classification = "DEFENSIVE_LESS_BAD_ONLY"
    elif nonmonotonic_horizons >= 2:
        classification = "NONMONOTONIC_BUCKET_EFFECT"
    else:
        classification = "NO_LONG_REVERSAL_ALPHA"
    diagnostics = {
        "sign_reversal_primary_horizons": int(sign_reversal_horizons),
        "blocks_positive_all_primary": blocks_positive,
        "relative_blocks_positive_all_primary": relative_blocks_positive,
        "mean_q1_strength_contribution_share_primary": contribution,
        "defensive_h20_cells": int(defensive_cells),
        "nonmonotonic_primary_horizons": int(nonmonotonic_horizons),
        "candidate_gate": candidate,
        "relative_only_gate": relative_only,
        "avoidance_gate": avoidance,
        "defensive_gate": defensive,
    }
    return classification, diagnostics


def _fmt(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:.3%}"


def _report(result: dict[str, Any], bucket_table: pd.DataFrame) -> str:
    family = result["family_summary"]
    lines = [
        "# A-share Post-Shock Adverse-Recovery Anatomy V1",
        "",
        "## Executive conclusion",
        "",
        f"Final classification: `{result['final_classification']}`.",
        "",
        result["economic_interpretation"],
        "",
        "## Why this experiment exists",
        "",
        "V1.1 unexpectedly found negative recovery Q5-Q1 spreads in all 18 frozen "
        "cells at h5/h10/h20. This anatomy was generated after that sign was known. "
        "It is post-hoc consumed-development analysis, not confirmation or OOS evidence.",
        "",
        "## Q1 long leg and parameter-neighborhood consistency",
        "",
        "| Horizon | Q1 absolute | Q1 industry-relative | Q1 median | Positive rate | "
        "Abs-positive cells | IndRel-positive cells | Both-positive | Monotonic |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        row = family[f"h{horizon}"]
        lines.append(
            f"| h{horizon} | {_fmt(row['q1_absolute_mean_equal_cell'])} | "
            f"{_fmt(row['q1_industry_relative_mean_equal_cell'])} | "
            f"{_fmt(row['q1_absolute_median_equal_cell'])} | "
            f"{_fmt(row['q1_positive_rate_equal_cell'])} | "
            f"{row['q1_positive_absolute_cells']}/18 | "
            f"{row['q1_positive_industry_relative_cells']}/18 | "
            f"{row['q1_both_positive_cells']}/18 | "
            f"{row['both_coordinate_monotonic_cells']}/18 |"
        )
    lines.extend(
        [
            "",
            "## Q1-Q5 anatomy",
            "",
            "The tracked compact bucket table contains Q1 through Q5 separately for "
            "every frozen cell and horizon, plus Q1 block/year rows. Equal-cell family "
            "means are shown below.",
            "",
            "| Horizon | Bucket | Absolute mean | Industry-relative mean | Median | Win rate |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    full = bucket_table.loc[bucket_table.scope.eq("FULL")]
    for horizon in HORIZONS:
        for bucket in BUCKETS:
            rows = full.loc[full.horizon.eq(horizon) & full.bucket.eq(bucket)]
            lines.append(
                f"| h{horizon} | Q{bucket} | {_fmt(rows.absolute_mean.mean())} | "
                f"{_fmt(rows.industry_relative_mean.mean())} | "
                f"{_fmt(rows.absolute_median.mean())} | "
                f"{_fmt(rows.absolute_positive_rate.mean())} |"
            )
    lines.extend(
        [
            "",
            "## Event-sample baseline decomposition",
            "",
            "| Horizon | Q1-event absolute | Q5-event absolute | Q1 share | "
            "Q1-event industry-relative | Q5-event industry-relative |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for horizon in HORIZONS:
        row = family[f"h{horizon}"]
        lines.append(
            f"| h{horizon} | {_fmt(row['q1_minus_event_absolute_equal_cell'])} | "
            f"{_fmt(row['q5_minus_event_absolute_equal_cell'])} | "
            f"{_fmt(row['q1_strength_contribution_share_equal_cell'])} | "
            f"{_fmt(row['q1_minus_event_industry_relative_equal_cell'])} | "
            f"{_fmt(row['q5_minus_event_industry_relative_equal_cell'])} |"
        )
    continuous = result["continuous_summary"]
    lines.extend(
        [
            "",
            "## Monotonicity",
            "",
            "| Horizon | Mean absolute steps | Mean industry-relative steps | "
            "Mean absolute bucket rho | Mean industry-relative bucket rho | Both monotonic |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    monotonic_rows = pd.DataFrame(result["monotonicity"])
    for horizon in HORIZONS:
        rows = monotonic_rows.loc[monotonic_rows.horizon.eq(horizon)]
        records = rows.to_dict("records")
        absolute_steps = np.mean([row["absolute"]["adjacent_favorable_steps"] for row in records])
        relative_steps = np.mean(
            [row["industry_relative"]["adjacent_favorable_steps"] for row in records]
        )
        absolute_rho = np.mean([row["absolute"]["bucket_spearman"] for row in records])
        relative_rho = np.mean([row["industry_relative"]["bucket_spearman"] for row in records])
        lines.append(
            f"| h{horizon} | "
            f"{absolute_steps:.2f}/4 | {relative_steps:.2f}/4 | "
            f"{absolute_rho:.3f} | {relative_rho:.3f} | "
            f"{int(rows.both_coordinates_broadly_monotonic.sum())}/18 |"
        )
    lines.extend(
        [
            "",
            "## Continuous and further-drawdown diagnostics",
            "",
            f"Across primary cell/horizon coordinates, Recovery Fraction has the "
            f"expected negative mean same-date rho in "
            f"{continuous['recovery_negative_primary_coordinates']}/108 coordinates. "
            f"Its mean rho is {continuous['recovery_primary_mean_rho_absolute']:.3f} "
            f"absolute and {continuous['recovery_primary_mean_rho_industry_relative']:.3f} "
            f"industry-relative. "
            f"Further Drawdown Ratio has the reversal-consistent positive rho in "
            f"{continuous['further_drawdown_positive_primary_coordinates']}/108; mean rho "
            f"is {continuous['further_drawdown_primary_mean_rho_absolute']:.3f} absolute "
            f"and {continuous['further_drawdown_primary_mean_rho_industry_relative']:.3f} "
            "industry-relative.",
            "",
            "## Chronological anatomy",
            "",
        ]
    )
    chronology = result["chronology"]
    for period, values in chronology["blocks"].items():
        lines.append(f"### {period}")
        lines.append("")
        for horizon in PRIMARY_HORIZONS:
            row = values[f"h{horizon}"]
            lines.append(
                f"- h{horizon}: Q1 absolute {_fmt(row['absolute_mean_equal_cell'])}; "
                f"industry-relative {_fmt(row['industry_relative_mean_equal_cell'])}; "
                f"positive cells {row['positive_absolute_cells']}/18 and "
                f"{row['positive_industry_relative_cells']}/18."
            )
        lines.append("")
    lines.extend(
        [
            "| Year | h5 absolute / industry-relative | h10 absolute / industry-relative | "
            "h20 absolute / industry-relative |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for year, values in chronology["years"].items():
        lines.append(
            f"| {year} | {_fmt(values['h5']['absolute_mean_equal_cell'])} / "
            f"{_fmt(values['h5']['industry_relative_mean_equal_cell'])} | "
            f"{_fmt(values['h10']['absolute_mean_equal_cell'])} / "
            f"{_fmt(values['h10']['industry_relative_mean_equal_cell'])} | "
            f"{_fmt(values['h20']['absolute_mean_equal_cell'])} / "
            f"{_fmt(values['h20']['industry_relative_mean_equal_cell'])} |"
        )
    lines.extend(
        [
            "",
            "## Existing controls",
            "",
            f"Supported positive Q1 control cells: severity "
            f"{result['control_summary']['severity_pass_cells']}/"
            f"{result['control_summary']['severity_supported_cells']}; trend "
            f"{result['control_summary']['trend_pass_terciles']}/3; volatility "
            f"{result['control_summary']['volatility_pass_terciles']}/3; liquidity "
            f"{result['control_summary']['liquidity_pass_terciles']}/3.",
            "",
            "### Frozen generic-recovery Q1 comparison",
            "",
            "| Window | Sample | h5 absolute / industry-relative | "
            "h10 absolute / industry-relative | h20 absolute / industry-relative |",
            "| ---: | --- | ---: | ---: | ---: |",
        ]
    )
    for window, values in result["controls"]["generic"].items():
        for sample in ("shock", "generic"):
            horizons = values[sample]["horizons"]
            lines.append(
                f"| {window} | {sample} | "
                f"{_fmt(horizons['h5']['absolute_mean'])} / "
                f"{_fmt(horizons['h5']['industry_relative_mean'])} | "
                f"{_fmt(horizons['h10']['absolute_mean'])} / "
                f"{_fmt(horizons['h10']['industry_relative_mean'])} | "
                f"{_fmt(horizons['h20']['absolute_mean'])} / "
                f"{_fmt(horizons['h20']['industry_relative_mean'])} |"
            )
    lines.extend(
        [
            "",
            "## Research status and next direction",
            "",
            f"Status: `{result['post_hoc_status']}`. No strategy replay, transaction-cost "
            "study, parameter rescue, Strategy-A change, post-2023 outcome, or CY-011 "
            "input was used.",
            "",
            result["next_recommended_research_direction"],
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    spec = _load_spec()
    v1_result = json.loads(
        _resolve(spec["inputs"]["v1_1_result"]["path"]).read_text(encoding="utf-8")
    )
    cells = [item["cell_id"] for item in v1_result["parameter_grid"]]
    panel = _read_panel(spec)
    maximum = _validate_panel(panel, cells)
    shock = panel.loc[panel.sample_type.eq("SHOCK")].copy()
    bucket_table = _bucket_table(shock, cells)
    baseline, monotonic = _full_anatomy(shock, bucket_table, cells)
    continuous = _continuous_diagnostics(shock, cells)
    family = _family_summary(bucket_table, baseline, monotonic)
    chronology = _chronology(bucket_table)
    controls = _controls(panel)
    classification, classification_diagnostics = classify(family, chronology, baseline)
    primary_continuous = continuous.loc[continuous.horizon.isin(PRIMARY_HORIZONS)]
    continuous_summary = {
        "recovery_negative_primary_coordinates": int(
            primary_continuous.loc[primary_continuous.score.eq("recovery_fraction")]
            .mean_same_date_spearman.lt(0)
            .sum()
        ),
        "further_drawdown_positive_primary_coordinates": int(
            primary_continuous.loc[primary_continuous.score.eq("further_drawdown_ratio")]
            .mean_same_date_spearman.gt(0)
            .sum()
        ),
        "recovery_primary_mean_rho_absolute": float(
            primary_continuous.loc[
                primary_continuous.score.eq("recovery_fraction")
                & primary_continuous.coordinate.eq("absolute")
            ].mean_same_date_spearman.mean()
        ),
        "recovery_primary_mean_rho_industry_relative": float(
            primary_continuous.loc[
                primary_continuous.score.eq("recovery_fraction")
                & primary_continuous.coordinate.eq("industry_relative")
            ].mean_same_date_spearman.mean()
        ),
        "further_drawdown_primary_mean_rho_absolute": float(
            primary_continuous.loc[
                primary_continuous.score.eq("further_drawdown_ratio")
                & primary_continuous.coordinate.eq("absolute")
            ].mean_same_date_spearman.mean()
        ),
        "further_drawdown_primary_mean_rho_industry_relative": float(
            primary_continuous.loc[
                primary_continuous.score.eq("further_drawdown_ratio")
                & primary_continuous.coordinate.eq("industry_relative")
            ].mean_same_date_spearman.mean()
        ),
        "total_primary_coordinates_per_score": 108,
        "rows": continuous.to_dict("records"),
    }
    severity_supported = [item for item in controls["severity"] if item["observations"] >= 100]
    control_summary = {
        "severity_supported_cells": len(severity_supported),
        "severity_pass_cells": sum(item["pass"] for item in severity_supported),
        "trend_pass_terciles": sum(item["pass"] for item in controls["coarse"]["PRE_SHOCK_TREND"]),
        "volatility_pass_terciles": sum(
            item["pass"] for item in controls["coarse"]["REALIZED_VOLATILITY"]
        ),
        "liquidity_pass_terciles": sum(item["pass"] for item in controls["coarse"]["LIQUIDITY"]),
    }
    interpretations = {
        "POST_HOC_LONG_REVERSAL_CANDIDATE": (
            "Q1 itself is broadly positive, chronological and monotonic across the "
            "neighborhood. This is a data-generated hypothesis only, not confirmed Alpha."
        ),
        "RELATIVE_REVERSAL_ONLY": (
            "Q1 has repeated industry-relative value, but its absolute long economics "
            "do not meet the frozen candidate standard."
        ),
        "STRONG_RECOVERY_AVOIDANCE_ONLY": (
            "The reversed spread is carried mainly by Q5 weakness; Q1 is not a credible "
            "standalone long candidate."
        ),
        "DEFENSIVE_LESS_BAD_ONLY": (
            "Q1 mainly reduces severe loss without establishing convincing positive payoff."
        ),
        "NONMONOTONIC_BUCKET_EFFECT": (
            "Intermediate buckets do not support a coherent continuous adverse-recovery "
            "relationship, so the Q5-Q1 extremes do not define a reversal mechanism."
        ),
        "CHRONOLOGICALLY_UNSTABLE": (
            "Q1 long economics materially reverse between consumed development blocks."
        ),
        "NO_LONG_REVERSAL_ALPHA": (
            "The prior adverse Q5-Q1 ordering does not translate into a credible Q1 long "
            "candidate under the frozen anatomy gates."
        ),
    }
    interpretation = interpretations[classification]
    if (
        classification == "CHRONOLOGICALLY_UNSTABLE"
        and classification_diagnostics["avoidance_gate"]
    ):
        interpretation += (
            " The secondary frozen decomposition is avoidance-like: Q5 weakness carries "
            "most of the primary-horizon spread while Q1 is not an attractive long leg."
        )
    if classification == "POST_HOC_LONG_REVERSAL_CANDIDATE":
        next_direction = (
            "Freeze the data-generated reversal hypothesis for genuinely independent "
            "future research; keep post-2023 outcomes quarantined."
        )
    else:
        next_direction = (
            "Close the local shock/recovery family without bucket or parameter rescue and "
            "resume the frozen Cross-Sectional Dispersion science."
        )
    result = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "frozen_spec_sha256": EXPECTED_SPEC_SHA256,
        "claim_boundary": spec["claim_boundary"],
        "provenance": spec["provenance"],
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "max_evaluation_outcome_date": str(maximum),
        "parameter_cells_reused": len(cells),
        "total_shock_cell_events": len(shock),
        "family_summary": family,
        "baseline_decomposition": baseline.to_dict("records"),
        "monotonicity": monotonic.to_dict("records"),
        "continuous_summary": continuous_summary,
        "chronology": chronology,
        "controls": controls,
        "control_summary": control_summary,
        "classification_diagnostics": classification_diagnostics,
        "final_classification": classification,
        "post_hoc_status": (
            "DATA_GENERATED_DEVELOPMENT_HYPOTHESIS_NOT_CONFIRMED_ALPHA"
            if classification == "POST_HOC_LONG_REVERSAL_CANDIDATE"
            else "POST_HOC_DEVELOPMENT_ANATOMY_NO_CANDIDATE_NOT_CONFIRMED_ALPHA"
        ),
        "economic_interpretation": interpretation,
        "next_recommended_research_direction": next_direction,
        "input_identity": {role: binding["sha256"] for role, binding in spec["inputs"].items()},
        "artifacts": {
            "bucket_table": str(BUCKET_PATH.relative_to(ROOT)),
            "report": str(REPORT_PATH.relative_to(ROOT)),
        },
    }
    BUCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
    bucket_table.to_csv(BUCKET_PATH, index=False, float_format="%.12g")
    result["artifacts"]["bucket_table_sha256"] = sha256_file(BUCKET_PATH)
    _atomic_write(REPORT_PATH, _report(result, bucket_table))
    result["artifacts"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "classification": classification,
                "events": len(shock),
                "parameter_cells": len(cells),
                "result_sha256": sha256_file(RESULT_PATH),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
