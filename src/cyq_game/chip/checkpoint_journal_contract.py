"""Phase-1-only contracts for checkpoint + source-recompute journal storage.

This module is deliberately disconnected from the production builder, registry,
resolver, and operator paths.  It freezes logical values and canonical digests;
the reference containers in the sibling codec modules are not a production file
format.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence, Set
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

STORAGE_VERSION = "chip-checkpoint-journal-storage-v1"
SCHEMA_VERSION = "chip-checkpoint-journal-schema-v1"
ARTIFACT_VERSION = "v12-chip-bundle-checkpoint-journal-v1"
CHECKPOINT_CODEC_VERSION = "chip-checkpoint-codec-v1"
JOURNAL_CODEC_VERSION = "chip-replay-journal-codec-v1"
TERMINAL_COMPLETENESS_VERSION = "chip-terminal-completeness-v1"
DEPENDENCY_BINDING_VERSION = "chip-dependency-binding-v1"
DEPENDENCY_MANIFEST_VERSION = "chip-replay-dependency-manifest-v1"
REPLAY_PARAMETER_MANIFEST_VERSION = "chip-replay-parameter-manifest-v1"
TRANSITION_SEMANTICS_VERSION = "real-chip-transition-semantics-v1"
QUALITY_REASON_CODE_DOMAIN_VERSION = "quality-reason-code-domain-v1"
REFERENCE_CODEC_MODE = "REFERENCE_ONLY_PHASE_1"

SELLER_MODEL_ORDER = ("UNIFORM", "DISPOSITION", "ACTIVE_STICKY")
RESEARCH_RECOVERABLE_REASON_CODES = (
    "TURNOVER_CAPPED_AT_FLOAT",
    "UNKNOWN_COST_INITIALIZATION",
    "UNKNOWN_COST_PRESENT",
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SYMBOL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_UINT64_MAX = (1 << 64) - 1


class ContractError(ValueError):
    """A Phase 1 logical, version, ordering, or integrity contract failed."""


def validate_canonical_integer(value: int, name: str = "canonical integer") -> None:
    """Validate the single signed-negative/unsigned-positive logical domain."""

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _INT64_MIN <= value <= _UINT64_MAX
    ):
        raise ContractError(
            f"{name} must be within [{_INT64_MIN}, {_UINT64_MAX}]"
        )


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def strict_json_loads(payload: bytes) -> Any:
    """Decode UTF-8 JSON while rejecting duplicate keys and non-JSON constants."""

    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("payload is not valid UTF-8") from exc

    def reject_constant(value: str) -> None:
        raise ContractError(f"non-finite JSON constant is forbidden: {value}")

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise ContractError("payload is not strict JSON") from exc


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractError("canonical timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def f64be(value: float) -> str:
    """Return the RFC canonical binary64 representation."""

    if not math.isfinite(value):
        raise ContractError("NaN and infinity are forbidden")
    return f"f64be:{struct.pack('>d', value).hex()}"


def f64be_bits(value: float) -> int:
    if not math.isfinite(value):
        raise ContractError("NaN and infinity are forbidden")
    return struct.unpack(">Q", struct.pack(">d", value))[0]


def bits_f64be(value: int) -> float:
    _require_uint64(value, "binary64 bits")
    result = struct.unpack(">d", struct.pack(">Q", value))[0]
    if not math.isfinite(result):
        raise ContractError("NaN and infinity bit patterns are forbidden")
    return result


def _canonical_bits_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        _require_uint64(value, "binary64 bits")
        bits_f64be(value)
        return f"f64be:{value:016x}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_bits_value(item) for item in value]
    raise ContractError("exact-float bits field has a non-bit value")


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise ContractError(
            f"unsupported canonical value type: {type(value).__name__}"
        )
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, int):
        validate_canonical_integer(value)
        return str(value)
    if isinstance(value, float):
        return f64be(value)
    if isinstance(value, datetime):
        return _utc_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_value(asdict(value))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractError("canonical map keys must be strings")
        return {
            key: (
                _canonical_bits_value(value[key])
                if key.endswith("_bits")
                else _canonical_value(value[key])
            )
            for key in sorted(value, key=lambda item: item.encode("utf-8"))
        }
    if isinstance(value, Set):
        encoded = [(canonical_json_bytes(item), item) for item in value]
        encoded.sort(key=lambda item: item[0])
        return [_canonical_value(item) for _, item in encoded]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonical_value(item) for item in value]
    raise ContractError(f"unsupported canonical value type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Encode logical data using the RFC's deterministic canonical JSON profile."""

    canonical = _canonical_value(value)
    return json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def logical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _require_exact_fields(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ContractError(f"{name} fields mismatch; missing={missing}, extra={extra}")


def _require_text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{name} must be a non-empty string")


def _require_digest(value: str, name: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ContractError(f"{name} must be a lowercase SHA-256 hex digest")


def _require_uint64(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _UINT64_MAX:
        raise ContractError(f"{name} must be a uint64")


def _require_int64(value: int, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _INT64_MIN <= value <= _INT64_MAX
    ):
        raise ContractError(f"{name} must be an int64")


def _require_ordered_unique(values: Sequence[str], name: str) -> None:
    if tuple(values) != tuple(sorted(set(values), key=lambda item: item.encode("utf-8"))):
        raise ContractError(f"{name} must be unique and UTF-8 byte sorted")


class DependencyClass(StrEnum):
    DAILY = "SHARED_REGISTERED_DAILY_INPUTS"
    MINUTE = "SHARED_REGISTERED_MINUTE_INPUTS"
    CORPORATE_ACTION = "SHARED_REGISTERED_CORPORATE_ACTION_INPUTS"
    ADDITIONAL_REPLAY_INPUT = "VERSIONED_ADDITIONAL_REPLAY_INPUT"


class DeletionProtectionState(StrEnum):
    PINNED = "PINNED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"


@dataclass(frozen=True)
class DependencyBinding:
    binding_version: str
    dependency_class: DependencyClass
    asset_id: str
    snapshot_id: str
    content_digest: str
    inventory_digest: str | None
    registry_binding_version: str
    registry_revision_digest: str
    retention_policy_id: str | None
    retained_until: datetime | None
    dependent_bundle_id: str
    dependency_created_at: datetime
    dependency_registered_at: datetime
    immutable: bool
    deletion_protection_state: DeletionProtectionState


def validate_dependency_binding(binding: DependencyBinding, *, active_bundle: bool = True) -> None:
    if binding.binding_version != DEPENDENCY_BINDING_VERSION:
        raise ContractError("unknown dependency binding version")
    for value, name in (
        (binding.asset_id, "asset_id"),
        (binding.snapshot_id, "snapshot_id"),
        (binding.registry_binding_version, "registry_binding_version"),
        (binding.dependent_bundle_id, "dependent_bundle_id"),
    ):
        _require_text(value, name)
    if binding.snapshot_id.lower() == "latest" or "latest/" in binding.snapshot_id.lower():
        raise ContractError("mutable latest dependency is forbidden")
    _require_digest(binding.content_digest, "content_digest")
    _require_digest(binding.registry_revision_digest, "registry_revision_digest")
    if binding.inventory_digest is not None:
        _require_digest(binding.inventory_digest, "inventory_digest")
    if (binding.retention_policy_id is None) == (binding.retained_until is None):
        raise ContractError("exactly one retention policy ID or retained_until is required")
    if binding.retention_policy_id is not None:
        _require_text(binding.retention_policy_id, "retention_policy_id")
    _utc_timestamp(binding.dependency_created_at)
    _utc_timestamp(binding.dependency_registered_at)
    if binding.retained_until is not None:
        _utc_timestamp(binding.retained_until)
    if not binding.immutable:
        raise ContractError("dependency must be immutable")
    if active_bundle and binding.deletion_protection_state is not DeletionProtectionState.PINNED:
        raise ContractError("active bundle dependency must be PINNED")


@dataclass(frozen=True)
class ForwardDependencyReference:
    reference_version: str
    bundle_id: str
    asset_id: str
    snapshot_id: str
    content_digest: str
    inventory_digest: str | None
    binding_digest: str
    generation: int


@dataclass(frozen=True)
class ReverseDependencyReference:
    reference_version: str
    asset_id: str
    snapshot_id: str
    dependent_bundle_id: str
    content_digest: str
    inventory_digest: str | None
    binding_digest: str
    generation: int


@dataclass(frozen=True)
class ReverseReferenceIndex:
    index_version: str
    generation: int
    references: tuple[ReverseDependencyReference, ...]
    index_digest: str


def _reference_key(
    value: ForwardDependencyReference | ReverseDependencyReference,
) -> tuple[str, str, str]:
    bundle = (
        value.bundle_id
        if isinstance(value, ForwardDependencyReference)
        else value.dependent_bundle_id
    )
    return bundle, value.asset_id, value.snapshot_id


def _reverse_index_payload(index: ReverseReferenceIndex) -> dict[str, Any]:
    return {
        "generation": index.generation,
        "index_version": index.index_version,
        "references": index.references,
    }


def reverse_reference_index_digest(index: ReverseReferenceIndex) -> str:
    return logical_sha256(_reverse_index_payload(index))


def dependency_binding_digest(binding: DependencyBinding) -> str:
    return logical_sha256(binding)


def _validate_forward_reference(value: ForwardDependencyReference) -> None:
    if type(value) is not ForwardDependencyReference:
        raise ContractError("forward dependency edge has an unknown type")
    if value.reference_version != DEPENDENCY_MANIFEST_VERSION:
        raise ContractError("unknown forward-reference version")
    for text, name in (
        (value.bundle_id, "forward bundle ID"),
        (value.asset_id, "forward asset ID"),
        (value.snapshot_id, "forward snapshot ID"),
    ):
        _require_text(text, name)
    if value.snapshot_id.lower() == "latest" or "latest/" in value.snapshot_id.lower():
        raise ContractError("mutable latest forward dependency is forbidden")
    validate_canonical_integer(value.generation, "forward-reference generation")
    if value.generation < 0:
        raise ContractError("forward-reference generation must be non-negative")
    _require_digest(value.content_digest, "forward content digest")
    _require_digest(value.binding_digest, "forward binding digest")
    if value.inventory_digest is not None:
        _require_digest(value.inventory_digest, "forward inventory digest")


def _validate_reverse_reference(value: ReverseDependencyReference) -> None:
    if type(value) is not ReverseDependencyReference:
        raise ContractError("reverse dependency edge has an unknown type")
    if value.reference_version != DEPENDENCY_MANIFEST_VERSION:
        raise ContractError("unknown reverse-reference version")
    for text, name in (
        (value.dependent_bundle_id, "reverse bundle ID"),
        (value.asset_id, "reverse asset ID"),
        (value.snapshot_id, "reverse snapshot ID"),
    ):
        _require_text(text, name)
    if value.snapshot_id.lower() == "latest" or "latest/" in value.snapshot_id.lower():
        raise ContractError("mutable latest reverse dependency is forbidden")
    validate_canonical_integer(value.generation, "reverse-reference generation")
    if value.generation < 0:
        raise ContractError("reverse-reference generation must be non-negative")
    _require_digest(value.content_digest, "reverse content digest")
    _require_digest(value.binding_digest, "reverse binding digest")
    if value.inventory_digest is not None:
        _require_digest(value.inventory_digest, "reverse inventory digest")


def validate_forward_reverse_references(
    forward: Sequence[ForwardDependencyReference],
    reverse_index: ReverseReferenceIndex,
) -> None:
    if reverse_index.index_version != DEPENDENCY_MANIFEST_VERSION:
        raise ContractError("unknown reverse-reference index version")
    validate_canonical_integer(
        reverse_index.generation, "reverse-reference index generation"
    )
    if reverse_index.generation < 0:
        raise ContractError("reverse-reference generation must be non-negative")
    reverse = reverse_index.references
    for item in forward:
        _validate_forward_reference(item)
    for item in reverse:
        _validate_reverse_reference(item)
    forward_keys = [_reference_key(item) for item in forward]
    reverse_keys = [_reference_key(item) for item in reverse]
    if len(set(forward_keys)) != len(forward_keys) or len(set(reverse_keys)) != len(
        reverse_keys
    ):
        raise ContractError("duplicate dependency edge")
    _require_digest(reverse_index.index_digest, "reverse index digest")
    if reverse_reference_index_digest(reverse_index) != reverse_index.index_digest:
        raise ContractError("reverse-reference index digest mismatch")
    if set(forward_keys) != set(reverse_keys):
        missing = sorted(set(forward_keys) - set(reverse_keys))
        stale = sorted(set(reverse_keys) - set(forward_keys))
        raise ContractError(f"forward/reverse edge disagreement; missing={missing}, stale={stale}")
    reverse_by_key = dict(zip(reverse_keys, reverse, strict=True))
    for item in forward:
        match = reverse_by_key[_reference_key(item)]
        if (
            item.generation != reverse_index.generation
            or match.generation != reverse_index.generation
        ):
            raise ContractError("reference generation mismatch")
        if (
            item.content_digest,
            item.inventory_digest,
            item.binding_digest,
        ) != (
            match.content_digest,
            match.inventory_digest,
            match.binding_digest,
        ):
            raise ContractError("forward/reverse dependency digest mismatch")


@dataclass(frozen=True)
class DependencyManifest:
    manifest_version: str
    bundle_id: str
    bindings: tuple[DependencyBinding, ...]
    forward_references: tuple[ForwardDependencyReference, ...]
    manifest_digest: str


def dependency_manifest_digest(manifest: DependencyManifest) -> str:
    return logical_sha256(
        {
            "bindings": manifest.bindings,
            "bundle_id": manifest.bundle_id,
            "forward_references": manifest.forward_references,
            "manifest_version": manifest.manifest_version,
        }
    )


def validate_dependency_manifest(manifest: DependencyManifest) -> None:
    if manifest.manifest_version != DEPENDENCY_MANIFEST_VERSION:
        raise ContractError("unknown dependency manifest version")
    _require_text(manifest.bundle_id, "bundle_id")
    if not manifest.bindings:
        raise ContractError("dependency manifest cannot be empty")
    keys: list[tuple[str, str]] = []
    for binding in manifest.bindings:
        if type(binding) is not DependencyBinding:
            raise ContractError("dependency manifest binding has an unknown type")
        validate_dependency_binding(binding)
        if binding.dependent_bundle_id != manifest.bundle_id:
            raise ContractError("dependency names the wrong dependent bundle")
        keys.append((binding.asset_id, binding.snapshot_id))
    if len(set(keys)) != len(keys):
        raise ContractError("duplicate dependency binding")
    for item in manifest.forward_references:
        _validate_forward_reference(item)
    forward_keys = [
        (item.asset_id, item.snapshot_id) for item in manifest.forward_references
    ]
    if len(set(forward_keys)) != len(forward_keys):
        raise ContractError("duplicate forward dependency edge")
    if set(forward_keys) != set(keys):
        raise ContractError("dependency bindings and forward references disagree")
    binding_by_key = dict(zip(keys, manifest.bindings, strict=True))
    for reference in manifest.forward_references:
        binding = binding_by_key[(reference.asset_id, reference.snapshot_id)]
        if reference.bundle_id != manifest.bundle_id:
            raise ContractError("forward dependency names the wrong bundle")
        if (
            reference.content_digest != binding.content_digest
            or reference.inventory_digest != binding.inventory_digest
        ):
            raise ContractError("forward dependency content/inventory binding mismatch")
        if reference.binding_digest != dependency_binding_digest(binding):
            raise ContractError("forward dependency logical binding digest mismatch")
    _require_digest(manifest.manifest_digest, "dependency manifest digest")
    if dependency_manifest_digest(manifest) != manifest.manifest_digest:
        raise ContractError("dependency manifest digest mismatch")


# Every replay-impacting row frozen by RFC section 5.2.  Composite rows remain
# composite values, but none may be absent or silently supplied from runtime defaults.
REQUIRED_REPLAY_PARAMETER_NAMES = (
    "scope.target_year",
    "scope.end_date",
    "scope.emit_start_date",
    "scope.symbols",
    "warmup.start_year",
    "warmup.first_positive_float_rule",
    "warmup.emit_rule",
    "continuation.parent_bundle_id",
    "continuation.parent_checkpoint_digest",
    "continuation.selection_mode",
    "dependencies.bindings",
    "model.version",
    "grid.version",
    "seller_models.order",
    "migration.max_holding_days",
    "migration.active_purchase_fraction",
    "initialization.allocations",
    "seller_hazard.uniform",
    "seller_hazard.disposition",
    "seller_hazard.active_sticky",
    "execution.same_day_resale",
    "grid.reference_price",
    "grid.step_pct",
    "grid.bucket_rounding",
    "grid.nonpositive_economic_bucket",
    "grid.economic_decode",
    "numeric.abs_tolerance",
    "numeric.rel_tolerance",
    "numeric.float_encoding",
    "numeric.comparison",
    "identity.cell_id",
    "identity.compaction",
    "numeric.summation",
    "numeric.residual_bridge",
    "corporate_action.coordinate",
    "corporate_action.identity_order",
    "corporate_action.float_bridge",
    "minute.path_price_policy",
    "minute.invalid_path_policy",
    "minute.daily_fallback_policy",
    "trading.zero_turnover",
    "trading.suspension",
    "minute.turnover_cap",
    "pit.session_times",
    "quality.fail_closed_policy",
    "quality.research_recoverable_reason_codes",
    "checkpoint.cadence",
    "journal.override_classes",
    "feature.distribution_parameters",
    "feature.peak_definition_parameters",
    "feature.peak_track_parameters",
    "feature.ensemble_aggregation",
    "storage.state_codec",
    "runtime.code_inventory",
    "runtime.environment",
)

# Static replay values are logical schema data, not runtime defaults.  Callers
# must still supply every row explicitly; validation compares their supplied
# values with these RFC-frozen contracts.
FROZEN_REPLAY_PARAMETER_VALUES: Mapping[str, Any] = {
    "warmup.first_positive_float_rule": (
        "FIRST_POSITIVE_FLOAT_INITIALIZES_THEN_NEXT_DAY_ADVANCES"
    ),
    "warmup.emit_rule": "TARGET_YEAR_ONLY",
    "model.version": "real-chip-inventory-v2.1",
    "grid.version": "log-grid-25bp-v1",
    "seller_models.order": SELLER_MODEL_ORDER,
    "migration.max_holding_days": 180,
    "migration.active_purchase_fraction": 0.7,
    "initialization.allocations": {
        "ACTIVE_STICKY": {"ACTIVE": 0.35, "STICKY": 0.65},
        "DISPOSITION": {"NEUTRAL": 1.0},
        "UNIFORM": {"NEUTRAL": 1.0},
        "holding_days": -1,
        "prior_units": "EQUAL_WEIGHTS",
    },
    "seller_hazard.uniform": {"constant": 1.0},
    "seller_hazard.disposition": {
        "clamp_lower": -2.0,
        "clamp_upper": 2.0,
        "formula": "exp(clamp(1.5*pnl,-2.0,2.0))",
        "unknown_cost": 1.0,
    },
    "seller_hazard.active_sticky": {
        "ACTIVE": 2.0,
        "NEUTRAL": 1.0,
        "STICKY": 0.25,
    },
    "execution.same_day_resale": "FORBIDDEN_FIXED_PRE_SALE_POST_PURCHASE",
    "grid.reference_price": 1.0,
    "grid.step_pct": 0.0025,
    "grid.bucket_rounding": "floor(log(price/ref)/log1p(step)+0.5)",
    "grid.nonpositive_economic_bucket": -2147483648,
    "grid.economic_decode": 0.0,
    "numeric.abs_tolerance": 1e-6,
    "numeric.rel_tolerance": 1e-12,
    "numeric.float_encoding": "IEEE754_BINARY64_BITS_NO_FLOAT32_NO_NORMALIZATION",
    "numeric.comparison": "BIT_EQUALITY_WHERE_EXACT_CONTRACT_REQUIRES",
    "identity.cell_id": (
        "SHA256_SORTED_COMPACT_JSON_ECONOMIC_FLOAT_HEX_FIRST8_BE_MASK63"
    ),
    "identity.compaction": (
        "DROP_NONPOSITIVE_STABLE_CELL_ID_ORDER_IDENTICAL_DIMENSION_AGE_CAP_MERGE_"
        "COMPENSATED_SUM"
    ),
    "numeric.summation": "COMPENSATED_ALGORITHM_FROZEN_ORDER_V1",
    "numeric.residual_bridge": "BOUNDED_SINGLE_ARGMAX_CORRECTION_SOURCE_BOUNDS",
    "corporate_action.coordinate": "causal-economic-price-v2:(C-D)/R",
    "corporate_action.identity_order": (
        "CASH_09:00:00",
        "SPLIT_09:00:01",
        "FLOAT_BRIDGE_09:00:02",
        "SORTED_SOURCE_IDS_SHA256_PAYLOAD",
    ),
    "corporate_action.float_bridge": (
        "FROZEN_TOLERANCE_SORTED_CELL_IDS_LAST_RESIDUAL_ASSIGNMENT"
    ),
    "minute.path_price_policy": (
        "UNIQUE_TIMESTAMP_VWAP_AMOUNT_OVER_VOLUME_CLAMP_LOW_HIGH_ELSE_OHLC4"
    ),
    "minute.invalid_path_policy": "ANY_INVALID_BAR_REJECTS_WHOLE_INTRADAY_PATH",
    "minute.daily_fallback_policy": (
        "POSITIVE_DAILY_VOLUME_15:00_IN_RANGE_VWAP_ELSE_CLOSE"
    ),
    "trading.zero_turnover": "EMPTY_PATH_NO_FABRICATED_SALE_OR_PURCHASE",
    "trading.suspension": "FROZEN_REGISTERED_STATE_QUALITY_EVENT_ADVANCE",
    "minute.turnover_cap": {
        "capped_volume_factor": 0.999999999,
        "scale": "ALL_VOLUMES_ONCE",
        "trigger": "volume>free_float+tolerance",
    },
    "pit.session_times": {
        "action": "09:00:00",
        "decision": "15:00:00",
        "float_bridge": "09:00:02",
        "requirement": "available_at<=decision_at",
        "split": "09:00:01",
        "timezone": "Asia/Shanghai",
    },
    "quality.fail_closed_policy": (
        "MISSING_POSITIVE_FLOAT_ON_HARD_VALID_ERRORS_REASONS_SORTED_"
        "HARD_VALID_ONLY_WITH_NO_REASONS"
    ),
    "checkpoint.cadence": (
        "OPENING_PLUS_EACH_CALENDAR_MONTH_END_TRADING_SESSION_INCLUDING_YEAR_END"
    ),
    "journal.override_classes": (
        "CORPORATE_ACTION_COORDINATE_CHANGE",
        "MULTI_ARC_TRANSITION",
        "INVENTORY_ADJUSTMENT",
        "IDENTITY_COLLISION",
        "MISSING_SOURCE_TOPOLOGY",
        "NON_ORDINARY_DESTINATION",
    ),
    "feature.distribution_parameters": {
        "asr": (0.9, 1.1),
        "concentration_multiplier": 1.2,
        "quantiles": (0.01, 0.1, 0.5, 0.9, 0.99),
        "smoothing": (1, 4, 6, 4, 1),
        "structural_score": 0.12,
    },
    "feature.peak_definition_parameters": {
        "kernel": (1, 4, 6, 4, 1),
        "max_span": 1000000,
        "min_mass": 0.03,
        "min_prominence": 0.003,
        "offsets": (-2, -1, 0, 1, 2),
        "tie_rounding": 12,
        "valley_ratio": 0.8,
    },
    "feature.peak_track_parameters": {
        "ambiguity_mass": 0.02,
        "ensemble_rule": "ONE_TO_ONE",
        "match_permitted_floor": 0.03,
        "nonoverlap_log_limit": 0.01,
        "score_tie": 0.05,
        "version": "peak-track-v2",
    },
    "feature.ensemble_aggregation": (
        "MEDIAN_SCALARS_MIN_KNOWN_MODEL_QUALITY_MAX_MINUS_MIN_SPREADS_"
        "ALL_MODEL_VALIDITY_SORTED_UNION_REASONS"
    ),
    "storage.state_codec": {
        "canonical": "UTF8_SORTED_KEYS_NO_WHITESPACE_F64BE_BITS",
        "codec_mode": REFERENCE_CODEC_MODE,
        "integer_encoding": "BASE10_SIGNED_INTEGER_STRING",
        "journal_codec_version": JOURNAL_CODEC_VERSION,
        "checkpoint_codec_version": CHECKPOINT_CODEC_VERSION,
    },
}


EXPECTED_REPLAY_PARAMETER_OWNER_VERSIONS: Mapping[str, str] = {
    **{name: "builder-scope-v1" for name in REQUIRED_REPLAY_PARAMETER_NAMES[:4]},
    **{name: "transition-v1" for name in REQUIRED_REPLAY_PARAMETER_NAMES[4:7]},
    **{name: "continuation-v1" for name in REQUIRED_REPLAY_PARAMETER_NAMES[7:10]},
    "dependencies.bindings": DEPENDENCY_MANIFEST_VERSION,
    "model.version": "builder-current-semantic-epoch",
    "grid.version": "builder-current-semantic-epoch",
    "seller_models.order": "ensemble-v2",
    "migration.max_holding_days": "transition-v1",
    "migration.active_purchase_fraction": "transition-v1",
    "initialization.allocations": "state-v3",
    "seller_hazard.uniform": "model-v2.1",
    "seller_hazard.disposition": "model-v2.1",
    "seller_hazard.active_sticky": "model-v2.1",
    "execution.same_day_resale": "transition-v1",
    "grid.reference_price": "grid-v1",
    "grid.step_pct": "grid-v1",
    "grid.bucket_rounding": "grid-v1",
    "grid.nonpositive_economic_bucket": "grid-v1",
    "grid.economic_decode": "grid-v1",
    "numeric.abs_tolerance": "state-v3",
    "numeric.rel_tolerance": "state-v3",
    "numeric.float_encoding": "codec-v1",
    "numeric.comparison": "codec-v1",
    "identity.cell_id": "state-v3",
    "identity.compaction": "transition-v1",
    "numeric.summation": "transition-v1",
    "numeric.residual_bridge": "transition-v1",
    "corporate_action.coordinate": "price-coordinate-v2",
    "corporate_action.identity_order": "price-coordinate-v2-builder",
    "corporate_action.float_bridge": "builder-transition-v1",
    "minute.path_price_policy": "builder-minute-path-v1",
    "minute.invalid_path_policy": "builder-minute-path-v1",
    "minute.daily_fallback_policy": "builder-minute-path-v1",
    "trading.zero_turnover": "transition-v1",
    "trading.suspension": "transition-v1",
    "minute.turnover_cap": "builder-minute-path-v1",
    "pit.session_times": "pit-contract-v1",
    "quality.fail_closed_policy": "state-v3",
    "quality.research_recoverable_reason_codes": QUALITY_REASON_CODE_DOMAIN_VERSION,
    "checkpoint.cadence": SCHEMA_VERSION,
    "journal.override_classes": SCHEMA_VERSION,
    "feature.distribution_parameters": "feature-v6",
    "feature.peak_definition_parameters": "peak-definition-v2",
    "feature.peak_track_parameters": "peak-track-v2",
    "feature.ensemble_aggregation": "feature-v6",
    "storage.state_codec": "checkpoint-journal-codec-v1",
    "runtime.code_inventory": "replay-manifest-v1",
    "runtime.environment": "replay-manifest-v1",
}


@dataclass(frozen=True)
class ReplayParameter:
    canonical_name: str
    owner_version: str
    value: Any


@dataclass(frozen=True)
class ReplayParameterManifest:
    manifest_version: str
    owner: str
    owner_version: str
    dependency_manifest_digest: str
    dependency_content_inventory_digests: tuple[str, ...]
    code_inventory_digests: tuple[str, ...]
    runtime_inventory: Mapping[str, Any]
    parameters: tuple[ReplayParameter, ...]
    parameter_manifest_sha256: str


def replay_parameter_manifest_digest(manifest: ReplayParameterManifest) -> str:
    return logical_sha256(
        {
            "code_inventory_digests": manifest.code_inventory_digests,
            "dependency_content_inventory_digests": manifest.dependency_content_inventory_digests,
            "dependency_manifest_digest": manifest.dependency_manifest_digest,
            "manifest_version": manifest.manifest_version,
            "owner": manifest.owner,
            "owner_version": manifest.owner_version,
            "parameters": manifest.parameters,
            "runtime_inventory": manifest.runtime_inventory,
        }
    )


def with_replay_parameter_digest(manifest: ReplayParameterManifest) -> ReplayParameterManifest:
    return replace(manifest, parameter_manifest_sha256=replay_parameter_manifest_digest(manifest))


def validate_replay_parameter_manifest(manifest: ReplayParameterManifest) -> None:
    if manifest.manifest_version != REPLAY_PARAMETER_MANIFEST_VERSION:
        raise ContractError("unknown replay parameter manifest version")
    _require_text(manifest.owner, "parameter manifest owner")
    _require_text(manifest.owner_version, "parameter manifest owner version")
    _require_digest(manifest.dependency_manifest_digest, "dependency manifest digest")
    for digest in (
        *manifest.dependency_content_inventory_digests,
        *manifest.code_inventory_digests,
    ):
        _require_digest(digest, "parameter-bound digest")
    if not manifest.dependency_content_inventory_digests or not manifest.code_inventory_digests:
        raise ContractError("parameter manifest inventories cannot be empty")
    if not manifest.runtime_inventory:
        raise ContractError("runtime inventory cannot be empty")
    names = tuple(item.canonical_name for item in manifest.parameters)
    if names != REQUIRED_REPLAY_PARAMETER_NAMES:
        missing = sorted(set(REQUIRED_REPLAY_PARAMETER_NAMES) - set(names))
        extra = sorted(set(names) - set(REQUIRED_REPLAY_PARAMETER_NAMES))
        raise ContractError(
            f"replay parameter names/order mismatch; missing={missing}, extra={extra}"
        )
    by_name = dict(zip(names, manifest.parameters, strict=True))
    for item in manifest.parameters:
        expected_owner = EXPECTED_REPLAY_PARAMETER_OWNER_VERSIONS[item.canonical_name]
        if item.owner_version != expected_owner:
            raise ContractError(
                f"replay parameter owner/version mismatch: {item.canonical_name}"
            )
    for name, expected_value in FROZEN_REPLAY_PARAMETER_VALUES.items():
        if canonical_json_bytes(by_name[name].value) != canonical_json_bytes(expected_value):
            raise ContractError(f"frozen replay parameter value mismatch: {name}")

    target_year = by_name["scope.target_year"].value
    if isinstance(target_year, bool) or not isinstance(target_year, int):
        raise ContractError("scope.target_year must be an explicit integer")
    if not 1900 <= target_year <= 9999:
        raise ContractError("scope.target_year is out of range")
    for name in ("scope.end_date", "scope.emit_start_date"):
        value = by_name[name].value
        if value is not None and not isinstance(value, date):
            raise ContractError(f"{name} must be an ISO date value or null")
        if isinstance(value, datetime):
            raise ContractError(f"{name} must be a date, not a timestamp")
    symbols = by_name["scope.symbols"].value
    if not isinstance(symbols, Sequence) or isinstance(symbols, (str, bytes)):
        raise ContractError("scope.symbols must be an explicit ordered array")
    symbol_tuple = tuple(symbols)
    if not symbol_tuple or any(not isinstance(item, str) for item in symbol_tuple):
        raise ContractError("scope.symbols must contain non-empty symbol strings")
    _require_ordered_unique(symbol_tuple, "scope.symbols")
    warmup_start = by_name["warmup.start_year"].value
    if (
        isinstance(warmup_start, bool)
        or not isinstance(warmup_start, int)
        or not 1900 <= warmup_start <= target_year
    ):
        raise ContractError("warmup.start_year must be an explicit valid prior year")

    selection_mode = by_name["continuation.selection_mode"].value
    if selection_mode not in {"EXPLICIT", "AUTO_ADJACENT_YEAR", "NONE"}:
        raise ContractError("unknown continuation selection mode")
    parent_bundle = by_name["continuation.parent_bundle_id"].value
    parent_digest = by_name["continuation.parent_checkpoint_digest"].value
    if selection_mode == "NONE":
        if parent_bundle is not None or parent_digest is not None:
            raise ContractError("NONE continuation cannot bind a parent")
    else:
        _require_text(parent_bundle, "continuation parent bundle ID")
        _require_digest(parent_digest, "continuation parent checkpoint digest")

    raw_bindings = by_name["dependencies.bindings"].value
    if not isinstance(raw_bindings, Sequence) or isinstance(raw_bindings, (str, bytes)):
        raise ContractError("dependencies.bindings must be an explicit ordered array")
    bindings = tuple(raw_bindings)
    if not bindings or any(not isinstance(item, DependencyBinding) for item in bindings):
        raise ContractError("dependencies.bindings must contain DependencyBinding values")
    for binding in bindings:
        validate_dependency_binding(binding)
    binding_keys = tuple((item.asset_id, item.snapshot_id) for item in bindings)
    if binding_keys != tuple(sorted(set(binding_keys))):
        raise ContractError("dependencies.bindings must be unique and canonically ordered")
    bound_digests = tuple(
        digest
        for binding in bindings
        for digest in (binding.content_digest, binding.inventory_digest)
        if digest is not None
    )
    if manifest.dependency_content_inventory_digests != bound_digests:
        raise ContractError("dependency binding/content inventory digest disagreement")

    quality = by_name["quality.research_recoverable_reason_codes"]
    if not isinstance(quality.value, Mapping):
        raise ContractError("research-recoverable parameter must be an object")
    _require_exact_fields(quality.value, {"domain_version", "values"}, "quality parameter")
    if quality.value["domain_version"] != QUALITY_REASON_CODE_DOMAIN_VERSION:
        raise ContractError("wrong quality reason-code domain version")
    if tuple(quality.value["values"]) != RESEARCH_RECOVERABLE_REASON_CODES:
        raise ContractError("research-recoverable reason-code set/order mismatch")
    code_inventory = by_name["runtime.code_inventory"].value
    if not isinstance(code_inventory, Mapping) or not code_inventory:
        raise ContractError("runtime.code_inventory must be a non-empty path/digest map")
    if any(not isinstance(path, str) or not path for path in code_inventory):
        raise ContractError("runtime.code_inventory contains an invalid path")
    ordered_code_digests = tuple(
        code_inventory[path]
        for path in sorted(code_inventory, key=lambda item: item.encode("utf-8"))
    )
    for digest in ordered_code_digests:
        _require_digest(digest, "runtime code inventory digest")
    if manifest.code_inventory_digests != ordered_code_digests:
        raise ContractError("runtime code inventory digest disagreement")
    if canonical_json_bytes(by_name["runtime.environment"].value) != canonical_json_bytes(
        manifest.runtime_inventory
    ):
        raise ContractError("runtime environment inventory disagreement")
    _require_digest(manifest.parameter_manifest_sha256, "parameter manifest digest")
    if replay_parameter_manifest_digest(manifest) != manifest.parameter_manifest_sha256:
        raise ContractError("replay parameter manifest digest mismatch")


def replay_contract_hash(
    *,
    parameter_manifest_digest: str,
    dependency_manifest_digest: str,
    schema_inventory: Mapping[str, Any],
    code_inventory: Mapping[str, Any],
    runtime_inventory: Mapping[str, Any],
) -> str:
    _require_digest(parameter_manifest_digest, "parameter manifest digest")
    _require_digest(dependency_manifest_digest, "dependency manifest digest")
    return logical_sha256(
        {
            "artifact_version": ARTIFACT_VERSION,
            "code_inventory": code_inventory,
            "dependency_manifest_digest": dependency_manifest_digest,
            "parameter_manifest_digest": parameter_manifest_digest,
            "runtime_inventory": runtime_inventory,
            "schema_inventory": schema_inventory,
            "schema_version": SCHEMA_VERSION,
            "storage_version": STORAGE_VERSION,
            "transition_semantics_version": TRANSITION_SEMANTICS_VERSION,
        }
    )


class TerminalFieldDisposition(StrEnum):
    STORED_IN_YEAR_END_CHECKPOINT = "STORED_IN_YEAR_END_CHECKPOINT"
    DETERMINISTICALLY_DERIVED = "DETERMINISTICALLY_DERIVED"
    MATERIALIZED_IN_COUNTED_COMPATIBILITY_TERMINAL = (
        "MATERIALIZED_IN_COUNTED_COMPATIBILITY_TERMINAL"
    )
    UNSUPPORTED = "UNSUPPORTED"


TERMINAL_REQUIRED_FIELDS = (
    "seller_model",
    "terminal_date",
    "target_year",
    "decision_at",
    "available_at",
    "effective_at",
    "phase",
    "snapshot_id",
    "input_snapshot_ids",
    "input_dependency_digests",
    "free_float_shares",
    "latent_supply_shares",
    "pit_grade",
    "hard_valid",
    "quality_reason_codes",
    "acquisition_cost",
    "initialization_prior_units",
    "complete_cells",
    "cell_identity",
    "exact_shares_bits",
    "economic_coordinate",
    "economic_bucket",
    "seller_continuation",
    "temporal_peak_tracker_continuation",
    "lifecycle_continuation",
    "semantic_fingerprint",
    "runtime_fingerprint",
    "dependency_retention_state",
)


@dataclass(frozen=True)
class TerminalFieldRule:
    field_name: str
    disposition: TerminalFieldDisposition
    derivation_contract_id: str | None = None
    compatibility_materialization_counted: bool = False


@dataclass(frozen=True)
class TerminalCompleteness:
    schema_version: str
    rules: tuple[TerminalFieldRule, ...]
    schema_digest: str


def terminal_completeness_digest(value: TerminalCompleteness) -> str:
    return logical_sha256({"rules": value.rules, "schema_version": value.schema_version})


def validate_terminal_completeness(value: TerminalCompleteness) -> None:
    if value.schema_version != TERMINAL_COMPLETENESS_VERSION:
        raise ContractError("unknown terminal completeness version")
    names = tuple(rule.field_name for rule in value.rules)
    if len(set(names)) != len(names):
        raise ContractError("terminal field disposition is duplicated")
    if set(names) != set(TERMINAL_REQUIRED_FIELDS):
        missing = sorted(set(TERMINAL_REQUIRED_FIELDS) - set(names))
        extra = sorted(set(names) - set(TERMINAL_REQUIRED_FIELDS))
        raise ContractError(
            f"terminal completeness fields mismatch; missing={missing}, extra={extra}"
        )
    if names != TERMINAL_REQUIRED_FIELDS:
        raise ContractError("terminal completeness rules are not in canonical order")
    for rule in value.rules:
        if type(rule.disposition) is not TerminalFieldDisposition:
            raise ContractError("terminal field disposition has an unknown type")
        if rule.disposition is TerminalFieldDisposition.DETERMINISTICALLY_DERIVED:
            _require_text(rule.derivation_contract_id or "", "derivation_contract_id")
        elif rule.derivation_contract_id is not None:
            raise ContractError("non-derived terminal field cannot name a derivation contract")
        if (
            rule.disposition
            is TerminalFieldDisposition.MATERIALIZED_IN_COUNTED_COMPATIBILITY_TERMINAL
            and not rule.compatibility_materialization_counted
        ):
            raise ContractError("compatibility terminal materialization must be counted")
        if rule.disposition is TerminalFieldDisposition.UNSUPPORTED:
            raise ContractError("required terminal field cannot be unsupported")
    _require_digest(value.schema_digest, "terminal completeness digest")
    if terminal_completeness_digest(value) != value.schema_digest:
        raise ContractError("terminal completeness digest mismatch")


@dataclass(frozen=True)
class CellIdentity:
    cell_id: int
    cost_bucket_id: int | None
    holding_days: int
    sensitivity: str
    economic_break_even_bits: int | None
    economic_coordinate_version: str


@dataclass(frozen=True)
class CheckpointLot:
    identity_position: int
    shares_bits: int
    acquisition_cost_bits: int | None
    initialization_prior_units_bits: int


@dataclass(frozen=True)
class SellerContinuation:
    continuation_version: str
    values: Mapping[str, Any]


@dataclass(frozen=True)
class TrackedPeakContinuation:
    peak_track_id: str
    age: int
    band_lower_bits: int
    band_upper_bits: int
    center_price_bits: int
    mass_bits: int
    prominence_bits: int
    ambiguity: bool
    split: bool
    merge: bool
    lost: bool
    reappear: bool
    definition_version: str
    track_version: str


@dataclass(frozen=True)
class TrackerScopeContinuation:
    scope: str
    base_track_id: str | None
    applied_action_ids: tuple[str, ...]
    previous_peaks: tuple[TrackedPeakContinuation, ...]


@dataclass(frozen=True)
class TemporalTrackerContinuation:
    tracker_version: str
    scopes: tuple[TrackerScopeContinuation, ...]


@dataclass(frozen=True)
class LifecycleAnchorContinuation:
    anchor_id: str
    anchor_date: date
    root_snapshot_id: str
    current_snapshot_id: str
    model_version: str
    grid_version: str
    root_origin_units_bits: int
    cell_ids: tuple[int, ...]
    origin_units_bits: tuple[int, ...]
    retention_bits: int
    destination_cell_ids: tuple[int, ...]
    lower_bound_bits: int
    upper_bound_bits: int


@dataclass(frozen=True)
class LifecycleContinuation:
    lifecycle_version: str
    active_anchor_ids: tuple[str, ...]
    anchors: tuple[LifecycleAnchorContinuation, ...]
    identity_digest: str
    share_digest: str
    retention_digest: str
    destination_digest: str


@dataclass(frozen=True)
class CheckpointModelState:
    seller_model: str
    decision_at: datetime
    available_at: datetime
    effective_at: datetime
    phase: str
    snapshot_id: str
    model_version: str
    grid_version: str
    lots: tuple[CheckpointLot, ...]
    free_float_shares_bits: int
    latent_supply_shares_bits: int
    conservation_error_bits: int
    input_snapshot_ids: tuple[str, ...]
    pit_grade: str
    hard_valid: bool
    quality_reason_codes: tuple[str, ...]
    seller_continuation: SellerContinuation
    lifecycle_continuation: LifecycleContinuation


@dataclass(frozen=True)
class CheckpointLogical:
    storage_version: str
    schema_version: str
    artifact_version: str
    checkpoint_codec_version: str
    symbol: str
    target_year: int
    checkpoint_date: date
    checkpoint_label: str
    identities: tuple[CellIdentity, ...]
    model_states: tuple[CheckpointModelState, ...]
    temporal_tracker: TemporalTrackerContinuation
    dependency_manifest_digest: str
    replay_parameter_manifest_digest: str
    replay_contract_hash: str
    transition_semantics_version: str
    semantic_fingerprint: str
    runtime_fingerprint: str
    terminal_completeness_digest: str


def _validate_cell_identity(identity: CellIdentity) -> None:
    _require_int64(identity.cell_id, "cell_id")
    if identity.cell_id < 0:
        raise ContractError("cell_id must be non-negative")
    if identity.cost_bucket_id is not None:
        _require_int64(identity.cost_bucket_id, "cost_bucket_id")
    if not -1 <= identity.holding_days <= 32767:
        raise ContractError("holding_days must fit int16 and be at least -1")
    if identity.sensitivity not in {"ACTIVE", "NEUTRAL", "STICKY"}:
        raise ContractError("unknown turnover sensitivity")
    if (identity.cost_bucket_id is None) != (identity.economic_break_even_bits is None):
        raise ContractError("cost bucket and economic coordinate nullability disagree")
    if identity.economic_break_even_bits is not None:
        bits_f64be(identity.economic_break_even_bits)
    _require_text(identity.economic_coordinate_version, "economic coordinate version")


def validate_checkpoint_logical(value: CheckpointLogical) -> None:
    if (
        value.storage_version,
        value.schema_version,
        value.artifact_version,
        value.checkpoint_codec_version,
        value.transition_semantics_version,
    ) != (
        STORAGE_VERSION,
        SCHEMA_VERSION,
        ARTIFACT_VERSION,
        CHECKPOINT_CODEC_VERSION,
        TRANSITION_SEMANTICS_VERSION,
    ):
        raise ContractError("checkpoint contains an unknown or mixed version")
    if _SYMBOL_RE.fullmatch(value.symbol) is None:
        raise ContractError("invalid checkpoint symbol")
    if not 1900 <= value.target_year <= 9999 or value.checkpoint_date.year != value.target_year:
        raise ContractError("checkpoint target year/date mismatch")
    _require_text(value.checkpoint_label, "checkpoint label")
    if not value.identities:
        raise ContractError("checkpoint identity union cannot be empty")
    for identity in value.identities:
        _validate_cell_identity(identity)
    cell_ids = tuple(identity.cell_id for identity in value.identities)
    if cell_ids != tuple(sorted(cell_ids)) or len(set(cell_ids)) != len(cell_ids):
        raise ContractError("checkpoint identities must be unique and sorted by cell_id")
    models = tuple(state.seller_model for state in value.model_states)
    if models != SELLER_MODEL_ORDER:
        raise ContractError("checkpoint requires all three seller models in frozen order")
    for state in value.model_states:
        for stamp, name in (
            (state.decision_at, "decision_at"),
            (state.available_at, "available_at"),
            (state.effective_at, "effective_at"),
        ):
            _utc_timestamp(stamp)
            if stamp.date() != value.checkpoint_date:
                raise ContractError(f"checkpoint {name} date mismatch")
        if state.available_at > state.decision_at or state.effective_at > state.decision_at:
            raise ContractError("checkpoint PIT boundary follows decision_at")
        if state.phase != "POST":
            raise ContractError("checkpoint terminal continuation must be POST")
        for field_value, name in (
            (state.snapshot_id, "snapshot_id"),
            (state.model_version, "model_version"),
            (state.grid_version, "grid_version"),
            (state.pit_grade, "pit_grade"),
            (state.seller_continuation.continuation_version, "seller continuation version"),
            (state.lifecycle_continuation.lifecycle_version, "lifecycle version"),
        ):
            _require_text(field_value, name)
        if not state.lots:
            raise ContractError("seller model checkpoint lots cannot be empty")
        for lot in state.lots:
            if not 0 <= lot.identity_position < len(value.identities):
                raise ContractError("checkpoint lot identity position is out of range")
            for bits, name in (
                (lot.shares_bits, "shares bits"),
                (lot.initialization_prior_units_bits, "prior units bits"),
            ):
                if bits_f64be(bits) < 0:
                    raise ContractError(f"{name} must be non-negative")
            identity = value.identities[lot.identity_position]
            if (lot.acquisition_cost_bits is None) != (identity.cost_bucket_id is None):
                raise ContractError("acquisition cost nullability disagrees with identity")
            if lot.acquisition_cost_bits is not None and bits_f64be(lot.acquisition_cost_bits) <= 0:
                raise ContractError("acquisition cost must be positive")
        free_float = bits_f64be(state.free_float_shares_bits)
        if free_float <= 0:
            raise ContractError("free float must be positive")
        lot_total = math.fsum(bits_f64be(lot.shares_bits) for lot in state.lots)
        if f64be_bits(lot_total) != state.free_float_shares_bits:
            raise ContractError("checkpoint lot mass does not exactly equal free float bits")
        if bits_f64be(state.latent_supply_shares_bits) < 0:
            raise ContractError("latent supply must be non-negative")
        bits_f64be(state.conservation_error_bits)
        _require_ordered_unique(state.input_snapshot_ids, "input_snapshot_ids")
        if not state.input_snapshot_ids:
            raise ContractError("input_snapshot_ids cannot be empty")
        _require_ordered_unique(state.quality_reason_codes, "quality_reason_codes")
        lifecycle = state.lifecycle_continuation
        _require_ordered_unique(lifecycle.active_anchor_ids, "active_anchor_ids")
        if tuple(anchor.anchor_id for anchor in lifecycle.anchors) != lifecycle.active_anchor_ids:
            raise ContractError("active anchor IDs and lifecycle continuation disagree")
        for anchor in lifecycle.anchors:
            for text_value, name in (
                (anchor.anchor_id, "anchor ID"),
                (anchor.root_snapshot_id, "anchor root snapshot ID"),
                (anchor.current_snapshot_id, "anchor current snapshot ID"),
                (anchor.model_version, "anchor model version"),
                (anchor.grid_version, "anchor grid version"),
            ):
                _require_text(text_value, name)
            if anchor.anchor_date > value.checkpoint_date:
                raise ContractError("lifecycle anchor date follows checkpoint")
            if not anchor.cell_ids:
                raise ContractError("lifecycle anchor continuation cannot be empty")
            if anchor.cell_ids != tuple(sorted(set(anchor.cell_ids))):
                raise ContractError("lifecycle cell IDs must be unique and sorted")
            if not (
                len(anchor.cell_ids)
                == len(anchor.origin_units_bits)
                == len(anchor.destination_cell_ids)
            ):
                raise ContractError("lifecycle identity/share/destination lengths mismatch")
            for cell_id in (*anchor.cell_ids, *anchor.destination_cell_ids):
                _require_int64(cell_id, "lifecycle cell ID")
                if cell_id < 0:
                    raise ContractError("lifecycle cell ID must be non-negative")
            root_units = bits_f64be(anchor.root_origin_units_bits)
            if root_units <= 0:
                raise ContractError("lifecycle root origin units must be positive")
            if any(bits_f64be(bits) < 0 for bits in anchor.origin_units_bits):
                raise ContractError("lifecycle origin units must be non-negative")
            retention = bits_f64be(anchor.retention_bits)
            lower = bits_f64be(anchor.lower_bound_bits)
            upper = bits_f64be(anchor.upper_bound_bits)
            if not 0 <= lower <= retention <= upper <= 1:
                raise ContractError("lifecycle retention bounds are invalid")
        for digest in (
            lifecycle.identity_digest,
            lifecycle.share_digest,
            lifecycle.retention_digest,
            lifecycle.destination_digest,
        ):
            _require_digest(digest, "lifecycle digest")
    expected_scopes = ("uniform", "disposition", "active_sticky", "ENSEMBLE")
    if tuple(scope.scope for scope in value.temporal_tracker.scopes) != expected_scopes:
        raise ContractError("temporal tracker scope order/coverage mismatch")
    _require_text(value.temporal_tracker.tracker_version, "tracker version")
    for scope in value.temporal_tracker.scopes:
        _require_ordered_unique(scope.applied_action_ids, "tracker action IDs")
        peak_ids = tuple(peak.peak_track_id for peak in scope.previous_peaks)
        if len(set(peak_ids)) != len(peak_ids):
            raise ContractError("duplicate temporal peak track ID")
        for peak in scope.previous_peaks:
            if peak.age < 0:
                raise ContractError("temporal peak age must be non-negative")
            for bits in (
                peak.band_lower_bits,
                peak.band_upper_bits,
                peak.center_price_bits,
                peak.mass_bits,
                peak.prominence_bits,
            ):
                bits_f64be(bits)
            _require_text(peak.definition_version, "peak definition version")
            _require_text(peak.track_version, "peak track version")
    for digest, name in (
        (value.dependency_manifest_digest, "dependency manifest digest"),
        (value.replay_parameter_manifest_digest, "replay parameter manifest digest"),
        (value.replay_contract_hash, "replay contract hash"),
        (value.semantic_fingerprint, "semantic fingerprint"),
        (value.runtime_fingerprint, "runtime fingerprint"),
        (value.terminal_completeness_digest, "terminal completeness digest"),
    ):
        _require_digest(digest, name)


@dataclass(frozen=True)
class ManifestPart:
    part_kind: str
    relative_path: str
    storage_version: str
    schema_version: str
    part_digest: str
    logical_digest: str


@dataclass(frozen=True)
class FeatureAssetBinding:
    asset_id: str
    snapshot_id: str
    content_digest: str
    available_at: datetime


@dataclass(frozen=True)
class RootManifest:
    storage_version: str
    schema_version: str
    artifact_version: str
    dependency_manifest_version: str
    replay_contract_hash: str
    transition_semantics_version: str
    replay_parameter_manifest_digest: str
    terminal_completeness_schema_version: str
    terminal_completeness_digest: str
    symbol: str
    target_year: int
    seller_models: tuple[str, ...]
    universe_identity: str
    bundle_id: str
    root_id: str
    parts: tuple[ManifestPart, ...]
    feature_asset_binding: FeatureAssetBinding
    dependency_bindings: tuple[DependencyBinding, ...]
    created_at: datetime
    created_by: str
    built_at: datetime
    built_by: str
    manifest_digest: str


def root_manifest_digest(value: RootManifest) -> str:
    return logical_sha256(
        {
            field.name: getattr(value, field.name)
            for field in fields(value)
            if field.name != "manifest_digest"
        }
    )


def validate_root_manifest(value: RootManifest) -> None:
    if (
        value.storage_version,
        value.schema_version,
        value.artifact_version,
        value.dependency_manifest_version,
        value.transition_semantics_version,
        value.terminal_completeness_schema_version,
    ) != (
        STORAGE_VERSION,
        SCHEMA_VERSION,
        ARTIFACT_VERSION,
        DEPENDENCY_MANIFEST_VERSION,
        TRANSITION_SEMANTICS_VERSION,
        TERMINAL_COMPLETENESS_VERSION,
    ):
        raise ContractError("root manifest contains an unknown or mixed version")
    if _SYMBOL_RE.fullmatch(value.symbol) is None or not 1900 <= value.target_year <= 9999:
        raise ContractError("invalid root symbol or target year")
    if value.seller_models != SELLER_MODEL_ORDER:
        raise ContractError("root manifest seller model order/coverage mismatch")
    for text_value, name in (
        (value.universe_identity, "universe identity"),
        (value.bundle_id, "bundle ID"),
        (value.root_id, "root ID"),
        (value.created_by, "created_by"),
        (value.built_by, "built_by"),
    ):
        _require_text(text_value, name)
    _utc_timestamp(value.created_at)
    _utc_timestamp(value.built_at)
    if not value.parts:
        raise ContractError("root manifest parts cannot be empty")
    part_paths: list[str] = []
    for part in value.parts:
        if part.storage_version != STORAGE_VERSION or part.schema_version != SCHEMA_VERSION:
            raise ContractError("same-root mixed storage/schema versions are forbidden")
        _require_text(part.part_kind, "part kind")
        _require_text(part.relative_path, "part path")
        _require_digest(part.part_digest, "part digest")
        _require_digest(part.logical_digest, "part logical digest")
        part_paths.append(part.relative_path)
    if len(set(part_paths)) != len(part_paths):
        raise ContractError("duplicate manifest part path")
    feature = value.feature_asset_binding
    for text_value, name in (
        (feature.asset_id, "feature asset ID"),
        (feature.snapshot_id, "feature snapshot ID"),
    ):
        _require_text(text_value, name)
    _require_digest(feature.content_digest, "feature content digest")
    _utc_timestamp(feature.available_at)
    if not value.dependency_bindings:
        raise ContractError("root manifest dependency bindings cannot be empty")
    for binding in value.dependency_bindings:
        validate_dependency_binding(binding)
        if binding.dependent_bundle_id != value.bundle_id:
            raise ContractError("root dependency names another bundle")
    for digest, name in (
        (value.replay_contract_hash, "replay contract hash"),
        (value.replay_parameter_manifest_digest, "replay parameter manifest digest"),
        (value.terminal_completeness_digest, "terminal completeness digest"),
        (value.manifest_digest, "root manifest digest"),
    ):
        _require_digest(digest, name)
    if root_manifest_digest(value) != value.manifest_digest:
        raise ContractError("root manifest digest mismatch")
