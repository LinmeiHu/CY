from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase2_candidate_selection_audit.py"
)
SPEC = spec_from_file_location("candidate_selection", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_group_summary_uses_only_strictly_covered_rows() -> None:
    frame = pd.DataFrame(
        {
            "coverage_20": [True, False],
            "mfe_20": [0.30, 9.0],
            "opportunity20_fixed20": [True, True],
            "opportunity50_fixed20": [False, True],
            "close_return_20": [0.10, 9.0],
            "terminal20_ge20": [False, True],
        }
    )
    result = MODULE.summarize_group(frame)
    assert result["candidate_count"] == 2
    assert result["covered20_count"] == 1
    assert result["median_mfe20"] == 0.30
    assert result["opportunity20_rate"] == 1.0
    assert result["opportunity50_rate"] == 0.0

