from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    fetch_exchange_issuer_announcements_v1 as subject,
)


def _fetched(
    payload: dict, exchange: str, page: int, *, code: str | None = None
) -> subject.FetchedPage:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_code = code or ("000001" if exchange == "SZSE" else "600000")
    method, url, params, json_body, headers = subject.build_request(
        exchange,
        request_code,
        "2021-01-01",
        "2021-12-31",
        page,
        cache_buster="123",
    )
    return subject.FetchedPage(
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


def _szse_row(index: int) -> dict:
    return {
        "annId": f"SZ-{index:03d}",
        "title": f"<em>公告</em> {index}",
        "publishTime": "2021-06-30",
        "attachPath": f"/disc/test/{index}.PDF",
        "secCode": ["000001", "000002"],
        "secName": ["测试公司", "另一公司"],
    }


def _sse_row(
    *,
    code: str = "600000",
    published_at: str = "2021-07-01 19:30:05",
    sse_date: str = "2021-07-01",
    url_suffix: str = "test",
) -> dict:
    return {
        "SECURITY_CODE": code,
        "SECURITY_NAME": "测试银行",
        "ADDDATE": published_at,
        "SSEDATE": sse_date,
        "TITLE": "年度公告",
        "URL": f"/disclosure/listedinfo/announcement/c/new/{url_suffix}.pdf",
    }


def test_date_only_is_delayed_but_intraday_time_is_exact() -> None:
    published, available, precision = subject.causal_times("2021-12-31")
    assert published == pd.Timestamp("2021-12-31")
    assert available == pd.Timestamp("2022-01-01")
    assert precision == "SOURCE_DATE_ONLY_CONSERVATIVE_NEXT_DAY"

    published, available, precision = subject.causal_times("2021-12-31 19:40:09")
    assert available == published
    assert precision == "SOURCE_SECOND"


def test_requests_is_optional_for_offline_normalization_but_required_for_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = subject.QuerySpec(
        exchange="SSE",
        symbol="600008.SH",
        code="600008",
        start="2021-01-01",
        end="2021-12-31",
        year=2021,
    )
    monkeypatch.setattr(subject, "requests", None)

    normalized = subject.normalize_record(
        spec,
        _sse_row(
            code="600008",
            published_at="2020-12-31 15:52:13",
            sse_date="2021-01-04",
        ),
        page=1,
        raw_body_path="raw/sse/600008/2021/page_0001.json",
        raw_body_sha256="0" * 64,
        retrieved_at="2026-09-05T00:00:00+00:00",
    )
    assert normalized["available_at"] == pd.Timestamp("2020-12-31 15:52:13")
    assert subject.sha256_bytes(b"offline") == (
        "8e2c7ac508139a02af859de64a4743c1f3946837279332c35ec8f5ddf20654ae"
    )
    with pytest.raises(subject.CaptureError, match="requires the optional 'requests'"):
        subject.fetch_page(None, spec, 1, retries=1, timeout=1.0)


def test_official_request_parameters_include_all_sse_page_pointers() -> None:
    method, url, params, body, headers = subject.build_request(
        "SSE", "600000", "2020-01-01", "2020-12-31", 7, cache_buster="9"
    )
    assert method == "GET"
    assert url == subject.SSE_ENDPOINT
    assert body is None
    assert params["productId"] == "600000"
    assert params["pageHelp.pageNo"] == 7
    assert params["pageHelp.beginPage"] == 7
    assert params["pageHelp.endPage"] == 7
    assert "productId=600000" in headers["Referer"]

    method, url, params, body, _ = subject.build_request(
        "SZSE", "000001", "2020-01-01", "2020-12-31", 2, cache_buster="9"
    )
    assert method == "POST"
    assert url == subject.SZSE_ENDPOINT
    assert params == {"random": "9"}
    assert body == {
        "pageSize": 50,
        "pageNum": 2,
        "stock": ["000001"],
        "channelCode": ["listedNotice_disc"],
        "seDate": ["2020-01-01", "2020-12-31"],
    }


def test_szse_parallel_security_arrays_use_the_matching_name() -> None:
    code, name = subject._szse_security(
        {
            "secCode": ["000002", "000001"],
            "secName": ["另一公司", "测试公司"],
        },
        "000001",
    )

    assert code == "000001"
    assert name == "测试公司"


def test_capture_preserves_raw_pages_and_exactly_conserves_totals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = tmp_path / "universe.parquet"
    pd.DataFrame({"symbol": ["000001.SZ", "600000.SH", "000001.SZ"]}).to_parquet(
        universe, index=False
    )

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, retries, timeout
        if spec.exchange == "SZSE":
            records = [_szse_row(i) for i in range(50)] if page == 1 else [_szse_row(50)]
            return _fetched({"announceCount": 51, "data": records}, "SZSE", page)
        return _fetched(
            {"pageHelp": {"total": 1, "pageCount": 1, "data": [_sse_row()]}},
            "SSE",
            page,
        )

    monkeypatch.setattr(subject, "fetch_page", fake_fetch)
    output = tmp_path / "capture"
    result = subject.run_capture(
        universe, output, "2021-01-01", "2021-12-31", workers=2
    )

    announcements = pd.read_parquet(output / "announcements.parquet")
    pages = pd.read_parquet(output / "request_pages.parquet")
    assert len(announcements) == 52
    assert announcements.announcement_key.is_unique
    assert announcements.raw_body_sha256.str.fullmatch(r"[0-9a-f]{64}").all()
    assert announcements.raw_record_sha256.str.fullmatch(r"[0-9a-f]{64}").all()
    assert announcements.loc[announcements.exchange.eq("SZSE"), "security_name"].eq(
        "测试公司"
    ).all()
    assert len(pages) == 3
    assert all((output / path).is_file() for path in pages.raw_body_path)
    assert result["audit"]["reported_records"] == 52
    assert result["audit"]["captured_raw_record_appearances"] == 52
    assert result["audit"]["canonical_announcements"] == 52
    assert result["audit"]["all_query_raw_appearances_conserve"] is True
    assert {"source_query_date_field", "source_query_date"}.issubset(
        announcements.columns
    )
    manifest = json.loads((output / "source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["staging"] is True
    assert manifest["backtest_authorized"] is False
    assert manifest["metadata_only"] is True
    assert manifest["documents_downloaded"] is False
    assert not list(output.rglob("*.pdf"))


@pytest.mark.parametrize(
    ("code", "year", "add_date", "sse_date", "record_count"),
    [
        ("600008", 2021, "2020-12-31 15:52:13", "2021-01-04", 5),
        ("600012", 2020, "2019-12-31 15:52:13", "2020-01-02", 7),
    ],
)
def test_sse_year_edge_adddate_is_available_time_and_ssedate_is_query_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    year: int,
    add_date: str,
    sse_date: str,
    record_count: int,
) -> None:
    universe = tmp_path / "universe.parquet"
    pd.DataFrame({"symbol": [f"{code}.SH"]}).to_parquet(universe, index=False)
    records = [
        _sse_row(
            code=code,
            published_at=add_date,
            sse_date=sse_date,
            url_suffix=f"{code}-{index}",
        )
        for index in range(record_count)
    ]

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, spec, retries, timeout
        return _fetched(
            {
                "pageHelp": {
                    "total": record_count,
                    "pageCount": 1,
                    "data": records,
                }
            },
            "SSE",
            page,
            code=code,
        )

    monkeypatch.setattr(subject, "fetch_page", fake_fetch)
    output = tmp_path / f"capture-{code}"
    result = subject.run_capture(
        universe, output, f"{year}-01-01", f"{year}-12-31", workers=1
    )

    announcements = pd.read_parquet(output / "announcements.parquet")
    assert len(announcements) == record_count
    assert announcements.published_at.eq(pd.Timestamp(add_date)).all()
    assert announcements.available_at.eq(pd.Timestamp(add_date)).all()
    assert announcements.precision.eq("SOURCE_SECOND").all()
    assert announcements.source_query_date_field.eq("SSEDATE").all()
    assert announcements.source_query_date.eq(pd.Timestamp(sse_date)).all()
    assert announcements.available_at.lt(announcements.source_query_date).all()
    assert result["audit"]["reported_records"] == record_count
    assert result["audit"]["captured_raw_record_appearances"] == record_count
    assert result["audit"]["canonical_announcements"] == record_count
    query = result["audit"]["queries"][0]
    assert query["reported_total"] == record_count
    assert query["captured_raw_record_appearances"] == record_count
    assert query["canonical_rows"] == record_count


def test_ssedate_outside_requested_interval_fails_closed() -> None:
    spec = subject.QuerySpec(
        exchange="SSE",
        symbol="600008.SH",
        code="600008",
        start="2021-01-01",
        end="2021-12-31",
        year=2021,
    )

    with pytest.raises(subject.CaptureError, match="source query date outside query interval"):
        subject.normalize_record(
            spec,
            _sse_row(
                code="600008",
                published_at="2020-12-30 23:59:59",
                sse_date="2020-12-31",
                url_suffix="wrong-query-year",
            ),
            page=1,
            raw_body_path="raw/sse/600008/2021/page_0001.json",
            raw_body_sha256="0" * 64,
            retrieved_at="2026-09-05T00:00:00+00:00",
        )


def test_sse_adddate_must_have_second_precision() -> None:
    spec = subject.QuerySpec(
        exchange="SSE",
        symbol="600008.SH",
        code="600008",
        start="2021-01-01",
        end="2021-12-31",
        year=2021,
    )
    with pytest.raises(subject.CaptureError, match="source-second precision"):
        subject.normalize_record(
            spec,
            _sse_row(
                code="600008",
                published_at="2021-01-04",
                sse_date="2021-01-04",
                url_suffix="date-only-adddate",
            ),
            page=1,
            raw_body_path="raw/sse/600008/2021/page_0001.json",
            raw_body_sha256="0" * 64,
            retrieved_at="2026-09-05T00:00:00+00:00",
        )


def test_sse_late_added_and_backfilled_records_remain_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = tmp_path / "universe.parquet"
    pd.DataFrame({"symbol": ["600008.SH"]}).to_parquet(universe, index=False)
    timing_pairs = [
        ("2019-12-06 19:57:18", "2019-12-05"),
        ("2019-12-10 19:38:33", "2019-10-16"),
        ("2019-12-04 19:20:11", "2019-12-03"),
    ]
    records = [
        _sse_row(
            code="600008",
            published_at=add_date,
            sse_date=sse_date,
            url_suffix=f"late-backfill-{index}",
        )
        for index, (add_date, sse_date) in enumerate(timing_pairs)
    ]

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, spec, retries, timeout
        return _fetched(
            {
                "pageHelp": {
                    "total": len(records),
                    "pageCount": 1,
                    "data": records,
                }
            },
            "SSE",
            page,
            code="600008",
        )

    monkeypatch.setattr(subject, "fetch_page", fake_fetch)
    output = tmp_path / "late-backfill-capture"
    result = subject.run_capture(
        universe, output, "2019-01-01", "2019-12-31", workers=1
    )

    announcements = pd.read_parquet(output / "announcements.parquet").sort_values(
        "source_publication_value"
    )
    assert len(announcements) == 3
    assert announcements.available_at.eq(announcements.published_at).all()
    assert announcements.available_at.dt.normalize().gt(
        announcements.source_query_date
    ).all()
    assert result["audit"]["reported_records"] == 3
    assert result["audit"]["canonical_announcements"] == 3
    assert result["audit"]["sse_available_after_query_date_rows"] == 3


def test_duplicate_source_key_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    universe = tmp_path / "universe.parquet"
    pd.DataFrame({"symbol": ["000001.SZ"]}).to_parquet(universe, index=False)
    duplicate = _szse_row(1)

    def fake_fetch(session, spec, page, *, retries, timeout):
        del session, spec, page, retries, timeout
        return _fetched(
            {"announceCount": 2, "data": [duplicate, duplicate]}, "SZSE", 1
        )

    monkeypatch.setattr(subject, "fetch_page", fake_fetch)
    output = tmp_path / "duplicate_capture"
    with pytest.raises(subject.CaptureError, match="duplicate source record"):
        subject.run_capture(
            universe,
            output,
            "2021-01-01",
            "2021-12-31",
            workers=1,
        )
    assert not output.exists()


def test_non_empty_output_root_is_never_overwritten(tmp_path: Path) -> None:
    universe = tmp_path / "universe.parquet"
    pd.DataFrame({"symbol": ["000001.SZ"]}).to_parquet(universe, index=False)
    output = tmp_path / "capture"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(subject.CaptureError, match="refusing to overwrite"):
        subject.run_capture(universe, output, "2021-01-01", "2021-12-31")
    assert marker.read_text(encoding="utf-8") == "keep"
