import pandas as pd

from five_strategy_bundle.strategies.mcb import build_v72


def test_cross_board_is_same_completed_close(tmp_path):
    close = pd.Timestamp("2020-01-02 15:00:00")
    rows = []
    for event, sleeve, symbol in (("A", "MAIN", "600001.SH"), ("B", "CHINEXT", "300001.SZ")):
        rows.append({"event_id": event, "source_event_id": event + "0", "signal_date": close.normalize(), "decision_at": close, "sleeve": sleeve, "symbol": symbol, "causal_industry": "X"})
    rows.append({"event_id": "C", "source_event_id": "C0", "signal_date": pd.Timestamp("2020-01-03"), "decision_at": pd.Timestamp("2020-01-03 15:00"), "sleeve": "MAIN", "symbol": "600002.SH", "causal_industry": "Y"})
    result = build_v72(pd.DataFrame(rows), tmp_path / "signals.parquet")
    assert set(result.v65_event_id) == {"A", "B"}
    assert result.cross_board_confirmation.all()
    assert result.cross_board_state_known_at.eq(close).all()
