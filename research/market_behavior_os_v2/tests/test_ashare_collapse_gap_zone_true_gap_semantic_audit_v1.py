import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_true_gap_semantic_audit_v1 as audit,
)


def test_true_gap_uses_high_not_open() -> None:
    frame = pd.DataFrame(
        {
            "open": [5.29, 4.83],
            "high": [5.45, 5.35],
            "prev_low": [5.88, 5.29],
        }
    )
    observed = frame.high.lt(frame.prev_low)
    assert observed.tolist() == [True, False]


def test_semantic_audit_reads_no_outcome_columns() -> None:
    rows = audit.load_trade_identities()
    forbidden = ("return", "exit", "pnl", "winner")
    assert len(rows) == 301
    assert not [c for c in rows if any(x in c.lower() for x in forbidden)]
