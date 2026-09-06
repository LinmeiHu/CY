from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v1 as classifier,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_integrity_cooldown_v29r1 as subject,
)


def _route_row(
    *,
    key: str,
    symbol: str,
    original_time: str,
    source_date: str,
    causal_available_at: str,
    title: str = "关于召开年度股东大会的通知",
) -> dict[str, object]:
    sse = symbol.endswith(".SH")
    if sse:
        published_at = original_time
        available_at = original_time
        precision = "SOURCE_SECOND"
        original_adddate: object = original_time
        original_ssedate: object = source_date
        original_publish_time: object = pd.NA
        publication_field = "ADDDATE"
        query_date_field = "SSEDATE"
        role = "SSE_FULL_HISTORY_AUTHORITATIVE"
        exchange = "SSE"
    else:
        published_at = original_time
        timestamp = pd.Timestamp(original_time)
        if timestamp == timestamp.normalize():
            available_at = timestamp + pd.Timedelta(days=1)
            precision = "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"
        else:
            available_at = timestamp
            precision = "SOURCE_SECOND"
        original_adddate = pd.NA
        original_ssedate = pd.NA
        original_publish_time = original_time
        publication_field = "publishTime"
        query_date_field = "publishTime"
        role = "BASE_SZSE_AUTHORITATIVE"
        exchange = "SZSE"
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
        "published_at": published_at,
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
    return classifier.classify_exchange_announcements(pd.DataFrame(rows))


def test_sse_causal_time_is_max_of_adddate_and_next_day_ssedate() -> None:
    rows = pd.DataFrame(
        [
            _route_row(
                key="floor",
                symbol="600001.SH",
                original_time="2020-01-01 10:00:00",
                source_date="2020-01-03",
                causal_available_at="2020-01-04 00:00:00",
            ),
            _route_row(
                key="late",
                symbol="600002.SH",
                original_time="2020-01-10 11:22:33",
                source_date="2020-01-03",
                causal_available_at="2020-01-10 11:22:33",
            ),
        ]
    )

    result = subject.derive_causal_available_at(rows)

    assert result.loc[0, "causal_available_at"] == pd.Timestamp(
        "2020-01-04 00:00:00", tz="Asia/Shanghai"
    )
    assert result.loc[1, "causal_available_at"] == pd.Timestamp(
        "2020-01-10 11:22:33", tz="Asia/Shanghai"
    )
    assert result.loc[0, "original_adddate"] == "2020-01-01 10:00:00"
    assert result.loc[0, "original_ssedate"] == "2020-01-03"


def test_szse_date_only_publish_time_keeps_conservative_next_day() -> None:
    rows = pd.DataFrame(
        [
            _route_row(
                key="date-only",
                symbol="000001.SZ",
                original_time="2020-01-03",
                source_date="2020-01-03",
                causal_available_at="2020-01-04 00:00:00",
            )
        ]
    )

    result = subject.derive_causal_available_at(rows)

    assert result.loc[0, "causal_available_at"] == pd.Timestamp(
        "2020-01-04 00:00:00", tz="Asia/Shanghai"
    )
    assert result.loc[0, "original_publish_time"] == "2020-01-03"


def test_named_original_time_or_sealed_causal_drift_fails_closed() -> None:
    row = _route_row(
        key="bad",
        symbol="600001.SH",
        original_time="2020-01-01 10:00:00",
        source_date="2020-01-03",
        causal_available_at="2020-01-03 00:00:00",
    )
    row["original_adddate"] = pd.NA

    with pytest.raises(subject.V29R1Error, match="named original-time"):
        subject.derive_causal_available_at(pd.DataFrame([row]))


def test_future_causal_rows_are_not_title_classified_or_selector_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known = _route_row(
        key="known",
        symbol="600001.SH",
        original_time="2021-12-30 10:00:00",
        source_date="2021-12-30",
        causal_available_at="2021-12-31 00:00:00",
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
    real_classifier = classifier.classify_exchange_announcements

    def capture(frame: pd.DataFrame) -> pd.DataFrame:
        seen.extend(frame["announcement_id"].astype(str).tolist())
        return real_classifier(frame)

    monkeypatch.setattr(subject.classifier, "classify_exchange_announcements", capture)

    classified, scope = subject.classify_development_titles(
        pd.DataFrame([known, future])
    )

    assert seen == ["known"]
    assert set(classified["announcement_id"].astype(str)) == {"known"}
    assert scope["rows_causal_available_from_2022"] == 1
    assert scope["causal_available_from_2022_titles_read"] is False
    assert scope["causal_available_from_2022_titles_classified"] is False
    assert scope["causal_available_from_2022_rows_selector_used"] is False
    assert "neither read, classified, nor selector-used" in scope["wording_guard"]


def test_title_projection_reads_only_prefiltered_route_keys(tmp_path: Path) -> None:
    known = _route_row(
        key="known",
        symbol="600001.SH",
        original_time="2021-12-30 10:00:00",
        source_date="2021-12-30",
        causal_available_at="2021-12-31 00:00:00",
    )
    future = _route_row(
        key="future",
        symbol="600001.SH",
        original_time="2021-12-31 10:00:00",
        source_date="2021-12-31",
        causal_available_at="2022-01-01 00:00:00",
        title="未来标题不得被投影",
    )
    source = pd.DataFrame([known, future]).drop(
        columns=[
            "component_role",
            "original_adddate",
            "original_ssedate",
            "original_publish_time",
            "causal_available_at",
        ]
    )
    source_path = tmp_path / "announcements.parquet"
    source.to_parquet(source_path, index=False)
    route = pd.DataFrame([known]).drop(columns="title")

    result = subject._read_authoritative_title_rows(
        source_path,
        route,
        component_role="SSE_FULL_HISTORY_AUTHORITATIVE",
        exchange="SSE",
    )

    assert result["announcement_id"].tolist() == ["known"]
    assert result["title"].tolist() == [known["title"]]


def test_title_route_selection_is_candidate_window_union_before_title_access() -> None:
    signal = pd.Timestamp("2020-06-30 15:00:00")
    window_start = signal - pd.Timedelta(days=subject.COOLING_CALENDAR_DAYS)
    inside = _route_row(
        key="inside",
        symbol="000001.SZ",
        original_time=window_start.strftime("%Y-%m-%d %H:%M:%S"),
        source_date=window_start.strftime("%Y-%m-%d"),
        causal_available_at=window_start.strftime("%Y-%m-%d %H:%M:%S"),
    )
    outside = _route_row(
        key="outside",
        symbol="000001.SZ",
        original_time=(window_start - pd.Timedelta(seconds=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        source_date=window_start.strftime("%Y-%m-%d"),
        causal_available_at=(window_start - pd.Timedelta(seconds=1)).strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
    )
    timed = subject.derive_causal_available_at(
        pd.DataFrame([inside, outside]).drop(columns="title")
    )

    selected, scope = subject.select_candidate_window_title_routes(
        timed,
        _entries([("g", "000001.SZ", str(signal))]),
    )

    assert selected["announcement_id"].tolist() == ["inside"]
    assert scope["route_keys_selected_and_frozen_before_title_read"] == 1
    assert scope["causal_available_from_2022_titles_read"] is False


def test_open_at_inclusive_window_start_blocks_and_close_never_shortens() -> None:
    signal = pd.Timestamp("2020-06-30 15:00:00")
    start = signal - pd.Timedelta(days=subject.COOLING_CALENDAR_DAYS)
    metadata = pd.DataFrame(
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
    events = _classified(metadata.to_dict("records"))

    result = subject.apply_issuer_integrity_cooldown(
        _entries([("g", "000001.SZ", str(signal))]),
        events,
        covered_symbols=["000001.SZ"],
    ).iloc[0]

    assert bool(result.v29r1_coverage_complete)
    assert not bool(result.v29r1_issuer_integrity_cooldown_gate)
    assert result.v29r1_open_transition_count == 1
    assert result.v29r1_rejection_reason == "RECENT_HIGH_PRECISION_OPEN_ISSUER_RISK"


def test_exchange_specific_zero_event_coverage_fails_closed() -> None:
    events = _classified(
        [
            {
                "announcement_key": "irrelevant|000001.SZ",
                "announcement_id": "irrelevant",
                "symbol": "000001.SZ",
                "exchange": "SZSE",
                "title": "关于召开年度股东大会的通知",
                "available_at": "2018-01-10 10:00:00",
            }
        ]
    )
    entries = _entries(
        [
            ("sz", "000001.SZ", "2018-01-15 15:00:00"),
            ("sh", "600001.SH", "2018-01-15 15:00:00"),
        ]
    )

    result = subject.apply_issuer_integrity_cooldown(
        entries,
        events,
        covered_symbols=["000001.SZ", "600001.SH"],
    ).set_index("gap_id")

    assert not bool(result.loc["sz", "v29r1_coverage_complete"])
    assert "WINDOW_START_PRECEDES_EXCHANGE_QUERY_COVERAGE" in result.loc[
        "sz", "v29r1_rejection_reason"
    ]
    assert bool(result.loc["sh", "v29r1_coverage_complete"])
    assert bool(result.loc["sh", "v29r1_issuer_integrity_cooldown_gate"])


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


def test_exact_selected_outcome_join_rejects_one_tick_mismatch() -> None:
    selected = pd.DataFrame([_exact_row()])
    outcomes = pd.DataFrame([_exact_row(entry_raw_price=10.02)])

    with pytest.raises(subject.V29R1Error, match=r"g1\.entry_raw_price"):
        subject.verify_exact_selected_outcome_join(
            selected,
            outcomes,
            exact_fields=[
                "symbol",
                "signal_date",
                "signal_time",
                "entry_date",
                "entry_time",
                "entry_status",
                "entry_cal_idx",
                "entry_raw_price",
                "entry_coordinate_factor",
                "entry_coordinate_price",
                "entry_invalid_step_cum",
                "up_limit_price",
                "entry_at_or_before_signal",
                "entry_after_signal_period_boundary",
                "buy_at_or_above_up_limit",
            ],
        )


def test_authoritative_title_join_rejects_route_identity_drift() -> None:
    route = pd.DataFrame(
        [
            _route_row(
                key="x",
                symbol="600001.SH",
                original_time="2020-01-01 10:00:00",
                source_date="2020-01-01",
                causal_available_at="2020-01-02 00:00:00",
            )
        ]
    ).drop(columns="title")
    source_row = _route_row(
        key="x",
        symbol="600001.SH",
        original_time="2020-01-01 10:00:00",
        source_date="2020-01-01",
        causal_available_at="2020-01-02 00:00:00",
    )
    source_row["raw_record_sha256"] = "b" * 64
    source = pd.DataFrame([source_row]).drop(
        columns=[
            "component_role",
            "original_adddate",
            "original_ssedate",
            "original_publish_time",
            "causal_available_at",
        ]
    )

    with pytest.raises(subject.V29R1Error, match="raw_record_sha256"):
        subject.attach_authoritative_titles(route, source, source.iloc[0:0].copy())


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

    with pytest.raises(subject.V29R1Error, match="Stage-A outputs already exist"):
        subject.run_stage_a()


def test_prior_v29_blocker_hash_drift_fails_before_parent_source_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocker = tmp_path / "blocker.json"
    blocker.write_text(json.dumps({"tampered": True}), encoding="utf-8")
    monkeypatch.setattr(subject, "BLOCKER", blocker)
    monkeypatch.setattr(
        subject,
        "_parent_source_paths",
        lambda: pytest.fail("parent sources must not be touched after blocker drift"),
    )

    with pytest.raises(subject.V29R1Error, match="coverage blocker drifted"):
        subject._verify_protocol()


def test_registry_post_2021_authorization_drift_fails_closed(
    tmp_path: Path,
) -> None:
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
        "record_level_available_at_available": True,
        "current_survivor_fallback_allowed": False,
        "event_classification_authorized": True,
        "development_outcome_join_authorized": True,
        "portfolio_replay_authorized": True,
        "post_2021_signal_or_selector_authorized": True,
    }

    with pytest.raises(subject.V29R1Error, match="authorization flags drifted"):
        subject._validate_registry_documents(
            registry,
            asset,
            authorization,
            {},
            manifest_path=manifest_path,
        )
