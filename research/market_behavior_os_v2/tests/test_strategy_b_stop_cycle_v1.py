from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"

EXPERIMENTS = {
    "ASHARE-PANIC-LIQUID-BASKET-REVERSAL-V1": (
        "VALIDATION_REJECTED_NO_FULL_REPLAY"
    ),
    "ASHARE-LIQUIDITY-ACTIVITY-LIQUID-BASKET-V1": (
        "GENERATION_REJECTED_VALIDATION_UNOPENED"
    ),
    "ASHARE-NEW-HIGH-LOW-EXHAUSTION-LIQUID-BASKET-V1": (
        "VALIDATION_REJECTED_NO_FULL_REPLAY"
    ),
    "ASHARE-POST-DISTRIBUTION-DRIFT-V1": (
        "GENERATION_REJECTED_VALIDATION_UNOPENED"
    ),
    "ASHARE-CASH-DIVIDEND-CAPTURE-V1": (
        "GENERATION_REJECTED_VALIDATION_UNOPENED"
    ),
    "ASHARE-INDUSTRY-CONSENSUS-Q1-RECURRENCE-V1": (
        "GENERATION_REJECTED_VALIDATION_UNOPENED"
    ),
    "ASHARE-SIX-INDEX-TREND-LIQUID-BASKET-V1": (
        "GENERATION_REJECTED_VALIDATION_UNOPENED"
    ),
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result(experiment_id: str) -> dict:
    return _read_json(PROGRAM / "artifacts" / f"{experiment_id}_result.json")


def test_frozen_specs_results_and_quarantine_contracts() -> None:
    for experiment_id, expected_status in EXPERIMENTS.items():
        spec_path = PROGRAM / "experiments" / f"{experiment_id}_spec.json"
        result = _result(experiment_id)
        spec = _read_json(spec_path)

        assert result["status"] == expected_status
        assert result["full_replay_opened"] is False
        assert result["post_2023_outcome_read"] == "NO"
        assert result["cy011_read"] == "NO"
        assert result["hashes"]["spec_sha256"] == _sha256(spec_path)
        assert spec["experiment_id"] == experiment_id

        prohibited = " ".join(spec["prohibited"])
        assert "post-2023" in prohibited
        assert "CY-011" in prohibited

        for phase in ("generation", "validation"):
            metrics = result.get(phase)
            if metrics and metrics.get("end_date"):
                assert metrics["end_date"] <= "2023-12-31"


def test_sequential_gates_close_without_rescue() -> None:
    panic = _result("ASHARE-PANIC-LIQUID-BASKET-REVERSAL-V1")
    exhaustion = _result(
        "ASHARE-NEW-HIGH-LOW-EXHAUSTION-LIQUID-BASKET-V1"
    )
    for result in (panic, exhaustion):
        assert result["generation_passed"] is True
        assert result["validation_opened"] is True
        assert result["validation_passed"] is False
        assert result["generation"]["annualized_return"] > 0.10
        assert result["validation"]["annualized_return"] < 0.0

    for experiment_id in (
        "ASHARE-LIQUIDITY-ACTIVITY-LIQUID-BASKET-V1",
        "ASHARE-POST-DISTRIBUTION-DRIFT-V1",
        "ASHARE-CASH-DIVIDEND-CAPTURE-V1",
        "ASHARE-SIX-INDEX-TREND-LIQUID-BASKET-V1",
    ):
        result = _result(experiment_id)
        assert result["generation_passed"] is False
        assert result["validation_opened"] is False
        assert result.get("validation") is None


def test_recurrence_failure_and_champion_identity_are_preserved() -> None:
    recurrence = _result("ASHARE-INDUSTRY-CONSENSUS-Q1-RECURRENCE-V1")
    generation = recurrence["generation"]
    recurrent = generation["groups"]["recurrent"]
    isolated = generation["groups"]["isolated"]

    assert recurrence["event_dates"] == 99
    assert recurrence["recurrent_event_dates"] == 82
    assert generation["passed"] is False
    assert generation["checks"]["severe_not_worse"] is False
    assert recurrent["mean_trade_return"] > isolated["mean_trade_return"]
    assert recurrent["severe_trade_fraction"] > isolated["severe_trade_fraction"]
    assert recurrence["validation_opened"] is False

    champion = _result("ASHARE-INDUSTRY-CONSENSUS-Q1-EVENT-V1")
    assert champion["status"] == "USER_TARGET_ACHIEVED"
    assert champion["candidate"]["annualized_return"] == 0.3370373479654274
    assert champion["candidate"]["maximum_drawdown"] == -0.18046774418308176
    assert champion["post_2023_outcome_read"] == "NO"
    assert champion["cy011_read"] == "NO"


def test_trend_strategy_failure_does_not_rewrite_representation_result() -> None:
    result = _result("ASHARE-SIX-INDEX-TREND-LIQUID-BASKET-V1")
    assert result["generation"]["annualized_return"] < 0.0
    assert result["generation"]["daily_sharpe"] < 0.0
    assert result["validation_opened"] is False

    report = (
        PROGRAM / "reports/ASHARE-SIX-INDEX-TREND-LIQUID-BASKET-V1_report.md"
    ).read_text(encoding="utf-8")
    assert "representation stability" in report
    assert "strategy usefulness" in report
