#!/usr/bin/env python3
"""Freeze EXP-OBL-008 selection competition without outcome access."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/original_breakout_lineage"
V1_SCRIPTS = ROOT / "research/chinext_v1/scripts"
LOCAL_SCRIPTS = WORK / "scripts"
SRC = ROOT / "src"
for path in (str(V1_SCRIPTS), str(LOCAL_SCRIPTS), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

import run_chinext_v1_extended_replay as extended  # noqa: E402
import run_chinext_v1_smoke as engine  # noqa: E402
import run_outcome_blind_lineage_freeze as daily_base  # noqa: E402

SPEC = WORK / "experiments/EXP-OBL-008_spec.json"
HELPER = LOCAL_SCRIPTS / "run_selection_block_engine.py"
IDENTITIES = ROOT / "research/chinext_v1/regime_attribution/artifacts/yearly_trades.csv"
HOLDOUT_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/daily_membership.parquet"
DEVELOPMENT_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
MARKET = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")

OUTPUT_TABLE = WORK / "artifacts/selection_competition_features.csv"
OUTPUT_AUDIT = WORK / "artifacts/EXP-OBL-008_audit.json"
LINEAGE_FREEZE = WORK / "lineage_freezes/LINEAGE-OBL-008.json"
REPORT = WORK / "reports/EXP-OBL-008_selection_competition_freeze.md"

FORBIDDEN_COLUMNS = daily_base.FORBIDDEN_COLUMNS
BLOCKS = (
    {
        "name": "EXTENDED_2018_2021",
        "start": "2018-01-02",
        "end": "2021-12-31",
        "warmup": "2017-04-12",
        "membership": "transient",
    },
    {
        "name": "HOLDOUT_O0_2022_2023",
        "start": "2022-01-04",
        "end": "2023-12-29",
        "warmup": "2021-07-08",
        "membership": HOLDOUT_MEMBERSHIP,
    },
    {
        "name": "DEVELOPMENT_2024_2025",
        "start": "2024-01-02",
        "end": "2025-12-31",
        "warmup": "2023-01-01",
        "membership": DEVELOPMENT_MEMBERSHIP,
    },
)


class SelectionFreezeError(RuntimeError):
    """Raised when replay identity, event reconstruction, or freeze gates fail."""


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
    if spec.get("experiment_id") != "EXP-OBL-008":
        raise SelectionFreezeError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_EVENT_REPLAY":
        raise SelectionFreezeError("selection experiment is not frozen")
    if spec.get("outcome_access") is not False:
        raise SelectionFreezeError("outcome prohibition changed")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for role, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        if not path.is_file():
            raise SelectionFreezeError(f"missing bound input: {role}: {path}")
        actual = sha256_file(path)
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[role] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise SelectionFreezeError(f"frozen input mismatch: {mismatches}")
    daily_base.phase2.validate_inputs()
    cy006 = daily_base.inventory_files(
        daily_base.CY006_INVENTORY,
        [f"partition_year={year}/data_0.parquet" for year in range(2018, 2026)],
    )
    if len(cy006) != 8:
        raise SelectionFreezeError("CY-006 partition count changed")
    return spec, identities


def run_block(
    block: dict[str, Any],
    temporary_root: Path,
    transient_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output = temporary_root / str(block["name"])
    membership = transient_root / "daily_membership.parquet" if block["membership"] == "transient" else Path(block["membership"])
    daily_root = transient_root if block["membership"] == "transient" else DAILY_ROOT
    command = [
        sys.executable,
        str(HELPER),
        "--start",
        str(block["start"]),
        "--end",
        str(block["end"]),
        "--warmup-start",
        str(block["warmup"]),
        "--pit-membership",
        str(membership),
        "--daily-root",
        str(daily_root),
        "--market",
        str(MARKET),
        "--calendar",
        str(CALENDAR),
        "--output-dir",
        str(output),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SelectionFreezeError(
            f"block replay failed: {block['name']}: {completed.stderr[-4000:]}"
        )
    event_path = output / "event_ledger.jsonl"
    if not event_path.is_file():
        raise SelectionFreezeError(f"event ledger missing: {block['name']}")
    events = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    return events, {
        "block": block["name"],
        "event_rows": len(events),
        "event_ledger_sha256": sha256_file(event_path),
        "files_read_by_parent": ["event_ledger.jsonl"],
        "performance_files_read_by_parent": [],
    }


def ranked_candidates(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if event.get("event") != "ENTRY_SIGNAL_EVALUATED":
            continue
        minimum = event.get("minvol") or {}
        rs = event.get("rs")
        if minimum.get("passed") is not True or not isinstance(rs, dict):
            continue
        day = str(event["signal_date"])
        candidates.setdefault(day, []).append(
            {
                "symbol": str(event["symbol"]),
                "score": float(rs["score"]),
                "mom60": float(rs["mom60"]),
            }
        )
    for day in candidates:
        candidates[day] = sorted(
            candidates[day],
            key=lambda row: (-row["score"], -row["mom60"], row["symbol"]),
        )
    return candidates


def selection_records(
    block_name: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates = ranked_candidates(events)
    changes: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event") != "DESIRED_SET_CHANGED":
            continue
        day = str(event["signal_date"])
        if day in changes:
            raise SelectionFreezeError(f"multiple desired-set changes: {block_name}/{day}")
        changes[day] = event
    records: list[dict[str, Any]] = []
    for day, event in sorted(changes.items()):
        previous = set(map(str, event["previous"]))
        desired = set(map(str, event["desired"]))
        additions = desired - previous
        if not additions:
            continue
        survivors = previous & desired
        vacancies = 10 - len(survivors)
        ranked = candidates.get(day, [])
        if vacancies <= 0 or not ranked:
            raise SelectionFreezeError(f"addition lacks vacancy/candidates: {block_name}/{day}")
        expected_additions = {row["symbol"] for row in ranked[:vacancies]}
        if additions != expected_additions:
            raise SelectionFreezeError(
                f"selection reconstruction mismatch: {block_name}/{day}: "
                f"actual={sorted(additions)} expected={sorted(expected_additions)}"
            )
        candidate_count = len(ranked)
        contested = candidate_count > vacancies
        cutoff = ranked[vacancies]["score"] if contested else None
        for index, row in enumerate(ranked[:vacancies], 1):
            if row["symbol"] not in additions:
                continue
            records.append(
                {
                    "baseline_block": block_name,
                    "symbol": row["symbol"],
                    "entry_signal_date": day,
                    "feature_available_at": f"{day}T15:30:00+08:00",
                    "candidate_count": candidate_count,
                    "vacancies_before_selection": vacancies,
                    "selection_pressure": candidate_count / vacancies,
                    "selected_rank": index,
                    "selected_rank_percentile": 1.0
                    if candidate_count == 1
                    else (candidate_count - index) / (candidate_count - 1),
                    "selected_rs_score": row["score"],
                    "cutoff_rs_score": cutoff,
                    "selected_margin_to_cutoff": None
                    if cutoff is None
                    else row["score"] - cutoff,
                    "selection_lineage_id": "L_CONTESTED"
                    if contested
                    else "L_UNCONTESTED",
                }
            )
    return records


def load_identity_projection() -> pd.DataFrame:
    columns = ["baseline_block", "trade_id", "symbol", "entry_signal_date"]
    identities = pd.read_csv(IDENTITIES, usecols=columns)
    if len(identities) != 399 or identities.trade_id.nunique() != 399:
        raise SelectionFreezeError("identity projection is not 399 unique cycles")
    identities["entry_signal_date"] = identities.entry_signal_date.astype(str)
    if FORBIDDEN_COLUMNS.intersection(identities.columns):
        raise SelectionFreezeError("outcome column entered identity projection")
    return identities


def audit_features(frame: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    counts = frame.selection_lineage_id.value_counts().sort_index()
    by_year = pd.crosstab(frame.entry_year, frame.selection_lineage_id)
    expected = {"L_CONTESTED", "L_UNCONTESTED"}
    if set(counts.index) != expected:
        raise SelectionFreezeError(f"selection lineage collapsed: {counts.to_dict()}")
    gates_spec = spec["construction_gates"]
    present_years = {
        lineage: int((by_year.get(lineage, pd.Series(dtype=int)) > 0).sum())
        for lineage in sorted(expected)
    }
    gates = {
        "complete_coverage": len(frame) == 399 and frame.trade_id.nunique() == 399,
        "minimum_lineage_size": int(counts.min()) >= gates_spec["minimum_lineage_size"],
        "maximum_lineage_fraction": float(counts.max() / len(frame))
        <= gates_spec["maximum_lineage_fraction"],
        "temporal_presence": min(present_years.values())
        >= gates_spec["minimum_years_each_lineage"],
        "rank_within_candidate_set": bool(
            ((frame.selected_rank >= 1) & (frame.selected_rank <= frame.candidate_count)).all()
        ),
        "capacity_boundary_exact": bool(
            (
                (frame.selection_lineage_id.eq("L_CONTESTED"))
                == (frame.candidate_count > frame.vacancies_before_selection)
            ).all()
        ),
        "cutoff_missingness_structural": bool(
            frame.loc[frame.selection_lineage_id.eq("L_CONTESTED"), "selected_margin_to_cutoff"].notna().all()
            and frame.loc[frame.selection_lineage_id.eq("L_UNCONTESTED"), "selected_margin_to_cutoff"].isna().all()
        ),
        "no_outcome_columns": not bool(FORBIDDEN_COLUMNS.intersection(frame.columns)),
    }
    if not all(gates.values()):
        raise SelectionFreezeError(
            f"selection construction gates failed: {gates}; counts={counts.to_dict()}; "
            f"present_years={present_years}"
        )
    return {
        "gates": gates,
        "lineage_counts": counts.to_dict(),
        "lineage_counts_by_year": by_year.to_dict(orient="index"),
        "lineage_present_years": present_years,
        "candidate_count": {
            "minimum": int(frame.candidate_count.min()),
            "maximum": int(frame.candidate_count.max()),
            "median": float(frame.candidate_count.median()),
        },
        "vacancies": {
            "minimum": int(frame.vacancies_before_selection.min()),
            "maximum": int(frame.vacancies_before_selection.max()),
            "median": float(frame.vacancies_before_selection.median()),
        },
    }


def render_report(audit: dict[str, Any], freeze_id: str) -> str:
    feature = audit["feature_audit"]
    return (
        "# EXP-OBL-008 outcome-blind selection-lineage freeze\n\n"
        f"LINEAGE_FREEZE_ID: `{freeze_id}`.\n\n"
        f"Lineage counts: `{feature['lineage_counts']}`.\n\n"
        "`CONTESTED` means the exact same-session candidate count exceeded "
        "canonical vacancies; `UNCONTESTED` means it did not. These are neutral "
        "formation/selection lineages and encode no favorable outcome meaning.\n\n"
        "Only temporary event ledgers and identity-only accepted-cycle columns were "
        "read. NAV, execution, summary, report, and outcome files were not read. "
        "No strategy rule or CY-011 access is authorized.\n"
    )


def main() -> None:
    spec, identities = validate_spec_and_inputs()
    replay_spec = extended.load_replay_spec()
    with tempfile.TemporaryDirectory(prefix="obl-selection-freeze-") as raw_temporary:
        temporary = Path(raw_temporary)
        transient = temporary / "extended_inputs"
        prepared = extended.materialize_transient_inputs(transient)
        extended.validate_prepared_manifest(prepared, replay_spec)
        records: list[dict[str, Any]] = []
        replay_audit: list[dict[str, Any]] = []
        for block in BLOCKS:
            events, block_audit = run_block(block, temporary / "runs", transient)
            records.extend(selection_records(str(block["name"]), events))
            replay_audit.append(block_audit)
    reconstructed = pd.DataFrame(records)
    projected = load_identity_projection()
    frame = projected.merge(
        reconstructed,
        on=["baseline_block", "symbol", "entry_signal_date"],
        how="left",
        validate="one_to_one",
    )
    feature_columns = [
        "candidate_count",
        "vacancies_before_selection",
        "selection_pressure",
        "selected_rank",
        "selected_rank_percentile",
        "selected_rs_score",
        "selection_lineage_id",
    ]
    if frame[feature_columns].isna().any().any():
        missing = frame.loc[frame[feature_columns].isna().any(axis=1), "trade_id"].tolist()
        raise SelectionFreezeError(f"accepted identity lacks selection context: {missing[:10]}")
    frame["entry_year"] = frame.entry_signal_date.str[:4].astype(int)
    frame = frame.sort_values("trade_id").reset_index(drop=True)
    feature_audit = audit_features(frame, spec)
    atomic_csv(OUTPUT_TABLE, frame)
    table_sha = sha256_file(OUTPUT_TABLE)
    freeze_id = f"LINEAGE-OBL-008-{table_sha[:16].upper()}"
    audit = {
        "experiment_id": "EXP-OBL-008",
        "hypothesis_id": "H-OBL-007",
        "status": "FROZEN_OUTCOME_BLIND_SELECTION_LINEAGE",
        "lineage_freeze_id": freeze_id,
        "outcome_columns_read": [],
        "performance_files_read": [],
        "population": {"events": len(frame), "years": sorted(frame.entry_year.unique().tolist())},
        "feature_audit": feature_audit,
        "replay_audit": replay_audit,
        "feature_table_sha256": table_sha,
        "input_identities": identities,
        "available_at_timestamp": "signal session 15:30 Asia/Shanghai",
        "potential_action_timestamp": "T+1 open or later",
    }
    atomic_write(
        OUTPUT_AUDIT,
        json.dumps(clean_json(audit), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    manifest = {
        "schema_version": "1.0.0",
        "lineage_freeze_id": freeze_id,
        "experiment_id": "EXP-OBL-008",
        "status": "FROZEN_BEFORE_OUTCOME_JOIN",
        "spec_path": str(SPEC.relative_to(ROOT)),
        "spec_sha256": sha256_file(SPEC),
        "runner_path": str(Path(__file__).resolve().relative_to(ROOT)),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "feature_table": str(OUTPUT_TABLE.relative_to(ROOT)),
        "feature_table_sha256": table_sha,
        "audit_path": str(OUTPUT_AUDIT.relative_to(ROOT)),
        "audit_sha256": sha256_file(OUTPUT_AUDIT),
        "lineage_ids": ["L_CONTESTED", "L_UNCONTESTED"],
        "outcome_access_before_freeze": False,
        "outcome_columns_read": [],
        "performance_files_read": [],
    }
    atomic_write(
        LINEAGE_FREEZE,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(REPORT, render_report(audit, freeze_id))
    print(json.dumps(clean_json(audit), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
