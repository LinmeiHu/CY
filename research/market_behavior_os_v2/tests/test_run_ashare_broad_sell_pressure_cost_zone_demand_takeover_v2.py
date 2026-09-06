from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "run_ashare_broad_sell_pressure_cost_zone_demand_takeover_v2.py"
SPEC = importlib.util.spec_from_file_location("broad_cost_takeover_v2_tested", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
V2 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V2
SPEC.loader.exec_module(V2)


def test_selection_counts_breadth_after_stock_level_demand_filters(monkeypatch) -> None:
    rows = []
    for day, count in (("2020-01-02", 20), ("2020-01-03", 19)):
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
                    "sleeve": "MAIN",
                }
            )
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(V2, "attach_prior_high", lambda candidates, daily: candidates)
    selected = V2.select(frame, Path("unused"))
    assert len(selected) == 20
    assert selected.signal_date.nunique() == 1
    assert selected.same_date_takeover_count.eq(20).all()


def test_selection_rejects_weak_reclaim_before_breadth_count(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "event_id": [f"event-{index}" for index in range(20)],
            "symbol": [f"{index:06d}.SZ" for index in range(20)],
            "signal_cal_idx": range(100, 120),
            "signal_date": pd.Timestamp("2020-01-02"),
            "signal_close": [9.9, *([10.1] * 19)],
            "prior_high": 10.0,
            "signal_turnover": 1.5,
            "signal_prior20_turnover": 1.0,
            "sleeve": "MAIN",
        }
    )
    monkeypatch.setattr(V2, "attach_prior_high", lambda candidates, daily: candidates)
    assert V2.select(frame, Path("unused")).empty
