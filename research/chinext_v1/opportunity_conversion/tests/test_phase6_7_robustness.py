from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_phase6_7_robustness.py"
SPEC = spec_from_file_location("phase6_7", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_within_year_standardization_removes_year_levels() -> None:
    frame = pd.DataFrame(
        {
            "entry_year": [2020, 2020, 2020, 2021, 2021, 2021],
            "x": [1.0, 2.0, 3.0, 101.0, 102.0, 103.0],
        }
    )
    values = MODULE.standardize_within_year(frame, "x")
    assert abs(values.iloc[:3].mean()) < 1e-12
    assert abs(values.iloc[3:].mean()) < 1e-12

