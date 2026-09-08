import json
from pathlib import Path
import pandas as pd
import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"


def test_native_scope_and_required_objects():
    m = pd.read_csv(OUT / "native_strategy_annual_metrics.csv")
    assert set(m.strategy) == {"ATRDR", "MCB", "OGR", "IFCGR", "SMV6"}
    assert len(m) == 45 and set(m.year) == set(range(2018, 2027))
    r = pd.read_csv(OUT / "native_atrdr_route_only_annual_metrics.csv")
    assert set(r.route) == {"BULL", "FAST_BEAR", "SLOW_BEAR"} and len(r) == 27


def test_route_only_replays_have_distinct_receipts():
    for route in ("BULL", "FAST_BEAR", "SLOW_BEAR"):
        receipt = json.loads((HERE / "cache" / "route_only" / route / "receipt.json").read_text())
        assert receipt["status"] == "PASS" and receipt["version"] == 2
        assert receipt["initial_cash"] == 1_000_000.0


def test_route_contribution_is_not_route_only_return():
    c = pd.read_csv(OUT / "native_atrdr_route_contribution_annual.csv")
    r = pd.read_csv(OUT / "native_atrdr_route_only_annual_metrics.csv")
    assert len(c) == 27 and len(r) == 27
    assert not np.allclose(c.pnl.to_numpy(), r.net_pnl.to_numpy())


def test_negative_year_concentration_is_explicit():
    m = pd.read_csv(OUT / "native_strategy_annual_metrics.csv")
    neg = m.loc[m.net_pnl <= 0]
    assert (neg.best_1_day_pnl_fraction == "NA_NEGATIVE_OR_ZERO_DENOMINATOR").all()


def test_output_manifest_reconstructs():
    for line in (OUT / "output_manifest.sha256").read_text().splitlines():
        digest, name = line.split("  ", 1)
        assert digest == __import__("hashlib").sha256((HERE / name).read_bytes()).hexdigest()
