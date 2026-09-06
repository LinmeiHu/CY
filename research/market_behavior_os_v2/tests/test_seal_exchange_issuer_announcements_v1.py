from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as collector,
)
from research.market_behavior_os_v2.scripts import (
    seal_exchange_issuer_announcements_v1 as subject,
)


def _raw_row(index: int) -> dict:
    return {
        "annId": f"ANN-{index:03d}",
        "title": f"<em>测试公告</em> {index}",
        "publishTime": "2021-06-30" if index % 2 else "2021-06-30 18:30:00",
        "attachPath": f"/disc/test/{index}.PDF",
        "secCode": ["000001"],
        "secName": ["测试公司"],
    }


def _fetched(payload: dict, page: int) -> collector.FetchedPage:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    method, url, params, json_body, headers = collector.build_request(
        "SZSE",
        "000001",
        "2021-01-01",
        "2021-12-31",
        page,
        cache_buster="123",
    )
    return collector.FetchedPage(
        body=body,
        method=method,
        url=url,
        params=params,
        json_body=json_body,
        request_headers=headers,
        response_headers={"Content-Type": "application/json"},
        status_code=200,
        retrieved_at="2026-09-05T00:00:00+00:00",
    )


def _sse_raw_row(published_at: str, source_query_date: str, suffix: str) -> dict:
    return {
        "SECURITY_CODE": "600008",
        "SECURITY_NAME": "测试股份",
        "ADDDATE": published_at,
        "SSEDATE": source_query_date,
        "TITLE": f"测试公告 {suffix}",
        "URL": f"/disclosure/listedinfo/announcement/c/new/{suffix}.pdf",
    }


def _sse_fetched(
    payload: dict, *, start: str = "2021-01-01", end: str = "2021-12-31"
) -> collector.FetchedPage:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    method, url, params, json_body, headers = collector.build_request(
        "SSE",
        "600008",
        start,
        end,
        1,
        cache_buster="123",
    )
    return collector.FetchedPage(
        body=body,
        method=method,
        url=url,
        params=params,
        json_body=json_body,
        request_headers=headers,
        response_headers={"Content-Type": "application/json"},
        status_code=200,
        retrieved_at="2026-09-05T00:00:00+00:00",
    )


def _capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    universe = (tmp_path / "universe.parquet").resolve()
    pd.DataFrame({"symbol": ["000001.SZ"]}).to_parquet(universe, index=False)

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, spec, retries, timeout
        records = [_raw_row(index) for index in range(50)] if page == 1 else [_raw_row(50)]
        return _fetched({"announceCount": 51, "data": records}, page)

    monkeypatch.setattr(collector, "fetch_page", fake_fetch)
    output = (tmp_path / "capture").resolve()
    collector.run_capture(
        universe,
        output,
        "2021-01-01",
        "2021-12-31",
        workers=1,
    )
    return output


def _sse_cross_year_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    universe = (tmp_path / "universe.parquet").resolve()
    pd.DataFrame({"symbol": ["600008.SH"]}).to_parquet(universe, index=False)
    payload = {
        "pageHelp": {
            "total": 2,
            "pageCount": 1,
            "data": [
                _sse_raw_row("2020-12-31 15:52:13", "2021-01-01", "cross-year"),
                _sse_raw_row("2021-01-02 09:05:00", "2021-01-02", "same-day"),
            ],
        }
    }

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, spec, page, retries, timeout
        return _sse_fetched(payload)

    monkeypatch.setattr(collector, "fetch_page", fake_fetch)
    output = (tmp_path / "capture").resolve()
    collector.run_capture(
        universe,
        output,
        "2021-01-01",
        "2021-12-31",
        workers=1,
    )
    return output


def _sse_late_backfill_capture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    universe = (tmp_path / "universe.parquet").resolve()
    pd.DataFrame({"symbol": ["600008.SH"]}).to_parquet(universe, index=False)
    timing_pairs = [
        ("2019-12-06 19:57:18", "2019-12-05"),
        ("2019-12-10 19:38:33", "2019-10-16"),
        ("2019-12-04 19:20:11", "2019-12-03"),
    ]
    payload = {
        "pageHelp": {
            "total": len(timing_pairs),
            "pageCount": 1,
            "data": [
                _sse_raw_row(add_date, sse_date, f"late-backfill-{index}")
                for index, (add_date, sse_date) in enumerate(timing_pairs)
            ],
        }
    }

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, spec, page, retries, timeout
        return _sse_fetched(payload, start="2019-01-01", end="2019-12-31")

    monkeypatch.setattr(collector, "fetch_page", fake_fetch)
    output = (tmp_path / "capture").resolve()
    collector.run_capture(
        universe,
        output,
        "2019-01-01",
        "2019-12-31",
        workers=1,
    )
    return output


def _rewrite_source_manifest(output: Path, mutate) -> None:
    path = output / "source_manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_successful_seal_and_full_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _capture(tmp_path, monkeypatch)

    sealed = subject.seal_asset(output)
    revalidated = subject.validate_asset(output)

    assert sealed["status"] == "PASS"
    assert sealed["backtest_authorized"] is False
    assert revalidated["status"] == "PASS"
    manifest = json.loads((output / "asset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "SEALED_STAGING"
    assert manifest["immutable"] is True
    assert manifest["manifest_self_included"] is False
    assert manifest["pit"] == {
        "grade": "B",
        "revision_history_incomplete": True,
        "strict_archival_pit_ready": False,
    }
    assert manifest["content"]["title_metadata_only"] is True
    assert manifest["registered"] is False
    assert manifest["backtest_authorized"] is False
    assert sum(row["role"] == "raw_page" for row in manifest["inventory"]) == 2
    assert not any(row["path"] == "asset_manifest.json" for row in manifest["inventory"])


def test_sse_query_date_keeps_cross_year_adddate_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _sse_cross_year_capture(tmp_path, monkeypatch)

    subject.seal_asset(output)
    result = subject.validate_asset(output)

    assert result["status"] == "PASS"
    audit = json.loads((output / "audit_validation.json").read_text(encoding="utf-8"))
    assert audit["counts"]["raw_record_appearances"] == 2
    assert audit["counts"]["canonical_announcements"] == 2
    announcements = pd.read_parquet(output / "announcements.parquet")
    cross_year = announcements.loc[
        announcements.source_publication_value.eq("2020-12-31 15:52:13")
    ].iloc[0]
    assert cross_year.source_query_date == pd.Timestamp("2021-01-01")
    assert cross_year.available_at == pd.Timestamp("2020-12-31 15:52:13")


def test_sealer_accepts_sse_late_added_and_backfilled_records_as_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _sse_late_backfill_capture(tmp_path, monkeypatch)

    subject.seal_asset(output)
    result = subject.validate_asset(output)

    assert result["status"] == "PASS"
    audit = json.loads((output / "audit_validation.json").read_text(encoding="utf-8"))
    assert audit["counts"]["raw_record_appearances"] == 3
    assert audit["counts"]["canonical_announcements"] == 3
    announcements = pd.read_parquet(output / "announcements.parquet")
    assert announcements.available_at.eq(announcements.published_at).all()
    assert announcements.available_at.dt.normalize().gt(
        announcements.source_query_date
    ).all()


def test_source_query_date_table_drift_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _sse_cross_year_capture(tmp_path, monkeypatch)
    announcements_path = output / "announcements.parquet"
    announcements = pd.read_parquet(announcements_path)
    announcements.loc[0, "source_query_date"] = pd.Timestamp("2020-12-30")
    announcements.to_parquet(announcements_path, index=False, compression="zstd")
    replacement_sha = collector.sha256_file(announcements_path)
    _rewrite_source_manifest(
        output,
        lambda value: value["hashes"].__setitem__(
            "announcements_parquet", replacement_sha
        ),
    )

    with pytest.raises(subject.SealError, match="announcement row mismatch"):
        subject.seal_asset(output)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("SSEDATE", ""),
        ("SSEDATE", "2022-01-01"),
        ("ADDDATE", "2021-01-01"),
    ],
)
def test_sse_missing_or_invalid_query_date_and_imprecise_adddate_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    output = _sse_cross_year_capture(tmp_path, monkeypatch)
    raw_path = output / "raw/sse/600008/2021/page_0001.json"
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["pageHelp"]["data"][0][field] = value
    raw_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    raw_sha = collector.sha256_file(raw_path)
    pages_path = output / "request_pages.parquet"
    pages = pd.read_parquet(pages_path)
    pages.loc[0, "raw_body_sha256"] = raw_sha
    pages.loc[0, "raw_body_bytes"] = raw_path.stat().st_size
    pages.to_parquet(pages_path, index=False, compression="zstd")
    pages_sha = collector.sha256_file(pages_path)

    def update_hashes(value: dict) -> None:
        value["hashes"]["request_pages_parquet"] = pages_sha

    _rewrite_source_manifest(output, update_hashes)
    with pytest.raises(subject.SealError, match="raw record normalization failed"):
        subject.seal_asset(output)


def test_raw_byte_tampering_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = _capture(tmp_path, monkeypatch)
    raw = output / "raw/szse/000001/2021/page_0001.json"
    raw.write_bytes(raw.read_bytes() + b"\n")

    with pytest.raises(subject.SealError, match="raw SHA mismatch"):
        subject.seal_asset(output)


def test_missing_and_extra_raw_pages_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _capture(tmp_path, monkeypatch)
    page_two = output / "raw/szse/000001/2021/page_0002.json"
    page_two.unlink()
    with pytest.raises(subject.SealError, match="missing or unsafe raw page"):
        subject.seal_asset(output)

    output = _capture(tmp_path / "extra", monkeypatch)
    extra = output / "raw/szse/000001/2021/page_9999.json"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(subject.SealError, match="extra raw pages"):
        subject.seal_asset(output)


def test_table_record_drift_is_caught_even_if_source_hash_is_rewritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _capture(tmp_path, monkeypatch)
    table_path = output / "announcements.parquet"
    table = pd.read_parquet(table_path)
    table.loc[0, "title"] = "被篡改的标题"
    table.to_parquet(table_path, index=False, compression="zstd")
    replacement_sha = collector.sha256_file(table_path)
    _rewrite_source_manifest(
        output,
        lambda value: value["hashes"].__setitem__("announcements_parquet", replacement_sha),
    )

    with pytest.raises(subject.SealError, match="announcement row mismatch"):
        subject.seal_asset(output)


def test_snapshot_drift_and_sealed_manifest_drift_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = _capture(tmp_path, monkeypatch)
    _rewrite_source_manifest(
        output, lambda value: value.__setitem__("snapshot_id", "forged-snapshot")
    )
    with pytest.raises(subject.SealError, match="source manifest snapshot_id"):
        subject.seal_asset(output)

    output = _capture(tmp_path / "sealed", monkeypatch)
    subject.seal_asset(output)
    manifest_path = output / "asset_manifest.json"
    manifest_path.chmod(0o644)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["inventory"][0]["sha256"] = "0" * 64
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o444)
    with pytest.raises(
        subject.SealError,
        match=r"asset_manifest\.json content or inventory drifted",
    ):
        subject.validate_asset(output)
