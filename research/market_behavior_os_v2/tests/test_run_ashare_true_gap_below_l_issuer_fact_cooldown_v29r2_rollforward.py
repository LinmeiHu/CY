from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2_rollforward as subject,
)


def _routes() -> pd.DataFrame:
    values = [
        {
            "snapshot_id": "snap",
            "announcement_key": "sse-a",
            "announcement_id": "SSE-a",
            "symbol": "600000.SH",
            "exchange": "SSE",
            "published_at": pd.Timestamp("2022-01-02 09:00:00"),
            "available_at": pd.Timestamp("2022-01-02 09:00:00"),
            "precision": "SOURCE_SECOND",
            "source_publication_field": "ADDDATE",
            "source_publication_value": "2022-01-02 09:00:00",
            "source_query_date_field": "SSEDATE",
            "source_query_date": pd.Timestamp("2022-01-03"),
            "query_year": 2022,
            "raw_record_sha256": "a" * 64,
            "revision_history_complete": False,
            "strict_pit_eligible": False,
            "hard_valid": True,
            "component_role": subject.SSE_COMPONENT_ROLE,
        },
        {
            "snapshot_id": "snap",
            "announcement_key": "szse-a",
            "announcement_id": "SZSE-a",
            "symbol": "000001.SZ",
            "exchange": "SZSE",
            "published_at": pd.Timestamp("2022-01-03"),
            "available_at": pd.Timestamp("2022-01-04"),
            "precision": "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY",
            "source_publication_field": "publishTime",
            "source_publication_value": "2022-01-03 00:00:00",
            "source_query_date_field": "publishTime",
            "source_query_date": pd.Timestamp("2022-01-03"),
            "query_year": 2022,
            "raw_record_sha256": "b" * 64,
            "revision_history_complete": False,
            "strict_pit_eligible": False,
            "hard_valid": True,
            "component_role": subject.SZSE_COMPONENT_ROLE,
        },
    ]
    return pd.DataFrame(values, columns=subject.ROUTE_COLUMNS)


def test_causal_time_rebuild_uses_sse_next_day_floor_and_szse_date_floor() -> None:
    result = subject.derive_causal_available_at(_routes())
    assert result.causal_available_at.tolist() == [
        pd.Timestamp("2022-01-04", tz="Asia/Shanghai"),
        pd.Timestamp("2022-01-04", tz="Asia/Shanghai"),
    ]


def test_local_timestamp_rejects_timezone_aware_inputs() -> None:
    with pytest.raises(subject.RollforwardError, match="timezone-naive"):
        subject.local_timestamp(pd.Timestamp("2022-01-01", tz="UTC"), "signal")


def test_classifier_uses_repaired_time_without_source_second_contract_conflict() -> None:
    routed = subject.derive_causal_available_at(_routes().iloc[[0]].copy())
    routed["title"] = "关于年度报告的公告"
    result = subject.classify_titles(routed)
    assert result.available_at.iloc[0] == pd.Timestamp("2022-01-04", tz="Asia/Shanghai")
    assert "original_published_at" in result
    assert "original_precision" in result


def test_cooldown_is_inclusive_and_close_cannot_erase_open() -> None:
    entries = pd.DataFrame(
        [
            {
                "gap_id": "g1",
                "symbol": "000001.SZ",
                "signal_date": pd.Timestamp("2022-05-01"),
                "signal_time": pd.Timestamp("2022-05-01 15:00:00"),
                "entry_status": "EXECUTABLE_ENTRY",
            },
            {
                "gap_id": "g2",
                "symbol": "600000.SH",
                "signal_date": pd.Timestamp("2022-05-01"),
                "signal_time": pd.Timestamp("2022-05-01 15:00:00"),
                "entry_status": "EXECUTABLE_ENTRY",
            },
        ]
    )
    events = pd.DataFrame(
        [
            {
                "announcement_key": "a",
                "symbol": "000001.SZ",
                "available_at": pd.Timestamp("2022-01-01 15:00:00", tz="Asia/Shanghai"),
                "action": subject.classifier.ACTION_OPEN,
                "risk_family": subject.classifier.FAMILY_BANK_FREEZE,
                "matched_rule": "OPEN",
                "classification_version": subject.classifier.CLASSIFICATION_VERSION,
            },
            {
                "announcement_key": "b",
                "symbol": "000001.SZ",
                "available_at": pd.Timestamp("2022-04-01", tz="Asia/Shanghai"),
                "action": subject.classifier.ACTION_CLOSE,
                "risk_family": subject.classifier.FAMILY_BANK_FREEZE,
                "matched_rule": "CLOSE",
                "classification_version": subject.classifier.CLASSIFICATION_VERSION,
            },
        ]
    )
    result = subject.apply_cooldown(entries, events)
    assert result.set_index("gap_id").v29r2_issuer_fact_cooldown_gate.to_dict() == {
        "g1": False,
        "g2": True,
    }


def test_detailed_yearly_keeps_empty_years_and_signal_year() -> None:
    selected = pd.DataFrame(
        [
            {
                "signal_date": pd.Timestamp("2022-12-30"),
                "entry_status": "EXECUTABLE_ENTRY",
            }
        ]
    )
    accepted = pd.DataFrame(
        [
            {
                "signal_date": pd.Timestamp("2022-12-30"),
                "completed": True,
                "net_return": 0.05,
                "holding_sessions": 3,
                "exit_reason": "PRE_L_TARGET",
            }
        ]
    )
    result = subject.detailed_yearly(selected, accepted, years=(2022, 2023))
    assert result["2022"]["signals_after_veto"] == 1
    assert result["2022"]["mean_net"] == 0.05
    assert result["2022"]["exit_reasons"] == {"PRE_L_TARGET": 1}
    assert result["2023"]["signals_after_veto"] == 0
    assert result["2023"]["mean_net"] is None


def _selected_outcome_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    row = {
        "gap_id": "g1",
        "symbol": "600000.SH",
        "signal_date": pd.Timestamp("2026-08-03"),
        "signal_time": pd.Timestamp("2026-08-03 15:00:00"),
        "entry_date": pd.Timestamp("2026-08-04"),
        "entry_time": pd.Timestamp("2026-08-04 09:30:00"),
        "entry_status": "EXECUTABLE_ENTRY",
        "entry_cal_idx": 10,
        "entry_raw_price": 8.0,
        "entry_coordinate_factor": 1.0,
        "entry_coordinate_price": 8.0,
        "entry_invalid_step_cum": 0.0,
        "up_limit_price": 8.8,
        "entry_at_or_before_signal": False,
        "entry_after_signal_period_boundary": True,
        "buy_at_or_above_up_limit": False,
        "L": 10.0,
    }
    selected = pd.DataFrame([row])
    outcome = {
        **row,
        "alpha": 0.67,
        "horizon": 20,
        "stop": "NONE",
        "target_coordinate": 8.0 + 0.67 * (10.0 - 8.0),
        "exit_date": pd.Timestamp("2026-08-12"),
        "exit_time": pd.Timestamp("2026-08-12 09:30:00"),
        "exit_reason": "PRE_L_TARGET",
        "net_return": 0.05,
        "holding_sessions": 6,
    }
    return selected, pd.DataFrame([outcome])


def test_exact_join_checks_all_fields_and_allows_post_cutoff_t_plus_one() -> None:
    selected, outcomes = _selected_outcome_pair()
    assert subject.verify_execution_contract(selected)["t_plus_one_and_execution_flags_verified"]
    assert subject.verify_exact_selected_outcome_join(selected, outcomes)["exact_fields_equal"]
    outcomes.loc[0, "entry_coordinate_factor"] = 2.0
    with pytest.raises(subject.RollforwardError, match="entry_coordinate_factor"):
        subject.verify_exact_selected_outcome_join(selected, outcomes)


def test_outcome_contract_uses_real_schema_without_completed_column() -> None:
    selected, outcomes = _selected_outcome_pair()
    assert "completed" not in outcomes
    result = subject.verify_outcome_contract(selected, outcomes)
    assert result["rows"] == 1
    assert result["alpha"] == 0.67
    assert result["horizon"] == 20


def test_accepted_contract_never_overwrites_explicit_incomplete_flag() -> None:
    _, accepted = _selected_outcome_pair()
    accepted["completed"] = False
    with pytest.raises(subject.RollforwardError, match="explicit completed flag"):
        subject.verify_accepted_contract(accepted)
    assert accepted.completed.eq(False).all()


def test_stage_a_persists_read_only_route_freeze_before_title_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset_root = tmp_path / "asset"
    (asset_root / "source_capture").mkdir(parents=True)
    (asset_root / "sse_full_history_capture").mkdir()
    (asset_root / "source_capture/source_manifest.json").write_text(
        json.dumps({"coverage": {"start": "2021-10-18", "end": "2026-08-03"}}),
        encoding="utf-8",
    )
    (asset_root / "sse_full_history_capture/source_manifest.json").write_text(
        json.dumps({"coverage": {"start": "1990-12-19", "end": "2026-08-03"}}),
        encoding="utf-8",
    )
    route = _routes().iloc[[0]].copy()
    route.to_parquet(asset_root / "announcement_route_index.parquet", index=False)
    selected, _ = _selected_outcome_pair()
    selected.loc[0, "signal_date"] = pd.Timestamp("2022-05-01")
    selected.loc[0, "signal_time"] = pd.Timestamp("2022-05-01 15:00:00")
    selected.loc[0, "entry_date"] = pd.Timestamp("2022-05-02")
    selected.loc[0, "entry_time"] = pd.Timestamp("2022-05-02 09:30:00")
    selected_path = tmp_path / "selected.parquet"
    selected.to_parquet(selected_path, index=False)
    output_root = tmp_path / "output"
    monkeypatch.setattr(subject, "verify_asset", lambda *args: {"identity": "test"})

    def fake_attach(_asset_root: Path, persisted: pd.DataFrame) -> pd.DataFrame:
        route_path = output_root / "stage_a/title_route_selection.parquet"
        freeze_path = output_root / "stage_a/pretitle_route_freeze.json"
        assert route_path.is_file() and freeze_path.is_file()
        assert route_path.stat().st_mode & 0o222 == 0
        assert freeze_path.stat().st_mode & 0o222 == 0
        pd.testing.assert_frame_equal(pd.read_parquet(route_path), persisted)
        result = persisted.copy()
        result["title"] = "年度报告"
        return result

    def fake_classify(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        result["available_at"] = result.causal_available_at
        result["action"] = subject.classifier.ACTION_IGNORE
        result["risk_family"] = pd.NA
        result["matched_rule"] = "IGNORE"
        result["classification_version"] = subject.classifier.CLASSIFICATION_VERSION
        return result

    monkeypatch.setattr(subject, "attach_titles", fake_attach)
    monkeypatch.setattr(subject, "classify_titles", fake_classify)
    subject.run_stage_a(asset_root, selected_path, output_root)
    for path in (output_root / "stage_a").iterdir():
        assert path.stat().st_mode & 0o222 == 0
