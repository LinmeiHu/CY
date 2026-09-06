from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_demand_recapture_v29r4_"
    "entry_evidence_diagnostic_v1.py"
)
BUILDER_PATH = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "build_ashare_true_gap_below_l_demand_recapture_v29r4_"
    "entry_evidence_diagnostic_v1_asset.py"
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


diagnostic = _load(RUNNER_PATH, "v29r4_entry_evidence_diagnostic_test")
builder = _load(BUILDER_PATH, "v29r4_entry_evidence_diagnostic_builder_test")


def _frames(
    *, entry_available_at: str = "2020-01-03 15:00:00", L: object = "10.00", factor: object = "1"
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    candidate = pd.DataFrame(
        [
            {
                "administratively_censored": False,
                "gap_id": "g1",
                "symbol": "000001.SZ",
                "signal_snapshot_id": "signal-row-snapshot",
                "signal_daily_snapshot_id": "signal-daily-snapshot",
                "signal_corporate_action_snapshot_id": "signal-action-snapshot",
                "signal_date": pd.Timestamp("2020-01-02"),
                "signal_time": pd.Timestamp("2020-01-02 15:00:00"),
                "entry_date": pd.Timestamp("2020-01-03"),
                "L": L,
                "coordinate_factor": factor,
            }
        ]
    )

    def daily_row(offset: int) -> dict[str, object]:
        row = dict.fromkeys(diagnostic.BASE.DAILY_COLUMNS)
        is_signal = offset == -1
        row.update(
            {
                "protocol_arm": "V29R4_CAP25",
                "gap_id": "g1",
                "symbol": "000001.SZ",
                "signal_date": pd.Timestamp("2020-01-02"),
                "entry_date": pd.Timestamp("2020-01-03"),
                "signal_session_offset": 0 if is_signal else 1,
                "entry_session_offset": offset,
                "trade_date": pd.Timestamp("2020-01-02" if is_signal else "2020-01-03"),
                "decision_at": pd.Timestamp(
                    "2020-01-02 15:00:00" if is_signal else entry_available_at
                ),
                "available_at": pd.Timestamp(
                    "2020-01-02 15:00:00" if is_signal else entry_available_at
                ),
                "open": "10.00",
                "high": "10.20",
                "trade_status": 1,
                "current_day_data_tradable": True,
                "market_rule_valid": True,
                "corporate_action_count": 0,
                "corporate_action_ids": "",
                "share_multiplier": "1",
                "cash_per_share": "0",
                "rights_ratio": "0",
                "rights_price": "0",
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "corporate_action_snapshot_id": (
                    "signal-action-snapshot" if is_signal else "entry-action-snapshot"
                ),
                "hard_valid": True,
                "invalid_reasons": "",
                "snapshot_id": ("signal-row-snapshot" if is_signal else "entry-daily-snapshot"),
                "daily_snapshot_id": (
                    "signal-daily-snapshot" if is_signal else "entry-source-snapshot"
                ),
            }
        )
        return row

    daily = pd.DataFrame([daily_row(-1), daily_row(0)], columns=diagnostic.BASE.DAILY_COLUMNS)
    execution_row = dict.fromkeys(diagnostic.BASE.EXECUTION_COLUMNS)
    execution_row.update(
        {
            "protocol_arm": "V29R4_CAP25",
            "gap_id": "g1",
            "symbol": "000001.SZ",
            "signal_date": pd.Timestamp("2020-01-02"),
            "entry_date": pd.Timestamp("2020-01-03"),
            "signal_session_offset": 1,
            "entry_session_offset": 0,
            "trade_date": pd.Timestamp("2020-01-03"),
            "window_index": 0,
            "available_at": pd.Timestamp("2020-01-03 09:35:00"),
            "open": "10.00",
            "trade_status": 1,
            "is_st": False,
            "up_limit_price": "11.00",
            "down_limit_price": "9.00",
            "market_rule_valid": True,
            "source_resolution_minutes": 1,
            "minute_count": 5,
            "distinct_minute_count": 5,
            "ohlc_valid": True,
            "unit_valid": True,
            "causal_inputs_valid": True,
            "hard_valid": True,
            "invalid_reasons": "",
            "source": "synthetic-test",
            "snapshot_id": "entry-window-snapshot",
            "daily_snapshot_id": "entry-daily-snapshot",
        }
    )
    execution = pd.DataFrame([execution_row], columns=diagnostic.BASE.EXECUTION_COLUMNS)
    actions = pd.DataFrame(columns=diagnostic.BASE.ACTION_COLUMNS)
    return candidate, daily, execution, actions


def test_frozen_protocol_and_predecessor_hashes_match() -> None:
    prereg = diagnostic.verify_preregistration()
    assert diagnostic.sha256(diagnostic.PREREGISTRATION) == diagnostic.PREREGISTRATION_SHA256
    assert diagnostic.sha256(diagnostic.CORRECTION_RUNNER) == diagnostic.CORRECTION_RUNNER_SHA256
    assert prereg["performance_replay_allowed"] is False
    assert prereg["post_2021_access"] == "PROHIBITED"
    assert prereg["required_output"]["candidate_outcome_paths_opened"] == 0


def test_runner_has_no_outcome_or_portfolio_calls() -> None:
    tree = ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))
    calls: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            calls.add(node.func.id)
    assert calls.isdisjoint(
        {
            "_load_one_candidate_path",
            "build_entries",
            "evaluate_one_outcome",
            "replay_online_portfolio",
            "summarize",
        }
    )


def test_attempt_is_published_before_any_parquet_row_loader_in_source() -> None:
    source = inspect.getsource(diagnostic.run_diagnostic)
    attempt = source.index("_publish_attempt")
    assert attempt < source.index("_projected_read")
    assert attempt < source.index("_read_arm_rows")
    assert attempt < source.index("_load_diagnostic_entry_inputs")


def test_attempt_is_published_before_row_loader_at_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    attempt = tmp_path / "attempt.json"
    attempt.write_text("sealed\n", encoding="utf-8")
    monkeypatch.setattr(diagnostic, "verify_activation", lambda: {"verified": True})

    def publish(_activation):
        events.append("attempt")
        return attempt

    def row_read(*_args, **_kwargs):
        assert events == ["attempt"]
        events.append("row-read")
        raise RuntimeError("sensitive-source-value-must-not-be-persisted")

    monkeypatch.setattr(diagnostic, "_publish_attempt", publish)
    monkeypatch.setattr(diagnostic.BASE, "_projected_read", row_read)
    monkeypatch.setattr(diagnostic, "_write_terminal", lambda payload, _attempt: payload)
    result = diagnostic.run_diagnostic()
    assert events == ["attempt", "row-read"]
    assert result["blocker_code"] == "FAIL_CLOSED_ENTRY_DIAGNOSTIC_ABORT"
    assert result["row_scope_audit_complete"] is False
    assert result["post_2021_rows_opened"] is None
    assert "sensitive-source-value" not in str(result)


def test_minimum_daily_projection_excludes_after_observation_ohlc() -> None:
    assert "open" not in diagnostic.DIAGNOSTIC_DAILY_COLUMNS
    assert "high" not in diagnostic.DIAGNOSTIC_DAILY_COLUMNS
    loader_source = inspect.getsource(diagnostic._load_diagnostic_entry_inputs)
    assert "BASE._load_entry_inputs" not in loader_source
    assert "d.entry_session_offset IN (-1,0)" in loader_source
    assert "e.entry_session_offset=0 AND e.window_index=0" in loader_source
    assert "DATE '2021-12-31'" in loader_source
    assert "OR a.effective_date<=a.entry_date" not in loader_source
    assert loader_source.count("INTERVAL 9 HOUR+INTERVAL 35 MINUTE") == 2


def test_after_observation_daily_context_is_fatal_and_aggregate_only() -> None:
    candidates, daily, execution, actions = _frames()
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    assert result["total_candidates"] == 1
    assert result["administratively_censored"] == 0
    assert result["administratively_eligible"] == 1
    assert result["candidate_conservation_passed"] is True
    assert result["mask_conservation_passed"] is True
    assert sum(result["first_failure_counts"].values()) == 1
    assert result["first_failure_counts"]["ENTRY_DAILY_CONTEXT_AFTER_EXECUTION_OBSERVATION"] == 1
    assert (
        result["independent_static_mask_counts"][
            "ENTRY_DAILY_AVAILABLE_AFTER_EXECUTION_OBSERVATION"
        ]["true"]
        == 1
    )
    assert (
        result["independent_static_mask_counts"][
            "EXECUTION_DAILY_CONTEXT_AVAILABLE_AFTER_EXECUTION_OBSERVATION"
        ]["true"]
        == 1
    )
    assert set(result) == {
        "total_candidates",
        "administratively_censored",
        "administratively_eligible",
        "first_failure_counts",
        "independent_static_mask_counts",
        "unresolved_first_failure_total",
        "repair_directive",
        "candidate_conservation_passed",
        "mask_conservation_passed",
    }
    for counts in result["independent_static_mask_counts"].values():
        assert counts["true"] + counts["false"] + counts["unknown"] == 1
        assert counts["evaluated"] == counts["true"] + counts["false"]
    assert result["repair_directive"]["causal_adapter_required"] is True
    assert result["repair_directive"]["performance_run_authorized"] is False


def test_raw_l_coordinate_failure_is_counted_without_rounding() -> None:
    candidates, daily, execution, actions = _frames(
        entry_available_at="2020-01-03 09:35:00", L="10", factor="3"
    )
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    assert result["first_failure_counts"]["RAW_L_COORDINATE_NONCANONICAL"] == 1
    assert result["independent_static_mask_counts"]["RAW_L_COORDINATE_NONCANONICAL"]["true"] == 1
    assert result["first_failure_counts"]["RESOLVED_ENTRY_EVIDENCE"] == 0
    assert result["repair_directive"]["raw_l_tick_regeneration_required"] is True
    assert result["repair_directive"]["classifier_parity_failure"] is False


def test_temporal_and_raw_l_repairs_are_cumulative() -> None:
    candidates, daily, execution, actions = _frames(L="10", factor="3")
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    directive = result["repair_directive"]
    assert directive["causal_adapter_required"] is True
    assert directive["raw_l_tick_regeneration_required"] is True
    assert directive["combined_rebuild_required"] is True
    assert directive["performance_run_authorized"] is False


def test_execution_timestamp_cannot_move_the_fixed_observation() -> None:
    candidates, daily, execution, actions = _frames(entry_available_at="2020-01-03 09:35:00")
    execution.loc[0, "available_at"] = pd.Timestamp("2020-01-03 16:00:00")
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    assert result["first_failure_counts"]["ENTRY_DAILY_CONTEXT_AFTER_EXECUTION_OBSERVATION"] == 0
    assert result["first_failure_counts"]["EXECUTION_TIMING_OR_COMPLETENESS"] == 1
    assert result["independent_static_mask_counts"]["EXECUTION_TIMING_OR_COMPLETENESS"]["true"] == 1
    assert result["repair_directive"]["execution_evidence_rebuild_required"] is True


def test_missing_execution_is_unknown_not_false_for_dependent_masks() -> None:
    candidates, daily, _execution, actions = _frames(entry_available_at="2020-01-03 09:35:00")
    execution = pd.DataFrame(columns=diagnostic.DIAGNOSTIC_EXECUTION_COLUMNS)
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    assert result["first_failure_counts"]["EXECUTION_CARDINALITY_OR_DATE"] == 1
    assert result["independent_static_mask_counts"]["EXECUTION_CARDINALITY_OR_DATE"] == {
        "true": 1,
        "false": 0,
        "unknown": 0,
        "evaluated": 1,
    }
    for name in (
        "ENTRY_OPEN_NONCANONICAL",
        "UP_LIMIT_NONCANONICAL",
        "DOWN_LIMIT_NONCANONICAL",
        "EXECUTION_TIMING_OR_COMPLETENESS",
        "EXECUTION_SNAPSHOT_BINDING_MISMATCH",
        "LIMIT_GEOMETRY_INVALID",
    ):
        assert result["independent_static_mask_counts"][name] == {
            "true": 0,
            "false": 0,
            "unknown": 1,
            "evaluated": 0,
        }


def test_missing_daily_timestamp_is_unknown_not_after_observation() -> None:
    candidates, daily, execution, actions = _frames(entry_available_at="2020-01-03 09:35:00")
    daily.loc[daily.entry_session_offset.eq(0), "available_at"] = pd.NaT
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    assert result["first_failure_counts"]["ENTRY_BINDING_OR_LINEAGE"] == 1
    assert result["independent_static_mask_counts"][
        "ENTRY_DAILY_AVAILABLE_AFTER_EXECUTION_OBSERVATION"
    ] == {"true": 0, "false": 0, "unknown": 1, "evaluated": 0}
    assert result["independent_static_mask_counts"][
        "EXECUTION_DAILY_CONTEXT_AVAILABLE_AFTER_EXECUTION_OBSERVATION"
    ] == {"true": 0, "false": 0, "unknown": 1, "evaluated": 0}


def test_missing_snapshot_never_counts_as_snapshot_match() -> None:
    candidates, daily, execution, actions = _frames(entry_available_at="2020-01-03 09:35:00")
    execution.loc[0, "daily_snapshot_id"] = None
    result = diagnostic.diagnose_entry_evidence(candidates, daily, execution, actions)
    assert (
        result["independent_static_mask_counts"]["EXECUTION_DAILY_SNAPSHOT_ID_MISSING"]["true"] == 1
    )
    assert (
        result["independent_static_mask_counts"]["EXECUTION_SNAPSHOT_BINDING_MISMATCH"]["unknown"]
        == 1
    )
    assert (
        result["independent_static_mask_counts"][
            "EXECUTION_DAILY_CONTEXT_AVAILABLE_AFTER_EXECUTION_OBSERVATION"
        ]["unknown"]
        == 1
    )


def test_post_2021_row_is_reported_honestly_in_blocked_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates, daily, execution, actions = _frames(entry_available_at="2020-01-03 09:35:00")
    candidates["protocol_arm"] = "V29R4_CAP25"
    candidates["admin_status"] = "ADMINISTRATIVE_WINDOW_COMPLETE"
    attempt = tmp_path / "attempt.json"
    attempt.write_text("sealed\n", encoding="utf-8")
    execution.loc[0, "trade_date"] = pd.Timestamp("2022-01-04")
    monkeypatch.setattr(diagnostic, "verify_activation", lambda: {"verified": True})
    monkeypatch.setattr(diagnostic, "_publish_attempt", lambda _activation: attempt)
    monkeypatch.setattr(
        diagnostic.BASE, "normalize_candidates", lambda *_args, **_kwargs: candidates.copy()
    )
    monkeypatch.setattr(
        diagnostic.BASE, "_projected_read", lambda *_args, **_kwargs: pd.DataFrame()
    )
    monkeypatch.setattr(diagnostic.BASE, "administrative_censor", lambda frame, _calendar: frame)
    monkeypatch.setattr(diagnostic.BASE, "_read_arm_rows", lambda *_args: pd.DataFrame())
    monkeypatch.setattr(diagnostic.BASE, "verify_admin_bounds", lambda *_args: None)
    monkeypatch.setattr(
        diagnostic,
        "_load_diagnostic_entry_inputs",
        lambda *_args: (daily, execution, actions),
    )
    monkeypatch.setattr(diagnostic, "_write_terminal", lambda payload, _attempt: payload)
    result = diagnostic.run_diagnostic()
    assert result["aggregate_publication_status"] == "BLOCKED"
    assert result["row_scope_audit_complete"] is True
    assert result["post_2021_rows_opened"] == 1
    assert result["maximum_daily_entry_session_offset_opened"] == 0
    assert result["maximum_execution_entry_session_offset_opened"] == 0
    assert "blocker" not in result


def test_builder_has_no_data_or_outcome_calls() -> None:
    tree = ast.parse(BUILDER_PATH.read_text(encoding="utf-8"))
    names = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert names.isdisjoint(
        {
            "connect",
            "read_parquet",
            "_projected_read",
            "_load_diagnostic_entry_inputs",
            "_load_one_candidate_path",
            "evaluate_one_outcome",
            "replay_online_portfolio",
            "write_parquet",
            "copy",
            "copy2",
        }
    )


def test_reference_wrapper_plan_is_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        builder,
        "_verify_reference_metadata",
        lambda: (
            {"reference_wrapper_asset_id": "CY-048"},
            {
                "attempt_seal_sha256": diagnostic.CORRECTED_ATTEMPT_SHA256,
                "blocked_result_sha256": diagnostic.CORRECTED_RESULT_SHA256,
            },
        ),
    )
    monkeypatch.setattr(builder.BASE, "normalized_json_sha256", lambda _value: "frozen")
    plan = builder.metadata_plan(require_absent=False)
    assert plan["status"] == "PASS_METADATA_ONLY"
    assert plan["parquet_rows_decoded"] is False
    assert plan["parquet_bytes_copied"] is False
    assert plan["outcome_or_return_rows_opened"] is False
    assert plan["post_2021_rows_opened"] is False
    assert plan["output_written"] is False


def test_reference_wrapper_rejects_symlinked_parent_before_metadata_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    monkeypatch.setattr(builder, "TARGET_ROOT", linked_parent / "CY-050")

    def unexpected_read():
        raise AssertionError("reference metadata opened before path validation")

    monkeypatch.setattr(builder, "_verify_reference_metadata", unexpected_read)
    with pytest.raises(builder.BASE.StageBError, match="symlink"):
        builder.metadata_plan(require_absent=True)
