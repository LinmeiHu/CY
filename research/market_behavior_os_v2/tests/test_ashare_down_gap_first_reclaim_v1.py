from __future__ import annotations

import json

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts.run_ashare_down_gap_first_reclaim_v1 import (
    OS_ROOT,
    classify_gap_age,
    collapse_trades,
    ratio_bin,
    return_summary,
)


def test_frozen_descriptive_bins_are_exact() -> None:
    ratios = pd.Series([0.30, 0.31, 0.50, 0.51, 0.70, 0.71, 1.00, 1.01])
    assert list(ratio_bin(ratios).astype(str)) == [
        "<=0.30",
        "(0.30,0.50]",
        "(0.30,0.50]",
        "(0.50,0.70]",
        "(0.50,0.70]",
        "(0.70,1.00]",
        "(0.70,1.00]",
        ">1.00",
    ]
    ages = pd.Series([0, 1, 3, 4, 10, 11, 20, 21, 60, 61, 120, 121])
    assert list(classify_gap_age(ages).astype(str)) == [
        "same day",
        "1-3",
        "1-3",
        "4-10",
        "4-10",
        "11-20",
        "11-20",
        "21-60",
        "21-60",
        "61-120",
        "61-120",
        ">120",
    ]


def test_simultaneous_gaps_collapse_without_future_return_choice() -> None:
    timestamp = pd.Timestamp("2020-02-03 10:17:00")
    rows = pd.DataFrame(
        {
            "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "bar_end_time": [timestamp, timestamp, timestamp],
            "entry_price": [9.90, 9.80, 8.00],
            "gap_id": ["newer", "older", "other"],
            "execution_valid": [True, True, True],
            "reclaim_date": [timestamp.normalize()] * 3,
        }
    )
    collapsed = collapse_trades(rows)
    first = collapsed.loc[collapsed.symbol.eq("000001.SZ")].iloc[0]
    assert len(collapsed) == 2
    assert first.entry_price == 9.80
    assert first.underlying_gap_count == 2
    assert first.underlying_gap_ids == "older|newer"


def test_return_summary_preserves_tail_and_severe_loss() -> None:
    frame = pd.DataFrame(
        {
            "t1_open_gross": [0.01, -0.11, 0.02],
            "t1_open_net": [0.006, -0.114, 0.016],
        }
    )
    result = return_summary(frame, "t1_open")
    assert result["n"] == 3
    assert np.isclose(result["gross_mean"], -0.08 / 3)
    assert np.isclose(result["severe_loss10"], 1 / 3)


def test_completed_result_is_sealed_and_hard_invariants_hold() -> None:
    path = OS_ROOT / "artifacts/ASHARE-DOWN-GAP-FIRST-RECLAIM-V1_result.json"
    if not path.is_file():
        return
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["chronology"]["validation_opened"] is False
    assert result["chronology"]["final_oos_opened"] is False
    assert result["chronology"]["max_evaluation_outcome_date"] <= "2021-12-31"
    for key in (
        "gap_ids_with_more_than_one_first_reclaim",
        "post_first_reclaim_reuse_count",
        "future_volume_leakage_count",
        "post_trigger_volume_used_in_dryup_count",
        "post_2021_outcome_read_count",
        "illegal_execution_count",
    ):
        assert result["invariants"][key] == 0
    assert result["invariants"]["contract_invalidating_action_crossings"] > 0
    assert result["verdict"] in {
        "FIRST_RECLAIM_EDGE_WITH_DRYUP_SUPPORT",
        "FIRST_RECLAIM_EDGE_BUT_DRYUP_NOT_INCREMENTAL",
        "DRYUP_CONDITIONAL_EDGE_ONLY",
        "OUTLIER_OR_CLUSTER_DRIVEN",
        "BELOW_COST",
        "NO_FIRST_RECLAIM_EDGE",
        "IMPLEMENTATION_BLOCKED",
    }
