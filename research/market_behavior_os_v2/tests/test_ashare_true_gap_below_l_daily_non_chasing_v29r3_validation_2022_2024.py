from __future__ import annotations

import pandas as pd
import pytest

from research.market_behavior_os_v2.scripts import (
    build_ashare_true_gap_below_l_daily_non_chasing_v29r3_activation_assets as builder,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_daily_non_chasing_v29r3_validation_2022_2024 as subject,
)


def _daily_row(
    symbol: str,
    step_return: float,
    *,
    available_at: str = "2023-06-01 15:00:00",
    hard_valid: bool = True,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "trade_date": "2023-06-01",
        "decision_at": "2023-06-01 15:00:00",
        "close": 100.0 * (1.0 + step_return),
        "preclose": 100.0,
        "trade_status": 1,
        "hard_valid": hard_valid,
        "current_day_data_tradable": True,
        "available_at": available_at,
        "snapshot_id": "PIT-SNAPSHOT",
    }


def test_signal_close_feature_uses_full_market_median_and_fails_closed() -> None:
    entries = pd.DataFrame(
        {
            "gap_id": ["pass", "fail", "missing"],
            "symbol": ["A.SZ", "B.SZ", "MISSING.SZ"],
            "signal_date": ["2023-06-01"] * 3,
            "signal_time": ["2023-06-01 15:00:00"] * 3,
        }
    )
    daily = pd.DataFrame(
        [
            _daily_row("A.SZ", 0.02),
            _daily_row("B.SZ", 0.06),
            _daily_row("C.SH", -0.02),
            _daily_row("D.SH", 0.00),
        ]
    )

    result = subject.attach_daily_non_chasing_feature(entries, daily).set_index("gap_id")

    assert result.loc["pass", "market_eligible_n"] == 4
    assert result.loc["pass", "full_market_hard_valid_pit_median_return"] == pytest.approx(0.01)
    assert bool(result.loc["pass", "v29r3_daily_non_chasing_2pct_gate"])
    assert not bool(result.loc["fail", "v29r3_daily_non_chasing_2pct_gate"])
    assert result.loc["fail", "v29r3_rejection_reason"] == ("SIGNAL_EXCESS_MARKET_GT_0P02")
    assert not bool(result.loc["missing", "v29r3_feature_available"])
    assert result.loc["missing", "v29r3_rejection_reason"] == ("MISSING_OR_DUPLICATE_SIGNAL_ROW")


def test_late_or_invalid_rows_cannot_enter_signal_or_market_feature() -> None:
    entries = pd.DataFrame(
        {
            "gap_id": ["late-signal"],
            "symbol": ["A.SZ"],
            "signal_date": ["2023-06-01"],
            "signal_time": ["2023-06-01 15:00:00"],
        }
    )
    daily = pd.DataFrame(
        [
            _daily_row("A.SZ", 0.01, available_at="2023-06-01 15:01:00"),
            _daily_row("B.SZ", 0.00),
            _daily_row("C.SH", 0.50, hard_valid=False),
        ]
    )

    result = subject.attach_daily_non_chasing_feature(entries, daily).iloc[0]

    assert result.market_eligible_n == 1
    assert not bool(result.v29r3_feature_available)
    assert not bool(result.v29r3_daily_non_chasing_2pct_gate)
    assert result.v29r3_rejection_reason == "SIGNAL_ROW_NOT_HARD_VALID_PIT_ELIGIBLE"


def test_stage_a_rejects_any_outcome_or_issuer_title_column() -> None:
    with pytest.raises(subject.V29R3ValidationError, match="outcomes or issuer/title"):
        subject._assert_no_forbidden_stage_a_columns(
            pd.DataFrame({"gap_id": ["g"], "net_return": [0.1]})
        )
    with pytest.raises(subject.V29R3ValidationError, match="outcomes or issuer/title"):
        subject._assert_no_forbidden_stage_a_columns(
            pd.DataFrame({"gap_id": ["g"], "issuer_risk_titles": ["x"]})
        )


def test_stage_a_authorization_failure_precedes_all_data_row_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_called = False

    def forbidden_read() -> pd.DataFrame:
        nonlocal read_called
        read_called = True
        raise AssertionError("data read occurred before authorization")

    monkeypatch.setattr(subject, "verify_preregistration", lambda: {})
    monkeypatch.setattr(subject, "verify_parent_identity_metadata", lambda: {})
    monkeypatch.setattr(
        subject,
        "verify_stage_a_activation",
        lambda: (_ for _ in ()).throw(subject.V29R3ValidationError("authorization missing")),
    )
    monkeypatch.setattr(subject, "load_parent_selected_identity", forbidden_read)
    monkeypatch.setattr(subject, "load_stage_a_daily", lambda _: forbidden_read())

    with pytest.raises(subject.V29R3ValidationError, match="authorization missing"):
        subject.run_stage_a()
    assert not read_called


def test_stage_b_cannot_resolve_activation_before_stage_a_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activation_called = False

    def activation(_: dict[str, object]) -> dict[str, object]:
        nonlocal activation_called
        activation_called = True
        return {}

    monkeypatch.setattr(
        subject,
        "verify_stage_a_freeze",
        lambda: (_ for _ in ()).throw(subject.V29R3ValidationError("Stage A missing")),
    )
    monkeypatch.setattr(subject, "verify_stage_b_activation", activation)

    with pytest.raises(subject.V29R3ValidationError, match="Stage A missing"):
        subject.prepare_stage_b()
    assert not activation_called


def test_cy041_builder_does_not_resolve_sources_before_stage_a_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_resolution_called = False

    def resolve() -> dict[str, object]:
        nonlocal source_resolution_called
        source_resolution_called = True
        return {}

    monkeypatch.setattr(builder, "_verify_frozen_protocol", lambda: None)
    monkeypatch.setattr(builder, "_assert_new_asset_id", lambda *_: None)
    monkeypatch.setattr(
        subject,
        "verify_stage_a_freeze",
        lambda: (_ for _ in ()).throw(subject.V29R3ValidationError("Stage A missing")),
    )
    monkeypatch.setattr(
        builder,
        "_resolve_stage_b_source_paths_after_stage_a_verification",
        resolve,
    )

    with pytest.raises(subject.V29R3ValidationError, match="Stage A missing"):
        builder.stage_b_manifest_payload({})
    assert not source_resolution_called


def _outcome_fixture() -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = pd.DataFrame(
        {
            "gap_id": ["g1", "g2"],
            "symbol": ["000001.SZ", "000002.SZ"],
            "signal_date": ["2024-06-03", "2024-06-03"],
            "signal_time": ["2024-06-03 15:00:00", "2024-06-03 15:00:00"],
            "entry_status": ["EXECUTABLE_ENTRY", "NO_LEGAL_ENTRY"],
        }
    )
    source = pd.DataFrame(
        {
            "gap_id": ["g1"],
            "symbol": ["000001.SZ"],
            "signal_date": ["2024-06-03"],
            "signal_time": ["2024-06-03 15:00:00"],
            "entry_date": ["2024-06-04"],
            "entry_time": ["2024-06-04 09:31:00"],
            "exit_date": ["2024-06-20"],
            "exit_time": ["2024-06-20 10:00:00"],
            "alpha": [0.67],
            "horizon": [20],
            "stop": ["NONE"],
            "entry_at_or_before_signal": [False],
            "buy_at_or_above_up_limit": [False],
        }
    )
    return selected, source


def test_frozen_outcome_join_preserves_t1_and_rejects_post_2024() -> None:
    selected, source = _outcome_fixture()
    result = subject.select_frozen_outcomes(selected, source)
    assert result.gap_id.tolist() == ["g1"]

    same_bar = source.copy()
    same_bar.loc[0, "entry_time"] = same_bar.loc[0, "signal_time"]
    with pytest.raises(subject.V29R3ValidationError, match=r"T\+1"):
        subject.select_frozen_outcomes(selected, same_bar)

    future = source.copy()
    future.loc[0, "exit_date"] = "2025-01-02"
    future.loc[0, "exit_time"] = "2025-01-02 10:00:00"
    with pytest.raises(subject.V29R3ValidationError, match="post-2024"):
        subject.select_frozen_outcomes(selected, future)

    same_day = source.copy()
    same_day.loc[0, "entry_date"] = same_day.loc[0, "signal_date"]
    with pytest.raises(subject.V29R3ValidationError, match=r"T\+1"):
        subject.select_frozen_outcomes(selected, same_day)

    drifted_identity = source.copy()
    drifted_identity.loc[0, "symbol"] = "000002.SZ"
    with pytest.raises(subject.V29R3ValidationError, match="frozen identity"):
        subject.select_frozen_outcomes(selected, drifted_identity)


def test_preregistration_is_exact_and_read_only() -> None:
    payload = subject.verify_preregistration()
    assert payload["single_additional_gate"]["threshold"] == 0.02
    assert payload["parent"]["issuer_veto_inherited"] is False
    assert (
        payload["development_origin"]["concentration_risk"]["largest_signal_date"] == "2018-10-26"
    )
    assert (
        subject.CROSS_SECTION_SEMANTICS["historical_security_master_completeness_verified"] is False
    )
    assert subject.CROSS_SECTION_SEMANTICS["survivorship_free_claim_allowed"] is False
