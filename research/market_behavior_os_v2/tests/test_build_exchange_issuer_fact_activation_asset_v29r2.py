from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_activation_asset_v29r2 as subject,
)
from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _route_row(
    *,
    role: str,
    exchange: str,
    symbol: str,
    key: str,
    query_date: str,
    available_at: str,
    causal_available_at: str,
) -> dict[str, object]:
    is_sse = exchange == "SSE"
    publication_field = "ADDDATE" if is_sse else "publishTime"
    publication_value = available_at
    return {
        "component_role": role,
        "original_adddate": publication_value if is_sse else pd.NA,
        "original_ssedate": query_date if is_sse else pd.NA,
        "original_publish_time": pd.NA if is_sse else publication_value,
        "causal_available_at": pd.Timestamp(causal_available_at),
        "snapshot_id": f"snapshot-{exchange.lower()}",
        "announcement_key": key,
        "announcement_id": f"id-{key}",
        "source_record_key": f"raw-{key}",
        "symbol": symbol,
        "security_code": symbol[:6],
        "published_at": pd.Timestamp(available_at),
        "available_at": pd.Timestamp(available_at),
        "precision": "SOURCE_SECOND",
        "document_url": f"https://example.invalid/{key}.pdf",
        "exchange": exchange,
        "source": "OFFICIAL_EXCHANGE_ANNOUNCEMENTS",
        "source_endpoint": f"https://example.invalid/{exchange.lower()}",
        "source_publication_field": publication_field,
        "source_publication_value": publication_value,
        "source_query_date_field": "SSEDATE" if is_sse else "publishTime",
        "source_query_date": pd.Timestamp(query_date),
        "query_id": f"query-{key}",
        "query_year": int(query_date[:4]),
        "raw_record_sha256": ("a" if is_sse else "b") * 64,
        "revision_history_complete": False,
        "strict_pit_eligible": False,
        "hard_valid": True,
    }


@pytest.fixture
def bounded_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    base_root = tmp_path / "base-capture"
    base_root.mkdir()
    upstream_root = tmp_path / "CY-036-R1"
    upstream_root.mkdir()
    (upstream_root / subject.v29r1_asset.SSE_CAPTURE_NAME).mkdir()
    route = pd.DataFrame(
        [
            _route_row(
                role="SSE_FULL_HISTORY_AUTHORITATIVE",
                exchange="SSE",
                symbol="600001.SH",
                key="sse-key",
                query_date="2021-12-31",
                available_at="2021-12-31 15:30:00",
                causal_available_at="2022-01-01 00:00:00",
            ),
            _route_row(
                role="BASE_SZSE_AUTHORITATIVE",
                exchange="SZSE",
                symbol="000001.SZ",
                key="szse-key",
                query_date="2021-12-30",
                available_at="2021-12-30 17:00:00",
                causal_available_at="2021-12-30 17:00:00",
            ),
        ],
        columns=subject._EXPECTED_ROUTE_COLUMNS,
    )
    route_path = upstream_root / subject.v29r1_asset.COMPOSITE_NAME
    route.to_parquet(route_path, index=False)
    audit_path = upstream_root / subject.v29r1_asset.ACTIVATION_AUDIT_NAME
    _write_json(audit_path, {"status": "PASS"})
    manifest_path = upstream_root / subject.v29r1_asset.ASSET_MANIFEST_NAME
    source_routing = {
        "BASE_SZSE_AUTHORITATIVE": {
            "root": str(base_root.resolve()),
            "snapshot_id": "snapshot-szse",
        },
        "SSE_FULL_HISTORY_AUTHORITATIVE": {
            "root": str(
                (upstream_root / subject.v29r1_asset.SSE_CAPTURE_NAME).resolve()
            ),
            "snapshot_id": "snapshot-sse",
        },
    }
    title_roles = {
        role: {
            "nested_announcements_path": f"/fixture/{role}/announcements.parquet",
            "inventory_role": f"{role.lower()}_nested_announcements",
            "snapshot_id": values["snapshot_id"],
            "expected_exchange": "SSE" if role.startswith("SSE") else "SZSE",
        }
        for role, values in source_routing.items()
    }
    _write_json(
        manifest_path,
        {
            "asset_id": subject.UPSTREAM_ASSET_ID,
            "registered": False,
            "backtest_authorized": False,
            "content": {"route_index_includes_title": False},
            "source_routing": source_routing,
            "title_route_contract": {
                "required_access_order": ["one", "two", "three"],
                "nested_title_column": "title",
                "nested_join_keys": ["snapshot_id", "announcement_key"],
                "join_cardinality": "one_to_one",
                "roles": title_roles,
            },
            "query_coverage": {"SSE": {"end": "2021-12-31"}},
        },
    )
    for path in (route_path, audit_path, manifest_path):
        path.chmod(0o444)
    monkeypatch.setattr(
        subject,
        "EXPECTED_UPSTREAM_ROUTE_SHA256",
        collector.sha256_file(route_path),
    )
    monkeypatch.setattr(
        subject,
        "EXPECTED_UPSTREAM_AUDIT_SHA256",
        collector.sha256_file(audit_path),
    )
    monkeypatch.setattr(
        subject,
        "EXPECTED_UPSTREAM_MANIFEST_SHA256",
        collector.sha256_file(manifest_path),
    )
    calls: list[tuple[Path, Path]] = []

    def fake_validate(root: Path, base: Path) -> dict[str, object]:
        calls.append((Path(root), Path(base)))
        return {
            "status": "PASS",
            "asset_id": subject.UPSTREAM_ASSET_ID,
            "base_nested_files_verified": 11,
            "sse_nested_files_verified": 12,
            "registered": False,
            "backtest_authorized": False,
        }

    monkeypatch.setattr(subject.v29r1_asset, "validate_asset", fake_validate)
    monkeypatch.setattr(
        subject,
        "_validate_protocol",
        lambda: {
            "preregistration": {},
            "preregistration_facts": subject._file_facts(
                subject.PREREGISTRATION_PATH, "preregistration"
            ),
            "classifier_facts": subject._file_facts(
                subject.CLASSIFIER_PATH, "classifier"
            ),
        },
    )
    return {
        "base_root": base_root,
        "upstream_root": upstream_root,
        "route_path": route_path,
        "output_root": tmp_path / "CY-036-R2",
        "calls": calls,
    }


def test_build_and_validate_independent_title_free_activation_wrapper(
    bounded_case: dict[str, object],
) -> None:
    output_root = Path(bounded_case["output_root"])
    upstream_root = Path(bounded_case["upstream_root"])
    base_root = Path(bounded_case["base_root"])
    built = subject.build_asset(output_root, upstream_root, base_root)
    validated = subject.validate_asset(output_root, upstream_root, base_root)

    assert built["status"] == validated["status"] == "PASS"
    assert built["asset_id"] == validated["asset_id"] == "CY-036-R2"
    assert built["registered"] is False
    assert built["backtest_authorized"] is False
    assert built["route_index_sha256"] == collector.sha256_file(
        Path(bounded_case["route_path"])
    )
    assert (output_root / subject.ROUTE_INDEX_NAME).read_bytes() == Path(
        bounded_case["route_path"]
    ).read_bytes()
    manifest = json.loads(
        (output_root / subject.ASSET_MANIFEST_NAME).read_text(encoding="utf-8")
    )
    assert manifest["route_index_path"] == subject.ROUTE_INDEX_NAME
    assert manifest["content"]["route_index_includes_title"] is False
    assert manifest["content"]["classification_included"] is False
    assert manifest["content"]["outcomes_included_or_opened"] is False
    assert set(manifest["title_route_contract"]["roles"]) == (
        subject._EXPECTED_COMPONENT_ROLES
    )
    assert manifest["title_route_contract"]["nested_join_keys"] == [
        "snapshot_id",
        "announcement_key",
    ]
    assert manifest["title_route_contract"]["activation_wrapper"][
        "title_column_projected_or_opened_by_builder"
    ] is False
    audit = json.loads(
        (output_root / subject.ACTIVATION_AUDIT_NAME).read_text(encoding="utf-8")
    )
    assert audit["protocol"]["outcome_files_access"] == "NONE"
    assert audit["checks"]["post_2021_title_opened_or_classified"] is False
    assert audit["checks"]["classifier_executed"] is False
    assert audit["counts"]["causal_available_at_from_2022_rows"] == 1
    assert len(bounded_case["calls"]) == 2


def test_upstream_route_byte_drift_fails_closed(
    bounded_case: dict[str, object],
) -> None:
    route_path = Path(bounded_case["route_path"])
    route_path.chmod(0o644)
    route_path.write_bytes(route_path.read_bytes() + b"drift")
    route_path.chmod(0o444)
    with pytest.raises(subject.V29R2AssetError, match="route index differs"):
        subject.build_asset(
            Path(bounded_case["output_root"]),
            Path(bounded_case["upstream_root"]),
            Path(bounded_case["base_root"]),
        )


def test_upstream_source_validation_failure_is_wrapped(
    bounded_case: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_validation(_root: Path, _base: Path) -> dict[str, object]:
        raise RuntimeError("nested source mismatch")

    monkeypatch.setattr(subject.v29r1_asset, "validate_asset", fail_validation)
    with pytest.raises(subject.V29R2AssetError, match="full source revalidation failed"):
        subject.build_asset(
            Path(bounded_case["output_root"]),
            Path(bounded_case["upstream_root"]),
            Path(bounded_case["base_root"]),
        )


def test_post_2021_query_partition_fails_closed(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            _route_row(
                role="SSE_FULL_HISTORY_AUTHORITATIVE",
                exchange="SSE",
                symbol="600001.SH",
                key="late",
                query_date="2022-01-01",
                available_at="2022-01-01 08:00:00",
                causal_available_at="2022-01-02 00:00:00",
            ),
            _route_row(
                role="BASE_SZSE_AUTHORITATIVE",
                exchange="SZSE",
                symbol="000001.SZ",
                key="old",
                query_date="2021-12-31",
                available_at="2021-12-31 08:00:00",
                causal_available_at="2021-12-31 08:00:00",
            ),
        ],
        columns=subject._EXPECTED_ROUTE_COLUMNS,
    )
    path = tmp_path / "route.parquet"
    frame.to_parquet(path, index=False)
    with pytest.raises(subject.V29R2AssetError, match="post-2021 source query"):
        subject._validate_route_frame(path)


def test_title_column_in_route_fails_closed(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            _route_row(
                role="SSE_FULL_HISTORY_AUTHORITATIVE",
                exchange="SSE",
                symbol="600001.SH",
                key="one",
                query_date="2021-12-31",
                available_at="2021-12-31 08:00:00",
                causal_available_at="2022-01-01 00:00:00",
            )
        ],
        columns=subject._EXPECTED_ROUTE_COLUMNS,
    )
    frame["title"] = "must not be here"
    path = tmp_path / "route.parquet"
    frame.to_parquet(path, index=False)
    with pytest.raises(subject.V29R2AssetError, match="columns drifted"):
        subject._validate_route_frame(path)


def test_live_protocol_and_classifier_hashes_are_self_consistent() -> None:
    validated = subject._validate_protocol()
    assert validated["preregistration"]["experiment"] == subject.EXPERIMENT
    assert validated["preregistration_facts"]["sha256"] == (
        "076566c5cd85158997d39e4690c090e98110e85597d55ebf7d5b4fa0e63a5a3a"
    )
    assert validated["classifier_facts"]["sha256"] == (
        "127f62e551d4344ede9d41970ea7a6634f5f4b192fe2829a78eed8c72cf2da9d"
    )


def test_preregistration_byte_drift_fails_before_json_is_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "preregistration.json"
    path.write_bytes(subject.PREREGISTRATION_PATH.read_bytes() + b"\n")
    monkeypatch.setattr(subject, "PREREGISTRATION_PATH", path)
    with pytest.raises(subject.V29R2AssetError, match="frozen identity"):
        subject._validate_protocol()


def test_classifier_byte_drift_fails_before_it_can_be_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "classifier.py"
    path.write_text("# drifted classifier\n", encoding="utf-8")
    monkeypatch.setattr(subject, "CLASSIFIER_PATH", path)
    with pytest.raises(subject.V29R2AssetError, match="frozen byte identity"):
        subject._validate_protocol()
