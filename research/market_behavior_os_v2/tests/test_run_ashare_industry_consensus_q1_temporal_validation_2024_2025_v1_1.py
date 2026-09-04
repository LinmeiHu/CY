from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
EXPERIMENT_ID = (
    "ASHARE-INDUSTRY-CONSENSUS-Q1-TEMPORAL-VALIDATION-2024-2025-V1_1"
)
SCRIPT = PROGRAM / (
    "scripts/"
    "run_ashare_industry_consensus_q1_temporal_validation_2024_2025_v1.py"
)
SPEC = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
RESULT = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
EQUITY = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
TRADES = PROGRAM / f"artifacts/{EXPERIMENT_ID}_trades.csv"
SELECTION = PROGRAM / f"artifacts/{EXPERIMENT_ID}_selection.csv"
INITIAL_CAPITAL = 10_000_000.0


def _module():
    module_spec = importlib.util.spec_from_file_location(
        "industry_consensus_q1_temporal_validation_v1_1_test", SCRIPT
    )
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_numeric_erratum_is_frozen_and_economically_neutral() -> None:
    module = _module()
    spec = _read_json(SPEC)
    merged = module._load_spec()

    assert _sha256(SPEC) == module.EXPECTED_SPEC_SHA256
    assert spec["status"] == (
        "FROZEN_NUMERIC_ERRATUM_BEFORE_ANY_2024_2025_STRATEGY_OUTCOME_AGGREGATION"
    )
    assert spec["initial_contract_failure"]["accepted_2024_2025_portfolio_outcome"] is False
    assert merged["numerical_erratum"]["epsilon"] == module.R20_POSITIVE_EPSILON == 1e-12
    assert _sha256(ROOT / spec["base_contract"]["path"]) == spec["base_contract"]["sha256"]

    frame = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2023-01-03"] * 4),
            "industry": ["I"] * 4,
            "r20": [-5e-13, 5e-13, 2e-12, -0.1],
            "diffusion_score": [99.0] * 4,
        }
    )
    corrected = module._canonicalize_diffusion(frame)
    assert np.allclose(corrected.diffusion_score, [1 / 3, 1 / 3, 0.0, 1 / 3])


def test_temporal_result_preserves_authorized_outcome_boundary() -> None:
    result = _read_json(RESULT)

    assert result["classification"] == "TEMPORAL_TRANSFER_INCONCLUSIVE"
    assert result["post_2023_outcome_read"] == "YES_AUTHORIZED_2024_2025_ONLY"
    assert result["maximum_market_outcome_date"] == "2025-12-31"
    assert result["market_2026_outcome_read"] == "NO"
    assert result["cy011_read"] == "NO"
    assert result["feature_replication_gate"]["status"] == "PASS"
    assert result["selection_replication_gate"]["status"] == "PASS"
    assert result["selection_replication_gate"]["selection_sha256"] == (
        "98e7ef4229b688bbc3dbb9f30bc6008cc8729d92541f847a54248d1c6f69e3bc"
    )
    assert [item["year"] for item in result["input_identity"]["partitions"]] == list(
        range(2018, 2026)
    )
    assert result["input_identity"]["market_2026_partition_read"] == "NO"
    assert result["primary_confirmation_checks"]["daily_sharpe"] is False
    assert result["primary_confirmation_checks"]["positive_calendar_years"] is False
    assert result["mixed_transfer_checks"]["entry_execution"] is False


def test_nav_trade_and_year_metrics_recompute() -> None:
    result = _read_json(RESULT)
    candidate = result["candidate"]
    equity = pd.read_csv(EQUITY, parse_dates=["trade_date"])
    trades = pd.read_csv(TRADES, parse_dates=["exit_date"])
    selection = pd.read_csv(SELECTION, parse_dates=["signal_date"])

    nav = equity.nav.to_numpy(float)
    returns = np.empty(len(nav), dtype=float)
    returns[0] = nav[0] / INITIAL_CAPITAL - 1.0
    returns[1:] = nav[1:] / nav[:-1] - 1.0
    peaks = np.maximum.accumulate(np.concatenate(([INITIAL_CAPITAL], nav)))[1:]
    total = float(nav[-1] / INITIAL_CAPITAL - 1.0)
    annualized = float((1.0 + total) ** (252.0 / len(nav)) - 1.0)
    maximum_drawdown = float((nav / peaks - 1.0).min())
    sharpe = float(math.sqrt(252.0) * returns.mean() / returns.std(ddof=1))

    assert abs(total - candidate["total_return"]) < 5e-11
    assert abs(annualized - candidate["annualized_return"]) < 5e-11
    assert abs(maximum_drawdown - candidate["maximum_drawdown"]) < 5e-11
    assert abs(sharpe - candidate["daily_sharpe"]) < 5e-11
    assert candidate["event_dates"] == selection.signal_date.nunique() == 50
    assert candidate["entries"] == candidate["completed_trades"] == len(trades) == 84
    assert candidate["planned_entries"] == len(selection) == 100
    assert candidate["terminal_open_lots"] == 0
    assert equity.positions.iloc[-1] == 0
    assert equity.cash.iloc[-1] == equity.nav.iloc[-1]
    assert equity.trade_date.min().date().isoformat() == "2024-01-02"
    assert equity.trade_date.max().date().isoformat() == "2025-12-31"
    assert trades.exit_date.max().date().isoformat() <= "2025-12-31"

    prior_nav = INITIAL_CAPITAL
    for year in (2024, 2025):
        year_equity = equity.loc[equity.trade_date.dt.year.eq(year)]
        year_total = float(year_equity.nav.iloc[-1] / prior_nav - 1.0)
        assert abs(year_total - result["calendar_years"][str(year)]["total_return"]) < 5e-11
        prior_nav = float(year_equity.nav.iloc[-1])

    for name, path in (
        ("equity", EQUITY),
        ("trades", TRADES),
        ("selection", SELECTION),
    ):
        assert _sha256(path) == result["hashes"][f"{name}_sha256"]
