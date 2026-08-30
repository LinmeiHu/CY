#!/usr/bin/env python3
"""Audit exact unchanged objective-level support without process estimates."""

from __future__ import annotations

import hashlib
import json
import struct
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-LVL-DATA-001_spec.json"
COUNT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-LVL-DATA-001_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-LVL-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-LVL-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "cfd6cde62ada6711566516d2cbb1be8194bbd658fb32a22a1e5ee2ca6a03bfa4"


class SupportLevelFeasibilityError(RuntimeError):
    """Fail-closed exact-level feasibility error."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if _sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportLevelFeasibilityError("level-feasibility spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_LEVEL_IDENTITY_COUNTS" or spec["outcome_access"]:
        raise SupportLevelFeasibilityError("level-feasibility activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or _sha256_file(path) != binding["sha256"]:
            raise SupportLevelFeasibilityError(f"bound input identity mismatch: {name}")
    parent = json.loads(
        _resolve(spec["inputs"]["dynamics_result"]["path"]).read_text(encoding="utf-8")
    )
    if (
        parent["status"] != "COMPLETE_REPRESENTATION_PASS_NO_PROCESS"
        or parent["directional_process_roles"]
        or parent["coupling"]["coupling_pass"]
        or parent["transition"]["transition_process_pass"]
        or parent["cy011_read"]
    ):
        raise SupportLevelFeasibilityError("parent dynamics boundary changed")
    return spec


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < budget["system_memory_headroom_floor_gib"] * 2**30:
        raise SupportLevelFeasibilityError("system memory headroom floor breached")
    process = psutil.Process()
    if process.memory_info().rss > budget["peak_rss_ceiling_gib"] * 2**30:
        raise SupportLevelFeasibilityError("process RSS ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise SupportLevelFeasibilityError("wall-clock ceiling breached")


def _level_bits(value: float) -> str:
    numeric = float(value)
    if not np.isfinite(numeric) or numeric <= 0:
        raise SupportLevelFeasibilityError("level is nonpositive or nonfinite")
    return struct.pack(">d", numeric).hex()


def _case_hash(sequence_id: str) -> str:
    return hashlib.sha256(f"MKT-SUPPORT-LVL-DATA-001|{sequence_id}".encode()).hexdigest()


def _load_inputs(spec: dict[str, Any]) -> pd.DataFrame:
    identity = [
        "audit_id",
        "sequence_id",
        "target_year",
        "block_id",
        "market_view",
        "market_sequence_rank",
        "symbol",
        "trade_date",
        "relative_day",
    ]
    path_fields = [
        f"h{horizon}_{path}_{field}"
        for horizon, path in [(10, "cont"), (20, "cont"), (40, "cont"), (20, "auction")]
        for field in [
            "tested",
            "recovery_completion",
            "recovery_speed",
            "recovery_volume_intensity",
        ]
    ]
    session = pd.read_csv(
        _resolve(spec["inputs"]["dynamics_session_panel"]["path"]),
        usecols=[*identity, *path_fields],
        dtype={"symbol": str},
        float_precision="round_trip",
    )
    coordinate = pd.read_csv(
        _resolve(spec["inputs"]["data004_coordinate_audit"]["path"]),
        usecols=["audit_id", "support_low10", "support_low20", "support_low40"],
        float_precision="round_trip",
    )
    frame = session.merge(coordinate, on="audit_id", validate="one_to_one")
    expected = spec["population"]
    if (
        len(frame) != expected["exact_cohort_rows"]
        or frame["sequence_id"].nunique() != expected["exact_sequences"]
        or len(frame[["symbol", "trade_date"]].drop_duplicates())
        != expected["exact_unique_physical_sessions"]
        or frame["relative_day"].min() != -5
        or frame["relative_day"].max() != -1
    ):
        raise SupportLevelFeasibilityError("bound input population changed")
    return frame


def _view_count_record(rows: pd.DataFrame, view: dict[str, Any]) -> dict[str, Any]:
    prefix = f"h{view['level_horizon']}_{view['path']}"
    tested = rows[f"{prefix}_tested"].astype(bool)
    recovered = (
        tested
        & rows[f"{prefix}_recovery_completion"].eq(True)
        & rows[f"{prefix}_recovery_speed"].notna()
        & rows[f"{prefix}_recovery_volume_intensity"].notna()
    )
    tested_levels = rows.loc[tested, f"support_low{view['level_horizon']}"]
    bit_patterns = tested_levels.map(_level_bits)
    tested_days = int(tested.sum())
    recovered_days = int(recovered.sum())
    unique_levels = int(bit_patterns.nunique())
    repeated = tested_days >= 2
    twice_recovered = recovered_days >= 2
    constant = repeated and unique_levels == 1
    return {
        "tested_day_count": tested_days,
        "recovered_tested_day_count": recovered_days,
        "unique_tested_level_count": unique_levels,
        "repeated_test_sequence": repeated,
        "twice_recovered_sequence": twice_recovered,
        "constant_test_level": constant,
        "constant_level_repeated_test": constant,
        "constant_level_twice_recovered": constant and twice_recovered,
        "constant_level_bits": bit_patterns.iloc[0] if constant else None,
    }


def build_count_audit(spec: dict[str, Any], frame: pd.DataFrame) -> pd.DataFrame:
    identity = [
        "sequence_id",
        "target_year",
        "block_id",
        "market_view",
        "market_sequence_rank",
        "symbol",
    ]
    records: list[dict[str, Any]] = []
    for key, rows in frame.groupby(identity, sort=True):
        rows = rows.sort_values("relative_day")
        if len(rows) != 5 or rows["relative_day"].tolist() != [-5, -4, -3, -2, -1]:
            raise SupportLevelFeasibilityError(f"sequence conservation changed: {key[0]}")
        for view in spec["views"]:
            records.append(
                {
                    **dict(zip(identity, key, strict=True)),
                    "identity_view": view["name"],
                    "level_horizon": view["level_horizon"],
                    "path": view["path"],
                    "gate_family": view["gate_family"],
                    **_view_count_record(rows, view),
                }
            )
    output = (
        pd.DataFrame(records).sort_values(["identity_view", "sequence_id"]).reset_index(drop=True)
    )
    if len(output) != spec["population"]["exact_sequences"] * len(spec["views"]):
        raise SupportLevelFeasibilityError("count-audit population changed")
    return output


def _count_domains(frame: pd.DataFrame, field: str) -> dict[str, Any]:
    selected = frame.loc[frame[field].astype(bool)]
    return {
        "total": len(selected),
        "by_block": {
            "A": int(selected["target_year"].isin([2018, 2019, 2020]).sum()),
            "B": int(selected["target_year"].isin([2021, 2022, 2023]).sum()),
        },
        "by_year": {
            str(year): int(selected["target_year"].eq(year).sum()) for year in range(2018, 2024)
        },
        "by_market_view": {
            view: int(selected["market_view"].eq(view).sum())
            for view in ["ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD"]
        },
    }


def _distribution(frame: pd.DataFrame, field: str) -> dict[str, int]:
    counts = frame[field].value_counts().sort_index()
    return {str(value): int(count) for value, count in counts.items()}


def _passes_count_gate(counts: dict[str, Any], gates: dict[str, int], role: str) -> bool:
    return bool(
        counts["total"] >= gates[f"{role}_total_minimum"]
        and all(
            value >= gates[f"{role}_each_block_minimum"] for value in counts["by_block"].values()
        )
        and all(value >= gates[f"{role}_each_year_minimum"] for value in counts["by_year"].values())
    )


def evaluate_adequacy(spec: dict[str, Any], audit: pd.DataFrame) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    passes: list[bool] = []
    for view in spec["views"]:
        frame = audit.loc[audit["identity_view"].eq(view["name"])]
        repeated_all = _count_domains(frame, "repeated_test_sequence")
        recovered_all = _count_domains(frame, "twice_recovered_sequence")
        repeated = _count_domains(frame, "constant_level_repeated_test")
        recovered = _count_domains(frame, "constant_level_twice_recovered")
        if view["name"] == "L20_CONT" and (
            repeated_all["total"] != spec["population"]["primary_repeated_test_sequences"]
            or recovered_all["total"] != spec["population"]["primary_twice_recovered_sequences"]
        ):
            raise SupportLevelFeasibilityError("primary parent counts changed")
        gates = spec["adequacy_gates"][view["gate_family"]]
        repeated_pass = _passes_count_gate(repeated, gates, "constant_repeated")
        recovered_pass = _passes_count_gate(recovered, gates, "constant_twice_recovered")
        view_pass = repeated_pass and recovered_pass
        passes.append(view_pass)
        evidence[view["name"]] = {
            "all_repeated_test": repeated_all,
            "all_twice_recovered": recovered_all,
            "constant_level_repeated_test": repeated,
            "constant_level_twice_recovered": recovered,
            "tested_day_count_distribution": _distribution(frame, "tested_day_count"),
            "unique_tested_level_count_distribution": _distribution(
                frame, "unique_tested_level_count"
            ),
            "repeated_gate_pass": repeated_pass,
            "twice_recovered_gate_pass": recovered_pass,
            "view_pass": view_pass,
        }
    return {"views": evidence, "all_views_pass": all(passes)}


def manual_case_audit(
    spec: dict[str, Any], frame: pd.DataFrame, audit: pd.DataFrame
) -> dict[str, Any]:
    primary = audit.loc[
        audit["identity_view"].eq("L20_CONT") & audit["constant_level_repeated_test"].astype(bool)
    ]
    selected = sorted(
        primary["sequence_id"].astype(str),
        key=lambda value: (_case_hash(value), value),
    )[: spec["audits"]["manual_scalar_cases"]]
    if len(selected) != spec["audits"]["manual_scalar_cases"]:
        raise SupportLevelFeasibilityError("manual scalar case support changed")
    audit_index = audit.set_index(["identity_view", "sequence_id"])
    cases: dict[str, Any] = {}
    for sequence_id in selected:
        rows = frame.loc[frame["sequence_id"].eq(sequence_id)].sort_values("relative_day")
        tested_days = 0
        recovered_days = 0
        bit_patterns: list[str] = []
        for row in rows.itertuples(index=False):
            if bool(row.h20_cont_tested):
                tested_days += 1
                bit_patterns.append(_level_bits(row.support_low20))
                recovered = (
                    bool(row.h20_cont_recovery_completion)
                    and pd.notna(row.h20_cont_recovery_speed)
                    and pd.notna(row.h20_cont_recovery_volume_intensity)
                )
                recovered_days += int(recovered)
        expected = audit_index.loc[("L20_CONT", sequence_id)]
        exact = (
            tested_days == expected.tested_day_count
            and recovered_days == expected.recovered_tested_day_count
            and len(set(bit_patterns)) == expected.unique_tested_level_count
            and len(set(bit_patterns)) == 1
            and bit_patterns[0] == expected.constant_level_bits
        )
        if not exact:
            raise SupportLevelFeasibilityError(
                f"manual scalar identity disagreement: {sequence_id}"
            )
        cases[sequence_id] = {
            "tested_days": tested_days,
            "recovered_days": recovered_days,
            "level_bits": bit_patterns[0],
            "exact": True,
        }
    return {"selected_sequence_ids": selected, "cases": cases, "all_exact": True}


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-SUPPORT-LVL-DATA-001 exact-level feasibility",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
    ]
    for view in ["L20_CONT", "L10_CONT", "L40_CONT", "L20_AUCTION"]:
        evidence = result["adequacy"]["views"][view]
        repeated = evidence["constant_level_repeated_test"]["total"]
        recovered = evidence["constant_level_twice_recovered"]["total"]
        lines.append(
            f"- {view}: constant repeated/twice-recovered {repeated}/{recovered}; "
            f"gate `{evidence['view_pass']}`."
        )
    lines.extend(
        [
            "- Exact identity uses round-trip binary64 bits; no tolerance or rounding.",
            (
                "- Zero raw minute/daily partition rows and zero trajectory/process "
                "estimates were read."
            ),
            (
                "- Passing is same-coordinate sample feasibility only, not support "
                "defense or usefulness."
            ),
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Count audit SHA-256: `{result['hashes']['count_audit_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    started = time.monotonic()
    spec = _load_spec()
    _resource_guard(spec, started)
    frame = _load_inputs(spec)
    audit = build_count_audit(spec, frame)
    adequacy = evaluate_adequacy(spec, audit)
    manual = manual_case_audit(spec, frame, audit)
    audit.to_csv(COUNT_PATH, index=False, lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": "MKT-SUPPORT-LVL-DATA-001",
        "status": (
            "COMPLETE_SAME_LEVEL_SAMPLE_ADEQUACY_PASS"
            if adequacy["all_views_pass"]
            else "COMPLETE_SAME_LEVEL_SAMPLE_INADEQUATE"
        ),
        "population": {
            "sequences": spec["population"]["exact_sequences"],
            "cohort_rows": len(frame),
            "unique_physical_sessions": len(frame[["symbol", "trade_date"]].drop_duplicates()),
            "raw_minute_rows_read": 0,
            "raw_daily_partition_rows_read": 0,
        },
        "adequacy": adequacy,
        "manual_scalar_audit": manual,
        "process_estimates_constructed": False,
        "trajectory_or_direction_fields_read": [],
        "future_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "support_defense_claim": "NONE",
        "prediction_or_usefulness_claim": "NONE",
        "hashes": {
            "spec_sha256": _sha256_file(SPEC_PATH),
            "count_audit_sha256": _sha256_file(COUNT_PATH),
            "bound_inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable_bytes = sum(path.stat().st_size for path in [COUNT_PATH, RESULT_PATH, REPORT_PATH])
    if durable_bytes > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise SupportLevelFeasibilityError("durable output ceiling breached")
    _resource_guard(spec, started)
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "all_views_pass": completed["adequacy"]["all_views_pass"],
                "primary": completed["adequacy"]["views"]["L20_CONT"],
            },
            indent=2,
            sort_keys=True,
        )
    )
