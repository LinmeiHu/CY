"""Regression locks for the free 2017-2021 historical-state Gate A/B closure."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import duckdb
import pytest

from cyq_game.data import DataActivationError, DataAssetRegistry, DataPurpose

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
SUMMARY_PATH = REPORTS / "chinext_v1_gate_ab_closure_summary.json"
MANIFEST_PATH = REPORTS / "chinext_v1_free_historical_state_manifest.json"
EVENTS_PATH = (
    ROOT
    / "research/chinext_v1/specs/"
    "chinext_v1_free_historical_state_official_events.json"
)
BUILDER_PATH = (
    ROOT
    / "research/chinext_v1/scripts/"
    "build_chinext_v1_free_historical_state.py"
)
DATA = ROOT / "research/chinext_v1/data/pit_free_2017_2021"
DAILY = DATA / "normalized/daily_historical_state.parquet"
MASTER = DATA / "normalized/security_master.parquet"
REGISTRY = ROOT / "configs/data_asset_registry.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
AUTHORIZATION_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-FREE-2017-2021-V1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_builder() -> ModuleType:
    scripts = str(BUILDER_PATH.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("chinext_free_state_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_authorization_request() -> dict[str, object]:
    return {
        "purpose": DataPurpose.CHINEXT_PIT_B_RESEARCH,
        "manifest_path": MANIFEST_PATH,
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "artifacts": {
            "daily_historical_state": (DAILY, sha256_file(DAILY)),
            "security_master": (MASTER, sha256_file(MASTER)),
        },
        "start": date(2017, 4, 12),
        "end": date(2021, 12, 31),
        "dependency_asset_id": "QD-007",
        "consumer_path": BUILDER_PATH,
        "strategy_path": STRATEGY,
        "strategy_sha256": sha256_file(STRATEGY),
        "current_survivor_fallback": False,
    }


def test_gate_a_b_close_without_gate_c_or_outcomes() -> None:
    summary = load_json(SUMMARY_PATH)
    assert summary["gate_a"]["decision"] == "PASS"
    assert summary["gate_b"]["decision"] == "PASS"
    assert summary["active_blockers_remaining"] == []
    assert summary["research_frontier"]["safe_to_preregister_gate_c"] == "YES"
    assert summary["research_scope"] == {
        "free_paid_data_required": "NO",
        "gate_c_executed": False,
        "new_nav": 0,
        "new_strategy_trades": 0,
        "phase12b4_executed": False,
        "strategy_performance_consumed": False,
    }
    assert not summary["authorization"]["strict_pit_a"]
    assert not summary["authorization"]["revision_history_complete"]


def test_historical_denominator_changes_through_time() -> None:
    manifest = load_json(MANIFEST_PATH)
    samples = manifest["historical_denominator_samples"]
    assert len(samples) == 6
    assert len({item["sorted_code_set_sha256"] for item in samples.values()}) == 6
    assert samples["2017-04-12"]["row_count"] == 3757
    assert samples["2021-12-31"]["row_count"] == 5147
    assert manifest["acquisition"]["trading_dates_required"] == 1153
    assert manifest["acquisition"]["trading_dates_acquired"] == 1153
    assert manifest["acquisition"]["snapshot_failure_count"] == 0


def test_current_universe_and_future_alias_are_not_projected_backward() -> None:
    summary = load_json(SUMMARY_PATH)
    assert not summary["historical_denominator"]["current_set_projected_backward"]
    connection = duckdb.connect()
    future, old = connection.execute(
        f"""
        SELECT COUNT(*) FILTER (WHERE symbol = '302132.SZ'),
               COUNT(*) FILTER (WHERE symbol = '300114.SZ')
        FROM read_parquet('{DAILY}')
        """
    ).fetchone()
    assert future == 0
    assert old == 1153
    alias = summary["alias_normalization"]
    assert alias["anomaly_count"] == alias["resolved_count"] == 1
    assert alias["unresolved_count"] == 0


def test_listing_delisting_and_non_survivor_retention() -> None:
    connection = duckdb.connect()
    boundaries = connection.execute(
        f"""
        SELECT
          (SELECT MIN(trade_date) FROM read_parquet('{DAILY}')
           WHERE symbol = '300812.SZ'),
          (SELECT MAX(trade_date) FROM read_parquet('{DAILY}')
           WHERE symbol = '300028.SZ'),
          (SELECT listed_trading_days FROM read_parquet('{DAILY}')
           WHERE symbol = '300812.SZ' ORDER BY trade_date LIMIT 1),
          (SELECT COUNT(*) FROM read_parquet('{MASTER}')
           WHERE identity_status = 'HISTORICAL_NON_SURVIVOR')
        """
    ).fetchone()
    assert boundaries == (date(2020, 1, 9), date(2020, 8, 3), 1, 40)
    assert connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{DAILY}') "
        "WHERE symbol = '300028.SZ' AND trade_date = DATE '2020-08-04'"
    ).fetchone()[0] == 0
    retained = {
        row[0]
        for row in connection.execute(
            f"SELECT symbol FROM read_parquet('{MASTER}') "
            "WHERE identity_status = 'HISTORICAL_NON_SURVIVOR'"
        ).fetchall()
    }
    assert {"300028.SZ", "300362.SZ", "300431.SZ"} <= retained


def test_st_star_st_and_removal_transitions_are_distinct() -> None:
    connection = duckdb.connect()
    st = connection.execute(
        f"""
        SELECT trade_date, risk_warning_type FROM read_parquet('{DAILY}')
        WHERE symbol = '300029.SZ'
          AND trade_date IN (DATE '2020-09-14', DATE '2020-09-15')
        ORDER BY trade_date
        """
    ).fetchall()
    star_st = connection.execute(
        f"""
        SELECT trade_date, risk_warning_type FROM read_parquet('{DAILY}')
        WHERE symbol = '300795.SZ'
          AND trade_date IN (DATE '2021-04-27', DATE '2021-04-28')
        ORDER BY trade_date
        """
    ).fetchall()
    assert st == [(date(2020, 9, 14), "NORMAL"), (date(2020, 9, 15), "ST")]
    assert star_st == [
        (date(2021, 4, 27), "NORMAL"),
        (date(2021, 4, 28), "STAR_ST"),
    ]
    risk = load_json(SUMMARY_PATH)["risk_warning"]
    assert risk["st_interval_count"] == 12
    assert risk["star_st_interval_count"] == 12
    assert risk["unresolved_count"] == 0
    assert risk["removal_positive_control"] == {
        "effective_date": "2022-04-12",
        "scope": "OUT_OF_AUTHORIZED_RANGE_VALIDATION_ONLY",
        "status": "PASS_OFFICIAL_EVENT_AND_PRIOR_BAOSTOCK_DAILY_CONTROL",
        "symbol": "300795.SZ",
    }


def test_full_day_suspension_and_warmup_null_rows() -> None:
    connection = duckdb.connect()
    count = connection.execute(
        f"""
        SELECT COUNT(*) FROM read_parquet('{DAILY}')
        WHERE symbol = '300198.SZ' AND full_day_suspended
          AND trade_date BETWEEN DATE '2017-04-20' AND DATE '2017-08-31'
        """
    ).fetchone()[0]
    assert count == 93
    warmup = connection.execute(
        f"""
        SELECT trade_date, trade_status, full_day_suspended, volume_raw, amount_raw
        FROM read_parquet('{DAILY}')
        WHERE symbol = '300372.SZ'
          AND trade_date IN (
            DATE '2017-04-21', DATE '2017-04-24', DATE '2017-04-25',
            DATE '2017-05-19', DATE '2017-08-28'
          )
        ORDER BY trade_date
        """
    ).fetchall()
    assert len(warmup) == 5
    assert all(row[1:] == ("0", True, "", "") for row in warmup)
    manifest = load_json(MANIFEST_PATH)
    assert manifest["suspension_crosscheck"]["status"] == "PASS_93_OF_93"
    assert manifest["suspension_crosscheck"]["sorted_yyyymmdd_sha256"] == (
        "0dfbbd52889738b0ee0d882199ef87b20b2ef212171bb0c099cd5873aeb211c7"
    )


def test_gate_b_registered_price_calendar_and_corporate_action_inputs() -> None:
    registry = load_json(REGISTRY)
    assets = {item["asset_id"]: item for item in registry["assets"]}
    for asset_id in ("QD-001", "QD-003", "QD-010"):
        asset = assets[asset_id]
        assert asset["status"] == "RESEARCH_CONDITIONAL"
        assert asset["pit_grade"] == "B"
        assert asset["lineage"]["immutable_manifest"] is True
        assert len(asset["lineage"]["manifest_sha256"]) == 64
    assert assets["QD-010"]["coverage"]["revision_history_complete"] is False
    adjudication = (
        REPORTS / "chinext_v1_corporate_action_adjudication.md"
    ).read_text(encoding="utf-8")
    assert "635 exact CY-006 event-ID matches" in adjudication
    assert "0 unmatched" in adjudication
    assert sha256_file(STRATEGY) == (
        "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
    )


def test_conservative_known_at_and_deterministic_rebuild_are_locked() -> None:
    connection = duckdb.connect()
    assert connection.execute(
        f"SELECT COUNT(*) FROM read_parquet('{DAILY}') "
        "WHERE earliest_safe_use_date IS NULL "
        "OR earliest_safe_use_date <= trade_date"
    ).fetchone()[0] == 0
    manifest = load_json(MANIFEST_PATH)
    assert manifest["materialization"]["deterministic_rebuild"] == (
        "PASS_BYTE_IDENTICAL"
    )
    assert sha256_file(DAILY) == (
        "995cdbcc14f290c208740a0deda4d2ec5329e194b469452546a4ed0cb89e7444"
    )
    assert sha256_file(MASTER) == (
        "ff709212fa96067c117e4ad951f33c1cfd45f107142401f5deb43c6d61f23f54"
    )


def test_hash_mismatch_and_missing_official_evidence_fail_closed(
    tmp_path: Path,
) -> None:
    builder = load_builder()
    document = {
        "source_document": "official.pdf",
        "source_document_sha256": "0" * 64,
    }
    events = {
        "board_code_semantics": document,
        "identity_events": [],
        "risk_warning_events": [],
        "validation_events": [],
    }
    (tmp_path / "official.pdf").write_bytes(b"%PDF-not-the-bound-file")
    with pytest.raises(ValueError, match="hash mismatch"):
        builder.validate_official_documents(events, tmp_path)
    (tmp_path / "official.pdf").unlink()
    with pytest.raises(ValueError, match="hash mismatch"):
        builder.validate_official_documents(events, tmp_path)


def test_ambiguous_or_missing_alias_evidence_fails_closed() -> None:
    builder = load_builder()
    base = {
        "effective_date": "2025-02-17",
        "old_code": "300114.SZ",
        "publication_date": "2025-02-15",
        "source_document_sha256": "1" * 64,
    }
    with pytest.raises(ValueError, match="ambiguous alias old code"):
        builder.validate_identity_events(
            [
                {**base, "new_code": "302132.SZ"},
                {**base, "new_code": "302133.SZ"},
            ]
        )
    with pytest.raises(ValueError, match="unresolved identity fingerprint group"):
        builder.resolve_alias_anomalies([["sz.300114", "sz.302132"]], [])


def test_ambiguous_or_missing_risk_subtype_fails_closed() -> None:
    builder = load_builder()
    interval = {
        "end_date": "2021-12-31",
        "source_code": "sz.300795",
        "start_date": "2021-04-28",
    }
    event = {
        "effective_date": "2021-04-28",
        "publication_date": "2021-04-27",
        "risk_warning_type": "STAR_ST",
        "source_document": "official.pdf",
        "source_document_sha256": "2" * 64,
        "symbol": "300795.SZ",
    }
    with pytest.raises(ValueError, match="missing official risk-warning subtype"):
        builder.resolve_risk_intervals([interval], [], ["2017-04-12", "2021-12-31"])
    with pytest.raises(ValueError, match="ambiguous risk-warning subtype"):
        builder.resolve_risk_intervals(
            [interval], [event, event], ["2017-04-12", "2021-12-31"]
        )


def test_exact_bounded_registry_authorization_and_fail_closed_variants() -> None:
    registry = DataAssetRegistry.load(REGISTRY)
    authorization = registry.authorize_bounded_research(
        AUTHORIZATION_ID, **exact_authorization_request()
    )
    assert authorization.asset_id == "CY-029"
    assert authorization.dependency_asset_id == "QD-007"
    assert registry.assets["QD-007"].status == "DISCOVERY_ONLY"
    assert not authorization.record_level_available_at_available

    bad_hash = exact_authorization_request()
    bad_hash["manifest_sha256"] = "0" * 64
    with pytest.raises(DataActivationError, match="manifest hash mismatch"):
        registry.authorize_bounded_research(AUTHORIZATION_ID, **bad_hash)

    bad_range = exact_authorization_request()
    bad_range["end"] = date(2022, 1, 4)
    with pytest.raises(DataActivationError, match="date range mismatch"):
        registry.authorize_bounded_research(AUTHORIZATION_ID, **bad_range)

    fallback = exact_authorization_request()
    fallback["current_survivor_fallback"] = True
    with pytest.raises(DataActivationError, match="current-survivor fallback is forbidden"):
        registry.authorize_bounded_research(AUTHORIZATION_ID, **fallback)
