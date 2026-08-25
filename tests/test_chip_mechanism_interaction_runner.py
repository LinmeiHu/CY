from __future__ import annotations

import math
import runpy
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "run_chip_mechanism_interaction_v1.py"
)
MODULE = runpy.run_path(str(SCRIPT))


def _node(node_id: str, coordinates: tuple[int, int, int]) -> dict[str, object]:
    return {
        "parameter_id": node_id,
        "migration_index": coordinates[0],
        "disagreement_index": coordinates[1],
        "overhead_index": coordinates[2],
        "base_gate_pass": True,
    }


def test_robust_region_components_do_not_join_diagonal_or_isolated_nodes() -> None:
    components = MODULE["_components"](
        [
            _node("a", (0, 0, 0)),
            _node("b", (1, 0, 0)),
            _node("c", (1, 1, 0)),
            _node("isolated", (2, 2, 2)),
        ]
    )

    assert components == [["a", "b", "c"], ["isolated"]]


def test_holm_step_down_closes_after_first_non_rejection() -> None:
    metrics = [
        {"absolute": {"bootstrap_p_one_sided": 0.001}},
        {"absolute": {"bootstrap_p_one_sided": 0.04}},
        {"absolute": {"bootstrap_p_one_sided": 0.03}},
    ]

    MODULE["_holm_passes"](metrics, alpha=0.05)

    ordered = sorted(metrics, key=lambda item: item["holm"]["rank"])
    assert [item["holm"]["pass"] for item in ordered] == [True, False, False]


def test_missing_lower_bound_fails_closed_without_losing_zero() -> None:
    convert = MODULE["_finite_or_negative_infinity"]

    assert convert(0.0) == 0.0
    assert convert(None) == -math.inf
