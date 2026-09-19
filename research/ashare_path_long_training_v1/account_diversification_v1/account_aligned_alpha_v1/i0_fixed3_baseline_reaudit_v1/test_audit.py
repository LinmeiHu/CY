from decimal import Decimal as D

import numpy as np
import pandas as pd
import pytest

from .audit import keyed_fixed3, load_replay_signal, percentile_by_date, stock_pnl_reconciliation


def seeds() -> dict[int, pd.DataFrame]:
    keys = pd.DataFrame({"t": [1, 1, 1, 2, 2], "j": [10, 11, 12, 10, 11]})
    return {s: keys.assign(score=np.array([1, 2, 2, 5, 4], float) + s / 1000) for s in (17, 29, 43)}


def test_keyed_fixed3_is_order_and_seed_order_invariant() -> None:
    original = seeds()
    expected = keyed_fixed3(original)
    shuffled = {seed: frame.sample(frac=1, random_state=seed) for seed, frame in reversed(original.items())}
    pd.testing.assert_frame_equal(expected, keyed_fixed3(shuffled))


def test_keyed_fixed3_rejects_missing_duplicate_and_wrong_keys() -> None:
    original = seeds()
    with pytest.raises(ValueError, match="EXACT_SEED_SET_REQUIRED"):
        keyed_fixed3({17: original[17], 29: original[29]})
    duplicate = {**original, 29: pd.concat([original[29], original[29].iloc[[0]]])}
    with pytest.raises(ValueError, match="DUPLICATE_KEYS"):
        keyed_fixed3(duplicate)
    wrong = {**original, 43: original[43].assign(j=[10, 11, 99, 10, 11])}
    with pytest.raises(ValueError, match="SEED_KEY_MISMATCH"):
        keyed_fixed3(wrong)


def test_average_tie_percentile_and_triplicate_identity() -> None:
    frame = pd.DataFrame({"t": [1, 1, 1], "j": [3, 1, 2], "raw": [5.0, 5.0, 1.0]})
    ranked = percentile_by_date(frame, "raw")
    assert ranked.score.tolist() == [5 / 6, 5 / 6, 1 / 3]
    one = ranked.rename(columns={"score": "score"})
    fixed = keyed_fixed3({17: one, 29: one, 43: one})
    assert np.array_equal(fixed.fixed3, fixed.score_s17)


def test_score_file_is_consumed_and_invalid_path_fails(tmp_path) -> None:
    gate = pd.DataFrame({"t": [1, 1], "j": [1, 2], "pred20": [.1, .1], "logamount20": [10.0, 10.0]})
    gate_path = tmp_path / "gate.parquet"; gate.to_parquet(gate_path, index=False)
    with pytest.raises(FileNotFoundError, match="SCORE_FILE_NOT_FOUND"):
        load_replay_signal(tmp_path / "missing.parquet", gate_path)
    a = tmp_path / "a.parquet"; b = tmp_path / "b.parquet"
    pd.DataFrame({"t": [1, 1], "j": [1, 2], "score": [2.0, 1.0]}).to_parquet(a, index=False)
    pd.DataFrame({"t": [1, 1], "j": [1, 2], "score": [1.0, 2.0]}).to_parquet(b, index=False)
    assert load_replay_signal(a, gate_path).sort_values(["score", "j"], ascending=[False, True]).j.tolist() == [1, 2]
    assert load_replay_signal(b, gate_path).sort_values(["score", "j"], ascending=[False, True]).j.tolist() == [2, 1]


def test_future_labels_are_not_an_input() -> None:
    base = pd.DataFrame({"t": [1, 1], "j": [1, 2], "raw": [0.3, -0.2], "Ret20": [1.0, 2.0]})
    changed = base.assign(Ret20=[-999.0, 999.0])
    pd.testing.assert_frame_equal(percentile_by_date(base, "raw"), percentile_by_date(changed, "raw"))


def test_stock_pnl_minimum_example_and_old_formula_counterexample() -> None:
    fills = pd.DataFrame([
        {"t": 1, "j": 1, "cash_delta": "-100"}, {"t": 2, "j": 1, "cash_delta": "110"},
        {"t": 1, "j": 2, "cash_delta": "-100"},
    ])
    cashflows = pd.DataFrame([
        {"t": 1, "j": 1, "kind": "BUY", "cash_delta": "-100"},
        {"t": 2, "j": 1, "kind": "SELL", "cash_delta": "110"},
        {"t": 1, "j": 2, "kind": "BUY", "cash_delta": "-100"},
    ])
    inventory = pd.DataFrame([{"t": 2, "j": 2, "value": "115"}])
    nav = pd.DataFrame([
        {"t": 0, "nav": "200", "receivable": "0", "tax_reserve": "0"},
        {"t": 2, "nav": "225", "receivable": "0", "tax_reserve": "0"},
    ])
    by_stock, summary = stock_pnl_reconciliation(fills, cashflows, inventory, nav, 1, 2)
    assert by_stock.set_index("j").stock_pnl.to_dict() == {1: "10", 2: "15"}
    assert summary["stock_pnl"] == "25" and summary["pass"]
    old_a = D("10") + D("10")
    old_b = D("-100") + D("-100") + D("115")
    assert old_a == D("20") and old_b == D("-85") and old_a + old_b == D("-65")


def test_stock_pnl_fees_partial_sale_dividend_receivable_tax_and_multilots() -> None:
    fills = pd.DataFrame([
        {"t": 1, "j": 7, "cash_delta": "-101"},
        {"t": 1, "j": 7, "cash_delta": "-51"},
        {"t": 2, "j": 7, "cash_delta": "79"},
    ])
    cashflows = pd.DataFrame([
        {"t": 1, "j": 7, "kind": "BUY", "cash_delta": "-152"},
        {"t": 2, "j": 7, "kind": "SELL", "cash_delta": "79"},
        {"t": 2, "j": 7, "kind": "DIVIDEND_PAYMENT", "cash_delta": "3"},
        {"t": 2, "j": 7, "kind": "DIVIDEND_TAX", "cash_delta": "-1"},
    ])
    inventory = pd.DataFrame([{"t": 0, "j": 7, "value": "0"}, {"t": 2, "j": 7, "value": "90"}])
    nav = pd.DataFrame([
        {"t": 0, "nav": "200", "receivable": "0", "tax_reserve": "0"},
        {"t": 2, "nav": "219", "receivable": "2", "tax_reserve": "2"},
    ])
    by_stock, summary = stock_pnl_reconciliation(fills, cashflows, inventory, nav, 1, 2)
    assert by_stock.iloc[0].stock_pnl == "19"
    assert summary["account_nonstock_total"] == "0"
    assert summary["nav_change_less_external"] == "19"
    assert summary["pass"]
