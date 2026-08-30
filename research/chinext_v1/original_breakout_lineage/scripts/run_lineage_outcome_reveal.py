#!/usr/bin/env python3
"""Execute EXP-OBL-004 against the immutable outcome-blind lineage freeze."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.stats import kruskal, pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
REGIME = ROOT / "research/chinext_v1/regime_attribution"

SPEC = WORK / "experiments/EXP-OBL-004_spec.json"
ASSIGNMENTS = WORK / "artifacts/lineage_assignments_v3.csv"
FEATURES = WORK / "artifacts/formation_features_v3.csv"
FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-003.json"
OUTCOMES = REGIME / "artifacts/trade_mechanism_attribution.csv"
CONTROLS = REGIME / "artifacts/pre_entry_transitions.csv"
TRADES = REGIME / "artifacts/yearly_trades.csv"

OUTPUT_TABLE = WORK / "artifacts/lineage_outcome_reveal.csv"
OUTPUT_JSON = WORK / "artifacts/EXP-OBL-004_result.json"
REPORT = WORK / "reports/EXP-OBL-004_lineage_outcome_reveal.md"
EVIDENCE_PACKET = WORK / "reports/EXP-OBL-004_evidence_packet.md"

CONTROL_COLUMNS = (
    "entry_rs_score",
    "entry_mom20",
    "entry_box_width",
    "entry_minvol_location",
    "entry_breakout_volume_ratio",
    "index_return_20d",
    "index_realized_vol20",
    "breadth_composite",
    "entry_beta60",
    "entry_log_amount20",
)
PRIMARY_ENDPOINTS = ("mfe", "non_false_breakout")
LINEAGE_STRENGTH = {
    "L00_BASE_LOW_ACCEPTANCE_LOW": 0.0,
    "L01_BASE_LOW_ACCEPTANCE_HIGH": 1.0,
    "L10_BASE_HIGH_ACCEPTANCE_LOW": 1.0,
    "L11_BASE_HIGH_ACCEPTANCE_HIGH": 2.0,
}
BASE_HIGH = {
    "L00_BASE_LOW_ACCEPTANCE_LOW": 0.0,
    "L01_BASE_LOW_ACCEPTANCE_HIGH": 0.0,
    "L10_BASE_HIGH_ACCEPTANCE_LOW": 1.0,
    "L11_BASE_HIGH_ACCEPTANCE_HIGH": 1.0,
}
ACCEPTANCE_HIGH = {
    "L00_BASE_LOW_ACCEPTANCE_LOW": 0.0,
    "L01_BASE_LOW_ACCEPTANCE_HIGH": 1.0,
    "L10_BASE_HIGH_ACCEPTANCE_LOW": 0.0,
    "L11_BASE_HIGH_ACCEPTANCE_HIGH": 1.0,
}


class OutcomeRevealError(RuntimeError):
    """Raised when the freeze, join, sample, or scientific contract fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False, float_format="%.12g", lineterminator="\n")
    os.replace(temporary, path)


def clean_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-004":
        raise OutcomeRevealError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_OUTCOME_JOIN":
        raise OutcomeRevealError("outcome reveal is not frozen")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise OutcomeRevealError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise OutcomeRevealError(f"frozen input mismatch: {mismatches}")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze.get("lineage_freeze_id") != "LINEAGE-OBL-003-4193834A6A3A39BF":
        raise OutcomeRevealError("lineage freeze identity changed")
    if freeze.get("outcome_access_before_freeze") is not False:
        raise OutcomeRevealError("lineage freeze outcome boundary changed")
    if freeze.get("assignment_table_sha256") != sha256_file(ASSIGNMENTS):
        raise OutcomeRevealError("assignment table no longer matches freeze")
    return spec, identities


def rank_series(series: pd.Series) -> pd.Series:
    return series.rank(method="average")


def association(frame: pd.DataFrame, x: str, y: str) -> dict[str, Any]:
    sample = frame[[x, y]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sample) < 8 or sample[x].nunique() < 2 or sample[y].nunique() < 2:
        return {"n": len(sample), "rho": None, "pvalue": None}
    result = spearmanr(sample[x], sample[y])
    return {
        "n": len(sample),
        "rho": float(result.statistic),
        "pvalue": float(result.pvalue),
    }


def partial_rank(
    frame: pd.DataFrame,
    x: str,
    y: str,
    controls: Iterable[str],
) -> dict[str, Any]:
    control_list = list(controls)
    columns = [x, y, *control_list]
    sample = frame[columns].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sample) < len(control_list) + 10 or sample[x].nunique() < 2 or sample[y].nunique() < 2:
        return {"n": len(sample), "partial_rank_rho": None, "pvalue": None}
    ranked = sample.apply(rank_series)
    design = np.column_stack(
        [np.ones(len(ranked)), ranked[control_list].to_numpy(float)]
    )
    x_values = ranked[x].to_numpy(float)
    y_values = ranked[y].to_numpy(float)
    x_resid = x_values - design @ np.linalg.lstsq(design, x_values, rcond=None)[0]
    y_resid = y_values - design @ np.linalg.lstsq(design, y_values, rcond=None)[0]
    if np.std(x_resid) < 1e-10 or np.std(y_resid) < 1e-10:
        return {"n": len(sample), "partial_rank_rho": None, "pvalue": None}
    result = pearsonr(x_resid, y_resid)
    return {
        "n": len(sample),
        "partial_rank_rho": float(result.statistic),
        "pvalue": float(result.pvalue),
    }


def add_year_dummies(frame: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    dummies = pd.get_dummies(
        frame.entry_year.astype(int), prefix="year", drop_first=True, dtype=float
    )
    result = pd.concat(
        [frame.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1
    )
    return result, tuple(dummies.columns)


def loyo(
    frame: pd.DataFrame,
    x: str,
    y: str,
    controls: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    values: dict[str, float | None] = {}
    for year in sorted(frame.entry_year.astype(int).unique()):
        sample = frame[frame.entry_year != year].copy()
        if controls is None:
            estimate = association(sample, x, y)["rho"]
        else:
            sample, year_columns = add_year_dummies(sample)
            estimate = partial_rank(sample, x, y, (*controls, *year_columns))[
                "partial_rank_rho"
            ]
        values[str(year)] = estimate
    finite = [value for value in values.values() if value is not None]
    return {
        "values": values,
        "positive": sum(value > 0 for value in finite),
        "total": len(finite),
        "minimum": min(finite) if finite else None,
        "maximum": max(finite) if finite else None,
    }


def benjamini_hochberg(pvalues: dict[str, float]) -> dict[str, float]:
    ordered = sorted(pvalues.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank, (name, value) in reversed(list(enumerate(ordered, 1))):
        running = min(running, value * count / rank)
        adjusted[name] = min(1.0, running)
    return adjusted


def leave_group_out(frame: pd.DataFrame, group: str, x: str, y: str) -> dict[str, Any]:
    estimates: list[float] = []
    for _, omitted in frame.groupby(group, sort=True):
        estimate = association(frame.drop(omitted.index), x, y)["rho"]
        if estimate is not None:
            estimates.append(float(estimate))
    return {
        "groups": len(estimates),
        "positive_fraction": float(np.mean(np.asarray(estimates) > 0)) if estimates else None,
        "minimum": min(estimates) if estimates else None,
        "maximum": max(estimates) if estimates else None,
    }


def load_analysis_frame() -> pd.DataFrame:
    assignments = pd.read_csv(ASSIGNMENTS)
    if len(assignments) != 399 or assignments.trade_id.nunique() != 399:
        raise OutcomeRevealError("assignment input is not 399 unique events")
    if set(assignments.lineage_id) != set(LINEAGE_STRENGTH):
        raise OutcomeRevealError("frozen lineage IDs changed")
    assignments["lineage_strength"] = assignments.lineage_id.map(LINEAGE_STRENGTH)
    assignments["base_high"] = assignments.lineage_id.map(BASE_HIGH)
    assignments["acceptance_high"] = assignments.lineage_id.map(ACCEPTANCE_HIGH)
    assignments["neighbor_lineage_strength"] = assignments.neighbor_lineage_id.map(
        LINEAGE_STRENGTH
    )

    outcomes = pd.read_csv(
        OUTCOMES,
        usecols=[
            "trade_id",
            "mfe",
            "round_trip_return",
            "realized_pnl",
            "opportunity20",
            "false_breakout",
            "severe_loss",
        ],
    )
    controls = pd.read_csv(
        CONTROLS,
        usecols=["trade_id", "entry_industry", *CONTROL_COLUMNS],
    )
    trades = pd.read_csv(
        TRADES,
        usecols=[
            "trade_id",
            "mae",
            "holding_trading_days",
            "canonical_exit_reason",
        ],
    )
    for name, frame in (("outcomes", outcomes), ("controls", controls), ("trades", trades)):
        if len(frame) != 399 or frame.trade_id.nunique() != 399:
            raise OutcomeRevealError(f"{name} input is not 399 unique cycles")
    frame = assignments.merge(outcomes, on="trade_id", validate="one_to_one")
    frame = frame.merge(controls, on="trade_id", validate="one_to_one")
    frame = frame.merge(trades, on="trade_id", validate="one_to_one")
    for column in ("opportunity20", "false_breakout", "severe_loss"):
        frame[column] = frame[column].astype(bool)
    frame["non_false_breakout"] = (~frame.false_breakout).astype(float)
    frame["extreme_winner"] = frame.round_trip_return >= 0.50
    expected = {
        "opportunity20": 84,
        "false_breakout": 213,
        "severe_loss": 44,
        "extreme_winner": 15,
    }
    actual = {
        name: int(frame[name].sum())
        for name in expected
    }
    if actual != expected:
        raise OutcomeRevealError(f"frozen outcome counts changed: {actual}")
    if not np.isfinite(
        frame[["mfe", "round_trip_return", "realized_pnl", "mae"]].to_numpy(float)
    ).all():
        raise OutcomeRevealError("nonfinite required outcome")
    if not (frame.mfe >= 0).all() or not (frame.mae <= 0).all():
        raise OutcomeRevealError("MFE/MAE sign convention changed")
    frame["entry_year"] = frame.entry_year.astype(int)
    return frame


def endpoint_packet(
    frame: pd.DataFrame,
    predictor: str,
    endpoint: str,
    controls: tuple[str, ...],
) -> dict[str, Any]:
    with_year, year_columns = add_year_dummies(frame)
    return {
        "raw": association(frame, predictor, endpoint),
        "raw_loyo": loyo(frame, predictor, endpoint),
        "controlled": partial_rank(
            with_year, predictor, endpoint, (*controls, *year_columns)
        ),
        "controlled_loyo": loyo(frame, predictor, endpoint, controls),
        "within_year": association(
            frame.assign(
                _x=frame.groupby("entry_year")[predictor].rank(pct=True),
                _y=frame.groupby("entry_year")[endpoint].rank(pct=True),
            ),
            "_x",
            "_y",
        ),
        "blocks": {
            str(block): association(sample, predictor, endpoint)
            for block, sample in frame.groupby("baseline_block", sort=True)
        },
    }


def lineage_summary(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    positive_pnl_total = float(frame.loc[frame.realized_pnl > 0, "realized_pnl"].sum())
    for lineage, sample in frame.groupby("lineage_id", sort=True):
        positive_pnl = float(sample.loc[sample.realized_pnl > 0, "realized_pnl"].sum())
        rows.append(
            {
                "lineage_id": lineage,
                "lineage_strength": LINEAGE_STRENGTH[lineage],
                "n": len(sample),
                "mean_mfe": float(sample.mfe.mean()),
                "median_mfe": float(sample.mfe.median()),
                "opportunity20_rate": float(sample.opportunity20.mean()),
                "false_breakout_rate": float(sample.false_breakout.mean()),
                "mean_terminal_return": float(sample.round_trip_return.mean()),
                "median_terminal_return": float(sample.round_trip_return.median()),
                "severe_loss_rate": float(sample.severe_loss.mean()),
                "extreme_winner_rate": float(sample.extreme_winner.mean()),
                "positive_pnl_share": None
                if positive_pnl_total <= 0
                else positive_pnl / positive_pnl_total,
            }
        )
    return rows


def analyze(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    primary = {
        endpoint: endpoint_packet(
            frame, "lineage_strength", endpoint, CONTROL_COLUMNS
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    qvalues = benjamini_hochberg(
        {endpoint: primary[endpoint]["raw"]["pvalue"] for endpoint in PRIMARY_ENDPOINTS}
    )
    for endpoint in PRIMARY_ENDPOINTS:
        primary[endpoint]["raw_bh_qvalue"] = qvalues[endpoint]

    grouped = [sample.mfe.to_numpy(float) for _, sample in frame.groupby("lineage_id")]
    omnibus_mfe = kruskal(*grouped)
    false_rates = frame.groupby("lineage_id").false_breakout.mean().sort_index()
    lineage_means = frame.groupby("lineage_strength").agg(
        mean_mfe=("mfe", "mean"),
        non_false_breakout_rate=("non_false_breakout", "mean"),
        n=("trade_id", "size"),
    )
    mechanisms = {
        axis: {
            endpoint: endpoint_packet(frame, axis, endpoint, CONTROL_COLUMNS)
            for endpoint in PRIMARY_ENDPOINTS
        }
        for axis in ("base_high", "acceptance_high")
    }
    secondary = {
        endpoint: association(frame, "lineage_strength", endpoint)
        for endpoint in (
            "opportunity20",
            "round_trip_return",
            "extreme_winner",
            "severe_loss",
            "mae",
        )
    }
    neighbor = {
        endpoint: {
            "raw": association(frame, "neighbor_lineage_strength", endpoint),
            "loyo": loyo(frame, "neighbor_lineage_strength", endpoint),
        }
        for endpoint in PRIMARY_ENDPOINTS
    }

    top4 = set(frame.assign(abs_pnl=frame.realized_pnl.abs()).nlargest(4, "abs_pnl").trade_id)
    attacks: dict[str, Any] = {}
    attack_samples = {
        "ex_top1pct_absolute_pnl": frame[~frame.trade_id.isin(top4)],
        "ex_extreme_winners": frame[~frame.extreme_winner],
        "ex_severe_losses": frame[~frame.severe_loss],
    }
    for name, sample in attack_samples.items():
        attacks[name] = {
            endpoint: association(sample, "lineage_strength", endpoint)
            for endpoint in PRIMARY_ENDPOINTS
        }
    exit_dummies = pd.get_dummies(
        frame.canonical_exit_reason.astype(str), prefix="exit", drop_first=True, dtype=float
    )
    duration_frame = pd.concat(
        [frame.reset_index(drop=True), exit_dummies.reset_index(drop=True)], axis=1
    )
    duration_frame, year_columns = add_year_dummies(duration_frame)
    attacks["holding_duration_exit_control"] = {
        endpoint: partial_rank(
            duration_frame,
            "lineage_strength",
            endpoint,
            (
                *CONTROL_COLUMNS,
                "holding_trading_days",
                *tuple(exit_dummies.columns),
                *year_columns,
            ),
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    attacks["security_leave_one_out"] = {
        endpoint: leave_group_out(frame, "symbol", "lineage_strength", endpoint)
        for endpoint in PRIMARY_ENDPOINTS
    }
    attacks["industry_leave_one_out"] = {
        endpoint: leave_group_out(
            frame, "entry_industry", "lineage_strength", endpoint
        )
        for endpoint in PRIMARY_ENDPOINTS
    }

    gates_spec = spec["decision_gates"]
    raw_gate = all(
        primary[endpoint]["raw"]["rho"] >= gates_spec["raw_minimum_rho"]
        and primary[endpoint]["raw_loyo"]["positive"]
        >= gates_spec["raw_minimum_positive_loyo"]
        and primary[endpoint]["raw_bh_qvalue"] <= gates_spec["maximum_bh_qvalue"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    controlled_gate = all(
        primary[endpoint]["controlled"]["partial_rank_rho"]
        >= gates_spec["controlled_minimum_rho"]
        and primary[endpoint]["controlled_loyo"]["positive"]
        >= gates_spec["controlled_minimum_positive_loyo"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    temporal_gate = all(
        sum(packet["rho"] > 0 for packet in primary[endpoint]["blocks"].values())
        >= gates_spec["minimum_positive_blocks"]
        and min(packet["rho"] for packet in primary[endpoint]["blocks"].values())
        > gates_spec["minimum_block_rho_exclusive"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    neighbor_gate = all(
        neighbor[endpoint]["raw"]["rho"] >= gates_spec["neighbor_minimum_rho"]
        and neighbor[endpoint]["loyo"]["positive"]
        >= gates_spec["neighbor_minimum_positive_loyo"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    tail_gate = all(
        attacks[name][endpoint]["rho"] > gates_spec["attack_minimum_rho_exclusive"]
        for name in attack_samples
        for endpoint in PRIMARY_ENDPOINTS
    )
    duration_gate = all(
        attacks["holding_duration_exit_control"][endpoint]["partial_rank_rho"]
        > gates_spec["attack_minimum_rho_exclusive"]
        for endpoint in PRIMARY_ENDPOINTS
    )
    concentration_gate = all(
        attacks[group][endpoint]["positive_fraction"]
        >= gates_spec["minimum_leave_group_positive_fraction"]
        and attacks[group][endpoint]["minimum"]
        > gates_spec["leave_group_minimum_rho_exclusive"]
        for group in ("security_leave_one_out", "industry_leave_one_out")
        for endpoint in PRIMARY_ENDPOINTS
    )
    falsification_gate = tail_gate and duration_gate and concentration_gate
    gates = {
        "raw_both_endpoints": raw_gate,
        "controlled_both_endpoints": controlled_gate,
        "temporal_both_endpoints": temporal_gate,
        "neighbor_both_endpoints": neighbor_gate,
        "falsification": falsification_gate,
    }
    endpoint_support = {
        endpoint: (
            primary[endpoint]["raw"]["rho"] >= gates_spec["raw_minimum_rho"]
            and primary[endpoint]["controlled"]["partial_rank_rho"]
            >= gates_spec["controlled_minimum_rho"]
        )
        for endpoint in PRIMARY_ENDPOINTS
    }
    if all(gates.values()):
        decision = "VALIDATE"
        verdict = "FROZEN_LINEAGE_STRENGTH_SURVIVES_ALL_EXPLORATORY_GATES"
    elif raw_gate and controlled_gate and temporal_gate:
        decision = "SUPPORTED_WEAK"
        verdict = "LINEAGE_SEPARATION_PRESENT_BUT_FAILS_NEIGHBOR_OR_FALSIFICATION"
    elif any(endpoint_support.values()):
        decision = "REFINE"
        verdict = "LINEAGE_MECHANISM_IS_ENDPOINT_SPECIFIC"
    else:
        decision = "REJECTED"
        verdict = "FROZEN_LINEAGE_STRENGTH_FAILS_PRIMARY_RAW_OR_CONTROLLED_GATES"

    ordered_summary = lineage_summary(frame)
    return {
        "experiment_id": "EXP-OBL-004",
        "hypothesis_id": "H-OBL-003",
        "lineage_freeze_id": "LINEAGE-OBL-003-4193834A6A3A39BF",
        "evidence_grade": "EXPLORATORY_REVEAL_ON_HISTORICALLY_CONSUMED_BOUNDED_PIT_B",
        "population": {
            "events": len(frame),
            "controlled_complete": int(
                frame[["lineage_strength", *PRIMARY_ENDPOINTS, *CONTROL_COLUMNS]]
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .shape[0]
            ),
            "opportunity20": int(frame.opportunity20.sum()),
            "false_breakout": int(frame.false_breakout.sum()),
            "extreme_winner": int(frame.extreme_winner.sum()),
            "severe_loss": int(frame.severe_loss.sum()),
        },
        "primary": primary,
        "omnibus": {
            "mfe_kruskal_statistic": float(omnibus_mfe.statistic),
            "mfe_kruskal_pvalue": float(omnibus_mfe.pvalue),
            "false_breakout_rates_by_lineage": false_rates.to_dict(),
            "ordinal_summary": lineage_means.reset_index().to_dict(orient="records"),
        },
        "lineage_summary": ordered_summary,
        "mechanism_axes": mechanisms,
        "secondary_not_decision_rescuing": secondary,
        "neighbor": neighbor,
        "attacks": attacks,
        "gates": gates,
        "endpoint_support": endpoint_support,
        "decision": decision,
        "verdict": verdict,
        "interpretation_boundary": (
            "Lineages were frozen without outcomes. Full signal-session information is "
            "available at 15:30 for T+1 or later only. This reveal tests mechanism "
            "separation and authorizes no entry, exit, size, overlay, or production rule."
        ),
    }


def render_report(result: dict[str, Any]) -> str:
    primary = result["primary"]
    lines = [
        "# EXP-OBL-004 frozen-lineage outcome reveal",
        "",
        f"Decision: `{result['decision']}`.",
        "",
        f"Verdict: `{result['verdict']}`.",
        "",
        "## Primary frozen tests",
        "",
        "| Endpoint | Raw rho | Raw LOYO + | Controlled rho | Controlled LOYO + | BH q |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for endpoint in PRIMARY_ENDPOINTS:
        packet = primary[endpoint]
        lines.append(
            f"| {endpoint} | {packet['raw']['rho']:.6f} | "
            f"{packet['raw_loyo']['positive']}/{packet['raw_loyo']['total']} | "
            f"{packet['controlled']['partial_rank_rho']:.6f} | "
            f"{packet['controlled_loyo']['positive']}/{packet['controlled_loyo']['total']} | "
            f"{packet['raw_bh_qvalue']:.6g} |"
        )
    lines.extend(
        [
            "",
            "## Frozen lineage summaries",
            "",
            "| Lineage | n | Mean MFE | False-breakout rate | Mean terminal return | Extreme-winner rate |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in result["lineage_summary"]:
        lines.append(
            f"| {row['lineage_id']} | {row['n']} | {row['mean_mfe']:.4f} | "
            f"{row['false_breakout_rate']:.4f} | {row['mean_terminal_return']:.4f} | "
            f"{row['extreme_winner_rate']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"Gates: `{json.dumps(result['gates'], sort_keys=True)}`.",
            "",
            result["interpretation_boundary"],
        ]
    )
    return "\n".join(lines) + "\n"


def render_evidence_packet(result: dict[str, Any]) -> str:
    return (
        "# EXP-OBL-004 evidence packet\n\n"
        f"- Freeze: `{result['lineage_freeze_id']}`\n"
        f"- Population: `{result['population']['events']}` events; "
        f"`{result['population']['controlled_complete']}` complete controlled rows\n"
        f"- Decision: `{result['decision']}`\n"
        f"- Verdict: `{result['verdict']}`\n"
        f"- Gates: `{json.dumps(result['gates'], sort_keys=True)}`\n\n"
        "Secondary terminal-return/right-tail evidence cannot rescue a failed primary gate. "
        "No strategy modification is authorized.\n"
    )


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    frame = load_analysis_frame()
    result = analyze(frame, spec)
    result["input_identities"] = identities
    output_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "entry_year",
        "lineage_id",
        "neighbor_lineage_id",
        "lineage_strength",
        "base_high",
        "acceptance_high",
        "mfe",
        "mae",
        "opportunity20",
        "false_breakout",
        "non_false_breakout",
        "round_trip_return",
        "realized_pnl",
        "extreme_winner",
        "severe_loss",
        "holding_trading_days",
        "canonical_exit_reason",
        "entry_industry",
        *CONTROL_COLUMNS,
    ]
    atomic_csv(OUTPUT_TABLE, frame[output_columns].sort_values("trade_id"))
    result["output_table_sha256"] = sha256_file(OUTPUT_TABLE)
    atomic_write(
        OUTPUT_JSON,
        json.dumps(clean_json(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(REPORT, render_report(result))
    atomic_write(EVIDENCE_PACKET, render_evidence_packet(result))
    print(json.dumps(clean_json(result), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
