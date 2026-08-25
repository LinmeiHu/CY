import numpy as np

from cyq_game.chip.operator_soa import advance_inventory_and_lineage


def test_compiled_operator_replay_merges_destination_collisions() -> None:
    ids, inventory, lineage = advance_inventory_and_lineage(
        np.array([1, 2], dtype=np.uint64),
        np.array([60.0, 40.0]),
        np.array([30.0, 20.0]),
        np.array([1, 2], dtype=np.uint64),
        np.array([3, 3], dtype=np.uint64),
        np.array([0.5, 0.25]),
        np.array([4], dtype=np.uint64),
        np.array([60.0]),
    )
    assert ids.tolist() == [3, 4]
    assert inventory.tolist() == [40.0, 60.0]
    assert lineage.tolist() == [20.0, 0.0]
