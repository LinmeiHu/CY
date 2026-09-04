from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_ashare_bull_quiet_inventory_industry_acceptance_v1.py"
)
SPEC = importlib.util.spec_from_file_location("bull_quiet_inventory_v1", RUNNER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_contract_is_bull_only_short_horizon_and_not_gap_repair() -> None:
    contract = MODULE.contract_value()
    assert contract["market_regime"]["strategy_action"].startswith("trade only BULL")
    assert tuple(contract["bounded_translations"])[:2] == MODULE.PROFILES
    assert contract["required_gate"]["mean_holding_sessions_max"] == 15
    assert contract["governance"]["no_same_bar_fill"] is True
    assert "No downward gap" in contract["independence"]


def test_rule_family_is_nested_and_missing_values_fail_closed() -> None:
    frame = pd.DataFrame(
        {
            "market_regime": ["BULL", "BULL", "BULL", "BEAR", None],
            "industry_n20": [20, 20, 20, 20, None],
            "industry_median_ret20": [0.01, 0.01, -0.01, 0.01, None],
            "industry_positive_ret20_share": [0.60, 0.40, 0.60, 0.60, None],
            "stock_minus_industry_ret20": [0.02, 0.02, 0.02, 0.02, None],
        }
    )
    masks = {rule: MODULE.rule_mask(frame, rule) for rule in MODULE.RULES}
    assert masks["BULL_ONLY"].tolist() == [True, True, True, False, False]
    assert masks["BULL_INDUSTRY_POSITIVE"].tolist() == [True, True, False, False, False]
    assert masks["BULL_INDUSTRY_MAJORITY"].tolist() == [True, False, False, False, False]
    assert masks["BULL_INDUSTRY_LEADER"].tolist() == [True, False, False, False, False]
    for less_restrictive, more_restrictive in zip(MODULE.RULES[:-1], MODULE.RULES[1:], strict=True):
        assert not (masks[more_restrictive] & ~masks[less_restrictive]).any()


def test_execution_state_fails_closed_on_unknown_lineage_or_status() -> None:
    row = pd.Series(
        {
            "hard_valid": True,
            "history_valid": True,
            "current_valid": True,
            "corporate_action_valid": True,
            "corporate_action_blocking": False,
            "current_day_data_tradable": True,
            "market_rule_valid": True,
            "trade_status": 1,
            "invalid_step_cum": 2.0,
            "open": 10.0,
            "up_limit_price": 11.0,
            "down_limit_price": 9.0,
        }
    )
    assert MODULE.legal_state(row, 2.0)
    assert MODULE.legal_buy(row, 2.0)
    assert MODULE.legal_sell_open(row, 2.0)
    for field in ("hard_valid", "trade_status", "invalid_step_cum"):
        broken = row.copy()
        broken[field] = pd.NA
        assert not MODULE.legal_state(broken, 2.0)


def test_discovery_selector_cannot_use_confirmation_or_diagnostic_columns() -> None:
    table = pd.DataFrame(
        [
            {
                "rule": "BULL_ONLY",
                "profile": "H10_NEXT_OPEN",
                "completed_trades": 300,
                "positive_years": 4,
                "mean_holding_sessions": 11.0,
                "median_annual_mean_net": 0.02,
                "mean_net": 0.021,
            },
            {
                "rule": "BULL_INDUSTRY_POSITIVE",
                "profile": "T10_H20_NO_STOP",
                "completed_trades": 280,
                "positive_years": 4,
                "mean_holding_sessions": 14.0,
                "median_annual_mean_net": 0.03,
                "mean_net": 0.028,
            },
        ]
    )
    selected = MODULE.select_candidate(table)
    assert selected.rule == "BULL_INDUSTRY_POSITIVE"
    assert selected.profile == "T10_H20_NO_STOP"
