from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections.abc import Iterator, Mapping
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
    "run_ashare_true_gap_below_l_causal_demand_recapture_v30_stage_b.py"
)
SPEC = importlib.util.spec_from_file_location("v30_causal_stage_b", RUNNER)
assert SPEC is not None and SPEC.loader is not None
V30 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V30
SPEC.loader.exec_module(V30)


SYMBOL = "000001.SZ"
SHA_A = "a" * 64
SHA_B = "b" * 64
PRODUCTION_CALENDAR_BINDING = (
    V30.FROZEN_CALENDAR_ROW_COUNT,
    V30.FROZEN_CALENDAR_MIN_DATE,
    V30.FROZEN_CALENDAR_MAX_DATE,
    V30.FROZEN_CALENDAR_CANONICAL_SHA256,
    V30.FROZEN_CALENDAR_NEWLINE_SHA256,
)


def _calendar() -> list[dict[str, Any]]:
    dates = pd.bdate_range("2021-01-04", periods=40)
    return [
        {"trade_date": date.normalize(), "calendar_index": index}
        for index, date in enumerate(dates)
    ]


@pytest.fixture(autouse=True)
def _synthetic_calendar_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind only synthetic unit tests to their deterministic toy calendar."""
    rows = _calendar()
    iso = [pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d") for row in rows]
    payload = {"dates": iso, "derivation": V30.FROZEN_CALENDAR_DERIVATION}
    monkeypatch.setattr(V30, "FROZEN_CALENDAR_ROW_COUNT", len(rows))
    monkeypatch.setattr(V30, "FROZEN_CALENDAR_MIN_DATE", pd.Timestamp(iso[0]))
    monkeypatch.setattr(V30, "FROZEN_CALENDAR_MAX_DATE", pd.Timestamp(iso[-1]))
    monkeypatch.setattr(
        V30, "FROZEN_CALENDAR_CANONICAL_SHA256", V30.normalized_json_sha256(payload)
    )
    monkeypatch.setattr(
        V30,
        "FROZEN_CALENDAR_NEWLINE_SHA256",
        hashlib.sha256(("\n".join(iso) + "\n").encode()).hexdigest(),
    )


def _entry(calendar: list[dict[str, Any]], *, gap_id: str = "gap-1") -> dict[str, Any]:
    signal_date = pd.Timestamp(calendar[0]["trade_date"])
    entry_date = pd.Timestamp(calendar[1]["trade_date"])
    return {
        "stage_a_cohort_frozen": True,
        "entry_evidence_accepted": True,
        "entry_settlement_status": "SETTLED_PROXY_ACCEPTED",
        "entry_evidence_status": "CONSERVATIVE_1M_BAR_EXECUTION_PROXY_ACCEPTED",
        "entry_execution_proxy_label": "CONSERVATIVE_1M_BAR_EXECUTION_PROXY",
        "real_fill_claimed": False,
        "entry_hard_valid": True,
        "protocol_arm": "V30_AMOUNT_1X_TO_2X_CAP25",
        "gap_id": gap_id,
        "symbol": SYMBOL,
        "signal_date": signal_date,
        "entry_date": entry_date,
        "entry_calendar_index": 1,
        "entry_decision_at": entry_date + pd.Timedelta(hours=9, minutes=35),
        "order_effective_at": entry_date + pd.Timedelta(hours=9, minutes=35, seconds=1),
        "proxy_interval_start_time": entry_date + pd.Timedelta(hours=9, minutes=36),
        "proxy_bar_end_time": entry_date + pd.Timedelta(hours=9, minutes=37),
        "proxy_worst_buy_tick": 800,
        "proxy_bar_volume_exact": 10_000,
        "proxy_bar_amount_exact": "80000",
        "confirmation_volume_exact": 50_000,
        "confirmation_amount_exact": "450000",
        "signal_close_tick": 900,
        "raw_l_tick": 1000,
        "reclaimed_pivot_tick": 850,
        "cap25_rank": 1,
        "universal_minimum_up_cap_tick": 945,
        "max_headroom_buy_tick": 938,
        "frozen_buy_limit_tick": 939,
        "confirmation_row_sha256": SHA_A,
        "cooldown_row_sha256": SHA_A,
        "execution_proxy_row_sha256": SHA_B,
        "signal_snapshot_id": "signal-snapshot",
        "signal_daily_snapshot_id": "signal-daily-snapshot",
        "signal_corporate_action_snapshot_id": "signal-action-snapshot",
    }


def _daily_rows(
    calendar: list[dict[str, Any]],
    *,
    close_ticks: dict[int, int] | None = None,
    suspensions: set[int] | None = None,
    action_terms: dict[int, tuple[str, Decimal]] | None = None,
) -> list[dict[str, Any]]:
    close_ticks = close_ticks or {}
    suspensions = suspensions or set()
    action_terms = action_terms or {}
    rows = []
    for offset in range(30):
        date = pd.Timestamp(calendar[1 + offset]["trade_date"])
        action_id, cash = action_terms.get(offset, ("", Decimal(0)))
        suspended = offset in suspensions
        rows.append(
            {
                "protocol_arm": "V30_AMOUNT_1X_TO_2X_CAP25",
                "gap_id": "gap-1",
                "symbol": SYMBOL,
                "session_offset": offset,
                "trade_date": date,
                "source_match_count": 1,
                "decision_at": date + pd.Timedelta(hours=15),
                "available_at": date + pd.Timedelta(hours=15),
                "decision_timezone": "Asia/Shanghai",
                "close_tick": close_ticks.get(offset, 900),
                "snapshot_id": "cy033-snapshot",
                "daily_snapshot_id": "daily-snapshot",
                "trading_state_snapshot_id": "state-snapshot",
                "corporate_action_snapshot_id": "action-snapshot",
                "bar_valid": True,
                "trading_state_valid": True,
                "corporate_action_valid": True,
                "market_rule_valid": True,
                "hard_valid": True,
                "corporate_action_blocking": False,
                "corporate_action_count": int(bool(action_id)),
                "corporate_action_ids": [action_id] if action_id else [],
                "cash_cents_per_original_share": str(cash),
                "share_multiplier": "1",
                "rights_ratio": "0",
                "rights_price_cents": "0",
                "trade_status": 0 if suspended else 1,
                "current_day_data_tradable": not suspended,
                "daily_volume": 0 if suspended else 1_000_000,
                "daily_amount": 0.0 if suspended else 9_000_000.0,
                "source_locator": f"daily/partition_year={date.year}/data_0.parquet",
                "partition_sha256": V30.CY033_DEVELOPMENT_PARTITION_SHA256[date.year],
                "row_sha256": "0" * 64,
            }
        )
        rows[-1]["row_sha256"] = _daily_row_sha256(rows[-1])
    return rows


def _daily_row_sha256(row: Mapping[str, Any]) -> str:
    payload = {
        "protocol_arm": row["protocol_arm"],
        "gap_id": row["gap_id"],
        "symbol": row["symbol"],
        "session_offset": row["session_offset"],
        "trade_date": pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d"),
        "source_match_count": 1,
        "decision_at": pd.Timestamp(row["decision_at"]).isoformat(),
        "available_at": pd.Timestamp(row["available_at"]).isoformat(),
        "decision_timezone": row["decision_timezone"],
        "close_tick": row["close_tick"],
        "snapshot_id": row["snapshot_id"],
        "daily_snapshot_id": row["daily_snapshot_id"],
        "trading_state_snapshot_id": row["trading_state_snapshot_id"],
        "corporate_action_snapshot_id": row["corporate_action_snapshot_id"],
        "bar_valid": row["bar_valid"],
        "trading_state_valid": row["trading_state_valid"],
        "corporate_action_valid": row["corporate_action_valid"],
        "market_rule_valid": row["market_rule_valid"],
        "hard_valid": row["hard_valid"],
        "corporate_action_blocking": row["corporate_action_blocking"],
        "corporate_action_count": row["corporate_action_count"],
        "corporate_action_ids": sorted(row["corporate_action_ids"]),
        "cash_cents_per_original_share": V30._canonical_decimal_text(
            Decimal(row["cash_cents_per_original_share"])
        ),
        "share_multiplier": V30._canonical_decimal_text(Decimal(row["share_multiplier"])),
        "rights_ratio": V30._canonical_decimal_text(Decimal(row["rights_ratio"])),
        "rights_price_cents": V30._canonical_decimal_text(Decimal(row["rights_price_cents"])),
        "trade_status": row["trade_status"],
        "current_day_data_tradable": row["current_day_data_tradable"],
        "daily_volume": row["daily_volume"],
        "daily_amount": {
            "source_float64_bits_le_hex": V30._source_float64_decimal(
                row["daily_amount"], "daily amount"
            )[1],
            "decimal_from_float": format(
                V30._source_float64_decimal(row["daily_amount"], "daily amount")[0],
                "f",
            ),
        },
        "source_locator": row["source_locator"],
        "partition_sha256": row["partition_sha256"],
        "projection": "V30_CY033_PERMITTED_COMPLETED_DAILY_ROW_V1",
    }
    return V30.normalized_json_sha256(payload)


def _f32_price(tick: int) -> float:
    return float(np.float32(tick / 100))


def _minute_day(
    calendar: list[dict[str, Any]],
    offset: int,
    *,
    default_tick: int = 900,
    overrides: dict[int, tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    date = pd.Timestamp(calendar[1 + offset]["trade_date"])
    overrides = overrides or {}
    rows = []
    for index, clock in enumerate(V30.EXPECTED_BAR_END_TIMES):
        tick, volume = overrides.get(index, (default_tick, 10_000))
        end = date + pd.Timedelta(hours=clock.hour, minutes=clock.minute)
        query_locator = (
            f"bars/{date.year}_day_parquet_none.parquet"
            f"::qmt_code={SYMBOL}"
            f"::trade_date={end.strftime('%Y-%m-%d')}"
            f"::bar_end_time={end.isoformat()}"
        )
        rows.append(
            {
                "protocol_arm": "V30_AMOUNT_1X_TO_2X_CAP25",
                "gap_id": "gap-1",
                "candidate_symbol": SYMBOL,
                "session_offset": offset,
                "qmt_code": SYMBOL,
                "symbol": "000001",
                "exchange": "SZ",
                "period": "1m",
                "adjust": "none",
                "source": "day_parquet_none",
                "trade_date": date,
                "bar_end_time": end,
                "available_at": end,
                "source_match_count": 1,
                "open": _f32_price(tick),
                "high": _f32_price(tick),
                "low": _f32_price(tick),
                "close": _f32_price(tick),
                "volume": float(volume),
                "amount": float(Decimal(tick * volume) / Decimal(100)),
                "query_locator": query_locator,
                "query_partition_sha256": V30.QD004_DEVELOPMENT_PARTITION_SHA256[date.year],
                "physical_source_locator": (f"{query_locator}::row_group=0::row_index={index}"),
                "source_snapshot_id": V30.qd004_source_snapshot_id(date.year),
                "row_sha256": "0" * 64,
            }
        )
        rows[-1]["row_sha256"] = _minute_row_sha256(rows[-1])
    return rows


def _minute_row_sha256(row: Mapping[str, Any]) -> str:
    prices = {}
    for field in ("open", "high", "low", "close"):
        source64 = np.float64(row[field])
        source64_bits = int(np.asarray([source64], dtype="<f8").view("<u8")[0])
        source = np.float32(source64)
        bits = int(np.asarray([source], dtype="<f4").view("<u4")[0])
        prices[field] = {
            "source_float64_bits_le_hex": f"{source64_bits:016x}",
            "float32_bits_le_hex": f"{bits:08x}",
            "tick": V30.qd004_float32_cent_tick(row[field]),
        }
    volume, volume_bits = V30.qd004_float64_volume_shares(row["volume"])
    amount, amount_bits = V30._source_float64_decimal(row["amount"], "minute amount")
    payload = {
        "protocol_arm": row["protocol_arm"],
        "gap_id": row["gap_id"],
        "candidate_symbol": row["candidate_symbol"],
        "session_offset": row["session_offset"],
        "qmt_code": row["qmt_code"],
        "symbol": row["symbol"],
        "exchange": row["exchange"],
        "period": row["period"],
        "adjust": row["adjust"],
        "source": row["source"],
        "trade_date": pd.Timestamp(row["trade_date"]).strftime("%Y-%m-%d"),
        "bar_end_time": pd.Timestamp(row["bar_end_time"]).isoformat(),
        "available_at": pd.Timestamp(row["available_at"]).isoformat(),
        "source_match_count": 1,
        "prices": prices,
        "volume": {
            "source_float64_bits_le_hex": volume_bits,
            "shares": volume,
        },
        "amount": {
            "source_float64_bits_le_hex": amount_bits,
            "decimal_from_float": format(amount, "f"),
        },
        "query_locator": row["query_locator"],
        "query_partition_sha256": row["query_partition_sha256"],
        "physical_source_locator": row["physical_source_locator"],
        "source_snapshot_id": row["source_snapshot_id"],
        "projection": "V30_QD004_PERMITTED_COMPLETED_MINUTE_ROW_V1",
    }
    return V30.normalized_json_sha256(payload)


def _empty_minute_scaffold(calendar: list[dict[str, Any]], offset: int) -> list[dict[str, Any]]:
    rows = _minute_day(calendar, offset)
    for row in rows:
        _zero_minute_row(row)
    return rows


def _zero_volume_minute_day(
    calendar: list[dict[str, Any]], offset: int, *, flat_tick: int = 800
) -> list[dict[str, Any]]:
    rows = _minute_day(calendar, offset, default_tick=flat_tick)
    for row in rows:
        row["volume"] = 0.0
        row["amount"] = 0.0
        row["row_sha256"] = _minute_row_sha256(row)
    return rows


def _zero_minute_row(row: dict[str, Any]) -> None:
    row["source_match_count"] = 0
    for field in V30.MINUTE_PHYSICAL_FIELDS:
        row[field] = None


def _action(
    calendar: list[dict[str, Any]],
    *,
    event_id: str,
    kind: str,
    effective_offset: int,
    known_at: pd.Timestamp,
    precision: str = "EXACT_TIMESTAMP",
    cash_cents: Decimal = Decimal(0),
) -> dict[str, Any]:
    source_table = "rights_issues" if kind == "RISK_RIGHTS" else "distributions"
    row = {
        "protocol_arm": "V30_AMOUNT_1X_TO_2X_CAP25",
        "gap_id": "gap-1",
        "candidate_symbol": SYMBOL,
        "event_id": event_id,
        "raw_event_id": f"raw-{event_id}",
        "raw_revision_id": f"revision-{event_id}",
        "vintage_id": "official-full-current-snapshot-v5",
        "source_row_hash": hashlib.sha256(
            f"source:{event_id}:{effective_offset}".encode()
        ).hexdigest(),
        "permitted_projection_sha256": "0" * 64,
        "raw_symbol": "000001",
        "canonical_symbol": SYMBOL,
        "action_kind": kind,
        "effective_date": pd.Timestamp(calendar[1 + effective_offset]["trade_date"]),
        "known_at": known_at,
        "available_at": known_at,
        "known_at_precision": precision,
        "cash_cents_per_original_share": float(cash_cents),
        "share_multiplier": 2.0 if kind == "RISK_SHARE" else 1.0,
        "rights_ratio": 0.1 if kind == "RISK_RIGHTS" else 0.0,
        "rights_price_cents": 500.0 if kind == "RISK_RIGHTS" else 0.0,
        "source_terms_complete": True,
        "snapshot_id": "qd010-vintage-raw-id",
        "source_table": source_table,
        "source_locator": f"normalized/{source_table}.parquet",
        "source_partition_sha256": V30.QD010_SOURCE_SHA256[source_table],
    }
    event = V30.ActionEvent(
        protocol_arm=row["protocol_arm"],
        gap_id=row["gap_id"],
        candidate_symbol=row["candidate_symbol"],
        event_id=row["event_id"],
        raw_event_id=row["raw_event_id"],
        raw_revision_id=row["raw_revision_id"],
        vintage_id=row["vintage_id"],
        source_row_hash=row["source_row_hash"],
        permitted_projection_sha256=row["permitted_projection_sha256"],
        raw_symbol=row["raw_symbol"],
        canonical_symbol=row["canonical_symbol"],
        action_kind=row["action_kind"],
        effective_date=pd.Timestamp(row["effective_date"]),
        known_at=pd.Timestamp(row["known_at"]),
        available_at=pd.Timestamp(row["available_at"]),
        known_at_precision=row["known_at_precision"],
        cash_cents_per_original_share=row["cash_cents_per_original_share"],
        share_multiplier=row["share_multiplier"],
        rights_ratio=row["rights_ratio"],
        rights_price_cents=row["rights_price_cents"],
        source_terms_complete=row["source_terms_complete"],
        snapshot_id=row["snapshot_id"],
        source_table=row["source_table"],
        source_locator=row["source_locator"],
        source_partition_sha256=row["source_partition_sha256"],
    )
    row["permitted_projection_sha256"] = V30.normalized_json_sha256(V30._action_row_payload(event))
    return row


def _rehash_action(row: dict[str, Any]) -> None:
    event = V30.ActionEvent(
        protocol_arm=row["protocol_arm"],
        gap_id=row["gap_id"],
        candidate_symbol=row["candidate_symbol"],
        event_id=row["event_id"],
        raw_event_id=row["raw_event_id"],
        raw_revision_id=row["raw_revision_id"],
        vintage_id=row["vintage_id"],
        source_row_hash=row["source_row_hash"],
        permitted_projection_sha256=row["permitted_projection_sha256"],
        raw_symbol=row["raw_symbol"],
        canonical_symbol=row["canonical_symbol"],
        action_kind=row["action_kind"],
        effective_date=pd.Timestamp(row["effective_date"]),
        known_at=pd.Timestamp(row["known_at"]),
        available_at=pd.Timestamp(row["available_at"]),
        known_at_precision=row["known_at_precision"],
        cash_cents_per_original_share=row["cash_cents_per_original_share"],
        share_multiplier=row["share_multiplier"],
        rights_ratio=row["rights_ratio"],
        rights_price_cents=row["rights_price_cents"],
        source_terms_complete=row["source_terms_complete"],
        snapshot_id=row["snapshot_id"],
        source_table=row["source_table"],
        source_locator=row["source_locator"],
        source_partition_sha256=row["source_partition_sha256"],
    )
    row["permitted_projection_sha256"] = V30.normalized_json_sha256(V30._action_row_payload(event))


def _action_envelope(
    calendar_value: list[dict[str, Any]], rows: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    raw_rows = list(rows or [])
    calendar = V30.normalize_market_calendar(calendar_value)
    entry = V30.normalize_accepted_entry(_entry(calendar_value), calendar)
    events = tuple(
        sorted(
            (V30._normalize_action(row, entry) for row in raw_rows),
            key=lambda item: (item.known_at, item.effective_date, item.event_id, item.raw_event_id),
        )
    )
    terminal_date = calendar[entry.entry_calendar_index + V30.TERMINAL_OFFSET].trade_date
    knowledge_cutoff = terminal_date + pd.Timedelta(hours=15)
    snapshot_id = events[0].snapshot_id if events else "qd010-query-snapshot"
    vintage_id = events[0].vintage_id if events else "official-full-current-snapshot-v5"
    counts = tuple(
        (source, sum(event.source_table == source for event in events))
        for source in sorted(V30.QD010_SOURCE_SHA256)
    )
    scope_sha = V30.normalized_json_sha256(
        V30._action_query_scope_payload(
            entry,
            terminal_date=terminal_date,
            knowledge_cutoff=knowledge_cutoff,
            snapshot_id=snapshot_id,
            vintage_id=vintage_id,
        )
    )
    ledger_sha = V30.normalized_json_sha256(V30._action_ledger_payload(events))
    completeness_sha = V30.normalized_json_sha256(
        V30._action_completeness_payload(
            query_scope_sha256=scope_sha,
            source_counts=counts,
            raw_source_match_count=len(events),
            projected_row_count=len(events),
            normalized_ledger_sha256=ledger_sha,
            snapshot_id=snapshot_id,
            vintage_id=vintage_id,
        )
    )
    return {
        "envelope_type": V30.ACTION_ENVELOPE_TYPE,
        "protocol_arm": entry.protocol_arm,
        "gap_id": entry.gap_id,
        "candidate_symbol": entry.symbol,
        "query_predicate": V30.ACTION_QUERY_PREDICATE,
        "effective_date_min_exclusive": entry.entry_date,
        "effective_date_max_inclusive": terminal_date,
        "knowledge_cutoff": knowledge_cutoff,
        "expected_source_partitions": dict(V30.QD010_SOURCE_SHA256),
        "canonical_symbol_reference_sha256": (V30.QD010_CANONICAL_SYMBOL_REFERENCE_SHA256),
        "source_match_count_by_partition": dict(counts),
        "raw_source_match_count": len(events),
        "projected_row_count": len(events),
        "query_complete": True,
        "snapshot_id": snapshot_id,
        "vintage_id": vintage_id,
        "normalized_ledger_sha256": ledger_sha,
        "query_scope_sha256": scope_sha,
        "completeness_sha256": completeness_sha,
        "rows": raw_rows,
    }


def _evaluate(
    *,
    minute: dict[int, list[dict[str, Any]]],
    daily: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> Any:
    calendar = _calendar()
    return V30.evaluate_one_outcome(
        _entry(calendar),
        daily or _daily_rows(calendar),
        minute,
        _action_envelope(calendar, actions),
        calendar,
    )


class _GuardedMapping(Mapping[str, Any]):
    def __init__(self, row: Mapping[str, Any], denied: set[str]) -> None:
        self._row = dict(row)
        self._denied = denied
        self.denied_reads: list[str] = []

    def __getitem__(self, key: str) -> Any:
        if key in self._denied:
            self.denied_reads.append(key)
            raise AssertionError(f"future physical field was opened: {key}")
        return self._row[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._row)

    def __len__(self) -> int:
        return len(self._row)


def test_production_calendar_binding_is_exact_and_rejects_self_consistent_toy_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = (
        973,
        pd.Timestamp("2018-01-02"),
        pd.Timestamp("2021-12-31"),
        "bf5da2b2e1436758b59086d3a6cb29952ed9b3385309c7e445876f8b18490e8a",
        "220988be72d36581dfbf279730116ae34427df21f192fca2cd7972f1c67b3676",
    )
    assert PRODUCTION_CALENDAR_BINDING == expected
    for field, value in zip(
        (
            "FROZEN_CALENDAR_ROW_COUNT",
            "FROZEN_CALENDAR_MIN_DATE",
            "FROZEN_CALENDAR_MAX_DATE",
            "FROZEN_CALENDAR_CANONICAL_SHA256",
            "FROZEN_CALENDAR_NEWLINE_SHA256",
        ),
        expected,
        strict=True,
    ):
        monkeypatch.setattr(V30, field, value)
    with pytest.raises(V30.V30StageBError, match="973-row CY033 calendar"):
        V30.normalize_market_calendar(_calendar())


def test_qd010_sql_semantics_and_accepted_candidate_grammar_are_separate() -> None:
    assert V30.canonicalize_qd010_symbol("000001") == "000001.SZ"
    assert V30.canonicalize_qd010_symbol("600000") == "600000.SH"
    assert V30.canonicalize_qd010_symbol("920001") == "920001.BJ"
    assert V30.canonicalize_qd010_symbol("830001") == "830001.BJ"
    assert V30.canonicalize_qd010_symbol("anything.sz") == "ANYTHING.SZ"
    assert V30.canonical_candidate_symbol("000001.SZ") == "000001.SZ"
    with pytest.raises(V30.UnknownEvidence):
        V30.canonical_candidate_symbol("000001")
    with pytest.raises(V30.UnknownEvidence):
        V30.canonical_candidate_symbol("920001.BJ")
    with pytest.raises(V30.UnknownEvidence):
        V30.canonicalize_qd010_symbol("000001 ")


def test_integer_coordinates_reject_string_and_float_impersonators() -> None:
    assert V30._exact_int(np.int64(7), "native integer") == 7
    for impostor in ("7", 7.0, Decimal(7)):
        with pytest.raises(V30.UnknownEvidence, match="exact integer"):
            V30._exact_int(impostor, "impostor")


@pytest.mark.parametrize(
    "fields",
    (
        V30.CALENDAR_FIELDS,
        V30.ACCEPTED_ENTRY_FIELDS,
        V30.DAILY_PROJECTION_FIELDS,
        V30.MINUTE_SCAFFOLD_FIELDS,
        V30.ACTION_PROJECTION_FIELDS,
        V30.ACTION_ENVELOPE_FIELDS,
    ),
)
def test_every_runner_projection_rejects_reordered_keys(fields: tuple[str, ...]) -> None:
    row = {field: None for field in reversed(fields)}
    with pytest.raises(V30.UnknownEvidence, match="reordered fields"):
        V30._require_exact_fields(row, fields, "synthetic boundary")


def test_dataframe_projection_is_checked_before_rows_are_materialized() -> None:
    frame = pd.DataFrame(columns=tuple(reversed(V30.CALENDAR_FIELDS)))
    with pytest.raises(V30.UnknownEvidence, match="exact ordered projection"):
        V30._records(
            frame,
            "calendar",
            expected_fields=V30.CALENDAR_FIELDS,
        )


def test_local_timestamp_rejects_aware_and_padded_equivalents() -> None:
    for value in (
        pd.Timestamp("2021-01-04 09:30", tz="Asia/Shanghai"),
        " 2021-01-04 09:30",
    ):
        with pytest.raises(V30.UnknownEvidence):
            V30._local_timestamp(value, "local clock")


def test_grid_is_exactly_241_and_float32_codec_rejects_non_source_widening() -> None:
    assert len(V30.EXPECTED_BAR_END_TIMES) == 241
    assert V30.EXPECTED_BAR_END_TIMES[0].strftime("%H:%M") == "09:30"
    assert V30.EXPECTED_BAR_END_TIMES[-1].strftime("%H:%M") == "15:00"
    assert V30.qd004_float32_cent_tick(_f32_price(935)) == 935
    with pytest.raises(V30.UnknownEvidence):
        V30.qd004_float32_cent_tick(9.3500001)


def test_all_sell_limits_use_d5_itself_and_never_repair_with_u5() -> None:
    assert V30.forced_sell_limit_tick(849, Decimal(0)) == 807
    assert V30.target_sell_limit_tick(400, 500, Decimal(0), 1000, Decimal(0)) == 950
    assert V30.target_sell_limit_tick(800, 1000, Decimal(0), 800, Decimal(0)) is None


def test_possible_partial_bars_can_only_be_resolved_by_later_same_day_full_proxy() -> None:
    calendar = _calendar()
    # A67=934 and D5=760.  Equality at 09:30 is not a fill; 80
    # shares at 09:31 cannot cover our lot; 09:32 is the first full-lot proof.
    minute = {
        1: _minute_day(
            calendar,
            1,
            overrides={0: (934, 100), 1: (935, 80), 2: (936, 10_000)},
        )
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar), _daily_rows(calendar), minute, _action_envelope(calendar), calendar
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "A67_TARGET"
    assert outcome.exit_tick == 934
    assert outcome.exit_at.strftime("%H:%M") == "09:32"
    assert outcome.holding_sessions == 1
    assert outcome.real_fill_claimed is False
    assert len(outcome.reached_evidence_sha256) >= 7
    assert len(outcome.outcome_evidence_sha256) == 64


def test_high_only_crossing_does_not_prove_fill_but_next_full_bar_does() -> None:
    calendar_value = _calendar()
    calendar = V30.normalize_market_calendar(calendar_value)
    entry = V30.normalize_accepted_entry(_entry(calendar_value), calendar)
    rows = _minute_day(calendar_value, 1, default_tick=900, overrides={1: (935, 10_000)})
    rows[0]["high"] = _f32_price(950)
    rows[0]["amount"] = 90_000.0
    rows[0]["row_sha256"] = _minute_row_sha256(rows[0])
    scan = V30._scan_session(
        rows,
        offset=1,
        entry=entry,
        calendar=calendar,
        order_limit_tick=934,
        session_reference_tick=900,
        target_order=True,
        risk_specs=(),
        events=(),
    )
    assert scan.status == "FILLED"
    assert scan.exit_tick == 934
    assert scan.exit_at.strftime("%H:%M") == "09:31"
    assert len(scan.reached_evidence_sha256) == 2


def _validated_minute_for_quantity_bound(
    *, low_tick: int, high_tick: int, volume: int, amount_cny: Decimal
) -> Any:
    return V30.ValidMinute(
        offset=1,
        trade_date=pd.Timestamp("2020-01-03"),
        bar_end_time=pd.Timestamp("2020-01-03 09:30"),
        open_tick=low_tick,
        high_tick=high_tick,
        low_tick=low_tick,
        close_tick=high_tick,
        volume=volume,
        amount=amount_cny,
        row_sha256=SHA_A,
    )


def test_ohlcva_amount_can_prove_10000_shares_above_limit_despite_low_below() -> None:
    minute = _validated_minute_for_quantity_bound(
        low_tick=900,
        high_tick=1000,
        volume=20_000,
        amount_cny=Decimal("193400"),
    )
    bound = V30.source_ohlcva_sell_quantity_lower_bound(minute, 934)
    assert bound.source_ohlcva_conditional_lower_bound_shares == 10_000
    assert bound.classification == "FULL_PROXY"
    assert bound.conservative_amount_cents == 19_340_000
    assert len(bound.evidence_sha256) == 64


def test_sell_amount_floor_prevents_binary_tail_from_inventing_the_10000th_share() -> None:
    minute = _validated_minute_for_quantity_bound(
        low_tick=934,
        high_tick=935,
        volume=10_000,
        amount_cny=Decimal("93499.99999999999"),
    )
    bound = V30.source_ohlcva_sell_quantity_lower_bound(minute, 934)
    assert bound.raw_amount_cents == Decimal("9349999.999999999")
    assert bound.conservative_amount_cents == 9_349_999
    assert bound.outward_adjustment_cents == Decimal("0.999999999")
    assert bound.source_ohlcva_conditional_lower_bound_shares == 9_999
    assert bound.classification == "POSSIBLE_PARTIAL_OR_FULL"


def test_equal_high_is_possible_but_strictly_lower_high_is_safe_no_fill() -> None:
    equality = _validated_minute_for_quantity_bound(
        low_tick=900,
        high_tick=934,
        volume=20_000,
        amount_cny=Decimal("180000"),
    )
    below = _validated_minute_for_quantity_bound(
        low_tick=900,
        high_tick=933,
        volume=20_000,
        amount_cny=Decimal("180000"),
    )
    assert (
        V30.source_ohlcva_sell_quantity_lower_bound(equality, 934).classification
        == "POSSIBLE_PARTIAL_OR_FULL"
    )
    assert (
        V30.source_ohlcva_sell_quantity_lower_bound(below, 934).classification
        == "SAFE_NO_FILL"
    )


@pytest.mark.parametrize("case", ("equality", "straddle", "sub_one_percent"))
def test_unresolved_possible_partial_at_day_end_is_unknown(case: str) -> None:
    calendar = _calendar()
    rows = _minute_day(calendar, 1, default_tick=900)
    if case == "equality":
        rows[0] = _minute_day(calendar, 1, overrides={0: (934, 10_000)})[0]
    elif case == "straddle":
        rows[0]["high"] = _f32_price(950)
        rows[0]["amount"] = 90_000.0
        rows[0]["row_sha256"] = _minute_row_sha256(rows[0])
    else:
        rows[0] = _minute_day(calendar, 1, overrides={0: (1000, 9_999)})[0]
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: rows},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "possible partial/full" in outcome.blocker
    assert len(outcome.reached_evidence_sha256) == 3 + 1 + 241


def test_forced_possible_partial_cannot_roll_to_next_session() -> None:
    calendar = _calendar()
    h3_guard = [
        _GuardedMapping(row, set(row)) for row in _minute_day(calendar, 3, default_tick=900)
    ]
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar, close_ticks={1: 849}),
        {
            1: _minute_day(calendar, 1, default_tick=900),
            2: _minute_day(
                calendar,
                2,
                default_tick=700,
                overrides={0: (1000, 9_999)},
            ),
            3: h3_guard,
        },
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "possible partial/full" in outcome.blocker
    assert all(row.denied_reads == [] for row in h3_guard)


def test_target_outside_u5_opens_no_minutes_then_retries_unchanged_target_next_day() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar, close_ticks={0: 800, 1: 900})
    guarded_h1 = [
        _GuardedMapping(row, set(row)) for row in _minute_day(calendar, 1, default_tick=950)
    ]
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {
            1: guarded_h1,
            2: _minute_day(calendar, 2, default_tick=935, overrides={0: (935, 10_000)}),
        },
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "A67_TARGET"
    assert outcome.exit_tick == 934
    assert outcome.holding_sessions == 2
    assert all(row.denied_reads == [] for row in guarded_h1)


def test_target_no_order_day_still_reads_close_and_can_schedule_failure() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar, close_ticks={0: 800, 1: 849})
    guarded_h1 = [
        _GuardedMapping(row, set(row)) for row in _minute_day(calendar, 1, default_tick=950)
    ]
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {
            1: guarded_h1,
            2: _minute_day(calendar, 2, default_tick=809, overrides={0: (809, 10_000)}),
        },
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "PIVOT_FAILURE"
    assert outcome.exit_tick == 807
    assert all(row.denied_reads == [] for row in guarded_h1)


def test_auction_order_clock_is_frozen_before_submission_and_0930_can_fill() -> None:
    calendar = _calendar()
    h1 = pd.Timestamp(calendar[2]["trade_date"])
    assert V30._order_freeze_at(h1) == h1 + pd.Timedelta(hours=9, minutes=14, seconds=59)
    assert V30._order_submitted_at(h1) == h1 + pd.Timedelta(hours=9, minutes=15)
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, overrides={0: (950, 10_000)})},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_tick == 934
    assert outcome.holding_sessions == 1


def test_partial_grid_and_missing_prefix_are_unknown_not_a_later_fill() -> None:
    calendar = _calendar()
    rows = _minute_day(calendar, 1, overrides={2: (936, 10_000)})
    _zero_minute_row(rows[1])
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: rows},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "no QD004 physical source row" in outcome.blocker


def test_early_fill_does_not_read_a_later_missing_source_cell() -> None:
    calendar = _calendar()
    rows = _minute_day(calendar, 1, overrides={0: (950, 10_000)})
    rows[200]["source_match_count"] = 0
    rows[200]["low"] = "not-opened-after-exit"
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: rows},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_tick == 934


def test_early_0930_fill_never_opens_later_minute_or_daily_physical_values() -> None:
    calendar = _calendar()
    minute_rows = _minute_day(calendar, 1, overrides={0: (950, 10_000)})
    minute_rows[200]["source_match_count"] = "invalid-if-opened"
    guarded_minute = _GuardedMapping(
        minute_rows[200], set(V30.MINUTE_PHYSICAL_FIELDS) | {"source_match_count"}
    )
    minute_rows[200] = guarded_minute  # type: ignore[assignment]
    daily_rows = _daily_rows(calendar)
    daily_rows[20]["source_match_count"] = "invalid-if-opened"
    guarded_daily = _GuardedMapping(
        daily_rows[20], set(V30.DAILY_PHYSICAL_FIELDS) | {"source_match_count"}
    )
    daily_rows[20] = guarded_daily  # type: ignore[assignment]

    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily_rows,
        {1: minute_rows},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_tick == 934
    assert guarded_minute.denied_reads == []
    assert guarded_daily.denied_reads == []


def test_reached_source_rows_require_real_projection_hashes_and_zero_rows_are_null() -> None:
    calendar = _calendar()
    minute = _minute_day(calendar, 1)
    for field in ("open", "high", "low", "close"):
        minute[0][field] = _f32_price(901)
    minute[0]["amount"] = 90_100.0
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: minute},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "permitted-projection row hash mismatch" in outcome.blocker

    daily = _daily_rows(calendar)
    daily[0]["close_tick"] = 901
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {1: _minute_day(calendar, 1)},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "permitted-projection row hash mismatch" in outcome.blocker

    fabricated_zero = _minute_day(calendar, 1)
    fabricated_zero[0]["source_match_count"] = 0
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: fabricated_zero},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "fabricates physical fields" in outcome.blocker

    wrong_snapshot = _minute_day(calendar, 1, default_tick=950)
    wrong_snapshot[0]["source_snapshot_id"] = f"QD004:{SHA_A}:{SHA_B}"
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: wrong_snapshot},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "source snapshot binding drift" in outcome.blocker


def test_daily_scaffold_is_lazy_but_a_reached_zero_match_is_unknown() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar)
    daily[1]["source_match_count"] = 0
    for field in V30.DAILY_PHYSICAL_FIELDS:
        daily[1][field] = None
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {1: _minute_day(calendar, 1, default_tick=900)},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "has no source row" in outcome.blocker


def test_actions_require_complete_typed_envelope_even_when_no_rows_match() -> None:
    calendar = _calendar()
    minute = {1: _minute_day(calendar, 1, default_tick=950)}
    naked = V30.evaluate_one_outcome(_entry(calendar), _daily_rows(calendar), minute, [], calendar)
    assert naked.outcome_status == V30.UNKNOWN_OUTCOME
    assert "typed query envelope" in naked.blocker

    complete_empty = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar),
        calendar,
    )
    assert complete_empty.outcome_status == V30.COMPLETE_OUTCOME

    broken_accounting = _action_envelope(calendar)
    broken_accounting["raw_source_match_count"] = 1
    broken = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        broken_accounting,
        calendar,
    )
    assert broken.outcome_status == V30.UNKNOWN_OUTCOME
    assert "source-match accounting" in broken.blocker


def test_action_envelope_recomputes_scope_completeness_and_raw_row_hashes() -> None:
    calendar = _calendar()
    action = _action(
        calendar,
        event_id="canonical-row",
        kind="CASH_ONLY",
        effective_offset=4,
        known_at=pd.Timestamp(calendar[2]["trade_date"]),
        cash_cents=Decimal(1),
    )
    action["raw_symbol"] = "000001.sz"
    _rehash_action(action)
    envelope = _action_envelope(calendar, [action])
    valid = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        envelope,
        calendar,
    )
    assert valid.outcome_status == V30.COMPLETE_OUTCOME

    envelope["query_scope_sha256"] = SHA_A
    invalid_scope = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        envelope,
        calendar,
    )
    assert invalid_scope.outcome_status == V30.UNKNOWN_OUTCOME
    assert "query-scope digest mismatch" in invalid_scope.blocker

    envelope = _action_envelope(calendar, [action])
    envelope["rows"][0]["cash_cents_per_original_share"] = 2.0
    invalid_row = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        envelope,
        calendar,
    )
    assert invalid_row.outcome_status == V30.UNKNOWN_OUTCOME
    assert "row hash mismatch" in invalid_row.blocker


def test_typed_action_envelope_cannot_bypass_source_accounting() -> None:
    calendar_value = _calendar()
    calendar = V30.normalize_market_calendar(calendar_value)
    entry = V30.normalize_accepted_entry(_entry(calendar_value), calendar)
    typed = V30.normalize_action_envelope(_action_envelope(calendar_value), entry, calendar)
    valid = V30.evaluate_one_outcome(
        entry,
        _daily_rows(calendar_value),
        {1: _minute_day(calendar_value, 1, default_tick=950)},
        typed,
        calendar,
    )
    assert valid.outcome_status == V30.COMPLETE_OUTCOME

    forged = replace(typed, raw_source_match_count=1)
    invalid = V30.evaluate_one_outcome(
        entry,
        _daily_rows(calendar_value),
        {1: _minute_day(calendar_value, 1, default_tick=950)},
        forged,
        calendar,
    )
    assert invalid.outcome_status == V30.UNKNOWN_OUTCOME
    assert "source-match accounting" in invalid.blocker


def test_qd004_and_qd010_raw_numeric_types_are_not_coerced() -> None:
    calendar = _calendar()
    minute = _minute_day(calendar, 1, default_tick=950)
    minute[0]["volume"] = 10_000
    invalid_minute = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: minute},
        _action_envelope(calendar),
        calendar,
    )
    assert invalid_minute.outcome_status == V30.UNKNOWN_OUTCOME
    assert "native float64 source value" in invalid_minute.blocker

    action = _action(
        calendar,
        event_id="raw-double",
        kind="CASH_ONLY",
        effective_offset=4,
        known_at=pd.Timestamp(calendar[2]["trade_date"]),
        cash_cents=Decimal(1),
    )
    envelope = _action_envelope(calendar, [action])
    envelope["rows"][0]["cash_cents_per_original_share"] = "1"
    invalid_action = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        envelope,
        calendar,
    )
    assert invalid_action.outcome_status == V30.UNKNOWN_OUTCOME
    assert "native float64 source value" in invalid_action.blocker


def test_gross_cash_adjusts_coordinates_but_performance_credit_is_zero() -> None:
    calendar = _calendar()
    signal_date = pd.Timestamp(calendar[0]["trade_date"])
    cash = _action(
        calendar,
        event_id="cash-1",
        kind="CASH_ONLY",
        effective_offset=1,
        known_at=signal_date + pd.Timedelta(hours=12),
        cash_cents=Decimal(10),
    )
    # Raw A67=934; after 10 cents cash the target is 924.  The first low=925 fills.
    minute = {1: _minute_day(calendar, 1, overrides={0: (925, 10_000)})}
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar, [cash]),
        calendar,
    )
    entry_cash = Decimal(100 * 800) * Decimal("1.002")
    exit_cash = Decimal(100 * 924) * Decimal("0.998")
    expected = (exit_cash - entry_cash) / entry_cash
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_tick == 924
    assert Decimal(outcome.gross_coordinate_cash_cents_per_original_share) == 10
    assert Decimal(outcome.cash_distribution_performance_credit_cents) == 0
    assert outcome.net_return_numerator == 924 * 998 - 800 * 1002
    assert outcome.net_return_denominator == 800 * 1002
    assert outcome.net_return == V30._fraction_display_text(
        V30.Fraction(outcome.net_return_numerator, outcome.net_return_denominator)
    )
    assert abs(Decimal(outcome.net_return) - expected) < Decimal("1e-18")


def test_same_day_day_only_cash_is_unknown_and_cannot_lower_target() -> None:
    calendar = _calendar()
    effective_date = pd.Timestamp(calendar[2]["trade_date"])
    cash = _action(
        calendar,
        event_id="cash-day-only",
        kind="CASH_ONLY",
        effective_offset=1,
        known_at=effective_date,
        precision="DAY_ONLY",
        cash_cents=Decimal(10),
    )
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, overrides={0: (925, 10_000)})},
        _action_envelope(calendar, [cash]),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "effective-session open" in outcome.blocker


def test_failure_is_close_only_then_forced_order_starts_next_session() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar, close_ticks={1: 849})
    minute = {
        1: _minute_day(calendar, 1, default_tick=900),
        # H2 D5 from 849 is 807; equality first, then strict fill at 808.
        2: _minute_day(
            calendar, 2, default_tick=700, overrides={0: (807, 10_000), 1: (808, 10_000)}
        ),
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar), daily, minute, _action_envelope(calendar), calendar
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "PIVOT_FAILURE"
    assert outcome.exit_tick == 807
    assert outcome.holding_sessions == 2


def test_h10_time_trigger_first_attempts_h11_and_counts_calendar_sessions() -> None:
    calendar = _calendar()
    minute = {offset: _minute_day(calendar, offset, default_tick=900) for offset in range(1, 11)}
    minute[11] = _minute_day(calendar, 11, default_tick=857)
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "H10_TIME"
    assert outcome.holding_sessions == 11
    assert outcome.exit_tick == 855


def test_pending_failure_rolls_over_dense_physical_zero_volume_day() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar, close_ticks={1: 849, 2: 849}, suspensions={2})
    minute = {
        1: _minute_day(calendar, 1, default_tick=900),
        2: _zero_volume_minute_day(calendar, 2, flat_tick=849),
        3: _minute_day(calendar, 3, default_tick=809),
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar), daily, minute, _action_envelope(calendar), calendar
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "PIVOT_FAILURE"
    assert outcome.holding_sessions == 3


def test_cash_suspension_reference_is_deducted_once_and_carried_to_reopening() -> None:
    calendar = _calendar()
    cash = _action(
        calendar,
        event_id="cash-suspension",
        kind="CASH_ONLY",
        effective_offset=2,
        known_at=pd.Timestamp(calendar[0]["trade_date"]) + pd.Timedelta(hours=12),
        cash_cents=Decimal(10),
    )
    daily = _daily_rows(
        calendar,
        close_ticks={1: 849, 2: 839},
        suspensions={2},
        action_terms={2: ("cash-suspension", Decimal(10))},
    )
    minute = {
        1: _minute_day(calendar, 1, default_tick=900),
        2: _zero_volume_minute_day(calendar, 2, flat_tick=839),
        3: _minute_day(calendar, 3, default_tick=798),
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        minute,
        _action_envelope(calendar, [cash]),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "PIVOT_FAILURE"
    assert outcome.exit_tick == 797
    assert outcome.holding_sessions == 3
    assert Decimal(outcome.gross_coordinate_cash_cents_per_original_share) == 10
    assert Decimal(outcome.cash_distribution_performance_credit_cents) == 0


def test_zero_volume_suspension_flat_price_must_equal_computed_reference() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar, close_ticks={1: 849, 2: 849}, suspensions={2})
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {
            1: _minute_day(calendar, 1, default_tick=900),
            2: _zero_volume_minute_day(calendar, 2, flat_tick=848),
        },
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "not flat at its exchange reference" in outcome.blocker


def test_day_only_risk_cancels_target_today_but_risk_order_waits_until_tomorrow() -> None:
    calendar = _calendar()
    h1_date = pd.Timestamp(calendar[2]["trade_date"])
    risk = _action(
        calendar,
        event_id="share-1",
        kind="RISK_SHARE",
        effective_offset=4,
        known_at=h1_date,
        precision="DAY_ONLY",
    )
    # A target would have filled H1, but the date-only notice cancels it from
    # the open.  Risk execution cannot begin until H2 and fills there.
    minute = {
        1: _minute_day(calendar, 1, default_tick=950),
        2: _minute_day(calendar, 2, default_tick=857),
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar, [risk]),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "PRE_ACTION_RISK"
    assert outcome.holding_sessions == 2


def test_exact_risk_at_091459_can_submit_today_but_091500_is_too_late() -> None:
    calendar = _calendar()
    h1_date = pd.Timestamp(calendar[2]["trade_date"])
    early = _action(
        calendar,
        event_id="risk-before-cutoff",
        kind="RISK_SHARE",
        effective_offset=3,
        known_at=h1_date + pd.Timedelta(hours=9, minutes=14, seconds=59),
    )
    early_outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=857)},
        _action_envelope(calendar, [early]),
        calendar,
    )
    assert early_outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert early_outcome.exit_reason == "PRE_ACTION_RISK"
    assert early_outcome.holding_sessions == 1

    late = _action(
        calendar,
        event_id="risk-at-submission",
        kind="RISK_SHARE",
        effective_offset=3,
        known_at=h1_date + pd.Timedelta(hours=9, minutes=15),
    )
    late_outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {
            1: _minute_day(calendar, 1, default_tick=900),
            2: _minute_day(calendar, 2, default_tick=857),
        },
        _action_envelope(calendar, [late]),
        calendar,
    )
    assert late_outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert late_outcome.exit_reason == "PRE_ACTION_RISK"
    assert late_outcome.holding_sessions == 2


def test_exact_risk_notice_inside_qualifying_target_bar_is_unknown() -> None:
    calendar = _calendar()
    h1_date = pd.Timestamp(calendar[2]["trade_date"])
    risk = _action(
        calendar,
        event_id="share-race",
        kind="RISK_SHARE",
        effective_offset=3,
        known_at=h1_date + pd.Timedelta(hours=10),
    )
    ten_am_index = [clock.strftime("%H:%M") for clock in V30.EXPECTED_BAR_END_TIMES].index("10:00")
    minute = {
        1: _minute_day(calendar, 1, default_tick=900, overrides={ten_am_index: (950, 10_000)})
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar, [risk]),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "intrabar ordering" in outcome.blocker


def test_later_known_bad_action_terms_do_not_flow_backward_before_exit() -> None:
    calendar = _calendar()
    h2_date = pd.Timestamp(calendar[3]["trade_date"])
    risk = _action(
        calendar,
        event_id="future-bad-terms",
        kind="RISK_SHARE",
        effective_offset=4,
        known_at=h2_date + pd.Timedelta(hours=10),
    )
    risk["source_terms_complete"] = False
    risk["share_multiplier"] = 1.0
    _rehash_action(risk)
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        _action_envelope(calendar, [risk]),
        calendar,
    )
    assert outcome.outcome_status == V30.COMPLETE_OUTCOME
    assert outcome.exit_reason == "A67_TARGET"


def test_action_raw_snapshot_identity_is_mandatory() -> None:
    calendar = _calendar()
    risk = _action(
        calendar,
        event_id="missing-vintage",
        kind="RISK_SHARE",
        effective_offset=4,
        known_at=pd.Timestamp(calendar[3]["trade_date"]),
    )
    envelope = _action_envelope(calendar, [risk])
    envelope["rows"][0]["snapshot_id"] = ""
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        envelope,
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "snapshot/vintage" in outcome.blocker


def test_action_event_and_revision_identity_cannot_fork_or_duplicate() -> None:
    calendar = _calendar()
    known = pd.Timestamp(calendar[3]["trade_date"])
    first = _action(
        calendar,
        event_id="forked-event",
        kind="RISK_SHARE",
        effective_offset=4,
        known_at=known,
    )
    second = _action(
        calendar,
        event_id="forked-event",
        kind="RISK_SHARE",
        effective_offset=5,
        known_at=known,
    )
    second["raw_event_id"] = "different-raw-event"
    second["raw_revision_id"] = "different-revision"
    _rehash_action(second)
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        _action_envelope(calendar, [first, second]),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "event id is duplicated" in outcome.blocker

    second["event_id"] = "different-event"
    second["raw_revision_id"] = first["raw_revision_id"]
    _rehash_action(second)
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        _action_envelope(calendar, [first, second]),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "revision id is duplicated" in outcome.blocker


def test_projection_whitelists_reject_extra_outcome_fields_and_boundary_drift() -> None:
    calendar = _calendar()
    minute = _minute_day(calendar, 1, default_tick=950)
    minute[0]["return"] = "forbidden"
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: minute},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "schema drift" in outcome.blocker

    minute = _minute_day(calendar, 1, default_tick=950)
    minute[200]["gap_id"] = "wrong-gap"
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: minute},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "candidate boundary" in outcome.blocker

    action = _action(
        calendar,
        event_id="wrong-arm-action",
        kind="RISK_SHARE",
        effective_offset=4,
        known_at=pd.Timestamp(calendar[3]["trade_date"]),
    )
    envelope = _action_envelope(calendar, [action])
    envelope["rows"][0]["protocol_arm"] = "V30_SHARE_VOLUME_1X_AMOUNT_LE_2X_CAP25"
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        {1: _minute_day(calendar, 1, default_tick=950)},
        envelope,
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "candidate boundary" in outcome.blocker


def test_stage_a_acceptance_label_is_recomputed_not_trusted() -> None:
    calendar = _calendar()
    corrupt = _entry(calendar)
    corrupt["entry_hard_valid"] = False
    with pytest.raises(V30.UnknownEvidence):
        V30.evaluate_one_outcome(
            corrupt,
            _daily_rows(calendar),
            {1: _minute_day(calendar, 1, default_tick=950)},
            _action_envelope(calendar),
            calendar,
        )

    corrupt = _entry(calendar)
    corrupt["proxy_bar_end_time"] = pd.Timestamp(corrupt["entry_date"]) + pd.Timedelta(
        hours=9, minutes=36
    )
    with pytest.raises(V30.V30StageBError, match="09:37"):
        V30.evaluate_one_outcome(
            corrupt,
            _daily_rows(calendar),
            {1: _minute_day(calendar, 1, default_tick=950)},
            _action_envelope(calendar),
            calendar,
        )

    corrupt = _entry(calendar)
    corrupt["frozen_buy_limit_tick"] = 800
    with pytest.raises(V30.V30StageBError, match="headroom"):
        V30.evaluate_one_outcome(
            corrupt,
            _daily_rows(calendar),
            {1: _minute_day(calendar, 1, default_tick=950)},
            _action_envelope(calendar),
            calendar,
        )

    corrupt = _entry(calendar)
    corrupt["future_return"] = "not allowed"
    with pytest.raises(V30.UnknownEvidence, match="schema drift"):
        V30.evaluate_one_outcome(
            corrupt,
            _daily_rows(calendar),
            {1: _minute_day(calendar, 1, default_tick=950)},
            _action_envelope(calendar),
            calendar,
        )


def test_daily_timezone_and_trade_status_are_exact_domains() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar)
    daily[0]["decision_timezone"] = "UTC"
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {1: _minute_day(calendar, 1, default_tick=950)},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "Asia/Shanghai" in outcome.blocker

    daily = _daily_rows(calendar)
    daily[0]["trade_status"] = 2
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {1: _minute_day(calendar, 1, default_tick=950)},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "0/1 domain" in outcome.blocker


def test_no_proxy_exit_through_complete_h30_is_unexited_not_zero_return() -> None:
    calendar = _calendar()
    minute = {
        offset: _minute_day(calendar, offset, default_tick=900 if offset <= 10 else 800)
        for offset in range(1, 31)
    }
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNEXITED_OUTCOME
    assert outcome.net_return is None
    normalized_calendar = V30.normalize_market_calendar(calendar)
    accepted_entry = V30.normalize_accepted_entry(_entry(calendar), normalized_calendar)
    stage_a_seal = V30._provisional_stage_a_cohort_seal([accepted_entry])
    replay_seal = V30._seal_stage_b_replay(
        stage_a_seal, [V30._accepted_seal_row(accepted_entry)], [outcome]
    )
    summary = V30.summarize_terminal_cohort(replay_seal)
    assert summary["unexited"] == 1
    assert summary["publishable"] is False


def test_h30_reached_zero_match_is_unknown_without_a_daily_resolver() -> None:
    calendar = _calendar()
    minute = {
        offset: _minute_day(calendar, offset, default_tick=900 if offset <= 10 else 800)
        for offset in range(1, 30)
    }
    minute[30] = _empty_minute_scaffold(calendar, 30)
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        _daily_rows(calendar),
        minute,
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "no QD004 physical source row" in outcome.blocker


def test_terminal_conservation_and_exact_gate_thresholds() -> None:
    outcomes = []
    exact_return = V30.Fraction(1045 * 998 - 1000 * 1002, 1000 * 1002)
    displayed_return = V30._fraction_display_text(exact_return)
    for index in range(201):
        year = 2018 + (index % 4)
        outcomes.append(
            V30._seal_outcome(
                V30.StageBOutcome(
                    protocol_arm="V30_AMOUNT_1X_TO_2X_CAP25",
                    gap_id=f"gap-{index:03d}",
                    symbol=SYMBOL,
                    signal_date=pd.Timestamp(f"{year}-06-01"),
                    entry_date=pd.Timestamp(f"{year}-06-02"),
                    entry_calendar_index=index,
                    entry_tick=1000,
                    outcome_status=V30.COMPLETE_OUTCOME,
                    exit_reason="A67_TARGET",
                    exit_date=pd.Timestamp(f"{year}-06-03"),
                    exit_at=pd.Timestamp(f"{year}-06-03 09:30:00"),
                    exit_calendar_index=index + 14,
                    exit_tick=1045,
                    holding_sessions=14,
                    gross_coordinate_cash_cents_per_original_share="4.16",
                    entry_cash_out_cents="100200",
                    exit_cash_in_cents="104291",
                    cash_distribution_performance_credit_cents="0",
                    net_return_numerator=1045 * 998 - 1000 * 1002,
                    net_return_denominator=1000 * 1002,
                    net_return=displayed_return,
                ),
                (SHA_A,),
            )
        )
    accepted_rows = tuple(
        V30.AcceptedEntrySealRow(
            protocol_arm=outcome.protocol_arm,
            gap_id=outcome.gap_id,
            symbol=outcome.symbol,
            signal_date=outcome.signal_date,
            entry_date=outcome.entry_date,
            entry_evidence_sha256=hashlib.sha256(f"entry:{outcome.gap_id}".encode()).hexdigest(),
        )
        for outcome in outcomes
    )
    stage_a_seal = V30.StageACohortSeal(
        protocol_arm="V30_AMOUNT_1X_TO_2X_CAP25",
        accepted_count=len(accepted_rows),
        accepted_cohort_sha256=V30._accepted_cohort_sha256(
            "V30_AMOUNT_1X_TO_2X_CAP25", accepted_rows
        ),
        accepted_key_evidence_sha256=V30._accepted_key_evidence_sha256(accepted_rows),
    )
    replay_seal = V30._seal_stage_b_replay(stage_a_seal, accepted_rows, outcomes)
    summary = V30.summarize_terminal_cohort(replay_seal)
    assert summary["terminal_conservation"] is True
    assert summary["publishable"] is True
    assert summary["development_pass"] is True
    assert summary["mean_net_return"] == displayed_return
    assert summary["median_net_return"] == displayed_return
    assert summary["mean_holding_sessions"] == "14"
    assert summary["median_holding_sessions"] == "14"
    assert summary["signals_per_year"] == "50.25"
    assert sum(item["signals"] for item in summary["annual"].values()) == 201
    assert all(item["win_rate"] == "1" for item in summary["annual"].values())
    assert all(
        item["median_net_return"] == displayed_return for item in summary["annual"].values()
    )
    assert sum(item["exit_reasons"]["A67_TARGET"] for item in summary["annual"].values()) == 201
    assert len(summary["terminal_ledger_sha256"]) == 64

    corrupted = replace(outcomes[0], net_return="0.0400000000000000001")
    with pytest.raises(V30.V30StageBError, match="outcome evidence digest"):
        V30.summarize_terminal_cohort(replace(replay_seal, outcomes=(corrupted, *outcomes[1:])))


def test_replay_stops_opening_paths_after_first_unresolved() -> None:
    calendar_value = _calendar()
    calendar = V30.normalize_market_calendar(calendar_value)
    first = V30.normalize_accepted_entry(_entry(calendar_value, gap_id="gap-1"), calendar)
    entries = [
        replace(first, gap_id=f"gap-{index:03d}", cap25_rank=(index % 25) + 1)
        for index in range(201)
    ]
    calls: list[str] = []

    def loader(entry: Any) -> Any:
        calls.append(entry.gap_id)
        return V30.StageBReplayEvidence([], {}, {})

    stage_a_seal = V30._provisional_stage_a_cohort_seal(entries)
    replay_seal = V30.replay_frozen_cohort(stage_a_seal, entries, calendar, loader)
    outcomes = replay_seal.outcomes
    assert calls == ["gap-000"]
    assert outcomes[0].outcome_status == V30.UNKNOWN_OUTCOME
    assert outcomes[1].outcome_status == V30.NOT_OPENED_OUTCOME
    assert len(outcomes) == 201

    with pytest.raises(V30.V30StageBError, match="StageBReplayEvidence"):
        V30.replay_frozen_cohort(
            stage_a_seal,
            entries,
            calendar,
            lambda entry: V30._unknown_outcome(entry, "forged caller outcome"),
        )


def test_daily_projection_cannot_smuggle_same_day_high_or_st_state() -> None:
    calendar = _calendar()
    daily = _daily_rows(calendar)
    daily[0]["high_tick"] = 999
    outcome = V30.evaluate_one_outcome(
        _entry(calendar),
        daily,
        {1: _minute_day(calendar, 1, default_tick=950)},
        _action_envelope(calendar),
        calendar,
    )
    assert outcome.outcome_status == V30.UNKNOWN_OUTCOME
    assert "schema drift" in outcome.blocker
