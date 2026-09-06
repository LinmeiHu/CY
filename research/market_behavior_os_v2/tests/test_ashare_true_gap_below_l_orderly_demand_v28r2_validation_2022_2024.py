from __future__ import annotations

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024 as subject,
)


def test_development_payload_requires_passed_frozen_selector() -> None:
    freeze = {
        "experiment": subject.v28r2.EXPERIMENT,
        "stage": "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        "contract_sha256": "c",
        "spec_sha256": "s",
        "runner_sha256": "r",
    }
    result = {
        "experiment": subject.v28r2.EXPERIMENT,
        "selector_passed": True,
        "goal_checks": {"a": True, "b": True},
        "post_2021_entries_or_outcomes_opened": "NO",
        "diagnostic_authorization_created": "NO",
        "stage_a_verification": {
            "checks": {"contract_sha256": "c", "spec_sha256": "s", "runner_sha256": "r"}
        },
    }
    subject._assert_development_payload(freeze, result)

    failed = result | {"selector_passed": False}
    with pytest.raises(subject.V28R2ValidationError, match="did not pass"):
        subject._assert_development_payload(freeze, failed)


def _outcome_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = pd.DataFrame(
        {
            "gap_id": ["g1", "g2"],
            "entry_status": ["EXECUTABLE_ENTRY", "NO_LEGAL_ENTRY"],
        }
    )
    source = pd.DataFrame(
        {
            "gap_id": ["g1"],
            "signal_date": ["2024-06-03"],
            "signal_time": ["2024-06-03 15:00:00"],
            "entry_date": ["2024-06-04"],
            "entry_time": ["2024-06-04 09:31:00"],
            "exit_date": ["2024-06-20"],
            "exit_time": ["2024-06-20 10:00:00"],
            "alpha": [0.67],
            "horizon": [20],
            "stop": ["NONE"],
            "entry_at_or_before_signal": [False],
            "buy_at_or_above_up_limit": [False],
        }
    )
    return selected, source


def test_frozen_outcome_identity_preserves_t1_and_rejects_future() -> None:
    selected, source = _outcome_fixture()
    result = subject.select_frozen_outcomes(selected, source)
    assert result.gap_id.tolist() == ["g1"]

    future = source.copy()
    future.loc[0, "exit_date"] = "2025-01-02"
    future.loc[0, "exit_time"] = "2025-01-02 10:00:00"
    with pytest.raises(subject.V28R2ValidationError, match="post-2024"):
        subject.select_frozen_outcomes(selected, future)

    same_bar = source.copy()
    same_bar.loc[0, "entry_time"] = same_bar.loc[0, "signal_time"]
    with pytest.raises(subject.V28R2ValidationError, match=r"T\+1"):
        subject.select_frozen_outcomes(selected, same_bar)


def test_detailed_summary_reports_years_and_tail() -> None:
    accepted = pd.DataFrame(
        {
            "gap_id": ["a", "b", "c"],
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "signal_date": pd.to_datetime(["2022-01-03", "2022-02-03", "2024-03-04"]),
            "entry_date": pd.to_datetime(["2022-01-04", "2022-02-04", "2024-03-05"]),
            "net_return": [0.10, -0.12, 0.05],
            "holding_sessions": [5, 10, 3],
            "exit_reason": ["PRE_L_TARGET", "H20_TIME_STOP", "PRE_L_TARGET"],
        }
    )
    summary = subject.detailed_summary(accepted, subject.VALIDATION_YEARS)

    assert summary["overall"]["trades"] == 3
    assert summary["overall"]["severe10"] == pytest.approx(1 / 3)
    assert summary["overall"]["cvar5"] == pytest.approx(-0.12)
    assert summary["yearly_by_signal_year"]["2023"]["trades"] == 0
    assert summary["yearly_by_signal_year"]["2024"]["target_hit"] == 1.0
