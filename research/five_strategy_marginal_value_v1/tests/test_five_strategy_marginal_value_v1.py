import importlib.util
from pathlib import Path

import pandas as pd


MODULE = Path(__file__).parents[1] / "run_five_strategy_marginal_value_v1.py"
spec = importlib.util.spec_from_file_location("five", MODULE); five = importlib.util.module_from_spec(spec); spec.loader.exec_module(five)


def test_fixed_initial_weight_and_cash_removal():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    navs = {name: pd.DataFrame({"date": dates, "nav": [1.0, value]}) for name, value in {"A": 1.2, "B": .8, "C": 1.0}.items()}
    assert five.composite(navs, ["A", "B", "C"]).nav.iloc[-1] == 1.0
    assert five.composite(navs, ["A", "B"]).nav.iloc[-1] == 1.0


def test_metric_does_not_fill_missing_nav():
    nav = pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-04"]), "nav": [1.0, 1.1]})
    assert five.metric(nav)["days"] == 2


def test_cash_removal_keeps_original_window():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    navs = {
        "A": pd.DataFrame({"date": dates, "nav": [1.0, 1.2]}),
        "B": pd.DataFrame({"date": dates, "nav": [1.0, .8]}),
        "C": pd.DataFrame({"date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]), "nav": [1.0, 1.0, 2.0]}),
    }
    removed = five.composite(navs, ["A", "B"], window_members=["A", "B", "C"])
    assert len(removed) == 2
    assert removed.nav.iloc[-1] == 1.0


def test_board_sleeves_are_not_dropped(tmp_path, monkeypatch):
    path = tmp_path / "nav.parquet"
    import duckdb
    duckdb.sql("select * from (values (date '2024-01-02', .5), (date '2024-01-02', .5)) t(trade_date, nav)").write_parquet(str(path))
    monkeypatch.setitem(five.SOURCES, "TEST", {"nav": str(path), "nav_col": "nav", "cash_col": None, "gross_col": None, "date_col": "trade_date"})
    assert five.load_nav("TEST", pd.Timestamp("2024-01-02")).nav.iloc[0] == 1.0
