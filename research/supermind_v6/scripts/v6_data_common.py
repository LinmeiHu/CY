from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_ROOT = REPO_ROOT / "research" / "supermind_v6"
STRATEGY_PATH = (
    RESEARCH_ROOT
    / "strategy"
    / (
        "SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_MINVOLLOC30_CAP50_"
        "SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py"
    )
)
DATA_ROOT = RESEARCH_ROOT / "data" / "market_data_v1"
QMT_DATA_ROOT = RESEARCH_ROOT / "data" / "market_data_qmt_v1"
MANIFEST_DIR = RESEARCH_ROOT / "manifests"
MANIFEST_PATH = MANIFEST_DIR / "v6_market_data_manifest.json"
VALIDATION_PATH = MANIFEST_DIR / "v6_market_data_validation.json"
CONTRACT_VERSION = "v6-market-data-contract-1"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def strategy_sha256() -> str:
    return sha256_file(STRATEGY_PATH)


def parse_strategy_pool() -> list[str]:
    tree = ast.parse(STRATEGY_PATH.read_text(encoding="utf-8"))
    assignments: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        is_pool = any(
            isinstance(target, ast.Attribute) and target.attr == "pool_raw"
            for target in node.targets
        )
        if is_pool:
            value = ast.literal_eval(node.value)
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError("context.pool_raw is not a literal list[str]")
            assignments.append(value)
    if len(assignments) != 1:
        raise ValueError(f"expected one context.pool_raw assignment; found {len(assignments)}")
    return assignments[0]


def universe_sha256(pool: list[str]) -> str:
    return sha256_bytes("\n".join(pool).encode("utf-8"))


def exchange_for(raw_code: str) -> str:
    if len(raw_code) != 6 or not raw_code.isdigit():
        raise ValueError(f"invalid raw code: {raw_code!r}")
    if raw_code.startswith("5"):
        return "SH"
    if raw_code.startswith("1"):
        return "SZ"
    raise ValueError(f"unsupported V6 ETF exchange prefix: {raw_code}")


def canonical_symbol(raw_code: str) -> str:
    return f"{raw_code}.{exchange_for(raw_code)}"


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_parquet(temporary, index=False, compression="zstd")
    os.replace(temporary, path)


def directory_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
