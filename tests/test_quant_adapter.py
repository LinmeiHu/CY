from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from cyq_game.data import (  # noqa: E402
    DataActivationError,
    DataAsset,
    DataExecutionAuthorization,
    DataOperation,
    DataPurpose,
    InputBinding,
    QuantAssetKind,
    QuantReadScope,
    ValidityReason,
    adapt_historical_trading_rules,
    inspect_quant_parquet,
    iter_quant_records,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _authorization(
    operation: DataOperation = DataOperation.INGEST,
) -> DataExecutionAuthorization:
    return DataExecutionAuthorization(
        operation=operation,
        registry_id="TEST-REGISTRY",
        registry_sha256="a" * 64,
        input_manifest_id="TEST-MANIFEST",
        input_manifest_sha256="b" * 64,
        purpose=DataPurpose.DATA_PREPARATION,
        hard_valid=False,
        software_test=False,
        scope_start=date(2024, 1, 1),
        scope_end=date(2024, 12, 31),
    )


def _binding(
    path: Path,
    kind: QuantAssetKind,
    *,
    lineage: dict[str, object] | None = None,
) -> InputBinding:
    asset_kind = {
        QuantAssetKind.DAILY_BARS: "market_bars_daily",
        QuantAssetKind.TRADING_STATE: "trading_state_daily",
        QuantAssetKind.INDEX_DAILY: "index_bars_daily",
        QuantAssetKind.MINUTE_BARS: "market_bars_1min",
        QuantAssetKind.INDUSTRY_DAILY: "industry_membership_pit",
        QuantAssetKind.SHARE_FLOAT_PIT: "free_float_shares_pit",
    }[kind]
    asset = DataAsset(
        asset_id=f"TEST-{kind.value}",
        name="quant adapter fixture",
        kind=asset_kind,
        status="QA_ONLY",
        pit_grade="B",
        physical_state="MATERIALIZED",
        location=path,
        source="test",
        lineage=lineage
        or {"record_available_at": False, "record_snapshot_id": False},
    )
    return InputBinding(
        role=kind.value.lower(),
        asset=asset,
        path=path,
        source="frozen-test-source",
        snapshot_id="input-snapshot",
        available_at_policy="modeled at bar close for data preparation only",
        sha256=_sha256(path),
        inventory_manifest=None,
        inventory_sha256=None,
    )


def _write_daily(path: Path, *, include_lineage: bool = True) -> None:
    values: dict[str, object] = {
        "trade_date": [datetime(2024, 1, 2, 16, 30)],
        "symbol": ["000001.SZ"],
        "adjust": ["none"],
        "open": [10.0],
        "high": [10.5],
        "low": [9.8],
        "close": [10.2],
        "preclose": [10.0],
        "volume": [1000.0],
        "amount": [10_200.0],
    }
    if include_lineage:
        values["available_at"] = [datetime(2024, 1, 2, 17)]
        values["snapshot_id"] = ["row-v1"]
    pq.write_table(pa.table(values), path)


def _write_minute(path: Path) -> None:
    pq.write_table(
        pa.table(
            {
                "qmt_code": ["000001.SZ"],
                "symbol": ["000001"],
                "exchange": ["SZ"],
                "period": ["1m"],
                "adjust": ["none"],
                "trade_date": pa.array([date(2024, 1, 2)], type=pa.date32()),
                "bar_end_time": [datetime(2024, 1, 2, 9, 31)],
                "open": [10.0],
                "high": [10.1],
                "low": [9.9],
                "close": [10.05],
                "volume": [100.0],
                "amount": [1005.0],
                "source": ["qmt"],
            }
        ),
        path,
    )


def _write_index(path: Path) -> None:
    pq.write_table(
        pa.table(
            {
                "trade_date": [datetime(2024, 1, 2)],
                "index_symbol": ["csi000300"],
                "index_name": ["沪深300"],
                "open": [3300.0],
                "high": [3330.0],
                "low": [3290.0],
                "close": [3320.0],
                "volume": [1000.0],
                "amount": [10_000.0],
            }
        ),
        path,
    )


def _write_industry(
    path: Path,
    *,
    industry: str = "银行Ⅱ",
    notice_date: date | None = date(2023, 10, 24),
    report_date: date | None = date(2023, 9, 30),
) -> None:
    pq.write_table(
        pa.table(
            {
                "trade_date": pa.array([date(2024, 1, 2)], type=pa.date32()),
                "symbol": ["000001"],
                "industry": [industry],
                "source_notice_date": pa.array([notice_date], type=pa.date32()),
                "source_report_date": pa.array([report_date], type=pa.date32()),
                "source": ["eastmoney_yjbb_notice_lag1" if industry != "UNKNOWN" else "unknown"],
            }
        ),
        path,
    )


def _write_float(path: Path) -> None:
    pq.write_table(
        pa.table(
            {
                "qmt_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
                "symbol": ["000001", "000001", "000001"],
                "exchange": ["SZ", "SZ", "SZ"],
                "m_timetag": [20230930, 20231231, 20240331],
                "m_anntime": [20231024, 20240315, 20240501],
                "circulating_capital": [19_405_918_198.0, 19_405_918_198.0, 0.0],
                "source": ["qmt_xtdata_capital"] * 3,
            }
        ),
        path,
    )


def _write_trading_state(
    path: Path,
    *,
    limit_pct: float = 0.1,
    duplicate: bool = False,
) -> None:
    rows = 2 if duplicate else 1
    pq.write_table(
        pa.table(
            {
                "trade_date": [datetime(2024, 1, 2)] * rows,
                "symbol": ["000001.SZ"] * rows,
                "trade_status": [1] * rows,
                "is_st": [False] * rows,
                "limit_pct": [limit_pct] * rows,
                "up_limit_price": [11.0] * rows,
                "down_limit_price": [9.0] * rows,
                "buy_blocked_open": [False] * rows,
                "sell_blocked_open": [False] * rows,
                "state_source": ["baostock_none_daily"] * rows,
            }
        ),
        path,
    )


def test_historical_trading_rules_adapter_is_causal_and_deduplicated(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "state.parquet"
    _write_trading_state(data_path)
    binding = _binding(
        data_path,
        QuantAssetKind.TRADING_STATE,
        lineage={
            "available_at_from_completed_state_day": True,
            "snapshot_id_from_frozen_input": True,
        },
    )

    records = adapt_historical_trading_rules(
        binding=binding,
        authorization=_authorization(),
        path=data_path,
        scope=QuantReadScope(
            start=date(2024, 1, 2),
            end=date(2024, 1, 2),
            symbols=("000001.SZ",),
        ),
    )

    assert len(records) == 1
    assert records[0].hard_valid is True
    assert records[0].available_at.astimezone().date() == date(2024, 1, 2)


def test_historical_trading_rules_reject_duplicates_and_bad_units(
    tmp_path: Path,
) -> None:
    duplicate_path = tmp_path / "duplicate.parquet"
    _write_trading_state(duplicate_path, duplicate=True)
    scope = QuantReadScope(
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        symbols=("000001.SZ",),
    )
    with pytest.raises(DataActivationError, match="duplicate historical trading state"):
        adapt_historical_trading_rules(
            binding=_binding(duplicate_path, QuantAssetKind.TRADING_STATE),
            authorization=_authorization(),
            path=duplicate_path,
            scope=scope,
        )

    bad_unit_path = tmp_path / "bad-unit.parquet"
    _write_trading_state(bad_unit_path, limit_pct=10.0)
    with pytest.raises(DataActivationError, match="decimal unit"):
        adapt_historical_trading_rules(
            binding=_binding(bad_unit_path, QuantAssetKind.TRADING_STATE),
            authorization=_authorization(),
            path=bad_unit_path,
            scope=scope,
        )


def test_daily_adapter_is_bounded_and_registry_lineage_remains_fail_closed(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "daily.parquet"
    _write_daily(data_path)
    binding = _binding(data_path, QuantAssetKind.DAILY_BARS)
    scope = QuantReadScope(
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        symbols=("000001.SZ",),
    )

    descriptor = inspect_quant_parquet(
        binding=binding,
        authorization=_authorization(DataOperation.INSPECT),
        kind=QuantAssetKind.DAILY_BARS,
        path=data_path,
    )
    records = list(
        iter_quant_records(
            binding=binding,
            authorization=_authorization(),
            kind=QuantAssetKind.DAILY_BARS,
            path=data_path,
            scope=scope,
        )
    )

    assert descriptor.rows == 1
    assert descriptor.min_trade_date == date(2024, 1, 2)
    assert descriptor.max_trade_date == date(2024, 1, 2)
    assert len(records) == 1
    assert records[0].symbol == "000001.SZ"
    assert records[0].snapshot_id == "row-v1"
    assert set(records[0].validity.reasons) == {
        ValidityReason.MODELED_AVAILABLE_AT,
        ValidityReason.MISSING_RECORD_VERSION_LINEAGE,
    }
    assert records[0].hard_valid is False


def test_promised_record_lineage_must_physically_exist(tmp_path: Path) -> None:
    data_path = tmp_path / "daily.parquet"
    _write_daily(data_path, include_lineage=False)
    binding = _binding(
        data_path,
        QuantAssetKind.DAILY_BARS,
        lineage={"record_available_at": True, "record_snapshot_id": True},
    )

    with pytest.raises(DataActivationError, match="promises record available_at"):
        list(
            iter_quant_records(
                binding=binding,
                authorization=_authorization(),
                kind=QuantAssetKind.DAILY_BARS,
                path=data_path,
                scope=QuantReadScope(
                    start=date(2024, 1, 2),
                    end=date(2024, 1, 2),
                    symbols=("000001.SZ",),
                ),
            )
        )


def test_minute_adapter_preserves_pre_2020_capability_but_limits_each_read(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "minute.parquet"
    _write_minute(data_path)
    binding = _binding(data_path, QuantAssetKind.MINUTE_BARS)

    records = list(
        iter_quant_records(
            binding=binding,
            authorization=_authorization(),
            kind=QuantAssetKind.MINUTE_BARS,
            path=data_path,
            scope=QuantReadScope(
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                symbols=("SZ000001",),
            ),
        )
    )

    assert len(records) == 1
    assert records[0].symbol == "000001.SZ"
    assert records[0].source == "frozen-test-source | qmt"
    with pytest.raises(DataActivationError, match="31 calendar days"):
        list(
            iter_quant_records(
                binding=binding,
                authorization=_authorization(),
                kind=QuantAssetKind.MINUTE_BARS,
                path=data_path,
                scope=QuantReadScope(
                    start=date(2024, 1, 1),
                    end=date(2024, 2, 1),
                    symbols=("000001.SZ",),
                ),
            )
        )


def test_index_adapter_accepts_registered_kind_and_index_identifier(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "index.parquet"
    _write_index(data_path)
    records = list(
        iter_quant_records(
            binding=_binding(data_path, QuantAssetKind.INDEX_DAILY),
            authorization=_authorization(),
            kind=QuantAssetKind.INDEX_DAILY,
            path=data_path,
            scope=QuantReadScope(
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                symbols=("CSI000300",),
            ),
        )
    )

    assert len(records) == 1
    assert records[0].symbol == "csi000300"


def test_industry_adapter_uses_causal_notice_date_and_frozen_snapshot(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "industry.parquet"
    _write_industry(data_path)
    binding = _binding(
        data_path,
        QuantAssetKind.INDUSTRY_DAILY,
        lineage={
            "record_available_at": False,
            "record_snapshot_id": False,
            "available_at_from_source_notice_date": True,
            "snapshot_id_from_frozen_input": True,
        },
    )

    records = list(
        iter_quant_records(
            binding=binding,
            authorization=_authorization(),
            kind=QuantAssetKind.INDUSTRY_DAILY,
            path=data_path,
            scope=QuantReadScope(
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                symbols=("000001.SZ",),
            ),
        )
    )

    assert len(records) == 1
    assert records[0].hard_valid is True
    assert records[0].snapshot_id == "input-snapshot"
    assert records[0].available_at.astimezone().date() == date(2023, 10, 24)
    assert records[0].source.endswith("eastmoney_yjbb_notice_lag1")


def test_unknown_industry_fails_closed(tmp_path: Path) -> None:
    data_path = tmp_path / "industry.parquet"
    _write_industry(
        data_path,
        industry="UNKNOWN",
        notice_date=None,
        report_date=None,
    )
    binding = _binding(
        data_path,
        QuantAssetKind.INDUSTRY_DAILY,
        lineage={
            "record_available_at": False,
            "record_snapshot_id": False,
            "available_at_from_source_notice_date": True,
            "snapshot_id_from_frozen_input": True,
        },
    )

    record = next(
        iter_quant_records(
            binding=binding,
            authorization=_authorization(),
            kind=QuantAssetKind.INDUSTRY_DAILY,
            path=data_path,
            scope=QuantReadScope(
                start=date(2024, 1, 2),
                end=date(2024, 1, 2),
                symbols=("000001.SZ",),
            ),
        )
    )

    assert record.hard_valid is False
    assert ValidityReason.MISSING_SECTOR_MEMBERSHIP in record.validity.reasons


def test_industry_adapter_rejects_noncausal_notice_date(tmp_path: Path) -> None:
    data_path = tmp_path / "industry.parquet"
    _write_industry(data_path, notice_date=date(2024, 1, 2))

    with pytest.raises(DataActivationError, match="notice_date < trade_date"):
        list(
            iter_quant_records(
                binding=_binding(
                    data_path,
                    QuantAssetKind.INDUSTRY_DAILY,
                    lineage={
                        "available_at_from_source_notice_date": True,
                        "snapshot_id_from_frozen_input": True,
                    },
                ),
                authorization=_authorization(),
                kind=QuantAssetKind.INDUSTRY_DAILY,
                path=data_path,
                scope=QuantReadScope(
                    start=date(2024, 1, 2),
                    end=date(2024, 1, 2),
                    symbols=("000001.SZ",),
                ),
            )
        )


def test_float_adapter_requires_effective_and_announced_dates(tmp_path: Path) -> None:
    data_path = tmp_path / "float.parquet"
    _write_float(data_path)
    binding = _binding(
        data_path,
        QuantAssetKind.SHARE_FLOAT_PIT,
        lineage={
            "record_available_at": False,
            "record_snapshot_id": False,
            "available_at_from_effective_and_announcement": True,
            "snapshot_id_from_frozen_input": True,
        },
    )

    records = list(
        iter_quant_records(
            binding=binding,
            authorization=_authorization(),
            kind=QuantAssetKind.SHARE_FLOAT_PIT,
            path=data_path,
            scope=QuantReadScope(
                start=date(2024, 1, 1),
                end=date(2024, 3, 31),
                symbols=("000001.SZ",),
            ),
        )
    )

    assert len(records) == 2
    assert records[-1].values["effective_date"] == date(2023, 12, 31)
    assert records[-1].available_at.astimezone().date() == date(2024, 3, 15)
    assert all(record.hard_valid for record in records)


def test_float_nonpositive_value_fails_closed_and_latest_revision_wins(
    tmp_path: Path,
) -> None:
    from cyq_game.data import select_float_as_of

    data_path = tmp_path / "float.parquet"
    _write_float(data_path)
    binding = _binding(
        data_path,
        QuantAssetKind.SHARE_FLOAT_PIT,
        lineage={
            "available_at_from_effective_and_announcement": True,
            "snapshot_id_from_frozen_input": True,
        },
    )
    records = list(
        iter_quant_records(
            binding=binding,
            authorization=_authorization(),
            kind=QuantAssetKind.SHARE_FLOAT_PIT,
            path=data_path,
            scope=QuantReadScope(
                start=date(2024, 1, 1),
                end=date(2024, 5, 1),
                symbols=("000001.SZ",),
            ),
        )
    )

    selected = select_float_as_of(
        records,
        symbol="000001.SZ",
        decision_at=datetime(2024, 5, 1, 23, 59, 59).astimezone(),
    )
    assert selected is not None
    assert selected.values["effective_date"] == date(2024, 3, 31)
    assert selected.hard_valid is False
    assert ValidityReason.MISSING_FLOAT_SHARES in selected.validity.reasons


def test_selected_parquet_is_rehashed_before_every_read(tmp_path: Path) -> None:
    data_path = tmp_path / "daily.parquet"
    _write_daily(data_path)
    binding = _binding(data_path, QuantAssetKind.DAILY_BARS)
    _write_daily(data_path, include_lineage=False)

    with pytest.raises(DataActivationError, match="selected file hash mismatch"):
        inspect_quant_parquet(
            binding=binding,
            authorization=_authorization(DataOperation.INSPECT),
            kind=QuantAssetKind.DAILY_BARS,
            path=data_path,
        )
