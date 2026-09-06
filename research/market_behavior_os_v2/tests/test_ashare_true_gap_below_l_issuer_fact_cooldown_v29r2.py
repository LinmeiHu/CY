from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_fact_cooldown_v29r2 as subject,
)


def _route_row(
    *,
    key: str,
    symbol: str,
    original_time: str,
    source_date: str,
    causal_available_at: str,
    title: str,
) -> dict[str, object]:
    sse = symbol.endswith(".SH")
    timestamp = pd.Timestamp(original_time)
    if sse:
        available_at = timestamp
        precision = "SOURCE_SECOND"
        role = "SSE_FULL_HISTORY_AUTHORITATIVE"
        exchange = "SSE"
        original_adddate: object = original_time
        original_ssedate: object = source_date
        original_publish_time: object = pd.NA
        publication_field = "ADDDATE"
        query_date_field = "SSEDATE"
    else:
        available_at = (
            timestamp + pd.Timedelta(days=1)
            if timestamp == timestamp.normalize()
            else timestamp
        )
        precision = (
            "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
            if timestamp == timestamp.normalize()
            else "SOURCE_SECOND"
        )
        role = "BASE_SZSE_AUTHORITATIVE"
        exchange = "SZSE"
        original_adddate = pd.NA
        original_ssedate = pd.NA
        original_publish_time = original_time
        publication_field = "publishTime"
        query_date_field = "publishTime"
    return {
        "component_role": role,
        "original_adddate": original_adddate,
        "original_ssedate": original_ssedate,
        "original_publish_time": original_publish_time,
        "causal_available_at": causal_available_at,
        "snapshot_id": f"snapshot-{exchange.lower()}",
        "announcement_key": f"{key}|{symbol}",
        "announcement_id": key,
        "source_record_key": key,
        "symbol": symbol,
        "security_code": symbol[:6],
        "title": title,
        "published_at": timestamp,
        "available_at": available_at,
        "precision": precision,
        "document_url": f"https://example.invalid/{key}.pdf",
        "exchange": exchange,
        "source": "SSE_SZSE_OFFICIAL_ISSUER_ANNOUNCEMENT_APIS",
        "source_endpoint": "https://example.invalid/api",
        "source_publication_field": publication_field,
        "source_publication_value": original_time,
        "source_query_date_field": query_date_field,
        "source_query_date": pd.Timestamp(source_date),
        "query_id": f"{exchange}-{symbol[:6]}-{source_date[:4]}",
        "query_year": int(source_date[:4]),
        "raw_record_sha256": "a" * 64,
        "revision_history_complete": False,
        "strict_pit_eligible": False,
        "hard_valid": True,
    }


def _entries(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gap_id": [row[0] for row in rows],
            "symbol": [row[1] for row in rows],
            "signal_date": [pd.Timestamp(row[2]).normalize() for row in rows],
            "signal_time": [pd.Timestamp(row[2]) for row in rows],
        }
    )


def _classified(rows: list[dict[str, object]]) -> pd.DataFrame:
    return subject.classifier.classify_exchange_announcements(pd.DataFrame(rows))


def _exact_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "gap_id": "g1",
        "symbol": "600001.SH",
        "signal_date": pd.Timestamp("2020-01-02"),
        "signal_time": pd.Timestamp("2020-01-02 15:00:00"),
        "entry_date": pd.Timestamp("2020-01-03"),
        "entry_time": pd.Timestamp("2020-01-03 09:31:00"),
        "entry_status": "EXECUTABLE_ENTRY",
        "entry_cal_idx": 123,
        "entry_raw_price": 10.01,
        "entry_coordinate_factor": 1.0,
        "entry_coordinate_price": 10.01,
        "entry_invalid_step_cum": 0.0,
        "up_limit_price": 11.0,
        "entry_at_or_before_signal": False,
        "entry_after_signal_period_boundary": False,
        "buy_at_or_above_up_limit": False,
    }
    row.update(overrides)
    return row


def test_live_preregistration_and_protocol_hashes_are_self_consistent() -> None:
    prereg, hashes = subject._verify_protocol()

    assert prereg["experiment"] == subject.EXPERIMENT
    assert hashes["preregistration_sha256"] == subject.EXPECTED_PREREGISTRATION_SHA256
    assert hashes["classifier_sha256"] == subject.EXPECTED_CLASSIFIER_SHA256
    assert hashes["parent_source_hashes_streamed_without_parsing"] == (
        prereg["stage_b_source_hashes"]
    )


def test_preregistered_selector_contract_is_exact() -> None:
    prereg = json.loads(subject.PREREGISTRATION.read_text(encoding="utf-8"))

    identity = subject._selector_contract(prereg)

    assert identity["candidate_announcement_titles"] == 13_338
    assert identity["classified_open_rows"] == 20
    assert identity["selected_signals"] == 362
    assert identity["rejected_signals"] == 8
    assert identity["rejected_gap_ids"] == list(subject.EXPECTED_REJECTED_GAP_IDS)


def _runtime_asset_identity() -> dict[str, object]:
    return {
        "activation_audit_sha256": "a" * 64,
        "asset_manifest_sha256": "b" * 64,
        "asset_root": "/fixture/CY-036-R2",
        "base_component_root": "/fixture/base",
        "base_nested_files_verified": 4451,
        "bounded_authorization_sha256": "c" * 64,
        "data_asset_registry_sha256": "d" * 64,
        "registered_asset_entry_sha256": "e" * 64,
        "route_index_sha256": "f" * 64,
        "sse_nested_files_verified": 4606,
        "title_route_contract": {"join_cardinality": "one_to_one"},
        "upstream_asset_root": "/fixture/CY-036-R1",
        "covered_symbols": ["600001.SH"],
    }


def test_unrelated_registry_byte_change_does_not_drift_stage_a_scope() -> None:
    runtime = _runtime_asset_identity()
    frozen = subject._scoped_cy036r2_identity(runtime)
    runtime["data_asset_registry_sha256"] = "0" * 64

    verified = subject._verify_frozen_cy036r2_identity(frozen, runtime)

    assert verified == frozen
    assert "data_asset_registry_sha256" not in verified


@pytest.mark.parametrize(
    "field",
    ["registered_asset_entry_sha256", "bounded_authorization_sha256"],
)
def test_target_asset_or_authorization_change_still_fails_closed(field: str) -> None:
    runtime = _runtime_asset_identity()
    frozen = subject._scoped_cy036r2_identity(runtime)
    runtime[field] = "0" * 64

    with pytest.raises(subject.V29R2Error, match="target asset/authorization"):
        subject._verify_frozen_cy036r2_identity(frozen, runtime)


def test_future_causal_title_is_never_passed_to_v2_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routine = _route_row(
        key="known",
        symbol="600001.SH",
        original_time="2021-12-30 10:00:00",
        source_date="2021-12-30",
        causal_available_at="2021-12-31 00:00:00",
        title="关于关联方资金占用专项审核报告",
    )
    future = _route_row(
        key="future",
        symbol="600001.SH",
        original_time="2021-12-31 10:00:00",
        source_date="2021-12-31",
        causal_available_at="2022-01-01 00:00:00",
        title="关于收到中国证监会立案调查通知书的公告",
    )
    seen: list[str] = []
    real_classifier = subject.classifier.classify_exchange_announcements

    def capture(frame: pd.DataFrame) -> pd.DataFrame:
        seen.extend(frame["announcement_id"].astype(str).tolist())
        return real_classifier(frame)

    monkeypatch.setattr(subject.classifier, "classify_exchange_announcements", capture)

    classified, scope = subject.classify_development_titles(
        pd.DataFrame([routine, future])
    )

    assert seen == ["known"]
    assert classified["classification_version"].eq(
        subject.classifier.CLASSIFICATION_VERSION
    ).all()
    assert classified["action"].eq(subject.classifier.ACTION_IGNORE).all()
    assert scope["rows_causal_available_from_2022"] == 1
    assert scope["causal_available_from_2022_titles_read"] is False
    assert scope["causal_available_from_2022_titles_classified"] is False
    assert scope["causal_available_from_2022_rows_selector_used"] is False


def test_explicit_fact_at_window_start_blocks_and_close_never_shortens() -> None:
    signal = pd.Timestamp("2020-06-30 15:00:00")
    start = signal - pd.Timedelta(days=subject.COOLING_CALENDAR_DAYS)
    events = _classified(
        [
            {
                "announcement_key": "open|000001.SZ",
                "announcement_id": "open",
                "symbol": "000001.SZ",
                "exchange": "SZSE",
                "title": "关于收到中国证监会立案调查通知书的公告",
                "available_at": start,
            },
            {
                "announcement_key": "close|000001.SZ",
                "announcement_id": "close",
                "symbol": "000001.SZ",
                "exchange": "SZSE",
                "title": "关于撤销立案的公告",
                "available_at": start + pd.Timedelta(days=10),
            },
        ]
    )

    row = subject.apply_issuer_fact_cooldown(
        _entries([("g", "000001.SZ", str(signal))]),
        events,
        covered_symbols=["000001.SZ"],
    ).iloc[0]

    assert bool(row.v29r2_coverage_complete)
    assert not bool(row.v29r2_issuer_fact_cooldown_gate)
    assert row.v29r2_open_transition_count == 1
    assert row.v29r2_rejection_reason == "RECENT_HIGH_PRECISION_OPEN_ISSUER_FACT"


def test_routine_fund_review_title_does_not_create_open_fact() -> None:
    events = _classified(
        [
            {
                "announcement_key": "routine|000001.SZ",
                "announcement_id": "routine",
                "symbol": "000001.SZ",
                "exchange": "SZSE",
                "title": "关于控股股东及其他关联方资金占用情况的专项审核报告",
                "available_at": "2020-05-01 10:00:00",
            }
        ]
    )

    row = subject.apply_issuer_fact_cooldown(
        _entries([("g", "000001.SZ", "2020-06-30 15:00:00")]),
        events,
        covered_symbols=["000001.SZ"],
    ).iloc[0]

    assert events["action"].eq(subject.classifier.ACTION_IGNORE).all()
    assert bool(row.v29r2_issuer_fact_cooldown_gate)


def test_exact_selected_outcome_join_rejects_one_tick_mismatch() -> None:
    selected = pd.DataFrame([_exact_row()])
    outcomes = pd.DataFrame([_exact_row(entry_raw_price=10.02)])

    with pytest.raises(subject.V29R2Error, match=r"g1\.entry_raw_price"):
        subject.verify_exact_selected_outcome_join(
            selected,
            outcomes,
            exact_fields=subject.EXACT_JOIN_FIELDS,
        )


def test_stage_a_refuses_overwrite_before_protocol_or_data_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subject, "EXT_ROOT", tmp_path / "external")
    frozen = tmp_path / "stage_a.json"
    frozen.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(subject, "STAGE_A_FREEZE", frozen)
    monkeypatch.setattr(subject, "DEVELOPMENT_RESULT", tmp_path / "result.json")
    monkeypatch.setattr(subject, "REPORT", tmp_path / "report.md")
    monkeypatch.setattr(
        subject,
        "_verify_protocol",
        lambda: pytest.fail("protocol must not be read after overwrite guard fails"),
    )

    with pytest.raises(subject.V29R2Error, match="Stage-A outputs already exist"):
        subject.run_stage_a()


def test_registry_post_2021_authorization_drift_fails_closed(tmp_path: Path) -> None:
    manifest_path = tmp_path / "asset_manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")
    registry = {
        "global_gate": {
            "free_causal_research_ready": True,
            "backtest_authorized": True,
        }
    }
    asset = {
        "asset_id": subject.ASSET_ID,
        "status": "RESEARCH_CONDITIONAL",
        "physical_state": "MATERIALIZED",
        "pit_grade": "B",
        "lineage": {
            "record_available_at": True,
            "record_snapshot_id": True,
            "immutable_manifest": True,
            "bounded_authorization_id": subject.AUTHORIZATION_ID,
            "manifest_path": str(manifest_path),
            "manifest_sha256": subject.sha256(manifest_path),
        },
        "coverage": {
            "sse_query_start": subject.SSE_QUERY_START,
            "szse_query_start": subject.SZSE_QUERY_START,
            "query_end": subject.QUERY_END,
            "signal_start": "2018-01-01",
            "signal_end": subject.QUERY_END,
        },
    }
    authorization = {
        "authorization_id": subject.AUTHORIZATION_ID,
        "purpose": subject.AUTHORIZATION_PURPOSE,
        "asset_id": subject.ASSET_ID,
        "dependency_asset_id": subject.cy036r2.UPSTREAM_ASSET_ID,
        "dependency_status": "RESEARCH_CONDITIONAL",
        "record_level_available_at_available": True,
        "current_survivor_fallback_allowed": False,
        "event_classification_authorized": True,
        "development_outcome_join_authorized": True,
        "portfolio_replay_authorized": True,
        "post_2021_announcement_classification_authorized": False,
        "post_2021_signal_or_selector_authorized": True,
    }

    with pytest.raises(subject.V29R2Error, match="authorization flags drifted"):
        subject._validate_registry_documents(
            registry,
            asset,
            authorization,
            {},
            manifest_path=manifest_path,
        )
