from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_breakout_hab_001.py"


def _module():
    spec = importlib.util.spec_from_file_location("run_mkt_breakout_hab_001_test", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_spec_and_map_identity() -> None:
    module = _module()
    spec = module._load_spec()
    assert hashlib.sha256(module.SPEC_PATH.read_bytes()).hexdigest() == (
        module.EXPECTED_SPEC_SHA256
    )
    research_map = spec["inputs"]["research_map"]
    assert (
        hashlib.sha256((ROOT / research_map["path"]).read_bytes()).hexdigest()
        == (research_map["sha256"])
    )


def test_prior_date_map_never_uses_event_date() -> None:
    module = _module()
    states = list(pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"]))
    mapped = module._prior_date_map(
        pd.Series(pd.to_datetime(["2020-01-02", "2020-01-06", "2020-01-07"])),
        states,
    )
    assert pd.isna(mapped[pd.Timestamp("2020-01-02")])
    assert mapped[pd.Timestamp("2020-01-06")] == pd.Timestamp("2020-01-03")
    assert mapped[pd.Timestamp("2020-01-07")] == pd.Timestamp("2020-01-06")


def test_partial_spearman_without_controls_preserves_monotonic_edge() -> None:
    module = _module()
    frame = pd.DataFrame({"response": np.arange(1.0, 11.0), "state": np.arange(11.0, 21.0)})
    n, rho, response_unique, state_unique = module._partial_spearman(frame, "response", "state", [])
    assert n == response_unique == state_unique == 10
    assert np.isclose(rho, 1.0)


def test_loaded_state_inputs_preserve_strict_availability_and_primary_population() -> None:
    module = _module()
    spec = module._load_spec()
    breakout, trend, breadth = module._load_inputs(spec)
    assert len(breakout) == 964
    assert set(breakout["temporal_block"]) == {"A", "B"}
    assert trend["index_symbol"].nunique() == 6
    assert breadth["market_view"].nunique() == 4
    assert set(breadth["denominator"]) == {"ALL_STATUS"}
