"""Minimal PIT-B adapter for the frozen CNINFO corporate-action snapshot."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from math import isfinite
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .quant_adapter import QuantReadScope
from .registry import (
    DataActivationError,
    DataExecutionAuthorization,
    DataOperation,
    InputBinding,
)

if TYPE_CHECKING:
    from .pit import CorporateActionRecord

SHANGHAI = ZoneInfo("Asia/Shanghai")
UNRESOLVED = "UNRESOLVED_CORPORATE_ACTION"


@dataclass(frozen=True)
class CorporateActionIssue:
    action_id: str
    symbol: str
    blocking_date: date | None
    reason: str


@dataclass(frozen=True)
class CorporateActionBatch:
    records: tuple[CorporateActionRecord, ...]
    issues: tuple[CorporateActionIssue, ...]
    distribution_rows_seen: int
    rights_rows_seen: int


def adapt_cninfo_corporate_actions(
    *,
    binding: InputBinding,
    authorization: DataExecutionAuthorization,
    scope: QuantReadScope,
    distributions_path: str | Path,
    rights_path: str | Path,
    run_id: str,
) -> CorporateActionBatch:
    """Adapt two frozen CNINFO Parquets into causal corporate-action records.

    This is intentionally a PIT-B adapter. The source is an official current
    snapshot without a historical revision stream. A row is usable only from
    ``known_at``; late, incomplete, or dimensionally invalid rows become an
    explicit blocking action instead of being silently repaired.
    """

    if authorization.operation is not DataOperation.INGEST:
        raise DataActivationError("corporate-action adaptation requires INGEST")
    if scope.start < authorization.scope_start or scope.end > authorization.scope_end:
        raise DataActivationError("corporate-action scope falls outside authorization")
    if scope.calendar_days > 366:
        raise DataActivationError("corporate-action reads are limited to 366 calendar days")
    if binding.asset.kind != "corporate_actions_pit":
        raise DataActivationError("binding is not a corporate_actions_pit asset")
    if not run_id.strip():
        raise DataActivationError("run_id must be non-empty")

    distributions = binding.verify_file(distributions_path)
    rights = binding.verify_file(rights_path)
    symbol_by_code = {symbol[:6]: symbol for symbol in scope.symbols}
    records: list[CorporateActionRecord] = []
    issues: list[CorporateActionIssue] = []

    distribution_rows = 0
    for row in _iter_parquet_rows(distributions):
        symbol = symbol_by_code.get(str(row.get("symbol") or "").zfill(6))
        if symbol is None:
            continue
        action_id = _required_text(row, "event_id")
        known_at = _timestamp(row.get("known_at"), label="known_at")
        effective_date = _optional_date(row.get("effective_date"))
        processing_date = _processing_date(known_at, effective_date)
        if not scope.start <= processing_date <= scope.end:
            continue
        distribution_rows += 1
        source = _source(binding, row)
        event_time = _event_time(row, known_at)
        reason = _distribution_problem(row, known_at, effective_date)
        if reason is not None:
            records.append(
                _blocking_record(
                    action_id=action_id,
                    symbol=symbol,
                    blocking_date=processing_date,
                    event_time=event_time,
                    available_at=known_at,
                    source=source,
                    binding=binding,
                    revision_id=_revision_id(row),
                    run_id=run_id,
                )
            )
            issues.append(CorporateActionIssue(action_id, symbol, processing_date, reason))
            continue

        assert effective_date is not None
        multiplier = _optional_number(row.get("share_multiplier")) or 1.0
        cash = _optional_number(row.get("cash_per_share_gross")) or 0.0
        if multiplier > 1.0:
            records.append(
                _record(
                    action_id=f"{action_id}:share",
                    symbol=symbol,
                    action_type="SPLIT",
                    ex_date=effective_date,
                    event_time=event_time,
                    available_at=known_at,
                    source=source,
                    binding=binding,
                    revision_id=_revision_id(row),
                    run_id=run_id,
                    ratio=multiplier,
                )
            )
        if cash > 0.0:
            records.append(
                _record(
                    action_id=f"{action_id}:cash",
                    symbol=symbol,
                    action_type="CASH_DIVIDEND",
                    ex_date=effective_date,
                    event_time=event_time,
                    available_at=known_at,
                    source=source,
                    binding=binding,
                    revision_id=_revision_id(row),
                    run_id=run_id,
                    cash_per_share=cash,
                )
            )

    rights_rows = 0
    for row in _iter_parquet_rows(rights):
        symbol = symbol_by_code.get(str(row.get("symbol") or "").zfill(6))
        if symbol is None:
            continue
        action_id = _required_text(row, "event_id")
        known_at = _timestamp(row.get("known_at"), label="known_at")
        effective_date = _optional_date(row.get("effective_date"))
        processing_date = _processing_date(known_at, effective_date)
        if not scope.start <= processing_date <= scope.end:
            continue
        rights_rows += 1
        source = _source(binding, row)
        event_time = _event_time(row, known_at)
        reason = _rights_problem(row, known_at, effective_date)
        if reason is not None:
            records.append(
                _blocking_record(
                    action_id=action_id,
                    symbol=symbol,
                    blocking_date=processing_date,
                    event_time=event_time,
                    available_at=known_at,
                    source=source,
                    binding=binding,
                    revision_id=_revision_id(row),
                    run_id=run_id,
                )
            )
            issues.append(CorporateActionIssue(action_id, symbol, processing_date, reason))
            continue

        assert effective_date is not None
        records.append(
            _record(
                action_id=f"{action_id}:rights",
                symbol=symbol,
                action_type="RIGHTS_ISSUE",
                ex_date=effective_date,
                event_time=event_time,
                available_at=known_at,
                source=source,
                binding=binding,
                revision_id=_revision_id(row),
                run_id=run_id,
                ratio=_optional_number(row.get("rights_subscription_ratio")),
                issue_price=_optional_number(row.get("rights_subscription_price")),
            )
        )

    action_order = {
        "SPLIT": 0,
        "CASH_DIVIDEND": 1,
        UNRESOLVED: 2,
        "RIGHTS_ISSUE": 3,
    }
    records.sort(
        key=lambda item: (
            item.ex_date,
            item.symbol,
            action_order.get(item.action_type, 99),
            item.action_id,
        )
    )
    issues.sort(key=lambda item: (item.blocking_date or date.max, item.symbol, item.action_id))
    return CorporateActionBatch(
        records=tuple(records),
        issues=tuple(issues),
        distribution_rows_seen=distribution_rows,
        rights_rows_seen=rights_rows,
    )


def _iter_parquet_rows(path: Path) -> Iterator[dict[str, Any]]:
    parquet = importlib.import_module("pyarrow.parquet")
    parquet_file = parquet.ParquetFile(path)
    for batch in parquet_file.iter_batches(batch_size=16_384):
        yield from batch.to_pylist()


def _distribution_problem(
    row: dict[str, Any], known_at: datetime, effective_date: date | None
) -> str | None:
    announcement = _optional_date(row.get("announcement_date"))
    if announcement is not None and announcement > known_at.astimezone(SHANGHAI).date():
        return "announcement_date follows known_at"
    if effective_date is None:
        return "missing effective_date"
    if known_at.astimezone(SHANGHAI).date() > effective_date:
        return "known_at follows effective_date"
    if row.get("source_terms_complete") is not True:
        return "distribution terms are incomplete"
    multiplier = _optional_number(row.get("share_multiplier"))
    cash = _optional_number(row.get("cash_per_share_gross"))
    if multiplier is not None and (multiplier <= 0.0 or multiplier > 100.0):
        return "share_multiplier unit anomaly"
    if cash is not None and (cash < 0.0 or cash > 100_000.0):
        return "cash_per_share_gross unit anomaly"
    if (multiplier or 1.0) > 1.0 and row.get("execution_timing_resolved") is not True:
        return "share-credit timing is unresolved"
    if (multiplier is None or multiplier <= 1.0) and (cash is None or cash <= 0.0):
        return "distribution has no positive economic terms"
    return None


def _rights_problem(
    row: dict[str, Any], known_at: datetime, effective_date: date | None
) -> str | None:
    announcement = _optional_date(row.get("announcement_date"))
    if announcement is not None and announcement > known_at.astimezone(SHANGHAI).date():
        return "announcement_date follows known_at"
    if effective_date is None:
        return "missing effective_date"
    if known_at.astimezone(SHANGHAI).date() > effective_date:
        return "known_at follows effective_date"
    if row.get("source_terms_complete") is not True:
        return "rights terms are incomplete"
    ratio = _optional_number(row.get("rights_subscription_ratio"))
    price = _optional_number(row.get("rights_subscription_price"))
    if ratio is None or ratio <= 0.0 or ratio > 100.0:
        return "rights_subscription_ratio unit anomaly"
    if price is None or price < 0.0 or price > 1_000_000.0:
        return "rights_subscription_price unit anomaly"
    return None


def _blocking_record(
    *,
    action_id: str,
    symbol: str,
    blocking_date: date,
    event_time: datetime,
    available_at: datetime,
    source: str,
    binding: InputBinding,
    revision_id: str,
    run_id: str,
) -> CorporateActionRecord:
    effective = max(blocking_date, available_at.astimezone(SHANGHAI).date())
    return _record(
        action_id=f"{action_id}:unresolved",
        symbol=symbol,
        action_type=UNRESOLVED,
        ex_date=effective,
        event_time=min(event_time, available_at),
        available_at=available_at,
        source=source,
        binding=binding,
        revision_id=revision_id,
        run_id=run_id,
    )


def _record(
    *,
    action_id: str,
    symbol: str,
    action_type: str,
    ex_date: date,
    event_time: datetime,
    available_at: datetime,
    source: str,
    binding: InputBinding,
    revision_id: str,
    run_id: str,
    ratio: float | None = None,
    cash_per_share: float | None = None,
    issue_price: float | None = None,
) -> CorporateActionRecord:
    from .pit import CorporateActionRecord

    if available_at.astimezone(SHANGHAI).date() > ex_date:
        raise DataActivationError("corporate action cannot be effective before available_at")
    effective_from = datetime.combine(ex_date, time.min, tzinfo=SHANGHAI)
    return CorporateActionRecord(
        action_id=action_id,
        symbol=symbol,
        action_type=action_type,
        ex_date=ex_date,
        event_time=event_time.astimezone(UTC),
        available_at=available_at.astimezone(UTC),
        effective_from=effective_from.astimezone(UTC),
        source=source,
        snapshot_id=binding.snapshot_id,
        revision_id=revision_id,
        run_id=run_id,
        ratio=ratio,
        cash_per_share=cash_per_share,
        issue_price=issue_price,
    )


def _processing_date(known_at: datetime, effective_date: date | None) -> date:
    known_date = known_at.astimezone(SHANGHAI).date()
    if effective_date is None or known_date > effective_date:
        return known_date
    return effective_date


def _event_time(row: dict[str, Any], known_at: datetime) -> datetime:
    announcement = _optional_date(row.get("announcement_date"))
    if announcement is None:
        return known_at
    return datetime.combine(announcement, time.min, tzinfo=SHANGHAI)


def _timestamp(value: Any, *, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise DataActivationError(f"{label} must be a timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _optional_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise DataActivationError("corporate-action date has unsupported type")


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not isfinite(number):
        raise DataActivationError("corporate-action number must be finite")
    return number


def _required_text(row: dict[str, Any], field: str) -> str:
    value = str(row.get(field) or "").strip()
    if not value:
        raise DataActivationError(f"corporate-action row requires {field}")
    return value


def _revision_id(row: dict[str, Any]) -> str:
    value = str(row.get("revision_id") or row.get("row_hash") or "").strip()
    if not value:
        raise DataActivationError("corporate-action row lacks revision lineage")
    return value


def _source(binding: InputBinding, row: dict[str, Any]) -> str:
    raw = str(row.get("source") or "").strip()
    return f"{binding.source} | {raw}" if raw else binding.source
