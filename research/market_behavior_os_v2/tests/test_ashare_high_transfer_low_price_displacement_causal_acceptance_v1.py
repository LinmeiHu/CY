from types import SimpleNamespace

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_causal_acceptance_v1 as rules,
)


def _row(idx: int, close: float, *, open_price: float | None = None) -> dict:
    price = close if open_price is None else open_price
    date = pd.Timestamp("2019-01-01") + pd.Timedelta(days=idx - 100)
    return {
        "event_id": "A|2019-01-01",
        "trade_date": date,
        "cal_idx": idx,
        "open": price,
        "high": max(price, close) + 0.1,
        "low": min(price, close) - 0.1,
        "close": close,
        "coord_open": price,
        "coord_high": max(price, close) + 0.1,
        "coord_low": min(price, close) - 0.1,
        "coord_close": close,
        "invalid_step_cum": 0.0,
        "coordinate_factor": 1.0,
        "trade_status": 1,
        "current_day_data_tradable": True,
        "current_valid": True,
        "market_rule_valid": True,
        "corporate_action_count": 0,
        "corporate_action_valid": True,
        "corporate_action_blocking": False,
        "hard_valid": True,
        "up_limit_price": price * 1.1,
        "down_limit_price": price * 0.9,
        "available_at": date + pd.Timedelta(hours=15),
        "decision_at": date + pd.Timedelta(hours=15),
    }


def test_first_acceptance_requires_three_of_exact_five_and_current_above() -> None:
    candidate = SimpleNamespace(signal_cal_idx=100, invalid_step_cum=0.0, coord_high=10.0)
    closes = [9.8, 10.1, 10.2, 9.9, 10.3, 9.7, 10.4, 10.5, 10.6, 10.7]
    path = pd.DataFrame([_row(idx, close) for idx, close in enumerate(closes, 101)])
    result = rules.find_stock_acceptance(candidate, path)
    assert result is not None
    assert result.cal_idx == 105

    path.loc[path.cal_idx.eq(103), "current_valid"] = False
    result = rules.find_stock_acceptance(candidate, path)
    assert result is not None
    assert result.cal_idx == 108


def test_market_route_distinguishes_bull_from_nonbull_repair() -> None:
    common = dict(
        market_median_ret20=-0.02,
        market_median_ret60=-0.05,
        market_positive_ret20_share=0.45,
        market_positive_ret60_share=0.35,
        latest_source_timestamp=pd.Timestamp("2019-01-01 15:00"),
    )
    decision = pd.Timestamp("2019-01-01 15:00")
    assert rules.market_admitted(SimpleNamespace(**common, market_regime="BULL"), decision) == (
        True,
        "BULL",
    )
    assert rules.market_admitted(SimpleNamespace(**common, market_regime="BEAR"), decision) == (
        True,
        "BEAR_REPAIR",
    )
    no_repair = SimpleNamespace(
        **{
            **common,
            "market_median_ret20": -0.08,
            "market_positive_ret20_share": 0.25,
        },
        market_regime="BEAR",
    )
    assert rules.market_admitted(no_repair, decision) == (False, "BEAR_NO_REPAIR")


def test_structural_exit_precedes_h60_and_uses_next_open() -> None:
    entry = SimpleNamespace(cal_idx=110, coord_open=10.2)
    rows = [_row(110, 10.2)]
    rows.extend(_row(idx, 10.1) for idx in range(111, 170))
    rows[1]["coord_close"] = 9.9
    rows[1]["close"] = 9.9
    rows[2]["coord_close"] = 9.8
    rows[2]["close"] = 9.8
    path = pd.DataFrame(rows)
    exit_row, reason = rules.choose_exit(entry, 10.0, 0.0, path)
    assert exit_row is not None
    assert exit_row.cal_idx == 113
    assert reason == "TWO_CLOSES_BELOW_EVENT_HIGH"


def test_h60_exit_when_structure_is_not_lost() -> None:
    entry = SimpleNamespace(cal_idx=110, coord_open=10.2)
    path = pd.DataFrame([_row(idx, 10.2) for idx in range(110, 172)])
    exit_row, reason = rules.choose_exit(entry, 10.0, 0.0, path)
    assert exit_row is not None
    assert exit_row.cal_idx == 170
    assert reason == "H60"
