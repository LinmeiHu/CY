from __future__ import annotations

# ruff: noqa: E501
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

RUNNER = (
    Path(__file__).resolve().parents[1]
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_demand_recapture_sequential_v29r45_stage_b.py"
)
SPEC = importlib.util.spec_from_file_location("v29r45_stage_b", RUNNER)
assert SPEC is not None and SPEC.loader is not None
stage_b = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_b)


def test_decimal_tick_contract_rejects_rounding_and_ceil_is_conservative() -> None:
    assert stage_b.observed_price_tick("10.10", "price") == 1010
    assert stage_b.theoretical_sell_tick(stage_b.Decimal("10.10001"), "target") == 1011
    with pytest.raises(stage_b.StageBError, match="canonical"):
        stage_b.observed_price_tick("10.101", "price")


def test_candidate_coordinates_remain_source_decimal_strings() -> None:
    signal_date = pd.Timestamp("2020-01-02")
    row = {
        "protocol_arm": "V29R4_CAP25",
        "gap_id": "g",
        "symbol": "000001.SZ",
        "board": "MAIN",
        "signal_date": signal_date,
        "signal_time": signal_date + pd.Timedelta(hours=15),
        "signal_available_at": signal_date + pd.Timedelta(hours=15),
        "signal_snapshot_id": "s",
        "signal_daily_snapshot_id": "d",
        "signal_corporate_action_snapshot_id": "a",
        "L": "10.0000000000000000001",
        "coordinate_factor": "1.0000000000000000001",
        "signal_industry": "I",
        "cap25_rank": "1",
    }
    normalized = stage_b.normalize_candidates(pd.DataFrame([row]))
    assert normalized.loc[0, "L"] == row["L"]
    assert normalized.loc[0, "coordinate_factor"] == row["coordinate_factor"]
    assert normalized.loc[0, "cap25_rank"] == 1


def test_online_capacity_never_opens_rejected_future_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_b, "MAX_POSITIONS", 1)
    entries = pd.DataFrame(
        [
            {"protocol_arm": "V29R4_CAP25", "gap_id": "a", "symbol": "A", "entry_status": "EXECUTABLE_ENTRY", "entry_date": "2020-01-02", "signal_date": "2020-01-01", "cap25_rank": 1},
            {"protocol_arm": "V29R4_CAP25", "gap_id": "b", "symbol": "A", "entry_status": "EXECUTABLE_ENTRY", "entry_date": "2020-01-03", "signal_date": "2020-01-02", "cap25_rank": 1},
            {"protocol_arm": "V29R4_CAP25", "gap_id": "d", "symbol": "D", "entry_status": "EXECUTABLE_ENTRY", "entry_date": "2020-01-03", "signal_date": "2020-01-02", "cap25_rank": 2},
            {"protocol_arm": "V29R4_CAP25", "gap_id": "c", "symbol": "C", "entry_status": "EXECUTABLE_ENTRY", "entry_date": "2020-01-06", "signal_date": "2020-01-03", "cap25_rank": 1},
        ]
    )
    opened: list[str] = []

    def resolve(row: SimpleNamespace) -> dict[str, object]:
        gap_id = str(row.gap_id)
        opened.append(gap_id)
        return {
            "gap_id": gap_id,
            "exit_date": pd.Timestamp("2020-01-03") if gap_id == "a" else pd.Timestamp("2020-01-07"),
            "outcome_status": "COMPLETED",
        }

    portfolio, outcomes = stage_b.replay_online_portfolio(entries, resolve)
    assert opened == ["a", "c"]
    assert dict(zip(portfolio.gap_id, portfolio.capacity_status, strict=True)) == {
        "a": "CAPACITY_ACCEPTED",
        "b": "CAPACITY_REJECT_SAME_SYMBOL_OVERLAP",
        "d": "CAPACITY_REJECT_K50",
        "c": "CAPACITY_ACCEPTED",
    }
    assert set(outcomes.gap_id) == {"a", "c"}


def test_administrative_censor_uses_entry_plus_23_without_price_data() -> None:
    dates = pd.bdate_range("2020-01-02", periods=25)
    calendar = pd.DataFrame({"trade_date": dates, "calendar_index": range(25)})
    candidates = pd.DataFrame(
        [
            {"gap_id": "complete", "signal_date": dates[0]},
            {"gap_id": "tail", "signal_date": dates[1]},
        ]
    )
    result = stage_b.administrative_censor(candidates, calendar).set_index("gap_id")
    assert not bool(result.loc["complete", "administratively_censored"])
    assert bool(result.loc["tail", "administratively_censored"])
    assert result.loc["tail", "admin_status"] == "RIGHT_CENSORED_2021_ADMINISTRATIVE"


def _paths(*, risk: bool) -> tuple[SimpleNamespace, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-02", periods=25)
    calendar = pd.DataFrame({"trade_date": dates, "calendar_index": range(25)})
    key = {
        "protocol_arm": "V29R4_CAP25",
        "gap_id": "g",
        "symbol": "000001.SZ",
        "signal_date": dates[0],
        "entry_date": dates[1],
    }
    daily_rows = []
    for signal_offset, date in enumerate(dates):
        entry_offset = signal_offset - 1
        daily_rows.append(
            {
                **key,
                "trade_date": date,
                "signal_session_offset": signal_offset,
                "entry_session_offset": entry_offset,
                "decision_at": date + pd.Timedelta(hours=15),
                "available_at": date + pd.Timedelta(hours=15),
                "open": "10.00",
                "high": "99.00" if entry_offset == 0 else ("11.00" if entry_offset == 1 else "10.00"),
                "trade_status": 1,
                "current_day_data_tradable": True,
                "market_rule_valid": True,
                "corporate_action_count": 0,
                "corporate_action_ids": "",
                "share_multiplier": "1",
                "cash_per_share": "0",
                "rights_ratio": "0",
                "rights_price": "0",
                "corporate_action_valid": True,
                "corporate_action_blocking": False,
                "corporate_action_snapshot_id": "ACT",
                "hard_valid": True,
                "invalid_reasons": "",
                "snapshot_id": f"D-{signal_offset}",
                "daily_snapshot_id": f"DD-{signal_offset}",
            }
        )
    daily = pd.DataFrame(daily_rows)
    execution_rows = []
    for entry_offset, date in enumerate(dates[1:]):
        execution_rows.append(
            {
                **key,
                "trade_date": date,
                "signal_session_offset": entry_offset + 1,
                "entry_session_offset": entry_offset,
                "window_index": 0,
                "available_at": date + pd.Timedelta(hours=9, minutes=35),
                "open": "9.00" if risk and entry_offset == 1 else "10.00",
                "trade_status": 1,
                "is_st": False,
                "up_limit_price": "11.00",
                "down_limit_price": "8.00",
                "market_rule_valid": True,
                "source_resolution_minutes": 1,
                "minute_count": 5,
                "distinct_minute_count": 5,
                "ohlc_valid": True,
                "unit_valid": True,
                "causal_inputs_valid": True,
                "hard_valid": True,
                "invalid_reasons": "",
                "source": "CY008",
                "snapshot_id": f"E-{entry_offset}",
                "daily_snapshot_id": f"D-{entry_offset + 1}",
            }
        )
    execution = pd.DataFrame(execution_rows)
    actions = pd.DataFrame(columns=stage_b.ACTION_COLUMNS)
    if risk:
        actions = pd.DataFrame(
            [
                {
                    **key,
                    "h23_date": dates[24],
                    "event_id": "R1",
                    "action_kind": "RISK_SHARE",
                    "known_at": dates[1] + pd.Timedelta(hours=10),
                    "available_at": dates[1] + pd.Timedelta(hours=10),
                    "effective_date": dates[5],
                    "cash_per_share": "0",
                    "share_multiplier": "2",
                    "rights_ratio": "0",
                    "rights_price": "0",
                    "source_terms_complete": True,
                    "execution_timing_resolved": True,
                    "snapshot_id": "QD010",
                }
            ]
        )
    entry = SimpleNamespace(
        **key,
        board="MAIN",
        entry_cal_idx=1,
        h20_cal_idx=21,
        last_exit_cal_idx=24,
        last_exit_date=dates[24],
        entry_observed_at=dates[1] + pd.Timedelta(hours=9, minutes=35),
        coordinate_factor="1",
        target_coordinate="11.00",
        entry_raw_price="10.00",
    )
    return entry, daily, execution, actions, calendar


def test_target_ignores_entry_day_high_and_fills_t_plus_one() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=False)
    outcome = stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)
    assert outcome["exit_reason"] == "A67_TARGET"
    assert outcome["holding_sessions"] == 1
    assert outcome["exit_raw_price"] == "11"


def test_risk_open_precedes_same_session_daily_high() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=True)
    outcome = stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)
    assert outcome["exit_reason"] == "CORPORATE_ACTION_RISK"
    assert outcome["holding_sessions"] == 1
    assert outcome["exit_raw_price"] == "9"


def test_unknown_action_timing_and_count_only_match_fail_closed() -> None:
    entry, daily, _, actions, _ = _paths(risk=True)
    actions.loc[0, "effective_date"] = pd.NaT
    with pytest.raises(stage_b.StageBError, match=r"unknown|noncausal"):
        stage_b.normalize_actions(actions)
    actions.loc[0, "effective_date"] = pd.Timestamp(entry.entry_date) + pd.offsets.BDay(4)
    row = daily.loc[daily.entry_session_offset.eq(4)].iloc[0].copy()
    row["corporate_action_count"] = 1
    row["corporate_action_ids"] = "WRONG"
    normalized = stage_b.normalize_actions(actions)
    with pytest.raises(stage_b.StageBError, match="identity mismatch"):
        stage_b._reconcile_action_day(row, normalized)


def test_qd_generic_execution_flag_does_not_replace_direct_terms() -> None:
    _, _, _, actions, _ = _paths(risk=True)
    actions.loc[0, "execution_timing_resolved"] = False
    normalized = stage_b.normalize_actions(actions)
    assert normalized.loc[0, "action_kind"] == "RISK_SHARE"


def test_action_effective_date_must_be_canonical_midnight() -> None:
    _, _, _, actions, calendar = _paths(risk=True)
    actions.loc[0, "effective_date"] = calendar.trade_date.iloc[5] + pd.Timedelta(hours=12)
    with pytest.raises(stage_b.StageBError, match="noncausal action event"):
        stage_b.normalize_actions(actions)


def test_invalid_action_is_ignored_only_when_provably_after_exit() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=True)
    actions.loc[0, "action_kind"] = "UNSUPPORTED_OR_UNKNOWN"
    actions.loc[0, "known_at"] = calendar.trade_date.iloc[3] + pd.Timedelta(hours=10)
    actions.loc[0, "available_at"] = calendar.trade_date.iloc[3] + pd.Timedelta(hours=10)
    actions.loc[0, "effective_date"] = calendar.trade_date.iloc[4]
    outcome = stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)
    assert outcome["exit_reason"] == "A67_TARGET"

    actions.loc[0, "known_at"] = calendar.trade_date.iloc[1] + pd.Timedelta(hours=16)
    actions.loc[0, "available_at"] = calendar.trade_date.iloc[1] + pd.Timedelta(hours=16)
    with pytest.raises(stage_b.StageBError, match="not provably strictly later"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)

    actions.loc[0, "known_at"] = calendar.trade_date.iloc[3] + pd.Timedelta(hours=10)
    actions.loc[0, "available_at"] = calendar.trade_date.iloc[3] + pd.Timedelta(hours=10)
    actions.loc[0, "effective_date"] = pd.NaT
    with pytest.raises(stage_b.StageBError, match="not provably strictly later"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)


def test_action_effective_before_h21_open_blocks_even_if_known_later() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=True)
    daily.loc[daily.entry_session_offset.between(1, 20), "high"] = "10.00"
    effective = calendar.trade_date.iloc[22]
    actions.loc[0, "effective_date"] = effective
    actions.loc[0, "known_at"] = effective + pd.Timedelta(hours=10)
    actions.loc[0, "available_at"] = effective + pd.Timedelta(hours=10)
    with pytest.raises(stage_b.StageBError, match="effective before opening exit"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)


def test_offset_calendar_mapping_is_exact_not_set_only() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=False)
    first, second = daily.index[0], daily.index[1]
    daily.loc[[first, second], "trade_date"] = daily.loc[[second, first], "trade_date"].to_numpy()
    with pytest.raises(stage_b.StageBError, match="offset/calendar mapping drift"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)


def test_opening_exit_rejects_cy008_nontrading_state_conflict() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=False)
    daily.loc[daily.entry_session_offset.between(1, 20), "high"] = "10.00"
    execution.loc[execution.entry_session_offset.eq(21), "trade_status"] = 0
    with pytest.raises(stage_b.StageBError, match="invalid opening-exit evidence"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)


def test_signal_daily_nan_validity_flag_fails_closed() -> None:
    entry, daily, execution, actions, _ = _paths(risk=False)
    signal = daily.loc[daily.entry_session_offset.eq(-1)].copy()
    entry_daily = daily.loc[daily.entry_session_offset.eq(0)].copy()
    daily_entry = pd.concat([signal, entry_daily], ignore_index=True)
    daily_entry["market_rule_valid"] = daily_entry["market_rule_valid"].astype(object)
    daily_entry.loc[daily_entry.entry_session_offset.eq(-1), "market_rule_valid"] = float("nan")
    candidate = pd.DataFrame(
        [
            {
                **entry.__dict__,
                "administratively_censored": False,
                "admin_status": "ADMINISTRATIVE_WINDOW_COMPLETE",
                "signal_snapshot_id": "D-0",
                "signal_daily_snapshot_id": "DD-0",
                "signal_corporate_action_snapshot_id": "ACT",
                "L": "12.00",
                "cap25_rank": 1,
            }
        ]
    )
    result = stage_b.build_entries(
        candidate,
        daily_entry,
        execution.loc[execution.entry_session_offset.eq(0)].copy(),
        actions,
        "V29R4_CAP25",
    )
    assert result.loc[0, "entry_status"] == "UNRESOLVED_DATA_QUALITY"


def _entry_candidate(entry: SimpleNamespace) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **entry.__dict__,
                "administratively_censored": False,
                "admin_status": "ADMINISTRATIVE_WINDOW_COMPLETE",
                "signal_snapshot_id": "D-0",
                "signal_daily_snapshot_id": "DD-0",
                "signal_corporate_action_snapshot_id": "ACT",
                "L": "12.00",
                "cap25_rank": 1,
            }
        ]
    )


def test_reconciled_entry_day_share_action_is_coordinate_no_entry() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=True)
    actions.loc[0, "known_at"] = calendar.trade_date.iloc[0] + pd.Timedelta(hours=10)
    actions.loc[0, "available_at"] = actions.loc[0, "known_at"]
    actions.loc[0, "effective_date"] = entry.entry_date
    mask = daily.entry_session_offset.eq(0)
    daily.loc[mask, "corporate_action_count"] = 1
    daily.loc[mask, "corporate_action_ids"] = "R1"
    daily.loc[mask, "share_multiplier"] = "2"
    daily.loc[mask, "corporate_action_valid"] = False
    daily.loc[mask, "corporate_action_blocking"] = True
    daily.loc[mask, "hard_valid"] = False
    daily_entry = daily.loc[daily.entry_session_offset.isin([-1, 0])].copy()
    result = stage_b.build_entries(
        _entry_candidate(entry),
        daily_entry,
        execution.loc[execution.entry_session_offset.eq(0)].copy(),
        actions,
        "V29R4_CAP25",
    )
    assert result.loc[0, "entry_status"] == "NO_ENTRY_ACTION_COORDINATE"


def test_entry_open_above_legal_up_limit_is_unresolved() -> None:
    entry, daily, execution, actions, _ = _paths(risk=False)
    execution.loc[execution.entry_session_offset.eq(0), "open"] = "11.01"
    result = stage_b.build_entries(
        _entry_candidate(entry),
        daily.loc[daily.entry_session_offset.isin([-1, 0])].copy(),
        execution.loc[execution.entry_session_offset.eq(0)].copy(),
        actions,
        "V29R4_CAP25",
    )
    assert result.loc[0, "entry_status"] == "UNRESOLVED_DATA_QUALITY"


def test_opening_exit_below_legal_down_limit_is_unresolved() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=False)
    daily.loc[daily.entry_session_offset.between(1, 20), "high"] = "10.00"
    execution.loc[execution.entry_session_offset.eq(21), "open"] = "7.99"
    with pytest.raises(stage_b.StageBError, match="outside legal price limits"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)


def test_opening_exit_above_legal_up_limit_is_unresolved() -> None:
    entry, daily, execution, actions, calendar = _paths(risk=False)
    daily.loc[daily.entry_session_offset.between(1, 20), "high"] = "10.00"
    execution.loc[execution.entry_session_offset.eq(21), "open"] = "11.01"
    with pytest.raises(stage_b.StageBError, match="outside legal price limits"):
        stage_b.evaluate_one_outcome(entry, daily, execution, actions, calendar)


def test_every_post_seal_exception_publishes_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    activation = {"verified": True}
    attempt = tmp_path / "attempt.json"
    attempt.write_text("sealed", encoding="utf-8")
    observed: dict[str, object] = {}
    monkeypatch.setattr(stage_b, "initialize_output_anchor", lambda: None)
    monkeypatch.setattr(stage_b, "verify_activation", lambda: activation)
    monkeypatch.setattr(stage_b, "_publish_attempt", lambda *_: attempt)

    def fail_read(*_: object) -> pd.DataFrame:
        raise RuntimeError("synthetic post-seal fault")

    def blocked(
        arm: str, bound: dict[str, object], seal: Path, exc: Exception
    ) -> dict[str, object]:
        observed.update({"arm": arm, "activation": bound, "seal": seal, "error": str(exc)})
        return {"aggregate_publication_status": "BLOCKED"}

    monkeypatch.setattr(stage_b, "_projected_read", fail_read)
    monkeypatch.setattr(stage_b, "_write_blocked_result", blocked)
    result = stage_b.run_arm("v29r4")
    assert result == {"aggregate_publication_status": "BLOCKED"}
    assert observed["error"] == "synthetic post-seal fault"


def test_attempt_seal_is_exclusive_and_consumed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output_root = tmp_path / "anchor"
    monkeypatch.setattr(stage_b, "OUTPUT_ROOT", output_root)
    activation = {
        "runner_sha256": "r",
        "preregistration_sha256": "p",
        "manifest_sha256": "m",
        "activation_audit_sha256": "a",
        "frozen_cohorts": {"V29R4_CAP25": {"stage_a_freeze": "f", "stage_a_selected": "s"}},
    }
    path = stage_b._publish_attempt("v29r4", activation, None)
    try:
        assert path.stat().st_mode & 0o777 == 0o444
        assert stage_b.is_user_immutable(path)
        with pytest.raises(stage_b.StageBError, match="repeated"):
            stage_b._publish_attempt("v29r4", activation, None)
    finally:
        stage_b.os.chflags(
            path,
            path.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        slot = output_root / "v29r4"
        if stage_b.is_user_immutable(slot):
            stage_b.os.chflags(
                slot,
                slot.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
                follow_symlinks=False,
            )
        stage_b.os.chflags(
            output_root,
            output_root.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )


def test_published_result_tree_receives_undeletable_seals(tmp_path: Path) -> None:
    root = tmp_path / "result"
    root.mkdir()
    member = root / "result.json"
    member.write_text("{}\n", encoding="utf-8")
    stage_b.freeze_published_tree(root, {"result.json"})
    try:
        assert root.stat().st_mode & 0o777 == 0o555
        assert member.stat().st_mode & 0o777 == 0o444
        assert stage_b.is_user_immutable(root)
        assert stage_b.is_user_immutable(member)
        with pytest.raises(PermissionError):
            member.unlink()
    finally:
        stage_b.os.chflags(
            root,
            root.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        stage_b.os.chflags(
            member,
            member.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )


def test_tree_freeze_accepts_already_immutable_attempt_member(tmp_path: Path) -> None:
    root = tmp_path / "result-with-attempt"
    root.mkdir()
    attempt = root / "attempt_seal.json"
    result = root / "result.json"
    attempt.write_text("{}\n", encoding="utf-8")
    result.write_text("{}\n", encoding="utf-8")
    attempt.chmod(0o444)
    stage_b.set_user_immutable(attempt)
    stage_b.freeze_published_tree(root, {attempt.name, result.name})
    try:
        assert stage_b.is_user_immutable(attempt)
        assert stage_b.is_user_immutable(result)
        assert stage_b.is_user_immutable(root)
    finally:
        stage_b.os.chflags(
            root,
            root.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        for path in (attempt, result):
            stage_b.os.chflags(
                path,
                path.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
                follow_symlinks=False,
            )


def test_complete_result_bundle_seals_after_consumed_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "anchor"
    monkeypatch.setattr(stage_b, "OUTPUT_ROOT", output_root)
    activation = {
        "runner_sha256": "r",
        "preregistration_sha256": "p",
        "manifest_sha256": "m",
        "activation_audit_sha256": "a",
        "frozen_cohorts": {
            "V29R4_CAP25": {"stage_a_freeze": "f", "stage_a_selected": "s"}
        },
    }
    attempt = stage_b._publish_attempt("v29r4", activation, None)
    entries = pd.DataFrame(
        [
            {
                "gap_id": "g",
                "admin_status": "ADMINISTRATIVE_WINDOW_COMPLETE",
                "entry_status": "EXECUTABLE_ENTRY",
            }
        ]
    )
    portfolio = pd.DataFrame(
        [
            {
                "gap_id": "g",
                "capacity_status": "CAPACITY_ACCEPTED",
                "terminal_class": "COMPLETED_ACCEPTED_TRADE",
            }
        ]
    )
    summary = {
        "success_gates": {
            "accepted_trades_per_development_year_gt_50": False,
            "mean_net_return_ge_0_04": True,
            "mean_holding_sessions_lt_15": True,
        },
        "passed_all_success_gates": False,
    }
    result = stage_b._write_result_bundle(
        "v29r4",
        activation,
        attempt,
        pd.DataFrame(),
        entries,
        pd.DataFrame([{"gap_id": "g", "net_return": "0.04"}]),
        portfolio,
        summary,
    )
    slot = output_root / "v29r4"
    expected = {
        "attempt_seal.json",
        "candidate_audit.parquet",
        "entries.parquet",
        "accepted_trades.parquet",
        "result.json",
    }
    try:
        assert result["aggregate_publication_status"] == "COMPLETE"
        assert {path.name for path in slot.iterdir()} == expected
        assert stage_b.is_user_immutable(slot)
        assert all(stage_b.is_user_immutable(path) for path in slot.iterdir())
    finally:
        stage_b.os.chflags(
            output_root,
            output_root.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        stage_b.os.chflags(
            slot,
            slot.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        for path in slot.iterdir():
            stage_b.os.chflags(
                path,
                path.stat().st_flags & ~stage_b.stat.UF_IMMUTABLE,
                follow_symlinks=False,
            )
