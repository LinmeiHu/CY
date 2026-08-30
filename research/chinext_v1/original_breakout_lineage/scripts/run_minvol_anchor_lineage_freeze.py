#!/usr/bin/env python3
"""Construct EXP-OBL-013 canonical minimum-volume anchor lineages."""

from __future__ import annotations

import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
SCRIPTS = WORK / "scripts"
STRATEGY_DIR = ROOT / "research/chinext_v1/strategy"
for import_root in (SCRIPTS, STRATEGY_DIR):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import run_outcome_blind_lineage_freeze as source  # noqa: E402
from chinext_v1_exploratory import ChinNextV1Config, minvol_diagnostic  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-013_spec.json"
FEATURES = WORK / "artifacts/minvol_anchor_features.csv"
ASSIGNMENTS = WORK / "artifacts/minvol_anchor_assignments.csv"
AUDIT = WORK / "artifacts/EXP-OBL-013_audit.json"
FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-013.json"
REPORT = WORK / "reports/EXP-OBL-013_minvol_anchor_freeze.md"

FORBIDDEN_COLUMNS = source.FORBIDDEN_COLUMNS | {
    "opportunity20",
    "non_false_breakout",
    "terminal_return",
}
LINEAGES = {
    (False, False): "L00_LOW_BROKEN_NOT_RECOVERED",
    (False, True): "L01_LOW_BROKEN_RECOVERED",
    (True, False): "L10_LOW_HELD_NOT_RECOVERED",
    (True, True): "L11_LOW_HELD_RECOVERED",
}


class MinVolFreezeError(RuntimeError):
    """Raised when canonical lineage, PIT, or outcome-blind gates fail."""


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_spec_and_inputs() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-OBL-013":
        raise MinVolFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_OUTCOME_BLIND_CONSTRUCTION":
        raise MinVolFreezeError("minimum-volume construction is not frozen")
    if spec.get("outcome_access") is not False:
        raise MinVolFreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise MinVolFreezeError(f"missing bound input: {role}: {path}")
        actual = source.sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise MinVolFreezeError(f"frozen input mismatch: {mismatches}")
    source.phase2.validate_inputs()
    return spec, identities


def build_history(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build action-safe history including fields needed for volume rebasing."""
    with tempfile.TemporaryDirectory(prefix="chinext_v1_obl013_") as temporary:
        transient_root = Path(temporary)
        manifest = source.phase2.extended.materialize_transient_inputs(transient_root)
        if manifest["canonical_sha256"] != source.phase2.EXPECTED_TRANSIENT_CANONICAL:
            raise MinVolFreezeError("transient canonical identity changed")
        if manifest["membership"]["sha256"] != source.phase2.EXPECTED_TRANSIENT_MEMBERSHIP:
            raise MinVolFreezeError("transient membership identity changed")
        connection = source.phase2.duckdb.connect()
        connection.execute("SET threads=1")
        source.phase2.create_membership_tables(
            connection, transient_root / "daily_membership.parquet"
        )
        panel_counts = source.phase2.create_panel_tables(connection, transient_root)
        source.phase2.create_stock_features(connection)
        projection = events[
            ["trade_id", "baseline_block", "symbol", "entry_signal_date"]
        ].copy()
        connection.register("obl013_identity", projection)
        connection.execute(
            """
            CREATE TEMP TABLE obl013_entries AS
            SELECT i.*,c.cal_idx AS signal_idx
            FROM obl013_identity i
            JOIN calendar c ON CAST(i.entry_signal_date AS DATE)=c.trade_date
            """
        )
        history = connection.execute(
            """
            SELECT e.trade_id,e.baseline_block,e.symbol,e.signal_idx,
                   w.trade_date,w.cal_idx,w.critical_valid,w.coordinate_step_valid,
                   w.adjusted_close,w.adjusted_high,w.adjusted_low,w.volume,
                   w.corporate_action_count,w.share_multiplier,w.rights_ratio,
                   w.corporate_action_available_date,w.corporate_action_valid,
                   w.corporate_action_blocking,w.snapshot_id,w.available_at
            FROM obl013_entries e
            JOIN stock_windows w
              ON w.baseline_block=e.baseline_block AND w.symbol=e.symbol
             AND w.cal_idx BETWEEN e.signal_idx-79 AND e.signal_idx
            ORDER BY e.trade_id,w.cal_idx
            """
        ).fetchdf()
        connection.close()
    return history, {
        "panel_counts": panel_counts,
        "transient_canonical_sha256": manifest["canonical_sha256"],
        "transient_membership_sha256": manifest["membership"]["sha256"],
    }


def volumes_in_signal_coordinate(rows: pd.DataFrame) -> np.ndarray:
    """Apply each visible action multiplier only to earlier volume history."""
    raw = rows.volume.to_numpy(float)
    result = raw.copy()
    for position, item in rows.reset_index(drop=True).iterrows():
        action_count = int(item.corporate_action_count or 0)
        if action_count <= 0:
            continue
        multiplier = float(item.share_multiplier)
        visible = (
            pd.notna(item.corporate_action_available_date)
            and pd.Timestamp(item.corporate_action_available_date).date()
            <= pd.Timestamp(item.trade_date).date()
        )
        valid = (
            bool(item.corporate_action_valid)
            and not bool(item.corporate_action_blocking)
            and visible
            and float(item.rights_ratio or 0.0) == 0.0
            and math.isfinite(multiplier)
            and multiplier > 0.0
        )
        if not valid:
            raise MinVolFreezeError("invalid corporate action inside accepted history")
        result[:position] *= multiplier
    if not np.isfinite(result).all() or (result <= 0).any():
        raise MinVolFreezeError("invalid rebased volume history")
    return result


def build_features(history: pd.DataFrame) -> pd.DataFrame:
    config = ChinNextV1Config()
    records: list[dict[str, Any]] = []
    for trade_id, rows in history.groupby("trade_id", sort=True):
        rows = rows.sort_values("cal_idx").reset_index(drop=True)
        signal_idx = int(rows.signal_idx.iloc[0])
        if rows.cal_idx.astype(int).tolist() != list(range(signal_idx - 79, signal_idx + 1)):
            raise MinVolFreezeError(f"incomplete 80-session history: {trade_id}")
        if not rows.critical_valid.astype(bool).all():
            raise MinVolFreezeError(f"hard-invalid daily row: {trade_id}")
        if not rows.iloc[1:].coordinate_step_valid.astype(bool).all():
            raise MinVolFreezeError(f"invalid action coordinate: {trade_id}")
        numeric = rows[
            ["adjusted_close", "adjusted_high", "adjusted_low", "volume"]
        ].to_numpy(float)
        if not np.isfinite(numeric).all() or (numeric <= 0).any():
            raise MinVolFreezeError(f"invalid history numeric: {trade_id}")
        rebased_volume = volumes_in_signal_coordinate(rows)
        diagnostic = minvol_diagnostic(
            rows.adjusted_close.to_numpy(float),
            rebased_volume,
            config,
        )
        if not diagnostic.valid or not diagnostic.passed:
            raise MinVolFreezeError(f"accepted event fails canonical MINVOL: {trade_id}")
        prior30 = rows.iloc[-31:-1].reset_index(drop=True)
        volume30 = rebased_volume[-31:-1]
        minimum_index = min(range(30), key=lambda index: volume30[index])
        minimum_value = float(volume30[minimum_index])
        tie_count = int(np.isclose(volume30, minimum_value, rtol=1e-12, atol=1e-12).sum())
        anchor = prior30.iloc[minimum_index]
        subsequent = prior30.iloc[minimum_index + 1 :]
        low_support_held = bool(
            subsequent.empty
            or (subsequent.adjusted_low.to_numpy(float) >= float(anchor.adjusted_low)).all()
        )
        close_support_held = bool(
            subsequent.empty
            or (subsequent.adjusted_close.to_numpy(float) >= float(anchor.adjusted_close)).all()
        )
        recovered = bool(
            float(prior30.adjusted_close.iloc[-1]) > float(anchor.adjusted_close)
        )
        primary_lineage = LINEAGES[(low_support_held, recovered)]
        neighbor_lineage = LINEAGES[(close_support_held, recovered)]
        signal = rows.iloc[-1]
        records.append(
            {
                "trade_id": trade_id,
                "baseline_block": rows.baseline_block.iloc[0],
                "symbol": rows.symbol.iloc[0],
                "entry_signal_date": pd.Timestamp(signal.trade_date).date().isoformat(),
                "entry_year": int(pd.Timestamp(signal.trade_date).year),
                "available_at_timestamp": pd.Timestamp(signal.available_at).isoformat(),
                "daily_snapshot_id": signal.snapshot_id,
                "minimum_volume_index_0_29": minimum_index,
                "sessions_since_minimum_volume": 29 - minimum_index,
                "minimum_volume_tie_count": tie_count,
                "minimum_volume_ratio": float(diagnostic.minimum_volume_ratio),
                "minimum_volume_location": float(diagnostic.location),
                "anchor_close": float(anchor.adjusted_close),
                "anchor_low": float(anchor.adjusted_low),
                "post_anchor_min_close_log_distance": 0.0
                if subsequent.empty
                else math.log(float(subsequent.adjusted_close.min()) / float(anchor.adjusted_close)),
                "post_anchor_min_low_log_distance": 0.0
                if subsequent.empty
                else math.log(float(subsequent.adjusted_low.min()) / float(anchor.adjusted_low)),
                "prebreakout_close_log_recovery": math.log(
                    float(prior30.adjusted_close.iloc[-1]) / float(anchor.adjusted_close)
                ),
                "low_support_held": low_support_held,
                "close_support_held_neighbor": close_support_held,
                "recovered_above_anchor_close": recovered,
                "lineage_id": primary_lineage,
                "neighbor_lineage_id": neighbor_lineage,
            }
        )
    frame = pd.DataFrame(records).sort_values("trade_id").reset_index(drop=True)
    if FORBIDDEN_COLUMNS.intersection(frame.columns):
        raise MinVolFreezeError("outcome column entered minimum-volume frame")
    return frame


def construction_audit(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    expected = sorted(LINEAGES.values())
    counts = frame.lineage_id.value_counts().reindex(expected, fill_value=0)
    by_year = pd.crosstab(frame.entry_year, frame.lineage_id).reindex(
        index=range(2018, 2026), columns=expected, fill_value=0
    )
    by_block = pd.crosstab(frame.baseline_block, frame.lineage_id).reindex(
        columns=expected, fill_value=0
    )
    agreement = float(frame.lineage_id.eq(frame.neighbor_lineage_id).mean())
    gates_spec = spec["construction_gates"]
    gates = {
        "complete_coverage": len(frame) == 399 and frame.trade_id.nunique() == 399,
        "all_four_lineages": bool((counts > 0).all()),
        "minimum_lineage_size": int(counts.min()) >= gates_spec["minimum_lineage_size"],
        "maximum_lineage_fraction": float(counts.max() / len(frame))
        <= gates_spec["maximum_lineage_fraction"],
        "every_lineage_in_every_year": int(by_year.min().min())
        >= gates_spec["minimum_lineage_count_per_year"],
        "neighbor_assignment_agreement": agreement
        >= gates_spec["minimum_neighbor_assignment_agreement"],
        "canonical_minvol_passed_all": bool(
            (frame.minimum_volume_ratio <= 0.70 + 1e-12).all()
            and (frame.minimum_volume_location <= 0.50 + 1e-12).all()
        ),
        "no_outcome_columns": not bool(FORBIDDEN_COLUMNS.intersection(frame.columns)),
    }
    return {
        "counts": counts.to_dict(),
        "fractions": (counts / len(frame)).to_dict(),
        "counts_by_year": by_year.to_dict(orient="index"),
        "counts_by_block": by_block.to_dict(orient="index"),
        "neighbor_assignment_agreement": agreement,
        "events_with_tied_minimum_volume": int((frame.minimum_volume_tie_count > 1).sum()),
        "gates": gates,
        "decision": "FREEZE_LINEAGE" if all(gates.values()) else "REJECT_BEFORE_OUTCOME",
    }


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    lines = [
        "# EXP-OBL-013 outcome-blind minimum-volume anchor freeze",
        "",
        f"Decision: `{audit['decision']}`.",
        "",
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.",
        "",
        "| Neutral lineage | Count |",
        "|---|---:|",
    ]
    lines.extend(f"| {name} | {count} |" for name, count in sorted(audit["counts"].items()))
    lines.extend(
        [
            "",
            f"Low-support/close-support neighboring agreement: `{audit['neighbor_assignment_agreement']:.6f}`.",
            "",
            f"Events with canonical earliest-minimum ties: `{audit['events_with_tied_minimum_volume']}`.",
            "",
            "No post-entry outcome was read. The IDs describe only support defense and t-1 recovery around V1's canonical minimum-volume session.",
            "",
            "Features are available at the signal close and can first inform T+1 or later. No strategy rule is authorized.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    events = source.load_identities()
    history, history_audit = build_history(events)
    frame = build_features(history)
    audit = construction_audit(frame, spec)
    if not all(audit["gates"].values()):
        raise MinVolFreezeError(f"frozen construction gates failed: {audit}")
    feature_columns = [
        column for column in frame.columns if column not in {"lineage_id", "neighbor_lineage_id"}
    ]
    assignment_columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_year",
        "lineage_id",
        "neighbor_lineage_id",
    ]
    source.atomic_csv(FEATURES, frame[feature_columns])
    source.atomic_csv(ASSIGNMENTS, frame[assignment_columns])
    feature_sha = source.sha256_file(FEATURES)
    assignment_sha = source.sha256_file(ASSIGNMENTS)
    freeze_id = f"LINEAGE-OBL-013-{assignment_sha[:16].upper()}"
    audit.update(
        {
            "experiment_id": "EXP-OBL-013",
            "hypothesis_id": "H-OBL-011",
            "outcome_access": False,
            "input_identities": identities,
            "history_audit": history_audit,
            "feature_table_sha256": feature_sha,
            "assignment_table_sha256": assignment_sha,
            "lineage_freeze_id": freeze_id,
        }
    )
    source.atomic_write(
        AUDIT,
        json.dumps(source.clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-013",
        "hypothesis_id": "H-OBL-011",
        "outcome_access_before_freeze": False,
        "available_at_timestamp": "completed signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "T+1 open or later",
        "feature_table_sha256": feature_sha,
        "assignment_table_sha256": assignment_sha,
        "audit_sha256": source.sha256_file(AUDIT),
        "modification_after_outcome_reveal": "FORBIDDEN",
    }
    source.atomic_write(
        FREEZE,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    source.atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(source.clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
