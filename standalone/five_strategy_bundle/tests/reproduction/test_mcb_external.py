import os
from pathlib import Path

import pytest

from five_strategy_bundle.reproduce import run_mcb


@pytest.mark.skipif("FIVE_STRATEGY_INPUT_CONFIG" not in os.environ, reason="external registered inputs not configured")
def test_mcb_registered_reproduction(tmp_path):
    from five_strategy_bundle.io import load_input_config
    result = run_mcb(load_input_config(Path(os.environ["FIVE_STRATEGY_INPUT_CONFIG"])), tmp_path)
    assert result["status"] == "FULL_END_TO_END_REPRODUCIBLE"
