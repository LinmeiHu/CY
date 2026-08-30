#!/usr/bin/env python3
"""Test one preregistered PIT-B chip-base coherence mechanism."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_day5_market_stock_decomposition as d5d  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-CBC-001_spec.json"
TRADES = WORK / "artifacts/yearly_trades.csv"
CONTROLS = WORK / "artifacts/pre_entry_transitions.csv"
REGISTRY = ROOT / "configs/data_asset_registry.json"
CHIP_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/"
    "chip_state_features_semantic_v3_2018_2026"
)
CHIP_INVENTORY = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-011-chip-state-features-semantic-v3-20260822.json"
)
CHIP_MANIFEST = CHIP_ROOT / "manifest.json"
CHIP_AUDIT = Path(
    "/Users/linmei/Documents/CY/data/audit/"
    "cyq_chip_state_features_semantic_v3_gate.json"
)
OUTPUT_TABLE = WORK / "artifacts/chip_base_coherence_attribution.csv"
OUTPUT_JSON = WORK / "artifacts/chip_base_coherence_attribution.json"
REPORT = WORK / "reports/chip_base_coherence_attribution.md"
EVIDENCE_PACKET = WORK / "reports/chip_base_coherence_evidence_packet.md"

BASE_CONTROLS = d5d.BASE_CONTROLS
DISCOVERY_START = pd.Timestamp("2020-01-01")
DISCOVERY_END = pd.Timestamp("2023-12-31")


class ChipCoherenceError(RuntimeError):
    """Raised when a frozen identity, PIT, or population invariant fails."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_stream(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def validate_registry() -> dict[str, Any]:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assets: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("asset_id") == "CY-011":
                assets.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    if len(assets) != 1:
        raise ChipCoherenceError("CY-011 registry identity is not unique")
    asset = assets[0]
    expected = {
        "status": "RESEARCH_CONDITIONAL",
        "pit_grade": "B",
        "physical_state": "MATERIALIZED_IMMUTABLE_CANDIDATE",
        "location": str(CHIP_ROOT),
    }
    for key, value in expected.items():
        if asset.get(key) != value:
            raise ChipCoherenceError(f"CY-011 registry field changed: {key}")
    coverage = asset.get("coverage", {})
    if (
        coverage.get("target_discovery_range") != "2020-01-01..2023-12-31"
        or coverage.get("target_holdout_range") != "2024-01-01..2026-08-12"
    ):
        raise ChipCoherenceError("CY-011 discovery/holdout boundary changed")
    if asset.get("quality_evidence", {}).get("gate_pass") is not True:
        raise ChipCoherenceError("CY-011 quality gate is not passing")
    return asset


def validate_inventory() -> dict[str, Any]:
    payload = json.loads(CHIP_INVENTORY.read_text(encoding="utf-8"))
    if Path(payload.get("root", "")) != CHIP_ROOT or len(payload.get("files", [])) != 81:
        raise ChipCoherenceError("CY-011 inventory root/count changed")
    failures: list[dict[str, Any]] = []
    total_bytes = 0
    for item in payload["files"]:
        path = CHIP_ROOT / item["path"]
        total_bytes += int(item["size"])
        if not path.is_file():
            failures.append({"path": item["path"], "reason": "MISSING"})
            continue
        if path.stat().st_size != int(item["size"]):
            failures.append({"path": item["path"], "reason": "SIZE"})
            continue
        if sha256_stream(path) != item["sha256"]:
            failures.append({"path": item["path"], "reason": "SHA256"})
    if failures:
        raise ChipCoherenceError(f"CY-011 inventory mismatch: {failures[:3]}")
    return {"inventory_files": 81, "inventory_bytes": total_bytes}


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-CBC-001":
        raise ChipCoherenceError("unexpected experiment identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_CHIP_OUTCOME_ASSOCIATION":
        raise ChipCoherenceError("experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = resolve_path(binding["path"])
        actual = sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise ChipCoherenceError(f"frozen input mismatch: {mismatches}")
    validate_registry()
    inventory_audit = validate_inventory()
    return spec, {**identities, **{k: str(v) for k, v in inventory_audit.items()}}


def within_year_rank(frame: pd.DataFrame, column: str) -> pd.Series:
    return frame.groupby("entry_year", sort=False)[column].rank(
        method="average", pct=True
    )


def build_composites(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if (result.cyqk_close_pre <= 0).any():
        raise ChipCoherenceError("non-positive chip reference close")
    result["upward_cost_migration"] = (
        result.average_cost_delta / result.cyqk_close_pre
    )
    result["narrow_i90"] = -result.i90_width_pct
    result["narrow_i70"] = -result.i70_width_pct
    result["chip_base_coherence"] = pd.concat(
        [
            within_year_rank(result, "narrow_i90"),
            within_year_rank(result, "i90_base_retention"),
            within_year_rank(result, "upward_cost_migration"),
        ],
        axis=1,
    ).mean(axis=1)
    result["chip_base_coherence_i70"] = pd.concat(
        [
            within_year_rank(result, "narrow_i70"),
            within_year_rank(result, "i70_base_retention"),
            within_year_rank(result, "upward_cost_migration"),
        ],
        axis=1,
    ).mean(axis=1)
    return result


def load_frame(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    trades = pd.read_csv(
        TRADES,
        usecols=[
            "trade_id",
            "baseline_block",
            "symbol",
            "entry_signal_date",
            "mfe",
            "realized_pnl",
            "holding_trading_days",
            "canonical_exit_reason",
        ],
    )
    controls = pd.read_csv(
        CONTROLS,
        usecols=[
            "trade_id",
            "entry_year",
            "entry_industry",
            "extreme_winner",
            "winner20",
            "false_breakout",
            "severe_loss",
            *BASE_CONTROLS,
        ],
    )
    frame = trades.merge(controls, on="trade_id", validate="one_to_one")
    frame["entry_signal_date"] = pd.to_datetime(frame.entry_signal_date)
    frame = frame[
        frame.entry_signal_date.between(DISCOVERY_START, DISCOVERY_END)
    ].copy()
    if frame.entry_signal_date.max() > DISCOVERY_END:
        raise ChipCoherenceError("locked validation row entered discovery sample")
    entry_keys = frame[["trade_id", "symbol", "entry_signal_date"]].copy()
    connection = duckdb.connect(":memory:")
    connection.register("entry_keys", entry_keys)
    feature_glob = str(CHIP_ROOT / "bucket=*/data.parquet").replace("'", "''")
    chip = connection.execute(
        f"""
        SELECT
          e.trade_id,
          f.trade_date AS chip_trade_date,
          f.available_at,
          f.daily_snapshot_id,
          f.minute_snapshot_id,
          f.state_version,
          f.config_sha256,
          f.code_sha256,
          f.chip_input_valid,
          f.daily_hard_valid,
          f.minute_hard_valid,
          f.minute_requirement_waived,
          f.state_chain_valid,
          f.strict_sample,
          f.research_sample,
          f.daily_research_sample,
          f.research_suspension_bridge,
          f.invalid_reason,
          f.mass_sum,
          f.state_quality,
          f.cyqk_close_pre,
          f.i90_width_pct,
          f.i70_width_pct,
          f.i90_base_retention,
          f.i70_base_retention,
          f.migration_mass,
          f.average_cost_delta
        FROM entry_keys e
        LEFT JOIN read_parquet('{feature_glob}') f
          ON f.symbol = e.symbol
         AND f.trade_date = CAST(e.entry_signal_date AS DATE)
        WHERE e.entry_signal_date BETWEEN DATE '2020-01-01' AND DATE '2023-12-31'
        """
    ).fetchdf()
    connection.close()
    if len(chip) != len(frame) or chip.trade_id.duplicated().any():
        raise ChipCoherenceError("CY-011 join is not row-conserving one-to-one")
    frame = frame.merge(chip, on="trade_id", validate="one_to_one")
    required = [
        "chip_trade_date",
        "available_at",
        "daily_snapshot_id",
        "minute_snapshot_id",
        "mass_sum",
        "cyqk_close_pre",
        "i90_width_pct",
        "i70_width_pct",
        "i90_base_retention",
        "i70_base_retention",
        "migration_mass",
        "average_cost_delta",
        *BASE_CONTROLS,
    ]
    if frame[required].isna().any().any():
        raise ChipCoherenceError("required CY-011 feature/control is missing")
    if pd.to_datetime(frame.chip_trade_date).max() > DISCOVERY_END:
        raise ChipCoherenceError("locked chip row was materialized")
    expected_time = frame.entry_signal_date + pd.Timedelta(hours=15, minutes=30)
    if not (pd.to_datetime(frame.available_at) == expected_time).all():
        raise ChipCoherenceError("CY-011 availability is not exact signal-day 15:30")
    true_flags = [
        "chip_input_valid",
        "daily_hard_valid",
        "minute_hard_valid",
        "state_chain_valid",
        "strict_sample",
        "research_sample",
        "daily_research_sample",
    ]
    false_flags = ["minute_requirement_waived", "research_suspension_bridge"]
    if not frame[true_flags].all(axis=None) or frame[false_flags].any(axis=None):
        raise ChipCoherenceError("CY-011 validity flags changed")
    if frame.invalid_reason.notna().any():
        raise ChipCoherenceError("CY-011 discovery row has an invalid reason")
    mass_error = float((frame.mass_sum - 1.0).abs().max())
    if mass_error > 1e-8:
        raise ChipCoherenceError("chip mass does not conserve")
    frame = build_composites(frame)
    frame["opportunity20"] = frame.mfe >= 0.20
    frame["non_false_breakout"] = 1.0 - frame.false_breakout.astype(float)
    sample = spec["sample"]
    audit = {
        "discovery_rows": int(len(frame)),
        "control_complete": int(frame[list(BASE_CONTROLS)].notna().all(axis=1).sum()),
        "opportunity20": int(frame.opportunity20.sum()),
        "false_breakout": int(frame.false_breakout.sum()),
        "severe_loss": int(frame.severe_loss.sum()),
        "unique_securities": int(frame.symbol.nunique()),
        "unique_industries": int(frame.entry_industry.nunique()),
    }
    if audit != {key: sample[key] for key in audit}:
        raise ChipCoherenceError(f"frozen discovery sample changed: {audit}")
    audit.update(
        {
            "maximum_mass_error": mass_error,
            "minimum_state_quality": float(frame.state_quality.min()),
            "returned_min_date": str(pd.to_datetime(frame.chip_trade_date).min().date()),
            "returned_max_date": str(pd.to_datetime(frame.chip_trade_date).max().date()),
            "locked_rows_materialized": 0,
            "available_at_timestamp": "SIGNAL_SESSION_15:30_ASIA_SHANGHAI",
            "potential_action_timestamp": "NEXT_VALID_SESSION_OR_LATER_ONLY; DISCOVERY_AUTHORIZES_NO_ACTION",
            "thresholds_or_rules_tested": 0,
            "strategy_replays": 0,
        }
    )
    return frame, audit


def top_pnl_flag(frame: pd.DataFrame, count: int) -> pd.Series:
    selected = frame.nlargest(count, "realized_pnl").index
    return frame.index.to_series().isin(selected)


def analyze(frame: pd.DataFrame) -> dict[str, Any]:
    feature = "chip_base_coherence"
    raw = wla.rank_association(frame, feature, "mfe")
    controlled = d5d.controlled_loyo(frame, feature, "mfe")
    i70 = wla.rank_association(frame, "chip_base_coherence_i70", "mfe")
    opportunity = wla.rank_association(frame, feature, "opportunity20")
    non_false = wla.rank_association(frame, feature, "non_false_breakout")
    duration_exit = d5d.partial_rank(
        frame,
        feature,
        "mfe",
        extra_controls=("holding_trading_days",),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    ex_top4 = wla.rank_association(frame.loc[~top_pnl_flag(frame, 4)], feature, "mfe")
    ex_severe = wla.rank_association(frame.loc[~frame.severe_loss], feature, "mfe")
    security = wla.omit_group_sensitivity(frame, feature, "mfe", "symbol")
    industry = wla.omit_group_sensitivity(frame, feature, "mfe", "entry_industry")
    blocks = {
        str(name): wla.safe_spearman(rows[feature], rows.mfe)
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    components = {
        "narrow_i90": wla.rank_association(frame, "narrow_i90", "mfe"),
        "i90_base_retention": wla.rank_association(
            frame, "i90_base_retention", "mfe"
        ),
        "upward_cost_migration": wla.rank_association(
            frame, "upward_cost_migration", "mfe"
        ),
    }
    raw_gate = bool(
        raw["rho"] is not None
        and raw["rho"] >= 0.12
        and raw["within_year_rank_rho"] is not None
        and raw["within_year_rank_rho"] > 0
        and raw["loyo_positive_count"] == 4
    )
    controlled_gate = bool(
        controlled["partial_rank_rho"] is not None
        and controlled["partial_rank_rho"] >= 0.10
        and controlled["loyo_positive_count"] == 4
    )
    neighbor_gate = bool(
        i70["rho"] is not None
        and i70["rho"] > 0
        and i70["loyo_positive_count"] >= 3
        and opportunity["rho"] is not None
        and opportunity["rho"] > 0
        and opportunity["loyo_positive_count"] >= 3
        and non_false["rho"] is not None
        and non_false["rho"] > 0
        and non_false["loyo_positive_count"] >= 3
    )
    block_rhos = [packet["rho"] for packet in blocks.values()]
    temporal_gate = bool(
        len(block_rhos) == 2
        and all(value is not None and value > 0 for value in block_rhos)
    )
    component_rhos = [packet["rho"] for packet in components.values()]
    component_gate = bool(
        sum(value is not None and value > 0 for value in component_rhos) >= 2
        and all(value is not None and value >= -0.05 for value in component_rhos)
    )
    falsification_gate = bool(
        duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.08
        and ex_top4["rho"] is not None
        and ex_top4["rho"] > 0
        and ex_severe["rho"] is not None
        and ex_severe["rho"] > 0
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
        and component_gate
    )
    if all((raw_gate, controlled_gate, neighbor_gate, temporal_gate, falsification_gate)):
        decision = "VALIDATE"
        verdict = "CHIP_BASE_COHERENCE_DESERVES_LOCKED_TEMPORAL_VALIDATION"
    elif raw_gate and controlled_gate:
        decision = "REFINE"
        verdict = "CHIP_BASE_COHERENCE_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    elif raw_gate:
        decision = "PIVOT"
        verdict = "RAW_CHIP_COHERENCE_IS_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_CHIP_BASE_COHERENCE_OPPORTUNITY_EFFECT"
    return {
        "experiment_id": "EXP-CBC-001",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "raw": raw,
            "controlled": controlled,
            "i70_neighbor": i70,
            "opportunity20": opportunity,
            "non_false_breakout": non_false,
            "duration_exit_control": duration_exit,
            "ex_top4_pnl": ex_top4,
            "ex_severe_loss": ex_severe,
            "leave_one_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "components": components,
            "raw_gate": raw_gate,
            "controlled_gate": controlled_gate,
            "neighbor_gate": neighbor_gate,
            "temporal_gate": temporal_gate,
            "component_gate": component_gate,
            "falsification_gate": falsification_gate,
        },
        "strategy_modification": "NONE",
        "holdout_access": "NONE_2024_2026_REMAINS_LOCKED",
        "interpretation_boundary": (
            "PIT-B discovery on already-consumed 2020-2023 outcomes cannot authorize "
            "a chip filter, threshold, ranking, sizing, entry, exit, or production rule"
        ),
    }


def fmt(value: Any) -> str:
    number = wla.finite_or_none(value)
    return "NA" if number is None else f"{number:.3f}"


def build_report(result: dict[str, Any], audit: dict[str, Any]) -> str:
    primary = result["primary"]
    return "\n".join(
        [
            "# Chip-base coherence attribution",
            "",
            "EXP-CBC-001 tests one frozen 2020-2023 PIT-B discovery composite against MFE. The 2024-2026 validation range remains locked.",
            "",
            "## Frozen tests",
            "",
            f"- Discovery rows/control-complete: `{audit['discovery_rows']}` / `{audit['control_complete']}`.",
            f"- Raw/controlled MFE rho: `{fmt(primary['raw']['rho'])}` / `{fmt(primary['controlled']['partial_rank_rho'])}`.",
            f"- I70/opportunity20/non-false-breakout neighbors: `{fmt(primary['i70_neighbor']['rho'])}` / `{fmt(primary['opportunity20']['rho'])}` / `{fmt(primary['non_false_breakout']['rho'])}`.",
            f"- Gates raw/control/neighbor/temporal/component/falsification: `{primary['raw_gate']}` / `{primary['controlled_gate']}` / `{primary['neighbor_gate']}` / `{primary['temporal_gate']}` / `{primary['component_gate']}` / `{primary['falsification_gate']}`.",
            "",
            "## Decision",
            "",
            f"`{result['decision']}` / `{result['mechanism_verdict']}`.",
            "",
            "No threshold, signal, filter, replay, entry, exit, sizing, ranking, or strategy modification was tested or authorized.",
            "",
        ]
    )


def main() -> int:
    spec, identities = validate_spec()
    frame, audit = load_frame(spec)
    result = analyze(frame)
    result.update(
        {
            "spec_sha256": sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_PIT_B_DISCOVERY",
            "duckdb_version": duckdb.__version__,
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_signal_date",
        "entry_year",
        "entry_industry",
        "available_at",
        "daily_snapshot_id",
        "minute_snapshot_id",
        "state_version",
        "mass_sum",
        "state_quality",
        "cyqk_close_pre",
        "i90_width_pct",
        "i70_width_pct",
        "i90_base_retention",
        "i70_base_retention",
        "migration_mass",
        "average_cost_delta",
        "upward_cost_migration",
        "narrow_i90",
        "narrow_i70",
        "chip_base_coherence",
        "chip_base_coherence_i70",
        "mfe",
        "opportunity20",
        "false_breakout",
        "non_false_breakout",
        "severe_loss",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        *BASE_CONTROLS,
    ]
    atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    report = build_report(result, audit)
    atomic_write(REPORT, report)
    atomic_write(
        EVIDENCE_PACKET,
        report.replace(
            "# Chip-base", "# EXP-CBC-001 structured evidence — Chip-base"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
