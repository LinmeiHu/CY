from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_phase2_4_attribution.py"
SPEC = spec_from_file_location("phase2_4", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_partial_spearman_removes_fixed_year_level() -> None:
    frame = pd.DataFrame(
        {
            "entry_year": [2020] * 5 + [2021] * 5,
            "x": [1, 2, 3, 4, 5] * 2,
            "y": [101, 102, 103, 104, 105, 201, 202, 203, 204, 205],
        }
    )
    result = MODULE.partial_spearman(frame, "x", "y", year_control=True)
    assert result["n"] == 10
    assert result["rho"] > 0.99


def test_bh_adjust_is_monotone_in_rank_order() -> None:
    adjusted = MODULE.bh_adjust([0.01, 0.03, 0.02, None])
    assert adjusted[0] <= adjusted[2] <= adjusted[1]
    assert adjusted[3] is None

