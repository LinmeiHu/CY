"""Minimal lossless source-recompute journal schema and Phase 1 reference codec."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from cyq_game.chip.checkpoint_journal_contract import (
    ARTIFACT_VERSION,
    JOURNAL_CODEC_VERSION,
    REFERENCE_CODEC_MODE,
    SCHEMA_VERSION,
    SELLER_MODEL_ORDER,
    STORAGE_VERSION,
    TRANSITION_SEMANTICS_VERSION,
    ContractError,
    DependencyClass,
    bits_f64be,
    canonical_json_bytes,
    strict_json_loads,
    validate_canonical_integer,
)

_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_RE = re.compile(r"0|-?[1-9][0-9]*\Z")
_F64BE_RE = re.compile(r"f64be:([0-9a-f]{16})\Z")
_UINT64_MAX = (1 << 64) - 1


class JournalOverrideType(StrEnum):
    SEALED_EXPLICIT_LEGACY_OPERATOR_FALLBACK = (
        "SEALED_EXPLICIT_LEGACY_OPERATOR_FALLBACK"
    )


class JournalOverrideReason(StrEnum):
    CORPORATE_ACTION_COORDINATE_CHANGE = "CORPORATE_ACTION_COORDINATE_CHANGE"
    MULTI_ARC_TRANSITION = "MULTI_ARC_TRANSITION"
    INVENTORY_ADJUSTMENT = "INVENTORY_ADJUSTMENT"
    IDENTITY_COLLISION = "IDENTITY_COLLISION"
    MISSING_SOURCE_TOPOLOGY = "MISSING_SOURCE_TOPOLOGY"
    NON_ORDINARY_DESTINATION = "NON_ORDINARY_DESTINATION"


JOURNAL_OVERRIDE_ORDER = tuple(item.value for item in JournalOverrideReason)


@dataclass(frozen=True)
class JournalDependencyReference:
    dependency_class: DependencyClass
    asset_id: str
    snapshot_id: str
    content_digest: str
    inventory_digest: str | None


@dataclass(frozen=True)
class JournalModelDigests:
    seller_model: str
    transition_digest: str
    post_state_digest: str
    identity_digest: str
    share_digest: str
    feature_digest: str
    conservation_digest: str
    tracker_digest: str
    lifecycle_digest: str


@dataclass(frozen=True)
class ExplicitLegacyOperatorFallbackPayload:
    source_cell_ids: tuple[int, ...]
    destination_cell_ids: tuple[int, ...]
    retained_fraction_bits: tuple[int, ...]
    inventory_adjustment_local_ids: tuple[int, ...]
    inventory_adjustment_shares_bits: tuple[int, ...]
    inventory_adjustment_economic_bucket_ids: tuple[int | None, ...]
    free_float_shares_bits: int
    cash_dividend_per_share_bits: int
    share_multiplier_bits: int


@dataclass(frozen=True)
class SealedExplicitLegacyOperatorFallback:
    override_type: JournalOverrideType
    reason: JournalOverrideReason
    override_version: str
    precondition_digest: str
    proof_digest: str
    payload: ExplicitLegacyOperatorFallbackPayload
    fallback_logical_digest: str


@dataclass(frozen=True)
class JournalDay:
    trading_date: date
    sequence: int
    decision_at: datetime
    available_at: datetime
    effective_at: datetime
    trading_state: str
    checkpoint_parent_digest: str
    dependency_references: tuple[JournalDependencyReference, ...]
    action_provenance: tuple[str, ...]
    input_snapshot_ids: tuple[str, ...]
    day_input_digest: str
    replay_contract_hash: str
    replay_parameter_manifest_digest: str
    transition_semantics_version: str
    runtime_fingerprint: str
    model_digests: tuple[JournalModelDigests, ...]
    hard_valid: bool
    quality_reason_codes: tuple[str, ...]
    override_required: bool
    explicit_override: SealedExplicitLegacyOperatorFallback | None


@dataclass(frozen=True)
class JournalLogical:
    storage_version: str
    schema_version: str
    artifact_version: str
    journal_codec_version: str
    symbol: str
    target_year: int
    dependency_manifest_digest: str
    replay_parameter_manifest_digest: str
    transition_semantics_version: str
    rows: tuple[JournalDay, ...]


def _digest(value: str, name: str) -> None:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ContractError(f"{name} must be a lowercase SHA-256 digest")


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{name} must be non-empty")


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{name} must be timezone-aware")


def _ordered_unique(values: tuple[str, ...], name: str) -> None:
    if values != tuple(sorted(set(values), key=lambda item: item.encode("utf-8"))):
        raise ContractError(f"{name} must be unique and UTF-8 byte sorted")


def explicit_legacy_operator_fallback_digest(
    value: SealedExplicitLegacyOperatorFallback,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "override_type": value.override_type,
                "reason": value.reason,
                "override_version": value.override_version,
                "precondition_digest": value.precondition_digest,
                "proof_digest": value.proof_digest,
                "payload": value.payload,
            }
        )
    ).hexdigest()


def _validate_uint64_id(value: int, name: str) -> None:
    validate_canonical_integer(value, name)
    if value < 0 or value > _UINT64_MAX:
        raise ContractError(f"{name} must be a uint64")


def _validate_fallback_payload(value: ExplicitLegacyOperatorFallbackPayload) -> None:
    if type(value) is not ExplicitLegacyOperatorFallbackPayload:
        raise ContractError("sealed fallback payload has an unknown type")
    tuple_fields = (
        (value.source_cell_ids, "source_cell_ids"),
        (value.destination_cell_ids, "destination_cell_ids"),
        (value.retained_fraction_bits, "retained_fraction_bits"),
        (value.inventory_adjustment_local_ids, "inventory_adjustment_local_ids"),
        (value.inventory_adjustment_shares_bits, "inventory_adjustment_shares_bits"),
        (
            value.inventory_adjustment_economic_bucket_ids,
            "inventory_adjustment_economic_bucket_ids",
        ),
    )
    for items, name in tuple_fields:
        if type(items) is not tuple:
            raise ContractError(f"sealed fallback {name} must be a tuple")
    if not value.source_cell_ids and not value.inventory_adjustment_local_ids:
        raise ContractError("sealed fallback operator cannot be empty")
    if not (
        len(value.source_cell_ids)
        == len(value.destination_cell_ids)
        == len(value.retained_fraction_bits)
    ):
        raise ContractError("sealed fallback operator arc lengths differ")
    if not (
        len(value.inventory_adjustment_local_ids)
        == len(value.inventory_adjustment_shares_bits)
        == len(value.inventory_adjustment_economic_bucket_ids)
    ):
        raise ContractError("sealed fallback adjustment lengths differ")
    for cell_id in (*value.source_cell_ids, *value.destination_cell_ids):
        _validate_uint64_id(cell_id, "sealed fallback operator cell ID")
    if len(set(value.inventory_adjustment_local_ids)) != len(
        value.inventory_adjustment_local_ids
    ):
        raise ContractError("sealed fallback adjustment cell IDs must be unique")
    for cell_id in value.inventory_adjustment_local_ids:
        _validate_uint64_id(cell_id, "sealed fallback adjustment cell ID")
    for bucket_id in value.inventory_adjustment_economic_bucket_ids:
        if bucket_id is not None:
            validate_canonical_integer(bucket_id, "sealed fallback economic bucket ID")
    for bits in value.retained_fraction_bits:
        retained = bits_f64be(bits)
        if not 0.0 <= retained <= 1.0:
            raise ContractError("sealed fallback retention must be within [0, 1]")
    for bits in value.inventory_adjustment_shares_bits:
        bits_f64be(bits)
    free_float = bits_f64be(value.free_float_shares_bits)
    bits_f64be(value.cash_dividend_per_share_bits)
    share_multiplier = bits_f64be(value.share_multiplier_bits)
    if free_float <= 0.0:
        raise ContractError("sealed fallback free float must be positive")
    if share_multiplier <= 0.0:
        raise ContractError("sealed fallback share multiplier must be positive")


def _validate_explicit_override(value: SealedExplicitLegacyOperatorFallback) -> None:
    if type(value) is not SealedExplicitLegacyOperatorFallback:
        raise ContractError("journal override is not the sealed fallback type")
    if type(value.override_type) is not JournalOverrideType or (
        value.override_type
        is not JournalOverrideType.SEALED_EXPLICIT_LEGACY_OPERATOR_FALLBACK
    ):
        raise ContractError("unknown journal override type")
    if type(value.reason) is not JournalOverrideReason:
        raise ContractError("unknown journal override reason")
    if value.override_version != JOURNAL_CODEC_VERSION:
        raise ContractError("unknown journal override version")
    _digest(value.precondition_digest, "override precondition digest")
    _digest(value.proof_digest, "override proof digest")
    _validate_fallback_payload(value.payload)
    _digest(value.fallback_logical_digest, "fallback logical digest")
    if explicit_legacy_operator_fallback_digest(value) != value.fallback_logical_digest:
        raise ContractError("sealed fallback logical digest mismatch")


def validate_journal_logical(value: JournalLogical) -> None:
    if (
        value.storage_version,
        value.schema_version,
        value.artifact_version,
        value.journal_codec_version,
        value.transition_semantics_version,
    ) != (
        STORAGE_VERSION,
        SCHEMA_VERSION,
        ARTIFACT_VERSION,
        JOURNAL_CODEC_VERSION,
        TRANSITION_SEMANTICS_VERSION,
    ):
        raise ContractError("journal contains an unknown or mixed version")
    _text(value.symbol, "journal symbol")
    if not 1900 <= value.target_year <= 9999:
        raise ContractError("journal target_year is out of range")
    _digest(value.dependency_manifest_digest, "dependency manifest digest")
    _digest(value.replay_parameter_manifest_digest, "replay parameter manifest digest")
    if not value.rows:
        raise ContractError("journal cannot be empty")
    dates = tuple(row.trading_date for row in value.rows)
    sequences = tuple(row.sequence for row in value.rows)
    for sequence in sequences:
        validate_canonical_integer(sequence, "journal sequence")
    if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
        raise ContractError("journal dates must be unique and increasing")
    if sequences != tuple(range(len(value.rows))):
        raise ContractError("journal sequence must be contiguous from zero")
    for row in value.rows:
        if type(row.hard_valid) is not bool or type(row.override_required) is not bool:
            raise ContractError("journal validity/override flags must be booleans")
        if row.trading_date.year != value.target_year:
            raise ContractError("journal row is outside target year")
        for stamp, name in (
            (row.decision_at, "decision_at"),
            (row.available_at, "available_at"),
            (row.effective_at, "effective_at"),
        ):
            _aware(stamp, name)
            if stamp.date() != row.trading_date:
                raise ContractError(f"journal {name} date mismatch")
        if row.available_at > row.decision_at or row.effective_at > row.decision_at:
            raise ContractError("journal PIT boundary follows decision_at")
        _text(row.trading_state, "trading state")
        for digest_value, name in (
            (row.checkpoint_parent_digest, "checkpoint parent digest"),
            (row.day_input_digest, "day input digest"),
            (row.replay_contract_hash, "replay contract hash"),
            (row.replay_parameter_manifest_digest, "row replay parameter digest"),
            (row.runtime_fingerprint, "runtime fingerprint"),
        ):
            _digest(digest_value, name)
        if row.replay_parameter_manifest_digest != value.replay_parameter_manifest_digest:
            raise ContractError("journal row/manifest replay parameter mismatch")
        if row.transition_semantics_version != TRANSITION_SEMANTICS_VERSION:
            raise ContractError("journal transition semantics mismatch")
        classes = tuple(item.dependency_class for item in row.dependency_references)
        required = {
            DependencyClass.DAILY,
            DependencyClass.MINUTE,
            DependencyClass.CORPORATE_ACTION,
        }
        if not required.issubset(set(classes)) or len(set(classes)) != len(classes):
            raise ContractError("journal dependency class coverage is incomplete or duplicated")
        for dependency in row.dependency_references:
            _text(dependency.asset_id, "journal dependency asset_id")
            _text(dependency.snapshot_id, "journal dependency snapshot_id")
            if dependency.snapshot_id.lower() == "latest":
                raise ContractError("journal dependency cannot use latest")
            _digest(dependency.content_digest, "journal dependency content digest")
            if dependency.inventory_digest is not None:
                _digest(dependency.inventory_digest, "journal dependency inventory digest")
        _ordered_unique(row.action_provenance, "action provenance")
        _ordered_unique(row.input_snapshot_ids, "journal input_snapshot_ids")
        if not row.input_snapshot_ids:
            raise ContractError("journal input_snapshot_ids cannot be empty")
        if tuple(item.seller_model for item in row.model_digests) != SELLER_MODEL_ORDER:
            raise ContractError("journal requires all three seller models in frozen order")
        for model in row.model_digests:
            for digest_value in (
                model.transition_digest,
                model.post_state_digest,
                model.identity_digest,
                model.share_digest,
                model.feature_digest,
                model.conservation_digest,
                model.tracker_digest,
                model.lifecycle_digest,
            ):
                _digest(digest_value, f"{model.seller_model} journal digest")
        _ordered_unique(row.quality_reason_codes, "journal quality reason codes")
        if row.override_required != (row.explicit_override is not None):
            raise ContractError("required explicit journal override is missing or spurious")
        if row.explicit_override is not None:
            _validate_explicit_override(row.explicit_override)


def journal_logical_bytes(value: JournalLogical) -> bytes:
    validate_journal_logical(value)
    return canonical_json_bytes(value)


def journal_logical_digest(value: JournalLogical) -> str:
    return hashlib.sha256(journal_logical_bytes(value)).hexdigest()


def encode_journal(value: JournalLogical) -> bytes:
    logical = journal_logical_bytes(value)
    return canonical_json_bytes(
        {
            "codec_mode": REFERENCE_CODEC_MODE,
            "codec_version": JOURNAL_CODEC_VERSION,
            "logical_digest": hashlib.sha256(logical).hexdigest(),
            "logical_payload": logical.decode("utf-8"),
        }
    )


def _exact(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        actual = set(value) if isinstance(value, dict) else set()
        raise ContractError(
            f"{name} fields mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    return value


def _integer(value: Any, name: str) -> int:
    if not isinstance(value, str) or _DECIMAL_RE.fullmatch(value) is None:
        raise ContractError(f"{name} is not a canonical integer")
    result = int(value)
    validate_canonical_integer(result, name)
    return result


def _bits(value: Any, name: str) -> int:
    if not isinstance(value, str):
        raise ContractError(f"{name} is not a canonical f64be value")
    match = _F64BE_RE.fullmatch(value)
    if match is None:
        raise ContractError(f"{name} is not a canonical f64be value")
    result = int(match.group(1), 16)
    bits_f64be(result)
    return result


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContractError(f"{name} is not canonical UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ContractError(f"invalid {name}") from exc


def _strings(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContractError(f"{name} must be a string array")
    return tuple(value)


def _dependency(raw: Any) -> JournalDependencyReference:
    value = _exact(
        raw,
        {"asset_id", "content_digest", "dependency_class", "inventory_digest", "snapshot_id"},
        "journal dependency",
    )
    try:
        dependency_class = DependencyClass(value["dependency_class"])
    except (TypeError, ValueError) as exc:
        raise ContractError("unknown journal dependency class") from exc
    return JournalDependencyReference(
        dependency_class=dependency_class,
        asset_id=value["asset_id"],
        snapshot_id=value["snapshot_id"],
        content_digest=value["content_digest"],
        inventory_digest=value["inventory_digest"],
    )


def _model(raw: Any) -> JournalModelDigests:
    expected = {
        "conservation_digest",
        "feature_digest",
        "identity_digest",
        "lifecycle_digest",
        "post_state_digest",
        "seller_model",
        "share_digest",
        "tracker_digest",
        "transition_digest",
    }
    value = _exact(raw, expected, "journal model digest")
    return JournalModelDigests(**value)


def _fallback_payload(raw: Any) -> ExplicitLegacyOperatorFallbackPayload:
    value = _exact(
        raw,
        {
            "cash_dividend_per_share_bits",
            "destination_cell_ids",
            "free_float_shares_bits",
            "inventory_adjustment_economic_bucket_ids",
            "inventory_adjustment_local_ids",
            "inventory_adjustment_shares_bits",
            "retained_fraction_bits",
            "share_multiplier_bits",
            "source_cell_ids",
        },
        "sealed fallback payload",
    )
    array_fields = (
        "source_cell_ids",
        "destination_cell_ids",
        "retained_fraction_bits",
        "inventory_adjustment_local_ids",
        "inventory_adjustment_shares_bits",
        "inventory_adjustment_economic_bucket_ids",
    )
    if any(not isinstance(value[name], list) for name in array_fields):
        raise ContractError("sealed fallback vector fields must be arrays")
    economic_buckets: list[int | None] = []
    for item in value["inventory_adjustment_economic_bucket_ids"]:
        economic_buckets.append(
            None if item is None else _integer(item, "fallback economic bucket ID")
        )
    return ExplicitLegacyOperatorFallbackPayload(
        source_cell_ids=tuple(
            _integer(item, "fallback source cell ID") for item in value["source_cell_ids"]
        ),
        destination_cell_ids=tuple(
            _integer(item, "fallback destination cell ID")
            for item in value["destination_cell_ids"]
        ),
        retained_fraction_bits=tuple(
            _bits(item, "fallback retained fraction")
            for item in value["retained_fraction_bits"]
        ),
        inventory_adjustment_local_ids=tuple(
            _integer(item, "fallback adjustment cell ID")
            for item in value["inventory_adjustment_local_ids"]
        ),
        inventory_adjustment_shares_bits=tuple(
            _bits(item, "fallback adjustment shares")
            for item in value["inventory_adjustment_shares_bits"]
        ),
        inventory_adjustment_economic_bucket_ids=tuple(economic_buckets),
        free_float_shares_bits=_bits(value["free_float_shares_bits"], "fallback free float"),
        cash_dividend_per_share_bits=_bits(
            value["cash_dividend_per_share_bits"], "fallback cash dividend"
        ),
        share_multiplier_bits=_bits(
            value["share_multiplier_bits"], "fallback share multiplier"
        ),
    )


def _override(raw: Any) -> SealedExplicitLegacyOperatorFallback | None:
    if raw is None:
        return None
    value = _exact(
        raw,
        {
            "fallback_logical_digest",
            "override_type",
            "override_version",
            "payload",
            "precondition_digest",
            "proof_digest",
            "reason",
        },
        "journal override",
    )
    try:
        override_type = JournalOverrideType(value["override_type"])
    except (TypeError, ValueError) as exc:
        raise ContractError("unknown journal override type") from exc
    try:
        reason = JournalOverrideReason(value["reason"])
    except (TypeError, ValueError) as exc:
        raise ContractError("unknown journal override reason") from exc
    return SealedExplicitLegacyOperatorFallback(
        override_type=override_type,
        reason=reason,
        override_version=value["override_version"],
        precondition_digest=value["precondition_digest"],
        proof_digest=value["proof_digest"],
        payload=_fallback_payload(value["payload"]),
        fallback_logical_digest=value["fallback_logical_digest"],
    )


def _row(raw: Any) -> JournalDay:
    expected = {
        "action_provenance",
        "available_at",
        "checkpoint_parent_digest",
        "day_input_digest",
        "decision_at",
        "dependency_references",
        "effective_at",
        "explicit_override",
        "hard_valid",
        "input_snapshot_ids",
        "model_digests",
        "override_required",
        "quality_reason_codes",
        "replay_contract_hash",
        "replay_parameter_manifest_digest",
        "runtime_fingerprint",
        "sequence",
        "trading_date",
        "trading_state",
        "transition_semantics_version",
    }
    value = _exact(raw, expected, "journal row")
    if not isinstance(value["hard_valid"], bool) or not isinstance(
        value["override_required"], bool
    ):
        raise ContractError("journal validity/override flags must be booleans")
    if not isinstance(value["dependency_references"], list) or not isinstance(
        value["model_digests"], list
    ):
        raise ContractError("journal dependency/model fields must be arrays")
    try:
        trading_date = date.fromisoformat(value["trading_date"])
    except (TypeError, ValueError) as exc:
        raise ContractError("invalid journal trading_date") from exc
    return JournalDay(
        trading_date=trading_date,
        sequence=_integer(value["sequence"], "journal sequence"),
        decision_at=_timestamp(value["decision_at"], "decision_at"),
        available_at=_timestamp(value["available_at"], "available_at"),
        effective_at=_timestamp(value["effective_at"], "effective_at"),
        trading_state=value["trading_state"],
        checkpoint_parent_digest=value["checkpoint_parent_digest"],
        dependency_references=tuple(_dependency(item) for item in value["dependency_references"]),
        action_provenance=_strings(value["action_provenance"], "action provenance"),
        input_snapshot_ids=_strings(value["input_snapshot_ids"], "input snapshot IDs"),
        day_input_digest=value["day_input_digest"],
        replay_contract_hash=value["replay_contract_hash"],
        replay_parameter_manifest_digest=value["replay_parameter_manifest_digest"],
        transition_semantics_version=value["transition_semantics_version"],
        runtime_fingerprint=value["runtime_fingerprint"],
        model_digests=tuple(_model(item) for item in value["model_digests"]),
        hard_valid=value["hard_valid"],
        quality_reason_codes=_strings(value["quality_reason_codes"], "quality reason codes"),
        override_required=value["override_required"],
        explicit_override=_override(value["explicit_override"]),
    )


def _logical(raw: Any) -> JournalLogical:
    expected = {
        "artifact_version",
        "dependency_manifest_digest",
        "journal_codec_version",
        "replay_parameter_manifest_digest",
        "rows",
        "schema_version",
        "storage_version",
        "symbol",
        "target_year",
        "transition_semantics_version",
    }
    value = _exact(raw, expected, "journal logical payload")
    if not isinstance(value["rows"], list):
        raise ContractError("journal rows must be an array")
    return JournalLogical(
        storage_version=value["storage_version"],
        schema_version=value["schema_version"],
        artifact_version=value["artifact_version"],
        journal_codec_version=value["journal_codec_version"],
        symbol=value["symbol"],
        target_year=_integer(value["target_year"], "target_year"),
        dependency_manifest_digest=value["dependency_manifest_digest"],
        replay_parameter_manifest_digest=value["replay_parameter_manifest_digest"],
        transition_semantics_version=value["transition_semantics_version"],
        rows=tuple(_row(item) for item in value["rows"]),
    )


def decode_journal(payload: bytes) -> JournalLogical:
    envelope = _exact(
        strict_json_loads(payload),
        {"codec_mode", "codec_version", "logical_digest", "logical_payload"},
        "journal envelope",
    )
    if envelope["codec_mode"] != REFERENCE_CODEC_MODE:
        raise ContractError("journal is not a Phase 1 reference container")
    if envelope["codec_version"] != JOURNAL_CODEC_VERSION:
        raise ContractError("unknown or cross-version journal codec")
    logical_text = envelope["logical_payload"]
    if not isinstance(logical_text, str):
        raise ContractError("journal logical payload must be a string")
    logical = logical_text.encode("utf-8")
    if envelope["logical_digest"] != hashlib.sha256(logical).hexdigest():
        raise ContractError("journal logical digest mismatch")
    value = _logical(strict_json_loads(logical))
    validate_journal_logical(value)
    if journal_logical_bytes(value) != logical:
        raise ContractError("journal payload is not canonical")
    return value
