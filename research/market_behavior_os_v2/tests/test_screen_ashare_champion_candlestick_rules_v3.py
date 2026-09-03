from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    / "screen_ashare_champion_candlestick_rules_v3.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("candlestick_v3_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cohort_trigger_priority_and_thresholds() -> None:
    module = _load_module()
    rows = []
    for signal_date, below_count, d10_return in (
        ("2020-01-03", 7, -0.10),
        ("2020-01-10", 6, -0.03),
        ("2020-01-17", 6, -0.029),
    ):
        for index in range(10):
            rows.append(
                {
                    "signal_date": signal_date,
                    "d5_close_below_signal_low": index < below_count,
                    "d10_close_from_entry": d10_return,
                }
            )
    result = module._cohort_triggers(pd.DataFrame(rows)).set_index("signal_date")

    assert result.loc[pd.Timestamp("2020-01-03").date(), "trigger_checkpoint"] == 5
    assert result.loc[pd.Timestamp("2020-01-10").date(), "trigger_checkpoint"] == 10
    assert pd.isna(result.loc[pd.Timestamp("2020-01-17").date(), "trigger_checkpoint"])


def test_cohort_trigger_fails_closed_on_missing_d5_state() -> None:
    module = _load_module()
    frame = pd.DataFrame(
        {
            "signal_date": ["2020-01-03", "2020-01-03"],
            "d5_close_below_signal_low": [True, None],
            "d10_close_from_entry": [-0.04, -0.04],
        }
    )

    try:
        module._cohort_triggers(frame)
    except module.CandlestickRuleScreenV3Error as error:
        assert "missing d5 cohort state" in str(error)
    else:
        raise AssertionError("missing checkpoint state did not fail closed")
