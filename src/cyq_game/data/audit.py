"""Deterministic, bounded audits for normalized quant records.

The audit layer does not upgrade data validity.  It records reproducible PASS,
FAIL, or NOT_RUN evidence and keeps missing expectations or joins fail closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .quant_adapter import SHANGHAI, NormalizedQuantRecord, QuantReadScope
from .registry import REQUIRED_AUDITS, DataActivationError

MAX_EVIDENCE_ITEMS = 20
DEFAULT_MAX_RECORDS = 5_000_000


class AuditStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True, order=True)
class RecordKey:
    """The canonical strategy-feed identity for one observed bar or state."""

    symbol: str
    event_time: datetime

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DataActivationError("audit record key symbol must be non-empty")
        if self.event_time.tzinfo is None:
            raise DataActivationError("audit record key event_time must be timezone-aware")

    def render(self) -> str:
        return f"{self.symbol}@{self.event_time.isoformat()}"


@dataclass(frozen=True)
class AuditCheck:
    status: AuditStatus
    examined: int
    issue_count: int
    evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.examined < 0 or self.issue_count < 0:
            raise ValueError("audit counts must be non-negative")
        if self.status is AuditStatus.PASS and self.issue_count != 0:
            raise ValueError("a passing audit cannot contain issues")
        if self.status is AuditStatus.FAIL and self.issue_count == 0:
            raise ValueError("a failing audit must contain at least one issue")
        if self.status is AuditStatus.NOT_RUN and self.issue_count != 0:
            raise ValueError("a skipped audit cannot contain issues")
        if any(not item.strip() for item in self.evidence):
            raise ValueError("audit evidence entries must be non-empty")

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "examined": self.examined,
            "issue_count": self.issue_count,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class DataAuditReport:
    scope_start: date
    scope_end: date
    row_count: int
    symbol_count: int
    asset_ids: tuple[str, ...]
    asset_kinds: tuple[str, ...]
    checks: Mapping[str, AuditCheck]

    def __post_init__(self) -> None:
        if self.scope_end < self.scope_start:
            raise ValueError("audit scope end precedes start")
        if self.row_count < 0 or self.symbol_count < 0:
            raise ValueError("audit counts must be non-negative")
        if set(self.checks) != set(REQUIRED_AUDITS):
            raise ValueError("audit report must contain exactly the required audits")
        object.__setattr__(self, "asset_ids", tuple(sorted(set(self.asset_ids))))
        object.__setattr__(self, "asset_kinds", tuple(sorted(set(self.asset_kinds))))
        object.__setattr__(
            self,
            "checks",
            MappingProxyType({name: self.checks[name] for name in REQUIRED_AUDITS}),
        )

    @property
    def all_passed(self) -> bool:
        return all(check.status is AuditStatus.PASS for check in self.checks.values())

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self._content()).encode()).hexdigest()

    @property
    def audit_id(self) -> str:
        return f"CYQ-AUDIT-{self.content_sha256[:20]}"

    def _content(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "scope": {
                "start": self.scope_start.isoformat(),
                "end": self.scope_end.isoformat(),
            },
            "row_count": self.row_count,
            "symbol_count": self.symbol_count,
            "asset_ids": list(self.asset_ids),
            "asset_kinds": list(self.asset_kinds),
            "checks": {
                name: self.checks[name].as_dict() for name in REQUIRED_AUDITS
            },
        }

    def as_dict(self) -> dict[str, Any]:
        payload = self._content()
        payload["audit_id"] = self.audit_id
        payload["content_sha256"] = self.content_sha256
        return payload


@dataclass
class _IssueCollector:
    count: int = 0
    evidence: list[str] | None = None

    def add(self, message: str, *, count: int = 1) -> None:
        if count < 1:
            raise ValueError("audit issue increment must be positive")
        self.count += count
        if self.evidence is None:
            self.evidence = []
        if len(self.evidence) < MAX_EVIDENCE_ITEMS:
            self.evidence.append(message)

    def check(self, examined: int) -> AuditCheck:
        if self.count:
            return AuditCheck(
                status=AuditStatus.FAIL,
                examined=examined,
                issue_count=self.count,
                evidence=tuple(self.evidence or ()),
            )
        return AuditCheck(
            status=AuditStatus.PASS,
            examined=examined,
            issue_count=0,
        )


def audit_normalized_records(
    records: Iterable[NormalizedQuantRecord],
    *,
    scope: QuantReadScope,
    expected_keys: Set[RecordKey] | None = None,
    required_records_by_role: Mapping[
        str, Iterable[NormalizedQuantRecord]
    ] | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> DataAuditReport:
    """Run the five mandatory audits over an explicitly bounded data slice.

    Coverage remains NOT_RUN unless the caller supplies an independently built
    expected key universe. Cross-table consistency remains NOT_RUN unless every
    mandatory joined role is supplied.
    """

    bounded = _bounded_records(records, max_records=max_records, label="primary")
    keys = tuple(_record_key(record) for record in bounded)
    checks: dict[str, AuditCheck] = {
        "coverage": _audit_coverage(keys, expected_keys, max_records=max_records),
        "duplicates": _audit_duplicates(keys),
        "time_travel": _audit_time_travel(bounded),
        "consistency": _audit_consistency(bounded, scope=scope),
        "cross_table": audit_cross_table_keys(
            bounded,
            required_records_by_role,
            max_records=max_records,
        ),
    }
    return DataAuditReport(
        scope_start=scope.start,
        scope_end=scope.end,
        row_count=len(bounded),
        symbol_count=len({record.symbol for record in bounded}),
        asset_ids=tuple(record.asset_id for record in bounded),
        asset_kinds=tuple(record.kind.value for record in bounded),
        checks=checks,
    )


def audit_cross_table_keys(
    primary_records: Iterable[NormalizedQuantRecord],
    required_records_by_role: Mapping[
        str, Iterable[NormalizedQuantRecord]
    ] | None,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
) -> AuditCheck:
    """Require every primary key to be represented in every supplied input role."""

    primary = _bounded_records(
        primary_records,
        max_records=max_records,
        label="cross-table primary",
    )
    if not required_records_by_role:
        return AuditCheck(
            status=AuditStatus.NOT_RUN,
            examined=len(primary),
            issue_count=0,
            evidence=("mandatory cross-table roles were not supplied",),
        )
    primary_keys = {_record_key(record) for record in primary}
    issues = _IssueCollector()
    for role in sorted(required_records_by_role):
        if not role.strip():
            raise DataActivationError("cross-table role must be non-empty")
        required = _bounded_records(
            required_records_by_role[role],
            max_records=max_records,
            label=f"cross-table role {role}",
        )
        role_keys = {_record_key(record) for record in required}
        missing = sorted(primary_keys - role_keys)
        for key in missing[:MAX_EVIDENCE_ITEMS]:
            issues.add(f"role={role} missing {key.render()}")
        omitted = len(missing) - min(len(missing), MAX_EVIDENCE_ITEMS)
        if omitted:
            issues.count += omitted
    return issues.check(len(primary_keys) * len(required_records_by_role))


def write_audit_evidence(report: DataAuditReport, output_dir: str | Path) -> Path:
    """Write immutable, content-addressed audit evidence without overwriting."""

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{report.audit_id}.json"
    content = (
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise DataActivationError(f"audit evidence identity collision: {path}")
        return path
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise DataActivationError(f"audit evidence appeared concurrently: {path}") from exc
    return path


def _audit_coverage(
    observed_keys: tuple[RecordKey, ...],
    expected_keys: Set[RecordKey] | None,
    *,
    max_records: int,
) -> AuditCheck:
    if expected_keys is None:
        return AuditCheck(
            status=AuditStatus.NOT_RUN,
            examined=len(observed_keys),
            issue_count=0,
            evidence=("independent expected key universe was not supplied",),
        )
    if len(expected_keys) > max_records:
        raise DataActivationError(
            f"coverage expected key universe exceeds safety limit {max_records}"
        )
    if not expected_keys:
        return AuditCheck(
            status=AuditStatus.FAIL,
            examined=len(observed_keys),
            issue_count=1,
            evidence=("expected key universe is empty",),
        )
    observed = set(observed_keys)
    missing = sorted(expected_keys - observed)
    unexpected = sorted(observed - expected_keys)
    issues = _IssueCollector()
    for key in missing:
        issues.add(f"missing {key.render()}")
    for key in unexpected:
        issues.add(f"unexpected {key.render()}")
    return issues.check(len(expected_keys))


def _audit_duplicates(keys: tuple[RecordKey, ...]) -> AuditCheck:
    issues = _IssueCollector()
    for key, count in sorted(Counter(keys).items()):
        if count > 1:
            issues.add(f"duplicate {key.render()} count={count}", count=count - 1)
    return issues.check(len(keys))


def _audit_time_travel(records: tuple[NormalizedQuantRecord, ...]) -> AuditCheck:
    issues = _IssueCollector()
    for record in records:
        if record.available_at < record.event_time:
            issues.add(
                f"{_record_key(record).render()} available_at="
                f"{record.available_at.isoformat()}"
            )
    return issues.check(len(records))


def _audit_consistency(
    records: tuple[NormalizedQuantRecord, ...],
    *,
    scope: QuantReadScope,
) -> AuditCheck:
    issues = _IssueCollector()
    for record in records:
        key = _record_key(record).render()
        event_date = record.event_time.astimezone(SHANGHAI).date()
        if not scope.start <= event_date <= scope.end:
            issues.add(f"{key} is outside audit date scope")
        if record.symbol not in scope.symbols:
            issues.add(f"{key} is outside audit symbol scope")
        if not record.asset_id.strip():
            issues.add(f"{key} has empty asset_id")
        if not record.source.strip():
            issues.add(f"{key} has empty source")
        if not record.snapshot_id.strip():
            issues.add(f"{key} has empty snapshot_id")
        for reason in record.validity.reasons:
            issues.add(f"{key} validity={reason.value}")
    asset_kinds = {(record.asset_id, record.kind) for record in records}
    if len(asset_kinds) > 1:
        rendered = ",".join(
            f"{asset_id}:{kind.value}" for asset_id, kind in sorted(asset_kinds)
        )
        issues.add(f"single-table audit contains mixed assets/kinds: {rendered}")
    return issues.check(len(records))


def _bounded_records(
    records: Iterable[NormalizedQuantRecord],
    *,
    max_records: int,
    label: str,
) -> tuple[NormalizedQuantRecord, ...]:
    if max_records < 1:
        raise DataActivationError("audit max_records must be positive")
    result: list[NormalizedQuantRecord] = []
    for record in records:
        if len(result) >= max_records:
            raise DataActivationError(
                f"{label} audit input exceeds safety limit {max_records}"
            )
        result.append(record)
    return tuple(result)


def _record_key(record: NormalizedQuantRecord) -> RecordKey:
    return RecordKey(symbol=record.symbol, event_time=record.event_time)


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
