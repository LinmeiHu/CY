from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_breakout_dyn_003.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_mkt_breakout_dyn_003_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_output_retry_inherits_science_and_relative_time() -> None:
    module = _module()
    effective, _ = module._load_spec()
    assert hashlib.sha256(module.SPEC_PATH.read_bytes()).hexdigest() == (
        module.EXPECTED_SPEC_SHA256
    )
    assert effective["experiment_id"] == "MKT-BREAKOUT-DYN-003"
    assert effective["population"]["event_time"] == "relative_day"
    assert effective["roles"] == module.retry002._load_spec()[0]["roles"]


def test_scientific_result_schema_has_no_dynamic_elapsed_field() -> None:
    source = (PROGRAM / "scripts/run_mkt_breakout_dyn_001.py").read_text()
    assert '"elapsed_seconds"' not in source
    assert "RUNNER_DEPENDENCIES" in source
