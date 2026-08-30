from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
RUNNER = (
    ROOT
    / "research/chinext_v1/research_os_v2/scripts/audit_five_day_minute_data.py"
)
SPEC = importlib.util.spec_from_file_location("audit_five_day_minute_data", RUNNER)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_spec_and_identity_projection_are_outcome_blind() -> None:
    spec, _ = audit.validate_spec_and_inputs()
    events, targets = audit.load_event_sessions()
    assert spec["outcome_access"] is False
    assert len(events) == 399
    assert len(targets) == 1995
    assert set(targets.relative_day) == {-5, -4, -3, -2, -1}
    assert not audit.FORBIDDEN_COLUMNS.intersection(events.columns)
    assert (targets.trade_date < targets.entry_signal_date).all()


def test_five_minute_aggregation_conserves_volume_and_amount() -> None:
    frame = pd.DataFrame(
        {
            "open": np.arange(240, dtype=float) + 100.0,
            "high": np.arange(240, dtype=float) + 101.0,
            "low": np.arange(240, dtype=float) + 99.0,
            "close": np.arange(240, dtype=float) + 100.5,
            "volume": np.arange(240, dtype=float) + 1.0,
            "amount": (np.arange(240, dtype=float) + 1.0) * 100.0,
            "bar_end_time": pd.date_range("2020-01-02 09:31", periods=240, freq="1min"),
        }
    )
    result = audit.aggregate_5m(frame)
    assert len(result) == 48
    assert result.volume.sum() == frame.volume.sum()
    assert result.amount.sum() == frame.amount.sum()
    assert result.open.iloc[0] == frame.open.iloc[0]
    assert result.close.iloc[-1] == frame.close.iloc[-1]


def test_session_descriptors_are_finite_for_smooth_path() -> None:
    auction = pd.DataFrame(
        {
            "bar_end_time": [pd.Timestamp("2020-01-02 09:30")],
            "open": [100.0],
            "high": [100.0],
            "low": [100.0],
            "close": [100.0],
            "volume": [1000.0],
            "amount": [100000.0],
        }
    )
    close = np.linspace(100.01, 102.40, 240)
    continuous = pd.DataFrame(
        {
            "bar_end_time": pd.date_range("2020-01-02 09:31", periods=240, freq="1min"),
            "open": np.r_[100.0, close[:-1]],
            "high": close + 0.01,
            "low": np.r_[100.0, close[:-1]] - 0.01,
            "close": close,
            "volume": np.full(240, 1000.0),
            "amount": close * 1000.0,
        }
    )
    result = audit.session_descriptors(pd.concat([auction, continuous], ignore_index=True))
    assert set(result) == set(audit.DESCRIPTOR_COLUMNS)
    assert np.isfinite(np.array(list(result.values()), dtype=float)).all()
    assert result["open_close_log_return"] > 0
    assert result["signed_directional_efficiency"] > 0
    assert result["high_time_fraction"] == 1.0


def test_persisted_audit_result_passes_exact_contract() -> None:
    result = json.loads(audit.RESULT.read_text(encoding="utf-8"))
    coverage = result["coverage"]
    assert result["decision"] == "PASS_FIVE_DAY_MINUTE_DATA_AND_DESCRIPTOR_FEASIBILITY"
    assert result["outcome_access"] is False
    assert coverage["events"] == 399
    assert coverage["event_sessions"] == 1995
    assert coverage["raw_rows"] == 399 * 5 * 241
    assert coverage["descriptor_rows"] == 1995
    assert coverage["descriptor_count"] == 34
    assert result["reconciliation"]["maximum_relative_opening_window_difference"] == 0
    assert result["reconciliation"]["maximum_five_minute_conservation_difference"] == 0
    descriptors = pd.read_csv(audit.DESCRIPTORS)
    assert len(descriptors) == 1995
    assert not audit.FORBIDDEN_COLUMNS.intersection(descriptors.columns)
