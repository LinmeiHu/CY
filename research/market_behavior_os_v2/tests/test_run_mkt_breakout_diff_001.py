from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "research/market_behavior_os_v2/scripts/run_mkt_breakout_diff_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_breakout_diff_001_tested", RUNNER)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
module = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(module)


def test_frozen_spec_excludes_failed_acceptance_industry_roles() -> None:
    spec = module._load_spec()
    assert spec["experiment_id"] == "MKT-BREAKOUT-DIFF-001"
    assert sorted(spec["data_activation"]["failed_roles_not_advanced"]) == [
        "acceptance_diffusion",
        "acceptance_leadership_concentration",
    ]
    assert not any(role.startswith("acceptance_") for role in spec["roles"])


def test_adjusted_rank_r2_distinguishes_exact_and_unrelated_geometry() -> None:
    frame = pd.DataFrame(
        {
            "target": np.arange(20, dtype=float),
            "same": np.arange(20, dtype=float),
            "alternating": np.tile([0.0, 1.0], 10),
        }
    )
    exact = module.adjusted_rank_r2(frame, "target", ["same"])
    unrelated = module.adjusted_rank_r2(frame, "target", ["alternating"])
    assert exact == 1.0
    assert unrelated < 0.0


def test_connected_components_uses_absolute_redundancy() -> None:
    correlation = pd.DataFrame(
        [[1.0, -0.9, 0.1], [-0.9, 1.0, 0.2], [0.1, 0.2, 1.0]],
        index=["a", "b", "c"],
        columns=["a", "b", "c"],
    )
    assert module.connected_components(correlation, 0.85) == [["a", "b"], ["c"]]


def test_semantic_bounds_keep_divergence_signed() -> None:
    assert module._semantic_bounds("stock_industry_divergence", pd.Series([-0.2, 0.3]))
    assert not module._semantic_bounds("stock_industry_divergence", pd.Series([-1.1, 0.0]))
