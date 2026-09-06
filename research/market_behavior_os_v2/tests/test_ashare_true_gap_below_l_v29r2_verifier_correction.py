from __future__ import annotations

import json
import stat
from datetime import timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
import pytz

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_verifier_correction_asset_v29r2 as builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_verifier_correction as runner,
)


def classified_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    values = ["2022-01-01 09:00:00", "2022-01-02 09:00:00"]
    persisted = pd.DataFrame(
        {
            "announcement_key": ["a", "b"],
            "available_at": pd.DatetimeIndex(values, tz=pytz.timezone("Asia/Shanghai")),
            "risk_family": [None, "REGULATORY_INVESTIGATION"],
            "count": pd.Series([1, 2], dtype="int64"),
        }
    )
    reproduced = pd.DataFrame(
        {
            "announcement_key": ["a", "b"],
            "available_at": pd.DatetimeIndex(values, tz=ZoneInfo("Asia/Shanghai")),
            "risk_family": [pd.NA, "REGULATORY_INVESTIGATION"],
            "count": pd.Series([1, 2], dtype="int64"),
        }
    )
    return persisted, reproduced


def test_canonical_comparator_allows_only_proven_representations() -> None:
    persisted, reproduced = classified_frames()

    audit = builder.require_classified_canonical_exact(persisted, reproduced)

    assert audit["frame_rows"] == 2
    assert audit["all_other_columns_dtype_value_order_exact"] is True


def test_canonical_comparator_rejects_available_at_instant_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced.loc[0, "available_at"] += pd.Timedelta(seconds=1)

    with pytest.raises(builder.VerifierCorrectionAssetError, match="UTC nanoseconds"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_wrong_timezone() -> None:
    persisted, reproduced = classified_frames()
    reproduced["available_at"] = reproduced["available_at"].dt.tz_convert("UTC")

    with pytest.raises(builder.VerifierCorrectionAssetError, match="Asia/Shanghai"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_fake_same_name_fixed_offset_timezone() -> None:
    persisted, reproduced = classified_frames()
    fake = timezone(timedelta(hours=8), name="Asia/Shanghai")
    reproduced["available_at"] = pd.DatetimeIndex(
        reproduced["available_at"].astype(str), tz=fake
    )

    with pytest.raises(builder.VerifierCorrectionAssetError, match="timezone backends"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_risk_na_mask_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced.loc[0, "risk_family"] = "REGULATORY_INVESTIGATION"

    with pytest.raises(builder.VerifierCorrectionAssetError, match="NA mask"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_nonnull_risk_value_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced.loc[1, "risk_family"] = "ILLEGAL_GUARANTEE"

    with pytest.raises(builder.VerifierCorrectionAssetError, match="non-null values"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_unapproved_risk_missing_scalar() -> None:
    persisted, reproduced = classified_frames()
    reproduced.loc[0, "risk_family"] = np.nan

    with pytest.raises(builder.VerifierCorrectionAssetError, match="unapproved missing"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_column_order_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced = reproduced[["available_at", "announcement_key", "risk_family", "count"]]

    with pytest.raises(builder.VerifierCorrectionAssetError, match="columns/order"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_row_order_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced = reproduced.iloc[::-1].reset_index(drop=True)

    with pytest.raises(builder.VerifierCorrectionAssetError, match="UTC nanoseconds"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_index_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced.index = pd.Index([2, 3])

    with pytest.raises(builder.VerifierCorrectionAssetError, match="index drifted"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_canonical_comparator_rejects_other_column_dtype_drift() -> None:
    persisted, reproduced = classified_frames()
    reproduced["count"] = reproduced["count"].astype("float64")

    with pytest.raises(builder.VerifierCorrectionAssetError, match="outside the two approved"):
        builder.require_classified_canonical_exact(persisted, reproduced)


def test_discrepancy_audit_binds_immutable_cy063_failure() -> None:
    audit = builder.validate_discrepancy_audit()

    assert audit["status"] == "FAILED_CLOSED_BEFORE_STAGE_B"
    assert audit["immutable_inventory"] == builder.CY063_STAGE_HASHES


def test_verify_only_creates_one_read_only_outer_freeze(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verification_root = tmp_path / "verification"
    stage_b_root = tmp_path / "stage-b"
    parent = tmp_path / "parent.parquet"
    asset = tmp_path / "asset"
    stage = {
        "classified_comparator": {"bounded": True},
        "parent_signals": 197,
        "selected_signals": 186,
        "rejected_signals": 11,
        "selected_by_signal_year": {
            "2022": 40,
            "2023": 10,
            "2024": 68,
            "2025": 36,
            "2026": 32,
        },
        "route_audit": {"rows": 7925},
        "selector_outputs_strict_exact": True,
        "execution_contract": {"target": "A67"},
    }
    identity = {"cy063_stage_a_verification": stage, "asset_id": "CY-064"}
    monkeypatch.setattr(runner, "EXPECTED_VERIFICATION_ROOT", verification_root)
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", stage_b_root)
    monkeypatch.setattr(runner, "verify_asset", lambda *_args: identity)

    result = runner.run_verify_only(asset, parent, verification_root, stage_b_root)

    freeze_path = verification_root / "verified_stage_a_freeze.json"
    assert result["outer_freeze"]["path"] == str(freeze_path)
    assert {item.name for item in verification_root.iterdir()} == {freeze_path.name}
    assert freeze_path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert verification_root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert not stage_b_root.exists()
    with pytest.raises(runner.VerifierCorrectionError, match="non-pristine"):
        runner.run_verify_only(asset, parent, verification_root, stage_b_root)


def test_verify_only_write_failure_seals_partial_root_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FreezeWriteFailure(RuntimeError):
        pass

    verification_root = tmp_path / "verification"
    stage_b_root = tmp_path / "stage-b"
    parent = tmp_path / "parent.parquet"
    asset = tmp_path / "asset"
    stage = {
        "classified_comparator": {"bounded": True},
        "parent_signals": 197,
        "selected_signals": 186,
        "rejected_signals": 11,
        "selected_by_signal_year": {
            "2022": 40,
            "2023": 10,
            "2024": 68,
            "2025": 36,
            "2026": 32,
        },
        "route_audit": {"rows": 7925},
        "selector_outputs_strict_exact": True,
        "execution_contract": {"target": "A67"},
    }
    identity = {"cy063_stage_a_verification": stage, "asset_id": "CY-064"}
    monkeypatch.setattr(runner, "EXPECTED_VERIFICATION_ROOT", verification_root)
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", stage_b_root)
    monkeypatch.setattr(runner, "verify_asset", lambda *_args: identity)

    def partial_write(path: Path, _value: object) -> None:
        path.write_text("partial", encoding="utf-8")
        raise FreezeWriteFailure

    monkeypatch.setattr(runner, "write_json_exclusive", partial_write)

    with pytest.raises(FreezeWriteFailure):
        runner.run_verify_only(asset, parent, verification_root, stage_b_root)

    partial = verification_root / "verified_stage_a_freeze.json"
    assert partial.is_file()
    assert partial.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert verification_root.stat().st_mode & (
        stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    ) == 0
    with pytest.raises(runner.VerifierCorrectionError, match="non-pristine"):
        runner.run_verify_only(asset, parent, verification_root, stage_b_root)


def test_stage_b_seal_is_first_file_before_outcome_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class OutcomeReadReached(RuntimeError):
        pass

    output_root = tmp_path / "stage-b"
    verification_root = tmp_path / "verification"
    asset = tmp_path / "asset"
    parent = tmp_path / "parent.parquet"
    outcomes = tmp_path / "outcomes.parquet"
    daily = tmp_path / "daily.parquet"
    expected_outer_sha = "a" * 64

    def fake_sha(path: Path) -> str:
        path = Path(path).resolve()
        selected_path = (runner.CY063_OUTPUT_ROOT / "stage_a/selected_entries.parquet").resolve()
        if path == selected_path:
            return builder.CY063_STAGE_HASHES["selected_entries.parquet"]
        return f"sha:{path}"

    identity = {
        "parent_sources": {
            role: {"path": str(path), "sha256": fake_sha(path)}
            for role, path in (
                ("selected", parent),
                ("outcomes", outcomes),
                ("outcome_daily", daily),
            )
        }
    }
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", output_root)
    monkeypatch.setattr(
        runner,
        "verify_outer_freeze",
        lambda *_args: {
            "outer_freeze_sha256": expected_outer_sha,
            "outer_freeze_path": str(verification_root / "verified_stage_a_freeze.json"),
            "asset_identity": identity,
            "cy063_stage_a_hashes": dict(builder.CY063_STAGE_HASHES),
        },
    )
    monkeypatch.setattr(runner, "sha256", fake_sha)
    attempt_path = output_root / "stage_b_pre_outcome_attempt_seal.json"

    def fake_read_parquet(path: Path, *args: object, **kwargs: object) -> pd.DataFrame:
        assert {item.name for item in output_root.iterdir()} == {attempt_path.name}
        assert attempt_path.stat().st_mode & (
            stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
        ) == 0
        if Path(path).resolve() == outcomes.resolve():
            raise OutcomeReadReached
        return pd.DataFrame()

    monkeypatch.setattr(runner.pd, "read_parquet", fake_read_parquet)

    with pytest.raises(OutcomeReadReached):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            expected_outer_sha,
        )

    seal = json.loads(attempt_path.read_text())
    assert seal["outcome_or_daily_parquet_content_rows_parsed"] is False
    assert seal["outer_freeze"]["sha256"] == expected_outer_sha
    assert output_root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    with pytest.raises(runner.VerifierCorrectionError, match="repeated/non-pristine"):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            expected_outer_sha,
        )


def test_stage_b_failure_seals_partial_nested_tree_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ReplayFailure(RuntimeError):
        pass

    output_root = tmp_path / "stage-b"
    verification_root = tmp_path / "verification"
    asset = tmp_path / "asset"
    parent = tmp_path / "parent.parquet"
    outcomes = tmp_path / "outcomes.parquet"
    daily = tmp_path / "daily.parquet"
    expected_outer_sha = "b" * 64

    def fake_sha(path: Path) -> str:
        path = Path(path).resolve()
        selected_path = (runner.CY063_OUTPUT_ROOT / "stage_a/selected_entries.parquet").resolve()
        if path == selected_path:
            return builder.CY063_STAGE_HASHES["selected_entries.parquet"]
        return f"sha:{path}"

    identity = {
        "parent_sources": {
            role: {"path": str(path), "sha256": fake_sha(path)}
            for role, path in (
                ("selected", parent),
                ("outcomes", outcomes),
                ("outcome_daily", daily),
            )
        }
    }
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", output_root)
    monkeypatch.setattr(
        runner,
        "verify_outer_freeze",
        lambda *_args: {
            "outer_freeze_sha256": expected_outer_sha,
            "outer_freeze_path": str(verification_root / "verified_stage_a_freeze.json"),
            "asset_identity": identity,
            "cy063_stage_a_hashes": dict(builder.CY063_STAGE_HASHES),
        },
    )
    monkeypatch.setattr(runner, "sha256", fake_sha)

    def fail_after_partial_write(**kwargs: object) -> dict[str, object]:
        root = Path(kwargs["output_root"])
        partial = root / "stage_b" / "lane"
        partial.mkdir(parents=True)
        (partial / "partial.parquet").write_bytes(b"partial")
        raise ReplayFailure

    monkeypatch.setattr(runner, "_complete_stage_b_after_seal", fail_after_partial_write)

    with pytest.raises(ReplayFailure):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            expected_outer_sha,
        )

    for path in output_root.rglob("*"):
        assert path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert output_root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    with pytest.raises(runner.VerifierCorrectionError, match="repeated/non-pristine"):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            expected_outer_sha,
        )


def test_stage_b_attempt_write_failure_seals_partial_root_and_refuses_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AttemptWriteFailure(RuntimeError):
        pass

    output_root = tmp_path / "stage-b"
    verification_root = tmp_path / "verification"
    asset = tmp_path / "asset"
    parent = tmp_path / "parent.parquet"
    outcomes = tmp_path / "outcomes.parquet"
    daily = tmp_path / "daily.parquet"
    expected_outer_sha = "c" * 64

    def fake_sha(path: Path) -> str:
        path = Path(path).resolve()
        selected_path = (runner.CY063_OUTPUT_ROOT / "stage_a/selected_entries.parquet").resolve()
        if path == selected_path:
            return builder.CY063_STAGE_HASHES["selected_entries.parquet"]
        return f"sha:{path}"

    identity = {
        "parent_sources": {
            role: {"path": str(path), "sha256": fake_sha(path)}
            for role, path in (
                ("selected", parent),
                ("outcomes", outcomes),
                ("outcome_daily", daily),
            )
        }
    }
    monkeypatch.setattr(runner, "EXPECTED_STAGE_B_ROOT", output_root)
    monkeypatch.setattr(
        runner,
        "verify_outer_freeze",
        lambda *_args: {
            "outer_freeze_sha256": expected_outer_sha,
            "outer_freeze_path": str(verification_root / "verified_stage_a_freeze.json"),
            "asset_identity": identity,
            "cy063_stage_a_hashes": dict(builder.CY063_STAGE_HASHES),
        },
    )
    monkeypatch.setattr(runner, "sha256", fake_sha)

    def partial_write(path: Path, _value: object) -> None:
        path.write_text("partial", encoding="utf-8")
        raise AttemptWriteFailure

    monkeypatch.setattr(runner, "write_json_exclusive", partial_write)

    with pytest.raises(AttemptWriteFailure):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            expected_outer_sha,
        )

    partial = output_root / "stage_b_pre_outcome_attempt_seal.json"
    assert partial.is_file()
    assert partial.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    assert output_root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) == 0
    with pytest.raises(runner.VerifierCorrectionError, match="repeated/non-pristine"):
        runner.run_stage_b(
            asset,
            parent,
            outcomes,
            daily,
            verification_root,
            output_root,
            expected_outer_sha,
        )
