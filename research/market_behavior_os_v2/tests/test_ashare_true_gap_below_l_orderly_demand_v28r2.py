from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2 as subject,
)


def _fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-02", periods=21)
    entries = pd.DataFrame(
        {
            "gap_id": ["g1"],
            "symbol": ["000001.SZ"],
            "signal_date": [dates[-1]],
            "signal_time": [dates[-1] + pd.Timedelta(hours=15)],
        }
    )
    daily = pd.DataFrame(
        {
            "symbol": ["000001.SZ"] * 21,
            "trade_date": dates,
            "decision_at": dates + pd.Timedelta(hours=15),
            "amount": list(range(1, 21)) + [21.0],
            "trade_status": [1] * 21,
            "hard_valid": [True] * 21,
            "available_at": dates + pd.Timedelta(hours=15),
            "snapshot_id": [f"s{i}" for i in range(21)],
        }
    )
    return entries, daily


def test_orderly_amount_uses_strict_prior20_and_accepts_exact_boundary() -> None:
    entries, daily = _fixture()
    result = subject.attach_orderly_amount_feature(entries, daily).iloc[0]

    assert result.prior20_completed_trading_sessions == 20
    assert result.prior20_median_amount == 10.5
    assert result.signal_amount_to_prior20_median == 2.0
    assert bool(result.prior20_amount_history_complete)
    assert bool(result.v28r2_orderly_amount_gate)


def test_orderly_amount_fails_closed_for_bad_history_or_late_lineage() -> None:
    entries, daily = _fixture()

    missing = subject.attach_orderly_amount_feature(entries, daily.iloc[1:].copy()).iloc[0]
    assert missing.prior20_completed_trading_sessions == 19
    assert not bool(missing.v28r2_orderly_amount_gate)

    invalid = daily.copy()
    invalid.loc[4, "hard_valid"] = False
    invalid_result = subject.attach_orderly_amount_feature(entries, invalid).iloc[0]
    assert not bool(invalid_result.prior20_amount_history_complete)
    assert not bool(invalid_result.v28r2_orderly_amount_gate)

    late = daily.copy()
    late.loc[4, "available_at"] = entries.signal_time.iloc[0] + pd.Timedelta(seconds=1)
    late_result = subject.attach_orderly_amount_feature(entries, late).iloc[0]
    assert not bool(late_result.prior20_amount_history_complete)
    assert not bool(late_result.v28r2_orderly_amount_gate)

    late_signal = daily.copy()
    late_signal.loc[20, "available_at"] = entries.signal_time.iloc[0] + pd.Timedelta(seconds=1)
    signal_result = subject.attach_orderly_amount_feature(entries, late_signal).iloc[0]
    assert not bool(signal_result.signal_amount_state_hard_valid)
    assert not bool(signal_result.v28r2_orderly_amount_gate)

    missing_lineage = daily.copy()
    missing_lineage.loc[20, "snapshot_id"] = pd.NA
    lineage_result = subject.attach_orderly_amount_feature(entries, missing_lineage).iloc[0]
    assert not bool(lineage_result.signal_amount_state_hard_valid)
    assert not bool(lineage_result.v28r2_orderly_amount_gate)


def test_orderly_amount_rejects_above_two_and_unknown_session_state() -> None:
    entries, daily = _fixture()
    above = daily.copy()
    above.loc[20, "amount"] = 21.01
    above_result = subject.attach_orderly_amount_feature(entries, above).iloc[0]
    assert above_result.signal_amount_to_prior20_median > 2.0
    assert not bool(above_result.v28r2_orderly_amount_gate)

    unknown = pd.concat(
        [
            daily.iloc[:10],
            pd.DataFrame(
                {
                    "symbol": ["000001.SZ"],
                    "trade_date": [pd.Timestamp("2020-01-04")],
                    "decision_at": [pd.Timestamp("2020-01-04 15:00:00")],
                    "amount": [5.0],
                    "trade_status": [pd.NA],
                    "hard_valid": [False],
                    "available_at": [pd.Timestamp("2020-01-04 15:00:00")],
                    "snapshot_id": ["unknown"],
                }
            ),
            daily.iloc[10:],
        ],
        ignore_index=True,
    )
    unknown_result = subject.attach_orderly_amount_feature(entries, unknown).iloc[0]
    assert unknown_result.prior20_unknown_trading_state_rows == 1
    assert not bool(unknown_result.prior20_amount_history_complete)
    assert not bool(unknown_result.v28r2_orderly_amount_gate)
