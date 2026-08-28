from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


MODULE_PATH = Path(__file__).with_name("run_reverse_wave_v2.py")
SPEC = importlib.util.spec_from_file_location("reverse_wave_v2", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_lead_analysis_coerces_nullable_canonical_values() -> None:
    feature_rows = []
    event_rows = []
    for symbol, winner, value in (("000001.SZ", True, pd.NA), ("000002.SZ", False, 3.0)):
        feature_rows.append(
            {
                "symbol": symbol,
                "base_exists": winner,
                "peak_track_age": value,
                "peak_track_mass": value,
                "peak_track_prominence": value,
                "peak_band_width_rel_price": value,
                "peak_location_rel_price": value,
                "base_presence_20": value,
                "ensemble_ambiguity": not winner,
                "concentration_20": value,
                "profit_ratio": value,
                "average_cost_rel_price": value,
                "p50_rel_price": value,
            }
        )
        event_rows.append(
            {
                "event_id": symbol,
                "symbol": symbol,
                "split": "discovery",
                "feature_position": 0,
                "any_upside": winner,
                "up20_20": winner,
                "up30_40": winner,
                "up50_60": winner,
            }
        )
    result = MODULE.lead_analysis(pd.DataFrame(event_rows), pd.DataFrame(feature_rows))
    age = result[
        result["feature"].eq("peak_track_age")
        & result["target"].eq("any_upside")
        & result["lead_trading_sessions"].eq(1)
    ].iloc[0]
    assert age["winner_available"] == 0
    assert age["nonwinner_available"] == 1


def test_threshold_audit_counts_object_boolean_rejections_as_positive() -> None:
    events = pd.DataFrame(
        [
            {
                "event_id": "winner",
                "symbol": "000001.SZ",
                "feature_date": pd.Timestamp("2020-06-01"),
                "sample_type": "upside_wave",
                "any_upside": True,
                "up20_20": True,
                "up30_40": False,
                "up50_60": False,
            },
            {
                "event_id": "control",
                "symbol": "000002.SZ",
                "feature_date": pd.Timestamp("2020-06-01"),
                "sample_type": "control_window",
                "any_upside": False,
                "up20_20": False,
                "up30_40": False,
                "up50_60": False,
            },
        ]
    )
    gates = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "decision_date": pd.Timestamp("2020-06-01"),
                "gate_order": 0,
                "gate_name": "setup_score",
                "observed_number": 0.0,
                "threshold_json": "1.0",
                "operator": ">=",
                "blocking": True,
                "passed": False,
            }
            for symbol in ("000001.SZ", "000002.SZ")
        ]
    )
    gates["passed"] = gates["passed"].astype(object)
    result = MODULE.threshold_audit(events, gates)
    setup = result[result["gate_name"].eq("setup_score")].iloc[0]
    assert setup["missed_winner_rejection_count"] == 1
    assert setup["global_evaluated_rows"] == 2
