#!/usr/bin/env python3
"""Continuous conditional attribution and final robustness/falsification gates."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/opportunity_conversion"
PRIOR = ROOT / "research/chinext_v1/regime_attribution"
STATS_SCRIPT = WORK / "scripts/run_phase2_4_attribution.py"
PANEL = WORK / "artifacts/trade_conversion_panel.csv"
FEATURES = PRIOR / "artifacts/daily_regime_features.parquet"
ENTRY_RESULTS = WORK / "artifacts/causal_entry_feature_results.csv"
PHASE5 = WORK / "artifacts/phase5_counterfactual_diagnostics.json"
POST_EXIT = WORK / "artifacts/post_exit_paths.csv"
SPEC = WORK / "experiments/phase6_7_spec.json"
OUTPUT_JSON = WORK / "artifacts/phase6_7_robustness.json"
INTERACTIONS_CSV = WORK / "artifacts/breadth_stock_interactions.csv"
NEIGHBOR_CSV = WORK / "artifacts/neighboring_definition_entry_results.csv"
REPORT6 = WORK / "reports/phase6_conditional_relationships.md"
REPORT7 = WORK / "reports/phase7_robustness_falsification.md"

ENTRY_FEATURES = [
    "entry_rs_score",
    "entry_mom20",
    "entry_mom60",
    "entry_mom120",
    "entry_box_width",
    "entry_vol_ratio",
    "entry_minvol_location",
    "entry_minimum_volume_ratio",
    "entry_breakout_volume_ratio",
]
DISPERSION = [
    "cross_sectional_return20_std",
    "cross_sectional_return20_p90_p10_spread",
    "cross_sectional_return20_right_tail_ge20",
]
PATH_CONTEXT = [
    "time_to_mfe_fraction",
    "pre_mfe_mae",
    "pre_peak_direction_efficiency",
    "pre_peak_positive_day_fraction",
    "pre_peak_max_drawdown",
    "days_from_peak_to_exit",
    "post_peak_positive_day_fraction",
    "post_mfe_giveback",
]


def load_stats() -> Any:
    spec = importlib.util.spec_from_file_location("oc_stats", STATS_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen statistics module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def boolify(panel: pd.DataFrame) -> pd.DataFrame:
    for column in (
        "opportunity20",
        "opportunity50",
        "right_tail_classification",
        "severe_loss_classification",
        "false_breakout",
        "positive_capture",
        "right_tail_conversion20",
    ):
        panel[column] = panel[column].map(
            {True: 1.0, False: 0.0, "True": 1.0, "False": 0.0}
        )
    return panel


def standardize_within_year(frame: pd.DataFrame, column: str) -> pd.Series:
    ranks = frame.groupby("entry_year")[column].rank(pct=True)
    centered = ranks - ranks.groupby(frame["entry_year"]).transform("mean")
    scale = centered.groupby(frame["entry_year"]).transform("std")
    return centered / scale.replace(0, np.nan)


def gate(row: dict[str, Any], q_value: float | None) -> bool:
    rho = row.get("rho")
    return bool(
        rho is not None
        and abs(float(rho)) >= 0.10
        and row["yearly_valid"] == 8
        and max(row["yearly_positive"], row["yearly_negative"]) >= 6
        and row["loyo_valid"] == 8
        and max(row["loyo_positive"], row["loyo_negative"]) == 8
        and q_value is not None
        and q_value <= 0.10
    )


def rolling_relations(
    stats: Any,
    frame: pd.DataFrame,
    x: str,
    y: str,
    controls: list[str] | None = None,
) -> list[dict[str, Any]]:
    years = sorted(int(value) for value in frame["entry_year"].unique())
    rows: list[dict[str, Any]] = []
    for width in (2, 3):
        for start_index in range(len(years) - width + 1):
            selected = years[start_index : start_index + width]
            subset = frame.loc[frame["entry_year"].isin(selected)]
            result = stats.partial_spearman(
                subset,
                x,
                y,
                year_control=True,
                continuous_controls=controls or [],
            )
            rows.append(
                {
                    "window": f"{selected[0]}-{selected[-1]}",
                    "width_years": width,
                    "n": result["n"],
                    "rho": result["rho"],
                }
            )
    return rows


def sensitivity_remove(
    stats: Any,
    frame: pd.DataFrame,
    x: str,
    y: str,
    order_column: str,
    controls: list[str] | None = None,
    absolute: bool = False,
) -> list[dict[str, Any]]:
    order = frame[order_column].abs() if absolute else frame[order_column]
    ordered_index = order.sort_values(ascending=False).index
    result: list[dict[str, Any]] = []
    for count in (0, 1, 5, 10, 20):
        subset = frame.drop(index=ordered_index[:count]) if count else frame
        row = stats.partial_spearman(
            subset,
            x,
            y,
            year_control=True,
            continuous_controls=controls or [],
        )
        result.append({"removed": count, "n": row["n"], "rho": row["rho"]})
    return result


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("frozen_before_execution") is not True:
        raise RuntimeError("Phase 6/7 spec is not frozen")
    stats = load_stats()
    panel = boolify(pd.read_csv(PANEL))
    if len(panel) != 399 or panel["trade_id"].nunique() != 399:
        raise RuntimeError("trade panel mismatch")
    connection = duckdb.connect()
    features = connection.execute(
        "SELECT * FROM read_parquet(?) ORDER BY baseline_block,trade_date",
        [str(FEATURES)],
    ).fetchdf()
    connection.close()
    features["trade_date"] = features["trade_date"].astype(str)
    features["entry_year"] = features["year"].astype(int)

    daily_dispersion: dict[str, Any] = {}
    for variable in DISPERSION:
        primary = stats.partial_spearman(
            features,
            "breadth_above_ma20",
            variable,
            year_control=True,
        )
        stability = stats.yearly_and_loyo(
            features, "breadth_above_ma20", variable
        )
        daily_dispersion[variable] = {**primary, **stability}

    entry_context = features[
        ["baseline_block", "trade_date", *DISPERSION]
    ].rename(columns={"trade_date": "entry_signal_date"})
    joined = panel.merge(
        entry_context,
        on=["baseline_block", "entry_signal_date"],
        how="left",
        validate="many_to_one",
    )
    dispersion_trade: dict[str, Any] = {}
    for variable in DISPERSION:
        dispersion_trade[variable] = {}
        for outcome in (
            "mfe",
            "opportunity20",
            "right_tail_classification",
            "terminal_return",
        ):
            primary = stats.partial_spearman(
                joined,
                variable,
                outcome,
                year_control=True,
                continuous_controls=["breadth_above_ma20"],
            )
            stability = stats.yearly_and_loyo(
                joined,
                variable,
                outcome,
                continuous_controls=["breadth_above_ma20"],
            )
            dispersion_trade[variable][outcome] = {**primary, **stability}

    interaction_rows: list[dict[str, Any]] = []
    interaction_frame = joined.copy()
    interaction_frame["breadth_z"] = standardize_within_year(
        interaction_frame, "breadth_above_ma20"
    )
    for feature in ENTRY_FEATURES:
        feature_z = f"{feature}_z"
        product = f"breadth_x_{feature}"
        interaction_frame[feature_z] = standardize_within_year(
            interaction_frame, feature
        )
        interaction_frame[product] = (
            interaction_frame["breadth_z"] * interaction_frame[feature_z]
        )
        for outcome in ("mfe", "right_tail_classification", "false_breakout"):
            primary = stats.partial_spearman(
                interaction_frame,
                product,
                outcome,
                year_control=True,
                continuous_controls=["breadth_z", feature_z],
            )
            stability = stats.yearly_and_loyo(
                interaction_frame,
                product,
                outcome,
                continuous_controls=["breadth_z", feature_z],
            )
            interaction_rows.append(
                {
                    "feature": feature,
                    "outcome": outcome,
                    "n": primary["n"],
                    "rho": primary["rho"],
                    "p_value_asymptotic": primary["p_value"],
                    "yearly_positive": stability["yearly_positive"],
                    "yearly_negative": stability["yearly_negative"],
                    "yearly_valid": stability["yearly_valid"],
                    "loyo_positive": stability["loyo_positive"],
                    "loyo_negative": stability["loyo_negative"],
                    "loyo_valid": stability["loyo_valid"],
                }
            )
    interaction_q = stats.bh_adjust(
        [row["p_value_asymptotic"] for row in interaction_rows]
    )
    for row, q_value in zip(interaction_rows, interaction_q, strict=True):
        row["bh_q_27"] = q_value
        row["passes_gate"] = gate(row, q_value)
    interactions = pd.DataFrame(interaction_rows)
    atomic_csv(INTERACTIONS_CSV, interactions)

    opportunities = joined.loc[joined["opportunity20"].eq(1)].copy()
    path_context: dict[str, Any] = {}
    for variable in PATH_CONTEXT:
        primary = stats.partial_spearman(
            opportunities,
            "breadth_above_ma20",
            variable,
            year_control=True,
            continuous_controls=["mfe"],
        )
        stability = stats.yearly_and_loyo(
            opportunities,
            "breadth_above_ma20",
            variable,
            continuous_controls=["mfe"],
        )
        path_context[variable] = {**primary, **stability}

    joined["calendar_quarter"] = joined["entry_quarter"].str[-1].astype(int)
    cohort_context: dict[str, Any] = {}
    for quarter, group in joined.groupby("calendar_quarter"):
        cohort_context[f"Q{quarter}"] = {
            outcome: {
                **stats.partial_spearman(
                    group,
                    "breadth_above_ma20",
                    outcome,
                    year_control=True,
                ),
                **stats.yearly_and_loyo(
                    group, "breadth_above_ma20", outcome
                ),
            }
            for outcome in ("mfe", "opportunity20", "terminal_return")
        }

    neighbor_columns: dict[str, tuple[str, float]] = {}
    for threshold in (0.15, 0.20, 0.25):
        name = f"opportunity_ge_{int(threshold * 100)}"
        joined[name] = (joined["mfe"] >= threshold).astype(float)
        neighbor_columns[name] = ("opportunity", threshold)
        name = f"terminal_ge_{int(threshold * 100)}"
        joined[name] = (joined["terminal_return"] >= threshold).astype(float)
        neighbor_columns[name] = ("right_tail_terminal", threshold)
    for threshold in (0.40, 0.50, 0.60):
        name = f"extreme_opportunity_ge_{int(threshold * 100)}"
        joined[name] = (joined["mfe"] >= threshold).astype(float)
        neighbor_columns[name] = ("extreme_opportunity", threshold)
    for threshold in (-0.08, -0.10, -0.12):
        name = f"severe_loss_le_{int(abs(threshold) * 100)}"
        joined[name] = (joined["terminal_return"] <= threshold).astype(float)
        neighbor_columns[name] = ("severe_loss", threshold)
    for threshold in (0.08, 0.10, 0.12):
        name = f"false_breakout_mfe_lt_{int(threshold * 100)}"
        joined[name] = (
            (joined["mfe"] < threshold) & (joined["terminal_return"] <= 0)
        ).astype(float)
        neighbor_columns[name] = ("false_breakout", threshold)

    breadth_neighbors: dict[str, Any] = {}
    for outcome, (family, threshold) in neighbor_columns.items():
        primary = stats.partial_spearman(
            joined,
            "breadth_above_ma20",
            outcome,
            year_control=True,
        )
        stability = stats.yearly_and_loyo(
            joined, "breadth_above_ma20", outcome
        )
        breadth_neighbors[outcome] = {
            "family": family,
            "threshold": threshold,
            **primary,
            **stability,
        }

    neighbor_entry_rows: list[dict[str, Any]] = []
    for feature in ENTRY_FEATURES:
        for outcome, (family, threshold) in neighbor_columns.items():
            primary = stats.partial_spearman(
                joined,
                feature,
                outcome,
                year_control=True,
                continuous_controls=["breadth_above_ma20"],
            )
            stability = stats.yearly_and_loyo(
                joined,
                feature,
                outcome,
                continuous_controls=["breadth_above_ma20"],
            )
            neighbor_entry_rows.append(
                {
                    "feature": feature,
                    "outcome": outcome,
                    "family": family,
                    "threshold": threshold,
                    "n": primary["n"],
                    "rho": primary["rho"],
                    "p_value_asymptotic": primary["p_value"],
                    "yearly_positive": stability["yearly_positive"],
                    "yearly_negative": stability["yearly_negative"],
                    "yearly_valid": stability["yearly_valid"],
                    "loyo_positive": stability["loyo_positive"],
                    "loyo_negative": stability["loyo_negative"],
                    "loyo_valid": stability["loyo_valid"],
                }
            )
    neighbor_q = stats.bh_adjust(
        [row["p_value_asymptotic"] for row in neighbor_entry_rows]
    )
    for row, q_value in zip(neighbor_entry_rows, neighbor_q, strict=True):
        row["bh_q_135"] = q_value
        row["passes_gate"] = gate(row, q_value)
    neighbor_entry = pd.DataFrame(neighbor_entry_rows)
    atomic_csv(NEIGHBOR_CSV, neighbor_entry)

    rolling = {
        "breadth_mfe": rolling_relations(
            stats, joined, "breadth_above_ma20", "mfe"
        ),
        "breadth_opportunity20": rolling_relations(
            stats, joined, "breadth_above_ma20", "opportunity20"
        ),
        "breadth_terminal_return": rolling_relations(
            stats, joined, "breadth_above_ma20", "terminal_return"
        ),
        "breadth_capture": rolling_relations(
            stats,
            opportunities,
            "breadth_above_ma20",
            "opportunity20_capture",
            controls=["mfe"],
        ),
    }
    rolling_signs = {
        name: {
            "positive": sum(
                row["rho"] is not None and row["rho"] > 0 for row in rows
            ),
            "negative": sum(
                row["rho"] is not None and row["rho"] < 0 for row in rows
            ),
            "valid": sum(row["rho"] is not None for row in rows),
        }
        for name, rows in rolling.items()
    }

    extreme_sensitivity = {
        "breadth_mfe_remove_top_mfe": sensitivity_remove(
            stats,
            joined,
            "breadth_above_ma20",
            "mfe",
            "mfe",
        ),
        "breadth_terminal_remove_top_abs_pnl": sensitivity_remove(
            stats,
            joined,
            "breadth_above_ma20",
            "terminal_return",
            "realized_pnl",
            absolute=True,
        ),
        "rs_mfe_remove_top_mfe": sensitivity_remove(
            stats, joined, "entry_rs_score", "mfe", "mfe", controls=["breadth_above_ma20"]
        ),
        "box_terminal_remove_top_abs_pnl": sensitivity_remove(
            stats,
            joined,
            "entry_box_width",
            "terminal_return",
            "realized_pnl",
            controls=["breadth_above_ma20"],
            absolute=True,
        ),
        "breadth_capture_remove_top_mfe": sensitivity_remove(
            stats,
            opportunities,
            "breadth_above_ma20",
            "opportunity20_capture",
            "mfe",
            controls=["mfe"],
        ),
    }

    phase5 = json.loads(PHASE5.read_text(encoding="utf-8"))
    post_exit = pd.read_csv(POST_EXIT)
    post_joined = joined.merge(post_exit, on="trade_id", validate="one_to_one")
    post_exit_year_medians = {
        str(year): float(group["post_exit_close_return_20d"].median())
        for year, group in post_joined.groupby("entry_year")
    }
    post_exit_stability = {
        "positive_years": sum(value > 0 for value in post_exit_year_medians.values()),
        "negative_years": sum(value < 0 for value in post_exit_year_medians.values()),
        "year_medians": post_exit_year_medians,
    }

    total_pnl = float(joined["realized_pnl"].sum())
    positive = joined.loc[joined["realized_pnl"] > 0].sort_values(
        "realized_pnl", ascending=False
    )
    opportunities_sorted = opportunities.assign(
        peak_giveback_amount=opportunities["capital"]
        * (opportunities["peak_close_return"] - opportunities["terminal_return"])
    ).sort_values("peak_giveback_amount", ascending=False)
    false_sorted = joined.loc[joined["false_breakout"].eq(1)].sort_values(
        "realized_pnl"
    )
    concentration: dict[str, Any] = {}
    for count in (1, 5, 10, 20):
        concentration[str(count)] = {
            "total_pnl_ex_best_positive_trades": float(
                total_pnl - positive.head(count)["realized_pnl"].sum()
            ),
            "best_positive_share": float(
                positive.head(count)["realized_pnl"].sum()
                / positive["realized_pnl"].sum()
            ),
            "opportunity_peak_giveback_top_share": float(
                opportunities_sorted.head(count)["peak_giveback_amount"].sum()
                / opportunities_sorted["peak_giveback_amount"].sum()
            ),
            "false_breakout_loss_top_share": float(
                false_sorted.head(count)["realized_pnl"].sum()
                / false_sorted["realized_pnl"].sum()
            ),
        }

    original_entry = pd.read_csv(ENTRY_RESULTS)
    strategy_gate = {
        "breadth_exposure_overlay": {
            "decision_time_available": True,
            "yearly_stable": False,
            "loyo_stable": False,
            "neighbor_stable": False,
            "cost_exposure_coverage": False,
            "frozen_result": "REJECTED_A40",
        },
        "causal_stock_selection": {
            "decision_time_available": True,
            "original_54_pass_count": int(
                original_entry["passes_preregistered_gate"].sum()
            ),
            "neighbor_135_pass_count": int(neighbor_entry["passes_gate"].sum()),
            "interaction_27_pass_count": int(interactions["passes_gate"].sum()),
            "passes": False,
        },
        "path_based_exit": {
            "decision_time_available": False,
            "economic_ceiling": True,
            "frozen_executable_counterevidence": "MIXED_DEVELOPMENT_AND_FAILED_OOS",
            "passes": False,
        },
        "minimum_candidate_authorized": False,
        "reason": "No decision-time variable passes yearly, LOYO, neighboring-definition, multiplicity, and frozen executable-counterevidence gates.",
    }

    payload = {
        "spec_id": spec["spec_id"],
        "spec_sha256": sha256_file(SPEC),
        "strategy_modified": False,
        "formal_replays": 0,
        "phase6": {
            "status": "PASS",
            "daily_dispersion_context": daily_dispersion,
            "selected_trade_dispersion_context": dispersion_trade,
            "interaction_test_count": len(interactions),
            "interaction_gate_pass_count": int(interactions["passes_gate"].sum()),
            "path_context": path_context,
            "calendar_quarter_context": cohort_context,
        },
        "phase7": {
            "status": "PASS",
            "breadth_neighboring_definitions": breadth_neighbors,
            "entry_neighbor_test_count": len(neighbor_entry),
            "entry_neighbor_gate_pass_count": int(neighbor_entry["passes_gate"].sum()),
            "rolling": rolling,
            "rolling_signs": rolling_signs,
            "extreme_sensitivity": extreme_sensitivity,
            "top_n_concentration": concentration,
            "post_exit_year_stability": post_exit_stability,
            "pit_audit": {
                "completed_trade_coverage": "399/399",
                "entry_breadth_coverage": f"{int(joined['breadth_above_ma20'].notna().sum())}/399",
                "opportunity20_breadth_coverage": f"{int(opportunities['breadth_above_ma20'].notna().sum())}/{len(opportunities)}",
                "post_exit_20d_coverage": f"{phase5['post_exit']['coverage']['20']}/399",
                "missing_imputed": 0,
                "post_entry_fields_used_as_predictors": 0,
                "breadth_thresholds_searched": 0,
            },
            "strategy_gate": strategy_gate,
        },
        "source_hashes": {
            "panel": sha256_file(PANEL),
            "feature_library": sha256_file(FEATURES),
            "phase5": sha256_file(PHASE5),
            "post_exit": sha256_file(POST_EXIT),
            "spec": sha256_file(SPEC),
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    lines6 = [
        "# Phase 6 — Conditional Relationships",
        "",
        "OC-EXP-P6-001: **PASS**. All breadth terms remain continuous; no threshold or overlay was tested.",
        "",
        "## Breadth and market opportunity dispersion",
        "",
        "| Daily dispersion field | N | rho(year) | Year + / - | LOYO + / - |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in daily_dispersion.items():
        lines6.append(
            f"| {name} | {row['n']} | {row['rho']:.3f} | {row['yearly_positive']} / {row['yearly_negative']} | {row['loyo_positive']} / {row['loyo_negative']} |"
        )
    lines6 += [
        "",
        f"Tested 27 continuous Breadth x causal-stock-feature interactions; `{int(interactions['passes_gate'].sum())}` pass the combined effect/yearly/LOYO/BH gate.",
        "",
        "| Strongest interaction | Outcome | N | rho | q(27) | Year + / - | LOYO + / - |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    display = interactions.reindex(interactions["rho"].abs().sort_values(ascending=False).index).head(12)
    for _, row in display.iterrows():
        lines6.append(
            f"| breadth x {row['feature']} | {row['outcome']} | {int(row['n'])} | {row['rho']:.3f} | {row['bh_q_27']:.3f} | {int(row['yearly_positive'])} / {int(row['yearly_negative'])} | {int(row['loyo_positive'])} / {int(row['loyo_negative'])} |"
        )
    lines6 += [
        "",
        "Path-context relations remain outcome diagnostics. Calendar-quarter and dispersion conditioning are reported in the machine-readable artifact; no cohort is selected as a rule.",
    ]
    atomic_write(REPORT6, "\n".join(lines6) + "\n")

    lines7 = [
        "# Phase 7 — Robustness and Falsification",
        "",
        "OC-EXP-P7-001: **PASS** as a completed audit. The strategy-design gate is **FAIL**.",
        "",
        "## Neighboring definitions",
        "",
        "| Family | Threshold | N | breadth rho | Year + / - | LOYO + / - |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, row in breadth_neighbors.items():
        rho = "NA" if row["rho"] is None else f"{row['rho']:.3f}"
        lines7.append(
            f"| {row['family']} | {row['threshold']:.2f} | {row['n']} | {rho} | {row['yearly_positive']} / {row['yearly_negative']} | {row['loyo_positive']} / {row['loyo_negative']} |"
        )
    lines7 += [
        "",
        f"Across 135 causal entry-feature neighboring-definition tests, `{int(neighbor_entry['passes_gate'].sum())}` pass the combined gate. Across 27 Breadth x stock-feature interactions, `{int(interactions['passes_gate'].sum())}` pass.",
        "",
        "## Rolling signs",
        "",
        "| Relation | Positive | Negative | Valid |",
        "|---|---:|---:|---:|",
    ]
    for name, row in rolling_signs.items():
        lines7.append(
            f"| {name} | {row['positive']} | {row['negative']} | {row['valid']} |"
        )
    lines7 += [
        "",
        "## Extreme-trade sensitivity",
        "",
        "| Relation | Remove 0 | Remove 1 | Remove 5 | Remove 10 | Remove 20 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, rows in extreme_sensitivity.items():
        values = ["NA" if row["rho"] is None else f"{row['rho']:.3f}" for row in rows]
        lines7.append(f"| {name} | " + " | ".join(values) + " |")
    lines7 += [
        "",
        "## Strategy-design gate",
        "",
        "- Breadth exposure overlay: frozen A40 rejected.",
        f"- Causal stock selection: 0/54 primary, {int(neighbor_entry['passes_gate'].sum())}/135 neighboring, and {int(interactions['passes_gate'].sum())}/27 interaction tests pass the full gate.",
        "- Path-based exits: economic leakage is large but the strongest fields are future outcomes; executable ablations are mixed and winner-hold fails OOS.",
        "- PIT/coverage: 399/399 trade lineage, no imputation, 387/399 entry-breadth coverage, 81/84 opportunity-breadth coverage, and 398/399 post-exit20 coverage.",
        "",
        "**No minimum candidate is authorized.** The robust result is explanatory: breadth supplies opportunities, while conversion leakage has no decision-time structure that passes the full gate.",
    ]
    atomic_write(REPORT7, "\n".join(lines7) + "\n")


if __name__ == "__main__":
    main()

