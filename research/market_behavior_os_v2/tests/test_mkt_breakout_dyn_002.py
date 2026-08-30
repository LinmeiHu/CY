from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_breakout_dyn_002.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_mkt_breakout_dyn_002_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_control_spec_and_map_identity() -> None:
    module = _module()
    module.base.SPEC_PATH = module.SPEC_PATH
    effective, _ = module._load_spec()
    assert module.base.SPEC_PATH == module.SPEC_PATH
    assert _sha256(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert effective["experiment_id"] == "MKT-BREAKOUT-DYN-002"
    assert effective["population"]["event_time"] == "relative_day"
    assert effective["population"]["required_sequence_time_grid"] == [
        -5,
        -4,
        -3,
        -2,
        -1,
    ]


def test_control_adapter_uses_relative_day_not_selection_ordinal() -> None:
    module = _module()
    effective, parent = module._load_spec()
    source = module._load_parent_panel(effective, parent)
    rows = source.loc[
        source["sequence_id"].eq("2018|01|ALL_A|02|600576.SH")
        & source["definition"].eq("L10_CONTINUOUS")
    ].sort_values("trade_date")
    assert rows["relative_day"].tolist() == [-5, -4]
    assert rows["market_sequence_rank"].tolist() == [-5, -4]
