#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen sequential V29R4/V29R5 Stage-B protocol.

``verify-activation`` is metadata-only: it hashes files and inspects parquet
footers, but never decodes a parquet row.  A run mode publishes an immutable
attempt seal before it reads any CY-046 parquet row.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import math
import os
import shutil
import stat
import uuid
from collections.abc import Callable, Iterable
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DEMAND-RECAPTURE-SEQUENTIAL-V29R45"
PREREG = OS_ROOT / f"experiments/{EXPERIMENT}_stage_b_preregistration.json"
REGISTRY = ROOT / "configs/data_asset_registry.json"

ASSET_ID = "CY-046"
AUTHORIZATION_ID = (
    "CYQ-AUTH-ASHARE-DEMAND-RECAPTURE-V29R45-STAGE-B-2018-2021-V1"
)
CY046_ROOT = Path(
    "/Users/linmei/Documents/CY/data/staging/"
    "CY-046-DEMAND-RECAPTURE-V29R45-STAGE-B-2018-2021-V1"
)
ASSET_MANIFEST = CY046_ROOT / "asset_manifest.json"
ACTIVATION_AUDIT = CY046_ROOT / "activation_audit.json"
V29R4_IDENTITY = CY046_ROOT / "v29r4_cap25_identity.parquet"
V29R5_IDENTITY = CY046_ROOT / "v29r5_cap25_identity.parquet"
ADMIN_BOUNDS = CY046_ROOT / "candidate_admin_bounds.parquet"
DAILY_TARGET_PATH = CY046_ROOT / "candidate_daily_path.parquet"
EXECUTION_WINDOW0 = CY046_ROOT / "candidate_execution_window0.parquet"
ACTION_EVENTS = CY046_ROOT / "candidate_action_events.parquet"
MARKET_CALENDAR = CY046_ROOT / "market_calendar.parquet"

CY046_FILES = {
    "v29r4_cap25_identity": V29R4_IDENTITY,
    "v29r5_cap25_identity": V29R5_IDENTITY,
    "candidate_admin_bounds": ADMIN_BOUNDS,
    "candidate_daily_path": DAILY_TARGET_PATH,
    "candidate_execution_window0": EXECUTION_WINDOW0,
    "candidate_action_events": ACTION_EVENTS,
    "market_calendar": MARKET_CALENDAR,
}

OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_demand_recapture_v29r45_stage_b"
)

START = pd.Timestamp("2018-01-01")
END = pd.Timestamp("2021-12-31")
TARGET_FRACTION = Decimal("0.67")
HORIZON = 20
TIME_EXIT_OFFSETS = (21, 22, 23)
PER_SIDE_COST = Decimal("0.002")
MIN_EXACT_TARGET_NET = Decimal("0.04")
MAX_POSITIONS = 50
EXPECTED_SEQUENCE = ("V29R4_CAP25", "V29R5_CAP25")
PROTOCOL_VERSION = "V1_PRE_OUTCOME"
CENT = Decimal("0.01")
ONE = Decimal("1")
PIT_CONTRACT = {
    "grade": "B",
    "strict_pit_eligible": False,
    "qd010_revision_history_complete": False,
    "publication_allowed": False,
    "usage": "RESEARCH_CONDITIONAL_HYPOTHESIS_ONLY",
}

ARM_CONFIG = {
    "v29r4": {
        "protocol_arm": "V29R4_CAP25",
        "identity": V29R4_IDENTITY,
        "expected_rows": 251,
        "expected_by_year": {2018: 178, 2019: 25, 2020: 12, 2021: 36},
    },
    "v29r5": {
        "protocol_arm": "V29R5_CAP25",
        "identity": V29R5_IDENTITY,
        "expected_rows": 255,
        "expected_by_year": {2018: 180, 2019: 30, 2020: 16, 2021: 29},
    },
}

IDENTITY_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "board",
    "signal_date",
    "signal_time",
    "signal_available_at",
    "signal_snapshot_id",
    "signal_daily_snapshot_id",
    "signal_corporate_action_snapshot_id",
    "L",
    "coordinate_factor",
    "signal_industry",
    "cap25_rank",
)
CALENDAR_COLUMNS = ("trade_date", "calendar_index")
PATH_KEY_COLUMNS = (
    "protocol_arm",
    "gap_id",
    "symbol",
    "signal_date",
    "entry_date",
)
ADMIN_BOUND_COLUMNS = (
    *PATH_KEY_COLUMNS,
    "signal_calendar_index",
    "h20_date",
    "h21_date",
    "h22_date",
    "h23_date",
    "admin_eligible",
)
EXECUTION_COLUMNS = (
    *PATH_KEY_COLUMNS,
    "signal_session_offset",
    "entry_session_offset",
    "trade_date",
    "window_index",
    "available_at",
    "open",
    "trade_status",
    "is_st",
    "up_limit_price",
    "down_limit_price",
    "market_rule_valid",
    "source_resolution_minutes",
    "minute_count",
    "distinct_minute_count",
    "ohlc_valid",
    "unit_valid",
    "causal_inputs_valid",
    "hard_valid",
    "invalid_reasons",
    "source",
    "snapshot_id",
    "daily_snapshot_id",
)
DAILY_COLUMNS = (
    *PATH_KEY_COLUMNS,
    "signal_session_offset",
    "entry_session_offset",
    "trade_date",
    "decision_at",
    "available_at",
    "open",
    "high",
    "trade_status",
    "current_day_data_tradable",
    "market_rule_valid",
    "corporate_action_count",
    "corporate_action_ids",
    "share_multiplier",
    "cash_per_share",
    "rights_ratio",
    "rights_price",
    "corporate_action_valid",
    "corporate_action_blocking",
    "corporate_action_snapshot_id",
    "hard_valid",
    "invalid_reasons",
    "snapshot_id",
    "daily_snapshot_id",
)
ACTION_COLUMNS = (
    *PATH_KEY_COLUMNS,
    "h23_date",
    "event_id",
    "action_kind",
    "known_at",
    "available_at",
    "effective_date",
    "cash_per_share",
    "share_multiplier",
    "rights_ratio",
    "rights_price",
    "source_terms_complete",
    "execution_timing_resolved",
    "snapshot_id",
)

PARQUET_REQUIRED_COLUMNS = {
    "v29r4_cap25_identity": set(IDENTITY_COLUMNS),
    "v29r5_cap25_identity": set(IDENTITY_COLUMNS),
    "candidate_admin_bounds": set(ADMIN_BOUND_COLUMNS),
    "candidate_daily_path": set(DAILY_COLUMNS),
    "candidate_execution_window0": set(EXECUTION_COLUMNS),
    "candidate_action_events": set(ACTION_COLUMNS),
    "market_calendar": set(CALENDAR_COLUMNS),
}

# Frozen from the builder's explicit Arrow schemas.  These fingerprints make
# activation depend on physical types/nullability/order, including an empty
# action ledger, rather than on a permissive required-column subset.
EXPECTED_OUTPUT_SCHEMA_SHA256 = {
    "v29r4_cap25_identity": "1610b077cefaeb77ede54bea1eec7a976862b23d7c25c5aa776f8dce0871068c",
    "v29r5_cap25_identity": "1610b077cefaeb77ede54bea1eec7a976862b23d7c25c5aa776f8dce0871068c",
    "candidate_admin_bounds": "61625a38f92652c282c77e92022eaf09174f93d5ebd9aa8ae00673f0c70e7294",
    "candidate_daily_path": "1acc93324be6d8c933ecd9640719c611fb487e88779fd377be00a28c7304bbe6",
    "candidate_execution_window0": "8d7d99391f794c8a4bcde1c824e06e243cd82632e8b8cbd576a45374ff133760",
    "candidate_action_events": "bb410c244bbe394ee8a43bcd78fdbfc18100400e9398b3fb8e2ad4f2a1833a6a",
    "market_calendar": "989f45929eb7870977ced35107a181977de3a020a4466f2e8d37ffe24d56affe",
}
EXPECTED_FIXED_OUTPUT_ROWS = {
    "v29r4_cap25_identity": 251,
    "v29r5_cap25_identity": 255,
    "candidate_admin_bounds": 506,
    "candidate_daily_path": 505 * 25,
    "candidate_execution_window0": 505 * 24,
}
MANIFEST_TOP_LEVEL_KEYS = {
    "asset_id",
    "status",
    "authorization_id",
    "coverage",
    "protocol",
    "files",
    "source_bindings",
    "pit_contract",
    "content_contract",
}
ACTIVATION_AUDIT_TOP_LEVEL_KEYS = {
    "asset_id",
    "status",
    "gate_pass",
    "manifest_path",
    "manifest_sha256",
    "preregistration_sha256",
    "runner_sha256",
    "asset_builder_sha256",
    "source_metadata_gate",
    "identity_count_gate",
    "scope_gate",
    "snapshot_nonempty_conflict_gate",
    "post_2021_rows",
    "outcome_or_return_source_columns",
    "audit_counts",
    "parquet_rows_opened_for_content_build",
    "outcome_or_return_rows_opened",
    "returns_computed",
    "registry_modified",
    "post_content_source_revalidation",
    "output_schema_sha256",
    "pit_contract",
}
AUDIT_COUNT_KEYS = {
    "r4_cap25_rows",
    "r5_cap25_rows",
    "administrative_bound_rows",
    "r4_administratively_eligible",
    "r4_administratively_censored",
    "r5_administratively_eligible",
    "r5_administratively_censored",
    "cy006_requested_rows",
    "cy006_missing_rows_preserved",
    "cy006_hard_invalid_rows_preserved",
    "cy008_requested_window0_rows",
    "cy008_missing_rows_preserved",
    "cy008_hard_invalid_rows_preserved",
    "cy008_or_cy006_snapshot_missing_rows_preserved",
    "cy008_cy006_nonempty_snapshot_conflicts",
    "qd010_bounded_event_rows",
    "qd010_cash_only_rows",
    "qd010_risk_share_rows",
    "qd010_risk_rights_rows",
    "qd010_unresolved_or_unsupported_rows",
    "post_2021_rows",
    "invalid_rows_filtered",
}

MECHANICAL_NO_ENTRY = {
    "NO_ENTRY_MECHANICAL_NOT_TRADED",
    "NO_ENTRY_MECHANICAL_UP_LIMIT",
    "NO_ENTRY_ACTION_COORDINATE",
    "NO_ENTRY_PENDING_RISK_ACTION",
    "NO_ENTRY_INSUFFICIENT_A67_HEADROOM",
}


class StageBError(RuntimeError):
    """Fail closed on identity, chronology, data quality, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_json_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageBError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StageBError(f"{label} is not a JSON object")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)
    fsync_file(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)
    fsync_file(path)


def fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def path_lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def publish_no_replace(staged: Path, target: Path) -> None:
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise StageBError(f"publish parent is not a real directory: {target.parent}")
    if path_lexists(target):
        raise StageBError(f"refusing to overwrite {target}")
    linked = False
    try:
        os.link(staged, target, follow_symlinks=False)
        linked = True
        fsync_directory(target.parent)
        staged.unlink()
        fsync_directory(staged.parent)
    except FileExistsError as exc:
        raise StageBError(f"refusing to overwrite {target}") from exc
    except Exception:
        # Do not leave a canonical directory entry that the caller never had a
        # chance to record.  The inode is still mutable at this point.
        if linked and path_lexists(target):
            target.unlink()
            fsync_directory(target.parent)
        raise


def publish_directory_no_replace(staged: Path, target: Path) -> None:
    """Atomically publish a directory with Darwin RENAME_EXCL semantics."""
    if staged.parent != target.parent:
        raise StageBError("result staging directory is not on the same parent")
    libc = ctypes.CDLL(None, use_errno=True)
    renamex_np = libc.renamex_np
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    if renamex_np(os.fsencode(staged), os.fsencode(target), 0x00000004) != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise StageBError(f"refusing to overwrite {target}")
        raise OSError(error, os.strerror(error), str(target))
    fsync_directory(target.parent)


def set_user_immutable(path: Path) -> None:
    """Set and verify Darwin UF_IMMUTABLE; permissions alone are not a seal."""
    flag = getattr(stat, "UF_IMMUTABLE", None)
    if flag is None or not hasattr(os, "chflags"):
        raise StageBError("host lacks the required user-immutable seal")
    if path.is_symlink() or not path.exists():
        raise StageBError(f"immutable seal target is missing or a symlink: {path}")
    os.chflags(path, path.stat().st_flags | flag, follow_symlinks=False)
    if not path.stat().st_flags & flag:
        raise StageBError(f"user-immutable seal did not persist: {path}")
    identity = path.lstat()
    if stat.S_ISREG(identity.st_mode):
        fsync_file(path)
    elif stat.S_ISDIR(identity.st_mode):
        fsync_directory(path)
    else:
        raise StageBError(f"immutable seal target is not a file or directory: {path}")


def freeze_published_tree(root: Path, expected_names: set[str]) -> None:
    """Make every result file and then its canonical directory undeletable."""
    if not root.is_dir() or root.is_symlink():
        raise StageBError(f"published result root is invalid: {root}")
    members = {path.name: path for path in root.iterdir()}
    if set(members) != expected_names:
        raise StageBError(f"published result inventory drift: {sorted(members)}")
    for path in members.values():
        identity = path.lstat()
        if not stat.S_ISREG(identity.st_mode) or stat.S_ISLNK(identity.st_mode):
            raise StageBError(f"unexpected published result member: {path}")
        if is_user_immutable(path):
            if stat.S_IMODE(identity.st_mode) != 0o444:
                raise StageBError(f"immutable result member has wrong mode: {path}")
            continue
        os.chmod(path, 0o444)
        set_user_immutable(path)
    os.chmod(root, 0o555)
    set_user_immutable(root)


def is_user_immutable(path: Path) -> bool:
    flag = getattr(stat, "UF_IMMUTABLE", None)
    if flag is None:
        return False
    try:
        identity = path.lstat()
    except OSError:
        return False
    return bool(not stat.S_ISLNK(identity.st_mode) and identity.st_flags & flag)


def reject_symlink_components(path: Path, label: str) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    for component in (absolute, *absolute.parents):
        try:
            mode = component.lstat().st_mode
        except OSError as exc:
            raise StageBError(f"{label} path component unavailable: {component}") from exc
        if stat.S_ISLNK(mode):
            raise StageBError(f"{label} path contains a symlink: {component}")
    return absolute


def initialize_output_anchor() -> None:
    """Create two fixed arm slots, then make the root entry unreplaceable."""
    parent = reject_symlink_components(OUTPUT_ROOT.parent, "output parent")
    if not stat.S_ISDIR(parent.lstat().st_mode):
        raise StageBError("output parent is not a regular directory")
    if not path_lexists(OUTPUT_ROOT):
        staged = OUTPUT_ROOT.with_name(
            f".{OUTPUT_ROOT.name}.anchor-{os.getpid()}-{uuid.uuid4().hex}"
        )
        try:
            staged.mkdir(mode=0o700)
            for arm in ARM_CONFIG:
                (staged / arm).mkdir(mode=0o700)
            os.chmod(staged, 0o555)
            publish_directory_no_replace(staged, OUTPUT_ROOT)
            set_user_immutable(OUTPUT_ROOT)
            fsync_directory(parent)
        except Exception:
            if staged.exists():
                shutil.rmtree(staged)
            raise
    root = reject_symlink_components(OUTPUT_ROOT, "output anchor")
    if (
        not stat.S_ISDIR(root.lstat().st_mode)
        or stat.S_IMODE(root.stat().st_mode) != 0o555
        or not is_user_immutable(root)
    ):
        raise StageBError("output anchor is not immutable 0555")
    members = {path.name: path for path in root.iterdir()}
    if set(members) != set(ARM_CONFIG):
        raise StageBError("output anchor slot inventory drift")
    for arm, slot in members.items():
        identity = slot.lstat()
        if stat.S_ISLNK(identity.st_mode) or not stat.S_ISDIR(identity.st_mode):
            raise StageBError(f"output arm slot is invalid: {arm}")
        mode = stat.S_IMODE(identity.st_mode)
        if (is_user_immutable(slot) and mode != 0o555) or (
            not is_user_immutable(slot) and mode != 0o700
        ):
            raise StageBError(f"output arm slot mode/seal drift: {arm}")


def preflight_slot_capabilities(slot: Path) -> None:
    """Prove hard-link commit, fsync and UF_IMMUTABLE before opening rows."""
    if any(slot.iterdir()):
        raise StageBError(f"attempt slot is not pristine: {slot}")
    probe = slot / f".seal-probe-{uuid.uuid4().hex}"
    linked = slot / f".seal-probe-link-{uuid.uuid4().hex}"
    staged_directory = slot / f".rename-probe-{uuid.uuid4().hex}"
    published_directory = slot / f".rename-probe-published-{uuid.uuid4().hex}"
    try:
        descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        try:
            payload = b"preflight\n"
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise StageBError("short write during output preflight")
                written += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        publish_no_replace(probe, linked)
        set_user_immutable(linked)
        if linked.read_bytes() != b"preflight\n":
            raise StageBError("output preflight content mismatch")
        os.chflags(
            linked,
            linked.stat().st_flags & ~stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        linked.unlink()
        staged_directory.mkdir(mode=0o700)
        publish_directory_no_replace(staged_directory, published_directory)
        published_directory.rmdir()
        os.chmod(slot, 0o555)
        set_user_immutable(slot)
        os.chflags(
            slot,
            slot.lstat().st_flags & ~stat.UF_IMMUTABLE,
            follow_symlinks=False,
        )
        os.chmod(slot, 0o700)
        fsync_directory(slot)
    finally:
        if is_user_immutable(slot):
            os.chflags(
                slot,
                slot.lstat().st_flags & ~stat.UF_IMMUTABLE,
                follow_symlinks=False,
            )
        if stat.S_ISDIR(slot.lstat().st_mode):
            os.chmod(slot, 0o700)
        for path in (probe, linked):
            if path_lexists(path):
                if is_user_immutable(path):
                    os.chflags(
                        path,
                        path.stat().st_flags & ~stat.UF_IMMUTABLE,
                        follow_symlinks=False,
                    )
                path.unlink()
        for path in (staged_directory, published_directory):
            if path_lexists(path):
                path.rmdir()


def _only(items: Iterable[dict[str, Any]], label: str) -> dict[str, Any]:
    values = list(items)
    if len(values) != 1:
        raise StageBError(f"expected exactly one {label}, found {len(values)}")
    return values[0]


def _nonempty(value: Any) -> bool:
    return bool(pd.notna(value) and str(value).strip())


def _finite(value: Any) -> bool:
    try:
        return bool(math.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _finite_positive(value: Any) -> bool:
    return _finite(value) and float(value) > 0


def decimal_from_source(value: Any, label: str) -> Decimal:
    """Parse the source's canonical string; never decide a gate in binary float."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        raise StageBError(f"{label} is missing")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise StageBError(f"{label} is not Decimal-compatible") from exc
    if not result.is_finite():
        raise StageBError(f"{label} is not finite")
    return result


def positive_decimal(value: Any, label: str) -> Decimal:
    result = decimal_from_source(value, label)
    if result <= 0:
        raise StageBError(f"{label} is not positive")
    return result


def nonnegative_decimal(value: Any, label: str) -> Decimal:
    result = decimal_from_source(value, label)
    if result < 0:
        raise StageBError(f"{label} is negative")
    return result


def observed_price_tick(value: Any, label: str) -> int:
    """Return integer cents only when the observed price is already canonical."""
    price = positive_decimal(value, label)
    cents = price * 100
    rounded = cents.quantize(ONE, rounding=ROUND_HALF_UP)
    if cents != rounded:
        raise StageBError(f"{label} is not a canonical 0.01-CNY tick")
    return int(rounded)


def theoretical_sell_tick(value: Decimal, label: str) -> int:
    if not value.is_finite() or value <= 0:
        raise StageBError(f"{label} is not a positive finite threshold")
    return int((value * 100).to_integral_value(rounding=ROUND_CEILING))


def tick_price(tick: int) -> Decimal:
    if not isinstance(tick, int) or tick <= 0:
        raise StageBError("invalid positive price tick")
    return Decimal(tick) / 100


def _parquet_columns(path: Path) -> set[str]:
    """Read only the parquet footer/schema, never a row group."""
    return set(pq.read_schema(path).names)


def _schema_descriptor(schema: Any) -> list[dict[str, Any]]:
    return [
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ]


def _schema_sha256(schema: Any) -> str:
    encoded = json.dumps(
        _schema_descriptor(schema), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parquet_footer_facts(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    return {
        "rows": parquet.metadata.num_rows,
        "row_groups": parquet.metadata.num_row_groups,
        "schema": _schema_descriptor(parquet.schema_arrow),
        "schema_sha256": _schema_sha256(parquet.schema_arrow),
    }


def _manifest_file_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = manifest.get("files")
    if not isinstance(files, list) or not all(isinstance(item, dict) for item in files):
        raise StageBError("CY046 manifest files must be a list of objects")
    mapped: dict[str, dict[str, Any]] = {}
    for item in files:
        role = item.get("role")
        if not isinstance(role, str) or not role or role in mapped:
            raise StageBError(f"missing or duplicate CY046 manifest role: {role!r}")
        mapped[role] = item
    return mapped


def _ensure_bound_path(path: Path) -> Path:
    """Bind a lexical regular file beneath the sealed, non-symlink CY046 root."""
    root = reject_symlink_components(CY046_ROOT, "CY046 root")
    bound = reject_symlink_components(path, "CY046 member")
    try:
        bound.relative_to(root)
    except ValueError as exc:
        raise StageBError(f"declared CY046 path escapes its bound root: {path}") from exc
    identity = bound.lstat()
    if (
        not stat.S_ISREG(identity.st_mode)
        or stat.S_IMODE(identity.st_mode) != 0o444
        or not is_user_immutable(bound)
    ):
        raise StageBError(f"CY046 member is not immutable 0444 regular data: {bound}")
    return bound


def verify_activation() -> dict[str, Any]:
    """Verify CY046 using JSON, file hashes, sizes, and parquet footers only."""
    required = (
        PREREG,
        REGISTRY,
        ASSET_MANIFEST,
        ACTIVATION_AUDIT,
        *CY046_FILES.values(),
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise StageBError("missing activation input: " + ",".join(missing))
    root = reject_symlink_components(CY046_ROOT, "CY046 root")
    root_identity = root.lstat()
    expected_inventory = {
        "asset_manifest.json",
        "activation_audit.json",
        *(path.name for path in CY046_FILES.values()),
    }
    if (
        not stat.S_ISDIR(root_identity.st_mode)
        or stat.S_IMODE(root_identity.st_mode) != 0o555
        or not is_user_immutable(root)
        or {path.name for path in root.iterdir()} != expected_inventory
    ):
        raise StageBError("CY046 root is not the exact immutable 0555 asset")
    _ensure_bound_path(ASSET_MANIFEST)
    _ensure_bound_path(ACTIVATION_AUDIT)

    prereg = load_json(PREREG, "Stage-B preregistration")
    prereg_pit = prereg.get("required_bounded_input", {}).get("pit_limitation", {})
    if (
        prereg.get("experiment") != EXPERIMENT
        or prereg.get("stage")
        != "DEVELOPMENT_STAGE_B_PRE_OUTCOME_EXECUTION_FREEZE"
        or prereg.get("status")
        != "FROZEN_PROTOCOL_AWAITING_CY046_ACTIVATION_AND_RUNNER_REVIEW"
        or prereg.get("development") != ["2018-01-01", "2021-12-31"]
        or prereg.get("post_2021_access") != "PROHIBITED"
        or prereg.get("protocol_version") != PROTOCOL_VERSION
        or tuple(prereg.get("sequential_testing", {}).get("order", ()))
        != EXPECTED_SEQUENCE
        or prereg_pit.get("grade") != "PIT-B_RESEARCH_CONDITIONAL"
        or prereg_pit.get("strict_pit_eligible") is not False
        or prereg_pit.get("qd010_revision_history_complete") is not False
        or prereg_pit.get("publication_allowed") is not False
    ):
        raise StageBError("Stage-B preregistration semantics drift")

    actual_manifest_sha = sha256(ASSET_MANIFEST)
    actual_runner_sha = sha256(Path(__file__))
    actual_prereg_sha = sha256(PREREG)
    registry = load_json(REGISTRY, "data registry")
    assets = registry.get("assets")
    authorizations = registry.get("bounded_authorizations")
    if not isinstance(assets, list) or not isinstance(authorizations, list):
        raise StageBError("registry lacks assets or bounded_authorizations")
    asset = _only(
        (item for item in assets if item.get("asset_id") == ASSET_ID),
        f"registry asset {ASSET_ID}",
    )
    authorization = _only(
        (
            item
            for item in authorizations
            if item.get("authorization_id") == AUTHORIZATION_ID
        ),
        f"authorization {AUTHORIZATION_ID}",
    )
    lineage = asset.get("lineage", {})
    coverage = asset.get("coverage", {})
    if (
        asset.get("status") != "RESEARCH_CONDITIONAL"
        or asset.get("pit_grade") != "B"
        or asset.get("physical_state") != "MATERIALIZED"
        or Path(str(asset.get("location", ""))) != CY046_ROOT
        or lineage.get("record_available_at") is not True
        or lineage.get("record_snapshot_id") is not True
        or lineage.get("immutable_manifest") is not True
        or Path(str(lineage.get("manifest_path", ""))) != ASSET_MANIFEST
        or lineage.get("manifest_sha256") != actual_manifest_sha
        or lineage.get("bounded_authorization_id") != AUTHORIZATION_ID
        or coverage.get("authorized_start") != "2018-01-01"
        or coverage.get("authorized_end") != "2021-12-31"
    ):
        raise StageBError("CY046 registry asset semantics drift")

    bound_manifest = authorization.get("bound_manifest", {})
    bound_protocol = authorization.get("bound_protocol", {})
    scope = authorization.get("scope", {})
    if (
        authorization.get("asset_id") != ASSET_ID
        or authorization.get("purpose")
        != "ASHARE_FROZEN_DEVELOPMENT_OUTCOME_ATTACHMENT"
        or authorization.get("outcome_attachment_authorized") is not True
        or authorization.get("charts_authorized") is not False
        or authorization.get("validation_authorized") is not False
        or authorization.get("post_2021_read_authorized") is not False
        or authorization.get("strict_pit_claim_authorized") is not False
        or authorization.get("publication_allowed") is not False
        or authorization.get("candidate_reselection_authorized") is not False
        or authorization.get("raw_competing_cohort_outcomes_authorized") is not False
        or authorization.get("portfolio_replay_authorized") is not True
        or tuple(authorization.get("sequential_order", ())) != EXPECTED_SEQUENCE
        or scope.get("start") != "2018-01-01"
        or scope.get("end") != "2021-12-31"
        or bound_manifest.get("path") != str(ASSET_MANIFEST)
        or bound_manifest.get("sha256") != actual_manifest_sha
        or bound_protocol.get("path") != str(PREREG)
        or bound_protocol.get("sha256") != actual_prereg_sha
        or bound_protocol.get("runner_path") != str(Path(__file__).resolve())
        or bound_protocol.get("runner_sha256") != actual_runner_sha
    ):
        raise StageBError("CY046 bounded authorization semantics drift")

    manifest = load_json(ASSET_MANIFEST, "CY046 manifest")
    protocol = manifest.get("protocol", {})
    content = manifest.get("content_contract", {})
    source_bindings = manifest.get("source_bindings", {})
    builder_path = Path(str(protocol.get("builder_path", "")))
    if (
        set(manifest) != MANIFEST_TOP_LEVEL_KEYS
        or manifest.get("asset_id") != ASSET_ID
        or manifest.get("status") != "PASS"
        or manifest.get("authorization_id") != AUTHORIZATION_ID
        or manifest.get("coverage")
        != {"start": "2018-01-01", "end": "2021-12-31"}
        or manifest.get("pit_contract") != PIT_CONTRACT
        or protocol.get("path") != str(PREREG)
        or protocol.get("sha256") != actual_prereg_sha
        or protocol.get("runner_path") != str(Path(__file__).resolve())
        or protocol.get("runner_sha256") != actual_runner_sha
        or not builder_path.is_file()
        or protocol.get("builder_sha256") != sha256(builder_path)
        or content.get("sequential_arms") != list(EXPECTED_SEQUENCE)
        or content.get("v29r4_cap25_exact_rows") != 251
        or content.get("v29r4_by_signal_year")
        != {"2018": 178, "2019": 25, "2020": 12, "2021": 36}
        or content.get("v29r5_cap25_exact_rows") != 255
        or content.get("v29r5_by_signal_year")
        != {"2018": 180, "2019": 30, "2020": 16, "2021": 29}
        or content.get("v29r4_admin_eligible") != 251
        or content.get("v29r5_admin_eligible") != 254
        or content.get("v29r5_admin_censored") != 1
        or content.get("administrative_censor_before_price_or_action_join") is not True
        or content.get("candidate_daily_signal_session_offsets") != [0, 24]
        or content.get("candidate_daily_entry_session_offsets") != [-1, 23]
        or content.get("candidate_execution_signal_session_offsets") != [1, 24]
        or content.get("candidate_execution_entry_session_offsets") != [0, 23]
        or content.get("cy008_window_index") != 0
        or content.get("cy008_daily_snapshot_bound_to_cy006_snapshot") is not True
        or content.get("candidate_action_effective_interval") != "(signal_date,h23_date]"
        or content.get("qd010_aliases")
        != {
            "available_at": "known_at",
            "cash_per_share": "cash_per_share_gross",
            "rights_ratio": "rights_subscription_ratio",
            "rights_price": "rights_subscription_price",
            "snapshot_id": "source_snapshot_id",
        }
        or content.get("ambiguous_or_incomplete_qd010_policy")
        != "ABORT_ACTIVATION_WITHOUT_CANONICAL_PUBLICATION"
        or content.get("cy006_cy008_invalid_or_missing_evidence_preserved") is not True
        or content.get("invalid_rows_filtered") != 0
        or content.get("post_2021_rows") != 0
        or content.get("outcome_or_return_source_columns") != []
        or content.get("returns_computed") is not False
        or content.get("manifest_does_not_hash_activation_audit") is not True
        or content.get("macos_readonly_uf_immutable_required") is not True
        or content.get("output_schema_sha256") != EXPECTED_OUTPUT_SCHEMA_SHA256
        or source_bindings.get("asset_id") != ASSET_ID
        or source_bindings.get("status") != "PASS_METADATA_ONLY"
        or source_bindings.get("coverage")
        != {"start": "2018-01-01", "end": "2021-12-31"}
        or source_bindings.get("selected_source_partition_years") != [2018, 2019, 2020, 2021]
        or source_bindings.get("parquet_rows_opened") is not False
        or source_bindings.get("output_written") is not False
        or source_bindings.get("outcome_or_return_sources_resolved") is not False
    ):
        raise StageBError("CY046 manifest protocol or coverage drift")
    planned_registry = source_bindings.get("registry_snapshot", {})
    planned_input_hashes = planned_registry.get("registered_input_entry_sha256")
    current_input_hashes = {
        asset_id: normalized_json_sha256(
            _only(
                (item for item in assets if item.get("asset_id") == asset_id),
                f"registry input asset {asset_id}",
            )
        )
        for asset_id in ("CY-006", "CY-008", "QD-010")
    }
    if (
        planned_registry.get("cy046_absent") is not True
        or planned_input_hashes != current_input_hashes
    ):
        raise StageBError("CY046 source registry bindings drift")
    file_map = _manifest_file_map(manifest)
    if set(file_map) != set(CY046_FILES):
        raise StageBError("CY046 manifest file-role inventory drift")

    verified_files: dict[str, str] = {}
    observed_rows: dict[str, int] = {}
    for role, path in CY046_FILES.items():
        path = _ensure_bound_path(path)
        item = file_map[role]
        relative = str(path.relative_to(CY046_ROOT))
        digest = sha256(path)
        footer = _parquet_footer_facts(path)
        if (
            item.get("path") != relative
            or item.get("size") != path.stat().st_size
            or item.get("sha256") != digest
            or item.get("rows") != footer["rows"]
            or item.get("row_groups") != footer["row_groups"]
            or item.get("schema") != footer["schema"]
            or item.get("schema_sha256") != footer["schema_sha256"]
            or footer["schema_sha256"] != EXPECTED_OUTPUT_SCHEMA_SHA256[role]
            or (
                role in EXPECTED_FIXED_OUTPUT_ROWS
                and footer["rows"] != EXPECTED_FIXED_OUTPUT_ROWS[role]
            )
        ):
            raise StageBError(f"CY046 manifest identity drift for {role}")
        verified_files[role] = digest
        observed_rows[role] = int(footer["rows"])
        required_columns = PARQUET_REQUIRED_COLUMNS.get(role)
        if required_columns is not None:
            observed_columns = _parquet_columns(path)
            if not required_columns.issubset(observed_columns):
                raise StageBError(
                    f"CY046 {role} schema misses required projected columns"
                )

    audit = load_json(ACTIVATION_AUDIT, "CY046 activation audit")
    actual_audit_sha = sha256(ACTIVATION_AUDIT)
    bound_artifacts = authorization.get("bound_artifacts")
    if not isinstance(bound_artifacts, list):
        raise StageBError("CY046 authorization lacks bound artifacts")
    artifact_rows = [item for item in bound_artifacts if isinstance(item, dict)]
    artifact_paths = [str(item.get("path")) for item in artifact_rows]
    artifact_roles = [str(item.get("role")) for item in artifact_rows]
    if (
        len(artifact_rows) != len(bound_artifacts)
        or any(not _nonempty(value) for value in (*artifact_paths, *artifact_roles))
        or len(artifact_paths) != len(set(artifact_paths))
        or len(artifact_roles) != len(set(artifact_roles))
    ):
        raise StageBError("CY046 authorization artifact identities are ambiguous")
    by_artifact_path = {
        str(item.get("path")): item
        for item in bound_artifacts
        if isinstance(item, dict) and _nonempty(item.get("path"))
    }
    audit_binding = by_artifact_path.get(str(ACTIVATION_AUDIT), {})
    builder_binding = by_artifact_path.get(str(builder_path), {})
    counts = audit.get("audit_counts")
    revalidation = content.get("post_content_source_revalidation")
    expected_count_values = {
        "r4_cap25_rows": observed_rows["v29r4_cap25_identity"],
        "r5_cap25_rows": observed_rows["v29r5_cap25_identity"],
        "administrative_bound_rows": observed_rows["candidate_admin_bounds"],
        "r4_administratively_eligible": 251,
        "r4_administratively_censored": 0,
        "r5_administratively_eligible": 254,
        "r5_administratively_censored": 1,
        "cy006_requested_rows": observed_rows["candidate_daily_path"],
        "cy008_requested_window0_rows": observed_rows[
            "candidate_execution_window0"
        ],
        "qd010_bounded_event_rows": observed_rows["candidate_action_events"],
        "cy008_cy006_nonempty_snapshot_conflicts": 0,
        "qd010_unresolved_or_unsupported_rows": 0,
        "post_2021_rows": 0,
        "invalid_rows_filtered": 0,
    }
    counts_valid = bool(
        isinstance(counts, dict)
        and set(counts) == AUDIT_COUNT_KEYS
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in counts.values()
        )
        and all(counts.get(key) == value for key, value in expected_count_values.items())
        and counts.get("qd010_cash_only_rows", -1)
        + counts.get("qd010_risk_share_rows", -1)
        + counts.get("qd010_risk_rights_rows", -1)
        == counts.get("qd010_bounded_event_rows")
        and counts.get("cy006_missing_rows_preserved", 1 << 60)
        <= counts.get("cy006_requested_rows", -1)
        and counts.get("cy006_hard_invalid_rows_preserved", 1 << 60)
        <= counts.get("cy006_requested_rows", -1)
        and counts.get("cy008_missing_rows_preserved", 1 << 60)
        <= counts.get("cy008_requested_window0_rows", -1)
        and counts.get("cy008_hard_invalid_rows_preserved", 1 << 60)
        <= counts.get("cy008_requested_window0_rows", -1)
        and counts.get("cy008_or_cy006_snapshot_missing_rows_preserved", 1 << 60)
        <= counts.get("cy008_requested_window0_rows", -1)
    )
    if (
        set(audit) != ACTIVATION_AUDIT_TOP_LEVEL_KEYS
        or audit.get("asset_id") != ASSET_ID
        or audit.get("status") != "PASS"
        or audit.get("gate_pass") is not True
        or audit.get("source_metadata_gate") != "PASS"
        or audit.get("identity_count_gate") != "PASS"
        or audit.get("scope_gate") != "PASS"
        or audit.get("snapshot_nonempty_conflict_gate") != "PASS"
        or audit.get("post_2021_rows") != 0
        or audit.get("outcome_or_return_source_columns") != []
        or audit.get("manifest_path") != "asset_manifest.json"
        or audit.get("manifest_sha256") != actual_manifest_sha
        or audit.get("preregistration_sha256") != actual_prereg_sha
        or audit.get("runner_sha256") != actual_runner_sha
        or audit.get("asset_builder_sha256") != sha256(builder_path)
        or audit.get("parquet_rows_opened_for_content_build") is not True
        or audit.get("outcome_or_return_rows_opened") is not False
        or audit.get("returns_computed") is not False
        or audit.get("registry_modified") is not False
        or audit.get("post_content_source_revalidation") != revalidation
        or not isinstance(revalidation, dict)
        or revalidation.get("sha256_device_inode_size_match") is not True
        or not isinstance(revalidation.get("files_revalidated"), int)
        or revalidation.get("files_revalidated", 0) <= 0
        or audit.get("output_schema_sha256") != EXPECTED_OUTPUT_SCHEMA_SHA256
        or audit.get("pit_contract") != PIT_CONTRACT
        or not counts_valid
        or audit_binding.get("role") != "activation_audit"
        or builder_binding.get("role") != "asset_builder"
        or audit_binding.get("sha256") != actual_audit_sha
        or builder_binding.get("sha256") != sha256(builder_path)
    ):
        raise StageBError("CY046 activation audit did not pass closed gates")

    cohorts = prereg.get("frozen_cohorts", {})
    for arm, stage_key, selected_key in (
        ("V29R4_CAP25", "stage_a_freeze", "stage_a_selected"),
        ("V29R5_CAP25", "stage_a_freeze", "stage_a_primary"),
    ):
        item = cohorts.get(arm, {})
        for key in (stage_key, selected_key):
            identity = item.get(key, {})
            path = Path(str(identity.get("path", "")))
            if not path.is_file() or sha256(path) != identity.get("sha256"):
                raise StageBError(f"frozen {arm} identity drift: {key}")

    return {
        "verified": True,
        "mode": "METADATA_ONLY_NO_PARQUET_ROWS_DECODED",
        "runner_sha256": actual_runner_sha,
        "preregistration_sha256": actual_prereg_sha,
        "manifest_sha256": actual_manifest_sha,
        "activation_audit_sha256": actual_audit_sha,
        "registry_asset_normalized_sha256": normalized_json_sha256(asset),
        "registry_authorization_normalized_sha256": normalized_json_sha256(
            authorization
        ),
        "registered_input_entry_sha256": current_input_hashes,
        "pit_contract": PIT_CONTRACT,
        "files": verified_files,
        "frozen_cohorts": {
            arm: {
                key: sha256(Path(identity["path"]))
                for key, identity in item.items()
                if key in {"stage_a_freeze", "stage_a_selected", "stage_a_primary"}
            }
            for arm, item in cohorts.items()
        },
    }


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise StageBError(f"{label} misses columns: {missing}")


def normalize_calendar(calendar: pd.DataFrame) -> pd.DataFrame:
    _require_columns(calendar, CALENDAR_COLUMNS, "market calendar")
    result = calendar.loc[:, CALENDAR_COLUMNS].copy()
    result["trade_date"] = pd.to_datetime(result.trade_date).dt.normalize()
    result["calendar_index"] = pd.to_numeric(result.calendar_index, errors="coerce")
    if (
        result.empty
        or result.trade_date.isna().any()
        or result.calendar_index.isna().any()
        or result.trade_date.duplicated().any()
        or result.calendar_index.duplicated().any()
        or result.trade_date.lt(START).any()
        or result.trade_date.gt(END).any()
        or result.calendar_index.mod(1).ne(0).any()
    ):
        raise StageBError("market calendar identity or range failure")
    result["calendar_index"] = result.calendar_index.astype("int64")
    result = result.rename(columns={"calendar_index": "cal_idx"})
    result = result.sort_values("cal_idx", kind="mergesort").reset_index(drop=True)
    if int(result.cal_idx.iloc[0]) != 0 or (
        len(result) > 1 and not np.diff(result.cal_idx.to_numpy()).tolist() == [1] * (
        len(result) - 1
        )
    ):
        raise StageBError("market calendar cal_idx is not contiguous")
    return result


def normalize_candidates(
    candidates: pd.DataFrame,
    *,
    expected_rows: int | None = None,
    expected_by_year: dict[int, int] | None = None,
) -> pd.DataFrame:
    _require_columns(candidates, IDENTITY_COLUMNS, "candidate identity")
    result = candidates.loc[:, IDENTITY_COLUMNS].copy()
    for column in ("signal_date", "signal_time", "signal_available_at"):
        result[column] = pd.to_datetime(result[column])
    # L and coordinate_factor are accounting coordinates.  Preserve their
    # canonical source representation so every later gate is Decimal-exact.
    rank = pd.to_numeric(result.cap25_rank, errors="coerce")

    def is_positive_decimal(value: Any) -> bool:
        try:
            positive_decimal(value, "candidate coordinate")
        except StageBError:
            return False
        return True

    invalid = (
        result.protocol_arm.map(_nonempty).eq(False)
        | result.gap_id.map(_nonempty).eq(False)
        | result.symbol.map(_nonempty).eq(False)
        | result.board.map(_nonempty).eq(False)
        | result.signal_industry.map(_nonempty).eq(False)
        | result.signal_date.isna()
        | result.signal_time.isna()
        | result.signal_available_at.isna()
        | result.signal_available_at.gt(result.signal_time)
        | result.signal_time.ne(result.signal_date.dt.normalize() + pd.Timedelta(hours=15))
        | result.signal_snapshot_id.map(_nonempty).eq(False)
        | result.signal_daily_snapshot_id.map(_nonempty).eq(False)
        | result.signal_corporate_action_snapshot_id.map(_nonempty).eq(False)
        | result.L.map(is_positive_decimal).eq(False)
        | result.coordinate_factor.map(is_positive_decimal).eq(False)
        | rank.isna()
        | rank.mod(1).ne(0)
        | rank.lt(1)
        | rank.gt(25)
    )
    if (
        invalid.any()
        or result.empty
        or result.gap_id.duplicated().any()
        or result.signal_date.dt.normalize().lt(START).any()
        or result.signal_date.dt.normalize().gt(END).any()
    ):
        raise StageBError("candidate identity audit failed")
    result["cap25_rank"] = rank.astype("int64")
    rank_groups = result.groupby(
        ["protocol_arm", result.signal_date.dt.normalize()], sort=False
    ).cap25_rank
    if rank_groups.apply(lambda values: values.duplicated().any()).any() or rank_groups.apply(
        lambda values: sorted(values.tolist()) != list(range(1, len(values) + 1))
    ).any():
        raise StageBError("candidate cap25 ranks are not unique and contiguous per signal day")
    if expected_rows is not None and len(result) != expected_rows:
        raise StageBError("candidate row count differs from preregistration")
    if expected_by_year is not None:
        actual = (
            result.signal_date.dt.year.value_counts().sort_index().astype(int).to_dict()
        )
        if actual != expected_by_year:
            raise StageBError(f"candidate annual identity drift: {actual}")
    return result.sort_values(
        ["signal_date", "cap25_rank", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)


def administrative_censor(
    candidates: pd.DataFrame, calendar: pd.DataFrame
) -> pd.DataFrame:
    """Apply the 2021 tail rule before any price path is joined."""
    calendar = normalize_calendar(calendar)
    by_date = calendar.set_index("trade_date")
    by_idx = calendar.set_index("cal_idx")
    rows: list[dict[str, Any]] = []
    for candidate in candidates.itertuples(index=False):
        signal_date = pd.Timestamp(candidate.signal_date).normalize()
        base = candidate._asdict()
        if signal_date not in by_date.index:
            rows.append(
                {
                    **base,
                    "admin_status": "UNRESOLVED_SIGNAL_CALENDAR",
                    "administratively_censored": False,
                }
            )
            continue
        signal_idx = int(by_date.loc[signal_date, "cal_idx"])
        required = [signal_idx + offset for offset in (1, HORIZON + 1, max(TIME_EXIT_OFFSETS) + 1)]
        # Offsets are relative to the signal: entry is +1, last exit is entry+23 = signal+24.
        required[-1] = signal_idx + 1 + max(TIME_EXIT_OFFSETS)
        if any(index not in by_idx.index for index in required):
            rows.append(
                {
                    **base,
                    "signal_cal_idx": signal_idx,
                    "admin_status": "RIGHT_CENSORED_2021_ADMINISTRATIVE",
                    "administratively_censored": True,
                }
            )
            continue
        entry_idx = signal_idx + 1
        h20_idx = entry_idx + HORIZON
        last_idx = entry_idx + max(TIME_EXIT_OFFSETS)
        if h20_idx not in by_idx.index or last_idx not in by_idx.index:
            rows.append(
                {
                    **base,
                    "signal_cal_idx": signal_idx,
                    "admin_status": "RIGHT_CENSORED_2021_ADMINISTRATIVE",
                    "administratively_censored": True,
                }
            )
            continue
        entry_row = by_idx.loc[entry_idx]
        rows.append(
            {
                **base,
                "signal_cal_idx": signal_idx,
                "entry_cal_idx": entry_idx,
                "entry_date": pd.Timestamp(entry_row.trade_date).normalize(),
                "h20_cal_idx": h20_idx,
                "h20_date": pd.Timestamp(by_idx.loc[h20_idx, "trade_date"]).normalize(),
                "last_exit_cal_idx": last_idx,
                "last_exit_date": pd.Timestamp(by_idx.loc[last_idx, "trade_date"]).normalize(),
                "admin_status": "ADMINISTRATIVE_WINDOW_COMPLETE",
                "administratively_censored": False,
            }
        )
    return pd.DataFrame.from_records(rows)


def verify_admin_bounds(
    candidates: pd.DataFrame,
    materialized: pd.DataFrame,
    calendar: pd.DataFrame,
    protocol_arm: str,
) -> None:
    """Recompute every bound without price rows and compare the CY046 copy exactly."""
    _require_columns(materialized, ADMIN_BOUND_COLUMNS, "candidate admin bounds")
    calendar_by_idx = normalize_calendar(calendar).set_index("cal_idx")
    actual = materialized.loc[:, ADMIN_BOUND_COLUMNS].copy()
    for column in ("signal_date", "entry_date", "h20_date", "h21_date", "h22_date", "h23_date"):
        actual[column] = pd.to_datetime(actual[column]).dt.normalize()
    if actual.protocol_arm.ne(protocol_arm).any() or actual.gap_id.duplicated().any():
        raise StageBError("candidate admin bounds arm or identity drift")
    expected_rows: list[dict[str, Any]] = []
    for row in candidates.itertuples(index=False):
        signal_idx = int(row.signal_cal_idx)
        eligible = not bool(row.administratively_censored)

        def date_or_nat(index: int) -> pd.Timestamp:
            if index not in calendar_by_idx.index:
                return pd.NaT
            return pd.Timestamp(calendar_by_idx.loc[index, "trade_date"]).normalize()

        expected_rows.append(
            {
                "protocol_arm": protocol_arm,
                "gap_id": str(row.gap_id),
                "symbol": str(row.symbol),
                "signal_date": pd.Timestamp(row.signal_date).normalize(),
                "entry_date": date_or_nat(signal_idx + 1),
                "signal_calendar_index": signal_idx,
                "h20_date": date_or_nat(signal_idx + 21),
                "h21_date": date_or_nat(signal_idx + 22),
                "h22_date": date_or_nat(signal_idx + 23),
                "h23_date": date_or_nat(signal_idx + 24),
                "admin_eligible": eligible,
            }
        )
    expected = pd.DataFrame(expected_rows, columns=ADMIN_BOUND_COLUMNS)
    key = ["protocol_arm", "gap_id", "symbol", "signal_date"]
    expected = expected.sort_values(key, kind="mergesort").reset_index(drop=True)
    actual = actual.sort_values(key, kind="mergesort").reset_index(drop=True)
    if len(expected) != len(actual):
        raise StageBError("candidate admin bounds row-count drift")
    for column in ADMIN_BOUND_COLUMNS:
        left, right = expected[column], actual[column]
        equal = left.eq(right) | (left.isna() & right.isna())
        if not bool(equal.all()):
            raise StageBError(f"candidate admin bounds drift in {column}")


def normalize_actions(actions: pd.DataFrame) -> pd.DataFrame:
    _require_columns(actions, ACTION_COLUMNS, "action events")
    result = actions.loc[:, ACTION_COLUMNS].copy()
    for column in ("known_at", "available_at", "effective_date"):
        result[column] = pd.to_datetime(result[column])
    supported = result.action_kind.isin(["CASH_ONLY", "RISK_SHARE", "RISK_RIGHTS"])
    common_valid = (
        result.protocol_arm.map(_nonempty)
        & result.gap_id.map(_nonempty)
        & result.symbol.map(_nonempty)
        & result.event_id.map(_nonempty)
        & result.snapshot_id.map(_nonempty)
        & result.known_at.notna()
        & result.available_at.notna()
        & result.effective_date.notna()
        & result.known_at.lt(result.effective_date)
        & result.available_at.eq(result.known_at)
        & result.available_at.lt(result.effective_date)
        & result.effective_date.eq(result.effective_date.dt.normalize())
        & result.source_terms_complete.eq(True)
        & supported
        & result.effective_date.dt.normalize().le(END)
    )
    if (~common_valid).any() or result.duplicated(
        ["protocol_arm", "gap_id", "symbol", "event_id"]
    ).any():
        raise StageBError("unknown, unsupported, incomplete, or noncausal action event")
    for row in result.itertuples(index=False):
        if pd.notna(row.cash_per_share) and nonnegative_decimal(
            row.cash_per_share, "cash_per_share"
        ) < 0:
            raise StageBError("negative action cash")
        if row.action_kind == "CASH_ONLY":
            cash = nonnegative_decimal(row.cash_per_share, "cash_per_share")
            multiplier = positive_decimal(row.share_multiplier, "cash share_multiplier")
            rights = nonnegative_decimal(row.rights_ratio, "cash rights_ratio")
            if cash < 0 or multiplier != ONE or rights != 0:
                raise StageBError("cash-only event changes share count")
        elif row.action_kind == "RISK_SHARE":
            rights = nonnegative_decimal(row.rights_ratio, "share rights_ratio")
            if (
                positive_decimal(row.share_multiplier, "share_multiplier") == ONE
                or rights != 0
            ):
                raise StageBError("incomplete share action")
        elif (
            positive_decimal(row.rights_ratio, "rights_ratio") <= 0
            or nonnegative_decimal(row.rights_price, "rights_price") < 0
        ):
            raise StageBError("incomplete rights action")
    return result.sort_values(
        ["protocol_arm", "gap_id", "symbol", "known_at", "effective_date", "event_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def partition_actions_for_causal_replay(
    actions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Keep invalid rows visible until an exit proves they are strictly later."""
    _require_columns(actions, ACTION_COLUMNS, "action events")
    raw = actions.loc[:, ACTION_COLUMNS].copy()
    for column in ("known_at", "available_at", "effective_date"):
        raw[column] = pd.to_datetime(raw[column], errors="coerce")
    duplicate = raw.duplicated(
        ["protocol_arm", "gap_id", "symbol", "event_id"], keep=False
    )
    valid_parts: list[pd.DataFrame] = []
    invalid_indices: list[Any] = []
    for index, row in raw.iterrows():
        if duplicate.loc[index] or row[["known_at", "available_at", "effective_date"]].isna().any():
            invalid_indices.append(index)
            continue
        try:
            valid_parts.append(normalize_actions(pd.DataFrame([row], columns=ACTION_COLUMNS)))
        except StageBError:
            invalid_indices.append(index)
    valid = (
        normalize_actions(pd.concat(valid_parts, ignore_index=True))
        if valid_parts
        else normalize_actions(pd.DataFrame(columns=ACTION_COLUMNS))
    )
    invalid = raw.loc[invalid_indices].copy()
    return valid, invalid


def assert_invalid_actions_strictly_after_exit(
    invalid: pd.DataFrame, *, exit_date: pd.Timestamp, exit_causal_at: pd.Timestamp
) -> None:
    if invalid.empty:
        return
    timing_complete = invalid[["known_at", "available_at", "effective_date"]].notna().all(axis=1)
    provably_later = (
        timing_complete
        & invalid.known_at.gt(exit_causal_at)
        & invalid.available_at.gt(exit_causal_at)
        & invalid.effective_date.dt.normalize().gt(exit_date)
    )
    if not bool(provably_later.all()):
        raise StageBError("invalid action is not provably strictly later than completed exit")


def _execution_evidence_status(row: pd.Series, expected_snapshot: str) -> str:
    trade_date = pd.Timestamp(row.get("trade_date")).normalize()
    expected_available = trade_date + pd.Timedelta(hours=9, minutes=35)
    observed_available = pd.Timestamp(row.get("available_at"))
    if observed_available.tzinfo is not None:
        observed_available = observed_available.tz_convert("Asia/Shanghai").tz_localize(None)
    required_true = (
        "ohlc_valid",
        "unit_valid",
        "causal_inputs_valid",
        "market_rule_valid",
        "hard_valid",
    )
    complete = bool(
        row.get("window_index") == 0
        and pd.notna(row.get("available_at"))
        and observed_available == expected_available
        and pd.notna(row.get("trade_status"))
        and int(row.get("trade_status")) == 1
        and row.get("source_resolution_minutes") == 1
        and row.get("minute_count") == 5
        and row.get("distinct_minute_count") == 5
        and all(pd.notna(row.get(column)) and bool(row.get(column)) for column in required_true)
        and _nonempty(row.get("snapshot_id"))
        and _nonempty(row.get("daily_snapshot_id"))
        and str(row.get("daily_snapshot_id")) == str(expected_snapshot)
    )
    return "VALID" if complete else "UNRESOLVED_DATA_QUALITY"


def build_entries(
    candidates: pd.DataFrame,
    daily_entry: pd.DataFrame,
    execution: pd.DataFrame,
    actions: pd.DataFrame,
    protocol_arm: str,
) -> pd.DataFrame:
    """Evaluate the already-fixed next-session order; never search a later row."""
    _require_columns(execution, EXECUTION_COLUMNS, "execution window0")
    _require_columns(daily_entry, DAILY_COLUMNS, "entry daily lineage")
    actions = normalize_actions(actions)
    execution = execution.copy()
    execution["trade_date"] = pd.to_datetime(execution.trade_date).dt.normalize()
    execution["available_at"] = pd.to_datetime(execution.available_at)
    grouped = {
        (str(arm), str(gap_id), str(symbol)): part
        for (arm, gap_id, symbol), part in execution.groupby(
            ["protocol_arm", "gap_id", "symbol"], sort=False
        )
    }
    daily_grouped = {
        (str(arm), str(gap_id), str(symbol)): part
        for (arm, gap_id, symbol), part in daily_entry.groupby(
            ["protocol_arm", "gap_id", "symbol"], sort=False
        )
    }
    action_groups = {
        (str(arm), str(gap_id), str(symbol)): part
        for (arm, gap_id, symbol), part in actions.groupby(
            ["protocol_arm", "gap_id", "symbol"], sort=False
        )
    }
    rows: list[dict[str, Any]] = []
    for candidate in candidates.itertuples(index=False):
        base = candidate._asdict()
        if bool(candidate.administratively_censored) or candidate.admin_status != "ADMINISTRATIVE_WINDOW_COMPLETE":
            rows.append({**base, "entry_status": candidate.admin_status})
            continue
        key = (protocol_arm, str(candidate.gap_id), str(candidate.symbol))
        daily_evidence = daily_grouped.get(key, pd.DataFrame())
        daily_offsets = set(
            pd.to_numeric(daily_evidence.get("entry_session_offset"), errors="coerce")
            .dropna()
            .astype(int)
            .tolist()
        )
        if (
            len(daily_evidence) != 2
            or daily_offsets != {-1, 0}
        ):
            rows.append({**base, "entry_status": "UNRESOLVED_DATA_QUALITY"})
            continue
        signal_daily = daily_evidence.loc[
            pd.to_numeric(daily_evidence.entry_session_offset).eq(-1)
        ].iloc[0]
        entry_daily = daily_evidence.loc[
            pd.to_numeric(daily_evidence.entry_session_offset).eq(0)
        ].iloc[0]
        events = action_groups.get(key, actions.iloc[0:0])
        entry_date = pd.Timestamp(candidate.entry_date).normalize()
        effective_between = events.loc[
            events.effective_date.dt.normalize().gt(
                pd.Timestamp(candidate.signal_date).normalize()
            )
            & events.effective_date.dt.normalize().le(entry_date)
        ]
        try:
            _reconcile_action_day(entry_daily, events)
            entry_lineage_complete = bool(
                pd.notna(entry_daily.get("corporate_action_count"))
                and pd.notna(entry_daily.get("decision_at"))
                and pd.notna(entry_daily.get("available_at"))
                and pd.Timestamp(entry_daily.get("available_at"))
                <= pd.Timestamp(entry_daily.get("decision_at"))
                and _nonempty(entry_daily.get("snapshot_id"))
                and _nonempty(entry_daily.get("corporate_action_snapshot_id"))
            )
        except StageBError:
            entry_lineage_complete = False
        entry_daily_state = (
            _daily_state(entry_daily, events)
            if effective_between.empty and entry_lineage_complete
            else "UNRESOLVED_DATA_QUALITY"
        )
        signal_required_true = (
            signal_daily.get("hard_valid"),
            signal_daily.get("market_rule_valid"),
            signal_daily.get("corporate_action_valid"),
            signal_daily.get("current_day_data_tradable"),
        )
        signal_lineage_valid = bool(
            pd.notna(signal_daily.get("available_at"))
            and pd.notna(signal_daily.get("decision_at"))
            and pd.Timestamp(signal_daily.available_at)
            <= pd.Timestamp(signal_daily.decision_at)
            and all(pd.notna(value) and bool(value) for value in signal_required_true)
            and pd.notna(signal_daily.get("corporate_action_blocking"))
            and not bool(signal_daily.get("corporate_action_blocking"))
            and pd.notna(signal_daily.get("trade_status"))
            and int(signal_daily.get("trade_status")) == 1
        )
        if (
            str(signal_daily.snapshot_id) != str(candidate.signal_snapshot_id)
            or str(signal_daily.daily_snapshot_id)
            != str(candidate.signal_daily_snapshot_id)
            or str(signal_daily.corporate_action_snapshot_id)
            != str(candidate.signal_corporate_action_snapshot_id)
            or pd.Timestamp(signal_daily.trade_date).normalize()
            != pd.Timestamp(candidate.signal_date).normalize()
            or pd.Timestamp(entry_daily.trade_date).normalize()
            != entry_date
            or not signal_lineage_valid
            or not entry_lineage_complete
        ):
            rows.append({**base, "entry_status": "UNRESOLVED_DATA_QUALITY"})
            continue
        # A fully reconciled action effective between signal and entry makes the
        # signal coordinate obsolete.  It is a deterministic no-entry, even
        # when CY006 deliberately marks that ex-date row hard-invalid/blocking.
        if not effective_between.empty:
            rows.append({**base, "entry_status": "NO_ENTRY_ACTION_COORDINATE"})
            continue
        if entry_daily_state == "UNRESOLVED_DATA_QUALITY":
            rows.append({**base, "entry_status": "UNRESOLVED_DATA_QUALITY"})
            continue
        if entry_daily_state == "KNOWN_NOT_TRADED":
            rows.append({**base, "entry_status": "NO_ENTRY_MECHANICAL_NOT_TRADED"})
            continue
        evidence = grouped.get(key, pd.DataFrame())
        if (
            len(evidence) != 1
            or int(evidence.iloc[0].get("entry_session_offset", -999)) != 0
            or pd.Timestamp(evidence.iloc[0].trade_date).normalize()
            != pd.Timestamp(candidate.entry_date).normalize()
        ):
            rows.append({**base, "entry_status": "UNRESOLVED_DATA_QUALITY"})
            continue
        row = evidence.iloc[0]
        evidence_status = _execution_evidence_status(
            row, str(entry_daily.snapshot_id)
        )
        if evidence_status != "VALID":
            rows.append({**base, "entry_status": evidence_status})
            continue
        observed_at = pd.Timestamp(row.available_at)
        pending_risk = events.loc[
            events.action_kind.isin(["RISK_SHARE", "RISK_RIGHTS"])
            & events.known_at.le(observed_at)
            & events.available_at.le(observed_at)
            & events.effective_date.dt.normalize().le(pd.Timestamp(candidate.last_exit_date))
        ]
        if not pending_risk.empty:
            rows.append({**base, "entry_status": "NO_ENTRY_PENDING_RISK_ACTION"})
            continue
        if pd.isna(row.trade_status) or int(row.trade_status) != 1:
            rows.append({**base, "entry_status": "NO_ENTRY_MECHANICAL_NOT_TRADED"})
            continue
        try:
            open_tick = observed_price_tick(row.open, "entry open")
            up_limit_tick = observed_price_tick(row.up_limit_price, "entry up limit")
            down_limit_tick = observed_price_tick(
                row.down_limit_price, "entry down limit"
            )
            entry_raw = tick_price(open_tick)
            factor = positive_decimal(candidate.coordinate_factor, "coordinate_factor")
            boundary = positive_decimal(candidate.L, "L")
            raw_l = boundary / factor
            raw_l_tick = observed_price_tick(raw_l, "raw L")
        except StageBError:
            rows.append({**base, "entry_status": "UNRESOLVED_DATA_QUALITY"})
            continue
        if down_limit_tick >= up_limit_tick or not (
            down_limit_tick <= open_tick <= up_limit_tick
        ):
            rows.append({**base, "entry_status": "UNRESOLVED_DATA_QUALITY"})
            continue
        if open_tick == up_limit_tick:
            rows.append({**base, "entry_status": "NO_ENTRY_MECHANICAL_UP_LIMIT"})
            continue
        entry_coordinate = entry_raw * factor
        if entry_coordinate >= boundary:
            rows.append({**base, "entry_status": "NO_ENTRY_INSUFFICIENT_A67_HEADROOM"})
            continue
        target_coordinate = entry_coordinate + TARGET_FRACTION * (
            boundary - entry_coordinate
        )
        target_raw_without_cash = target_coordinate / factor
        target_tick = theoretical_sell_tick(target_raw_without_cash, "entry target")
        target_price = tick_price(target_tick)
        exact_net = (
            target_price * (ONE - PER_SIDE_COST)
            / (entry_raw * (ONE + PER_SIDE_COST))
            - ONE
        )
        if (
            target_tick >= raw_l_tick
            or exact_net < MIN_EXACT_TARGET_NET
        ):
            rows.append(
                {
                    **base,
                    "entry_status": "NO_ENTRY_INSUFFICIENT_A67_HEADROOM",
                    "entry_raw_price": str(entry_raw),
                    "entry_coordinate_price": str(entry_coordinate),
                    "target_coordinate": str(target_coordinate),
                    "target_tick": target_tick,
                    "raw_l_tick": raw_l_tick,
                    "exact_target_net_headroom": str(exact_net),
                }
            )
            continue
        rows.append(
            {
                **base,
                "entry_status": "EXECUTABLE_ENTRY",
                "entry_raw_price": str(entry_raw),
                "entry_coordinate_price": str(entry_coordinate),
                "entry_observed_at": observed_at,
                "entry_snapshot_id": row.snapshot_id,
                "entry_daily_snapshot_id": row.daily_snapshot_id,
                "target_coordinate": str(target_coordinate),
                "target_tick": target_tick,
                "raw_l_tick": raw_l_tick,
                "exact_target_net_headroom": str(exact_net),
                "entry_label": "CY008_WINDOW0_OPEN_0931_0935_OBSERVED_0935",
            }
        )
    result = pd.DataFrame.from_records(rows)
    if len(result) != len(candidates) or result.gap_id.duplicated().any():
        raise StageBError("entry identity conservation failure")
    return result


def _candidate_path_key(row: Any) -> tuple[str, str, str]:
    return (str(row.protocol_arm), str(row.gap_id), str(row.symbol))


def _action_ids(value: Any) -> tuple[str, ...]:
    if value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == "":
        return ()
    if isinstance(value, (list, tuple)):
        values = [str(item).strip() for item in value]
    else:
        text = str(value).strip()
        if text.startswith("["):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError as exc:
                raise StageBError("invalid corporate_action_ids JSON") from exc
            if not isinstance(decoded, list):
                raise StageBError("corporate_action_ids is not a list")
            values = [str(item).strip() for item in decoded]
        else:
            values = [item.strip() for item in text.replace(",", "|").split("|")]
    if any(not item for item in values) or len(values) != len(set(values)):
        raise StageBError("empty or duplicate corporate action id")
    return tuple(sorted(values))


def _reconcile_action_day(row: pd.Series, events: pd.DataFrame) -> None:
    date = pd.Timestamp(row.trade_date).normalize()
    effective = events.loc[events.effective_date.dt.normalize().eq(date)] if not events.empty else events
    expected_ids = tuple(sorted(effective.event_id.astype(str).tolist())) if not effective.empty else ()
    try:
        observed_count = int(row.corporate_action_count)
    except (TypeError, ValueError, OverflowError) as exc:
        raise StageBError("CY006 action count is not a finite integer") from exc
    if observed_count < 0 or observed_count != len(expected_ids) or _action_ids(row.corporate_action_ids) != expected_ids:
        raise StageBError("QD010/CY006 action identity mismatch")
    cash = sum(
        (
            decimal_from_source(0 if pd.isna(value) else value, "event cash")
            for value in effective.cash_per_share
        ),
        start=Decimal("0"),
    ) if not effective.empty else Decimal("0")
    multiplier = Decimal("1")
    if not effective.empty:
        for value in effective.share_multiplier:
            multiplier *= decimal_from_source(1 if pd.isna(value) else value, "event multiplier")
    rights = effective.loc[effective.action_kind.eq("RISK_RIGHTS")] if not effective.empty else effective
    expected_rights_ratio = (
        decimal_from_source(rights.iloc[0].rights_ratio, "event rights ratio")
        if len(rights) == 1 else Decimal("0")
    )
    expected_rights_price = (
        decimal_from_source(rights.iloc[0].rights_price, "event rights price")
        if len(rights) == 1 else Decimal("0")
    )
    if len(rights) > 1:
        raise StageBError("multiple rights events cannot reconcile to scalar daily terms")
    observed = (
        decimal_from_source(0 if pd.isna(row.cash_per_share) else row.cash_per_share, "daily cash"),
        decimal_from_source(1 if pd.isna(row.share_multiplier) else row.share_multiplier, "daily multiplier"),
        decimal_from_source(0 if pd.isna(row.rights_ratio) else row.rights_ratio, "daily rights ratio"),
        decimal_from_source(0 if pd.isna(row.rights_price) else row.rights_price, "daily rights price"),
    )
    if observed != (cash, multiplier, expected_rights_ratio, expected_rights_price):
        raise StageBError("QD010/CY006 action terms mismatch")


def _assert_candidate_path(frame: pd.DataFrame, entry: Any, label: str) -> None:
    if frame.empty:
        return
    _require_columns(frame, PATH_KEY_COLUMNS, label)
    expected = _candidate_path_key(entry)
    actual = set(
        zip(
            frame.protocol_arm.astype(str),
            frame.gap_id.astype(str),
            frame.symbol.astype(str),
            strict=True,
        )
    )
    if actual != {expected}:
        raise StageBError(f"{label} crosses a candidate boundary")
    if (
        pd.to_datetime(frame.signal_date).dt.normalize().ne(pd.Timestamp(entry.signal_date).normalize()).any()
        or pd.to_datetime(frame.entry_date).dt.normalize().ne(pd.Timestamp(entry.entry_date).normalize()).any()
    ):
        raise StageBError(f"{label} date identity drift")


def _daily_state(row: pd.Series, events: pd.DataFrame) -> str:
    """Validate lineage/action state before asking CY008 for an executable price."""
    try:
        _reconcile_action_day(row, events)
    except StageBError:
        return "UNRESOLVED_DATA_QUALITY"
    if (
        pd.isna(row.get("trade_status"))
        or pd.isna(row.get("current_day_data_tradable"))
        or pd.isna(row.get("market_rule_valid"))
        or not bool(row.get("market_rule_valid"))
        or pd.isna(row.get("corporate_action_valid"))
        or not bool(row.get("corporate_action_valid"))
        or pd.isna(row.get("corporate_action_blocking"))
        or bool(row.get("corporate_action_blocking"))
        or pd.isna(row.get("hard_valid"))
        or not bool(row.get("hard_valid"))
        or pd.isna(row.get("corporate_action_count"))
        or pd.isna(row.get("decision_at"))
        or pd.isna(row.get("available_at"))
        or pd.Timestamp(row.get("available_at")) > pd.Timestamp(row.get("decision_at"))
        or not _nonempty(row.get("snapshot_id"))
        or not _nonempty(row.get("corporate_action_snapshot_id"))
    ):
        return "UNRESOLVED_DATA_QUALITY"
    if int(row.trade_status) != 1 or not bool(row.current_day_data_tradable):
        return "KNOWN_NOT_TRADED"
    return "TRADED"


def _first_close_index(known_at: pd.Timestamp, calendar: pd.DataFrame) -> int | None:
    for row in calendar.itertuples(index=False):
        close = pd.Timestamp(row.trade_date).normalize() + pd.Timedelta(hours=15)
        if close >= pd.Timestamp(known_at):
            return int(row.cal_idx)
    return None


def _execution_row(
    execution_groups: dict[int, pd.DataFrame],
    cal_idx: int,
    calendar_by_idx: pd.DataFrame,
    daily_by_idx: dict[int, pd.Series],
    events: pd.DataFrame,
) -> tuple[pd.Series | None, str]:
    if cal_idx not in calendar_by_idx.index:
        return None, "UNRESOLVED_DATA_QUALITY"
    date = pd.Timestamp(calendar_by_idx.loc[cal_idx, "trade_date"]).normalize()
    daily = daily_by_idx.get(cal_idx)
    if daily is None or pd.Timestamp(daily.trade_date).normalize() != date:
        return None, "UNRESOLVED_DATA_QUALITY"
    daily_status = _daily_state(daily, events)
    if daily_status == "UNRESOLVED_DATA_QUALITY":
        return None, daily_status
    if daily_status == "KNOWN_NOT_TRADED":
        return None, "MECHANICAL_ROLL"
    rows = execution_groups.get(cal_idx, pd.DataFrame())
    if len(rows) != 1:
        return None, "UNRESOLVED_DATA_QUALITY"
    row = rows.iloc[0]
    if pd.Timestamp(row.trade_date).normalize() != date:
        return None, "UNRESOLVED_DATA_QUALITY"
    status = _execution_evidence_status(row, str(daily.snapshot_id))
    return (row if status == "VALID" else None), status


def evaluate_one_outcome(
    entry: Any,
    daily: pd.DataFrame,
    execution: pd.DataFrame,
    actions: pd.DataFrame,
    calendar: pd.DataFrame,
) -> dict[str, Any]:
    """Resolve one accepted candidate; callers must apply capacity first."""
    _require_columns(daily, DAILY_COLUMNS, "daily target path")
    _require_columns(execution, EXECUTION_COLUMNS, "execution window0")
    _assert_candidate_path(daily, entry, "daily target path")
    _assert_candidate_path(execution, entry, "execution window0")
    _assert_candidate_path(actions, entry, "action events")
    calendar = normalize_calendar(calendar)
    calendar_by_idx = calendar.set_index("cal_idx", drop=False)
    actions, invalid_actions = partition_actions_for_causal_replay(actions)
    frozen_sessions = set(calendar.trade_date.tolist())
    if not actions.empty and not actions.effective_date.dt.normalize().isin(
        frozen_sessions
    ).all():
        raise StageBError("UNRESOLVED_ACTION_BLOCK: action effective date is not a market session")
    daily = daily.copy()
    execution = execution.copy()
    for frame, columns in (
        (daily, ("trade_date", "decision_at", "available_at")),
        (execution, ("trade_date", "available_at")),
    ):
        for column in columns:
            frame[column] = pd.to_datetime(frame[column])
    if daily.trade_date.dt.normalize().gt(END).any() or execution.trade_date.dt.normalize().gt(END).any():
        raise StageBError("post-2021 row reached outcome engine")
    calendar_dates = calendar.set_index("trade_date")["cal_idx"]
    if daily.trade_date.duplicated().any() or execution.trade_date.duplicated().any():
        raise StageBError("duplicate candidate path date")
    daily["cal_idx"] = daily.trade_date.dt.normalize().map(calendar_dates)
    execution["cal_idx"] = execution.trade_date.dt.normalize().map(calendar_dates)
    if daily.cal_idx.isna().any() or execution.cal_idx.isna().any():
        raise StageBError("candidate path date is outside frozen calendar")
    daily["cal_idx"] = daily.cal_idx.astype(int)
    execution["cal_idx"] = execution.cal_idx.astype(int)
    if set(daily.entry_session_offset.astype(int)) != set(range(-1, 24)):
        raise StageBError("daily candidate path is not signal through entry+23")
    if set(execution.entry_session_offset.astype(int)) != set(range(0, 24)):
        raise StageBError("execution candidate path is not entry through entry+23")
    if not (
        daily.cal_idx.eq(int(entry.entry_cal_idx) + daily.entry_session_offset.astype(int)).all()
        and execution.cal_idx.eq(
            int(entry.entry_cal_idx) + execution.entry_session_offset.astype(int)
        ).all()
    ):
        raise StageBError("candidate path offset/calendar mapping drift")
    daily_by_idx = {int(row.cal_idx): row for _, row in daily.iterrows()}
    execution_groups = {
        int(cal_idx): part for cal_idx, part in execution.groupby("cal_idx", sort=False)
    }

    entry_observed = pd.Timestamp(entry.entry_observed_at)
    action_observed = actions[["known_at", "available_at"]].max(axis=1) if not actions.empty else pd.Series(dtype="datetime64[ns]")
    later_risks = actions.loc[
        actions.action_kind.isin(["RISK_SHARE", "RISK_RIGHTS"])
        & action_observed.gt(entry_observed)
        & actions.effective_date.dt.normalize().le(pd.Timestamp(entry.last_exit_date))
    ].copy()
    risk_specs: list[dict[str, Any]] = []
    for risk in later_risks.itertuples(index=False):
        decision_at = max(pd.Timestamp(risk.known_at), pd.Timestamp(risk.available_at))
        decision_idx = _first_close_index(decision_at, calendar)
        if decision_idx is None:
            raise StageBError("UNRESOLVED_ACTION_BLOCK: risk decision outside calendar")
        risk_specs.append(
            {
                "first_attempt": decision_idx + 1,
                "effective_date": pd.Timestamp(risk.effective_date).normalize(),
                "event_id": str(risk.event_id),
            }
        )
    risk_specs.sort(key=lambda item: (item["first_attempt"], item["effective_date"], item["event_id"]))
    risk_barrier_idx = risk_specs[0]["first_attempt"] if risk_specs else None

    target_exit: dict[str, Any] | None = None
    factor = positive_decimal(entry.coordinate_factor, "coordinate_factor")
    target_coordinate = positive_decimal(entry.target_coordinate, "target_coordinate")
    for offset in range(1, HORIZON + 1):
        cal_idx = int(entry.entry_cal_idx) + offset
        if risk_barrier_idx is not None and cal_idx >= risk_barrier_idx:
            break  # opening risk order has priority over this session's later high
        row = daily_by_idx.get(cal_idx)
        if row is None or int(row.entry_session_offset) != offset:
            raise StageBError("UNRESOLVED_DATA_QUALITY: missing target daily row")
        date = pd.Timestamp(row.trade_date).normalize()
        effective_risk = actions.loc[
            actions.action_kind.isin(["RISK_SHARE", "RISK_RIGHTS"])
            & actions.effective_date.dt.normalize().gt(pd.Timestamp(entry.entry_date))
            & actions.effective_date.dt.normalize().le(date)
        ]
        effective_invalid = invalid_actions.loc[
            invalid_actions.effective_date.notna()
            & invalid_actions.effective_date.dt.normalize().le(date)
        ]
        if not effective_risk.empty or not effective_invalid.empty:
            raise StageBError("UNRESOLVED_ACTION_BLOCK: risk action became effective")
        state = _daily_state(row, actions)
        if state == "UNRESOLVED_DATA_QUALITY":
            raise StageBError(state)
        if state == "KNOWN_NOT_TRADED":
            continue
        cash_rows = actions.loc[
            actions.action_kind.eq("CASH_ONLY")
            & actions.effective_date.dt.normalize().gt(pd.Timestamp(entry.entry_date))
            & actions.effective_date.dt.normalize().le(date)
        ]
        for cash_row in cash_rows.itertuples(index=False):
            if max(pd.Timestamp(cash_row.known_at), pd.Timestamp(cash_row.available_at)) > pd.Timestamp(row.decision_at):
                raise StageBError("UNRESOLVED_ACTION_BLOCK: cash was not causally available")
        cash = sum(
            (nonnegative_decimal(value, "cash_per_share") for value in cash_rows.cash_per_share),
            start=Decimal("0"),
        )
        open_tick = observed_price_tick(row.open, "daily open")
        high_tick = observed_price_tick(row.high, "daily high")
        if high_tick < open_tick:
            raise StageBError("UNRESOLVED_DATA_QUALITY: daily high below open")
        target_tick = theoretical_sell_tick(
            target_coordinate / factor - cash, "cash-adjusted target"
        )
        if max(open_tick, high_tick) >= target_tick:
            target_exit = {
                "exit_cal_idx": cal_idx,
                "exit_date": date,
                "exit_raw_tick": target_tick,
                "exit_reason": "A67_TARGET",
                "exit_causal_at": pd.Timestamp(row.decision_at),
            }
            break

    chosen = target_exit
    if chosen is None:
        time_start = int(entry.entry_cal_idx) + TIME_EXIT_OFFSETS[0]
        open_start = min(risk_barrier_idx or time_start, time_start)
        for cal_idx in range(open_start, int(entry.last_exit_cal_idx) + 1):
            active_risks = [spec for spec in risk_specs if spec["first_attempt"] <= cal_idx]
            date = pd.Timestamp(calendar_by_idx.loc[cal_idx, "trade_date"]).normalize()
            effective_valid_risk = actions.loc[
                actions.action_kind.isin(["RISK_SHARE", "RISK_RIGHTS"])
                & actions.effective_date.dt.normalize().gt(pd.Timestamp(entry.entry_date))
                & actions.effective_date.dt.normalize().le(date)
            ]
            effective_invalid = invalid_actions.loc[
                invalid_actions.effective_date.notna()
                & invalid_actions.effective_date.dt.normalize().le(date)
            ]
            if not effective_valid_risk.empty or not effective_invalid.empty:
                raise StageBError("UNRESOLVED_ACTION_BLOCK: action effective before opening exit")
            if active_risks and date >= min(spec["effective_date"] for spec in active_risks):
                raise StageBError("UNRESOLVED_ACTION_BLOCK: no legal pre-effective exit")
            row, status = _execution_row(
                execution_groups, cal_idx, calendar_by_idx, daily_by_idx, actions
            )
            if status == "MECHANICAL_ROLL":
                continue
            if status != "VALID" or row is None:
                kind = "UNRESOLVED_ACTION_BLOCK" if active_risks else "UNRESOLVED_DATA_QUALITY"
                raise StageBError(f"{kind}: invalid opening-exit evidence")
            open_tick = observed_price_tick(row.open, "opening exit open")
            down_tick = observed_price_tick(row.down_limit_price, "opening down limit")
            up_tick = observed_price_tick(row.up_limit_price, "opening up limit")
            if down_tick >= up_tick or not (down_tick <= open_tick <= up_tick):
                kind = "UNRESOLVED_ACTION_BLOCK" if active_risks else "UNRESOLVED_DATA_QUALITY"
                raise StageBError(f"{kind}: opening price is outside legal price limits")
            if open_tick == down_tick:
                continue
            chosen = {
                "exit_cal_idx": cal_idx,
                "exit_date": date,
                "exit_raw_tick": open_tick,
                "exit_reason": "CORPORATE_ACTION_RISK" if active_risks else "H20_TIME_STOP",
                "exit_causal_at": pd.Timestamp(row.available_at),
            }
            break
    if chosen is None:
        if risk_specs:
            raise StageBError("UNRESOLVED_ACTION_BLOCK: no opening exit")
        raise StageBError("UNEXPECTED_UNRESOLVED_TIME_EXIT")
    if int(chosen["exit_cal_idx"]) <= int(entry.entry_cal_idx):
        raise StageBError("T+1 violation")
    exit_date = pd.Timestamp(chosen["exit_date"]).normalize()
    assert_invalid_actions_strictly_after_exit(
        invalid_actions,
        exit_date=exit_date,
        exit_causal_at=pd.Timestamp(chosen["exit_causal_at"]),
    )
    cash_rows = actions.loc[
        actions.action_kind.eq("CASH_ONLY")
        & actions.effective_date.dt.normalize().gt(pd.Timestamp(entry.entry_date))
        & actions.effective_date.dt.normalize().le(exit_date)
    ]
    cash = sum(
        (nonnegative_decimal(value, "cash_per_share") for value in cash_rows.cash_per_share),
        start=Decimal("0"),
    )
    entry_raw = positive_decimal(entry.entry_raw_price, "entry raw")
    exit_raw = tick_price(int(chosen["exit_raw_tick"]))
    net = (exit_raw * (ONE - PER_SIDE_COST) + cash) / (
        entry_raw * (ONE + PER_SIDE_COST)
    ) - ONE
    if not net.is_finite():
        raise StageBError("nonfinite net return")
    return {
        "protocol_arm": entry.protocol_arm,
        "gap_id": entry.gap_id,
        "symbol": entry.symbol,
        "signal_date": pd.Timestamp(entry.signal_date).normalize(),
        "board": entry.board,
        "entry_date": pd.Timestamp(entry.entry_date).normalize(),
        "entry_cal_idx": int(entry.entry_cal_idx),
        "entry_raw_price": str(entry_raw),
        "target_coordinate": str(target_coordinate),
        "exit_date": exit_date,
        "exit_cal_idx": int(chosen["exit_cal_idx"]),
        "exit_raw_price": str(exit_raw),
        "exit_reason": chosen["exit_reason"],
        "cash_per_entry_share": str(cash),
        "net_return": str(net),
        "holding_sessions": int(chosen["exit_cal_idx"]) - int(entry.entry_cal_idx),
        "outcome_status": "COMPLETED",
    }


def replay_online_portfolio(
    entries: pd.DataFrame,
    outcome_loader: Callable[[Any], dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Admit chronologically; rejected candidates never call outcome_loader."""
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    executable["entry_date"] = pd.to_datetime(executable.entry_date).dt.normalize()
    executable = executable.sort_values(
        ["entry_date", "signal_date", "cap25_rank", "symbol", "gap_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    active: list[dict[str, Any]] = []
    result_rows: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for row in executable.itertuples(index=False):
        entry_date = pd.Timestamp(row.entry_date).normalize()
        active = [
            item
            for item in active
            if pd.Timestamp(item["exit_date"]).normalize() >= entry_date
        ]
        if any(str(item["symbol"]) == str(row.symbol) for item in active):
            status = "CAPACITY_REJECT_SAME_SYMBOL_OVERLAP"
        elif len(active) >= MAX_POSITIONS:
            status = "CAPACITY_REJECT_K50"
        else:
            status = "CAPACITY_ACCEPTED"
            outcome = outcome_loader(row)
            if outcome.get("outcome_status") != "COMPLETED":
                raise StageBError("unexpected unresolved accepted outcome")
            if str(outcome.get("gap_id")) != str(row.gap_id):
                raise StageBError("outcome loader changed candidate identity")
            exit_date = pd.Timestamp(outcome["exit_date"]).normalize()
            if exit_date < entry_date:
                raise StageBError("outcome exit precedes entry")
            active.append(
                {
                    "symbol": str(row.symbol),
                    "exit_date": exit_date,
                }
            )
            outcomes.append(outcome)
        result_rows.append({
            **row._asdict(),
            "capacity_status": status,
            "terminal_class": status if status != "CAPACITY_ACCEPTED" else "COMPLETED_ACCEPTED_TRADE",
        })
    return pd.DataFrame.from_records(result_rows), pd.DataFrame.from_records(outcomes)


def summarize(
    candidates: pd.DataFrame,
    entries: pd.DataFrame,
    outcomes: pd.DataFrame,
    portfolio: pd.DataFrame,
) -> dict[str, Any]:
    unresolved_entries = entries.loc[
        entries.entry_status.str.startswith("UNRESOLVED", na=False)
    ]
    unresolved_outcomes = outcomes.loc[
        ~outcomes.outcome_status.eq("COMPLETED")
    ] if not outcomes.empty else outcomes
    if len(unresolved_entries) or len(unresolved_outcomes):
        raise StageBError("unexpected unresolved blocks aggregate publication")
    accepted_ids = portfolio.loc[
        portfolio.capacity_status.eq("CAPACITY_ACCEPTED"), "gap_id"
    ].astype(str)
    accepted = outcomes.loc[outcomes.gap_id.astype(str).isin(set(accepted_ids))].copy()
    if accepted.empty:
        raise StageBError("accepted portfolio is empty")
    if len(accepted) != len(accepted_ids) or accepted.gap_id.duplicated().any():
        raise StageBError("accepted outcome identity conservation failure")
    audit = _terminal_audit(entries, portfolio)
    eligible = audit.loc[audit.admin_status.eq("ADMINISTRATIVE_WINDOW_COMPLETE")]
    if len(eligible) != int(audit.terminal_class.notna().sum()):
        raise StageBError("terminal-class conservation failure")

    def median_decimal(values: list[Decimal]) -> Decimal:
        ordered = sorted(values)
        center = len(ordered) // 2
        return ordered[center] if len(ordered) % 2 else (ordered[center - 1] + ordered[center]) / 2

    def group_report(candidate_part: pd.DataFrame) -> dict[str, Any]:
        ids = set(candidate_part.gap_id.astype(str))
        entry_part = entries.loc[entries.gap_id.astype(str).isin(ids)]
        portfolio_part = portfolio.loc[portfolio.gap_id.astype(str).isin(ids)]
        accepted_part = accepted.loc[accepted.gap_id.astype(str).isin(ids)]
        report: dict[str, Any] = {
            "candidate_signals": len(candidate_part),
            "administratively_censored": int(candidate_part.administratively_censored.fillna(False).sum()),
            "eligible_no_entry_by_reason": entry_part.loc[
                entry_part.entry_status.isin(MECHANICAL_NO_ENTRY), "entry_status"
            ].value_counts().astype(int).to_dict(),
            "entry_status_counts": entry_part.entry_status.value_counts().astype(int).to_dict(),
            "executable_entries": int(entry_part.entry_status.eq("EXECUTABLE_ENTRY").sum()),
            "capacity_accepted": int(portfolio_part.capacity_status.eq("CAPACITY_ACCEPTED").sum()) if not portfolio_part.empty else 0,
            "capacity_rejected": int(portfolio_part.capacity_status.ne("CAPACITY_ACCEPTED").sum()) if not portfolio_part.empty else 0,
        }
        if not accepted_part.empty:
            nets = [decimal_from_source(value, "group net") for value in accepted_part.net_return]
            holds = [Decimal(int(value)) for value in accepted_part.holding_sessions]
            report.update(
                {
                    "mean_net_return": str(sum(nets, start=Decimal("0")) / Decimal(len(nets))),
                    "median_net_return": str(median_decimal(nets)),
                    "win_rate": str(Decimal(sum(value > 0 for value in nets)) / Decimal(len(nets))),
                    "mean_holding_sessions": str(sum(holds, start=Decimal("0")) / Decimal(len(holds))),
                    "median_holding_sessions": str(median_decimal(holds)),
                    "severe_loss_le_minus_10pct": sum(value <= Decimal("-0.10") for value in nets),
                    "exit_reasons": accepted_part.exit_reason.value_counts().astype(int).to_dict(),
                }
            )
        return report

    net_values = [decimal_from_source(value, "net_return") for value in accepted.net_return]
    hold_values = [int(value) for value in accepted.holding_sessions]
    mean_net = sum(net_values, start=Decimal("0")) / Decimal(len(net_values))
    mean_holding = Decimal(sum(hold_values)) / Decimal(len(hold_values))
    annualized = Decimal(len(accepted)) / Decimal(4)
    gates = {
        "accepted_trades_per_development_year_gt_50": annualized > Decimal("50"),
        "mean_net_return_ge_0_04": mean_net >= Decimal("0.04"),
        "mean_holding_sessions_lt_15": mean_holding < Decimal("15"),
    }
    signal_year = pd.to_datetime(candidates.signal_date).dt.year
    by_year = {
        str(year): group_report(candidates.loc[signal_year.eq(year)])
        for year in (2018, 2019, 2020, 2021)
    }
    by_board = {
        str(board): group_report(part)
        for board, part in candidates.groupby("board", sort=True)
    }
    max_same_date = int(pd.to_datetime(accepted.entry_date).dt.normalize().value_counts().max())
    return {
        "candidate_signals": len(candidates),
        "administratively_censored": int(
            candidates.administratively_censored.fillna(False).sum()
        ),
        "eligible_no_entry_by_reason": entries.loc[
            entries.entry_status.isin(MECHANICAL_NO_ENTRY), "entry_status"
        ].value_counts().astype(int).to_dict(),
        "entry_status_counts": entries.entry_status.value_counts().astype(int).to_dict(),
        "executable_entries": int(entries.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "capacity_accepted": len(accepted),
        "capacity_rejected": int(
            portfolio.capacity_status.ne("CAPACITY_ACCEPTED").sum()
        ),
        "accepted_trades_per_development_year": str(annualized),
        "mean_net_return": str(mean_net),
        "median_net_return": str(median_decimal(net_values)),
        "win_rate": str(
            Decimal(sum(value > 0 for value in net_values)) / Decimal(len(net_values))
        ),
        "mean_holding_sessions": str(mean_holding),
        "median_holding_sessions": float(pd.Series(hold_values).median()),
        "severe_loss_le_minus_10pct": int(
            sum(value <= Decimal("-0.10") for value in net_values)
        ),
        "exit_reasons": accepted.exit_reason.value_counts().astype(int).to_dict(),
        "by_signal_year": by_year,
        "by_board": by_board,
        "largest_entry_date_share": str(Decimal(max_same_date) / Decimal(len(accepted))),
        "weighting": "EVENT_EQUAL",
        "terminal_class_counts": eligible.terminal_class.value_counts().astype(int).to_dict(),
        "success_gates": gates,
        "passed_all_success_gates": all(gates.values()),
    }


def _projected_read(path: Path, columns: Iterable[str]) -> pd.DataFrame:
    projected = ",".join(f'"{column}"' for column in columns)
    with duckdb.connect() as con:
        return con.execute(
            f"SELECT {projected} FROM read_parquet(?)", [str(path)]
        ).fetchdf()


def _candidate_join(alias: str, bound: str = "b") -> str:
    return " AND ".join(
        [
            f'{alias}.protocol_arm={bound}.protocol_arm',
            f'{alias}.gap_id={bound}.gap_id',
            f'{alias}.symbol={bound}.symbol',
            f'{alias}.signal_date={bound}.signal_date',
            f'{alias}.entry_date={bound}.entry_date',
        ]
    )


def _read_arm_rows(path: Path, columns: Iterable[str], protocol_arm: str) -> pd.DataFrame:
    projected = ",".join(f'"{column}"' for column in columns)
    with duckdb.connect() as con:
        return con.execute(
            f"SELECT {projected} FROM read_parquet(?) WHERE protocol_arm=?",
            [str(path), protocol_arm],
        ).fetchdf()


def _load_entry_inputs(
    eligible: pd.DataFrame, protocol_arm: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Decode only signal/entry state and actions already known by entry 09:35."""
    bounds = eligible[["gap_id", "symbol", "signal_date", "entry_date"]].copy()
    bounds.insert(0, "protocol_arm", protocol_arm)
    with duckdb.connect() as con:
        con.register("candidate_bounds", bounds)
        daily_projection = ",".join(f'd."{column}"' for column in DAILY_COLUMNS)
        execution_projection = ",".join(f'e."{column}"' for column in EXECUTION_COLUMNS)
        action_projection = ",".join(f'a."{column}"' for column in ACTION_COLUMNS)
        daily = con.execute(
            f"""
            SELECT {daily_projection}
            FROM read_parquet(?) d JOIN candidate_bounds b ON {_candidate_join('d')}
            WHERE d.entry_session_offset IN (-1,0)
              AND d.trade_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
            """,
            [str(DAILY_TARGET_PATH)],
        ).fetchdf()
        execution = con.execute(
            f"""
            SELECT {execution_projection}
            FROM read_parquet(?) e JOIN candidate_bounds b ON {_candidate_join('e')}
            WHERE e.entry_session_offset=0 AND e.window_index=0
              AND e.trade_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31'
            """,
            [str(EXECUTION_WINDOW0)],
        ).fetchdf()
        actions = con.execute(
            f"""
            SELECT {action_projection}
            FROM read_parquet(?) a JOIN candidate_bounds b ON {_candidate_join('a')}
            WHERE (
                (a.known_at<=CAST(a.entry_date AS TIMESTAMP)+INTERVAL 9 HOUR+INTERVAL 35 MINUTE
                 AND a.available_at<=CAST(a.entry_date AS TIMESTAMP)+INTERVAL 9 HOUR+INTERVAL 35 MINUTE)
                OR a.effective_date<=a.entry_date
              )
              AND (a.effective_date IS NULL OR (a.effective_date>a.signal_date AND a.effective_date<=a.h23_date))
            """,
            [str(ACTION_EVENTS)],
        ).fetchdf()
    return daily, execution, actions


def _load_one_candidate_path(entry: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Called only after online admission; opens exactly one candidate-keyed path."""
    params = [
        str(entry.protocol_arm),
        str(entry.gap_id),
        str(entry.symbol),
        pd.Timestamp(entry.signal_date).date(),
        pd.Timestamp(entry.entry_date).date(),
    ]
    predicate = (
        "protocol_arm=? AND gap_id=? AND symbol=? "
        "AND signal_date=? AND entry_date=?"
    )
    with duckdb.connect() as con:
        frames = []
        for path, columns, extra in (
            (DAILY_TARGET_PATH, DAILY_COLUMNS, "entry_session_offset BETWEEN -1 AND 23"),
            (EXECUTION_WINDOW0, EXECUTION_COLUMNS, "entry_session_offset BETWEEN 0 AND 23 AND window_index=0"),
            (ACTION_EVENTS, ACTION_COLUMNS, "effective_date IS NULL OR (effective_date>signal_date AND effective_date<=h23_date)"),
        ):
            projected = ",".join(f'"{column}"' for column in columns)
            frames.append(
                con.execute(
                    f"SELECT {projected} FROM read_parquet(?) WHERE {predicate} AND ({extra})",
                    [str(path), *params],
                ).fetchdf()
            )
    return frames[0], frames[1], frames[2]


def _attempt_path(arm: str) -> Path:
    return _arm_root(arm) / "attempt_seal.json"


def _arm_root(arm: str) -> Path:
    return OUTPUT_ROOT / arm


def _verify_v29r4_failure(activation: dict[str, Any]) -> dict[str, Any]:
    root = reject_symlink_components(_arm_root("v29r4"), "V29R4 result slot")
    result_path = root / "result.json"
    expected_members = {
        "attempt_seal.json",
        "candidate_audit.parquet",
        "entries.parquet",
        "accepted_trades.parquet",
        "result.json",
    }
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise StageBError("V29R5 is locked until immutable V29R4 result exists")
    members = {path.name: path for path in root.iterdir()}
    if set(members) != expected_members:
        raise StageBError("V29R4 result inventory is incomplete or unexpected")
    if stat.S_IMODE(root.lstat().st_mode) != 0o555:
        raise StageBError("V29R4 result directory is not immutable 0555")
    if not is_user_immutable(root):
        raise StageBError("V29R4 result directory lacks UF_IMMUTABLE")
    for path in members.values():
        bound = reject_symlink_components(path, "V29R4 result member")
        identity = bound.lstat()
        if (
            not stat.S_ISREG(identity.st_mode)
            or stat.S_IMODE(identity.st_mode) != 0o444
            or not is_user_immutable(bound)
        ):
            raise StageBError("V29R4 result bundle lacks immutable 0444 regular seals")
    result = load_json(result_path, "V29R4 result")
    if result.get("verdict") == "PASS":
        raise StageBError("V29R4 passed; V29R5 is permanently ineligible")
    gates = result.get("summary", {}).get("success_gates")
    bound_activation = result.get("activation", {})
    gate_names = {
        "accepted_trades_per_development_year_gt_50",
        "mean_net_return_ge_0_04",
        "mean_holding_sessions_lt_15",
    }
    gate_values_are_bool = bool(
        isinstance(gates, dict)
        and set(gates) == gate_names
        and all(type(value) is bool for value in gates.values())
    )
    passed_count = sum(gates.values()) if gate_values_are_bool else -1
    expected_verdict = (
        "PASS"
        if passed_count == len(gate_names)
        else "FAIL_ALL_GATES" if passed_count == 0 else "FAIL_ONE_OR_MORE_GATES"
    )
    output_hashes = result.get("output_hashes")
    if (
        result.get("experiment") != EXPERIMENT
        or result.get("arm") != "v29r4"
        or result.get("aggregate_publication_status") != "COMPLETE"
        or expected_verdict not in {"FAIL_ALL_GATES", "FAIL_ONE_OR_MORE_GATES"}
        or result.get("verdict") != expected_verdict
        or result.get("summary", {}).get("passed_all_success_gates") is not False
        or not gate_values_are_bool
        or bound_activation != activation
        or not isinstance(output_hashes, dict)
        or set(output_hashes) != {"candidate_audit", "entries", "accepted_trades"}
        or result.get("post_2021_rows_opened") != "NO"
        or result.get("raw_competing_cohort_outcomes_opened") != "NO"
        or result.get("charts_run") != "NO"
        or result.get("validation_run") != "NO"
        or result.get("pit_contract") != PIT_CONTRACT
    ):
        raise StageBError("V29R4 result did not fail the frozen all-required gate")
    for name, digest in output_hashes.items():
        path = root / f"{name}.parquet"
        if sha256(path) != digest:
            raise StageBError("V29R4 output hash drift")
    attempt = _attempt_path("v29r4")
    if (
        stat.S_IMODE(attempt.lstat().st_mode) != 0o444
        or not is_user_immutable(attempt)
        or result.get("attempt_seal_sha256") != sha256(attempt)
    ):
        raise StageBError("V29R4 attempt seal drift")
    attempt_payload = load_json(attempt, "V29R4 attempt seal")
    expected_attempt = {
        "experiment": EXPERIMENT,
        "arm": "v29r4",
        "protocol_arm": "V29R4_CAP25",
        "protocol_version": PROTOCOL_VERSION,
        "status": "ATTEMPT_OPENED_BEFORE_ANY_CY046_PARQUET_ROW",
        "runner_sha256": activation["runner_sha256"],
        "preregistration_sha256": activation["preregistration_sha256"],
        "manifest_sha256": activation["manifest_sha256"],
        "activation_audit_sha256": activation["activation_audit_sha256"],
        "activation_sha256": normalized_json_sha256(activation),
        "cohort_hashes": activation["frozen_cohorts"]["V29R4_CAP25"],
        "v29r4_failure_dependency": None,
        "post_2021_access": "PROHIBITED",
    }
    if attempt_payload != expected_attempt:
        raise StageBError("V29R4 attempt seal content drift")
    return {"path": str(result_path), "sha256": sha256(result_path)}


def _publish_attempt(arm: str, activation: dict[str, Any], dependency: Any) -> Path:
    initialize_output_anchor()
    attempt = _attempt_path(arm)
    slot = _arm_root(arm)
    if is_user_immutable(slot) or any(slot.iterdir()) or path_lexists(attempt):
        raise StageBError(f"refusing repeated or overwritten {arm} attempt")
    preflight_slot_capabilities(slot)
    protocol_arm = ARM_CONFIG[arm]["protocol_arm"]
    payload = {
        "experiment": EXPERIMENT,
        "arm": arm,
        "protocol_arm": protocol_arm,
        "protocol_version": PROTOCOL_VERSION,
        "status": "ATTEMPT_OPENED_BEFORE_ANY_CY046_PARQUET_ROW",
        "runner_sha256": activation["runner_sha256"],
        "preregistration_sha256": activation["preregistration_sha256"],
        "manifest_sha256": activation["manifest_sha256"],
        "activation_audit_sha256": activation["activation_audit_sha256"],
        "activation_sha256": normalized_json_sha256(activation),
        "cohort_hashes": activation["frozen_cohorts"][protocol_arm],
        "v29r4_failure_dependency": dependency,
        "post_2021_access": "PROHIBITED",
    }
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, default=str, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    try:
        descriptor = os.open(attempt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError as exc:
        raise StageBError(f"refusing repeated {arm} attempt") from exc
    try:
        written = 0
        while written < len(encoded):
            count = os.write(descriptor, encoded[written:])
            if count <= 0:
                raise StageBError("short write while publishing attempt seal")
            written += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(attempt, 0o444)
    set_user_immutable(attempt)
    if attempt.read_bytes() != encoded:
        raise StageBError("attempt seal readback mismatch")
    fsync_directory(slot)
    return attempt


def _terminal_audit(entries: pd.DataFrame, portfolio: pd.DataFrame) -> pd.DataFrame:
    audit = entries.copy()
    capacity = portfolio[["gap_id", "capacity_status", "terminal_class"]] if not portfolio.empty else pd.DataFrame(columns=["gap_id", "capacity_status", "terminal_class"])
    audit = audit.merge(capacity, on="gap_id", how="left", validate="one_to_one")
    mapping = {
        "NO_ENTRY_MECHANICAL_NOT_TRADED": "MECHANICAL_NO_ENTRY",
        "NO_ENTRY_MECHANICAL_UP_LIMIT": "MECHANICAL_NO_ENTRY",
        "NO_ENTRY_ACTION_COORDINATE": "ANNOUNCED_ACTION_ENTRY_BLOCK",
        "NO_ENTRY_PENDING_RISK_ACTION": "ANNOUNCED_ACTION_ENTRY_BLOCK",
        "NO_ENTRY_INSUFFICIENT_A67_HEADROOM": "INSUFFICIENT_HEADROOM",
    }
    for status, terminal in mapping.items():
        audit.loc[audit.entry_status.eq(status), "terminal_class"] = terminal
    eligible = audit.admin_status.eq("ADMINISTRATIVE_WINDOW_COMPLETE")
    if audit.loc[eligible, "terminal_class"].isna().any():
        raise StageBError("eligible candidate lacks exactly one terminal class")
    return audit


def _write_result_bundle(
    arm: str,
    activation: dict[str, Any],
    attempts: Path,
    candidates: pd.DataFrame,
    entries: pd.DataFrame,
    outcomes: pd.DataFrame,
    portfolio: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, Any]:
    slot = _arm_root(arm)
    result_names = {
        "attempt_seal.json",
        "candidate_audit.parquet",
        "entries.parquet",
        "accepted_trades.parquet",
        "result.json",
    }
    if (
        slot.is_symlink()
        or not slot.is_dir()
        or is_user_immutable(slot)
        or {path.name for path in slot.iterdir()} != {"attempt_seal.json"}
        or attempts != slot / "attempt_seal.json"
        or not is_user_immutable(attempts)
    ):
        raise StageBError(f"result slot is not one pristine consumed attempt: {slot}")
    temporary = slot / f".staging-{os.getpid()}-{uuid.uuid4().hex}"
    temporary.mkdir(mode=0o700)
    published: list[Path] = []
    try:
        audit_path = temporary / "candidate_audit.parquet"
        entries_path = temporary / "entries.parquet"
        trades_path = temporary / "accepted_trades.parquet"
        candidate_audit = _terminal_audit(entries, portfolio)
        write_parquet(candidate_audit, audit_path)
        write_parquet(entries, entries_path)
        write_parquet(
            outcomes.copy(),
            trades_path,
        )
        hashes = {
            "candidate_audit": sha256(audit_path),
            "entries": sha256(entries_path),
            "accepted_trades": sha256(trades_path),
        }
        passed_count = sum(summary["success_gates"].values())
        verdict = (
            "PASS"
            if summary["passed_all_success_gates"]
            else "FAIL_ALL_GATES" if passed_count == 0 else "FAIL_ONE_OR_MORE_GATES"
        )
        result = {
            "experiment": EXPERIMENT,
            "arm": arm,
            "aggregate_publication_status": "COMPLETE",
            "verdict": verdict,
            "summary": summary,
            "activation": activation,
            "pit_contract": PIT_CONTRACT,
            "attempt_seal_sha256": sha256(attempts),
            "output_hashes": hashes,
            "post_2021_rows_opened": "NO",
            "raw_competing_cohort_outcomes_opened": "NO",
            "charts_run": "NO",
            "validation_run": "NO",
        }
        result_path = temporary / "result.json"
        write_json(result_path, result)
        for path in (audit_path, entries_path, trades_path, result_path):
            os.chmod(path, 0o444)
        fsync_directory(temporary)
        for path in (audit_path, entries_path, trades_path, result_path):
            target = slot / path.name
            publish_no_replace(path, target)
            published.append(target)
        temporary.rmdir()
        fsync_directory(slot)
        freeze_published_tree(slot, result_names)
        fsync_directory(OUTPUT_ROOT)
        return result
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        # Before result.json commits, roll back only this function's own links so
        # the caller can publish the consumed attempt as BLOCKED.
        if not path_lexists(slot / "result.json"):
            for path in reversed(published):
                if path_lexists(path) and not is_user_immutable(path):
                    os.chmod(path, 0o600)
                    path.unlink()
            fsync_directory(slot)
        raise


def _write_blocked_result(arm: str, activation: dict[str, Any], attempt: Path, exc: Exception) -> dict[str, Any]:
    slot = _arm_root(arm)
    if (
        slot.is_symlink()
        or not slot.is_dir()
        or is_user_immutable(slot)
        or {path.name for path in slot.iterdir()} != {"attempt_seal.json"}
        or attempt != slot / "attempt_seal.json"
        or not is_user_immutable(attempt)
    ):
        raise StageBError(f"blocked-result slot is not one pristine consumed attempt: {slot}")
    temporary = slot / f".blocked-{os.getpid()}-{uuid.uuid4().hex}"
    temporary.mkdir(mode=0o700)
    result = {
        "experiment": EXPERIMENT,
        "arm": arm,
        "aggregate_publication_status": "BLOCKED",
        "verdict": "UNRESOLVED",
        "blocker": str(exc),
        "activation": activation,
        "pit_contract": PIT_CONTRACT,
        "attempt_seal_sha256": sha256(attempt),
        "performance_gates_computed": False,
    }
    path = temporary / "result.json"
    try:
        write_json(path, result)
        os.chmod(path, 0o444)
        fsync_directory(temporary)
        publish_no_replace(path, slot / "result.json")
        temporary.rmdir()
        fsync_directory(slot)
        freeze_published_tree(slot, {"attempt_seal.json", "result.json"})
        fsync_directory(OUTPUT_ROOT)
        return result
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def run_arm(arm: str) -> dict[str, Any]:
    if arm not in ARM_CONFIG:
        raise StageBError(f"unknown arm {arm}")
    activation = verify_activation()  # hashes and footers only; no parquet rows
    initialize_output_anchor()  # capability and immutable-root checks; still no rows
    dependency = _verify_v29r4_failure(activation) if arm == "v29r5" else None
    attempt = _publish_attempt(arm, activation, dependency)
    try:
        # Every post-seal row access and transformation must terminate in COMPLETE or BLOCKED.
        config = ARM_CONFIG[arm]
        candidates = normalize_candidates(
            _projected_read(config["identity"], IDENTITY_COLUMNS),
            expected_rows=config["expected_rows"],
            expected_by_year=config["expected_by_year"],
        )
        if candidates.protocol_arm.ne(config["protocol_arm"]).any():
            raise StageBError("identity protocol arm drift")
        calendar = normalize_calendar(
            _projected_read(MARKET_CALENDAR, CALENDAR_COLUMNS)
        )
        censored = administrative_censor(candidates, calendar)
        bad_calendar = censored.admin_status.eq("UNRESOLVED_SIGNAL_CALENDAR")
        if bad_calendar.any():
            raise StageBError("candidate signal is absent from frozen calendar")
        eligible = censored.loc[~censored.administratively_censored].copy()
        admin_bounds = _read_arm_rows(ADMIN_BOUNDS, ADMIN_BOUND_COLUMNS, config["protocol_arm"])
        verify_admin_bounds(censored, admin_bounds, calendar, config["protocol_arm"])
        # Only signal/entry state and already-known entry actions are decoded here.
        daily_entry, execution_entry, entry_actions = _load_entry_inputs(
            eligible, config["protocol_arm"]
        )
        entries = build_entries(
            censored, daily_entry, execution_entry, entry_actions, config["protocol_arm"]
        )

        def resolve(row: Any) -> dict[str, Any]:
            daily, execution, actions = _load_one_candidate_path(row)
            return evaluate_one_outcome(row, daily, execution, actions, calendar)

        portfolio, outcomes = replay_online_portfolio(entries, resolve)
        summary = summarize(censored, entries, outcomes, portfolio)
        return _write_result_bundle(
            arm, activation, attempt, censored, entries, outcomes, portfolio, summary
        )
    except Exception as exc:
        return _write_blocked_result(arm, activation, attempt, exc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("verify-activation", "run-v29r4", "run-v29r5"),
        default="verify-activation",
    )
    args = parser.parse_args()
    if args.mode == "verify-activation":
        payload = verify_activation()
    elif args.mode == "run-v29r4":
        payload = run_arm("v29r4")
    else:
        payload = run_arm("v29r5")
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
