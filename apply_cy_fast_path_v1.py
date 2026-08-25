#!/usr/bin/env python3
"""Apply or roll back CY fast-path v1 from a bundle directory.

Run from the CY repository root:
    python /path/to/CY_fast_path_v1/apply_cy_fast_path_v1.py --check
    python /path/to/CY_fast_path_v1/apply_cy_fast_path_v1.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BUNDLE_ROOT = Path(__file__).resolve().parent
PAYLOAD_ROOT = BUNDLE_ROOT / "payload"
LEGACY_PAYLOAD_ROOT = BUNDLE_ROOT / "CY_fast_path_v1" / "payload"
BACKUP_ROOT_NAME = ".cy-fast-v1-backup"

PAYLOAD_WRITES = (
    "src/cyq_game/chip/profile_metrics.py",
    "src/cyq_game/strategy/exact_chip_features.py",
    "tests/test_exact_chip_features.py",
)


@dataclass(frozen=True)
class Replacement:
    path: str
    old: str
    new: str
    expected_count: int = 1


REPLACEMENTS = (
    Replacement(
        "scripts/build_real_chip_year.py",
        'STORAGE_VERSION = "chip-operator-log-v11"\n'
        'STAGE_LAYOUT_VERSION = "bucket-symbol-v3-mixed-native-resolution"',
        'STORAGE_VERSION = "chip-operator-log-v12"\n'
        '_COMPATIBLE_TERMINAL_STORAGE_VERSIONS = frozenset(\n'
        '    {"chip-operator-log-v11", STORAGE_VERSION}\n'
        ')\n'
        'STAGE_LAYOUT_VERSION = "bucket-symbol-v3-mixed-native-resolution"',
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        "    prepare_minute_path,\n"
        ")\n"
        "from cyq_game.chip.state_v2 import (  # noqa: E402\n",
        "    prepare_minute_path,\n"
        ")\n"
        "from cyq_game.chip.profile_metrics import (  # noqa: E402\n"
        "    compute_distribution_metrics,\n"
        ")\n"
        "from cyq_game.chip.state_v2 import (  # noqa: E402\n",
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        '        ("known_cost_fraction", pa.float64()),\n'
        '        ("unknown_cost_fraction", pa.float64()),\n'
        '        ("average_cost", pa.float64()),\n'
        '        ("cost_p10", pa.float64()),\n'
        '        ("cost_p50", pa.float64()),\n'
        '        ("cost_p90", pa.float64()),\n'
        '        ("main_peak", pa.float64()),\n',
        '        ("known_cost_fraction", pa.float64()),\n'
        '        ("unknown_cost_fraction", pa.float64()),\n'
        '        ("profile_close", pa.float64()),\n'
        '        ("average_cost", pa.float64()),\n'
        '        ("cost_p01", pa.float64()),\n'
        '        ("cost_p10", pa.float64()),\n'
        '        ("cost_p50", pa.float64()),\n'
        '        ("cost_p90", pa.float64()),\n'
        '        ("cost_p99", pa.float64()),\n'
        '        ("main_peak", pa.float64()),\n'
        '        ("dominant_band_lower", pa.float64()),\n'
        '        ("dominant_band_upper", pa.float64()),\n'
        '        ("dominant_band_mass", pa.float64()),\n'
        '        ("profit_ratio", pa.float64()),\n'
        '        ("asr", pa.float64()),\n'
        '        ("cbw", pa.float64()),\n'
        '        ("concentration_20", pa.float64()),\n'
        '        ("peak_count", pa.int16()),\n',
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        "    codec: _CellCodec,\n"
        "    grid: StableLogPriceGrid,\n"
        "    cash_dividend_per_share: float = 0.0,\n",
        "    codec: _CellCodec,\n"
        "    grid: StableLogPriceGrid,\n"
        "    close: float,\n"
        "    cash_dividend_per_share: float = 0.0,\n",
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        "    profile = _profile_from_bucket_mass(by_bucket, grid)\n"
        "    total = state.free_float_shares\n",
        "    profile = (\n"
        "        None\n"
        "        if not by_bucket\n"
        "        else compute_distribution_metrics(by_bucket, close, grid=grid)\n"
        "    )\n"
        "    total = state.free_float_shares\n",
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        "        known_shares / total,\n"
        "        (total - known_shares) / total,\n"
        '        None if profile is None else profile["average"],\n'
        '        None if profile is None else profile["p10"],\n'
        '        None if profile is None else profile["p50"],\n'
        '        None if profile is None else profile["p90"],\n'
        '        None if profile is None else profile["peak"],\n',
        "        known_shares / total,\n"
        "        (total - known_shares) / total,\n"
        "        close,\n"
        "        None if profile is None else profile.average_cost,\n"
        "        None if profile is None else profile.cost_p01,\n"
        "        None if profile is None else profile.cost_p10,\n"
        "        None if profile is None else profile.cost_p50,\n"
        "        None if profile is None else profile.cost_p90,\n"
        "        None if profile is None else profile.cost_p99,\n"
        "        None if profile is None else profile.main_peak,\n"
        "        None if profile is None else profile.dominant_band_lower,\n"
        "        None if profile is None else profile.dominant_band_upper,\n"
        "        None if profile is None else profile.dominant_band_mass,\n"
        "        None if profile is None else profile.profit_ratio,\n"
        "        None if profile is None else profile.asr,\n"
        "        None if profile is None else profile.cbw,\n"
        "        None if profile is None else profile.concentration_20,\n"
        "        None if profile is None else profile.peak_count,\n",
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        "                    codec=codec,\n"
        "                    grid=grid,\n"
        "                    cash_dividend_per_share=float(\n",
        "                    codec=codec,\n"
        "                    grid=grid,\n"
        '                    close=float(row["close"]),\n'
        "                    cash_dividend_per_share=float(\n",
    ),
    Replacement(
        "scripts/build_real_chip_year.py",
        '        if row["storage_version"] != STORAGE_VERSION:\n'
        '            raise ValueError("terminal storage version mismatch")\n',
        '        if row["storage_version"] not in _COMPATIBLE_TERMINAL_STORAGE_VERSIONS:\n'
        '            raise ValueError("terminal storage version mismatch")\n',
    ),
    Replacement(
        "src/cyq_game/strategy/chip_lineage.py",
        '_OPERATOR_STORAGE_VERSION = "chip-operator-log-v11"\n'
        "_COMPATIBLE_OPERATOR_STORAGE_VERSIONS = frozenset(\n"
        "    {\n"
        '        "chip-operator-log-v8",\n'
        '        "chip-operator-log-v9",\n'
        '        "chip-operator-log-v10",\n'
        "        _OPERATOR_STORAGE_VERSION,\n"
        "    }\n"
        ")\n",
        '_OPERATOR_STORAGE_VERSION = "chip-operator-log-v12"\n'
        "_COMPATIBLE_OPERATOR_STORAGE_VERSIONS = frozenset(\n"
        "    {\n"
        '        "chip-operator-log-v8",\n'
        '        "chip-operator-log-v9",\n'
        '        "chip-operator-log-v10",\n'
        '        "chip-operator-log-v11",\n'
        "        _OPERATOR_STORAGE_VERSION,\n"
        "    }\n"
        ")\n",
    ),
    Replacement(
        "scripts/build_exact_10stock_overlay.py",
        '"""Build a small exact-v11 feature overlay for the ten-stock diagnostic."""',
        '"""Build a small exact feature overlay for the ten-stock diagnostic."""',
    ),
    Replacement(
        "scripts/build_exact_10stock_overlay.py",
        "    if output_path.is_file():\n"
        "        return symbol, pq.ParquetFile(output_path).metadata.num_rows, True\n",
        '    if output_path.is_file() and "feature_source" in (\n'
        "        pq.ParquetFile(output_path).schema_arrow.names\n"
        "    ):\n"
        "        return symbol, pq.ParquetFile(output_path).metadata.num_rows, True\n"
        "    output_path.unlink(missing_ok=True)\n",
    ),
    Replacement(
        "scripts/build_exact_10stock_overlay.py",
        '        "model_spread_main_peak",\n'
        "    }\n",
        '        "model_spread_main_peak",\n'
        '        "feature_source",\n'
        "    }\n",
    ),
    Replacement(
        "scripts/build_exact_10stock_overlay.py",
        "b\"exact-chip-ensemble-features-v3|dominant-half-height-band|median-three-models|log-grid-25bp-v1\"",
        "b\"exact-chip-ensemble-features-v4|persisted-daily-metrics-v12|median-three-models|log-grid-25bp-v1\"",
    ),
    Replacement(
        "scripts/build_exact_10stock_overlay.py",
        "                    'real-chip-inventory-v2.1/chip-operator-log-v11' AS state_version,\n",
        "                    CASE\n"
        "                        WHEN e.feature_source = 'PERSISTED_DAILY_METRICS_V12'\n"
        "                            THEN 'real-chip-inventory-v2.1/chip-operator-log-v12'\n"
        "                        ELSE 'real-chip-inventory-v2.1/replayed-legacy-operator-log'\n"
        "                    END AS state_version,\n",
    ),
    Replacement(
        "scripts/build_exact_10stock_overlay.py",
        "'B_RESEARCH_ONLY_EXACT_V11'",
        "'B_RESEARCH_ONLY_EXACT'",
        expected_count=2,
    ),
    Replacement(
        "tests/test_real_chip_storage.py",
        "def test_v11_schema_keeps_exact_compact_operators_and_economic_coordinates() -> None:\n"
        '    assert MODULE["STORAGE_VERSION"] == "chip-operator-log-v11"\n',
        "def test_v12_schema_keeps_exact_operators_and_daily_metrics() -> None:\n"
        '    assert MODULE["STORAGE_VERSION"] == "chip-operator-log-v12"\n'
        '    assert "chip-operator-log-v11" in MODULE[\n'
        '        "_COMPATIBLE_TERMINAL_STORAGE_VERSIONS"\n'
        "    ]\n",
    ),
    Replacement(
        "tests/test_real_chip_storage.py",
        '    assert schema.field("share_multiplier").type == pa.float64()\n'
        '    assert schema.field("research_valid").type == pa.bool_()\n',
        '    assert schema.field("share_multiplier").type == pa.float64()\n'
        '    assert schema.field("profile_close").type == pa.float64()\n'
        '    assert schema.field("cost_p01").type == pa.float64()\n'
        '    assert schema.field("cost_p99").type == pa.float64()\n'
        '    assert schema.field("dominant_band_mass").type == pa.float64()\n'
        '    assert schema.field("peak_count").type == pa.int16()\n'
        '    assert schema.field("research_valid").type == pa.bool_()\n',
    ),
    Replacement(
        "tests/test_real_chip_storage.py",
        '            "known_cost_fraction": 0.75,\n'
        '            "unknown_cost_fraction": 0.25,\n'
        '            "average_cost": 10.0,\n'
        '            "cost_p10": 9.0,\n'
        '            "cost_p50": 10.0,\n'
        '            "cost_p90": 11.0,\n'
        '            "main_peak": 10.0,\n',
        '            "known_cost_fraction": 0.75,\n'
        '            "unknown_cost_fraction": 0.25,\n'
        '            "profile_close": 10.5,\n'
        '            "average_cost": 10.0,\n'
        '            "cost_p01": 8.0,\n'
        '            "cost_p10": 9.0,\n'
        '            "cost_p50": 10.0,\n'
        '            "cost_p90": 11.0,\n'
        '            "cost_p99": 12.0,\n'
        '            "main_peak": 10.0,\n'
        '            "dominant_band_lower": 9.5,\n'
        '            "dominant_band_upper": 10.5,\n'
        '            "dominant_band_mass": 0.7,\n'
        '            "profit_ratio": 0.6,\n'
        '            "asr": 0.5,\n'
        '            "cbw": 50.0,\n'
        '            "concentration_20": 0.8,\n'
        '            "peak_count": 2,\n',
    ),
    Replacement(
        "tests/test_real_chip_storage.py",
        "        codec=codec,\n"
        "        grid=grid,\n"
        "        share_multiplier=2.0,\n",
        "        codec=codec,\n"
        "        grid=grid,\n"
        "        close=grid.price_for_bucket(200),\n"
        "        share_multiplier=2.0,\n",
    ),
)

PREWRITE_EXPECTATIONS = {
    "src/cyq_game/strategy/exact_chip_features.py": (
        '"""Strategy features derived directly from persisted exact chip inventories."""',
        "resolver.iter_daily_bucket_mass(symbol, start, end)",
    ),
    "tests/test_exact_chip_features.py": (
        "def test_exact_distribution_features_use_known_economic_cost_mass()",
        "def test_exact_research_invalid_reason_preserves_source_failure()",
    ),
}

APPLIED_MARKERS = {
    "scripts/build_real_chip_year.py": (
        'STORAGE_VERSION = "chip-operator-log-v12"',
        '("profile_close", pa.float64())',
        "compute_distribution_metrics(by_bucket, close, grid=grid)",
    ),
    "src/cyq_game/strategy/chip_lineage.py": (
        '_OPERATOR_STORAGE_VERSION = "chip-operator-log-v12"',
        '"chip-operator-log-v11",',
    ),
    "scripts/build_exact_10stock_overlay.py": (
        '"feature_source",',
        "PERSISTED_DAILY_METRICS_V12",
    ),
    "tests/test_real_chip_storage.py": (
        "def test_v12_schema_keeps_exact_operators_and_daily_metrics()",
        'schema.field("profile_close")',
    ),
}


class PatchError(RuntimeError):
    pass


def _touched_paths() -> tuple[str, ...]:
    return tuple(sorted(set(PAYLOAD_WRITES) | {item.path for item in REPLACEMENTS}))


def _read_payload(relative: str) -> str:
    path = (
        PAYLOAD_ROOT / relative
        if (PAYLOAD_ROOT / relative).is_file()
        else (LEGACY_PAYLOAD_ROOT / relative)
    )
    if not path.is_file():
        raise PatchError(f"missing payload file: {path}")
    return path.read_text(encoding="utf-8")


def _looks_applied(root: Path) -> bool:
    for relative in PAYLOAD_WRITES:
        target = root / relative
        if not target.is_file() or target.read_text(encoding="utf-8") != _read_payload(relative):
            return False
    for relative, markers in APPLIED_MARKERS.items():
        path = root / relative
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8")
        if not all(marker in text for marker in markers):
            return False
    return True


def _already_real_chip_year_fast_path(text: str) -> bool:
    return (
        "STORAGE_VERSION = OPERATOR_LOG_VERSION" in text
        and "def _profile_from_bucket_mass(" in text
        and "current_price: float | None = None" in text
        and "dominant_peak_today" in text
    )


def _already_operator_storage_compat_v12(text: str) -> bool:
    return "_OPERATOR_STORAGE_VERSION = OPERATOR_LOG_VERSION" in text


def _already_test_real_chip_storage_v12(text: str) -> bool:
    return (
        "test_v12_schema_keeps_full_cell_identity_and_economic_coordinates" in text
        and "dominant_peak_today" in text
        and "known_cost_fraction" in text
    )


def _check_git_clean(root: Path, allow_dirty: bool) -> None:
    if allow_dirty or not (root / ".git").exists():
        return
    touched = list(_touched_paths())
    commands = (
        ["git", "diff", "--quiet", "--", *touched],
        ["git", "diff", "--cached", "--quiet", "--", *touched],
    )
    for command in commands:
        completed = subprocess.run(command, cwd=root, check=False)
        if completed.returncode == 1:
            raise PatchError(
                "one or more touched files have uncommitted changes; commit/stash them "
                "or rerun with --allow-dirty"
            )
        if completed.returncode not in (0, 1):
            raise PatchError("git status check failed")
    profile = root / "src/cyq_game/chip/profile_metrics.py"
    if profile.exists():
        completed = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(profile.relative_to(root))],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode != 0:
            raise PatchError(
                "untracked src/cyq_game/chip/profile_metrics.py already exists; "
                "move it or rerun with --allow-dirty"
            )


def _build_proposed(root: Path, allow_dirty: bool) -> dict[str, str]:
    if _looks_applied(root):
        return {}
    _check_git_clean(root, allow_dirty)

    for relative in _touched_paths():
        path = root / relative
        if relative not in PAYLOAD_WRITES and not path.is_file():
            raise PatchError(f"missing expected repository file: {path}")

    proposed: dict[str, str] = {}
    for relative in {item.path for item in REPLACEMENTS}:
        path = root / relative
        proposed[relative] = path.read_text(encoding="utf-8")

    for relative, markers in PREWRITE_EXPECTATIONS.items():
        path = root / relative
        if not path.is_file():
            raise PatchError(f"missing expected repository file: {path}")
        current = path.read_text(encoding="utf-8")
        if not all(marker in current for marker in markers):
            raise PatchError(
                f"{relative}: current file does not match the expected main-branch implementation"
            )

    for replacement in REPLACEMENTS:
        current = proposed[replacement.path]
        if replacement.path == "scripts/build_real_chip_year.py" and _already_real_chip_year_fast_path(
            current
        ):
            continue
        if replacement.path == "src/cyq_game/strategy/chip_lineage.py" and _already_operator_storage_compat_v12(
            current
        ):
            continue
        if replacement.path == "tests/test_real_chip_storage.py" and _already_test_real_chip_storage_v12(
            current
        ):
            continue

        count = current.count(replacement.old)
        if count != replacement.expected_count:
            raise PatchError(
                f"{replacement.path}: expected {replacement.expected_count} match(es), "
                f"found {count}; repository changed or patch is partially applied"
            )
        proposed[replacement.path] = current.replace(
            replacement.old,
            replacement.new,
            replacement.expected_count,
        )

    for relative in PAYLOAD_WRITES:
        target = root / relative
        if relative == "src/cyq_game/chip/profile_metrics.py" and target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing != _read_payload(relative):
                raise PatchError(
                    f"{relative} already exists with different content; refusing to overwrite"
                )
        proposed[relative] = _read_payload(relative)

    for relative in list(proposed):
        target = root / relative
        if target.is_file():
            current = target.read_text(encoding="utf-8")
            if current == proposed[relative]:
                proposed.pop(relative)

    for relative, text in proposed.items():
        if relative.endswith(".py"):
            try:
                compile(text, relative, "exec")
            except SyntaxError as exc:
                raise PatchError(f"generated syntax error in {relative}: {exc}") from exc
    return proposed


def _backup(root: Path, proposed: dict[str, str]) -> None:
    backup_root = root / BACKUP_ROOT_NAME
    if backup_root.exists():
        raise PatchError(
            f"backup directory already exists: {backup_root}; rollback or remove it first"
        )
    manifest: dict[str, bool] = {}
    for relative in sorted(proposed):
        source = root / relative
        existed = source.exists()
        manifest[relative] = existed
        if existed:
            destination = backup_root / "files" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".cy-fast-v1.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _commit(root: Path, proposed: dict[str, str]) -> None:
    _backup(root, proposed)
    try:
        for relative, text in proposed.items():
            _atomic_write(root / relative, text)
    except BaseException:
        _rollback(root, quiet=True)
        raise


def _rollback(root: Path, *, quiet: bool = False) -> None:
    backup_root = root / BACKUP_ROOT_NAME
    manifest_path = backup_root / "manifest.json"
    if not manifest_path.is_file():
        raise PatchError(f"no fast-path backup found at {backup_root}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise PatchError("invalid backup manifest")
    for relative, existed in raw.items():
        target = root / relative
        if bool(existed):
            source = backup_root / "files" / relative
            if not source.is_file():
                raise PatchError(f"missing backup file: {source}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            target.unlink(missing_ok=True)
    shutil.rmtree(backup_root)
    if not quiet:
        print("Rolled back CY fast-path v1.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    root = args.repo.resolve()

    try:
        if args.rollback:
            _rollback(root)
            return 0
        proposed = _build_proposed(root, args.allow_dirty)
        if not proposed:
            print("CY fast-path v1 is already applied.")
            return 0
        if args.check:
            print("Preflight PASS. Files to change:")
            for relative in sorted(proposed):
                print(f"- {relative}")
            return 0
        _commit(root, proposed)
    except PatchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Applied CY fast-path v1:")
    for relative in sorted(proposed):
        print(f"- {relative}")
    print(f"Backup: {root / BACKUP_ROOT_NAME}")
    print("Next: run the focused tests, then rebuild operator logs as v12.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
