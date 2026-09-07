import pandas as pd

from five_strategy_bundle.strategies.ogr import replay_portfolio


def test_ogr_replay_accepts_explicit_later_account_window():
    outcomes = pd.DataFrame([
        {
            "gap_id": f"{board}-G", "symbol": symbol, "board": board,
            "entry_date": pd.Timestamp("2022-01-04"), "entry_time": pd.Timestamp("2022-01-04 09:31"),
            "entry_raw_price": 10.0, "target_coordinate": 10.5, "entry_coordinate_price": 10.0,
            "exit_date": pd.Timestamp("2022-01-05"), "exit_time": pd.Timestamp("2022-01-05 09:31"),
            "exit_raw_price": 10.5, "exit_reason": "PRE_L_TARGET", "cash_events_json": "[]",
            "pre_gap_inside_density_relative_local": 0.5,
        }
        for board, symbol in (("MAIN", "600001.SH"), ("CHINEXT", "300001.SZ"))
    ])
    daily = pd.DataFrame([
        {"symbol": symbol, "trade_date": date, "cal_idx": offset, "close": price}
        for symbol in ("600001.SH", "300001.SZ")
        for offset, (date, price) in enumerate(
            ((pd.Timestamp("2022-01-03"), 10.0), (pd.Timestamp("2022-01-04"), 10.0), (pd.Timestamp("2022-01-05"), 10.5)),
            start=1,
        )
    ])
    accepted, _, nav = replay_portfolio(
        outcomes, daily, account_start="2022-01-03", account_end="2022-01-05",
    )
    combined = nav.loc[nav.board.eq("COMBINED")]
    assert len(accepted) == 2
    assert combined.trade_date.min() == pd.Timestamp("2022-01-03")
    assert combined.trade_date.max() == pd.Timestamp("2022-01-05")
