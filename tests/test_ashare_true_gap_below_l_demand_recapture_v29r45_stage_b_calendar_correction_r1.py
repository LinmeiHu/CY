from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_demand_recapture_sequential_v29r45_"
    "stage_b_calendar_correction_r1.py"
)
BUILDER_PATH = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "build_ashare_true_gap_below_l_demand_recapture_v29r45_"
    "stage_b_calendar_correction_r1_asset.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


correction = _load(RUNNER_PATH, "calendar_correction_runner_test")
builder = _load(BUILDER_PATH, "calendar_correction_builder_test")


def test_frozen_base_and_protocol_hashes_match() -> None:
    assert correction.sha256(correction.BASE_RUNNER) == correction.BASE_RUNNER_SHA256
    assert correction.sha256(correction.PREREGISTRATION) == correction.PREREGISTRATION_SHA256
    prereg = correction._verify_preregistration()
    assert prereg["scientific_change"] == "NONE"
    assert prereg["only_allowed_functional_change"]["normalizer_change_allowed"] is False


def test_base_normalizer_contract_is_not_widened() -> None:
    raw = pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2020-01-02", periods=25),
            "calendar_index": range(25),
        }
    )
    normalized = correction.BASE.normalize_calendar(raw)
    assert tuple(normalized.columns) == ("trade_date", "cal_idx")
    with pytest.raises(correction.BASE.StageBError, match="calendar_index"):
        correction.BASE.normalize_calendar(normalized)


def test_corrected_run_arm_passes_raw_calendar_to_all_three_consumers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = correction.BASE
    raw_calendar = pd.DataFrame(
        {
            "trade_date": pd.bdate_range("2020-01-02", periods=25),
            "calendar_index": range(25),
        }
    )
    identity_path = Path("/pure-memory/v29r4_identity.parquet")
    candidates = pd.DataFrame([{"protocol_arm": "V29R4_CAP25", "gap_id": "g1"}])
    censored = pd.DataFrame(
        [
            {
                "protocol_arm": "V29R4_CAP25",
                "gap_id": "g1",
                "admin_status": "ADMINISTRATIVE_WINDOW_COMPLETE",
                "administratively_censored": False,
            }
        ]
    )
    observed_calendar_columns: list[tuple[str, ...]] = []
    published_attempts: list[str] = []

    monkeypatch.setattr(correction, "verify_activation", lambda: {"verified": True})
    monkeypatch.setattr(base, "OUTPUT_ROOT", base.OUTPUT_ROOT)
    monkeypatch.setattr(base, "EXPERIMENT", base.EXPERIMENT)
    monkeypatch.setattr(base, "PROTOCOL_VERSION", base.PROTOCOL_VERSION)
    monkeypatch.setattr(base, "initialize_output_anchor", lambda: None)
    monkeypatch.setattr(
        base,
        "ARM_CONFIG",
        {
            "v29r4": {
                "identity": identity_path,
                "expected_rows": 1,
                "expected_by_year": {2020: 1},
                "protocol_arm": "V29R4_CAP25",
            }
        },
    )

    def publish_attempt(*_args):
        published_attempts.append("v29r4")
        return Path("attempt.json")

    monkeypatch.setattr(base, "_publish_attempt", publish_attempt)

    def projected(path: Path, _columns):
        if path == identity_path:
            return pd.DataFrame([{"unused": 1}])
        assert path == base.MARKET_CALENDAR
        return raw_calendar.copy()

    monkeypatch.setattr(base, "_projected_read", projected)
    monkeypatch.setattr(base, "normalize_candidates", lambda *_args, **_kwargs: candidates)

    def administrative(_candidates: pd.DataFrame, calendar: pd.DataFrame):
        pd.testing.assert_frame_equal(calendar, raw_calendar)
        observed_calendar_columns.append(tuple(calendar.columns))
        return censored.copy()

    monkeypatch.setattr(base, "administrative_censor", administrative)
    monkeypatch.setattr(base, "_read_arm_rows", lambda *_: pd.DataFrame())

    def verify_bounds(
        _candidates: pd.DataFrame,
        _bounds: pd.DataFrame,
        calendar: pd.DataFrame,
        _arm: str,
    ) -> None:
        pd.testing.assert_frame_equal(calendar, raw_calendar)
        observed_calendar_columns.append(tuple(calendar.columns))

    monkeypatch.setattr(base, "verify_admin_bounds", verify_bounds)
    empty = pd.DataFrame()
    monkeypatch.setattr(base, "_load_entry_inputs", lambda *_: (empty, empty, empty))
    entries = pd.DataFrame([{"gap_id": "g1"}])
    monkeypatch.setattr(base, "build_entries", lambda *_: entries)
    monkeypatch.setattr(base, "_load_one_candidate_path", lambda *_: (empty, empty, empty))

    def evaluate(
        _row: SimpleNamespace,
        _daily: pd.DataFrame,
        _execution: pd.DataFrame,
        _actions: pd.DataFrame,
        calendar: pd.DataFrame,
    ) -> dict[str, str]:
        pd.testing.assert_frame_equal(calendar, raw_calendar)
        observed_calendar_columns.append(tuple(calendar.columns))
        return {"gap_id": "g1", "outcome_status": "COMPLETED"}

    monkeypatch.setattr(base, "evaluate_one_outcome", evaluate)

    def replay(_entries: pd.DataFrame, resolve):
        resolved = resolve(SimpleNamespace(gap_id="g1"))
        assert resolved["outcome_status"] == "COMPLETED"
        return pd.DataFrame(), pd.DataFrame([resolved])

    monkeypatch.setattr(base, "replay_online_portfolio", replay)
    monkeypatch.setattr(base, "summarize", lambda *_: {"summary": "ok"})
    monkeypatch.setattr(
        base,
        "_write_result_bundle",
        lambda *_: {"aggregate_publication_status": "COMPLETE_TEST"},
    )

    def blocked(*_args):
        raise AssertionError("corrected orchestration unexpectedly entered BLOCKED")

    monkeypatch.setattr(base, "_write_blocked_result", blocked)
    result = correction.run_arm("v29r4")
    assert result["aggregate_publication_status"] == "COMPLETE_TEST"
    assert published_attempts == ["v29r4"]
    assert base.EXPERIMENT == correction.CORRECTION_EXPERIMENT
    assert observed_calendar_columns == [
        correction.BASE.CALENDAR_COLUMNS,
        correction.BASE.CALENDAR_COLUMNS,
        correction.BASE.CALENDAR_COLUMNS,
    ]


def test_reference_wrapper_plan_never_decodes_or_copies_parquet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(builder.os.path, "lexists", lambda _path: False)
    monkeypatch.setattr(builder, "_cy048_absent_from_registry", lambda: None)
    monkeypatch.setattr(builder, "_verify_reference_metadata", lambda: {"x": 1})
    monkeypatch.setattr(builder.BASE, "normalized_json_sha256", lambda _value: "frozen")
    plan = builder.metadata_plan(require_absent=True)
    assert plan["status"] == "PASS_METADATA_ONLY"
    assert plan["referenced_files"] == 7
    assert plan["parquet_rows_decoded"] is False
    assert plan["parquet_bytes_copied"] is False
    assert plan["outcome_or_return_rows_opened"] is False
    assert plan["returns_computed"] is False
    assert plan["output_written"] is False


def test_reference_wrapper_plan_rejects_symlinked_parent_before_metadata_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    monkeypatch.setattr(builder, "TARGET_ROOT", linked_parent / "CY-048")

    def unexpected_read():
        raise AssertionError("reference metadata opened before path validation")

    monkeypatch.setattr(builder, "_verify_reference_metadata", unexpected_read)
    with pytest.raises(builder.BASE.StageBError, match="symlink"):
        builder.metadata_plan(require_absent=True)


def test_activation_rebinds_generic_registry_identity_to_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_activation = {
        "runner_sha256": correction.BASE_RUNNER_SHA256,
        "preregistration_sha256": correction.BASE_PREREGISTRATION_SHA256,
        "manifest_sha256": correction.BASE_MANIFEST_SHA256,
        "activation_audit_sha256": correction.BASE_ACTIVATION_AUDIT_SHA256,
        "registry_asset_normalized_sha256": correction.BASE_ASSET_NORMALIZED_SHA256,
        "registry_authorization_normalized_sha256": (
            correction.BASE_AUTHORIZATION_NORMALIZED_SHA256
        ),
        "pit_contract": correction.PIT_CONTRACT,
    }
    asset = {"asset_id": "CY-048", "identity": "wrapper"}
    authorization = {
        "authorization_id": correction.AUTHORIZATION_ID,
        "identity": "correction",
    }
    base_builder = correction.REPO_ROOT / (
        "research/market_behavior_os_v2/scripts/"
        "build_ashare_true_gap_below_l_demand_recapture_v29r45_stage_b_asset.py"
    )
    digests = {
        correction.BASE_RUNNER: correction.BASE_RUNNER_SHA256,
        correction.BASE.PREREG: correction.BASE_PREREGISTRATION_SHA256,
        base_builder: correction.BASE_BUILDER_SHA256,
        RUNNER_PATH: "1" * 64,
        correction.WRAPPER_MANIFEST: "2" * 64,
        correction.WRAPPER_AUDIT: "3" * 64,
    }
    monkeypatch.setattr(correction, "sha256", lambda path: digests[Path(path)])
    monkeypatch.setattr(
        correction,
        "_verify_preregistration",
        lambda: {"correction_experiment": correction.CORRECTION_EXPERIMENT},
    )
    monkeypatch.setattr(correction, "BASE_VERIFY_ACTIVATION", lambda: base_activation)
    monkeypatch.setattr(correction, "verify_predecessor", lambda _activation: {})
    monkeypatch.setattr(correction, "_verify_wrapper_files", lambda _activation: ({}, {}))
    monkeypatch.setattr(
        correction, "_verify_registry", lambda _manifest, _audit: (asset, authorization)
    )

    activation = correction.verify_activation()
    asset_sha = correction.BASE.normalized_json_sha256(asset)
    authorization_sha = correction.BASE.normalized_json_sha256(authorization)
    assert activation["registry_asset_normalized_sha256"] == asset_sha
    assert activation["registry_authorization_normalized_sha256"] == authorization_sha
    assert (
        activation["base_registry_asset_normalized_sha256"]
        == correction.BASE_ASSET_NORMALIZED_SHA256
    )
    assert (
        activation["base_registry_authorization_normalized_sha256"]
        == correction.BASE_AUTHORIZATION_NORMALIZED_SHA256
    )


def test_manifest_declares_exact_reference_identity() -> None:
    manifest = builder._manifest()
    assert manifest["asset_id"] == "CY-048"
    assert manifest["referenced_files"] == correction.EXPECTED_REFERENCE_FILES
    assert manifest["correction_contract"] == {
        "consumer_change_allowed": False,
        "new_output_root": str(correction.OUTPUT_ROOT),
        "normalizer_change_allowed": False,
        "only_change": "RUN_ARM_PASSES_RAW_CALENDAR_TO_EXISTING_CONSUMERS",
        "operational_experiment": correction.CORRECTION_EXPERIMENT,
        "protocol_version": correction.CORRECTION_PROTOCOL_VERSION,
        "scientific_change": "NONE",
        "strategy_or_accounting_change_allowed": False,
    }
    assert manifest["content_contract"]["parquet_rows_decoded"] is False
    assert manifest["content_contract"]["parquet_bytes_copied"] is False
