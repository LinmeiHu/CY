from __future__ import annotations

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_v26_v27_union_v1 as subject,
)


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "gap_id": "A",
        "symbol": "000001.SZ",
        "signal_time": pd.Timestamp("2023-01-02 15:00"),
        "gap_width_pct": 0.03,
        "pre_gap_corridor_touch_sessions": 10,
        "gap_age": 14,
        "max_depth": 0.16,
        "current_depth": 0.11,
        "pre_peak_to_gap_sessions": 20,
    }
    row.update(overrides)
    return row


def test_union_is_or_not_and() -> None:
    frame = pd.DataFrame(
        [
            _row(gap_id="V26", gap_age=30),
            _row(gap_id="V27", gap_width_pct=0.04, pre_gap_corridor_touch_sessions=12),
            _row(gap_id="BOTH"),
        ]
    )
    frame["entry_status"] = "NO_NEXT_BUYABLE_OPEN"
    union = subject.canonical_union(frame.iloc[[0, 2]], frame.iloc[[1, 2]])
    assert set(union.gap_id) == {"V26", "V27", "BOTH"}
    assert union.set_index("gap_id").loc["BOTH", "union_source"] == "BOTH"
    assert union.union_admission_pass.all()


def test_condition_ledger_separates_signal_entry_and_outcome_time() -> None:
    ledger = {item["condition"]: item for item in subject.condition_ledger()}
    assert ledger["TRUE_GAP"]["known_by_signal"] is True
    assert ledger["NEXT_LEGAL_MINUTE_OPEN_AND_HEADROOM"]["known_by_entry"] is True
    assert ledger["A67_TARGET_H20_T1"]["outcome_only"] is True


def test_contract_has_no_branch_priority_or_extra_capital() -> None:
    contract = subject.contract_value()
    assert contract["union"]["operator"] == "OR"
    assert contract["union"]["priority_between_branches"] == "NONE"
    assert contract["execution"]["portfolio"].endswith("one active symbol")
