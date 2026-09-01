#!/usr/bin/env python3
"""Run the frozen Q5-only post-shock strong-recovery avoidance anatomy."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-POST-SHOCK-STRONG-RECOVERY-AVOIDANCE-ANATOMY-V1_spec.json"
RESULT_PATH = (
    PROGRAM / "artifacts/ASHARE-POST-SHOCK-STRONG-RECOVERY-AVOIDANCE-ANATOMY-V1_result.json"
)
TABLE_PATH = (
    PROGRAM / "artifacts/ASHARE-POST-SHOCK-STRONG-RECOVERY-AVOIDANCE-ANATOMY-V1_q5_table.csv"
)
REPORT_PATH = PROGRAM / "reports/ASHARE-POST-SHOCK-STRONG-RECOVERY-AVOIDANCE-ANATOMY-V1_report.md"
EXPECTED_SPEC_SHA256 = "262045c7ab32fb9bfa74e966fcc415d6c531bcb00874f8a030fc1a80c976d0f2"
HORIZONS = (1, 3, 5, 10, 20)
PRIMARY_HORIZONS = (5, 10, 20)
TARGET = "ABS_m06_REL_m04_W3"
Q5 = 5
SEVERE = -0.10


class StrongRecoveryAvoidanceError(RuntimeError):
    """Fail-closed error for the frozen avoidance anatomy."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


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


def deterministic_json(value: Any) -> str:
    return json.dumps(_clean(value), indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StrongRecoveryAvoidanceError("frozen avoidance specification changed")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_NEW_Q5_POST_HOC_OUTCOME_AGGREGATION":
        raise StrongRecoveryAvoidanceError("invalid avoidance freeze status")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise StrongRecoveryAvoidanceError(f"bound input changed: {role}")
    if spec["sample"]["parameter_cells"] != 18 or spec["sample"]["selected_bucket"] != Q5:
        raise StrongRecoveryAvoidanceError("frozen Q5 family changed")
    return spec


def validate_outcome_boundary(panel: pd.DataFrame) -> date:
    if panel.empty or pd.to_datetime(panel.signal_date).dt.year.max() > 2023:
        raise StrongRecoveryAvoidanceError("empty or post-2023 signal panel")
    dates = pd.concat(
        [pd.to_datetime(panel[f"outcome_date_h{horizon}"]) for horizon in HORIZONS]
    ).dropna()
    if dates.empty:
        raise StrongRecoveryAvoidanceError("no complete outcome dates")
    maximum = dates.max().date()
    if maximum > pd.Timestamp("2023-12-31").date():
        raise StrongRecoveryAvoidanceError("post-2023 outcome detected")
    return maximum


def _read_panel(spec: dict[str, Any]) -> pd.DataFrame:
    columns = [
        "event_id",
        "cell_id",
        "window",
        "signal_date",
        "sample_type",
        "recovery_quintile",
        "absolute_shock_magnitude",
        "relative_shock_magnitude",
        "pre_shock_trend20",
        "pre_shock_volatility20",
        "shock_avg_amount20",
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
    panel = pd.read_parquet(_resolve(spec["inputs"]["evaluation_panel"]["path"]), columns=columns)
    panel["signal_date"] = pd.to_datetime(panel.signal_date)
    panel["year"] = panel.signal_date.dt.year
    return panel


def _validate_panel(panel: pd.DataFrame, cells: list[str]) -> date:
    maximum = validate_outcome_boundary(panel)
    shock = panel.loc[panel.sample_type.eq("SHOCK")]
    if len(shock) != 709_981:
        raise StrongRecoveryAvoidanceError(f"shock event count changed: {len(shock)}")
    if sorted(shock.cell_id.unique()) != sorted(cells):
        raise StrongRecoveryAvoidanceError("exact V1.1 cells changed")
    if set(shock.recovery_quintile.dropna().astype(int).unique()) != {1, 2, 3, 4, 5}:
        raise StrongRecoveryAvoidanceError("recovery quintile mapping changed")
    if shock.duplicated("event_id").any():
        raise StrongRecoveryAvoidanceError("duplicate shock event identity")
    return maximum


def q5_metrics(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    absolute_column = f"net_return_h{horizon}"
    relative_column = f"industry_relative_h{horizon}"
    q5 = group.loc[group.recovery_quintile.eq(Q5)].dropna(subset=[absolute_column, relative_column])
    absolute = q5[absolute_column]
    relative = q5[relative_column]
    return {
        "n": len(q5),
        "absolute_mean": absolute.mean(),
        "absolute_median": absolute.median(),
        "absolute_positive_rate": absolute.gt(0).mean(),
        "industry_relative_mean": relative.mean(),
        "industry_relative_median": relative.median(),
        "severe_loss_incidence": q5.mae_h20.le(SEVERE).mean() if horizon == 20 else np.nan,
        "mean_mae": q5.mae_h20.mean() if horizon == 20 else np.nan,
    }


def q5_baseline(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    absolute_column = f"net_return_h{horizon}"
    relative_column = f"industry_relative_h{horizon}"
    complete = group.dropna(subset=[absolute_column, relative_column])
    q1 = complete.loc[complete.recovery_quintile.eq(1)]
    q5 = complete.loc[complete.recovery_quintile.eq(Q5)]

    def coordinate(column: str) -> dict[str, Any]:
        event_mean = complete[column].mean()
        q1_mean = q1[column].mean()
        q5_mean = q5[column].mean()
        spread = q1_mean - q5_mean
        weakness = event_mean - q5_mean
        return {
            "event_mean": event_mean,
            "q1_mean": q1_mean,
            "q5_mean": q5_mean,
            "q5_minus_event": q5_mean - event_mean,
            "q1_minus_q5": spread,
            "q5_weakness_contribution_share": weakness / spread if spread > 0 else np.nan,
        }

    return {
        "n": len(complete),
        "absolute": coordinate(absolute_column),
        "industry_relative": coordinate(relative_column),
        "event_severe_loss_incidence_h20": (
            complete.mae_h20.le(SEVERE).mean() if horizon == 20 else np.nan
        ),
        "q5_severe_loss_incidence_h20": (q5.mae_h20.le(SEVERE).mean() if horizon == 20 else np.nan),
        "event_mean_mae_h20": complete.mae_h20.mean() if horizon == 20 else np.nan,
        "q5_mean_mae_h20": q5.mae_h20.mean() if horizon == 20 else np.nan,
    }


def _q5_table(shock: pd.DataFrame, cells: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str, pd.Series]] = [
        ("FULL", "2018_2023", pd.Series(True, index=shock.index)),
        ("BLOCK", "EARLY_2018_2021", shock.year.le(2021)),
        ("BLOCK", "LATE_2022_2023", shock.year.ge(2022)),
    ]
    scopes.extend(("YEAR", str(year), shock.year.eq(year)) for year in range(2018, 2024))
    for scope, period, mask in scopes:
        sample = shock.loc[mask]
        for cell in cells:
            cell_sample = sample.loc[sample.cell_id.eq(cell)]
            for horizon in HORIZONS:
                rows.append(
                    {
                        "scope": scope,
                        "period": period,
                        "cell_id": cell,
                        "horizon": horizon,
                        **q5_metrics(cell_sample, horizon),
                    }
                )
    return pd.DataFrame(rows)


def _full_baselines(shock: pd.DataFrame, cells: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "cell_id": cell,
                "horizon": horizon,
                **q5_baseline(shock.loc[shock.cell_id.eq(cell)], horizon),
            }
            for cell in cells
            for horizon in HORIZONS
        ]
    )


def _family_summary(table: pd.DataFrame, baselines: pd.DataFrame) -> dict[str, Any]:
    full = table.loc[table.scope.eq("FULL")]
    output: dict[str, Any] = {}
    for horizon in HORIZONS:
        rows = full.loc[full.horizon.eq(horizon)]
        base = baselines.loc[baselines.horizon.eq(horizon)].to_dict("records")
        output[f"h{horizon}"] = {
            "q5_n": int(rows.n.sum()),
            "q5_absolute_mean_equal_cell": rows.absolute_mean.mean(),
            "q5_absolute_mean_range": [rows.absolute_mean.min(), rows.absolute_mean.max()],
            "q5_industry_relative_mean_equal_cell": rows.industry_relative_mean.mean(),
            "q5_industry_relative_mean_range": [
                rows.industry_relative_mean.min(),
                rows.industry_relative_mean.max(),
            ],
            "q5_absolute_median_equal_cell": rows.absolute_median.mean(),
            "q5_positive_rate_equal_cell": rows.absolute_positive_rate.mean(),
            "negative_absolute_cells": int(rows.absolute_mean.lt(0).sum()),
            "negative_industry_relative_cells": int(rows.industry_relative_mean.lt(0).sum()),
            "both_negative_cells": int(
                (rows.absolute_mean.lt(0) & rows.industry_relative_mean.lt(0)).sum()
            ),
            "negative_absolute_median_cells": int(rows.absolute_median.lt(0).sum()),
            "sub_50_positive_rate_cells": int(rows.absolute_positive_rate.lt(0.50).sum()),
            "q5_minus_event_absolute_equal_cell": float(
                np.mean([item["absolute"]["q5_minus_event"] for item in base])
            ),
            "q5_minus_event_industry_relative_equal_cell": float(
                np.mean([item["industry_relative"]["q5_minus_event"] for item in base])
            ),
            "q5_below_event_absolute_cells": int(
                sum(item["absolute"]["q5_minus_event"] < 0 for item in base)
            ),
            "q5_below_event_industry_relative_cells": int(
                sum(item["industry_relative"]["q5_minus_event"] < 0 for item in base)
            ),
            "q5_below_event_both_cells": int(
                sum(
                    item["absolute"]["q5_minus_event"] < 0
                    and item["industry_relative"]["q5_minus_event"] < 0
                    for item in base
                )
            ),
            "q5_weakness_contribution_share_equal_cell": float(
                np.nanmean([item["absolute"]["q5_weakness_contribution_share"] for item in base])
            ),
        }
        if horizon == 20:
            output[f"h{horizon}"].update(
                {
                    "q5_severe_loss_incidence_equal_cell": float(
                        np.mean([item["q5_severe_loss_incidence_h20"] for item in base])
                    ),
                    "event_severe_loss_incidence_equal_cell": float(
                        np.mean([item["event_severe_loss_incidence_h20"] for item in base])
                    ),
                    "q5_mean_mae_equal_cell": float(
                        np.mean([item["q5_mean_mae_h20"] for item in base])
                    ),
                    "event_mean_mae_equal_cell": float(
                        np.mean([item["event_mean_mae_h20"] for item in base])
                    ),
                    "q5_worse_severe_loss_cells": int(
                        sum(
                            item["q5_severe_loss_incidence_h20"]
                            > item["event_severe_loss_incidence_h20"]
                            for item in base
                        )
                    ),
                    "q5_worse_mae_cells": int(
                        sum(item["q5_mean_mae_h20"] < item["event_mean_mae_h20"] for item in base)
                    ),
                }
            )
    return output


def _chronology(table: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {"blocks": {}, "years": {}}

    def summarize(rows: pd.DataFrame) -> dict[str, Any]:
        return {
            f"h{horizon}": {
                "q5_n": int(group.n.sum()),
                "absolute_mean_equal_cell": group.absolute_mean.mean(),
                "industry_relative_mean_equal_cell": group.industry_relative_mean.mean(),
                "negative_absolute_cells": int(group.absolute_mean.lt(0).sum()),
                "negative_industry_relative_cells": int(group.industry_relative_mean.lt(0).sum()),
                "both_negative_cells": int(
                    (group.absolute_mean.lt(0) & group.industry_relative_mean.lt(0)).sum()
                ),
                "negative_median_cells": int(group.absolute_median.lt(0).sum()),
                "sub_50_positive_rate_cells": int(group.absolute_positive_rate.lt(0.50).sum()),
            }
            for horizon in HORIZONS
            for group in [rows.loc[rows.horizon.eq(horizon)]]
        }

    for period in ("EARLY_2018_2021", "LATE_2022_2023"):
        output["blocks"][period] = summarize(
            table.loc[table.scope.eq("BLOCK") & table.period.eq(period)]
        )
    for year in range(2018, 2024):
        output["years"][str(year)] = summarize(
            table.loc[table.scope.eq("YEAR") & table.period.eq(str(year))]
        )
    return output


def _group_diagnostic(group: pd.DataFrame) -> dict[str, Any]:
    output = {"q5_observations": int(group.recovery_quintile.eq(Q5).sum()), "horizons": {}}
    for horizon in PRIMARY_HORIZONS:
        metrics = q5_metrics(group, horizon)
        baseline = q5_baseline(group, horizon)
        output["horizons"][f"h{horizon}"] = {
            **metrics,
            "q5_minus_event_absolute": baseline["absolute"]["q5_minus_event"],
            "q5_minus_event_industry_relative": baseline["industry_relative"]["q5_minus_event"],
        }
    output["adverse_supported"] = bool(
        output["q5_observations"] >= 100
        and all(
            output["horizons"][f"h{horizon}"]["absolute_mean"] < 0
            and output["horizons"][f"h{horizon}"]["industry_relative_mean"] < 0
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
    severity = [
        {
            "absolute_bin": absolute_bin,
            "relative_bin": relative_bin,
            **_group_diagnostic(group),
        }
        for (absolute_bin, relative_bin), group in target.groupby(
            ["absolute_bin", "relative_bin"], sort=True
        )
    ]
    definitions = {
        "PRE_SHOCK_TREND": "pre_shock_trend20",
        "REALIZED_VOLATILITY": "pre_shock_volatility20",
        "LIQUIDITY": "shock_avg_amount20",
    }
    coarse: dict[str, Any] = {}
    for name, column in definitions.items():
        ranks = target.groupby("signal_date", sort=False)[column].rank(method="average", pct=True)
        terciles = np.ceil(ranks * 3).clip(1, 3).astype("Int64")
        coarse[name] = [
            {"tercile": tercile, **_group_diagnostic(target.loc[terciles.eq(tercile)])}
            for tercile in range(1, 4)
        ]
    return {"target": TARGET, "severity": severity, "coarse": coarse}


def _generic_comparison(panel: pd.DataFrame) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for window in (2, 3, 5):
        pair: dict[str, Any] = {}
        for name, sample in (
            (
                "shock",
                panel.loc[
                    panel.cell_id.eq(f"ABS_m06_REL_m04_W{window}") & panel.sample_type.eq("SHOCK")
                ],
            ),
            (
                "generic",
                panel.loc[
                    panel.cell_id.eq(f"GENERIC_W{window}") & panel.sample_type.eq("NONSHOCK")
                ],
            ),
        ):
            pair[name] = {
                f"h{horizon}": {
                    **q5_metrics(sample, horizon),
                    "baseline": q5_baseline(sample, horizon),
                }
                for horizon in PRIMARY_HORIZONS
            }
        shock_magnitude = np.mean(
            [
                -pair["shock"][f"h{horizon}"]["baseline"]["absolute"]["q5_minus_event"]
                for horizon in PRIMARY_HORIZONS
            ]
        )
        generic_magnitude = np.mean(
            [
                -pair["generic"][f"h{horizon}"]["baseline"]["absolute"]["q5_minus_event"]
                for horizon in PRIMARY_HORIZONS
            ]
        )
        pair["generic_to_shock_absolute_magnitude_ratio"] = (
            generic_magnitude / shock_magnitude if shock_magnitude > 0 else np.nan
        )
        pair["comparable_generic_window"] = bool(
            all(
                pair["generic"][f"h{horizon}"]["baseline"]["absolute"]["q5_minus_event"] < 0
                and pair["generic"][f"h{horizon}"]["baseline"]["industry_relative"][
                    "q5_minus_event"
                ]
                < 0
                for horizon in PRIMARY_HORIZONS
            )
            and pair["generic_to_shock_absolute_magnitude_ratio"] >= 0.75
        )
        output[f"W{window}"] = pair
    return output


def classify(
    family: dict[str, Any],
    chronology: dict[str, Any],
    controls: dict[str, Any],
    generic: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    primary = [family[f"h{horizon}"] for horizon in PRIMARY_HORIZONS]
    early = chronology["blocks"]["EARLY_2018_2021"]
    late = chronology["blocks"]["LATE_2022_2023"]
    sign_reversals = sum(
        np.sign(early[f"h{horizon}"][coordinate]) != np.sign(late[f"h{horizon}"][coordinate])
        for horizon in PRIMARY_HORIZONS
        for coordinate in ("absolute_mean_equal_cell", "industry_relative_mean_equal_cell")
    )
    block_stability = all(
        block[f"h{horizon}"]["absolute_mean_equal_cell"] < 0
        and block[f"h{horizon}"]["industry_relative_mean_equal_cell"] < 0
        for block in (early, late)
        for horizon in PRIMARY_HORIZONS
    )
    year_counts = {
        f"h{horizon}": sum(
            chronology["years"][str(year)][f"h{horizon}"]["absolute_mean_equal_cell"] < 0
            and chronology["years"][str(year)][f"h{horizon}"]["industry_relative_mean_equal_cell"]
            < 0
            for year in range(2018, 2024)
        )
        for horizon in PRIMARY_HORIZONS
    }
    year_stability = all(count >= 4 for count in year_counts.values())
    mean_weakness = all(
        item["negative_absolute_cells"] >= 12
        and item["negative_industry_relative_cells"] >= 12
        and item["both_negative_cells"] >= 12
        and item["q5_below_event_both_cells"] >= 12
        for item in primary
    )
    broad_horizon = {
        f"h{horizon}": family[f"h{horizon}"]["negative_absolute_median_cells"] >= 12
        and family[f"h{horizon}"]["sub_50_positive_rate_cells"] >= 12
        for horizon in PRIMARY_HORIZONS
    }
    broad_weakness = all(broad_horizon.values())
    mean_only_horizons = sum(not value for value in broad_horizon.values())
    mean_event_delta = float(
        np.mean([item["q5_minus_event_absolute_equal_cell"] for item in primary])
    )
    material = bool(
        mean_event_delta <= -0.002
        and all(
            item["q5_minus_event_absolute_equal_cell"] < 0
            and item["q5_minus_event_industry_relative_equal_cell"] < 0
            for item in primary
        )
    )
    severity_supported = [item for item in controls["severity"] if item["q5_observations"] >= 100]
    severity_pass = sum(item["adverse_supported"] for item in severity_supported)
    tercile_pass = {
        name: sum(item["adverse_supported"] for item in rows)
        for name, rows in controls["coarse"].items()
    }
    control_survival = bool(
        severity_supported
        and severity_pass * 2 >= len(severity_supported)
        and all(count >= 2 for count in tercile_pass.values())
    )
    comparable_generic_windows = sum(item["comparable_generic_window"] for item in generic.values())
    generic_risk = comparable_generic_windows >= 2
    relative_only_gate = bool(
        all(
            item["negative_industry_relative_cells"] >= 12
            and item["q5_below_event_industry_relative_cells"] >= 12
            for item in primary
        )
        and all(
            block[f"h{horizon}"]["industry_relative_mean_equal_cell"] < 0
            for block in (early, late)
            for horizon in PRIMARY_HORIZONS
        )
        and not mean_weakness
    )
    candidate = bool(
        mean_weakness
        and material
        and broad_weakness
        and block_stability
        and year_stability
        and control_survival
        and not generic_risk
    )
    mean_only = bool(mean_weakness and material and mean_only_horizons >= 2)
    if sign_reversals >= 2:
        classification = "CHRONOLOGICALLY_UNSTABLE"
    elif generic_risk:
        classification = "GENERIC_RECOVERY_CHASING_RISK"
    elif candidate:
        classification = "POST_HOC_STRONG_RECOVERY_AVOIDANCE_CANDIDATE"
    elif relative_only_gate:
        classification = "RELATIVE_AVOIDANCE_ONLY"
    elif mean_only:
        classification = "MEAN_ONLY_Q5_WEAKNESS"
    else:
        classification = "NO_ACTIONABLE_AVOIDANCE_INFORMATION"
    return classification, {
        "sign_reversal_primary_coordinates": int(sign_reversals),
        "stable_block_direction": block_stability,
        "negative_both_years_by_horizon": year_counts,
        "stable_year_breadth": year_stability,
        "mean_weakness_gate": mean_weakness,
        "broad_weakness_by_horizon": broad_horizon,
        "broad_weakness_gate": broad_weakness,
        "mean_only_failed_horizons": int(mean_only_horizons),
        "mean_primary_q5_minus_event_absolute": mean_event_delta,
        "material_event_underperformance_gate": material,
        "severity_supported_groups": len(severity_supported),
        "severity_adverse_groups": int(severity_pass),
        "adverse_terciles": tercile_pass,
        "control_survival_gate": control_survival,
        "comparable_generic_windows": int(comparable_generic_windows),
        "generic_recovery_chasing_risk_gate": generic_risk,
        "candidate_gate": candidate,
        "relative_only_gate": relative_only_gate,
        "mean_only_gate": mean_only,
    }


def _fmt(value: float | None) -> str:
    return "n/a" if value is None or not math.isfinite(value) else f"{value:.3%}"


def _report(result: dict[str, Any]) -> str:
    family = result["family_summary"]
    diagnostics = result["classification_diagnostics"]
    lines = [
        "# A-share Post-Shock Strong-Recovery Avoidance Anatomy V1",
        "",
        "## Executive conclusion",
        "",
        f"Final classification: `{result['final_classification']}`.",
        "",
        result["economic_interpretation"],
        "",
        "This Q5-only direction was generated after the V1.1 adverse surface and prior "
        "Q1-Q5 anatomy were known. It is post-hoc consumed-development anatomy, not "
        "independent confirmation, OOS evidence, or a strategy replay.",
        "",
        f"The bound prior anatomy attributed "
        f"{result['prior_anatomy_q5_weakness_contribution_share_primary']:.2%} of the "
        "primary-horizon adverse spread to Q5 weakness under its frozen positive-Q1 "
        "contribution convention.",
        "",
        "## Q5 economics and event-sample decomposition",
        "",
        "| Horizon | N | Absolute | Industry-relative | Median | Win rate | "
        "Q5-event abs | Q5-event rel |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        row = family[f"h{horizon}"]
        lines.append(
            f"| h{horizon} | {row['q5_n']:,} | {_fmt(row['q5_absolute_mean_equal_cell'])} | "
            f"{_fmt(row['q5_industry_relative_mean_equal_cell'])} | "
            f"{_fmt(row['q5_absolute_median_equal_cell'])} | "
            f"{_fmt(row['q5_positive_rate_equal_cell'])} | "
            f"{_fmt(row['q5_minus_event_absolute_equal_cell'])} | "
            f"{_fmt(row['q5_minus_event_industry_relative_equal_cell'])} |"
        )
    lines.extend(
        [
            "",
            "## Parameter-neighborhood breadth",
            "",
            "| Horizon | Abs < 0 | IndRel < 0 | Both < 0 | Median < 0 | "
            "Win < 50% | Below event both |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for horizon in PRIMARY_HORIZONS:
        row = family[f"h{horizon}"]
        lines.append(
            f"| h{horizon} | {row['negative_absolute_cells']}/18 | "
            f"{row['negative_industry_relative_cells']}/18 | {row['both_negative_cells']}/18 | "
            f"{row['negative_absolute_median_cells']}/18 | "
            f"{row['sub_50_positive_rate_cells']}/18 | "
            f"{row['q5_below_event_both_cells']}/18 |"
        )
    lines.extend(["", "## Chronology", ""])
    for period, values in result["chronology"]["blocks"].items():
        lines.append(f"### {period}")
        lines.append("")
        for horizon in PRIMARY_HORIZONS:
            row = values[f"h{horizon}"]
            lines.append(
                f"- h{horizon}: absolute {_fmt(row['absolute_mean_equal_cell'])}; "
                f"industry-relative {_fmt(row['industry_relative_mean_equal_cell'])}; "
                f"both-negative cells {row['both_negative_cells']}/18."
            )
        lines.append("")
    lines.extend(
        [
            "| Year | h5 absolute / relative | h10 absolute / relative | h20 absolute / relative |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for year, values in result["chronology"]["years"].items():
        lines.append(
            f"| {year} | {_fmt(values['h5']['absolute_mean_equal_cell'])} / "
            f"{_fmt(values['h5']['industry_relative_mean_equal_cell'])} | "
            f"{_fmt(values['h10']['absolute_mean_equal_cell'])} / "
            f"{_fmt(values['h10']['industry_relative_mean_equal_cell'])} | "
            f"{_fmt(values['h20']['absolute_mean_equal_cell'])} / "
            f"{_fmt(values['h20']['industry_relative_mean_equal_cell'])} |"
        )
    h20 = family["h20"]
    lines.extend(
        [
            "",
            "## Risk anatomy",
            "",
            "At h20, Q5 severe-loss incidence was "
            f"{_fmt(h20['q5_severe_loss_incidence_equal_cell'])} "
            f"versus {_fmt(h20['event_severe_loss_incidence_equal_cell'])} for all shock events; "
            f"Q5 was worse in {h20['q5_worse_severe_loss_cells']}/18 cells. Mean MAE was "
            f"{_fmt(h20['q5_mean_mae_equal_cell'])} versus "
            f"{_fmt(h20['event_mean_mae_equal_cell'])}; "
            f"Q5 was worse in {h20['q5_worse_mae_cells']}/18 cells.",
            "",
            "## Frozen controls",
            "",
            f"Supported adverse severity groups: {diagnostics['severity_adverse_groups']}/"
            f"{diagnostics['severity_supported_groups']}. Adverse trend, volatility, "
            f"and liquidity terciles: {diagnostics['adverse_terciles']}.",
            "",
            "## Generic matched non-shock recovery",
            "",
            "| Window | Shock Q5-event abs | Generic Q5-event abs | "
            "Generic/shock magnitude | Comparable |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for window, pair in result["generic_comparison"].items():
        shock = np.mean(
            [
                pair["shock"][f"h{h}"]["baseline"]["absolute"]["q5_minus_event"]
                for h in PRIMARY_HORIZONS
            ]
        )
        generic = np.mean(
            [
                pair["generic"][f"h{h}"]["baseline"]["absolute"]["q5_minus_event"]
                for h in PRIMARY_HORIZONS
            ]
        )
        lines.append(
            f"| {window} | {_fmt(shock)} | {_fmt(generic)} | "
            f"{pair['generic_to_shock_absolute_magnitude_ratio']:.2f} | "
            f"{pair['comparable_generic_window']} |"
        )
    strategy = result["strategy_a_independence"]
    lines.extend(
        [
            "",
            "## Strategy-A independence and research status",
            "",
            f"Frozen V1.1 evidence was reused without replay: Low-MAX mean same-date rho "
            f"{strategy['low_max_rank_relationship']['mean_same_date_spearman']:.3f}; Q5 Champion "
            f"overlap {strategy['q5_champion_overlap_fraction']:.3%}; only "
            f"{strategy['q5_champion_overlap_count']} overlapping observations. "
            "Strategy A was unchanged.",
            "",
            f"Status: `{result['post_hoc_status']}`.",
            "",
            result["next_recommended_research_direction"],
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    spec = _load_spec()
    v1_result = json.loads(_resolve(spec["inputs"]["v1_1_result"]["path"]).read_text())
    prior_anatomy = json.loads(
        _resolve(spec["inputs"]["adverse_recovery_anatomy_result"]["path"]).read_text()
    )
    cells = [item["cell_id"] for item in v1_result["parameter_grid"]]
    panel = _read_panel(spec)
    maximum = _validate_panel(panel, cells)
    shock = panel.loc[panel.sample_type.eq("SHOCK")].copy()
    table = _q5_table(shock, cells)
    baselines = _full_baselines(shock, cells)
    family = _family_summary(table, baselines)
    chronology = _chronology(table)
    controls = _controls(panel)
    generic = _generic_comparison(panel)
    classification, diagnostics = classify(family, chronology, controls, generic)
    interpretations = {
        "POST_HOC_STRONG_RECOVERY_AVOIDANCE_CANDIDATE": (
            "Extreme post-shock Q5 recovery is broadly and stably adverse in absolute, "
            "industry-relative, median, win-rate, control, and event-baseline terms. This "
            "freezes a data-generated negative-selection hypothesis, not confirmed Alpha."
        ),
        "RELATIVE_AVOIDANCE_ONLY": (
            "Q5 is repeatedly adverse relative to its PIT industry, but absolute weakness "
            "does not support a standalone long-only admission veto."
        ),
        "MEAN_ONLY_Q5_WEAKNESS": (
            "Q5 underperformance is primarily a mean effect; medians and win rates do not "
            "show sufficiently broad negative-selection information."
        ),
        "GENERIC_RECOVERY_CHASING_RISK": (
            "Matched non-shock Q5 recovery is comparably adverse, so the finding is a "
            "broader data-generated recovery-chasing risk rather than shock-specific avoidance."
        ),
        "CHRONOLOGICALLY_UNSTABLE": (
            "Q5 avoidance direction materially changes between consumed development blocks."
        ),
        "NO_ACTIONABLE_AVOIDANCE_INFORMATION": (
            "Q5 passes the frozen magnitude and broad-distribution gates, but it does not "
            "meet the joint block-stability and severity-control standard for actionable "
            "negative selection."
        ),
    }
    candidate_classes = {
        "POST_HOC_STRONG_RECOVERY_AVOIDANCE_CANDIDATE",
        "GENERIC_RECOVERY_CHASING_RISK",
    }
    if classification == "POST_HOC_STRONG_RECOVERY_AVOIDANCE_CANDIDATE":
        next_direction = (
            "Freeze the exact Q5 post-shock avoidance hypothesis for a separate future "
            "admission-veto validation. Do not replay or tune it on 2018-2023."
        )
    elif classification == "GENERIC_RECOVERY_CHASING_RISK":
        next_direction = (
            "If prioritized, preregister the broader recovery-chasing negative-selection "
            "hypothesis for independent validation; do not relabel it as shock-specific "
            "or replay it here."
        )
    else:
        next_direction = (
            "Close the local shock/recovery family without cutoff, bucket, score, or execution "
            "rescue and resume frozen Cross-Sectional Dispersion science."
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
        "total_q5_cell_events": int(shock.recovery_quintile.eq(Q5).sum()),
        "prior_anatomy_q5_weakness_contribution_share_primary": float(
            1.0
            - np.mean(
                [
                    prior_anatomy["family_summary"][f"h{horizon}"][
                        "q1_strength_contribution_share_equal_cell"
                    ]
                    for horizon in PRIMARY_HORIZONS
                ]
            )
        ),
        "family_summary": family,
        "baseline_decomposition": baselines.to_dict("records"),
        "chronology": chronology,
        "controls": controls,
        "generic_comparison": generic,
        "classification_diagnostics": diagnostics,
        "final_classification": classification,
        "post_hoc_status": (
            "DATA_GENERATED_NEGATIVE_SELECTION_HYPOTHESIS_NOT_CONFIRMED_ALPHA"
            if classification in candidate_classes
            else "POST_HOC_DEVELOPMENT_ANATOMY_NO_CANDIDATE_NOT_CONFIRMED_ALPHA"
        ),
        "economic_interpretation": interpretations[classification],
        "next_recommended_research_direction": next_direction,
        "strategy_a_independence": v1_result["strategy_a_independence"],
        "strategy_a_modified": False,
        "strategy_a_replayed": False,
        "input_identity": {role: binding["sha256"] for role, binding in spec["inputs"].items()},
        "artifacts": {
            "q5_table": str(TABLE_PATH.relative_to(ROOT)),
            "report": str(REPORT_PATH.relative_to(ROOT)),
        },
    }
    TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(TABLE_PATH, index=False, float_format="%.12g")
    result["artifacts"]["q5_table_sha256"] = sha256_file(TABLE_PATH)
    _atomic_write(REPORT_PATH, _report(result))
    result["artifacts"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, deterministic_json(result))
    print(
        deterministic_json(
            {
                "classification": classification,
                "q5_events": result["total_q5_cell_events"],
                "parameter_cells": len(cells),
                "result_sha256": sha256_file(RESULT_PATH),
            }
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
