from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RESEARCH = Path(__file__).resolve().parents[1]
ROOT = RESEARCH.parents[1]
sys.path.insert(0, str(RESEARCH))

from run_five_strategy_portfolio_v1 import (
    asof_trade_view,
    fixed_cost_stress,
    leave_cash,
    main,
    merge_one_to_one,
    portfolio_frame,
    prevent_false_segment_concat,
    reject_missing_metric,
    sha256,
    trade_profit,
)


def test_join_does_not_inflate_and_stages_remain_distinct() -> None:
    signals = pd.DataFrame({"event_id": ["a", "b"], "qualified": [True, True]})
    trades = pd.DataFrame({"event_id": ["a"], "executable": [True]})
    joined = merge_one_to_one(signals, trades, "event_id", "signals/trades")
    assert len(joined) == 2
    assert joined.executable.notna().sum() == 1
    with pytest.raises(ValueError, match="duplicate identity"):
        merge_one_to_one(signals, pd.concat([trades, trades]), "event_id", "bad")


def test_asof_missing_and_reset_guards() -> None:
    trades = pd.DataFrame(
        {
            "signal_date": pd.to_datetime(["2026-07-01", "2026-07-02"]),
            "exit_date": pd.to_datetime(["2026-07-20", "2026-08-10"]),
        }
    )
    exited, unresolved = asof_trade_view(trades, pd.Timestamp("2026-08-03"))
    assert len(exited) == len(unresolved) == 1
    assert np.isnan(reject_missing_metric(pd.DataFrame({"nav": [1.0]}), "utilization"))
    with pytest.raises(ValueError, match="cannot be concatenated"):
        prevent_false_segment_concat(
            [pd.DataFrame({"nav": [1]}), pd.DataFrame({"nav": [1]})], [False, True]
        )


def test_fixed_budget_delete_cash_replacement_and_drifted_exposure() -> None:
    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
    accounts = {
        "A": pd.DataFrame(
            {"nav": [1.0, 2.0, 2.0], "utilization": [1.0, 1.0, 0.5]}, index=dates
        ),
        "B": pd.DataFrame(
            {"nav": [1.0, 1.0, 2.0], "utilization": [0.0, 0.0, 1.0]}, index=dates
        ),
    }
    p = portfolio_frame(accounts, {"A": 0.5, "B": 0.5}, dates)
    assert p.nav.tolist() == [1.0, 1.5, 2.0]
    assert p.loc[dates[1], "drift_weight_A"] == pytest.approx(2 / 3)
    assert p.loc[dates[2], "utilization"] == pytest.approx(0.75)
    without_a = leave_cash(p, accounts["A"].nav, 0.5, accounts["A"].utilization)
    assert without_a.nav.tolist() == [1.0, 1.0, 1.5]
    replacement = portfolio_frame(accounts, {"A": 1.0}, dates)
    assert replacement.nav.tolist() == [1.0, 2.0, 2.0]


def test_ifcgr_counterfactual_is_parent_execution_not_money_sum(tmp_path: Path) -> None:
    root = tmp_path
    (root / "ifcgr").mkdir()
    (root / "ogr").mkdir()
    pd.DataFrame(
        {
            "gap_id": ["x", "y"],
            "symbol": ["1.SH", "2.SH"],
            "signal_date": pd.to_datetime(["2020-01-01", "2020-01-02"]),
            "v29r2_rejection_reason": ["RISK", "RISK"],
            "v29r2_open_risk_families": ["A", "B"],
        }
    ).to_parquet(root / "ifcgr/rejected.parquet")
    pd.DataFrame(
        {
            "gap_id": ["x", "y"],
            "entry_status": ["EXECUTABLE_ENTRY", "NO_NEXT_BUYABLE_OPEN"],
        }
    ).to_parquet(root / "ogr/entries.parquet")
    pd.DataFrame(
        {
            "gap_id": ["x"],
            "net_return": [-0.12],
            "holding_sessions": [3],
            "exit_reason": ["H20"],
        }
    ).to_parquet(root / "ogr/trades.parquet")
    from run_five_strategy_portfolio_v1 import reject_attribution

    result = reject_attribution(root)
    assert (
        result.set_index("gap_id").loc["x", "counterfactual"] == "AVOIDED_SEVERE_LOSS"
    )
    assert (
        result.set_index("gap_id").loc["y", "counterfactual"] == "PARENT_NOT_EXECUTABLE"
    )
    assert "profit_amount" not in result


def test_additional_cost_uses_actual_fill_notional_once() -> None:
    dates = pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"])
    account = pd.DataFrame(
        {"nav": [100.0, 110.0, 120.0], "cash": [100.0, 60.0, 120.0]}, index=dates
    )
    notionals = pd.DataFrame({"trade_date": dates[1:], "notional": [50.0, 60.0]})
    stressed, breaches = fixed_cost_stress(account, notionals, dates, extra_bps=20)
    assert stressed.iloc[-1] == pytest.approx(1.2 - (50 + 60) * 0.002 / 100)
    assert breaches == 0
    assert account.nav.iloc[-1] == 120.0


def test_realized_profit_uses_cash_and_ogr_distribution() -> None:
    stock = pd.DataFrame(
        {
            "entry_outlay": [100.0],
            "qty": [10.0],
            "exit_price": [11.0],
            "net_return": [999.0],
        }
    )
    assert trade_profit(stock).iloc[0] == pytest.approx(10 * 11 * 0.998 - 100)
    ogr = pd.DataFrame(
        {
            "entry_outlay": [100.0],
            "qty": [10.0],
            "exit_raw_price": [10.0],
            "cash_events_json": ['[{"cash_per_share": 0.5}]'],
            "net_return": [999.0],
        }
    )
    assert trade_profit(ogr).iloc[0] == pytest.approx(10 * (10 * 0.998 + 0.5) - 100)


def test_frozen_source_config_unchanged_and_smv6_is_local_cash_nav() -> None:
    config = json.loads((RESEARCH / "input_config.json").read_text())
    baseline = config["standalone_baseline"]
    subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            baseline,
            "--",
            "configs/frozen",
            "src/five_strategy_bundle",
        ],
        cwd=ROOT,
        check=True,
    )
    sealed = Path(config["sealed_output_root"])
    result = json.loads((sealed / "smv6/result.json").read_text())
    nav = pd.read_parquet(sealed / "smv6/nav.parquet", columns=["cash"])
    assert (
        result["status"]
        == "LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED"
    )
    assert result["native_platform_equivalence"] == "UNVERIFIED"
    assert nav.cash.min() >= 0


def test_same_inputs_repeat_core_outputs(tmp_path: Path) -> None:
    outputs = [tmp_path / "a", tmp_path / "b"]
    for output in outputs:
        assert (
            main(
                [
                    "--input-config",
                    str(RESEARCH / "input_config.json"),
                    "--output-root",
                    str(output),
                    "--signal-start",
                    "2018-01-01",
                    "--signal-end",
                    "2026-08-03",
                    "--as-of",
                    "2026-08-03",
                    "--stage",
                    "analysis",
                ]
            )
            == 0
        )
    for name in (
        "strategy_summary.csv",
        "family_analysis.csv",
        "ifcgr_reject_attribution.csv",
        "risk_and_capital.csv",
        "portfolio_comparison.csv",
        "profit_concentration.csv",
        "decision_matrix.csv",
    ):
        assert sha256(outputs[0] / name) == sha256(outputs[1] / name)
