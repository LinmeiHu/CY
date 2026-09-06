from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_risk_composite_asset_v29r1 as subject,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _identity_row(
    *,
    snapshot_id: str,
    key: str,
    symbol: str,
    exchange: str,
    source_query_date: str,
    available_at: str,
    raw_record_sha256: str,
) -> dict[str, object]:
    code = symbol[:6]
    is_sse = exchange == "SSE"
    published = pd.Timestamp(available_at)
    return {
        "snapshot_id": snapshot_id,
        "announcement_key": key,
        "announcement_id": f"{exchange}-{key}",
        "source_record_key": f"raw-{key}",
        "symbol": symbol,
        "security_code": code,
        "published_at": published,
        "available_at": published,
        "precision": "SOURCE_SECOND",
        "document_url": f"https://example.invalid/{key}.pdf",
        "exchange": exchange,
        "source": collector.SOURCE_NAME,
        "source_endpoint": collector.SSE_ENDPOINT if is_sse else collector.SZSE_ENDPOINT,
        "source_publication_field": "ADDDATE" if is_sse else "publishTime",
        "source_publication_value": available_at,
        "source_query_date_field": "SSEDATE" if is_sse else "publishTime",
        "source_query_date": pd.Timestamp(source_query_date),
        "query_id": f"{exchange}-{code}-{source_query_date[:4]}",
        "query_year": int(source_query_date[:4]),
        "query_page": 1,
        "retrieved_at": "2026-09-05T00:00:00+00:00",
        "raw_body_path": f"raw/{exchange.lower()}/{code}/page_0001.json",
        "raw_body_sha256": "e" * 64,
        "raw_record_sha256": raw_record_sha256,
        "revision_history_complete": False,
        "strict_pit_eligible": False,
        "hard_valid": True,
    }


def _page_rows(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    rows = []
    for spec in collector.build_query_specs(symbols, start, end):
        rows.append(
            {
                "query_id": spec.query_id,
                "exchange": spec.exchange,
                "symbol": spec.symbol,
                "query_year": spec.year,
                "query_start": spec.start,
                "query_end": spec.end,
                "page": 1,
            }
        )
    return pd.DataFrame(rows)


def _capture(
    root: Path,
    universe: Path,
    *,
    start: str,
    end: str,
    snapshot_id: str,
    rows: list[dict[str, object]],
    symbols: list[str],
) -> None:
    root.mkdir(parents=True)
    pd.DataFrame(rows, columns=subject._IDENTITY_COLUMNS).to_parquet(
        root / "announcements.parquet", index=False
    )
    _page_rows(symbols, start, end).to_parquet(root / "request_pages.parquet", index=False)
    _write_json(
        root / "source_manifest.json",
        {
            "asset_id": collector.ASSET_ID,
            "coverage": {"start": start, "end": end},
            "snapshot_id": snapshot_id,
            "universe_source": str(universe.resolve()),
            "backtest_authorized": False,
        },
    )
    _write_json(
        root / "asset_manifest.json",
        {
            "asset_id": collector.ASSET_ID,
            "snapshot_id": snapshot_id,
            "backtest_authorized": False,
        },
    )
    _write_json(root / "audit.json", {"status": "PASS"})
    _write_json(root / "audit_validation.json", {"status": "PASS"})


@pytest.fixture
def bounded_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    base_symbols = ["000001.SZ", "600001.SH", "600002.SH"]
    sse_symbols = ["600001.SH", "600002.SH"]
    monkeypatch.setattr(subject, "EXPECTED_BASE_SYMBOLS", 3)
    monkeypatch.setattr(subject, "EXPECTED_SSE_SYMBOLS", 2)

    base_parent = tmp_path / "base-parent"
    base_parent.mkdir()
    base_universe = base_parent / "universe.parquet"
    pd.DataFrame({"symbol": base_symbols}).to_parquet(base_universe, index=False)
    monkeypatch.setattr(
        subject,
        "EXPECTED_BASE_UNIVERSE_SHA256",
        collector.sha256_file(base_universe),
    )
    base_capture = base_parent / "source_capture"
    overlap = _identity_row(
        snapshot_id="base-snapshot",
        key="shared-sse",
        symbol="600001.SH",
        exchange="SSE",
        source_query_date="2018-01-02",
        available_at="2017-12-29 16:00:00",
        raw_record_sha256="a" * 64,
    )
    szse = _identity_row(
        snapshot_id="base-snapshot",
        key="base-szse",
        symbol="000001.SZ",
        exchange="SZSE",
        source_query_date="2018-02-01",
        available_at="2018-02-01 10:00:00",
        raw_record_sha256="b" * 64,
    )
    _capture(
        base_capture,
        base_universe,
        start=subject.BASE_QUERY_START,
        end=subject.QUERY_END,
        snapshot_id="base-snapshot",
        rows=[overlap, szse],
        symbols=base_symbols,
    )
    monkeypatch.setattr(subject, "EXPECTED_BASE_SNAPSHOT_ID", "base-snapshot")
    monkeypatch.setattr(
        subject,
        "EXPECTED_BASE_ASSET_MANIFEST_SHA256",
        collector.sha256_file(base_capture / "asset_manifest.json"),
    )

    asset_root = tmp_path / "CY-036-R1"
    prepared = subject.prepare_sse_universe(base_capture, asset_root)
    assert prepared["symbols"] == 2
    sse_universe = asset_root / subject.SSE_UNIVERSE_NAME
    history_overlap = dict(overlap, snapshot_id="history-snapshot")
    old_sse = _identity_row(
        snapshot_id="history-snapshot",
        key="old-sse",
        symbol="600002.SH",
        exchange="SSE",
        source_query_date="2000-01-03",
        available_at="2000-01-03 15:00:00",
        raw_record_sha256="c" * 64,
    )
    history_capture = asset_root / subject.SSE_CAPTURE_NAME
    _capture(
        history_capture,
        sse_universe,
        start=subject.SSE_QUERY_START,
        end=subject.QUERY_END,
        snapshot_id="history-snapshot",
        rows=[old_sse, history_overlap],
        symbols=sse_symbols,
    )

    lineage = tmp_path / "lineage"
    lineage.mkdir()
    prereg = lineage / "prereg.json"
    blocker = lineage / "blocker.json"
    parent_runner = lineage / "runner.py"
    parent_stage = lineage / "stage.json"
    parent_result = lineage / "result.json"
    for path in (prereg, blocker, parent_runner, parent_stage, parent_result):
        path.write_text(f"fixture {path.name}\n", encoding="utf-8")
    monkeypatch.setattr(subject, "PREREGISTRATION_PATH", prereg)
    monkeypatch.setattr(subject, "V29_BLOCKER_PATH", blocker)
    monkeypatch.setattr(subject, "V28R2_RUNNER_PATH", parent_runner)
    monkeypatch.setattr(subject, "V28R2_STAGE_A_PATH", parent_stage)
    monkeypatch.setattr(subject, "V28R2_DEVELOPMENT_RESULT_PATH", parent_result)

    protocol = {
        "preregistration": {},
        "preregistration_facts": subject._file_facts(prereg, "prereg"),
        "blocker_facts": subject._file_facts(blocker, "blocker"),
        "parent_facts": {
            "parent_runner_sha256": subject._file_facts(parent_runner, "runner"),
            "parent_development_stage_a_sha256": subject._file_facts(parent_stage, "stage"),
            "parent_development_result_sha256": subject._file_facts(parent_result, "result"),
        },
    }
    monkeypatch.setattr(subject, "_validate_preregistration", lambda: protocol)

    def fake_validate(root: Path) -> dict[str, object]:
        resolved = Path(root).resolve()
        if resolved == base_capture.resolve():
            snapshot = "base-snapshot"
        elif resolved == history_capture.resolve():
            snapshot = "history-snapshot"
        else:
            raise AssertionError(f"unexpected source root {root}")
        return {
            "status": "PASS",
            "snapshot_id": snapshot,
            "asset_manifest_sha256": collector.sha256_file(root / "asset_manifest.json"),
            "files_verified": 11,
            "backtest_authorized": False,
        }

    monkeypatch.setattr(subject.source_sealer, "validate_asset", fake_validate)
    return {
        "root": asset_root,
        "base": base_capture,
        "history": history_capture,
    }


def test_build_and_validate_routed_read_only_wrapper(bounded_case: dict[str, Path]) -> None:
    built = subject.build_asset(bounded_case["root"], bounded_case["base"])
    validated = subject.validate_asset(bounded_case["root"], bounded_case["base"])

    assert built["status"] == validated["status"] == "PASS"
    assert built["asset_id"] == validated["asset_id"] == "CY-036-R1"
    assert built["registered"] is False
    assert built["backtest_authorized"] is False
    routed = pd.read_parquet(bounded_case["root"] / subject.COMPOSITE_NAME)
    assert "title" not in routed.columns
    assert routed.columns.tolist() == [
        "component_role",
        "original_adddate",
        "original_ssedate",
        "original_publish_time",
        "causal_available_at",
        *subject._IDENTITY_COLUMNS,
    ]
    assert len(routed.columns) == 28
    assert routed.component_role.tolist() == [
        "SSE_FULL_HISTORY_AUTHORITATIVE",
        "SSE_FULL_HISTORY_AUTHORITATIVE",
        "BASE_SZSE_AUTHORITATIVE",
    ]
    shared = routed.loc[routed.announcement_key.eq("shared-sse")].iloc[0]
    assert shared.original_adddate == "2017-12-29 16:00:00"
    assert shared.original_ssedate == "2018-01-02"
    assert pd.Timestamp(shared.causal_available_at) == pd.Timestamp("2018-01-03")
    manifest = json.loads(
        (bounded_case["root"] / subject.ASSET_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["registered"] is False
    assert manifest["backtest_authorized"] is False
    assert manifest["pit"]["grade"] == "B"
    assert manifest["pit"]["revision_history_incomplete"] is True
    assert manifest["pit"]["knowledge_time"] == "causal_available_at only"
    assert manifest["content"]["route_index_includes_title"] is False
    assert manifest["source_routing"]["SSE_FULL_HISTORY_AUTHORITATIVE"][
        "query_start"
    ] == "1990-12-19"
    assert manifest["source_routing"]["SSE_FULL_HISTORY_AUTHORITATIVE"][
        "causal_availability_field"
    ] == subject.SSE_CAUSAL_AVAILABLE_AT_CONTRACT
    title_contract = manifest["title_route_contract"]
    assert title_contract["nested_join_keys"] == ["snapshot_id", "announcement_key"]
    assert title_contract["join_cardinality"] == "one_to_one"
    assert title_contract["roles"]["SSE_FULL_HISTORY_AUTHORITATIVE"][
        "inventory_role"
    ] == "sse_full_history_nested_announcements"
    roles = {row["role"] for row in manifest["inventory"]}
    assert {
        "v29r1_composite_builder_code",
        "exchange_announcement_collector_code",
        "exchange_announcement_sealer_code",
        "base_nested_announcements",
        "sse_full_history_nested_announcements",
    }.issubset(roles)
    audit = json.loads(
        (bounded_case["root"] / subject.ACTIVATION_AUDIT_NAME).read_text(encoding="utf-8")
    )
    assert audit["checks"]["nested_sealer_validated_title_metadata_from_raw_pages"] is True
    assert audit["checks"]["wrapper_projected_or_classified_title_column"] is False


def test_overlap_raw_record_conflict_fails_closed(bounded_case: dict[str, Path]) -> None:
    path = bounded_case["history"] / "announcements.parquet"
    frame = pd.read_parquet(path)
    frame.loc[frame.announcement_key.eq("shared-sse"), "raw_record_sha256"] = "d" * 64
    frame.to_parquet(path, index=False)

    with pytest.raises(subject.V29R1AssetError, match="raw_record_sha256"):
        subject.build_asset(bounded_case["root"], bounded_case["base"])


def test_query_gap_fails_closed() -> None:
    pages = _page_rows(["600001.SH"], "2019-01-01", "2020-12-31")
    pages = pages.loc[pages.query_year.ne(2020)].copy()
    with pytest.raises(subject.V29R1AssetError, match="gap, overlap, or identity drift"):
        subject._validate_query_coverage(
            pages,
            ["600001.SH"],
            start="2019-01-01",
            end="2020-12-31",
            label="fixture",
        )


def test_exact_live_preregistration_and_parent_hashes_are_self_consistent() -> None:
    validated = subject._validate_preregistration()
    assert validated["preregistration"]["experiment"] == subject.EXPERIMENT
    assert validated["preregistration_facts"]["sha256"] == (
        "583e35cf4722daf569feec8bc64118cf430aa5b278b4c7149d6147ef79504b34"
    )


def test_preregistration_byte_drift_fails_before_json_is_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drifted = tmp_path / "drifted-prereg.json"
    drifted.write_bytes(subject.PREREGISTRATION_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(subject, "PREREGISTRATION_PATH", drifted)

    with pytest.raises(subject.V29R1AssetError, match="frozen identity"):
        subject._validate_preregistration()


def test_collector_code_lineage_drift_invalidates_wrapper(
    bounded_case: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    subject.build_asset(bounded_case["root"], bounded_case["base"])
    drifted = tmp_path / "collector_drift.py"
    drifted.write_text("# different collector identity\n", encoding="utf-8")
    monkeypatch.setattr(subject.collector, "__file__", str(drifted))

    with pytest.raises(subject.V29R1AssetError, match="activation audit content drifted"):
        subject.validate_asset(bounded_case["root"], bounded_case["base"])
