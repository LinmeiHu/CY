from __future__ import annotations

import importlib.util
import struct
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / (
    "research/market_behavior_os_v2/scripts/"
    "run_ashare_true_gap_below_l_causal_demand_recapture_v30_stage_a.py"
)
SPEC = importlib.util.spec_from_file_location("v30_stage_a_under_test", RUNNER)
assert SPEC is not None and SPEC.loader is not None
v30 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = v30
SPEC.loader.exec_module(v30)


def _f32_widened_to_source_f64(tick: int) -> np.float64:
    return np.float64(np.float32(tick / 100))


def _f64_bits(value: float | np.float64) -> str:
    return struct.pack("<d", float(np.float64(value))).hex()


def _source_decimal(value: float | np.float64) -> str:
    return v30._canonical_decimal_text(
        Decimal.from_float(float(np.float64(value))), "synthetic source double"
    )


def _bind_calendar(monkeypatch: pytest.MonkeyPatch, periods: int = 80) -> pd.DataFrame:
    dates = pd.bdate_range("2020-01-02", periods=periods).normalize()
    calendar = pd.DataFrame(
        {"trade_date": dates, "calendar_index": np.arange(periods, dtype=np.int64)}
    )
    iso = [value.date().isoformat() for value in dates]
    canonical = v30._canonical_json_sha256(
        {"dates": iso, "derivation": v30.FROZEN_CALENDAR_DERIVATION}
    )
    newline = v30.hashlib.sha256(("\n".join(iso) + "\n").encode()).hexdigest()
    monkeypatch.setattr(v30, "FROZEN_CALENDAR_ROW_COUNT", periods)
    monkeypatch.setattr(v30, "FROZEN_CALENDAR_MIN_DATE", dates.min())
    monkeypatch.setattr(v30, "FROZEN_CALENDAR_MAX_DATE", dates.max())
    monkeypatch.setattr(v30, "FROZEN_CALENDAR_CANONICAL_SHA256", canonical)
    monkeypatch.setattr(v30, "FROZEN_CALENDAR_NEWLINE_SHA256", newline)
    return calendar


def _signal_state(key: Any, close_tick: int = 900) -> dict[str, Any]:
    date = key.signal_date
    close = np.float64(close_tick / 100)
    multiplier = np.float64(1.0)
    cash = np.float64(0.0)
    raw = {
        "trade_date": date,
        "decision_at": pd.Timestamp(f"{date.date()} 15:00:00"),
        "decision_timezone": "Asia/Shanghai",
        "symbol": key.symbol,
        "close": v30._canonical_decimal_text(
            Decimal(close_tick) / 100, "synthetic close"
        ),
        "close_source_float64_bits": _f64_bits(close),
        "trade_status": np.int64(1),
        "is_st": False,
        "current_day_data_tradable": True,
        "corporate_action_count": np.int64(0),
        "corporate_action_blocking": False,
        "share_multiplier": _source_decimal(multiplier),
        "share_multiplier_source_float64_bits": _f64_bits(multiplier),
        "cash_per_share": _source_decimal(cash),
        "cash_per_share_source_float64_bits": _f64_bits(cash),
        "bar_valid": True,
        "trading_state_valid": True,
        "industry_valid": True,
        "corporate_action_valid": True,
        "market_rule_valid": True,
        "hard_valid": True,
        "available_at": pd.Timestamp(f"{date.date()} 15:00:00"),
        "snapshot_id": "signal-snapshot",
        "daily_snapshot_id": "daily-snapshot",
        "trading_state_snapshot_id": "state-snapshot",
        "industry_snapshot_id": "industry-snapshot",
        "corporate_action_snapshot_id": "action-snapshot",
        "permitted_projection_sha256": v30.hashlib.sha256(
            b"synthetic-signal-daily-permitted-projection"
        ).hexdigest(),
    }
    return {column: raw[column] for column in v30.SIGNAL_STATE_INPUT_COLUMNS}


def _snapshot_binding() -> dict[str, str]:
    return {
        "snapshot_id": "signal-snapshot",
        "daily_snapshot_id": "daily-snapshot",
        "trading_state_snapshot_id": "state-snapshot",
        "industry_snapshot_id": "industry-snapshot",
        "corporate_action_snapshot_id": "action-snapshot",
        "permitted_projection_sha256": v30.hashlib.sha256(
            b"synthetic-signal-daily-permitted-projection"
        ).hexdigest(),
    }


def _action(
    key: Any,
    *,
    event: str = "event-1",
    kind: str = "CASH_ONLY",
    effective_offset: int = 2,
    known_at: str | pd.Timestamp | None = None,
    source_table: str = "distributions",
) -> dict[str, Any]:
    raw_symbol = key.symbol[:6]
    known = (
        pd.Timestamp(f"{key.signal_date.date()} 16:00:00")
        if known_at is None
        else pd.Timestamp(known_at)
    )
    cash = np.float64(0.10 if kind == "CASH_ONLY" else 0.0)
    multiplier = np.float64(1.10 if kind == "RISK_SHARE" else 1.0)
    rights_ratio = np.float64(0.10 if kind == "RISK_RIGHTS" else 0.0)
    rights_price = np.float64(5.0 if kind == "RISK_RIGHTS" else 0.0)
    if source_table == "distributions":
        term_fields = {
            "cash_per_share_gross_source_is_null": False,
            "cash_per_share_gross_source_float64_bits": _f64_bits(cash),
            "cash_per_share_gross": _source_decimal(cash),
            "cash_per_share_gross_normalization_status": v30.QD010_SOURCE_VALUE_EXACT,
            "share_multiplier_source_is_null": False,
            "share_multiplier_source_float64_bits": _f64_bits(multiplier),
            "share_multiplier": _source_decimal(multiplier),
            "share_multiplier_normalization_status": v30.QD010_SOURCE_VALUE_EXACT,
            "rights_ratio_source_is_null": True,
            "rights_ratio_source_float64_bits": None,
            "rights_ratio": "0",
            "rights_ratio_normalization_status": (
                v30.QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0
            ),
            "rights_price_source_is_null": True,
            "rights_price_source_float64_bits": None,
            "rights_price": "0",
            "rights_price_normalization_status": (
                v30.QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0
            ),
        }
    else:
        term_fields = {
            "cash_per_share_gross_source_is_null": True,
            "cash_per_share_gross_source_float64_bits": None,
            "cash_per_share_gross": "0",
            "cash_per_share_gross_normalization_status": (
                v30.QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_0
            ),
            "share_multiplier_source_is_null": True,
            "share_multiplier_source_float64_bits": None,
            "share_multiplier": "1",
            "share_multiplier_normalization_status": (
                v30.QD010_SOURCE_NOT_APPLICABLE_NEUTRAL_1
            ),
            "rights_ratio_source_is_null": False,
            "rights_ratio_source_float64_bits": _f64_bits(rights_ratio),
            "rights_ratio": _source_decimal(rights_ratio),
            "rights_ratio_normalization_status": v30.QD010_SOURCE_VALUE_EXACT,
            "rights_price_source_is_null": False,
            "rights_price_source_float64_bits": _f64_bits(rights_price),
            "rights_price": _source_decimal(rights_price),
            "rights_price_normalization_status": v30.QD010_SOURCE_VALUE_EXACT,
        }
    raw: dict[str, Any] = {
        "raw_symbol": raw_symbol,
        "canonical_symbol": key.symbol,
        "event_id": event,
        "source_row_hash": v30.hashlib.sha256(f"source:{event}".encode()).hexdigest(),
        "permitted_projection_sha256": "0" * 64,
        "source_table": source_table,
        "source_file_sha256": v30.QD010_SOURCE_SHA256[source_table],
        "source_locator": f"{source_table}:{event}",
        "snapshot_id": f"snapshot:{event}",
        "vintage_id": f"vintage:{event}",
        "known_at": known,
        "available_at": known,
        "known_at_precision": "EXACT_TIMESTAMP",
        "effective_date": key.signal_date + pd.offsets.BDay(effective_offset),
        "action_kind": kind,
        "source_terms_complete": True,
        **term_fields,
    }
    row = {column: raw[column] for column in v30.QD010_ACTION_INPUT_COLUMNS}
    row["permitted_projection_sha256"] = v30.qd010_permitted_projection_sha256(row)
    return row


def _admin_row(key: Any, calendar: pd.DataFrame) -> dict[str, Any]:
    bound = v30.administrative_bound(key.signal_date, calendar)
    assert bound["entry_date"] == key.entry_date
    raw = {
        "protocol_arm": key.protocol_arm,
        "gap_id": key.gap_id,
        "symbol": key.symbol,
        "signal_date": key.signal_date,
        **bound,
        "candidate_key_sha256": key.sha256,
    }
    return {column: raw[column] for column in v30.ADMIN_OUTPUT_COLUMNS}


def _order_bundle(
    monkeypatch: pytest.MonkeyPatch,
    *,
    symbol: str = "000001.SZ",
    gap_id: str = "gap-1",
    arm: str | None = None,
    raw_l_tick: int = 1000,
    close_tick: int = 900,
    actions: list[dict[str, Any]] | None = None,
) -> tuple[Any, pd.DataFrame, dict[str, Any]]:
    calendar = _bind_calendar(monkeypatch)
    signal_date = pd.Timestamp(calendar.trade_date.iloc[20])
    entry_date = pd.Timestamp(calendar.trade_date.iloc[21])
    key = v30.make_candidate_key(
        protocol_arm=v30.AMOUNT_ARM if arm is None else arm,
        gap_id=gap_id,
        symbol=symbol,
        signal_date=signal_date,
        entry_date=entry_date,
    )
    admin = _admin_row(key, calendar)
    action_rows = [] if actions is None else actions
    proof = v30.make_qd010_scope_proof(
        action_rows,
        candidate_key=key,
        observation_at=pd.Timestamp(f"{entry_date.date()} 09:14:59"),
        effective_end_date=admin["h30_capacity_audit_date"],
        projected_row_count=len(action_rows),
        query_complete=True,
    )
    order = v30.freeze_entry_order_at_0915(
        _signal_state(key, close_tick),
        action_rows,
        candidate_key=key,
        action_scope_proof=proof,
        administrative_row=admin,
        market_calendar=calendar,
        raw_l_tick=np.int64(raw_l_tick),
        reclaimed_pivot_tick=np.int64(close_tick - 10),
        expected_signal_close_tick=np.int64(close_tick),
        expected_signal_snapshot_ids=_snapshot_binding(),
    )
    return order, calendar, admin


def _entry_row(
    order: Any,
    time_text: str,
    *,
    high_tick: int | None = None,
    low_tick: int | None = None,
    volume: int = 100,
    amount_cny: float | None = None,
    bar_valid: bool = True,
    snapshot: str | None = None,
    physical_locator: str | None = None,
) -> dict[str, Any]:
    limit = int(order.frozen_buy_limit_tick)
    high = limit if high_tick is None else high_tick
    low = high if low_tick is None else low_tick
    end = pd.Timestamp(f"{order.candidate_key.entry_date.date()} {time_text}:00")
    partition = v30.QD004_DEVELOPMENT_PARTITION_SHA256[end.year]
    query, physical = v30._expected_qd004_locators(order.candidate_key, end, partition)
    amount = (
        float(Decimal(low + high) * Decimal(volume) / 200)
        if amount_cny is None
        else amount_cny
    )
    code, exchange = order.candidate_key.symbol.rsplit(".", 1)
    row = {
        "qmt_code": order.candidate_key.symbol,
        "symbol": code,
        "exchange": exchange,
        "period": "1m",
        "adjust": "none",
        "trade_date": order.candidate_key.entry_date,
        "bar_end_time": end,
        "open": _f32_widened_to_source_f64(high),
        "high": _f32_widened_to_source_f64(high),
        "low": _f32_widened_to_source_f64(low),
        "close": _f32_widened_to_source_f64(high),
        "volume": np.float64(volume),
        "amount": np.float64(amount),
        "source": v30.QD004_REQUIRED_SOURCE,
        "protocol_arm": order.candidate_key.protocol_arm,
        "gap_id": order.candidate_key.gap_id,
        "candidate_symbol": order.candidate_key.symbol,
        "expected_trade_date": order.candidate_key.entry_date,
        "expected_bar_end_time": end,
        "available_at": end,
        "bar_valid": bar_valid,
        "source_snapshot_id": (
            f"QD004:{v30.QD004_CANONICAL_SOURCE_SHA256}:{partition}"
            if snapshot is None
            else snapshot
        ),
        "query_partition_sha256": partition,
        "query_locator": query,
        "physical_source_locator": physical if physical_locator is None else physical_locator,
        "source_match_count": np.int64(1),
        "permitted_projection_sha256": "0" * 64,
    }
    row["permitted_projection_sha256"] = v30.qd004_permitted_projection_sha256(
        row, order=order, expected_bar_end_time=end
    )
    return row


def _zero_key(order: Any, time_text: str) -> dict[str, Any]:
    end = pd.Timestamp(f"{order.candidate_key.entry_date.date()} {time_text}:00")
    partition = v30.QD004_DEVELOPMENT_PARTITION_SHA256[end.year]
    query, _ = v30._expected_qd004_locators(order.candidate_key, end, partition)
    return {
        **{column: None for column in v30.QD004_PHYSICAL_SOURCE_COLUMNS},
        "protocol_arm": order.candidate_key.protocol_arm,
        "gap_id": order.candidate_key.gap_id,
        "candidate_symbol": order.candidate_key.symbol,
        "expected_trade_date": order.candidate_key.entry_date,
        "expected_bar_end_time": end,
        "available_at": None,
        "bar_valid": None,
        "source_snapshot_id": None,
        "query_partition_sha256": partition,
        "query_locator": query,
        "physical_source_locator": None,
        "source_match_count": np.int64(0),
        "permitted_projection_sha256": None,
    }


def _h0_audit(
    order: Any,
    *,
    daily_volume: float = 1_000_000.0,
    daily_amount: float = 10_000_000.0,
    suspended: bool = False,
    is_st: bool = False,
) -> dict[str, Any]:
    date = order.candidate_key.entry_date
    if suspended:
        daily_volume = 0.0
        daily_amount = 0.0
    volume = np.float64(daily_volume)
    amount = np.float64(daily_amount)
    partition = v30.CY033_DEVELOPMENT_PARTITION_SHA256[date.year]
    query, physical, source_snapshot = v30._expected_cy033_h0_locators(
        order.candidate_key, partition
    )
    row: dict[str, Any] = {
        "trade_date": date,
        "decision_at": pd.Timestamp(f"{date.date()} 15:00:00"),
        "decision_timezone": "Asia/Shanghai",
        "symbol": order.candidate_key.symbol,
        "volume": volume,
        "amount": amount,
        "trade_status": np.int64(0 if suspended else 1),
        "is_st": is_st,
        "state_source": "registered-state",
        "float_effective_date": date - pd.Timedelta(days=100),
        "float_announced_date": date - pd.Timedelta(days=50),
        "float_available_date": date - pd.Timedelta(days=50),
        "circulating_shares": np.float64(100_000_000.0),
        "float_source": "registered-float",
        "corporate_action_count": np.int64(0),
        "corporate_action_ids": None,
        "corporate_action_source": "registered-no-known-action",
        "corporate_action_available_date": date,
        "corporate_action_blocking": False,
        "corporate_action_problems": None,
        "share_multiplier": np.float64(1.0),
        "cash_per_share": np.float64(0.0),
        "rights_ratio": np.float64("nan"),
        "rights_price": np.float64("nan"),
        "market_rule_id": "CN_A_SHARE_MAIN_10_T1_LOT100_V1",
        "market_rule_source": "registered-rule",
        "bar_valid": True,
        "trading_state_valid": True,
        "industry_valid": True,
        "float_valid": True,
        "corporate_action_valid": True,
        "market_valid": True,
        "market_rule_valid": True,
        "historical_identity_valid": True,
        "hard_valid": True,
        "invalid_reasons": "",
        "current_day_data_tradable": not suspended,
        "available_at": pd.Timestamp(f"{date.date()} 15:00:00"),
        "snapshot_id": v30.CY033_REGISTERED_SNAPSHOT_ID,
        "pit_grade": "B_CAUSAL_RESEARCH",
        "strict_archive_ready": False,
        "daily_snapshot_id": "cy033-h0-daily",
        "trading_state_snapshot_id": "cy033-h0-state",
        "industry_snapshot_id": "cy033-h0-industry",
        "float_snapshot_id": "cy033-h0-float",
        "corporate_action_snapshot_id": "cy033-h0-action",
        "market_snapshot_id": "cy033-h0-market",
        "protocol_arm": order.candidate_key.protocol_arm,
        "gap_id": order.candidate_key.gap_id,
        "expected_trade_date": date,
        "source_match_count": np.int64(1),
        "query_locator": query,
        "query_partition_sha256": partition,
        "physical_source_locator": physical,
        "source_snapshot_id": source_snapshot,
        "permitted_projection_sha256": "0" * 64,
    }
    row["permitted_projection_sha256"] = (
        v30.cy033_h0_permitted_projection_sha256(
            row, candidate_key=order.candidate_key
        )
    )
    return row


class _Reader:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[str] = []

    def __call__(self, timestamp: pd.Timestamp) -> dict[str, Any]:
        key = timestamp.strftime("%H:%M")
        self.calls.append(key)
        return self.rows[key]


class _H0Reader:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.calls: list[pd.Timestamp] = []

    def __call__(self, timestamp: pd.Timestamp) -> dict[str, Any]:
        self.calls.append(timestamp)
        return self.row


def _preallocation_candidate(order: Any, rank: int = 1) -> dict[str, Any]:
    key = order.candidate_key
    return {
        "protocol_arm": key.protocol_arm,
        "gap_id": key.gap_id,
        "symbol": key.symbol,
        "signal_date": key.signal_date,
        "entry_date": key.entry_date,
        "h30_capacity_audit_date": order.h30_capacity_audit_date,
        "cap25_rank": np.int64(rank),
        "preorder_status": v30.PREORDER_ORDER_FROZEN,
        "candidate_key_sha256": key.sha256,
        "market_calendar_sha256": order.market_calendar_sha256,
        "action_scope_digest": order.action_scope_digest,
        "frozen_order_digest": order.frozen_order_digest,
        "order_decision_at": order.order_decision_at,
        "order_submitted_at": order.order_submitted_at,
    }


def _all_no_cross_rows(order: Any) -> dict[str, dict[str, Any]]:
    return {
        time_text: _entry_row(
            order,
            time_text,
            high_tick=int(order.frozen_buy_limit_tick) + 1,
            low_tick=int(order.frozen_buy_limit_tick) + 1,
        )
        for time_text in v30.ENTRY_SCAN_BAR_END_TIMES
    }


def test_metadata_check_is_row_free_and_contains_only_final_entry_clock() -> None:
    metadata = v30.metadata_check()
    assert metadata["actual_market_data_rows_opened"] == 0
    assert metadata["post_2021_rows_opened"] == 0
    assert metadata["registry_read"] is False
    assert metadata["entry_clock"]["candidate_cap25_k50_qd010_cutoff"] == "09:14:59"
    assert metadata["entry_clock"]["order_submitted_time"] == "09:15:00"
    assert (
        metadata["entry_clock"]["minimum_provable_strict_through_volume_shares"]
        == 10_000
    )
    assert metadata["entry_clock"]["real_broker_or_L2_fill_claimed"] is False
    assert metadata["entry_clock"]["h0_can_create_fill_or_resolve_missing_minute"] is False
    assert "close" not in metadata["schemas"]["cy033_h0_terminal_audit_input"]


def test_candidate_key_is_exact_five_tuple_and_rejects_aliases() -> None:
    key = v30.make_candidate_key(
        protocol_arm=v30.AMOUNT_ARM,
        gap_id="g",
        symbol="000001.SZ",
        signal_date=pd.Timestamp("2020-02-03"),
        entry_date=pd.Timestamp("2020-02-04"),
    )
    assert len(key.sha256) == 64
    assert v30.validate_candidate_key(key) == key
    with pytest.raises(v30.V30StageAError):
        v30.make_candidate_key(
            protocol_arm=v30.AMOUNT_ARM,
            gap_id="g",
            symbol="000001.SH",
            signal_date=pd.Timestamp("2020-02-03"),
            entry_date=pd.Timestamp("2020-02-04"),
        )
    with pytest.raises(v30.V30StageAError):
        v30.make_candidate_key(
            protocol_arm=v30.AMOUNT_ARM,
            gap_id="g",
            symbol="000001.SZ",
            signal_date=pd.Timestamp("2020-02-03"),
            entry_date=pd.Timestamp("2020-02-03"),
        )


@pytest.mark.parametrize(
    ("close", "d5", "u5"),
    [(101, 96, 106), (110, 105, 116), (109, 104, 114), (900, 855, 945)],
)
def test_universal_d5_u5_use_half_up_integer_ticks(close: int, d5: int, u5: int) -> None:
    assert int(v30.universal_maximum_down_floor_tick(np.int64(close))) == d5
    assert int(v30.universal_minimum_up_cap_tick(np.int64(close))) == u5
    for bad in (float(close), str(close), True):
        with pytest.raises(v30.V30StageAError):
            v30.universal_maximum_down_floor_tick(bad)


def test_order_is_frozen_at_cutoff_submitted_0915_and_binds_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, calendar, admin = _order_bundle(monkeypatch)
    assert order.order_decision_at.strftime("%H:%M:%S") == "09:14:59"
    assert order.order_submitted_at.strftime("%H:%M:%S") == "09:15:00"
    assert order.order_size_shares == 100
    assert order.time_in_force == "DAY"
    assert int(order.universal_maximum_down_floor_tick) <= int(
        order.frozen_buy_limit_tick
    ) <= int(order.universal_minimum_up_cap_tick)
    assert int(order.frozen_buy_limit_tick) == min(
        int(order.max_headroom_buy_tick), int(order.universal_minimum_up_cap_tick)
    )
    assert v30.validate_frozen_order(order) == order

    changed = dict(admin)
    changed["entry_date"] = pd.Timestamp(changed["entry_date"]) + pd.offsets.BDay(1)
    with pytest.raises(v30.V30StageAError):
        v30.validate_administrative_candidate(
            changed, calendar=calendar, candidate_key=order.candidate_key
        )


def test_below_d5_is_deterministic_preopen_no_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, _ = _order_bundle(monkeypatch, raw_l_tick=910, close_tick=900)
    assert order.entry_hard_valid is False
    assert order.entry_status == "NO_ENTRY_PLANNED_LIMIT_BELOW_D5"
    assert order.frozen_buy_limit_tick is None
    assert v30.preorder_status_from_frozen_order(order) == v30.PREORDER_RESOLVED_NO_ORDER


def test_qd010_scope_separates_source_and_projection_hashes_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, calendar, admin = _order_bundle(monkeypatch)
    key = order.candidate_key
    row = _action(key)
    proof = v30.make_qd010_scope_proof(
        [row],
        candidate_key=key,
        observation_at=pd.Timestamp(f"{key.entry_date.date()} 09:14:59"),
        effective_end_date=admin["h30_capacity_audit_date"],
        projected_row_count=np.int64(1),
        query_complete=True,
    )
    assert proof.projected_source_row_hashes == (row["source_row_hash"],)
    assert proof.permitted_projection_sha256s == (
        row["permitted_projection_sha256"],
    )
    assert dict(proof.source_row_counts) == {"distributions": 1, "rights_issues": 0}
    assert v30.validate_qd010_scope_proof(proof, [row]) == proof

    empty = v30.make_qd010_scope_proof(
        [],
        candidate_key=key,
        observation_at=pd.Timestamp(f"{key.entry_date.date()} 09:14:59"),
        effective_end_date=admin["h30_capacity_audit_date"],
        projected_row_count=0,
        query_complete=True,
    )
    assert dict(empty.source_row_counts) == {"distributions": 0, "rights_issues": 0}


def test_qd010_projection_pit_scope_and_locator_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, admin = _order_bundle(monkeypatch)
    key = order.candidate_key
    row = _action(key)

    changed = dict(row)
    changed["cash_per_share_gross"] = "0.20"
    with pytest.raises(v30.V30StageAError):
        v30.make_qd010_scope_proof(
            [changed],
            candidate_key=key,
            observation_at=order.order_decision_at,
            effective_end_date=admin["h30_capacity_audit_date"],
            projected_row_count=1,
            query_complete=True,
        )

    future = _action(key, event="future", known_at=order.order_decision_at + pd.Timedelta(seconds=1))
    proof = v30.make_qd010_scope_proof(
        [future],
        candidate_key=key,
        observation_at=order.order_decision_at,
        effective_end_date=admin["h30_capacity_audit_date"],
        projected_row_count=1,
        query_complete=True,
    )
    with pytest.raises(v30.V30StageAError):
        v30.classify_entry_known_actions([future], scope_proof=proof)

    duplicate = _action(key, event="other")
    duplicate["source_locator"] = row["source_locator"]
    duplicate["permitted_projection_sha256"] = v30.qd010_permitted_projection_sha256(
        duplicate
    )
    proof = v30.make_qd010_scope_proof(
        [row, duplicate],
        candidate_key=key,
        observation_at=order.order_decision_at,
        effective_end_date=admin["h30_capacity_audit_date"],
        projected_row_count=2,
        query_complete=True,
    )
    with pytest.raises(v30.V30StageAError):
        v30.classify_entry_known_actions([row, duplicate], scope_proof=proof)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("000001", "000001.SZ"),
        ("600000", "600000.SH"),
        ("920001", "920001.BJ"),
        ("430001", "430001.BJ"),
        ("830001", "830001.BJ"),
        ("500001", "500001.SH"),
    ],
)
def test_qd010_canonicalizer_matches_bound_sql(raw: str, expected: str) -> None:
    assert v30.canonicalize_qd010_symbol(raw) == expected


def test_first_valid_10000_share_full_bar_proxy_accepts_then_opens_h0(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, _ = _order_bundle(monkeypatch)
    rows = _all_no_cross_rows(order)
    rows["09:30"] = _entry_row(
        order, "09:30", high_tick=int(order.frozen_buy_limit_tick) - 1, volume=10_000
    )
    reader = _Reader(rows)
    h0_reader = _H0Reader(_h0_audit(order))
    evidence = v30.evaluate_entry_order_execution(order, reader, h0_reader)
    assert reader.calls == ["09:30"]
    assert len(h0_reader.calls) == 1
    assert h0_reader.calls[0].strftime("%H:%M:%S") == "15:00:00"
    assert evidence.entry_evidence_accepted is True
    assert evidence.counterfactual_proxy_fill_proved is True
    assert (
        evidence.h0_audit.audit_status
        == "H0_CORROBORATED_COUNTERFACTUAL_PROXY_FILL"
    )
    assert int(evidence.fill_tick) == int(order.frozen_buy_limit_tick)
    assert len(evidence.opened_bars) == 1
    assert v30.validate_entry_settlement_evidence(
        evidence,
        expected_row={
            **_preallocation_candidate(order),
            "occupied_sample_slots_before": 0,
            "preallocation_status": "PREALLOCATED_ORDER_SAMPLE_SLOT",
            "sample_cap_semantics": v30.SAMPLE_CAP_SEMANTICS,
        },
    ) == evidence


@pytest.mark.parametrize(
    ("high_delta", "low_delta", "volume"),
    [
        (0, 0, 10_000),
        (1, -1, 10_000),
        (2, -2, 10_000),
        (-1, -2, 9_999),
    ],
)
def test_terminal_equality_straddle_low_cross_or_9999_share_touch_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
    high_delta: int,
    low_delta: int,
    volume: int,
) -> None:
    order, _, _ = _order_bundle(monkeypatch)
    limit = int(order.frozen_buy_limit_tick)
    rows = _all_no_cross_rows(order)
    rows["09:30"] = _entry_row(
        order,
        "09:30",
        high_tick=limit + high_delta,
        low_tick=limit + low_delta,
        volume=volume,
    )
    reader = _Reader(rows)
    h0_reader = _H0Reader(_h0_audit(order))
    with pytest.raises(v30.V30StageAError, match="possible partial"):
        v30.evaluate_entry_order_execution(order, reader, h0_reader)
    assert reader.calls == list(v30.ENTRY_SCAN_BAR_END_TIMES)
    assert h0_reader.calls == []


def test_earlier_ambiguous_touch_is_resolved_only_by_later_full_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, _ = _order_bundle(monkeypatch)
    limit = int(order.frozen_buy_limit_tick)
    rows = _all_no_cross_rows(order)
    rows["09:30"] = _entry_row(
        order, "09:30", high_tick=limit, low_tick=limit - 2, volume=10_000
    )
    rows["09:31"] = _entry_row(
        order, "09:31", high_tick=limit - 1, low_tick=limit - 2, volume=10_000
    )
    reader = _Reader(rows)
    h0_reader = _H0Reader(_h0_audit(order))
    evidence = v30.evaluate_entry_order_execution(order, reader, h0_reader)
    assert reader.calls == ["09:30", "09:31"]
    assert len(h0_reader.calls) == 1
    assert evidence.entry_evidence_accepted is True
    assert evidence.opened_bars[-1].bar_end_time.strftime("%H:%M") == "09:31"
    assert int(evidence.fill_tick) == limit


def test_eight_valid_zero_volume_physical_rows_are_known_no_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, _ = _order_bundle(monkeypatch)
    rows = {
        time_text: _entry_row(order, time_text, volume=0)
        for time_text in v30.ENTRY_SCAN_BAR_END_TIMES
    }
    reader = _Reader(rows)
    h0_reader = _H0Reader(_h0_audit(order, suspended=True))
    evidence = v30.evaluate_entry_order_execution(order, reader, h0_reader)
    assert reader.calls == list(v30.ENTRY_SCAN_BAR_END_TIMES)
    assert len(h0_reader.calls) == 1
    assert evidence.entry_evidence_accepted is False
    assert evidence.entry_status == "DAY_LIMIT_CANCELLED_093701_NO_FILL"
    assert evidence.h0_audit.audit_status == "H0_CORROBORATED_SUSPENSION_NO_FILL"
    assert evidence.cancel_at.strftime("%H:%M:%S") == "09:37:01"


def test_all_zero_match_scaffold_is_unknown_and_never_opens_entry_day_daily(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, _ = _order_bundle(monkeypatch)
    reader = _Reader(
        {time_text: _zero_key(order, time_text) for time_text in v30.ENTRY_SCAN_BAR_END_TIMES}
    )
    h0_reader = _H0Reader(_h0_audit(order, suspended=True))
    with pytest.raises(v30.V30StageAError, match="minute key is absent"):
        v30.evaluate_entry_order_execution(order, reader, h0_reader)
    assert reader.calls == ["09:30"]
    assert h0_reader.calls == []


def test_mixed_zero_one_duplicate_invalid_or_wrong_snapshot_prefix_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order, _, _ = _order_bundle(monkeypatch)
    rows = _all_no_cross_rows(order)
    rows["09:30"] = _zero_key(order, "09:30")
    with pytest.raises(v30.V30StageAError):
        v30.evaluate_entry_order_execution(
            order, _Reader(rows), _H0Reader(_h0_audit(order))
        )

    rows = _all_no_cross_rows(order)
    rows["09:31"] = _entry_row(order, "09:31")
    rows["09:31"]["physical_source_locator"] = rows["09:30"][
        "physical_source_locator"
    ]
    with pytest.raises(v30.V30StageAError):
        v30.evaluate_entry_order_execution(
            order, _Reader(rows), _H0Reader(_h0_audit(order))
        )

    rows = _all_no_cross_rows(order)
    rows["09:31"]["bar_valid"] = False
    with pytest.raises(v30.V30StageAError):
        v30.evaluate_entry_order_execution(
            order, _Reader(rows), _H0Reader(_h0_audit(order))
        )

    rows = _all_no_cross_rows(order)
    rows["09:30"]["source_snapshot_id"] = "wrong"
    with pytest.raises(v30.V30StageAError):
        v30.evaluate_entry_order_execution(
            order, _Reader(rows), _H0Reader(_h0_audit(order))
        )

    zero = _zero_key(order, "09:30")
    zero["source_snapshot_id"] = "fabricated"
    rows = {time_text: _zero_key(order, time_text) for time_text in v30.ENTRY_SCAN_BAR_END_TIMES}
    rows["09:30"] = zero
    with pytest.raises(v30.V30StageAError):
        v30.evaluate_entry_order_execution(
            order, _Reader(rows), _H0Reader(_h0_audit(order))
        )
