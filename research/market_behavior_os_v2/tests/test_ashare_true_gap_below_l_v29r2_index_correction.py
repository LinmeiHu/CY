from __future__ import annotations

import json
import stat
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_index_correction_asset_v29r2 as builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_index_correction as runner,
)


def test_corrected_selector_normalizes_nondefault_index() -> None:
    timed = pd.DataFrame(
        {
            "symbol": ["600000.SH", "600000.SH", "000001.SZ"],
            "announcement_key": ["a", "b", "c"],
            "causal_available_at": pd.to_datetime(
                ["2022-01-01 09:00", "2022-01-09 09:00", "2022-01-05 09:00"]
            ).tz_localize("Asia/Shanghai"),
        },
        index=[19, 41, 87],
    )
    entries = pd.DataFrame(
        {
            "gap_id": ["g1"],
            "symbol": ["600000.SH"],
            "signal_date": [pd.Timestamp("2022-01-10")],
            "signal_time": [pd.Timestamp("2022-01-10 15:00")],
        }
    )

    selected, audit = runner.corrected_select_window_routes(timed, entries)

    assert isinstance(selected.index, pd.RangeIndex)
    assert selected.announcement_key.tolist() == ["a", "b"]
    assert audit["window_route_keys_selected_before_title_projection"] == 2


def test_exact_frame_check_rejects_selector_field_tamper() -> None:
    expected = pd.DataFrame({"gap_id": ["g1"], "v29r2_open_events_json": ["[]"], "count": [0]})
    tampered = expected.copy()
    tampered.loc[0, "v29r2_open_events_json"] = '[{"unexpected":true}]'

    with pytest.raises(runner.IndexCorrectionError, match="selector_audit"):
        runner.require_frame_exact("selector_audit", tampered, expected)


def test_failed_stage_a_boundary_is_semantically_revalidated() -> None:
    builder.validate_failure_boundary()


def test_failed_stage_a_boundary_rejects_fingerprint_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hashes = dict(builder.EXPECTED_HASHES)
    hashes["failed_stage_a_title_route_selection"] = "0" * 64
    monkeypatch.setattr(builder, "EXPECTED_HASHES", hashes)

    with pytest.raises(builder.CorrectionAssetError, match="frozen predecessor artifact drifted"):
        builder.validate_failure_boundary()


def test_wrapper_build_requires_frozen_output_root_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    monkeypatch.setattr(builder, "CORRECTED_OUTPUT_ROOT", occupied)

    with pytest.raises(builder.CorrectionAssetError, match="must be absent"):
        builder.validate_dependencies(builder.NEW_RUNNER, require_corrected_output_absent=True)


def test_stage_commands_reject_alternate_output_root(tmp_path: Path) -> None:
    wrong = tmp_path / "alternate"
    with pytest.raises(runner.IndexCorrectionError, match="frozen corrected output root"):
        runner.run_stage_a(tmp_path / "asset", tmp_path / "parent", wrong)
    with pytest.raises(runner.IndexCorrectionError, match="frozen corrected output root"):
        runner.run_stage_b(
            tmp_path / "asset",
            tmp_path / "parent",
            tmp_path / "outcomes",
            tmp_path / "daily",
            wrong,
            "a" * 64,
        )


def test_stage_b_seals_exclusive_attempt_before_first_outcome_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OutcomeReadReached(RuntimeError):
        pass

    output_root = tmp_path / "frozen-output"
    asset_root = tmp_path / "asset"
    parent = tmp_path / "parent.parquet"
    outcomes = tmp_path / "outcomes.parquet"
    daily = tmp_path / "daily.parquet"
    expected_stage_sha = "a" * 64
    monkeypatch.setattr(runner, "EXPECTED_CORRECTED_OUTPUT_ROOT", output_root)

    def fake_sha(path: Path) -> str:
        return f"sha:{Path(path).resolve()}"

    identity = {
        "bound_artifacts": {
            role: {"path": str(path), "sha256": fake_sha(path)}
            for role, path in (
                ("parent_selected", parent),
                ("parent_outcomes", outcomes),
                ("parent_outcome_daily", daily),
            )
        },
        "correction": {"sha256": "c" * 64},
    }
    monkeypatch.setattr(
        runner,
        "verify_stage_a",
        lambda *_args: {
            "stage_a_freeze_sha256": expected_stage_sha,
            "asset_identity": identity,
            "hashes": {
                "selected_entries": fake_sha(output_root / "stage_a/selected_entries.parquet")
            },
        },
    )
    original_read_json = runner.read_json

    def fake_read_json(path: Path, label: str) -> dict[str, object]:
        if Path(path).name == "freeze.json":
            return {
                "parent_outcome_and_daily_bytes_hashed_for_identity": True,
                "outcome_or_daily_parquet_content_rows_parsed": False,
                "hashes": {
                    "selected_entries": fake_sha(output_root / "stage_a/selected_entries.parquet")
                },
            }
        return original_read_json(path, label)

    attempt_path = output_root / "stage_b_pre_outcome_attempt_seal.json"

    def fake_read_parquet(path: Path, *args: object, **kwargs: object) -> pd.DataFrame:
        assert attempt_path.is_file()
        assert attempt_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
        if Path(path).resolve() == outcomes.resolve():
            raise OutcomeReadReached
        return pd.DataFrame()

    monkeypatch.setattr(runner, "sha256", fake_sha)
    monkeypatch.setattr(runner, "read_json", fake_read_json)
    monkeypatch.setattr(runner.pd, "read_parquet", fake_read_parquet)

    with pytest.raises(OutcomeReadReached):
        runner.run_stage_b(
            asset_root,
            parent,
            outcomes,
            daily,
            output_root,
            expected_stage_sha,
        )

    seal = json.loads(attempt_path.read_text())
    assert seal["outcome_or_daily_parquet_content_rows_parsed"] is False
    assert seal["stage_a_freeze"]["sha256"] == expected_stage_sha
