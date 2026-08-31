from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).parents[1] / "code/replicate_formation_depth.py"
SPEC = importlib.util.spec_from_file_location("formation_depth_qa", MODULE_PATH)
assert SPEC and SPEC.loader
qa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qa)


def test_rank_residual_scalar_fixture() -> None:
    frame = pd.DataFrame(
        {
            "state": [1, 2, 2, 4, 5, 6, 7, 8],
            "response": [8, 6, 7, 4, 5, 3, 2, 1],
            "control": [1, 1, 2, 2, 3, 3, 4, 4],
        }
    )
    n, rho = qa.partial_rank(frame, "state", "response", ["control"])
    assert n == 8
    assert np.isclose(rho, -0.9349335374369989, atol=1e-14)


def test_full_chain_and_determinism(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    lineage_root = Path("/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830")
    result = qa.run(first, lineage_root)
    qa.run(second, lineage_root)
    assert result["status"] == "PASS_ORTHOGONAL_REPLICATION"
    assert all(item["pass"] for item in result["experiments"].values())
    assert (first / "result.json").read_bytes() == (second / "result.json").read_bytes()
    for code in qa.EXPERIMENTS:
        assert (first / f"{code.lower()}_independent_audit.csv").read_bytes() == (
            second / f"{code.lower()}_independent_audit.csv"
        ).read_bytes()
    payload = json.loads((first / "result.json").read_text())
    assert payload["prohibited_data_read"] == {
        "cy008": False,
        "cy011": False,
        "post_2023": False,
        "raw_qd004": False,
        "strategy_outcomes": False,
    }
