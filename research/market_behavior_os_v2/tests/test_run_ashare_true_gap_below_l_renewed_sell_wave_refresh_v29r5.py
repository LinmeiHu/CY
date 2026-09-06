from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_ashare_true_gap_below_l_renewed_sell_wave_refresh_v29r5.py"
)
SPEC = importlib.util.spec_from_file_location("v29r5", RUNNER)
assert SPEC is not None and SPEC.loader is not None
v29r5 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v29r5)


def test_refreshed_freshness_keeps_f14_and_only_recent_low_for_old_gap() -> None:
    assert v29r5.refreshed_freshness(14, 10)
    assert v29r5.refreshed_freshness(15, 3)
    assert v29r5.refreshed_freshness(30, 1)
    assert not v29r5.refreshed_freshness(30, 0)
    assert not v29r5.refreshed_freshness(15, 4)
    assert not v29r5.refreshed_freshness(31, 0)
    assert not v29r5.refreshed_freshness(None, 0)


def test_one_price_limit_down_requires_all_four_raw_prices_at_limit() -> None:
    exact = pd.Series(
        {
            "open": 9.0,
            "high": 9.0,
            "low": 9.0,
            "close": 9.0,
            "down_limit_price": 9.0,
        }
    )
    traded = exact.copy()
    traded["high"] = 9.02
    missing = exact.copy()
    missing["down_limit_price"] = None
    assert v29r5._one_price_limit_down(exact)
    assert not v29r5._one_price_limit_down(traded)
    assert not v29r5._one_price_limit_down(missing)


def test_row_lineage_fails_closed_on_availability_and_snapshot() -> None:
    signal_time = pd.Timestamp("2021-06-01 15:30:00")
    base = {
        "bar_valid": True,
        "trading_state_valid": True,
        "industry_valid": True,
        "corporate_action_valid": True,
        "market_rule_valid": True,
        "hard_valid": True,
        "decision_timezone": "Asia/Shanghai",
        "available_at": pd.Timestamp("2021-06-01 15:10:00"),
        "decision_at": pd.Timestamp("2021-06-01 15:10:00"),
        "snapshot_id": "snapshot",
        "daily_snapshot_id": "daily",
        "trading_state_snapshot_id": "trading",
        "industry_snapshot_id": "industry",
        "corporate_action_snapshot_id": "action",
    }
    assert v29r5._row_lineage_valid(pd.Series(base), signal_time)
    future = dict(base, available_at=pd.Timestamp("2021-06-02"))
    assert not v29r5._row_lineage_valid(pd.Series(future), signal_time)
    inverted = dict(
        base,
        available_at=pd.Timestamp("2021-06-01 15:11:00"),
        decision_at=pd.Timestamp("2021-06-01 15:10:00"),
    )
    assert not v29r5._row_lineage_valid(pd.Series(inverted), signal_time)
    missing = dict(base, industry_snapshot_id="")
    assert not v29r5._row_lineage_valid(pd.Series(missing), signal_time)


def test_cap25_round_robin_is_deterministic_and_industry_balanced() -> None:
    rows = []
    for industry, count in (("A", 20), ("B", 10), ("C", 5)):
        for index in range(count):
            rows.append(
                {
                    "gap_id": f"{industry}-{index}",
                    "symbol": f"{industry}{index:03d}",
                    "signal_date": pd.Timestamp("2020-01-02"),
                    "signal_industry": industry,
                    "rebound_from_post_gap_low_over_l": 1.0 - index / 100.0,
                }
            )
    selected = pd.DataFrame(rows)
    first = v29r5.build_cap25_identity(selected)
    second = v29r5.build_cap25_identity(selected.sample(frac=1.0, random_state=7))
    assert len(first) == 25
    assert first.gap_id.tolist() == second.gap_id.tolist()
    assert first.signal_industry.value_counts().to_dict() == {"A": 10, "B": 10, "C": 5}
    assert first.cap25_rank.tolist() == list(range(1, 26))
    assert first.cap25_primary_economic_admission.eq(True).all()


def test_parent_allow_list_has_no_execution_or_outcome_columns() -> None:
    assert not {
        column
        for column in v29r5.V13_COLUMNS
        if any(token in column.lower() for token in v29r5.FORBIDDEN_PARENT_TOKENS)
    }
    assert tuple(v29r5.DEVELOPMENT_YEARS) == (2018, 2019, 2020, 2021)
    assert v29r5.V13_SIGNALS.name == "signals.parquet"


def test_unknown_action_and_traded_limit_inputs_fail_closed() -> None:
    action = pd.Series(
        {
            "corporate_action_count": 0,
            "corporate_action_blocking": None,
            "share_multiplier": 1.0,
            "cash_per_share": 0.0,
        }
    )
    assert not v29r5._action_free(action)
    limit_row = pd.Series(
        {
            "trade_status": 1,
            "open": 9.0,
            "high": 9.0,
            "low": 9.0,
            "close": 9.0,
            "down_limit_price": None,
        }
    )
    assert not v29r5._limit_history_row_known(limit_row)


def _uniform_refresh_fixture() -> tuple[pd.DataFrame, pd.Series]:
    dates = pd.bdate_range("2020-01-02", periods=40)
    rows = []
    for date in dates:
        decision_at = date + pd.Timedelta(hours=15)
        rows.append(
            {
                "trade_date": date,
                "decision_at": decision_at,
                "decision_timezone": "Asia/Shanghai",
                "symbol": "000001.SZ",
                "open": 8.8,
                "high": 9.0,
                "low": 8.6,
                "close": 8.7,
                "amount": 100.0,
                "trade_status": 1,
                "is_st": False,
                "up_limit_price": 11.0,
                "down_limit_price": 7.0,
                "current_day_data_tradable": True,
                "industry": "TEST",
                "corporate_action_count": 0,
                "corporate_action_blocking": False,
                "share_multiplier": 1.0,
                "cash_per_share": 0.0,
                "bar_valid": True,
                "trading_state_valid": True,
                "industry_valid": True,
                "corporate_action_valid": True,
                "market_rule_valid": True,
                "hard_valid": True,
                "available_at": decision_at,
                "snapshot_id": "SNAP",
                "daily_snapshot_id": "DAILY",
                "trading_state_snapshot_id": "STATE",
                "industry_snapshot_id": "INDUSTRY",
                "corporate_action_snapshot_id": "ACTION",
            }
        )
    daily = pd.DataFrame(rows)
    daily.loc[15, ["open", "high", "low", "close"]] = [9.8, 10.0, 9.2, 9.4]
    daily.loc[25, "low"] = 8.00001
    daily.loc[28, "low"] = 8.00004
    daily.loc[30, ["open", "high", "low", "close", "amount"]] = [
        8.9,
        9.2,
        8.8,
        9.1,
        150.0,
    ]
    gap = pd.Series(
        {
            "gap_id": "000001.SZ|2020-01-23",
            "symbol": "000001.SZ",
            "board": "MAIN",
            "gap_date": daily.loc[15, "trade_date"],
            "signal_date": daily.loc[30, "trade_date"],
            "signal_time": daily.loc[30, "decision_at"],
            "gap_age": 15,
            "coordinate_factor": 1.0,
            "L": 10.0,
            "pre_peak_to_gap_sessions": 30,
            "max_depth": 0.20,
            "current_depth": 0.09,
            "days_since_low20": 9,
            "recovery_from_low20": 0.03,
            "decision_latest_timestamp": daily.loc[30, "decision_at"],
        }
    )
    return daily, gap


def test_refresh_low_age_is_recomputed_from_latest_raw_cent_tick() -> None:
    daily, gap = _uniform_refresh_fixture()

    audit, _ = v29r5.evaluate_fixed_signal(gap, daily)

    assert audit["selected"] is True
    assert audit["days_since_low20"] == 2
    assert audit["low20_raw"] == daily.loc[28, "low"]
    assert audit["parent_low_age_matches_uniform"] is False

    daily.loc[12, "corporate_action_count"] = 1
    daily.loc[12, "cash_per_share"] = 0.05
    blocked, _ = v29r5.evaluate_fixed_signal(gap, daily)
    assert blocked["selected"] is False
    assert blocked["coordinate_window_action_free"] is False
