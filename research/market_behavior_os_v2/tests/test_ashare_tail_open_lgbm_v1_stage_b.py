from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
CORE_PATH = ROOT / "research/market_behavior_os_v2/scripts/ashare_tail_open_lgbm_v1_core.py"
RUNNER_PATH = (
    ROOT / "research/market_behavior_os_v2/scripts/run_ashare_tail_open_lgbm_v1_stage_b.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location("tail_open_core_test", CORE_PATH)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
CORE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = CORE
MODULE_SPEC.loader.exec_module(CORE)
RUNNER_SPEC = importlib.util.spec_from_file_location("tail_open_runner_test", RUNNER_PATH)
assert RUNNER_SPEC is not None and RUNNER_SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(RUNNER_SPEC)
sys.modules[RUNNER_SPEC.name] = RUNNER
RUNNER_SPEC.loader.exec_module(RUNNER)


def _raw_table(post_cutoff_jump: float = 0.0) -> pa.Table:
    minutes = CORE.EXPECTED_MINUTES
    timestamps = [
        pd.Timestamp("2020-06-01") + pd.Timedelta(minutes=int(value)) for value in minutes
    ]
    close = 10.0 + np.arange(len(minutes), dtype=float) * 0.001
    close[CORE.CUTOFF_POSITION + 1 :] += post_cutoff_jump
    open_price = np.r_[close[0], close[:-1]]
    high = np.maximum(open_price, close) + 0.001
    low = np.minimum(open_price, close) - 0.001
    volume = np.full(len(minutes), 1000.0)
    amount = volume * (open_price + close) / 2
    return pa.table(
        {
            "symbol": ["600000"] * len(minutes),
            "exchange": ["SH"] * len(minutes),
            "period": ["1m"] * len(minutes),
            "adjust": ["none"] * len(minutes),
            "trade_date": [date(2020, 6, 1)] * len(minutes),
            "bar_end_time": timestamps,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "source": ["synthetic"] * len(minutes),
        }
    )


def test_post_1425_prices_cannot_change_feature_vector() -> None:
    base, _ = CORE.extract_raw_day(_raw_table())
    changed, _ = CORE.extract_raw_day(_raw_table(post_cutoff_jump=5.0))
    np.testing.assert_array_equal(
        base[list(CORE.RAW_DIRECT_FEATURES)].to_numpy(),
        changed[list(CORE.RAW_DIRECT_FEATURES)].to_numpy(),
    )
    assert base.entry_vwap.iloc[0] != changed.entry_vwap.iloc[0]


def test_feature_construction_is_deterministic() -> None:
    first, first_audit = CORE.extract_raw_day(_raw_table())
    second, second_audit = CORE.extract_raw_day(_raw_table())
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    assert first_audit == second_audit


def test_resumable_shard_identity_normalizes_timestamp_to_date() -> None:
    table = pa.table(
        {"trade_date": pa.array([pd.Timestamp("2018-01-02")], type=pa.timestamp("ns"))}
    )
    assert RUNNER._normalized_trade_dates(table) == {date(2018, 1, 2)}


def test_prior_liquidity_log_ignores_invalid_zero_amount() -> None:
    values = duckdb.sql(
        """
        WITH history(sequence,amount,history_valid) AS (
          VALUES (1,0.0,FALSE),(2,100.0,TRUE),(3,200.0,TRUE)
        )
        SELECT ln(avg(amount) FILTER (WHERE history_valid) OVER (
          ORDER BY sequence ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
        )) AS prior_log_amount
        FROM history ORDER BY sequence
        """
    ).fetchall()
    assert values[0][0] is None
    assert values[1][0] is None
    assert values[2][0] == np.log(100.0)


def test_panel_audit_rejects_all_null_frozen_feature(tmp_path: Path) -> None:
    path = tmp_path / "panel.parquet"
    pq.write_table(pa.table({"valid": [1.0], "all_null": [None]}), path)
    connection = duckdb.connect()
    assert RUNNER._all_null_columns(connection, path, ["valid", "all_null"]) == ["all_null"]
    connection.close()


def test_pit_industry_requires_prior_notice() -> None:
    assert CORE.causal_industry("2020-05-29", "2020-06-01", "Bank")
    assert not CORE.causal_industry("2020-06-01", "2020-06-01", "Bank")
    assert not CORE.causal_industry(None, "2020-06-01", "Bank")


def test_ridge_preprocessing_is_fit_on_training_only() -> None:
    pipeline = CORE.ridge_pipeline(alpha=10.0)
    train = pd.DataFrame({"a": [1.0, np.nan, 3.0], "b": [2.0, 4.0, 6.0]})
    pipeline.fit(train, [0.0, 0.1, 0.2])
    assert pipeline.named_steps["imputer"].statistics_.tolist() == [2.0, 4.0]
    pipeline.predict(pd.DataFrame({"a": [1_000_000.0], "b": [1_000_000.0]}))
    assert pipeline.named_steps["imputer"].statistics_.tolist() == [2.0, 4.0]


def test_folds_are_strictly_chronological() -> None:
    folds = CORE.frozen_development_folds()
    assert len(folds) == 4
    assert [fold.predict_start.year for fold in folds] == [2018, 2019, 2020, 2021]
    for fold in folds:
        assert fold.train_start <= fold.train_end < fold.predict_start <= fold.predict_end


def test_purge_and_embargo_remove_boundary_labels() -> None:
    fold = CORE.frozen_development_folds()[0]
    signals = pd.Series(pd.to_datetime(["2017-12-27", "2017-12-28", "2017-12-29"]))
    exits = pd.Series(pd.to_datetime(["2017-12-28", "2017-12-29", "2018-01-02"]))
    mask = CORE.purged_training_mask(signals, exits, fold)
    assert mask.tolist() == [True, False, False]


def test_label_matches_frozen_cost_formula() -> None:
    actual = CORE.net_tail_open_return(10.0, 10.1, 0.002)
    expected = 10.1 * 0.998 / (10.0 * 1.002) - 1
    assert actual == expected


def test_label_carries_exact_cash_only_action_without_sell_cost() -> None:
    actual = CORE.net_tail_open_return(10.0, 10.1, 0.002, 0.2)
    expected = (10.1 * 0.998 + 0.2) / (10.0 * 1.002) - 1
    assert actual == expected


def test_first_legal_exit_is_t_plus_one_or_later() -> None:
    rows = [
        {
            "trade_date": "2020-06-01",
            "hard_valid": True,
            "trade_status": 1,
            "current_day_data_tradable": True,
            "sell_blocked_open": False,
            "open": 10.0,
        },
        {
            "trade_date": "2020-06-02",
            "hard_valid": True,
            "trade_status": 0,
            "current_day_data_tradable": False,
            "sell_blocked_open": False,
            "open": 10.0,
        },
        {
            "trade_date": "2020-06-03",
            "hard_valid": True,
            "trade_status": 1,
            "current_day_data_tradable": True,
            "sell_blocked_open": False,
            "open": 10.2,
        },
    ]
    exit_row = CORE.first_legal_exit(rows, date(2020, 6, 1))
    assert exit_row is not None and exit_row["trade_date"] == "2020-06-03"


def test_upper_limit_pinned_entry_is_not_executable() -> None:
    assert not CORE.entry_executable(11.0, 11.0, 11.0)
    assert CORE.entry_executable(10.99, 10.99, 11.0)


def test_lower_limit_or_suspension_blocks_exit() -> None:
    suspended = {
        "hard_valid": True,
        "trade_status": 0,
        "current_day_data_tradable": False,
        "sell_blocked_open": False,
        "open": 9.0,
    }
    pinned = {
        "hard_valid": True,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "sell_blocked_open": True,
        "open": 9.0,
    }
    assert not CORE.legal_open(suspended)
    assert not CORE.legal_open(pinned)


def test_corporate_action_unknown_or_rights_path_fails_closed() -> None:
    assert CORE.corporate_action_path_valid([{"corporate_action_count": 0}])
    assert not CORE.corporate_action_path_valid([{"corporate_action_count": 1}])
    assert not CORE.corporate_action_path_valid(
        [{"corporate_action_count": 0, "rights_ratio": 0.1}]
    )


def test_lightgbm_is_deterministic_for_frozen_seed() -> None:
    rng = np.random.default_rng(7)
    x = rng.normal(size=(500, 4))
    y = x[:, 0] - 0.5 * x[:, 1] + rng.normal(scale=0.1, size=500)
    profile = {
        "name": "test",
        "num_leaves": 7,
        "max_depth": 3,
        "min_data_in_leaf": 20,
        "lambda_l1": 1.0,
        "lambda_l2": 10.0,
    }
    first = CORE.lightgbm_model(profile, 20260901, n_estimators=30).fit(x, y)
    second = CORE.lightgbm_model(profile, 20260901, n_estimators=30).fit(x, y)
    np.testing.assert_array_equal(first.predict(x), second.predict(x))


def test_signal_eligibility_requires_bound_daily_snapshot() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "e.daily_snapshot_id=d.snapshot_id" in source


def test_execution_extension_drops_hive_year_artifact() -> None:
    extension_path = RUNNER_PATH.with_name(
        "build_ashare_tail_open_lgbm_v1_execution_extension.py"
    )
    source = extension_path.read_text(encoding="utf-8")
    assert "SELECT * EXCLUDE(year) FROM read_parquet" in source
