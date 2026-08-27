from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import runpy
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from cyq_game.chip.checkpoint_journal_contract import SELLER_MODEL_ORDER, logical_sha256
from cyq_game.chip.checkpoint_journal_writer import (
    manifest_coverage,
    verify_root,
    write_json,
)

PROTOTYPE = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/prototype_checkpoint_journal_writer_3symbol.py")
)
CapturedCell = PROTOTYPE["CapturedCell"]
CapturedCheckpoint = PROTOTYPE["CapturedCheckpoint"]
CapturedModelState = PROTOTYPE["CapturedModelState"]
write_symbol_artifacts = PROTOTYPE["write_symbol_artifacts"]


def _stamp(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


def _state(day: date, model: str, position: int) -> CapturedModelState:
    stamp = _stamp(day)
    cell = CapturedCell(
        cell_id=position + 1,
        cost_bucket_id=100 + position,
        holding_days=1,
        sensitivity=("NEUTRAL", "ACTIVE", "STICKY")[position],
        acquisition_cost=10.0 + position,
        economic_break_even=10.0 + position,
        shares=100.0,
        initialization_prior_units=0.0,
    )
    return CapturedModelState(
        seller_model=model,
        decision_at=stamp,
        available_at=stamp,
        effective_at=stamp,
        phase="POST",
        snapshot_id=f"chip_snapshot_v2_{position + 1:064x}",
        model_version="real-chip-inventory-v2.1",
        grid_version="log-grid-25bp-v1",
        cells=(cell,),
        free_float_shares=100.0,
        latent_supply_shares=0.0,
        conservation_error=0.0,
        input_snapshot_ids=(f"input-{position}",),
        pit_grade="PIT_STRICT",
        hard_valid=True,
        quality_reason_codes=(),
    )


def test_writer_round_trips_checkpoint_journal_index_and_candidates(tmp_path: Path) -> None:
    day = date(2020, 1, 2)
    stamp = _stamp(day)
    operator_rows = []
    for position, model in enumerate(SELLER_MODEL_ORDER):
        operator_rows.append(
            {
                "trade_date": day,
                "seller_model": model,
                "snapshot_id": f"chip_snapshot_v2_{position + 1:064x}",
                "transition_id": f"origin_survival_transition_{position + 4:064x}",
                "input_snapshot_digest": bytes([position + 1]) * 32,
                "decision_at": stamp,
                "available_at": stamp,
                "free_float_shares": 100.0,
                "conservation_error_shares": 0.0,
                "action_provenance_ids": [],
                "hard_valid": True,
                "quality_reason_codes": [],
            }
        )
    operator_path = tmp_path / "operator.parquet"
    pq.write_table(pa.Table.from_pylist(operator_rows), operator_path)
    feature_row = {
        "symbol": "002260.SZ",
        "trade_date": day,
        "available_at": stamp,
        "dominant_band_mass": 0.5,
        "tracked_base_peak": 10.0,
        "peak_track_id": "track-1",
        "peak_track_band_lower": 9.0,
        "peak_track_band_upper": 11.0,
        "peak_track_state": "CONTINUE",
        "peak_track_ambiguous": False,
        "peak_track_split": False,
        "peak_track_merge": False,
        "peak_track_lost": False,
        "peak_definition_version": "canonical-chip-peak-v2",
        "peak_track_version": "temporal-chip-peak-v2",
    }
    feature_path = tmp_path / "feature.parquet"
    pq.write_table(pa.Table.from_pylist([feature_row]), feature_path)
    terminal_path = tmp_path / "terminal.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [{"seller_model": model, "value": float(index)} for index, model in enumerate(SELLER_MODEL_ORDER)]
        ),
        terminal_path,
    )
    digest = logical_sha256("phase2-test")
    artifact_root = tmp_path / "artifact"
    captured = CapturedCheckpoint(
        symbol="002260.SZ",
        trading_date=day,
        model_states=tuple(_state(day, model, index) for index, model in enumerate(SELLER_MODEL_ORDER)),
    )
    artifact = write_symbol_artifacts(
        root=artifact_root,
        symbol="002260.SZ",
        captured_checkpoints={day: captured},
        operator_path=operator_path,
        feature_source_path=feature_path,
        terminal_source_path=terminal_path,
        dependency_manifest_digest=digest,
        replay_parameter_manifest_digest=digest,
        replay_contract_hash=digest,
        semantic_fingerprint=digest,
        runtime_fingerprint=digest,
        terminal_completeness_digest=digest,
        bundle_id="test-bundle",
        root_id="test-root",
    )
    coverage = manifest_coverage(
        (artifact,), bundle_id="test-bundle", root_id="test-root"
    )
    parts = [item.__dict__ for item in artifact.file_metadata]
    write_json(
        artifact_root / "manifest.json",
        {"coverage": coverage, "parts": parts},
    )
    verify_root(artifact_root)
    assert not (artifact_root / "index.json").exists()
    assert not any(item["kind"] == "terminal" for item in parts)
    assert artifact.terminal_path == ""
    assert artifact.trading_days == 1
    assert artifact.model_rows == 3
    assert artifact.fallback_rows == 0
