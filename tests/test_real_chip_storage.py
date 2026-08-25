import json
import math
import runpy
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import numpy as np
from cyq_game.chip.migration_v2 import _PackedWorkingLots
from math import isclose
from cyq_game.chip.profile_metrics import compute_distribution_metrics
from cyq_game.strategy.exact_chip_features import _FAST_OPERATOR_COLUMNS

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_real_chip_year.py"
MODULE = runpy.run_path(str(SCRIPT))


def test_v12_packed_cell_dimensions_are_reversible_for_legacy_reading() -> None:
    pack = MODULE["_pack_cell_dimensions"]
    unpack = MODULE["_unpack_cell_dimensions"]

    dimensions = [
        (None, -1, 0),
        (-123_456, 0, 1),
        (0, 20, 2),
        (2_000_000, 253, 2),
    ]
    for expected in dimensions:
        assert unpack(pack(*expected)) == expected


def test_packed_profile_bucket_mass_uses_legacy_fsum() -> None:
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    bucket = 884
    shares = np.array([1.0e16, 1.0, 1.0], dtype=np.float64)
    packed = _PackedWorkingLots(
        cell_ids=np.array([1, 2, 3], dtype=np.int64),
        cost_bucket_ids=np.array([0, 0, 0], dtype=np.int64),
        holding_days=np.array([0, 0, 0], dtype=np.int16),
        sensitivity_codes=np.array([0, 0, 0], dtype=np.int8),
        acquisition_costs=np.ones(3, dtype=np.float64),
        economic_break_evens=np.full(
            3, grid.price_for_bucket(bucket), dtype=np.float64
        ),
        shares=shares,
        initialization_prior_units=np.zeros(3, dtype=np.float64),
    )
    state = SimpleNamespace(packed_lots=packed)

    _, by_bucket, _, _ = MODULE["_CellCodec"]().register_state_and_profile(
        state, grid
    )

    expected = math.fsum(shares.tolist())
    assert float(np.bincount(np.zeros(3, dtype=np.int64), weights=shares)[0]) != expected
    assert by_bucket == {bucket: expected}


def test_packed_profile_refreshes_stale_cell_ids_even_when_marked_current() -> None:
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    sensitivity = MODULE["TurnoverSensitivity"].NEUTRAL
    cost_bucket_id = 1293
    holding_days = 180
    economic_break_even = 25.076922490046574
    canonical_id = MODULE["stable_cell_id"](
        cost_bucket_id=cost_bucket_id,
        holding_days=holding_days,
        sensitivity=sensitivity,
        economic_break_even=economic_break_even,
    )
    stale_id = 7449910493840738799
    assert canonical_id == 4579257534702646082
    assert stale_id != canonical_id
    packed = _PackedWorkingLots(
        cell_ids=np.array([stale_id], dtype=np.int64),
        cost_bucket_ids=np.array([cost_bucket_id], dtype=np.int64),
        holding_days=np.array([holding_days], dtype=np.int16),
        sensitivity_codes=np.array([1], dtype=np.int8),
        acquisition_costs=np.array([economic_break_even], dtype=np.float64),
        economic_break_evens=np.array([economic_break_even], dtype=np.float64),
        shares=np.array([17.5], dtype=np.float64),
        initialization_prior_units=np.array([0.0], dtype=np.float64),
    )
    packed._cell_ids_current = True
    state = SimpleNamespace(packed_lots=packed)
    dimensions_before = (
        packed.cost_bucket_ids.copy(),
        packed.holding_days.copy(),
        packed.sensitivity_codes.copy(),
        packed.shares.copy(),
    )

    view, _, _, _ = MODULE["_CellCodec"]().register_state_and_profile(
        state, grid
    )

    assert view == {
        canonical_id: (cost_bucket_id, holding_days, sensitivity, 17.5)
    }
    assert packed.cell_ids.tolist() == [canonical_id]
    assert stale_id not in view
    assert np.array_equal(packed.cost_bucket_ids, dimensions_before[0])
    assert np.array_equal(packed.holding_days, dimensions_before[1])
    assert np.array_equal(packed.sensitivity_codes, dimensions_before[2])
    assert np.array_equal(packed.shares, dimensions_before[3])


def test_v12_schema_keeps_full_cell_identity_and_economic_coordinates() -> None:
    assert MODULE["STORAGE_VERSION"] == "chip-operator-log-v12"
    assert MODULE["MODEL_VERSION"] == "real-chip-inventory-v2.1"
    assert MODULE["CHECKPOINT_INTERVAL_DAYS"] == 20
    assert MODULE["PARQUET_COMPRESSION_LEVEL"] == 3

    schema = MODULE["OUTPUT_SCHEMA"]
    assert schema.field("checkpoint_local_ids").type == pa.list_(pa.uint64())
    assert schema.field("checkpoint_economic_bucket_ids").type == pa.list_(pa.int32())
    assert schema.field("source_cell_ids_override").type == pa.list_(pa.uint64())
    assert schema.field("destination_override_cell_ids").type == pa.list_(pa.uint64())
    assert schema.field("inventory_adjustment_local_ids").type == pa.list_(pa.uint64())
    assert schema.field("inventory_adjustment_economic_bucket_ids").type == pa.list_(
        pa.int32()
    )
    assert schema.field("cash_dividend_per_share").type == pa.float64()
    assert schema.field("share_multiplier").type == pa.float64()
    assert schema.field("research_valid").type == pa.bool_()


def test_v12_schema_contains_all_fast_operator_columns() -> None:
    assert set(_FAST_OPERATOR_COLUMNS).issubset(MODULE["OUTPUT_SCHEMA"].names)


def test_minute_inputs_include_registered_2026_qmt_tail(tmp_path: Path) -> None:
    paths_for_year = MODULE["_minute_paths_for_year"]

    assert paths_for_year(2025, tmp_path) == [
        tmp_path / "2025_day_parquet_none.parquet"
    ]
    assert paths_for_year(2026, tmp_path) == [
        tmp_path / "2026_day_parquet_none.parquet",
        tmp_path / "2026_qmt_tail.parquet",
    ]


def test_minute_vwap_rounding_is_clipped_not_discarded() -> None:
    trading_date = date(2020, 6, 19)
    timestamp = datetime(2020, 6, 19, 10, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    bars = MODULE["_minute_bars"](
        [
            {
                "symbol": "000001.SZ",
                "trade_date": trading_date,
                "bar_end_time": timestamp,
                "open": 10.00,
                "high": 10.02,
                "low": 9.99,
                "close": 10.01,
                "volume": 100.0,
                # Rounded turnover implies 10.0201, just above the observed
                # high.  The migration price must remain amount-informed.
                "amount": 1002.01,
            }
        ],
        trading_date,
    )

    assert len(bars) == 1
    assert bars[0].vwap == 10.02
    assert bars[0].migration_price == 10.02


def test_one_invalid_minute_rejects_the_whole_intraday_path() -> None:
    trading_date = date(2026, 8, 21)
    valid = {
        "symbol": "300462.SZ",
        "trade_date": trading_date,
        "bar_end_time": datetime(
            2026, 8, 21, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        "open": 10.0,
        "high": 10.1,
        "low": 9.9,
        "close": 10.0,
        "volume": 100.0,
        "amount": 1_000.0,
    }
    invalid = {
        **valid,
        "bar_end_time": datetime(
            2026, 8, 21, 10, 5, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        "open": 0.0,
    }

    assert MODULE["_minute_bars"]([valid, invalid], trading_date) == ()


def test_turnover_cap_scales_only_the_migration_operator() -> None:
    trading_date = date(2020, 8, 5)
    rows = [
        {
            "symbol": "603733.SH",
            "trade_date": trading_date,
            "bar_end_time": datetime(
                2020, 8, 5, 10, minute, tzinfo=ZoneInfo("Asia/Shanghai")
            ),
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 60.0,
            "amount": 60.0 * price,
        }
        for minute, price in ((1, 10.0), (2, 11.0))
    ]
    bars = MODULE["_minute_bars"](rows, trading_date)
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    path = MODULE["prepare_minute_path"](
        grid=grid,
        decision_at=datetime(2020, 8, 5, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
        minute_bars=bars,
    )

    capped = MODULE["_cap_prepared_minute_path"](path, max_volume=100.0)

    assert capped.total_volume == pytest.approx(100.0)
    assert capped.volumes.tolist() == pytest.approx([50.0, 50.0])
    assert capped.purchase_volumes.sum() == pytest.approx(100.0)
    assert capped.prices.tolist() == path.prices.tolist()
    assert sum(bar.volume_shares for bar in capped.minute_bars) == 120.0


def test_columnar_output_batch_preserves_schema_and_values() -> None:
    schema = MODULE["OUTPUT_SCHEMA"]
    batch = MODULE["_ColumnarOutputBatch"]()
    timestamp = datetime(2020, 6, 19, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    values = tuple(
        {
            "storage_version": MODULE["STORAGE_VERSION"],
            "model_version": MODULE["MODEL_VERSION"],
            "symbol": "000001.SZ",
            "trade_date": date(2020, 6, 19),
            "seller_model": "uniform",
            "snapshot_id": "snapshot:test",
            "decision_at": timestamp,
            "available_at": timestamp,
            "input_snapshot_digest": b"0" * 32,
            "free_float_shares": 100.0,
            "known_cost_fraction": 0.75,
            "unknown_cost_fraction": 0.25,
            "profile_close": 11.0,
            "average_cost": 10.0,
            "cost_p01": 8.5,
            "cost_p10": 9.0,
            "cost_p50": 10.0,
            "cost_p90": 11.0,
            "cost_p99": 11.5,
            "profit_ratio": 0.5,
            "asr": 0.8,
            "cbw": 35.0,
            "concentration_20": 0.9,
            "main_peak": 10.0,
            "dominant_peak_today": 10.0,
            "dominant_band_lower": 9.5,
            "dominant_band_upper": 10.5,
            "dominant_band_mass": 0.8,
            "peak_count": 1,
            "model_quality": 1.0,
            "checkpoint_local_ids": [1],
            "checkpoint_shares": [100.0],
            "checkpoint_economic_bucket_ids": [0],
            "transition_id": "transition:test",
            "source_cell_ids_override": [],
            "destination_override_positions": [],
            "destination_override_cell_ids": [],
            "retention_encoding": 0,
            "retention_values": [1.0],
            "retention_codes": b"",
            "inventory_adjustment_local_ids": [],
            "inventory_adjustment_shares": [],
            "inventory_adjustment_economic_bucket_ids": [],
            "cash_dividend_per_share": 0.0,
            "share_multiplier": 1.0,
            "action_provenance_ids": [],
            "fixed_pre_eligible_shares": 100.0,
            "executed_sell_shares": 0.0,
            "same_day_resale_shares": 0.0,
            "conservation_error_shares": 0.0,
            "minute_fallback": False,
            "hard_valid": True,
            "research_valid": True,
            "quality_reason_codes": [],
        }[field.name]
        for field in schema
    )

    batch.append(values)
    table = batch.to_table()

    assert table.schema == schema
    assert table.num_rows == 1
    assert table.column("symbol")[0].as_py() == "000001.SZ"
    assert table.column("free_float_shares")[0].as_py() == 100.0

    batch.clear()
    assert len(batch) == 0


def test_research_valid_only_relaxes_explicit_unknown_cost() -> None:
    research_valid = MODULE["_research_valid"]

    assert research_valid(SimpleNamespace(quality_reason_codes=("UNKNOWN_COST_PRESENT",)))
    assert research_valid(
        SimpleNamespace(quality_reason_codes=("TURNOVER_CAPPED_AT_FLOAT",))
    )
    assert not research_valid(
        SimpleNamespace(
            quality_reason_codes=("UNKNOWN_COST_PRESENT", "DAILY_BAR_FALLBACK")
        )
    )


def test_daily_profile_peak_uses_stable_bucket_and_tie_break() -> None:
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    profile = MODULE["_profile_from_bucket_mass"](
        {40: 100.0 + 1e-11, 20: 100.0}, grid, current_price=1.0
    )

    assert profile is not None
    assert profile["dominant_peak_today"] == grid.price_for_bucket(20)


def test_daily_profile_peak_prefers_structural_cluster_over_isolated_spike() -> None:
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    profile = MODULE["_profile_from_bucket_mass"](
        {20: 60.0, 21: 60.0, 22: 60.0, 40: 100.0},
        grid,
        current_price=1.0,
    )

    assert profile is not None
    assert profile["dominant_peak_today"] == grid.price_for_bucket(21)


def test_daily_profile_uses_dividend_adjusted_economic_cost() -> None:
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    acquisition_bucket = grid.bucket_for_price(10.0)
    economic_bucket = grid.bucket_for_price(9.5)
    state = SimpleNamespace(
        packed_lots=None,
        lots=[
            SimpleNamespace(
                cell_id=123,
                cost_bucket_id=acquisition_bucket,
                holding_days=10,
                sensitivity=MODULE["TurnoverSensitivity"].NEUTRAL,
                shares=100.0,
                acquisition_cost=10.0,
                economic_break_even=9.5,
            )
        ],
    )

    view, by_bucket, known_shares, economic_buckets = MODULE[
        "_CellCodec"
    ]().register_state_and_profile(state, grid)

    # Cell identity keeps immutable acquisition cost, while the strategy-facing
    # support profile moves to the dividend-adjusted economic coordinate.
    assert view[123][0] == acquisition_bucket
    assert by_bucket == {economic_bucket: 100.0}
    assert economic_bucket != acquisition_bucket
    assert known_shares == 100.0
    assert economic_buckets == {123: economic_bucket}


def test_daily_profile_preserves_nonpositive_economic_break_even() -> None:
    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, "test-grid")
    sentinel = MODULE["NONPOSITIVE_ECONOMIC_BUCKET"]
    state = SimpleNamespace(
        packed_lots=None,
        lots=[
            SimpleNamespace(
                cell_id=123,
                cost_bucket_id=grid.bucket_for_price(1.0),
                holding_days=10,
                sensitivity=MODULE["TurnoverSensitivity"].NEUTRAL,
                shares=100.0,
                acquisition_cost=1.0,
                economic_break_even=-0.5,
            )
        ],
    )

    _, by_bucket, known_shares, economic_buckets = MODULE[
        "_CellCodec"
    ]().register_state_and_profile(state, grid)
    assert by_bucket == {sentinel: 100.0}
    assert economic_buckets == {123: sentinel}
    assert known_shares == 100.0
    with pytest.raises(ValueError, match="positive"):
        MODULE["_profile_from_bucket_mass"](
            by_bucket, grid, current_price=1.0
        )


def test_zero_retention_company_action_destination_needs_no_codec_entry() -> None:
    """A zero-mass transformed cell must not break compact operator encoding."""

    grid = MODULE["StableLogPriceGrid"](1.0, 0.0025, MODULE["GRID_VERSION"])
    stable_cell_id = MODULE["stable_cell_id"]
    sensitivity = MODULE["TurnoverSensitivity"].NEUTRAL
    source_id = stable_cell_id(
        cost_bucket_id=100, holding_days=10, sensitivity=sensitivity
    )
    transformed_zero_id = stable_cell_id(
        cost_bucket_id=50, holding_days=11, sensitivity=sensitivity
    )
    purchase_id = stable_cell_id(
        cost_bucket_id=200, holding_days=0, sensitivity=sensitivity
    )
    timestamp = datetime(2020, 6, 19, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    state = SimpleNamespace(
        packed_lots=None,
        lots=[
            SimpleNamespace(
                cell_id=purchase_id,
                cost_bucket_id=200,
                holding_days=0,
                sensitivity=sensitivity,
                shares=100.0,
                acquisition_cost=grid.price_for_bucket(200),
                economic_break_even=grid.price_for_bucket(200),
            )
        ],
        model_version=MODULE["MODEL_VERSION"],
        symbol="300729.SZ",
        trading_date=date(2020, 6, 19),
        seller_model=MODULE["SellerModel"].UNIFORM,
        snapshot_id="snapshot:post",
        decision_at=timestamp,
        available_at=timestamp,
        input_snapshot_ids=("input:test",),
        free_float_shares=100.0,
        conservation_error=0.0,
        hard_valid=True,
        quality_reason_codes=(),
    )
    transition = SimpleNamespace(
        transition_id="transition:test",
        source_cell_ids=(source_id,),
        destination_cell_ids=(transformed_zero_id,),
        retained_fractions=(0.0,),
        fixed_pre_eligible_shares=100.0,
        executed_sell_shares=100.0,
        same_day_resale_shares=0.0,
    )
    codec = MODULE["_CellCodec"]()
    codec.by_cell_id[source_id] = MODULE["_pack_cell_dimensions"](100, 10, 1)

    row, _, _ = MODULE["_output_row"](
        state=state,
        transition=transition,
        fallback=False,
        previous_post={source_id: (100, 10, sensitivity, 100.0)},
        previous_economic_buckets={source_id: 100},
        codec=codec,
        grid=grid,
        current_price=11.0,
        share_multiplier=2.0,
    )

    expected = compute_distribution_metrics({200: 100.0}, close=11.0, grid=grid)
    values = dict(zip(MODULE["OUTPUT_SCHEMA"].names, row, strict=True))
    assert values["profile_close"] == 11.0
    assert values["main_peak"] == expected.main_peak
    assert values["dominant_peak_today"] == expected.main_peak
    assert isclose(values["average_cost"], expected.average_cost, rel_tol=1e-12)
    assert isclose(values["cost_p01"], expected.cost_p01, rel_tol=1e-12)
    assert isclose(values["cost_p10"], expected.cost_p10, rel_tol=1e-12)
    assert isclose(values["cost_p50"], expected.cost_p50, rel_tol=1e-12)
    assert isclose(values["cost_p90"], expected.cost_p90, rel_tol=1e-12)
    assert isclose(values["cost_p99"], expected.cost_p99, rel_tol=1e-12)
    assert isclose(values["profit_ratio"], expected.profit_ratio, rel_tol=1e-12)
    assert isclose(values["asr"], expected.asr, rel_tol=1e-12)
    assert values["cbw"] == expected.cbw
    assert isclose(values["concentration_20"], expected.concentration_20, rel_tol=1e-12)
    assert values["peak_count"] == expected.peak_count

    assert values["destination_override_positions"] == [0]
    assert values["destination_override_cell_ids"] == [transformed_zero_id]
    assert values["inventory_adjustment_shares"] == [100.0]


def test_targeted_run_reuses_staged_symbol_superset() -> None:
    matches = MODULE["_stage_marker_matches"]
    metadata = {
        "year": 2020,
        "warmup_start": 2018,
        "buckets": 10,
        "layout_version": MODULE["STAGE_LAYOUT_VERSION"],
        "prior_history_start": None,
        "end_date": "2020-06-19",
        "symbols": ["000001.SZ", "600000.SH"],
    }

    assert matches(
        metadata,
        year=2020,
        warmup_start=2018,
        buckets=10,
        symbols=("000001.SZ",),
        prior_history_start=None,
        end_date=date(2020, 6, 19),
    )
    assert not matches(
        metadata,
        year=2020,
        warmup_start=2018,
        buckets=10,
        symbols=("300750.SZ",),
        prior_history_start=None,
        end_date=date(2020, 6, 19),
    )


def test_v10_retention_codec_is_exact() -> None:
    encode = MODULE["_encode_retention"]
    decode = MODULE["_decode_retention"]
    fractions = (0.5, 0.5, 0.75, 0.125, 0.125, 0.9)
    sensitivities = (0, 1, 2, 0, 1, 2)

    encoding, values, payload = encode(fractions, sensitivities)

    assert encoding != MODULE["RETENTION_SOURCE_REPLAY"]
    assert decode(encoding, values, payload, sensitivities) == fractions


def test_legacy_part_is_not_resumed(tmp_path: Path) -> None:
    path = tmp_path / "legacy.parquet"
    pq.write_table(pa.table({"symbol": ["000005.SZ"]}), path)

    assert MODULE["_existing_part_result"](path, "000005.SZ") is None


def test_symbol_partition_reader_restores_symbol_without_bucket_scan(
    tmp_path: Path,
) -> None:
    partition = tmp_path / "daily" / "bucket=3" / "symbol=000005.SZ"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "trade_date": ["2020-01-03", "2020-01-02"],
                "close": [11.0, 10.0],
            }
        ),
        partition / "data_0.parquet",
    )

    partitions = MODULE["_symbol_partition_dirs"](tmp_path, "daily", 3)
    rows = MODULE["_read_symbol_partition"](
        partitions["000005.SZ"], "000005.SZ"
    )

    assert set(partitions) == {"000005.SZ"}
    assert [row["symbol"] for row in rows] == ["000005.SZ", "000005.SZ"]
    assert [row["close"] for row in rows] == [11.0, 10.0]


def test_terminal_state_roundtrip_is_exact_and_resumable(tmp_path: Path) -> None:
    timestamp = datetime(2020, 12, 31, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    snapshots = {
        model: MODULE["initial_unknown_snapshot"](
            symbol="000005.SZ",
            decision_at=timestamp,
            available_at=timestamp,
            free_float_shares=123_456_789.0,
            latent_supply_shares=0.0,
            seller_model=model,
            model_version=MODULE["MODEL_VERSION"],
            grid_version=MODULE["GRID_VERSION"],
            input_snapshot_ids=("daily:test",),
        )
        for model in MODULE["SELLER_MODEL_ORDER"]
    }
    path = tmp_path / "terminal.parquet"

    MODULE["_write_terminal_snapshots"](path, snapshots)
    restored = MODULE["_read_terminal_snapshots"](
        path, "000005.SZ", before_year=2021, expected_year=2020
    )

    assert restored == snapshots
    assert {snapshot.trading_date for snapshot in restored.values()} == {
        date(2020, 12, 31)
    }
    with pytest.raises(ValueError, match="immediately previous year"):
        MODULE["_read_terminal_snapshots"](
            path, "000005.SZ", before_year=2022, expected_year=2021
        )


def test_v11_terminal_snapshot_can_seed_v12_initial_state(tmp_path: Path) -> None:
    symbol = "000005.SZ"
    timestamp = datetime(2020, 12, 31, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    snapshots = {
        model: MODULE["initial_unknown_snapshot"](
            symbol=symbol,
            decision_at=timestamp,
            available_at=timestamp,
            free_float_shares=1_000.0,
            latent_supply_shares=0.0,
            seller_model=model,
            model_version=MODULE["MODEL_VERSION"],
            grid_version=MODULE["GRID_VERSION"],
            input_snapshot_ids=("daily:test",),
        )
        for model in MODULE["SELLER_MODEL_ORDER"]
    }
    terminal_v12 = tmp_path / "terminal_v12.parquet"
    terminal_v11 = tmp_path / "terminal_v11.parquet"
    MODULE["_write_terminal_snapshots"](terminal_v12, snapshots)
    terminal = pq.read_table(terminal_v12)
    terminal = terminal.set_column(
        terminal.schema.get_field_index("storage_version"),
        "storage_version",
        pa.array(["chip-operator-log-v11"] * terminal.num_rows),
    )
    pq.write_table(terminal, terminal_v11)

    initial_snapshots = MODULE["_read_terminal_snapshots"](
        terminal_v11, symbol, before_year=2021, expected_year=2020
    )
    assert set(initial_snapshots) == set(MODULE["SELLER_MODEL_ORDER"])

    trading_date = date(2021, 1, 2)
    daily = {
        "symbol": symbol,
        "trade_date": trading_date,
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "volume": 100.0,
        "amount": 1_000.0,
        "circulating_shares": 1_000.0,
        "corporate_action_available_date": trading_date,
        "float_available_date": trading_date,
        "cash_per_share": 0.0,
        "share_multiplier": 1.0,
        "hard_valid": True,
        "snapshot_id": "daily:2021-01-02",
        "daily_snapshot_id": "daily:2021-01-02",
        "float_snapshot_id": "float:2021-01-02",
        "corporate_action_snapshot_id": "action:2021-01-02",
    }
    minute = {
        "symbol": symbol,
        "trade_date": trading_date,
        "bar_end_time": datetime(
            2021, 1, 2, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "volume": 100.0,
        "amount": 1_000.0,
    }

    result, terminal = MODULE["_run_symbol"](
        symbol,
        [daily],
        [minute],
        2021,
        None,
        initial_snapshots,
        emit_operators=False,
    )

    assert result["state_resumed"] is True
    assert {state.trading_date for state in terminal.values()} == {trading_date}


def test_terminal_only_run_advances_state_without_writing_operators() -> None:
    symbol = "000005.SZ"
    prior_at = datetime(2023, 12, 29, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
    initial = {
        model: MODULE["initial_unknown_snapshot"](
            symbol=symbol,
            decision_at=prior_at,
            available_at=prior_at,
            free_float_shares=1_000.0,
            latent_supply_shares=0.0,
            seller_model=model,
            model_version=MODULE["MODEL_VERSION"],
            grid_version=MODULE["GRID_VERSION"],
            input_snapshot_ids=("daily:prior",),
        )
        for model in MODULE["SELLER_MODEL_ORDER"]
    }
    trading_date = date(2024, 1, 2)
    daily = {
        "symbol": symbol,
        "trade_date": trading_date,
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "volume": 100.0,
        "amount": 1_000.0,
        "circulating_shares": 1_000.0,
        "corporate_action_available_date": trading_date,
        "float_available_date": trading_date,
        "cash_per_share": 0.0,
        "share_multiplier": 1.0,
        "hard_valid": True,
        "snapshot_id": "daily:2024-01-02",
        "daily_snapshot_id": "daily:2024-01-02",
        "float_snapshot_id": "float:2024-01-02",
        "corporate_action_snapshot_id": "action:2024-01-02",
    }
    minute = {
        "symbol": symbol,
        "trade_date": trading_date,
        "bar_end_time": datetime(
            2024, 1, 2, 15, 0, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        "open": 10.0,
        "high": 10.0,
        "low": 10.0,
        "close": 10.0,
        "volume": 100.0,
        "amount": 1_000.0,
    }

    result, terminal = MODULE["_run_symbol"](
        symbol,
        [daily],
        [minute],
        2024,
        None,
        initial,
        emit_operators=False,
    )

    assert result["rows"] == 0
    assert result["target_days"] == 1
    assert result["emitted_days"] == 0
    assert result["state_resumed"] is True
    assert {state.trading_date for state in terminal.values()} == {trading_date}


def test_targeted_stage_reuses_full_stage_but_not_another_symbol_scope() -> None:
    matches = MODULE["_stage_marker_matches"]
    full = {
        "year": 2021,
        "warmup_start": 2021,
        "buckets": 10,
        "layout_version": MODULE["STAGE_LAYOUT_VERSION"],
    }
    scoped = {**full, "symbols": ["000001.SZ"]}

    assert matches(
        full,
        year=2021,
        warmup_start=2021,
        buckets=10,
        symbols=("000001.SZ",),
    )
    assert matches(
        scoped,
        year=2021,
        warmup_start=2021,
        buckets=10,
        symbols=("000001.SZ",),
    )
    assert not matches(
        scoped,
        year=2021,
        warmup_start=2021,
        buckets=10,
        symbols=("000002.SZ",),
    )
    assert not matches(
        scoped,
        year=2021,
        warmup_start=2021,
        buckets=10,
        symbols=(),
    )


def test_stage_marker_separates_incremental_prior_history_contract() -> None:
    matches = MODULE["_stage_marker_matches"]
    metadata = {
        "year": 2021,
        "warmup_start": 2021,
        "buckets": 10,
        "layout_version": MODULE["STAGE_LAYOUT_VERSION"],
        "prior_history_start": 2018,
    }

    assert matches(
        metadata,
        year=2021,
        warmup_start=2021,
        buckets=10,
        symbols=(),
        prior_history_start=2018,
    )
    assert not matches(
        metadata,
        year=2021,
        warmup_start=2021,
        buckets=10,
        symbols=(),
        prior_history_start=None,
    )


def test_stage_marker_separates_end_date_contract() -> None:
    matches = MODULE["_stage_marker_matches"]
    metadata = {
        "year": 2020,
        "warmup_start": 2018,
        "buckets": 10,
        "layout_version": MODULE["STAGE_LAYOUT_VERSION"],
        "prior_history_start": None,
        "end_date": "2020-06-19",
    }

    assert matches(
        metadata,
        year=2020,
        warmup_start=2018,
        buckets=10,
        symbols=(),
        end_date=date(2020, 6, 19),
    )
    assert not matches(
        metadata,
        year=2020,
        warmup_start=2018,
        buckets=10,
        symbols=(),
        end_date=date(2020, 6, 18),
    )


def test_adjacent_year_terminal_is_discovered_automatically(tmp_path: Path) -> None:
    output_root = tmp_path / "year=2021"
    previous_root = tmp_path / "year=2020"
    (previous_root / "terminal").mkdir(parents=True)
    resolve = MODULE["_resolve_resume_root"]

    assert resolve(
        output_root=output_root,
        year=2021,
        warmup_start=2018,
        explicit=None,
        auto_resume=True,
    ) == (previous_root, "auto_adjacent_year")
    assert resolve(
        output_root=output_root,
        year=2021,
        warmup_start=2018,
        explicit=None,
        auto_resume=False,
    ) == (None, "none")


def test_staged_prior_symbol_index_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "PRIOR_SYMBOLS.json"
    path.write_text(json.dumps(["000001.SZ", "600000.SH"]), encoding="utf-8")

    assert MODULE["_read_prior_symbols"](tmp_path) == {
        "000001.SZ",
        "600000.SH",
    }
