from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_evidence_depth_cycle_010.py"
SPEC = ROOT / "research/market_behavior_os_v2/experiments/ASHARE-EVIDENCE-DEPTH-CYCLE-010_spec.json"


def _module():
    spec = importlib.util.spec_from_file_location("cycle010_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_frozen_spec_and_fail_closed_ivol_contract() -> None:
    module = _module()
    frozen = module._load_spec()
    assert module.sha256_file(SPEC) == module.EXPECTED_SPEC_SHA256
    assert frozen["low_risk"]["canonical_ivol"] == "CANONICAL_IVOL_DATA_LIMITED"
    assert frozen["optional_third_family"] == "NOT_AUTHORIZED_EXACT_METHOD_NOT_RECOVERED"


def test_consecutive_limit_run_excludes_run_and_first_following_session() -> None:
    module = _module()
    flags = pd.Series([False, True, True, False, False])
    assert module._revised_exclusion_contract(flags).tolist() == [False, True, True, True, False]


def test_extreme_legs_are_disjoint_and_source_oriented() -> None:
    module = _module()
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2020-01-31").date()] * 10,
            "symbol": [f"{value:06d}.SZ" for value in range(10)],
            "score": list(range(10)),
        }
    )
    low, high = module._extreme_legs(
        frame,
        "test",
        "score",
        5,
        "track",
        {"design": "test", "variant": "source", "formation_sessions": 20},
    )
    assert low.signal_score.tolist() == [0, 1]
    assert high.signal_score.tolist() == [9, 8]
    assert set(low.symbol).isdisjoint(set(high.symbol))


def test_summary_compares_stock_tail_rate_with_control_stock_tail_rate() -> None:
    module = _module()
    common = {
        "trade_date": pd.Timestamp("2019-01-31"),
        "status_h20": "COMPLETE",
        "gross_return_h20": 0.0,
        "entry_status": "EXECUTABLE",
        "candidate_count": 2,
        "avg_amount20": 100_000_000.0,
        "entry_amount_h20": 100_000_000.0,
    }
    panel = pd.DataFrame(
        [
            {**common, "family": "date_control", "net_return_h20": -0.20},
            {**common, "family": "date_control", "net_return_h20": 0.10},
            {
                **common,
                "family": "test_high",
                "track": "test",
                "leg": "high",
                "design": "test",
                "variant": "test",
                "formation_sessions": 20,
                "net_return_h20": -0.15,
            },
            {
                **common,
                "family": "test_high",
                "track": "test",
                "leg": "high",
                "design": "test",
                "variant": "test",
                "formation_sessions": 20,
                "net_return_h20": 0.05,
            },
        ]
    )
    row = module._summary(panel).iloc[0]
    assert row.control_severe_loss_fraction == 0.5
    assert row.severe_loss_fraction == 0.5
    assert row.severe_loss_disadvantage == 0.0
