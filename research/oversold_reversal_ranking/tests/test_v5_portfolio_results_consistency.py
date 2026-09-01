from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

LANE = Path(__file__).resolve().parents[1]
RESULTS = LANE / "reports" / "v5_portfolio_results.json"
REPORT = LANE / "reports" / "V5_PORTFOLIO_REPORT.md"
DAILY = LANE / "reports" / "v5_daily_nav.csv"


def _assert_finite(value: Any) -> None:
    if isinstance(value, float):
        assert math.isfinite(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_finite(item)
    elif isinstance(value, list):
        for item in value:
            _assert_finite(item)


def test_v5_cohort_causal_deployment_and_accounting_reconcile() -> None:
    payload = json.loads(RESULTS.read_text())
    _assert_finite(payload)
    assert payload["verdict"] == "EVENT_ALPHA_COLLAPSES"
    assert set(payload["v3_checks"].values()) == {0}
    assert all(
        item["content_hash_verified"]
        for item in payload["input_identities"]["data_files"]
    )
    sample = payload["sample_profile"]
    assert sample["events"] == 22_357
    assert sample["securities"] == 4_835
    assert sample["missing_scheduled_exit"] == 0
    assert sample["missing_legal_exit"] == 0
    causal = payload["causal_sizing_deployment"]
    assert sum(causal["causal_bucket_counts"].values()) == sample["events"]
    assert causal["warmup_events"] == 284
    assert causal["post_warmup"]["shifted_two_or_more_rate"] == 0.0

    for key, value in payload["checks"].items():
        if key.endswith("accounting_error") or key.endswith("nav_difference"):
            assert abs(value) <= 1e-12
        else:
            assert value == 0
    for policy in ("EQUAL_SIZE", "RISK_AWARE_SIZE"):
        for mode in ("GROSS", "BASE", "HIGH_COST"):
            key = f"{policy}:{mode}"
            flow = payload["signal_flow"][key]
            assert flow["signals"] == flow["entered"] == sample["events"]
            assert flow["overlapping_security_skips"] == 0
            assert flow["missed_for_zero_cash"] == 0
            assert payload["portfolio_metrics"][key]["minimum_cash"] >= 0.0


def test_daily_nav_reproduces_final_nav_and_core_metrics() -> None:
    payload = json.loads(RESULTS.read_text())
    rows = list(csv.DictReader(DAILY.open()))
    mapping = {
        "EQUAL_SIZE:GROSS": "equal_gross_nav",
        "EQUAL_SIZE:BASE": "equal_net_nav",
        "RISK_AWARE_SIZE:GROSS": "risk_aware_gross_nav",
        "RISK_AWARE_SIZE:BASE": "risk_aware_net_nav",
    }
    assert len(rows) == 1_597
    for key, column in mapping.items():
        values = np.asarray([float(row[column]) for row in rows], dtype=float)
        metrics = payload["portfolio_metrics"][key]
        assert math.isclose(values[-1], metrics["ending_nav"], abs_tol=1e-14)
        nav = np.asarray([1.0, *values], dtype=float)
        returns = nav[1:] / nav[:-1] - 1.0
        assert math.isclose(
            float(np.std(returns, ddof=1) * math.sqrt(252.0)),
            metrics["annualized_volatility"],
            abs_tol=1e-14,
        )
        drawdown = nav / np.maximum.accumulate(nav) - 1.0
        assert math.isclose(
            float(np.min(drawdown)), metrics["max_drawdown"], abs_tol=1e-14
        )


def test_v5_economic_decomposition_and_report_agree() -> None:
    payload = json.loads(RESULTS.read_text())
    decomposition = payload["alpha_collapse_decomposition"]
    assert decomposition["v5_executable_event_equal_mean_return"] > 0.04
    assert decomposition["entry_date_equal_mean_cross_sectional_return"] < 0.003
    assert decomposition["events_on_days_with_more_than_20_signals_rate"] > 0.70
    assert decomposition["overlapping_security_skips"] == 0
    assert decomposition["missed_for_zero_cash"] == 0
    bridge = payload["v4_executable_bridge"]
    assert bridge["entered_events"] == 22_357
    assert bridge["return_correlation"] > 0.99
    assert abs(bridge["mean_return_difference"]) < 0.001

    equal = payload["portfolio_metrics"]["EQUAL_SIZE:BASE"]
    risk = payload["portfolio_metrics"]["RISK_AWARE_SIZE:BASE"]
    assert equal["ending_nav"] < 1.0
    assert risk["ending_nav"] < equal["ending_nav"]
    assert risk["max_drawdown"] < equal["max_drawdown"]
    assert payload["transaction_cost_attribution"]["EQUAL_SIZE"][
        "stress_ending_nav"
    ] < equal["ending_nav"]

    report = REPORT.read_text()
    assert "`EVENT_ALPHA_COLLAPSES`" in report
    assert f"{payload['sample_profile']['events']:,} across 4,835 securities" in report
    assert "Ending NAV | 0.8653 | 0.8591" in report
    assert report.count("## SINGLE NEXT STEP") == 1
    required = {
        "## ENVIRONMENT",
        "## PREDECESSOR FINDINGS",
        "## FROZEN STRATEGY CONTRACT",
        "## CAUSAL SIZING DEPLOYMENT",
        "## PORTFOLIO ENGINE",
        "## COHORT / SIGNAL FLOW",
        "## EQUAL SIZE PORTFOLIO",
        "## RISK-AWARE PORTFOLIO",
        "## PRIMARY COMPARISON",
        "## CAPITAL COMPETITION",
        "## TRANSACTION COSTS",
        "## YEARLY RESULTS",
        "## TIME BLOCKS",
        "## DRAWDOWN EPISODES",
        "## EXPOSURE / CASH",
        "## RISK-AWARE CAPITAL ATTRIBUTION",
        "## CONCENTRATION",
        "## V4 BRIDGE",
        "## LIMITATIONS",
        "## ECONOMIC INTERPRETATION",
        "## VERDICT",
    }
    assert required.issubset(set(report.splitlines()))
