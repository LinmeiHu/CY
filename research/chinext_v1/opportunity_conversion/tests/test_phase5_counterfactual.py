from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pandas as pd
import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts/run_phase5_counterfactual_diagnostics.py"
)
SPEC = spec_from_file_location("phase5", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_ceiling_summary_retains_overlap_and_unclipped_giveback() -> None:
    frame = pd.DataFrame(
        {
            "terminal_return": [-0.10, 0.20],
            "realized_pnl": [-10.0, 20.0],
            "false_breakout": [True, False],
            "severe_loss_classification": [True, False],
            "opportunity20": [False, True],
            "capital": [100.0, 100.0],
            "mfe": [0.05, 0.30],
            "peak_close_return": [0.00, 0.25],
        }
    )
    result = MODULE.ceiling_summary(frame)
    assert result["perfect_terminal_sign_selection_ceiling"] == 10.0
    assert result["false_breakout_avoidance_ceiling"] == 10.0
    assert result["severe_loss_avoidance_ceiling"] == 10.0
    assert result["false_breakout_severe_overlap_count"] == 1
    assert result["opportunity20_mfe_initial_capital_ceiling"] == pytest.approx(10.0)
    assert result["opportunity20_peak_close_initial_capital_ceiling"] == pytest.approx(5.0)
