import numpy as np
import hashlib
from pathlib import Path
import pandas as pd

from .run import _corr_top20, _first_pressure, _outcomes


def test_top20_is_deterministic_and_excludes_leader():
    rng = np.random.default_rng(7)
    window = rng.normal(size=(20, 30))
    peers, scores = _corr_top20(window, np.array([0, 1]), np.ones(30, dtype=bool))
    assert peers.shape == (2, 20)
    assert not set(peers[0]).intersection({0})
    assert not set(peers[1]).intersection({1})
    again, again_scores = _corr_top20(window, np.array([0, 1]), np.ones(30, dtype=bool))
    assert np.array_equal(peers, again)
    assert np.allclose(scores, again_scores, equal_nan=True)


def test_first_pressure_does_not_select_future_best():
    basket = np.full(150, 0.001, dtype=float)
    basket[122:125] = -0.06
    basket[130:133] = -0.20
    pressure, _, _ = _first_pressure(basket, 121, 140)
    assert pressure == 123


def test_fixed_window_and_landmark_outcome_start():
    coord = np.arange(20, dtype=float)[:, None] + 100
    out = _outcomes(coord, 0, 5)
    assert np.isclose(out["fwd5"], coord[10, 0] / coord[5, 0] - 1)
    assert not np.isclose(out["fwd5"], coord[9, 0] / coord[5, 0] - 1)


def test_no_future_best_pressure_selection_is_deterministic():
    basket = np.linspace(0.001, 0.002, 150)
    assert _first_pressure(basket, 121, 140)[0] == -1


def test_materialized_panel_preserves_no_pressure_and_common_landmark():
    p = Path("/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v2/strong_stock_lifecycle_v2_event_panel.parquet")
    if not p.exists():
        return
    d = pd.read_parquet(p)
    assert d.event_id.is_unique
    assert (d.loc[d.peer_status == "OK", "peer_n"] == 20).all()
    assert (d.loc[d.pressure_status == "PRESSURE", "landmark"] == d.loc[d.pressure_status == "PRESSURE", "pressure_start"] + 4).all()
    assert (d.loc[d.pressure_status.isin(["NO_PRESSURE", "NO_PEER"]), "landmark"] == -1).all()
    assert (d.loc[d.pressure_status == "PRESSURE", "pressure_start"] > d.loc[d.pressure_status == "PRESSURE", "t"]).all()


def test_materialized_panel_hash_matches_manifest():
    root = Path("research/ashare_strong_stock_lifecycle_v2")
    panel = Path("/Volumes/quant/CY_quant_research/ashare_strong_stock_lifecycle_v2/strong_stock_lifecycle_v2_event_panel.parquet")
    manifest = root / "V2_MANIFEST.json"
    if not panel.exists() or not manifest.exists():
        return
    h = hashlib.sha256(panel.read_bytes()).hexdigest()
    assert h == __import__("json").loads(manifest.read_text())["event_panel_sha256"]
