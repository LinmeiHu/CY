"""Bounded, fail-closed adapters for registered quant Parquet assets.

The adapter deliberately has no unbounded ``read_all`` API. Every data read
must be tied to an activated input binding, an ingest authorization, a date
range, and an explicit symbol set.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from math import isfinite
from pathlib import Path
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from .registry import (
    DataActivationError,
    DataExecutionAuthorization,
    DataOperation,
    InputBinding,
)
from .validity import ValidityAssessment, ValidityReason

SHANGHAI = ZoneInfo("Asia/Shanghai")


class QuantAssetKind(StrEnum):
    DAILY_BARS = "DAILY_BARS"
    TRADING_STATE = "TRADING_STATE"
    INDEX_DAILY = "INDEX_DAILY"
    MINUTE_BARS = "MINUTE_BARS"
    INDUSTRY_DAILY = "INDUSTRY_DAILY"
    SHARE_FLOAT_PIT = "SHARE_FLOAT_PIT"


EXPECTED_ASSET_KINDS = {
    QuantAssetKind.DAILY_BARS: "market_bars_daily",
    QuantAssetKind.TRADING_STATE: "trading_state_daily",
    QuantAssetKind.INDEX_DAILY: "index_bars_daily",
    QuantAssetKind.MINUTE_BARS: "market_bars_1min",
    QuantAssetKind.INDUSTRY_DAILY: "industry_membership_pit",
    QuantAssetKind.SHARE_FLOAT_PIT: "free_float_shares_pit",
}

REQUIRED_FIELDS = {
    QuantAssetKind.DAILY_BARS: (
        "trade_date",
        "symbol",
        "adjust",
        "open",
        "high",
        "low",
        "close",
        "preclose",
        "volume",
        "amount",
    ),
    QuantAssetKind.TRADING_STATE: (
        "trade_date",
        "symbol",
        "trade_status",
        "is_st",
        "limit_pct",
        "up_limit_price",
        "down_limit_price",
        "buy_blocked_open",
        "sell_blocked_open",
        "state_source",
    ),
    QuantAssetKind.INDEX_DAILY: (
        "trade_date",
        "index_symbol",
        "index_name",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ),
    QuantAssetKind.MINUTE_BARS: (
        "qmt_code",
        "symbol",
        "exchange",
        "period",
        "adjust",
        "trade_date",
        "bar_end_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source",
    ),
    QuantAssetKind.INDUSTRY_DAILY: (
        "trade_date",
        "symbol",
        "industry",
        "source_notice_date",
        "source_report_date",
        "source",
    ),
    QuantAssetKind.SHARE_FLOAT_PIT: (
        "qmt_code",
        "symbol",
        "exchange",
        "m_timetag",
        "m_anntime",
        "circulating_capital",
        "source",
    ),
}

IDENTITY_FIELDS = {
    QuantAssetKind.DAILY_BARS: ("trade_date", "symbol"),
    QuantAssetKind.TRADING_STATE: ("trade_date", "symbol"),
    QuantAssetKind.INDEX_DAILY: ("trade_date", "index_symbol"),
    QuantAssetKind.MINUTE_BARS: (
        "qmt_code",
        "symbol",
        "exchange",
        "period",
        "trade_date",
        "bar_end_time",
    ),
    QuantAssetKind.INDUSTRY_DAILY: ("trade_date", "symbol"),
    QuantAssetKind.SHARE_FLOAT_PIT: (
        "qmt_code",
        "m_timetag",
        "m_anntime",
    ),
}


@dataclass(frozen=True)
class QuantReadScope:
    start: date
    end: date
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise DataActivationError("quant read scope end precedes start")
        symbols = tuple(sorted({_canonical_symbol(value) for value in self.symbols}))
        if not symbols:
            raise DataActivationError("quant read scope requires at least one symbol")
        if len(symbols) > 256:
            raise DataActivationError("quant read scope exceeds the 256-symbol safety limit")
        object.__setattr__(self, "symbols", symbols)

    @property
    def calendar_days(self) -> int:
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class QuantParquetDescriptor:
    asset_id: str
    kind: QuantAssetKind
    path: Path
    rows: int
    row_groups: int
    fields: tuple[tuple[str, str], ...]
    min_trade_date: date | None
    max_trade_date: date | None


@dataclass(frozen=True)
class NormalizedQuantRecord:
    asset_id: str
    kind: QuantAssetKind
    symbol: str
    event_time: datetime
    available_at: datetime
    source: str
    snapshot_id: str
    values: Mapping[str, Any]
    validity: ValidityAssessment

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None or self.available_at.tzinfo is None:
            raise DataActivationError("normalized timestamps must be timezone-aware")
        if self.event_time > self.available_at:
            raise DataActivationError("event_time cannot follow available_at")

    @property
    def hard_valid(self) -> bool:
        return self.validity.hard_valid


def inspect_quant_parquet(
    *,
    binding: InputBinding,
    authorization: DataExecutionAuthorization,
    kind: QuantAssetKind,
    path: str | Path,
) -> QuantParquetDescriptor:
    """Inspect Parquet metadata without scanning market rows."""

    _require_operation(
        authorization,
        {DataOperation.INSPECT, DataOperation.INGEST},
        action="inspect quant Parquet",
    )
    selected = _prepare_file(binding, kind, path)
    _, parquet, _ = _pyarrow_modules()
    parquet_file = parquet.ParquetFile(selected)
    fields = tuple(
        (field.name, str(field.type)) for field in parquet_file.schema_arrow
    )
    _require_schema(kind, {name for name, _ in fields})
    date_field = (
        "m_timetag"
        if kind is QuantAssetKind.SHARE_FLOAT_PIT
        else "trade_date"
    )
    min_date, max_date = _metadata_date_bounds(parquet_file, date_field)
    metadata = parquet_file.metadata
    return QuantParquetDescriptor(
        asset_id=binding.asset.asset_id,
        kind=kind,
        path=selected,
        rows=int(metadata.num_rows),
        row_groups=int(metadata.num_row_groups),
        fields=fields,
        min_trade_date=min_date,
        max_trade_date=max_date,
    )


def iter_quant_records(
    *,
    binding: InputBinding,
    authorization: DataExecutionAuthorization,
    kind: QuantAssetKind,
    path: str | Path,
    scope: QuantReadScope,
    batch_size: int = 65_536,
) -> Iterator[NormalizedQuantRecord]:
    """Yield normalized rows from one frozen Parquet file within a bounded scope."""

    _require_operation(
        authorization,
        {DataOperation.INGEST},
        action="read quant records",
    )
    _require_scope(scope, authorization, kind)
    if batch_size < 1 or batch_size > 1_000_000:
        raise DataActivationError("batch_size must be between 1 and 1,000,000")
    selected = _prepare_file(binding, kind, path)
    pyarrow, _, dataset_module = _pyarrow_modules()
    dataset = dataset_module.dataset(selected, format="parquet")
    names = set(dataset.schema.names)
    _require_schema(kind, names)

    if kind is QuantAssetKind.SHARE_FLOAT_PIT:
        end_yyyymmdd = int(scope.end.strftime("%Y%m%d"))
        expression = (
            (dataset_module.field("m_timetag") <= end_yyyymmdd)
            & (dataset_module.field("m_anntime") <= end_yyyymmdd)
        )
    else:
        trade_date_field = dataset.schema.field("trade_date")
        expression = _date_filter(
            pyarrow=pyarrow,
            dataset_module=dataset_module,
            field_type=trade_date_field.type,
            start=scope.start,
            end=scope.end,
        )
    raw_symbol_field = _raw_symbol_field(kind)
    candidates = sorted(_raw_symbol_candidates(scope.symbols))
    expression &= dataset_module.field(raw_symbol_field).isin(candidates)
    columns = list(REQUIRED_FIELDS[kind])
    for optional in ("available_at", "snapshot_id"):
        if optional in names:
            columns.append(optional)
    scanner = dataset.scanner(
        columns=columns,
        filter=expression,
        batch_size=batch_size,
        use_threads=True,
    )
    selected_symbols = set(scope.symbols)
    for batch in scanner.to_batches():
        for row in batch.to_pylist():
            record = _normalize_row(row, binding=binding, kind=kind)
            if record.symbol not in selected_symbols:
                continue
            if kind is QuantAssetKind.SHARE_FLOAT_PIT:
                effective_date = record.values["effective_date"]
                announced_date = record.values["announced_date"]
                if effective_date > scope.end or announced_date > scope.end:
                    raise DataActivationError(
                        f"float row escaped as-of predicate: {record.symbol}"
                    )
            else:
                selected_date = _as_date(record.values["trade_date"], label="trade_date")
                if not scope.start <= selected_date <= scope.end:
                    raise DataActivationError(
                        f"row escaped date predicate: {record.symbol} {selected_date}"
                    )
            yield record


def adapt_historical_trading_rules(
    *,
    binding: InputBinding,
    authorization: DataExecutionAuthorization,
    path: str | Path,
    scope: QuantReadScope,
) -> tuple[NormalizedQuantRecord, ...]:
    """Adapt frozen historical daily trading states without synthesizing gaps."""

    records: list[NormalizedQuantRecord] = []
    seen: set[tuple[str, date]] = set()
    for record in iter_quant_records(
        binding=binding,
        authorization=authorization,
        kind=QuantAssetKind.TRADING_STATE,
        path=path,
        scope=scope,
    ):
        key = (record.symbol, record.values["trade_date"])
        if key in seen:
            raise DataActivationError(
                f"duplicate historical trading state: {key[0]} {key[1]}"
            )
        seen.add(key)
        records.append(record)
    return tuple(records)


def select_float_as_of(
    records: Iterable[NormalizedQuantRecord],
    *,
    symbol: str,
    decision_at: datetime,
) -> NormalizedQuantRecord | None:
    """Select the latest float fact both effective and known by ``decision_at``."""

    if decision_at.tzinfo is None:
        raise DataActivationError("decision_at must be timezone-aware")
    canonical_symbol = _canonical_symbol(symbol)
    eligible = [
        record
        for record in records
        if record.kind is QuantAssetKind.SHARE_FLOAT_PIT
        and record.symbol == canonical_symbol
        and record.available_at <= decision_at.astimezone(UTC)
    ]
    if not eligible:
        return None
    by_identity: dict[tuple[date, date], float] = {}
    for record in eligible:
        key = (record.values["effective_date"], record.values["announced_date"])
        value = float(record.values["circulating_capital"])
        previous = by_identity.setdefault(key, value)
        if previous != value:
            raise DataActivationError(
                f"conflicting float revisions for {canonical_symbol} at {key}"
            )
    return max(
        eligible,
        key=lambda record: (
            record.values["effective_date"],
            record.values["announced_date"],
        ),
    )


def _prepare_file(
    binding: InputBinding,
    kind: QuantAssetKind,
    path: str | Path,
) -> Path:
    expected_kind = EXPECTED_ASSET_KINDS[kind]
    if binding.asset.kind != expected_kind:
        raise DataActivationError(
            f"asset {binding.asset.asset_id} kind {binding.asset.kind!r} "
            f"cannot be read as {kind.value}"
        )
    selected = binding.verify_file(path)
    if selected.suffix.lower() not in {".parquet", ".pq"}:
        raise DataActivationError(f"quant adapter requires Parquet input: {selected}")
    return selected


def _require_operation(
    authorization: DataExecutionAuthorization,
    allowed: set[DataOperation],
    *,
    action: str,
) -> None:
    if authorization.operation not in allowed:
        expected = ", ".join(sorted(item.value for item in allowed))
        raise DataActivationError(
            f"{action} requires operation in {{{expected}}}, "
            f"got {authorization.operation.value}"
        )


def _require_scope(
    scope: QuantReadScope,
    authorization: DataExecutionAuthorization,
    kind: QuantAssetKind,
) -> None:
    if scope.start < authorization.scope_start or scope.end > authorization.scope_end:
        raise DataActivationError("quant read scope falls outside authorization scope")
    if kind is QuantAssetKind.MINUTE_BARS:
        if scope.calendar_days > 31:
            raise DataActivationError("minute reads are limited to 31 calendar days")
        if len(scope.symbols) > 64:
            raise DataActivationError("minute reads are limited to 64 symbols")
    elif scope.calendar_days > 366:
        raise DataActivationError("daily reads are limited to 366 calendar days")


def _require_schema(kind: QuantAssetKind, names: set[str]) -> None:
    missing = set(REQUIRED_FIELDS[kind]) - names
    if missing:
        raise DataActivationError(
            f"{kind.value} Parquet is missing required fields: "
            + ", ".join(sorted(missing))
        )


def _normalize_row(
    row: Mapping[str, Any],
    *,
    binding: InputBinding,
    kind: QuantAssetKind,
) -> NormalizedQuantRecord:
    _require_non_null(row, IDENTITY_FIELDS[kind], kind)
    missing_value_fields = tuple(
        name for name in REQUIRED_FIELDS[kind] if row.get(name) is None
    )
    symbol = _row_symbol(row, kind)
    reasons: list[ValidityReason] = []
    derived_available_at: datetime | None = None
    if missing_value_fields:
        reasons.append(ValidityReason.NULL_REQUIRED_FIELD)
    if kind is QuantAssetKind.SHARE_FLOAT_PIT:
        effective_date = _yyyymmdd_date(row["m_timetag"], label="m_timetag")
        announced_date = _yyyymmdd_date(row["m_anntime"], label="m_anntime")
        event_time = datetime.combine(
            effective_date,
            time(23, 59, 59),
            tzinfo=SHANGHAI,
        )
        derived_available_at = datetime.combine(
            max(effective_date, announced_date),
            time(23, 59, 59),
            tzinfo=SHANGHAI,
        )
        if row.get("circulating_capital") is not None:
            if _finite_float(
                row["circulating_capital"], label="circulating_capital"
            ) <= 0:
                reasons.append(ValidityReason.MISSING_FLOAT_SHARES)
    else:
        trade_date = _as_date(row["trade_date"], label="trade_date")
    if kind is QuantAssetKind.MINUTE_BARS:
        if str(row["period"]).strip().lower() != "1m":
            raise DataActivationError("minute period must equal 1m")
        event_time = _aware_datetime(row["bar_end_time"], label="bar_end_time")
        if event_time.astimezone(SHANGHAI).date() != trade_date:
            raise DataActivationError("bar_end_time and trade_date disagree")
        if not _is_unadjusted(row.get("adjust")):
            reasons.append(ValidityReason.PRICE_COORDINATE_MISMATCH)
        if not _has_nulls(row, ("open", "high", "low", "close", "volume", "amount")):
            _validate_ohlcv(row)
    elif kind is not QuantAssetKind.SHARE_FLOAT_PIT:
        event_time = datetime.combine(trade_date, time(15), tzinfo=SHANGHAI)
        if kind is QuantAssetKind.DAILY_BARS:
            if not _is_unadjusted(row.get("adjust")):
                reasons.append(ValidityReason.PRICE_COORDINATE_MISMATCH)
            if not _has_nulls(
                row, ("open", "high", "low", "close", "volume", "amount")
            ):
                _validate_ohlcv(row)
        elif kind is QuantAssetKind.INDEX_DAILY:
            if not _has_nulls(
                row, ("open", "high", "low", "close", "volume", "amount")
            ):
                _validate_ohlcv(row)
        elif kind is QuantAssetKind.TRADING_STATE:
            state_fields = (
                "trade_status",
                "is_st",
                "limit_pct",
                "up_limit_price",
                "down_limit_price",
                "buy_blocked_open",
                "sell_blocked_open",
            )
            if not _has_nulls(row, state_fields):
                _validate_trading_state(row)
        else:
            industry = str(row.get("industry") or "").strip()
            if not industry or industry.upper() == "UNKNOWN":
                reasons.append(ValidityReason.MISSING_SECTOR_MEMBERSHIP)
            else:
                report_value = row.get("source_report_date")
                notice_value = row.get("source_notice_date")
                if report_value is None or notice_value is None:
                    raise DataActivationError(
                        "known industry row requires report and notice dates"
                    )
                report_date = _as_date(
                    report_value,
                    label="source_report_date",
                )
                notice_date = _as_date(
                    notice_value,
                    label="source_notice_date",
                )
                if report_date > notice_date or notice_date >= trade_date:
                    raise DataActivationError(
                        "industry lineage must satisfy report_date <= notice_date "
                        "< trade_date"
                    )
                event_time = datetime.combine(
                    report_date,
                    time(23, 59, 59),
                    tzinfo=SHANGHAI,
                )
                derived_available_at = datetime.combine(
                    notice_date,
                    time(23, 59, 59),
                    tzinfo=SHANGHAI,
                )

    raw_available_at = row.get("available_at")
    has_observed_available_at = binding.asset.lineage.get("record_available_at") is True
    has_causal_available_at = (
        (
            kind
            in {
                QuantAssetKind.DAILY_BARS,
                QuantAssetKind.INDEX_DAILY,
                QuantAssetKind.MINUTE_BARS,
            }
            and binding.asset.lineage.get("available_at_from_completed_bar") is True
        )
        or (
            kind is QuantAssetKind.TRADING_STATE
            and binding.asset.lineage.get("available_at_from_completed_state_day")
            is True
        )
        or (
            kind is QuantAssetKind.INDUSTRY_DAILY
            and binding.asset.lineage.get("available_at_from_source_notice_date") is True
            and derived_available_at is not None
        )
        or (
            kind is QuantAssetKind.SHARE_FLOAT_PIT
            and binding.asset.lineage.get(
                "available_at_from_effective_and_announcement"
            )
            is True
            and derived_available_at is not None
        )
    )
    if has_observed_available_at and raw_available_at is None:
        raise DataActivationError(
            f"asset {binding.asset.asset_id} promises record available_at but row omits it"
        )
    if raw_available_at is None:
        available_at = derived_available_at or event_time
    else:
        available_at = _aware_datetime(raw_available_at, label="available_at")
    if not has_observed_available_at and not has_causal_available_at:
        reasons.append(ValidityReason.MODELED_AVAILABLE_AT)

    raw_snapshot = row.get("snapshot_id")
    has_record_snapshot = binding.asset.lineage.get("record_snapshot_id") is True
    has_frozen_input_snapshot = (
        binding.asset.lineage.get("snapshot_id_from_frozen_input") is True
        and bool(binding.sha256 or binding.inventory_manifest)
    )
    if has_record_snapshot and raw_snapshot is None:
        raise DataActivationError(
            f"asset {binding.asset.asset_id} promises record snapshot_id but row omits it"
        )
    if raw_snapshot is None:
        snapshot_id = binding.snapshot_id
    else:
        snapshot_id = str(raw_snapshot).strip()
        if not snapshot_id:
            raise DataActivationError("record snapshot_id must be non-empty")
    if not has_record_snapshot and not has_frozen_input_snapshot:
        reasons.append(ValidityReason.MISSING_RECORD_VERSION_LINEAGE)
    if event_time > available_at:
        raise DataActivationError("record event_time follows available_at")

    source_parts = [binding.source]
    source_field = (
        "source"
        if kind
        in {
            QuantAssetKind.MINUTE_BARS,
            QuantAssetKind.INDUSTRY_DAILY,
            QuantAssetKind.SHARE_FLOAT_PIT,
        }
        else "state_source"
    )
    raw_source = row.get(source_field)
    if raw_source is not None and str(raw_source).strip():
        source_parts.append(str(raw_source).strip())
    values = {name: row.get(name) for name in REQUIRED_FIELDS[kind]}
    if kind is QuantAssetKind.SHARE_FLOAT_PIT:
        values["effective_date"] = effective_date
        values["announced_date"] = announced_date
    else:
        values["trade_date"] = trade_date
    return NormalizedQuantRecord(
        asset_id=binding.asset.asset_id,
        kind=kind,
        symbol=symbol,
        event_time=event_time.astimezone(UTC),
        available_at=available_at.astimezone(UTC),
        source=" | ".join(source_parts),
        snapshot_id=snapshot_id,
        values=MappingProxyType(values),
        validity=ValidityAssessment(tuple(reasons)),
    )


def _row_symbol(row: Mapping[str, Any], kind: QuantAssetKind) -> str:
    if kind is QuantAssetKind.INDEX_DAILY:
        return _canonical_symbol(str(row["index_symbol"]))
    if kind in {QuantAssetKind.MINUTE_BARS, QuantAssetKind.SHARE_FLOAT_PIT}:
        qmt_code = str(row["qmt_code"]).strip()
        exchange = str(row["exchange"]).strip()
        symbol = _canonical_symbol(qmt_code, exchange_hint=exchange)
        raw_symbol = _canonical_symbol(str(row["symbol"]), exchange_hint=exchange)
        if symbol != raw_symbol:
            raise DataActivationError(
                f"QMT symbol identity mismatch: qmt_code={qmt_code}, "
                f"symbol={row['symbol']}, exchange={exchange}"
            )
        return symbol
    return _canonical_symbol(str(row["symbol"]))


def _canonical_symbol(value: str, *, exchange_hint: str | None = None) -> str:
    text = value.strip().upper()
    if not text:
        raise DataActivationError("symbol must be non-empty")
    if (
        len(text) == 9
        and text[:3] in {"CSI", "SHI", "SZI"}
        and text[3:].isdigit()
    ):
        return text.lower()
    if text.startswith(("SH", "SZ", "BJ")) and len(text) == 8 and text[2:].isdigit():
        text = f"{text[2:]}.{text[:2]}"
    if "." in text:
        code, exchange = text.rsplit(".", 1)
        if code.isdigit() and len(code) == 6 and exchange in {"SH", "SZ", "BJ"}:
            return f"{code}.{exchange}"
        raise DataActivationError(f"unsupported symbol format: {value}")
    if not text.isdigit() or len(text) != 6:
        raise DataActivationError(f"unsupported symbol format: {value}")
    hint = exchange_hint.strip().upper() if exchange_hint else ""
    if hint in {"SSE", "XSHG", "SHANGHAI"}:
        hint = "SH"
    elif hint in {"SZSE", "XSHE", "SHENZHEN"}:
        hint = "SZ"
    elif hint in {"BSE", "BEIJING"}:
        hint = "BJ"
    exchange = hint or _infer_exchange(text)
    if exchange not in {"SH", "SZ", "BJ"}:
        raise DataActivationError(f"unsupported exchange for symbol {value}: {exchange_hint}")
    return f"{text}.{exchange}"


def _infer_exchange(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _raw_symbol_candidates(symbols: tuple[str, ...]) -> set[str]:
    candidates: set[str] = set()
    for symbol in symbols:
        if "." not in symbol:
            candidates.update({symbol, symbol.lower(), symbol.upper()})
            continue
        code, exchange = symbol.split(".")
        candidates.update(
            {
                symbol,
                symbol.lower(),
                code,
                f"{exchange}{code}",
                f"{exchange.lower()}{code}",
            }
        )
    return candidates


def _raw_symbol_field(kind: QuantAssetKind) -> str:
    if kind is QuantAssetKind.INDEX_DAILY:
        return "index_symbol"
    if kind in {QuantAssetKind.MINUTE_BARS, QuantAssetKind.SHARE_FLOAT_PIT}:
        return "qmt_code"
    return "symbol"


def _require_non_null(
    row: Mapping[str, Any],
    names: tuple[str, ...],
    kind: QuantAssetKind,
) -> None:
    missing = [name for name in names if row.get(name) is None]
    if missing:
        raise DataActivationError(
            f"{kind.value} row has null required fields: " + ", ".join(sorted(missing))
        )


def _has_nulls(row: Mapping[str, Any], names: tuple[str, ...]) -> bool:
    return any(row.get(name) is None for name in names)


def _is_unadjusted(value: Any) -> bool:
    return str(value).strip().lower() in {"none", "raw", "unadjusted"}


def _validate_ohlcv(row: Mapping[str, Any]) -> None:
    prices = {
        name: _finite_float(row[name], label=name)
        for name in ("open", "high", "low", "close")
    }
    if min(prices.values()) <= 0:
        raise DataActivationError("OHLC prices must be positive")
    if prices["low"] > min(prices["open"], prices["close"]):
        raise DataActivationError("low exceeds the open/close envelope")
    if prices["high"] < max(prices["open"], prices["close"]):
        raise DataActivationError("high is below the open/close envelope")
    if _finite_float(row["volume"], label="volume") < 0:
        raise DataActivationError("volume must be non-negative")
    if _finite_float(row["amount"], label="amount") < 0:
        raise DataActivationError("amount must be non-negative")


def _validate_trading_state(row: Mapping[str, Any]) -> None:
    trade_status = row["trade_status"]
    if isinstance(trade_status, bool) or not isinstance(trade_status, int):
        raise DataActivationError("trade_status must be an integer")
    if trade_status not in {0, 1}:
        raise DataActivationError("trade_status must be 0 or 1")
    for name in ("is_st", "buy_blocked_open", "sell_blocked_open"):
        if not isinstance(row[name], bool):
            raise DataActivationError(f"{name} must be boolean")
    limit_pct = _finite_float(row["limit_pct"], label="limit_pct")
    if not any(abs(limit_pct - allowed) <= 1e-9 for allowed in (0.05, 0.1, 0.2, 0.3)):
        raise DataActivationError("limit_pct must use a known A-share decimal unit")
    up_limit = _finite_float(row["up_limit_price"], label="up_limit_price")
    down_limit = _finite_float(row["down_limit_price"], label="down_limit_price")
    if up_limit <= 0 or down_limit <= 0 or up_limit < down_limit:
        raise DataActivationError("daily limit prices are invalid")
    if trade_status == 0 and not (
        row["buy_blocked_open"] and row["sell_blocked_open"]
    ):
        raise DataActivationError("suspended state must block both order sides")
    if str(row["state_source"]).strip() != "baostock_none_daily":
        raise DataActivationError("unsupported historical trading-state source")


def _finite_float(value: Any, *, label: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError) as exc:
        raise DataActivationError(f"{label} must be numeric") from exc
    if not isfinite(converted):
        raise DataActivationError(f"{label} must be finite")
    return converted


def _as_date(value: Any, *, label: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DataActivationError(f"{label} must be an ISO date") from exc


def _yyyymmdd_date(value: Any, *, label: str) -> date:
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    if len(text) != 8 or not text.isdigit():
        raise DataActivationError(f"{label} must be YYYYMMDD")
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as exc:
        raise DataActivationError(f"{label} must be YYYYMMDD") from exc


def _aware_datetime(value: Any, *, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise DataActivationError(f"{label} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed


def _arrow_temporal_scalar(pyarrow: Any, field_type: Any, value: date) -> Any:
    if pyarrow.types.is_timestamp(field_type):
        raw: date | datetime = datetime.combine(value, time())
    else:
        raw = value
    return pyarrow.scalar(raw, type=field_type)


def _date_filter(
    *,
    pyarrow: Any,
    dataset_module: Any,
    field_type: Any,
    start: date,
    end: date,
) -> Any:
    field = dataset_module.field("trade_date")
    start_value = _arrow_temporal_scalar(pyarrow, field_type, start)
    if pyarrow.types.is_timestamp(field_type):
        end_exclusive = _arrow_temporal_scalar(
            pyarrow,
            field_type,
            end + timedelta(days=1),
        )
        return (field >= start_value) & (field < end_exclusive)
    end_value = _arrow_temporal_scalar(pyarrow, field_type, end)
    return (field >= start_value) & (field <= end_value)


def _metadata_date_bounds(parquet_file: Any, field_name: str) -> tuple[date | None, date | None]:
    field_index = parquet_file.schema_arrow.get_field_index(field_name)
    if field_index < 0:
        return None, None
    minima: list[date] = []
    maxima: list[date] = []
    for index in range(parquet_file.metadata.num_row_groups):
        statistics = parquet_file.metadata.row_group(index).column(field_index).statistics
        if statistics is None or not statistics.has_min_max:
            continue
        parse_date = _yyyymmdd_date if field_name == "m_timetag" else _as_date
        minima.append(parse_date(statistics.min, label=field_name))
        maxima.append(parse_date(statistics.max, label=field_name))
    return (min(minima) if minima else None, max(maxima) if maxima else None)


def _pyarrow_modules() -> tuple[Any, Any, Any]:
    try:
        pyarrow = importlib.import_module("pyarrow")
        parquet = importlib.import_module("pyarrow.parquet")
        dataset = importlib.import_module("pyarrow.dataset")
    except ImportError as exc:
        raise DataActivationError(
            "quant Parquet adapters require the optional 'data' dependencies"
        ) from exc
    return pyarrow, parquet, dataset
