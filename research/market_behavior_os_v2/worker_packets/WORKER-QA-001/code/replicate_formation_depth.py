#!/usr/bin/env python3
"""Orthogonal compact-artifact replication of the formation-depth chain.

This module deliberately does not import or invoke any primary experiment runner.
It reads only the frozen compact CSV/JSON/Markdown artifacts through 2023 and
implements rank residualization, partial correlation, and gate evaluation here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[5]
PROGRAM = ROOT / "research/market_behavior_os_v2"
TOLERANCE = 5e-12
EXPERIMENTS = ("ATTR", "PROP", "CLOSE", "PATH", "IMMED")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def median(values: Any) -> float:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def sign(value: float) -> int:
    return 0 if not np.isfinite(value) or value == 0 else (1 if value > 0 else -1)


def average_ranks(frame: pd.DataFrame) -> np.ndarray:
    # Independent local implementation entry point; pandas supplies only tie ranks.
    return frame.rank(axis=0, method="average", na_option="keep").to_numpy(float)


def ols_residual(response: np.ndarray, regressors: np.ndarray) -> np.ndarray:
    design = np.concatenate([np.ones((len(response), 1), dtype=float), regressors], axis=1)
    beta, _, _, _ = np.linalg.lstsq(design, response, rcond=None)
    return response - design @ beta


def pearson(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return float("nan")
    left_centered = left - np.mean(left)
    right_centered = right - np.mean(right)
    denominator = np.sqrt(np.sum(left_centered**2) * np.sum(right_centered**2))
    return float(np.sum(left_centered * right_centered) / denominator)


def partial_rank(
    frame: pd.DataFrame, state: str, response: str, controls: list[str]
) -> tuple[int, float]:
    valid = frame[[state, response, *controls]].dropna()
    if len(valid) <= len(controls) + 2:
        return len(valid), float("nan")
    ranks = average_ranks(valid)
    state_residual = ols_residual(ranks[:, 0], ranks[:, 2:])
    response_residual = ols_residual(ranks[:, 1], ranks[:, 2:])
    return len(valid), pearson(state_residual, response_residual)


def tail_gap(
    frame: pd.DataFrame,
    state: str,
    response: str,
    controls: list[str],
    low_maximum: float,
    high_minimum: float,
) -> tuple[int, int, int, float]:
    valid = frame[[state, response, *controls]].dropna()
    if len(valid) <= len(controls) + 2:
        return len(valid), 0, 0, float("nan")
    control_ranks = average_ranks(valid[controls])
    response_residual = ols_residual(valid[response].to_numpy(float), control_ranks)
    state_values = valid[state].to_numpy(float)
    low = response_residual[state_values <= low_maximum]
    high = response_residual[state_values >= high_minimum]
    gap = float(np.mean(high) - np.mean(low)) if len(low) and len(high) else float("nan")
    return len(valid), len(low), len(high), gap


def spearman(frame: pd.DataFrame, left: str, right: str) -> tuple[int, float]:
    valid = frame[[left, right]].dropna()
    if len(valid) < 3 or valid[left].nunique() < 2 or valid[right].nunique() < 2:
        return len(valid), float("nan")
    ranks = average_ranks(valid)
    return len(valid), pearson(ranks[:, 0], ranks[:, 1])


def adjusted_rank_r2(
    frame: pd.DataFrame, state: str, controls: list[str]
) -> tuple[int, float, float]:
    valid = frame[[state, *controls]].dropna()
    n, p = len(valid), len(controls)
    if n <= p + 2 or valid[state].nunique() < 2:
        return n, float("nan"), float("nan")
    ranks = average_ranks(valid)
    response = ranks[:, 0]
    residual = ols_residual(response, ranks[:, 1:])
    total = float(np.sum((response - np.mean(response)) ** 2))
    r2 = float(1 - np.sum(residual**2) / total)
    adjusted = float(1 - (1 - r2) * (n - 1) / (n - p - 1))
    return n, r2, adjusted


def experiment_paths(code: str) -> dict[str, Path]:
    stem = f"MKT-FORMDEPTH-{code}-001"
    report_suffix = {
        "ATTR": "attribution",
        "PROP": "topology",
        "CLOSE": "topology",
        "PATH": "timing",
        "IMMED": "timing",
    }[code]
    return {
        "spec": PROGRAM / f"experiments/{stem}_spec.json",
        "panel": PROGRAM / f"artifacts/{stem}_panel.csv",
        "audit": PROGRAM / f"artifacts/{stem}_response_audit.csv",
        "result": PROGRAM / f"artifacts/{stem}_result.json",
        "report": PROGRAM / f"reports/{stem}_{report_suffix}.md",
        "runner": PROGRAM / f"scripts/run_mkt_formdepth_{code.lower()}_001.py",
    }


def controls_for(code: str, spec: dict[str, Any]) -> list[str]:
    controls = spec["controls"]
    return controls["all_five_primary"] if code == "ATTR" else controls


def state_for(code: str, row: pd.Series, spec: dict[str, Any]) -> str:
    if code == "IMMED":
        return spec["state"]["pit"]
    return spec["state" if code != "ATTR" else "target"][str(row["coordinate"])]


def response_for(code: str, row: pd.Series) -> str:
    horizon = int(row["horizon"])
    audit_type = str(row["audit_type"])
    channel = str(row.get("channel", ""))
    if code == "ATTR":
        return f"adverse_mean_log_excursion_h{horizon}"
    if code == "PROP":
        prefix = {
            "CROSSER_DOWNSIDE": "crossing",
            "NONCROSSER_DOWNSIDE": "noncrossing",
            "CROSSER_MINUS_NONCROSSER": "paired",
        }[channel]
        if audit_type == "terminal_diagnostic":
            return f"{prefix}_terminal_log_return_h{horizon}_mean"
        return (
            f"paired_adverse_h{horizon}"
            if prefix == "paired"
            else f"{prefix}_adverse_log_excursion_h{horizon}_mean"
        )
    if code == "CLOSE":
        prefix = {
            "ACCEPTED_CROSSER_DOWNSIDE": "accepted",
            "REJECTED_CROSSER_DOWNSIDE": "rejected",
            "REJECTED_MINUS_ACCEPTED": "paired",
        }[channel]
        if audit_type == "terminal_diagnostic":
            return f"{prefix}_terminal_log_return_h{horizon}_mean"
        return (
            f"paired_adverse_h{horizon}"
            if prefix == "paired"
            else f"{prefix}_adverse_log_excursion_h{horizon}_mean"
        )
    if code == "PATH":
        if audit_type == "terminal_diagnostic":
            return f"crossing_terminal_log_return_h{horizon}_mean"
        component = {
            "PREOPEN_PATH_DOWNSIDE": "preopen_path_to_trough",
            "TROUGH_SESSION_INTRADAY_DOWNSIDE": "trough_session_intraday",
            "POST_TROUGH_RECOVERY_DIAGNOSTIC": "post_trough_recovery",
        }[channel]
        prefix = str(row["closing_arm"]) if audit_type == "arm_robustness" else "crossing"
        return f"{prefix}_{component}_h{horizon}_mean"
    if code == "IMMED":
        if str(row["scope"]) == "arm_robustness":
            return f"{row['closing_arm']}_first_trough_share_h3"
        return f"crossing_first_trough_share_h{horizon}"
    raise AssertionError(code)


def scoped_frame(panel: pd.DataFrame, row: pd.Series, spec: dict[str, Any]) -> pd.DataFrame:
    frame = panel[
        (panel["market_view"] == row["market_view"]) & (panel["denominator"] == row["denominator"])
    ]
    scope = str(row["scope"])
    scope_value = str(row["scope_value"])
    scopes = spec.get("scopes", {})
    blocks = scopes.get("blocks", spec.get("geometry_gates", {}).get("blocks", {}))
    supported_years = scopes.get(
        "pit_supported_years",
        spec.get("response_gates", {}).get("pit_supported_years", []),
    )
    if scope == "block":
        frame = frame[frame["event_year"].isin(blocks[scope_value])]
    elif scope == "year":
        frame = frame[frame["event_year"] == int(scope_value)]
    elif scope == "leave_one_year_out":
        years = [year for year in supported_years if year != int(scope_value)]
        frame = frame[frame["event_year"].isin(years)]
    elif scope == "phase":
        horizon = int(row["horizon"])
        frame = frame[frame["session_ordinal"] % horizon == int(scope_value)]
    return frame.sort_values("trade_date")


def reconstruct_response_audit(
    code: str, panel: pd.DataFrame, audit: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    controls = controls_for(code, spec)
    rows: list[dict[str, Any]] = []
    maximum_error = 0.0
    mismatch_count = 0
    manual_cases: list[dict[str, Any]] = []
    for index, authoritative in audit.iterrows():
        frame = scoped_frame(panel, authoritative, spec)
        state = state_for(code, authoritative, spec)
        response = response_for(code, authoritative)
        if str(authoritative["audit_type"]) == "tail_residual_gap":
            n, low_n, high_n, value = tail_gap(
                frame,
                state,
                response,
                controls,
                spec["state" if code != "ATTR" else "target"]["pit_low_maximum"],
                spec["state" if code != "ATTR" else "target"]["pit_high_minimum"],
            )
            expected = float(authoritative["tail_residual_gap"])
            count_match = n == int(authoritative["n"])
            count_match &= low_n == int(authoritative["low_n"])
            count_match &= high_n == int(authoritative["high_n"])
        else:
            n, value = partial_rank(frame, state, response, controls)
            expected = float(authoritative["partial_rho"])
            count_match = n == int(authoritative["n"])
        error = abs(value - expected) if np.isfinite(value) and np.isfinite(expected) else 0.0
        passed = bool(count_match and error <= TOLERANCE)
        mismatch_count += int(not passed)
        maximum_error = max(maximum_error, error)
        rows.append(
            {
                "source_row": int(index),
                "audit_type": str(authoritative["audit_type"]),
                "channel": None
                if "channel" not in authoritative
                else str(authoritative["channel"]),
                "scope": str(authoritative["scope"]),
                "scope_value": str(authoritative["scope_value"]),
                "market_view": str(authoritative["market_view"]),
                "denominator": str(authoritative["denominator"]),
                "coordinate": str(authoritative.get("coordinate", "pit")),
                "horizon": int(authoritative["horizon"]),
                "closing_arm": (
                    None
                    if pd.isna(authoritative.get("closing_arm", np.nan))
                    else str(authoritative["closing_arm"])
                ),
                "n": n,
                "independent_value": value,
                "authoritative_value": expected,
                "absolute_error": error,
                "pass": passed,
            }
        )
        if (
            len(manual_cases) == 0
            and str(authoritative["audit_type"]) in {"partial_rank", "arm_robustness"}
            and str(authoritative["scope"]) == "cell"
            and int(authoritative["horizon"]) == 3
            and str(authoritative.get("coordinate", "pit")) == "pit"
        ):
            manual_cases.append(rows[-1].copy())
    return pd.DataFrame(rows), {
        "rows_reconstructed": len(rows),
        "mismatch_count": mismatch_count,
        "maximum_absolute_error": maximum_error,
        "selected_scalar_case": manual_cases[0],
    }


def reconstruct_attr_geometry(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    path = PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_geometry_audit.csv"
    authoritative = pd.read_csv(path)
    controls = spec["controls"]
    pairwise = {
        "original_discovery": controls["original_discovery"],
        "original_volatility": controls["original_volatility"],
        "central_direction": controls["central_direction"],
        "open_close_return": controls["open_close_return"],
        "intraday_range": controls["intraday_range"],
    }
    maximum_error = 0.0
    mismatches = 0
    for _, row in authoritative.iterrows():
        frame = panel[
            (panel["market_view"] == row["market_view"])
            & (panel["denominator"] == row["denominator"])
        ]
        if row["scope"] == "block":
            frame = frame[
                frame["event_year"].isin(spec["geometry_gates"]["blocks"][row["scope_value"]])
            ]
        state = spec["target"][row["coordinate"]]
        if row["audit_type"] == "pairwise":
            control = pairwise[row["control_role"]]
            if row["coordinate"] == "pit" and row["control_role"] == "central_direction":
                control = controls["central_direction_pit"]
            n, value = spearman(frame, state, control)
            expected = float(row["spearman"])
        else:
            n, _, value = adjusted_rank_r2(frame, state, controls["all_five_primary"])
            expected = float(row["adjusted_r2"])
        error = abs(value - expected)
        passed = n == int(row["n"]) and error <= TOLERANCE
        mismatches += int(not passed)
        maximum_error = max(maximum_error, error)
    return {
        "rows_reconstructed": len(authoritative),
        "mismatch_count": mismatches,
        "maximum_absolute_error": maximum_error,
        "sha256": sha256(path),
    }


def summarize_channel(
    independent: pd.DataFrame, channel: str, include_arms: bool = False
) -> dict[str, Any]:
    rows = independent[independent["channel"] == channel]
    partial = rows[(rows["audit_type"] == "partial_rank") & (rows["coordinate"] == "pit")]
    primary = partial[(partial["scope"] == "cell") & (partial["horizon"] == 3)]
    result: dict[str, Any] = {
        "median_h3_partial_rho": median(primary["independent_value"]),
        "negative_cells": int((primary["independent_value"] < 0).sum()),
        "neighbor_median_partial_rho": {
            str(horizon): median(
                partial[(partial["scope"] == "cell") & (partial["horizon"] == horizon)][
                    "independent_value"
                ]
            )
            for horizon in (1, 5)
        },
        "block_median_partial_rho": {
            block: median(
                partial[(partial["scope"] == "block") & (partial["scope_value"] == block)][
                    "independent_value"
                ]
            )
            for block in ("A", "B")
        },
        "year_median_partial_rho": {
            str(year): median(
                partial[(partial["scope"] == "year") & (partial["scope_value"] == str(year))][
                    "independent_value"
                ]
            )
            for year in (2020, 2021, 2022, 2023)
        },
        "leave_one_year_out_median_partial_rho": {
            str(year): median(
                partial[
                    (partial["scope"] == "leave_one_year_out")
                    & (partial["scope_value"] == str(year))
                ]["independent_value"]
            )
            for year in (2020, 2021, 2022, 2023)
        },
        "phase_signs": {
            str(horizon): [
                sign(
                    median(
                        partial[
                            (partial["scope"] == "phase")
                            & (partial["horizon"] == horizon)
                            & (partial["scope_value"] == str(phase))
                        ]["independent_value"]
                    )
                )
                for phase in range(horizon)
            ]
            for horizon in (3, 5)
        },
        "median_tail_residual_gap": median(
            rows[rows["audit_type"] == "tail_residual_gap"]["independent_value"]
        ),
    }
    if include_arms:
        result["closing_arm_h3_median_partial_rho"] = {
            arm: median(
                rows[(rows["audit_type"] == "arm_robustness") & (rows["closing_arm"] == arm)][
                    "independent_value"
                ]
            )
            for arm in ("accepted", "rejected")
        }
    return result


def negative_channel_pass(
    summary: dict[str, Any], gate: dict[str, Any], arms: bool = False
) -> bool:
    checks = [
        summary["median_h3_partial_rho"] <= gate["maximum_median_h3_partial_rho"],
        summary["negative_cells"] >= gate["minimum_negative_cells"],
        all(
            value <= gate["maximum_each_block_partial_rho"]
            for value in summary["block_median_partial_rho"].values()
        ),
        all(value < 0 for value in summary["year_median_partial_rho"].values()),
        all(value < 0 for value in summary["leave_one_year_out_median_partial_rho"].values()),
        all(value < 0 for value in summary["neighbor_median_partial_rho"].values()),
        sum(value < 0 for value in summary["phase_signs"]["3"])
        >= gate["minimum_negative_h3_phases"],
        sum(value < 0 for value in summary["phase_signs"]["5"])
        >= gate["minimum_negative_h5_phases"],
        summary["median_tail_residual_gap"] <= gate["maximum_median_tail_residual_gap"],
    ]
    if arms:
        checks.append(
            all(value < 0 for value in summary["closing_arm_h3_median_partial_rho"].values())
        )
    return all(checks)


def paired_pass(summary: dict[str, Any], gate: dict[str, Any]) -> bool:
    return all(
        [
            summary["median_h3_partial_rho"] <= gate["maximum_median_h3_partial_rho"],
            summary["negative_cells"] >= gate["minimum_negative_cells"],
            all(value < 0 for value in summary["block_median_partial_rho"].values()),
            all(value <= 0 for value in summary["neighbor_median_partial_rho"].values()),
            summary["median_tail_residual_gap"] <= gate["maximum_median_tail_residual_gap"],
        ]
    )


def key_evaluation(
    code: str,
    independent: pd.DataFrame,
    panel: pd.DataFrame,
    spec: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if code == "ATTR":
        primary = independent[
            (independent["audit_type"] == "partial_rank")
            & (independent["scope"] == "cell")
            & (independent["horizon"] == 3)
        ]
        # The filtered rows contain absolute and PIT entries. Preserve PIT using the
        # source audit coordinate rather than relying on row order.
        source = pd.read_csv(experiment_paths(code)["audit"])
        pit_rows = source.index[
            (source["audit_type"] == "partial_rank")
            & (source["scope"] == "cell")
            & (source["coordinate"] == "pit")
            & (source["horizon"] == 3)
        ]
        primary = independent[independent["source_row"].isin(pit_rows)]

        def values_for(scope: str, scope_value: str | None = None, horizon: int = 3) -> pd.Series:
            idx = source.index[
                (source["audit_type"] == "partial_rank")
                & (source["scope"] == scope)
                & (source["coordinate"] == "pit")
                & (source["horizon"] == horizon)
            ]
            if scope_value is not None:
                idx = idx[source.loc[idx, "scope_value"].astype(str) == scope_value]
            return independent[independent["source_row"].isin(idx)]["independent_value"]

        summary = {
            "median_h3_partial_rho": median(primary["independent_value"]),
            "same_sign_cells": int((primary["independent_value"] < 0).sum()),
            "neighbor_median_partial_rho": {
                str(h): median(values_for("cell", horizon=h)) for h in (1, 5)
            },
            "block_median_partial_rho": {b: median(values_for("block", b)) for b in ("A", "B")},
            "year_median_partial_rho": {
                str(y): median(values_for("year", str(y))) for y in (2020, 2021, 2022, 2023)
            },
            "leave_one_year_out_median_partial_rho": {
                str(y): median(values_for("leave_one_year_out", str(y)))
                for y in (2020, 2021, 2022, 2023)
            },
            "phase_signs": {
                str(h): [sign(median(values_for("phase", str(p), h))) for p in range(h)]
                for h in (3, 5)
            },
            "median_tail_residual_gap": median(
                independent[independent["audit_type"] == "tail_residual_gap"]["independent_value"]
            ),
        }
        gate = spec["response_gates"]
        response_pass = all(
            [
                summary["median_h3_partial_rho"] <= -gate["minimum_absolute_median_h3_partial_rho"],
                summary["same_sign_cells"] >= gate["minimum_same_sign_cells"],
                all(
                    value <= -gate["minimum_absolute_block_partial_rho"]
                    for value in summary["block_median_partial_rho"].values()
                ),
                all(value < 0 for value in summary["year_median_partial_rho"].values()),
                all(
                    value < 0 for value in summary["leave_one_year_out_median_partial_rho"].values()
                ),
                all(value < 0 for value in summary["neighbor_median_partial_rho"].values()),
                sum(value < 0 for value in summary["phase_signs"]["3"])
                >= gate["h3_phase_same_sign_minimum"],
                sum(value < 0 for value in summary["phase_signs"]["5"])
                >= gate["h5_phase_same_sign_minimum"],
                summary["median_tail_residual_gap"] <= gate["maximum_median_tail_residual_gap"],
            ]
        )
        geometry_file = pd.read_csv(PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_geometry_audit.csv")
        geometry_pass = (
            geometry_file[
                (geometry_file["audit_type"] == "pairwise") & (geometry_file["scope"] == "cell")
            ]["spearman"]
            .abs()
            .max()
            < spec["geometry_gates"]["maximum_absolute_pairwise_spearman"]
            and median(
                geometry_file[
                    (geometry_file["audit_type"] == "joint_rank_regression")
                    & (geometry_file["scope"] == "cell")
                ]["adjusted_r2"]
            )
            <= spec["geometry_gates"]["maximum_median_joint_adjusted_rank_r2"]
        )
        classification = (
            spec["classification"]["pass"]
            if response_pass and geometry_pass
            else spec["classification"]["response_fail" if not response_pass else "directness_fail"]
        )
        return {
            "response": summary,
            "response_pass": response_pass,
            "geometry_pass": geometry_pass,
        }, classification

    if code in {"PROP", "CLOSE"}:
        channels = (
            ("CROSSER_DOWNSIDE", "NONCROSSER_DOWNSIDE", "CROSSER_MINUS_NONCROSSER")
            if code == "PROP"
            else (
                "ACCEPTED_CROSSER_DOWNSIDE",
                "REJECTED_CROSSER_DOWNSIDE",
                "REJECTED_MINUS_ACCEPTED",
            )
        )
        summaries = {channel: summarize_channel(independent, channel) for channel in channels}
        first = negative_channel_pass(summaries[channels[0]], spec["arm_channel_gates"])
        second = negative_channel_pass(summaries[channels[1]], spec["arm_channel_gates"])
        paired = paired_pass(summaries[channels[2]], spec["paired_localization_gates"])
        if code == "PROP":
            classification = (
                "CROSSER_AND_NONCROSSER_DOWNSIDE_PROPAGATION"
                if first and second
                else "LOCALIZED_CROSSER_DOWNSIDE_TOPOLOGY"
                if first and paired and not second
                else "NONCROSSER_DOWNSIDE_PROPAGATION_ONLY"
                if second and not first
                else "CROSSER_CHANNEL_WITHOUT_LOCALIZATION"
                if first
                else "AGGREGATE_RESPONSE_NOT_MEMBERSHIP_RESOLVED"
            )
        else:
            classification = (
                "ACCEPTED_AND_REJECTED_CROSSER_DOWNSIDE"
                if first and second
                else "CLOSING_REJECTION_LOCALIZED_DOWNSIDE"
                if second and paired and not first
                else "CLOSING_ACCEPTANCE_DOWNSIDE_ONLY"
                if first and not second
                else "REJECTED_CHANNEL_WITHOUT_CLOSING_LOCALIZATION"
                if second
                else "CROSSER_DOWNSIDE_NOT_CLOSING_STATE_RESOLVED"
            )
        return {
            "channels": summaries,
            "passes": {channels[0]: first, channels[1]: second, channels[2]: paired},
        }, classification

    if code == "PATH":
        channels = (
            "PREOPEN_PATH_DOWNSIDE",
            "TROUGH_SESSION_INTRADAY_DOWNSIDE",
            "POST_TROUGH_RECOVERY_DIAGNOSTIC",
        )
        summaries = {
            channel: summarize_channel(independent, channel, include_arms=channel != channels[2])
            for channel in channels
        }
        preopen = negative_channel_pass(summaries[channels[0]], spec["component_gates"], arms=True)
        intraday = negative_channel_pass(summaries[channels[1]], spec["component_gates"], arms=True)
        classification = (
            "MIXED_PREOPEN_AND_INTRADAY_DOWNSIDE_PATH"
            if preopen and intraday
            else "PREOPEN_PATH_LOCALIZED_DOWNSIDE"
            if preopen
            else "TROUGH_SESSION_INTRADAY_LOCALIZED_DOWNSIDE"
            if intraday
            else "ADVERSE_PATH_TIMING_NOT_RESOLVED"
        )
        return {
            "channels": summaries,
            "passes": {channels[0]: preopen, channels[1]: intraday},
        }, classification

    # IMMED has no channel column and a two-sided direction chosen from the h3 median.
    primary = independent[
        (independent["audit_type"] == "partial_rank")
        & (independent["scope"] == "cell")
        & (independent["horizon"] == 3)
    ]
    direction = sign(median(primary["independent_value"]))

    def scoped(scope: str, value: str | None = None, horizon: int = 3) -> pd.Series:
        rows = independent[
            (independent["audit_type"] == "partial_rank")
            & (independent["scope"] == scope)
            & (independent["horizon"] == horizon)
        ]
        if value is not None:
            rows = rows[rows["scope_value"] == value]
        return rows["independent_value"]

    summary = {
        "median_h3_partial_rho": median(primary["independent_value"]),
        "h5_median_partial_rho": median(scoped("cell", horizon=5)),
        "direction": direction,
        "same_direction_cells": int(
            sum(sign(value) == direction for value in primary["independent_value"])
        ),
        "block_median_partial_rho": {b: median(scoped("block", b)) for b in ("A", "B")},
        "year_median_partial_rho": {
            str(y): median(scoped("year", str(y))) for y in (2020, 2021, 2022, 2023)
        },
        "leave_one_year_out_median_partial_rho": {
            str(y): median(scoped("leave_one_year_out", str(y))) for y in (2020, 2021, 2022, 2023)
        },
        "phase_signs": {
            str(h): [sign(median(scoped("phase", str(p), h))) for p in range(h)] for h in (3, 5)
        },
        "closing_arm_h3_median_partial_rho": {
            arm: median(scoped("arm_robustness", arm)) for arm in ("accepted", "rejected")
        },
        "median_tail_residual_gap": median(
            independent[independent["audit_type"] == "tail_residual_gap"]["independent_value"]
        ),
    }
    gate = spec["two_sided_gates"]
    passed = direction != 0 and all(
        [
            abs(summary["median_h3_partial_rho"]) >= gate["minimum_absolute_median_h3_partial_rho"],
            summary["same_direction_cells"] >= gate["minimum_same_direction_cells"],
            all(
                abs(value) >= gate["minimum_absolute_each_block_partial_rho"]
                and sign(value) == direction
                for value in summary["block_median_partial_rho"].values()
            ),
            all(sign(value) == direction for value in summary["year_median_partial_rho"].values()),
            all(
                sign(value) == direction
                for value in summary["leave_one_year_out_median_partial_rho"].values()
            ),
            abs(summary["h5_median_partial_rho"]) >= gate["minimum_absolute_h5_partial_rho"]
            and sign(summary["h5_median_partial_rho"]) == direction,
            sum(value == direction for value in summary["phase_signs"]["3"])
            >= gate["minimum_same_direction_h3_phases"],
            sum(value == direction for value in summary["phase_signs"]["5"])
            >= gate["minimum_same_direction_h5_phases"],
            abs(summary["median_tail_residual_gap"]) >= gate["minimum_absolute_tail_residual_gap"]
            and sign(summary["median_tail_residual_gap"]) == direction,
            all(
                sign(value) == direction
                for value in summary["closing_arm_h3_median_partial_rho"].values()
            ),
        ]
    )
    classification = (
        (
            "EARLIER_TROUGH_WITH_FORMATION_DEPTH"
            if direction > 0
            else "LATER_TROUGH_WITH_FORMATION_DEPTH"
        )
        if passed
        else "NO_STABLE_TROUGH_IMMEDIACY_SHIFT"
    )
    return {"summary": summary, "pass": passed}, classification


def compare_selected(computed: dict[str, Any], authoritative: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def walk(left: Any, right: Any, path: str) -> None:
        if isinstance(left, dict):
            for key, value in left.items():
                if key in right:
                    walk(value, right[key], f"{path}.{key}" if path else key)
        elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
            error = abs(float(left) - float(right))
            checks.append({"path": path, "absolute_error": error, "pass": error <= TOLERANCE})
        elif isinstance(left, list) and isinstance(right, list):
            checks.append({"path": path, "pass": left == right})

    walk(computed, authoritative, "")
    return {"checks": checks, "mismatch_count": sum(not item["pass"] for item in checks)}


def audit_hashes(
    paths: dict[str, Path],
    spec: dict[str, Any],
    result: dict[str, Any],
    lineage_root: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for name, binding in spec["inputs"].items():
        path = resolve(binding["path"])
        physical_root = "worker_worktree"
        if not path.is_file() and not Path(binding["path"]).is_absolute():
            path = lineage_root / binding["path"]
            physical_root = "director_artifact_store"
        actual = sha256(path)
        rows.append(
            {
                "role": f"spec_input:{name}",
                "path": binding["path"],
                "physical_root": physical_root,
                "expected": binding["sha256"],
                "actual": actual,
                "pass": actual == binding["sha256"],
            }
        )
    result_bindings = {
        "spec_sha256": paths["spec"],
        "panel_sha256": paths["panel"],
        "response_audit_sha256": paths["audit"],
        "runner_sha256": paths["runner"],
    }
    if "map_sha256" in result["hashes"]:
        result_bindings["map_sha256"] = resolve(spec["inputs"]["attribution_map"]["path"])
    if "geometry_audit_sha256" in result["hashes"]:
        result_bindings["geometry_audit_sha256"] = (
            PROGRAM / "artifacts/MKT-FORMDEPTH-ATTR-001_geometry_audit.csv"
        )
    for role, path in result_bindings.items():
        actual = sha256(path)
        expected = result["hashes"][role]
        rows.append(
            {
                "role": f"result_binding:{role}",
                "path": str(path.relative_to(ROOT)),
                "expected": expected,
                "actual": actual,
                "pass": actual == expected,
            }
        )
    rows.extend(
        [
            {
                "role": "result_file",
                "path": str(paths["result"].relative_to(ROOT)),
                "actual": sha256(paths["result"]),
                "pass": True,
            },
            {
                "role": "report_file",
                "path": str(paths["report"].relative_to(ROOT)),
                "actual": sha256(paths["report"]),
                "pass": True,
            },
        ]
    )
    return {"rows": rows, "mismatch_count": sum(not row["pass"] for row in rows)}


def clock_and_support(panel: pd.DataFrame, result: dict[str, Any]) -> dict[str, Any]:
    clocks = pd.to_datetime(panel["available_at"], errors="coerce")
    exact_clock = bool(
        clocks.notna().all()
        and ((clocks.dt.hour == 15) & (clocks.dt.minute == 30) & (clocks.dt.second == 0)).all()
    )
    unique_keys = not panel[["trade_date", "market_view", "denominator"]].duplicated().any()
    max_year = int(panel["event_year"].max())
    groups = int(panel[["market_view", "denominator"]].drop_duplicates().shape[0])
    return {
        "exact_1530_available_at": exact_clock,
        "response_begins_next_exchange_session": result["response_begins"]
        == "next exchange session",
        "joint_information_clock_1530": result["joint_information_clock"] == "15:30 Asia/Shanghai",
        "unique_date_view_denominator_key": unique_keys,
        "maximum_event_year": max_year,
        "post_2023_absent": max_year <= 2023,
        "groups": groups,
        "eight_groups": groups == 8,
    }


def run(output_dir: Path, lineage_root: Path | None = None) -> dict[str, Any]:
    lineage_root = lineage_root or ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    final: dict[str, Any] = {
        "worker_id": "WORKER-QA-001",
        "base_commit": "fc665b016e2df01e11047a64e88f53905ccdcfdf",
        "method": (
            "independent compact-panel rank residualization; "
            "no primary runner import or invocation"
        ),
        "tolerance": TOLERANCE,
        "prohibited_data_read": {
            "raw_qd004": False,
            "cy008": False,
            "cy011": False,
            "post_2023": False,
            "strategy_outcomes": False,
        },
        "experiments": {},
    }
    global_pass = True
    for code in EXPERIMENTS:
        paths = experiment_paths(code)
        spec = json.loads(paths["spec"].read_text())
        result = json.loads(paths["result"].read_text())
        panel = pd.read_csv(paths["panel"], parse_dates=["trade_date"])
        audit = pd.read_csv(paths["audit"])
        independent, replay = reconstruct_response_audit(code, panel, audit, spec)
        independent.to_csv(
            output_dir / f"{code.lower()}_independent_audit.csv",
            index=False,
            float_format="%.17g",
            lineterminator="\n",
        )
        computed, classification = key_evaluation(code, independent, panel, spec)
        comparison = compare_selected(computed, result["evaluation"])
        hashes = audit_hashes(paths, spec, result, lineage_root)
        clock = clock_and_support(panel, result)
        geometry = reconstruct_attr_geometry(panel, spec) if code == "ATTR" else None
        passed = all(
            [
                replay["mismatch_count"] == 0,
                comparison["mismatch_count"] == 0,
                hashes["mismatch_count"] == 0,
                classification == result["classification"],
                all(value for key, value in clock.items() if isinstance(value, bool)),
                geometry is None or geometry["mismatch_count"] == 0,
            ]
        )
        global_pass &= passed
        final["experiments"][code] = {
            "pass": passed,
            "authoritative_classification": result["classification"],
            "independent_classification": classification,
            "response_replay": replay,
            "aggregate_comparison": comparison,
            "hash_audit": hashes,
            "clock_and_support": clock,
            "geometry_replay": geometry,
            "independent_key_evaluation": computed,
        }
    final["status"] = "PASS_ORTHOGONAL_REPLICATION" if global_pass else "QUARANTINE_DISAGREEMENT"
    final["conclusion"] = (
        "The accepted formation-depth chain is independently reproduced from "
        "compact bound artifacts."
        if global_pass
        else "At least one independent replay disagrees; quarantine the formation-depth chain."
    )
    (output_dir / "result.json").write_text(
        json.dumps(clean(final), indent=2, sort_keys=True) + "\n"
    )
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lineage-root", type=Path, default=ROOT)
    parser.add_argument("--canonical-result", type=Path)
    args = parser.parse_args()
    result = run(args.output_dir.resolve(), args.lineage_root.resolve())
    if args.canonical_result is not None:
        args.canonical_result.resolve().write_bytes(
            (args.output_dir.resolve() / "result.json").read_bytes()
        )
    print(
        json.dumps(
            {
                "status": result["status"],
                "experiments": {key: value["pass"] for key, value in result["experiments"].items()},
            },
            sort_keys=True,
        )
    )
    raise SystemExit(0 if result["status"] == "PASS_ORTHOGONAL_REPLICATION" else 2)


if __name__ == "__main__":
    main()
