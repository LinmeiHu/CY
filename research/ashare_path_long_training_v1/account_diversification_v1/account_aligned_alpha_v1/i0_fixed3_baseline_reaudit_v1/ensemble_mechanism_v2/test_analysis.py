import pandas as pd

from .run_analysis import add_rank, correlation, label_metrics


def test_rank_is_keyed_and_ties_break_by_j() -> None:
    frame = pd.DataFrame({"t": [1, 1, 1, 2], "j": [3, 1, 2, 1], "score": [0.9, 0.9, 0.8, 0.1]})
    add_rank(frame, "score", "rank")
    assert frame.set_index(["t", "j"])["rank"].to_dict() == {(1, 1): 1, (1, 3): 2, (1, 2): 3, (2, 1): 1}


def test_label_metrics_select_then_report_coverage() -> None:
    frame = pd.DataFrame({"ret10": [0.1, None, -0.2], "ret20": [0.2, 0.3, None]})
    rows = label_metrics(frame, {"bucket": "C0"})
    assert rows[0]["selected"] == 3 and rows[0]["coverage"] == 2
    assert rows[0]["large_loss_frequency"] == 0.5


def test_correlation_fails_closed_for_tiny_or_constant_group() -> None:
    assert pd.isna(correlation(pd.Series([1.0]), pd.Series([2.0])))
    assert pd.isna(correlation(pd.Series([1.0, 1.0]), pd.Series([2.0, 3.0])))
