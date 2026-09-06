from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_exchange_issuer_fact_rollforward_asset_v29r2 as subject,
)


def _row(
    key: str,
    symbol: str,
    exchange: str,
    *,
    snapshot: str,
    raw_hash: str,
) -> dict[str, object]:
    publication_field = "ADDDATE" if exchange == "SSE" else "publishTime"
    query_field = "SSEDATE" if exchange == "SSE" else "publishTime"
    return {
        "snapshot_id": snapshot,
        "announcement_key": key,
        "announcement_id": key,
        "symbol": symbol,
        "exchange": exchange,
        "published_at": pd.Timestamp("2022-01-02 09:00:00"),
        "available_at": pd.Timestamp("2022-01-02 09:00:00"),
        "precision": "SOURCE_SECOND",
        "source_publication_field": publication_field,
        "source_publication_value": "2022-01-02 09:00:00",
        "source_query_date_field": query_field,
        "source_query_date": pd.Timestamp("2022-01-02"),
        "query_year": 2022,
        "raw_record_sha256": raw_hash,
        "revision_history_complete": False,
        "strict_pit_eligible": False,
        "hard_valid": True,
    }


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=subject.SOURCE_IDENTITY_COLUMNS)


def test_dual_source_route_uses_only_full_sse_and_window_szse() -> None:
    window = _frame(
        [
            _row("sh", "600000.SH", "SSE", snapshot="window", raw_hash="a" * 64),
            _row("sz", "000001.SZ", "SZSE", snapshot="window", raw_hash="b" * 64),
        ]
    )
    full = _frame([_row("sh", "600000.SH", "SSE", snapshot="full", raw_hash="a" * 64)])
    result = subject.build_route({"600000.SH", "000001.SZ"}, window, full)
    assert list(result.columns) == subject.ROUTE_COLUMNS
    assert result.set_index("symbol").component_role.to_dict() == {
        "600000.SH": subject.SSE_ROLE,
        "000001.SZ": subject.SZSE_ROLE,
    }
    assert result.set_index("symbol").snapshot_id.to_dict()["600000.SH"] == "full"
    assert "title" not in result


def test_query_coverage_requires_exact_contiguous_symbol_year_map() -> None:
    symbols = ["000001.SZ"]
    specs = subject.collector.build_query_specs(symbols, "2021-10-18", "2022-02-02")
    pages = pd.DataFrame(
        [
            {
                "query_id": spec.query_id,
                "exchange": spec.exchange,
                "symbol": spec.symbol,
                "query_start": spec.start,
                "query_end": spec.end,
            }
            for spec in specs
        ]
    )
    subject.validate_query_coverage(
        pages,
        symbols,
        start="2021-10-18",
        end="2022-02-02",
        label="test",
    )
    with pytest.raises(subject.AssetError, match="query map drifted"):
        subject.validate_query_coverage(
            pages.iloc[:-1],
            symbols,
            start="2021-10-18",
            end="2022-02-02",
            label="test",
        )


def test_sse_overlap_requires_exact_normalized_and_raw_record_identity() -> None:
    window = _frame([_row("sh", "600000.SH", "SSE", snapshot="window", raw_hash="a" * 64)])
    full = _frame([_row("sh", "600000.SH", "SSE", snapshot="full", raw_hash="a" * 64)])
    assert subject.compare_sse_overlap(window, full)["key_sets_equal"] is True
    full.loc[0, "raw_record_sha256"] = "b" * 64
    with pytest.raises(subject.AssetError, match="identity drifted"):
        subject.compare_sse_overlap(window, full)


def test_validate_inputs_rejects_arbitrary_runner_before_source_access(tmp_path: Path) -> None:
    wrong_runner = tmp_path / "wrong.py"
    wrong_runner.write_text("# wrong\n", encoding="utf-8")
    with pytest.raises(subject.AssetError, match="unexpected roll-forward runner"):
        subject.validate_inputs(
            tmp_path,
            tmp_path / "selected.parquet",
            tmp_path / "outcomes.parquet",
            tmp_path / "daily.parquet",
            wrong_runner,
        )


def test_validate_reconstructs_and_rejects_manifest_semantic_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in subject.EXPECTED_TOP_BEFORE:
        path = tmp_path / name
        if "." in name:
            path.write_bytes(b"placeholder")
        else:
            path.mkdir()
    route = pd.DataFrame({"announcement_key": ["a"]})
    route_path = tmp_path / "announcement_route_index.parquet"
    route.to_parquet(route_path, index=False)
    audit_path = tmp_path / "activation_audit.json"
    audit = {"validated_at": "2026-09-06T00:00:00+00:00"}
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    audit_path.chmod(0o444)
    bound = tmp_path / "source_capture/bound.bin"
    bound.write_bytes(b"bound")
    digest = hashlib.sha256(bound.read_bytes()).hexdigest()
    inventory = [
        {
            "role": role,
            "path": str(bound),
            "sha256": digest,
            "bytes": len(b"bound"),
            "content_read_during_asset_build": False,
        }
        for role in subject.INVENTORY_ROLE_ORDER
    ]
    clean = {
        "created_at": audit["validated_at"],
        "inventory": inventory,
        "status": "SEALED_PENDING_CENTRAL_REGISTRATION",
    }
    tampered = {**clean, "status": "TAMPERED"}
    manifest_path = tmp_path / "asset_manifest.json"
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    manifest_path.chmod(0o444)
    validated = {"route": route}
    monkeypatch.setattr(subject, "validate_inputs", lambda *args: validated)
    monkeypatch.setattr(subject, "build_audit", lambda *args: audit)
    monkeypatch.setattr(subject, "binding_inventory", lambda *args: inventory)
    monkeypatch.setattr(subject, "build_manifest", lambda *args: clean)
    with pytest.raises(subject.AssetError, match="semantic content drifted"):
        subject.validate(tmp_path)
