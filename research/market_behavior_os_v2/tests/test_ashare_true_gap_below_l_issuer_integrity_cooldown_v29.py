from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    classify_exchange_issuer_risk_events_v1 as classifier,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_issuer_integrity_cooldown_v29 as subject,
)


def _entries(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gap_id": [row[0] for row in rows],
            "symbol": [row[1] for row in rows],
            "signal_date": [pd.Timestamp(row[2]).normalize() for row in rows],
            "signal_time": [pd.Timestamp(row[2]) for row in rows],
        }
    )


def _metadata(rows: list[dict[str, object]]) -> pd.DataFrame:
    values: list[dict[str, object]] = []
    for number, row in enumerate(rows, start=1):
        symbol = str(row.get("symbol", "000001.SZ"))
        exchange = "SSE" if symbol.endswith(".SH") else "SZSE"
        announcement_id = str(row.get("announcement_id", f"a{number}"))
        available_at = row["available_at"]
        values.append(
            {
                "announcement_key": f"{announcement_id}|{symbol}",
                "announcement_id": announcement_id,
                "symbol": symbol,
                "exchange": exchange,
                "title": row["title"],
                "published_at": row.get("published_at", available_at),
                "available_at": available_at,
                "precision": row.get("precision", "SOURCE_SECOND"),
            }
        )
    return pd.DataFrame(values)


def _classified(rows: list[dict[str, object]]) -> pd.DataFrame:
    return classifier.classify_exchange_announcements(_metadata(rows))


def test_open_at_inclusive_window_start_blocks_even_after_close() -> None:
    signal = pd.Timestamp("2020-06-30 15:00:00")
    window_start = signal - pd.Timedelta(days=subject.COOLING_CALENDAR_DAYS)
    events = _classified(
        [
            {
                "announcement_id": "open",
                "title": "关于收到中国证监会立案调查通知书的公告",
                "available_at": window_start,
            },
            {
                "announcement_id": "close",
                "title": "关于撤销立案的公告",
                "available_at": window_start + pd.Timedelta(days=10),
            },
        ]
    )

    result = subject.apply_issuer_integrity_cooldown(
        _entries([("g1", "000001.SZ", str(signal))]),
        events,
        covered_symbols=["000001.SZ"],
    ).iloc[0]

    assert bool(result.v29_coverage_complete)
    assert not bool(result.v29_issuer_integrity_cooldown_gate)
    assert result.v29_open_transition_count == 1
    assert result.v29_open_announcement_count == 1
    assert result.v29_open_announcement_keys == "open|000001.SZ"
    assert result.v29_open_risk_families == classifier.FAMILY_INVESTIGATION
    assert result.v29_rejection_reason == "RECENT_HIGH_PRECISION_OPEN_ISSUER_RISK"


def test_available_at_is_the_only_knowledge_time_and_end_is_inclusive() -> None:
    signal = pd.Timestamp("2020-06-30 15:00:00")
    events = _classified(
        [
            {
                "symbol": "000001.SZ",
                "announcement_id": "date-only-late",
                "title": "关于公司银行账户被冻结的公告",
                "published_at": "2020-06-30 00:00:00",
                "available_at": "2020-07-01 00:00:00",
                "precision": "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY",
            },
            {
                "symbol": "000002.SZ",
                "announcement_id": "exact-end",
                "title": "关于公司银行账户被冻结的公告",
                "available_at": signal,
            },
        ]
    )
    entries = _entries(
        [
            ("g1", "000001.SZ", str(signal)),
            ("g2", "000002.SZ", str(signal)),
        ]
    )

    result = subject.apply_issuer_integrity_cooldown(
        entries,
        events,
        covered_symbols=["000001.SZ", "000002.SZ"],
    ).set_index("gap_id")

    assert bool(result.loc["g1", "v29_issuer_integrity_cooldown_gate"])
    assert result.loc["g1", "v29_open_transition_count"] == 0
    assert not bool(result.loc["g2", "v29_issuer_integrity_cooldown_gate"])
    assert result.loc["g2", "v29_open_transition_count"] == 1


@pytest.mark.parametrize(
    ("signal", "symbol", "covered", "expected_reason"),
    [
        (
            "2018-01-15 15:00:00",
            "000001.SZ",
            ["000001.SZ"],
            "WINDOW_START_PRECEDES_SEALED_CAPTURE",
        ),
        (
            "2020-06-30 15:00:00",
            "000002.SZ",
            ["000001.SZ"],
            "SYMBOL_NOT_IN_SEALED_UNIVERSE",
        ),
    ],
)
def test_zero_events_rejects_when_coverage_is_not_proven(
    signal: str,
    symbol: str,
    covered: list[str],
    expected_reason: str,
) -> None:
    events = _classified(
        [
            {
                "announcement_id": "irrelevant",
                "title": "关于召开年度股东大会的通知",
                "available_at": "2020-01-02 10:00:00",
            }
        ]
    )

    result = subject.apply_issuer_integrity_cooldown(
        _entries([("g", symbol, signal)]),
        events,
        covered_symbols=covered,
    ).iloc[0]

    assert result.v29_open_transition_count == 0
    assert not bool(result.v29_coverage_complete)
    assert not bool(result.v29_issuer_integrity_cooldown_gate)
    assert expected_reason in result.v29_rejection_reason


def test_classifier_version_unknown_fails_closed() -> None:
    events = _classified(
        [
            {
                "announcement_id": "irrelevant",
                "title": "关于召开年度股东大会的通知",
                "available_at": "2020-01-02 10:00:00",
            }
        ]
    )
    events.loc[:, "classification_version"] = "UNREGISTERED_RULES"

    with pytest.raises(subject.V29Error, match="classification version drifted"):
        subject.apply_issuer_integrity_cooldown(
            _entries([("g", "000001.SZ", "2020-06-30 15:00:00")]),
            events,
            covered_symbols=["000001.SZ"],
        )


def test_unregistered_cy036_fails_before_any_asset_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "global_gate": {
                    "free_causal_research_ready": True,
                    "backtest_authorized": True,
                },
                "assets": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(subject, "REGISTRY", registry)

    with pytest.raises(subject.V29Error, match="CY-036 must resolve to exactly one"):
        subject.verify_registered_cy036()


def test_post_development_available_rows_are_not_title_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / subject.cy036.SOURCE_CAPTURE_NAME
    source.mkdir()
    (source / "announcements.parquet").touch()
    metadata = pd.DataFrame(
        [
            {
                "snapshot_id": "snapshot-1",
                "announcement_key": "known|600001.SH",
                "announcement_id": "known",
                "symbol": "600001.SH",
                "exchange": "SSE",
                "title": "关于召开年度股东大会的通知",
                "published_at": "2021-12-31 15:30:00",
                "available_at": "2021-12-31 15:30:00",
                "precision": "SOURCE_SECOND",
                "hard_valid": True,
                "revision_history_complete": False,
                "strict_pit_eligible": False,
                "query_year": 2021,
                "source_query_date": "2021-12-31",
            },
            {
                "snapshot_id": "snapshot-1",
                "announcement_key": "late|600001.SH",
                "announcement_id": "late",
                "symbol": "600001.SH",
                "exchange": "SSE",
                "title": "关于收到中国证监会立案调查通知书的公告",
                "published_at": "2022-01-03 10:00:00",
                "available_at": "2022-01-03 10:00:00",
                "precision": "SOURCE_SECOND",
                "hard_valid": True,
                "revision_history_complete": False,
                "strict_pit_eligible": False,
                "query_year": 2021,
                "source_query_date": "2021-12-31",
            },
        ]
    )
    monkeypatch.setattr(subject.pd, "read_parquet", lambda _path: metadata.copy())
    real_classifier = classifier.classify_exchange_announcements
    classified_ids: list[str] = []

    def classify_only_development(frame: pd.DataFrame) -> pd.DataFrame:
        classified_ids.extend(frame["announcement_id"].astype(str).tolist())
        return real_classifier(frame)

    monkeypatch.setattr(
        subject.classifier,
        "classify_exchange_announcements",
        classify_only_development,
    )

    classified, scope = subject._load_and_validate_announcements(
        {"asset_root": str(tmp_path), "source_snapshot_id": "snapshot-1"}
    )

    assert classified_ids == ["known"]
    assert set(classified["announcement_id"].astype(str)) == {"known"}
    assert scope["sealed_source_rows"] == 2
    assert scope["classified_rows_available_before_2022"] == 1
    assert scope["unclassified_rows_available_from_2022"] == 1
    assert scope["future_available_titles_classified"] is False


def test_stage_a_refuses_to_overwrite_any_frozen_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subject, "EXT_ROOT", tmp_path / "external")
    frozen = tmp_path / "stage_a.json"
    frozen.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(subject, "STAGE_A_FREEZE", frozen)
    monkeypatch.setattr(subject, "DEVELOPMENT_RESULT", tmp_path / "development.json")
    monkeypatch.setattr(subject, "REPORT", tmp_path / "report.md")
    monkeypatch.setattr(
        subject,
        "_verify_preregistration_and_parent",
        lambda: pytest.fail("protocol must not be read after overwrite guard fails"),
    )

    with pytest.raises(subject.V29Error, match="Stage-A outputs already exist"):
        subject.run_stage_a()


def test_pristine_stage_a_fails_closed_on_the_frozen_coverage_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subject, "EXT_ROOT", tmp_path / "external")
    monkeypatch.setattr(subject, "STAGE_A_FREEZE", tmp_path / "stage_a.json")
    monkeypatch.setattr(subject, "DEVELOPMENT_RESULT", tmp_path / "development.json")
    monkeypatch.setattr(subject, "REPORT", tmp_path / "report.md")

    with pytest.raises(subject.V29Error, match="retired and backtest-prohibited"):
        subject.run_stage_a()


def test_development_refuses_to_overwrite_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subject, "EXT_ROOT", tmp_path / "external")
    result = tmp_path / "development.json"
    result.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(subject, "DEVELOPMENT_RESULT", result)
    monkeypatch.setattr(subject, "REPORT", tmp_path / "report.md")
    monkeypatch.setattr(
        subject,
        "verify_stage_a",
        lambda: pytest.fail("Stage A must not be read after overwrite guard fails"),
    )

    with pytest.raises(subject.V29Error, match="development outputs already exist"):
        subject.run_development()
