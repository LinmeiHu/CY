from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "run_ashare_regime_routed_cross_industry_takeover_v5.py"
SPEC = importlib.util.spec_from_file_location("regime_takeover_v5_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
V5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V5
SPEC.loader.exec_module(V5)


def test_market_regime_is_cut_off_at_candidate_close(tmp_path) -> None:
    dates = pd.bdate_range("2020-01-01", periods=62)
    rows = []
    for symbol, last_price in (("000001.SZ", 2.0), ("000002.SZ", 3.0)):
        prices = np.linspace(1.0, last_price, 61).tolist() + [1000.0]
        for cal_idx, (trade_date, adjusted_close) in enumerate(zip(dates, prices)):
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "cal_idx": cal_idx,
                    "adjusted_close": adjusted_close,
                    "hard_valid": True,
                    "history_valid": True,
                    "current_valid": True,
                    "current_day_data_tradable": True,
                    "market_rule_valid": True,
                    "corporate_action_valid": True,
                    "corporate_action_blocking": False,
                    "is_st": False,
                }
            )
    daily = tmp_path / "daily.parquet"
    pd.DataFrame(rows).to_parquet(daily, index=False)
    market = V5.market_regime_table(daily, dates[60].date().isoformat())
    last = market.loc[market.trade_date.eq(dates[60])].iloc[0]
    assert last.market_valid_count == 2
    assert last.market_median_ret60 == 1.5


def _rows(day: str, count: int, market_return: float) -> list[dict[str, object]]:
    rows = []
    for index in range(count):
        rows.append(
            {
                "event_id": f"{day}|{index}",
                "symbol": f"{index:06d}.SZ",
                "signal_cal_idx": index + 100,
                "signal_date": pd.Timestamp(day),
                "signal_close": 10.1,
                "prior_high": 10.0,
                "signal_turnover": 1.5,
                "signal_prior20_turnover": 1.0,
                "signal_ret60": 0.0,
                "signal_amount": 1.0,
                "anchor_return": -0.03 - index / 1000,
                "causal_industry": f"industry-{index % 8}",
                "sleeve": "MAIN",
                "market_median_ret60": market_return,
                "market_valid_count": 1000,
            }
        )
    return rows


def test_market_route_rejects_mild_downtrend_even_when_broad(monkeypatch) -> None:
    frame = pd.DataFrame(
        _rows("2020-01-02", 11, 0.01)
        + _rows("2020-01-03", 11, -0.05)
        + _rows("2020-01-06", 11, -0.10)
        + _rows("2020-01-07", 20, -0.05)
    )
    monkeypatch.setattr(V5.v3, "attach_features", lambda candidates, daily: candidates)
    monkeypatch.setattr(V5, "attach_market_regime", lambda candidates, daily: candidates)
    selected = V5.select(frame, Path("unused"))
    assert set(selected.signal_date.dt.strftime("%Y-%m-%d")) == {
        "2020-01-02",
        "2020-01-06",
    }
    routes = selected.groupby("signal_date").market_route.first().to_dict()
    assert routes[pd.Timestamp("2020-01-02")] == "BULL_TREND"
    assert routes[pd.Timestamp("2020-01-06")] == "DEEP_CAPITULATION"


def test_industry_cap_prefers_deeper_supply_shocks(monkeypatch) -> None:
    frame = pd.DataFrame(_rows("2020-01-02", 11, 0.01))
    frame["causal_industry"] = "one-industry"
    # Preserve the event-level industry breadth gate while putting four names
    # into one industry after that causal state has already been attached.
    frame.loc[:7, "causal_industry"] = [f"industry-{index}" for index in range(8)]
    frame.loc[8:, "causal_industry"] = "industry-0"
    monkeypatch.setattr(V5.v3, "attach_features", lambda candidates, daily: candidates)
    monkeypatch.setattr(V5, "attach_market_regime", lambda candidates, daily: candidates)
    selected = V5.select(frame, Path("unused"))
    industry_zero = selected.loc[selected.causal_industry.eq("industry-0")]
    assert len(industry_zero) == 3
    assert set(industry_zero.event_id) == {
        "2020-01-02|8",
        "2020-01-02|9",
        "2020-01-02|10",
    }
