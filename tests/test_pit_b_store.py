from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
    PITBDailyStore,
)
from cyq_game.data import pit_b_store as pit_b_store_module  # noqa: E402

_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_inventory(root: Path, path: Path, inventory_path: Path) -> None:
    inventory_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "root": str(root),
                "files": [
                    {
                        "path": str(path.relative_to(root)),
                        "size": path.stat().st_size,
                        "sha256": _sha256(path),
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _minute_binding(
    tmp_path: Path, *, execution_hard_valid: list[bool] | None = None
) -> InputBinding:
    root = tmp_path / "minute-pit-b"
    daily_path = root / "daily" / "partition_year=2024" / "data_0.parquet"
    execution_path = root / "execution_5m" / "partition_year=2024" / "data_0.parquet"
    daily_path.parent.mkdir(parents=True)
    execution_path.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001.SZ"],
                "trade_date": pa.array([date(2024, 1, 2)], type=pa.date32()),
                "chip_prices": [[9.9, 10.1, 10.3]],
                "chip_volumes": [[200.0, 500.0, 300.0]],
                "available_at": [datetime(2024, 1, 2, 15, 30)],
                "source": ["QMT_1MIN+PIT_B_DAILY"],
                "snapshot_id": ["minute-pit-b:000001:20240102"],
                "hard_valid": [True],
                "opening_30m_return": [0.012],
                "closing_30m_return": [0.008],
                "close_vs_vwap": [0.006],
                "last_hour_volume_share": [0.32],
                "realized_volatility": [0.018],
            }
        ),
        daily_path,
    )
    available = [datetime(2024, 1, 2, 9, 35) + timedelta(minutes=index * 5) for index in range(6)]
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001.SZ"] * 6,
                "trade_date": pa.array([date(2024, 1, 2)] * 6, type=pa.date32()),
                "window_index": list(range(6)),
                "available_at": available,
                "open": [10.0 + index * 0.01 for index in range(6)],
                "high": [10.1 + index * 0.01 for index in range(6)],
                "low": [9.9 + index * 0.01 for index in range(6)],
                "close": [10.02 + index * 0.01 for index in range(6)],
                "volume": [100.0] * 6,
                "amount": [1_002.0 + index for index in range(6)],
                "circulating_shares": [1_000_000.0] * 6,
                "trade_status": [1] * 6,
                "is_st": [False] * 6,
                "up_limit_price": [11.0] * 6,
                "down_limit_price": [9.0] * 6,
                "market_rule_id": ["MAIN_10"] * 6,
                "market_rule_valid": [True] * 6,
                "limit_pct": [0.1] * 6,
                "hard_valid": execution_hard_valid or [True] * 6,
            }
        ),
        execution_path,
    )
    inventory_path = tmp_path / "minute-inventory.json"
    payload = {
        "schema_version": 1,
        "root": str(root),
        "files": [
            {
                "path": str(path.relative_to(root)),
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in (daily_path, execution_path)
        ],
    }
    inventory_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    asset = DataAsset(
        asset_id="TEST-MINUTE-PIT-B",
        name="Minute PIT-B runtime fixture",
        kind="minute_pit_b",
        status="RESEARCH_READY",
        pit_grade="B",
        physical_state="MATERIALIZED",
        location=root,
        source="test",
        lineage={},
    )
    return InputBinding(
        role="minute_pit_b",
        asset=asset,
        path=root,
        source="test",
        snapshot_id="TEST-MINUTE-PIT-B-SNAPSHOT",
        available_at_policy="explicit record timestamp",
        sha256=None,
        inventory_manifest=inventory_path,
        inventory_sha256=_sha256(inventory_path),
    )


def _chip_feature_binding(tmp_path: Path) -> InputBinding:
    root = tmp_path / "chip-features"
    path = root / "year=2024" / "data.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001.SZ"],
                "trade_date": pa.array([date(2024, 1, 2)], type=pa.date32()),
                "available_at": [datetime(2024, 1, 2, 15, 30)],
                "daily_snapshot_id": ["pit-b:000001:20240102"],
                "minute_snapshot_id": ["minute-pit-b:000001:20240102"],
                "strict_sample": [True],
                "invalid_reason": [None],
                "profit_ratio": [0.61],
                "trapped_ratio": [0.39],
                "average_cost": [10.0],
                "p01": [9.0],
                "p10": [9.4],
                "p50": [10.0],
                "p90": [10.7],
                "p99": [11.0],
                "asr": [0.72],
                "space20": [0.18],
                "ckdp": [58.0],
                "ckdw": [50.0],
                "cbw": [22.2],
                "cyqk_open_pre": [55.0],
                "cyqk_high_pre": [65.0],
                "cyqk_low_pre": [48.0],
                "cyqk_close_pre": [61.0],
                "cyc5": [10.1],
                "cyc13": [9.9],
                "cyc34": [9.7],
                "cys13": [3.0],
                "cys34": [5.0],
                "rpy2": [70.0],
                "concentration_20": [0.45],
                "base_retention": [0.83],
                "peak_count": [1],
                "peaks_json": [
                    '[{"center_price":10.0,"mass":0.45,"width_pct":0.08,'
                    '"prominence":0.12,"age_mean":8.0,"formation_date":"2023-12-20"}]'
                ],
                "priors_json": ['["BOOK_PRIOR:TEST"]'],
                "state_quality": [0.98],
                "opening_30m_return": [0.012],
                "closing_30m_return": [0.008],
                "close_vs_vwap": [0.006],
                "last_hour_volume_share": [0.32],
                "realized_volatility": [0.018],
            }
        ),
        path,
    )
    inventory_path = tmp_path / "chip-feature-inventory.json"
    _write_inventory(root, path, inventory_path)
    asset = DataAsset(
        asset_id="TEST-CHIP-FEATURES",
        name="Prepared chip feature fixture",
        kind="chip_state_features",
        status="DERIVE_ONLY",
        pit_grade="B",
        physical_state="MATERIALIZED",
        location=root,
        source="test",
        lineage={},
    )
    return InputBinding(
        role="chip_state_features",
        asset=asset,
        path=root,
        source="test",
        snapshot_id="TEST-CHIP-FEATURES-SNAPSHOT",
        available_at_policy="explicit record timestamp",
        sha256=None,
        inventory_manifest=inventory_path,
        inventory_sha256=_sha256(inventory_path),
    )


def _store(
    tmp_path: Path,
    *,
    include_minute: bool = False,
    include_chip_features: bool = False,
    execution_hard_valid: list[bool] | None = None,
) -> PITBDailyStore:
    data_root = tmp_path / "pit-b"
    data_root.mkdir()
    parquet_path = data_root / "year=2024.parquet"
    pq.write_table(
        pa.table(
            {
                "symbol": ["000001.SZ", "000002.SZ"],
                "trade_date": pa.array([date(2024, 1, 2)] * 2, type=pa.date32()),
                "open": [10.0, 20.0],
                "high": [10.5, 20.5],
                "low": [9.8, 19.8],
                "close": [10.2, 20.2],
                "volume": [1_000.0, 2_000.0],
                "amount": [10_200.0, 40_400.0],
                "circulating_shares": [1_000_000.0, 2_000_000.0],
                "available_at": [datetime(2024, 1, 2, 15, 30)] * 2,
                "trade_status": [1, 1],
                "is_st": [False, False],
                "up_limit_price": [11.0, 22.0],
                "down_limit_price": [9.0, 18.0],
                "hard_valid": [True, False],
                "invalid_reasons": ["[]", '["INDUSTRY_UNKNOWN"]'],
                "snapshot_id": ["pit-b:000001:20240102", "pit-b:000002:20240102"],
                "market_rule_id": ["MAIN_10", "MAIN_10"],
                "market_rule_valid": [True, True],
                "limit_pct": [0.1, 0.1],
                "industry": ["银行", None],
                "industry_source": ["QMT_CURRENT_WITH_EFFECTIVE_DATE", None],
                "source_notice_date": pa.array([date(2024, 1, 1), None], type=pa.date32()),
                "corporate_action_ids": ['["CA-1"]', "[]"],
                "corporate_action_source": ["CNINFO", None],
                "corporate_action_available_date": pa.array(
                    [date(2024, 1, 1), None], type=pa.date32()
                ),
                "corporate_action_blocking": [False, False],
                "corporate_action_problems": ["[]", "[]"],
                "share_multiplier": [1.0, 1.0],
                "cash_per_share": [0.1, 0.0],
                "rights_ratio": [0.0, 0.0],
                "rights_price": [None, None],
                "bar_valid": [True, True],
                "trading_state_valid": [True, True],
                "float_valid": [True, True],
                "corporate_action_count": [1, 0],
            }
        ),
        parquet_path,
    )
    inventory_path = tmp_path / "inventory.json"
    _write_inventory(data_root, parquet_path, inventory_path)
    asset = DataAsset(
        asset_id="TEST-PIT-B",
        name="PIT-B runtime fixture",
        kind="daily_pit_b",
        status="RESEARCH_READY",
        pit_grade="B",
        physical_state="MATERIALIZED",
        location=data_root,
        source="test",
        lineage={},
    )
    binding = InputBinding(
        role="daily_pit_b",
        asset=asset,
        path=data_root,
        source="test",
        snapshot_id="TEST-PIT-B-SNAPSHOT",
        available_at_policy="explicit record timestamp",
        sha256=None,
        inventory_manifest=inventory_path,
        inventory_sha256=_sha256(inventory_path),
    )
    authorization = DataExecutionAuthorization(
        operation=DataOperation.BACKTEST,
        registry_id="TEST-REGISTRY",
        registry_sha256="a" * 64,
        input_manifest_id="TEST-MANIFEST",
        input_manifest_sha256="b" * 64,
        purpose=DataPurpose.CAUSAL_RESEARCH,
        hard_valid=True,
        software_test=False,
        scope_start=date(2024, 1, 1),
        scope_end=date(2024, 1, 31),
    )
    return PITBDailyStore(
        tmp_path / "metadata.sqlite3",
        binding=binding,
        minute_binding=(
            _minute_binding(tmp_path, execution_hard_valid=execution_hard_valid)
            if include_minute
            else None
        ),
        chip_feature_binding=(_chip_feature_binding(tmp_path) if include_chip_features else None),
        authorization=authorization,
    )


def test_inventory_verification_cache_skips_unchanged_file_and_detects_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.initialize()
    store.close()
    cache_dir = store.path.parent / ".inventory_verification"
    parquet_path = next(store.binding.path.glob("*.parquet"))

    pit_b_store_module._VERIFIED_INVENTORIES.clear()
    original_sha256 = pit_b_store_module._sha256_file
    hashed: list[Path] = []

    def recording_sha256(path: Path) -> str:
        hashed.append(path)
        return original_sha256(path)

    monkeypatch.setattr(pit_b_store_module, "_sha256_file", recording_sha256)
    pit_b_store_module._verify_inventory_once(store.binding, cache_dir=cache_dir)
    assert hashed == [store.binding.inventory_manifest]

    before = parquet_path.stat()
    with parquet_path.open("r+b") as handle:
        handle.seek(-1, os.SEEK_END)
        last_byte = handle.read(1)
        handle.seek(-1, os.SEEK_END)
        handle.write(bytes([last_byte[0] ^ 1]))
    os.utime(parquet_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    pit_b_store_module._VERIFIED_INVENTORIES.clear()
    with pytest.raises(DataActivationError, match="file hash mismatch"):
        pit_b_store_module._verify_inventory_once(store.binding, cache_dir=cache_dir)


def test_pit_b_store_separates_strict_signals_from_execution_bars(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.initialize()
    decision_at = datetime(2024, 1, 2, 16, tzinfo=_SHANGHAI)
    try:
        assert store.symbols() == ["000001.SZ", "000002.SZ"]
        assert store.date_bounds() == (date(2024, 1, 2), date(2024, 1, 2))
        assert store.strict_bars_for_day(
            ["000001.SZ", "000002.SZ"], date(2024, 1, 2), decision_at
        ).keys() == {"000001.SZ"}
        assert store.execution_bars_for_day(
            ["000001.SZ", "000002.SZ"], date(2024, 1, 2), decision_at
        ).keys() == {"000001.SZ", "000002.SZ"}

        provenance = store.bar_provenance("000002.SZ", date(2024, 1, 2), decision_at)
        assert provenance["bar_snapshot_id"] == "pit-b:000002:20240102"
        assert provenance["hard_valid"] is False
        assert provenance["invalid_reasons"] == ["INDUSTRY_UNKNOWN"]

        membership = store.industry_memberships_as_of(
            ["000001.SZ", "000002.SZ"], date(2024, 1, 2), decision_at
        )
        assert membership["000001.SZ"].industry == "银行"
        assert "000002.SZ" not in membership
        assert store.rule_as_of("000001.SZ", "MAIN", date(2024, 1, 2), decision_at).known
        actions = store.corporate_actions_as_of(
            "000001.SZ", date(2024, 1, 2), date(2024, 1, 2), decision_at
        )
        assert [(item.action_type, item.cash_per_share) for item in actions] == [
            ("CASH_DIVIDEND", 0.1)
        ]

        forecasts = store.calibrate_forecasts(
            ["000001.SZ", "000002.SZ"], {date(2024, 1, 2)}, decision_at
        )
        assert forecasts.keys() == {"000001.SZ", "000002.SZ"}
        assert forecasts["000001.SZ"].sample_size == 0
        assert forecasts["000002.SZ"].sample_size == 0

        before_available = datetime(2024, 1, 2, 15, tzinfo=_SHANGHAI)
        assert not store.strict_bars_for_day(["000001.SZ"], date(2024, 1, 2), before_available)
    finally:
        store.close()


def test_pit_b_store_exposes_minute_chip_and_causal_execution_windows(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, include_minute=True)
    store.initialize()
    trade_date = date(2024, 1, 2)
    try:
        before_chip = datetime(2024, 1, 2, 15, 29, tzinfo=_SHANGHAI)
        assert store.chip_observations_for_day(["000001.SZ"], trade_date, before_chip) == {}

        after_chip = datetime(2024, 1, 2, 15, 30, tzinfo=_SHANGHAI)
        observation = store.chip_observations_for_day(["000001.SZ"], trade_date, after_chip)[
            "000001.SZ"
        ]
        assert observation.prices == (9.9, 10.1, 10.3)
        assert sum(observation.volumes) == pytest.approx(1_000.0)
        assert observation.available_at == after_chip
        assert observation.intraday_factors_complete
        assert observation.opening_30m_return == pytest.approx(0.012)
        assert observation.closing_30m_return == pytest.approx(0.008)
        assert observation.close_vs_vwap == pytest.approx(0.006)
        assert observation.last_hour_volume_share == pytest.approx(0.32)
        assert observation.realized_volatility == pytest.approx(0.018)
        assert store.requires_intraday_evidence
        assert not store.supports_fundamental_signals

        before_first = datetime(2024, 1, 2, 9, 34, tzinfo=_SHANGHAI)
        assert store.execution_windows_for_day(["000001.SZ"], trade_date, before_first) == {}
        before_batch = store.execution_batch_for_day(
            {"000001.SZ": "MAIN"}, trade_date, before_first
        )
        assert before_batch.windows == {}
        assert before_batch.observed_symbols == frozenset()
        assert before_batch.valid_symbols == frozenset()
        first_cutoff = datetime(2024, 1, 2, 9, 35, tzinfo=_SHANGHAI)
        first = store.execution_windows_for_day(["000001.SZ"], trade_date, first_cutoff)[
            "000001.SZ"
        ]
        assert len(first) == 1
        assert first[0].available_at == first_cutoff
        assert store.rule_as_of("000001.SZ", "MAIN", trade_date, first_cutoff).known

        final_cutoff = datetime(2024, 1, 2, 10, 0, tzinfo=_SHANGHAI)
        windows = store.execution_windows_for_day(["000001.SZ"], trade_date, final_cutoff)[
            "000001.SZ"
        ]
        assert len(windows) == 6
        assert [bar.available_at for bar in windows] == [
            datetime(2024, 1, 2, 9, 35, tzinfo=_SHANGHAI) + timedelta(minutes=index * 5)
            for index in range(6)
        ]
        batch = store.execution_batch_for_day(
            {"000001.SZ": "MAIN"}, trade_date, final_cutoff
        )
        assert len(batch.windows["000001.SZ"]) == 6
        assert batch.observed_symbols == frozenset({"000001.SZ"})
        assert batch.valid_symbols == frozenset({"000001.SZ"})
        assert batch.rules["000001.SZ"].known
        assert batch.invalid_at == {}

        morning = datetime(2024, 1, 2, 9, 31, tzinfo=_SHANGHAI)
        actions = store.corporate_actions_as_of("000001.SZ", trade_date, trade_date, morning)
        assert [(item.action_type, item.cash_per_share) for item in actions] == [
            ("CASH_DIVIDEND", 0.1)
        ]
    finally:
        store.close()


def test_execution_batch_reads_windows_validity_and_rules_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, include_minute=True)
    store.initialize()
    calls = 0
    original_query = store._query

    def counted_query(sql: str, parameters: list[object]) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return original_query(sql, parameters)

    monkeypatch.setattr(store, "_query", counted_query)
    try:
        batch = store.execution_batch_for_day(
            {"000001.SZ": "MAIN"},
            date(2024, 1, 2),
            datetime(2024, 1, 2, 10, 0, tzinfo=_SHANGHAI),
        )

        assert len(batch.windows["000001.SZ"]) == 6
        assert batch.rules["000001.SZ"].known
        assert batch.valid_symbols == frozenset({"000001.SZ"})
        assert calls == 1
    finally:
        store.close()


def test_execution_batch_preserves_first_invalid_window_time(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        include_minute=True,
        execution_hard_valid=[True, False, True, True, True, True],
    )
    store.initialize()
    try:
        batch = store.execution_batch_for_day(
            {"000001.SZ": "MAIN"},
            date(2024, 1, 2),
            datetime(2024, 1, 2, 10, 0, tzinfo=_SHANGHAI),
        )

        assert len(batch.windows["000001.SZ"]) == 5
        assert batch.windows["000001.SZ"][0].available_at == datetime(
            2024, 1, 2, 9, 35, tzinfo=_SHANGHAI
        )
        assert batch.invalid_at["000001.SZ"] == datetime(
            2024, 1, 2, 9, 40, tzinfo=_SHANGHAI
        )
    finally:
        store.close()


def test_pit_b_store_reads_prepared_chip_features_causally(tmp_path: Path) -> None:
    store = _store(tmp_path, include_chip_features=True)
    store.initialize()
    trade_date = date(2024, 1, 2)
    try:
        before = datetime(2024, 1, 2, 15, 29, tzinfo=_SHANGHAI)
        assert store.prepared_chip_features_for_day(["000001.SZ"], trade_date, before) == {}

        decision_at = datetime(2024, 1, 2, 15, 30, tzinfo=_SHANGHAI)
        record = store.prepared_chip_features_for_day(["000001.SZ"], trade_date, decision_at)[
            "000001.SZ"
        ]
        assert store.supports_precomputed_chip_features
        assert record.strict_sample
        assert record.features.profit_ratio == pytest.approx(0.61)
        assert record.features.cyqk_pre.close == pytest.approx(61.0)
        assert record.features.peaks[0].mass == pytest.approx(0.45)
        assert record.features.priors == ("BOOK_PRIOR:TEST",)
        assert record.base_retention == pytest.approx(0.83)
        assert record.intraday_factors_complete
    finally:
        store.close()


def test_prepared_chip_features_materialize_each_month_once(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, include_chip_features=True)
    store.initialize()
    try:
        decision_at = datetime(2024, 1, 2, 15, 30, tzinfo=_SHANGHAI)
        records = store.prepared_chip_features_for_day(
            ["000001.SZ"], date(2024, 1, 2), decision_at
        )
        assert records.keys() == {"000001.SZ"}
        assert store._chip_cache_month == (2024, 1)

        # Removing the source view proves the second lookup is served from the
        # materialized month instead of rebuilding it from Parquet.
        store._connection().execute("DROP VIEW pit_b_chip_features")
        cached = store.prepared_chip_features_for_day(
            ["000001.SZ"], date(2024, 1, 2), decision_at
        )
        assert cached == records
    finally:
        store.close()


def test_daily_batch_lookups_reuse_one_execution_snapshot_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, include_minute=True)
    store.initialize()
    trade_date = date(2024, 1, 2)
    decision_at = datetime(2024, 1, 2, 16, tzinfo=_SHANGHAI)
    calls = 0
    original_query = store._query

    def counted_query(sql: str, parameters: list[object]) -> list[dict[str, object]]:
        nonlocal calls
        calls += 1
        return original_query(sql, parameters)

    monkeypatch.setattr(store, "_query", counted_query)
    try:
        execution = store.execution_bars_for_day(
            ["000001.SZ", "000002.SZ"], trade_date, decision_at
        )
        strict = store.strict_bars_for_day(["000001.SZ", "000002.SZ"], trade_date, decision_at)
        provenances = store.bar_provenances_for_day(
            ["000001.SZ", "000002.SZ"], trade_date, decision_at
        )
        rules = store.rules_as_of(
            {"000001.SZ": "MAIN", "000002.SZ": "MAIN"},
            trade_date,
            decision_at,
        )
        market_open = datetime(2024, 1, 2, 9, 30, tzinfo=_SHANGHAI)
        actions = store.corporate_actions_for_day(
            ["000001.SZ", "000002.SZ"], trade_date, market_open
        )

        assert execution.keys() == {"000001.SZ", "000002.SZ"}
        assert strict.keys() == {"000001.SZ"}
        assert strict["000001.SZ"] is execution["000001.SZ"]
        assert provenances["000001.SZ"]["hard_valid"] is True
        assert provenances["000002.SZ"]["hard_valid"] is False
        assert all(rule.known for rule in rules.values())
        assert rules["000001.SZ"] is rules["000002.SZ"]
        assert [item.action_type for item in actions["000001.SZ"]] == ["CASH_DIVIDEND"]
        assert calls == 1
    finally:
        store.close()


def test_daily_rows_reuse_materialized_month_for_new_as_of_time(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.initialize()
    trade_date = date(2024, 1, 2)
    try:
        first = store.execution_bars_for_day(
            ["000001.SZ"],
            trade_date,
            datetime(2024, 1, 2, 16, tzinfo=_SHANGHAI),
        )
        assert first.keys() == {"000001.SZ"}
        assert store._daily_cache_month == (2024, 1)

        # A different decision_at misses the day cache. Dropping the Parquet
        # view proves that lookup still uses the already materialized month.
        store._connection().execute("DROP VIEW pit_b_daily")
        second = store.execution_bars_for_day(
            ["000001.SZ"],
            trade_date,
            datetime(2024, 1, 2, 17, tzinfo=_SHANGHAI),
        )
        assert second == first
    finally:
        store.close()
