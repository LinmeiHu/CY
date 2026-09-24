"""Minimal contract check for the public-trades minute conversion."""

import pandas as pd

from recover_public_minutes import minute_bars


def test_auction_labels() -> None:
    trades = pd.DataFrame({
        "ticker": ["600363", "600363", "600363"],
        "time_s": [33900, 34201, 54030],
        "tran_id": [1, 2, 3],
        "price_x10000": [100000, 101000, 102000],
        "volume": [100, 200, 300],
    })
    bars = minute_bars(trades, "2026-08-26", "600363")
    assert len(bars) == 241
    assert bars.loc[bars.bar_end_time.dt.strftime("%H:%M").eq("09:30"), "volume"].item() == 100
    assert bars.loc[bars.bar_end_time.dt.strftime("%H:%M").eq("09:31"), "volume"].item() == 200
    assert bars.loc[bars.bar_end_time.dt.strftime("%H:%M").eq("15:00"), "volume"].item() == 300
    assert bars.volume.sum() == 600


if __name__ == "__main__":
    test_auction_labels()
