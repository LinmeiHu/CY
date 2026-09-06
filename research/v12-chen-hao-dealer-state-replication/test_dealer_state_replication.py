from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

STUDY_DIR = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "dealer_state_replication", STUDY_DIR / "run_dealer_state_replication.py"
)
assert SPEC is not None and SPEC.loader is not None
STUDY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = STUDY
SPEC.loader.exec_module(STUDY)
PROTOCOL = json.loads((STUDY_DIR / "preregistered_protocol.json").read_text())


def test_protocol_freezes_chronology_and_medium_horizons() -> None:
    assert tuple(PROTOCOL["chronology"]["future_horizons_sessions"]) == STUDY.HORIZONS
    assert PROTOCOL["chronology"]["t_plus_one"] is True
    assert PROTOCOL["cyqk"]["status"] == "UNAVAILABLE"
    assert PROTOCOL["prohibitions"]["full_market_build"] is False


def test_locked_mass_uses_total_float_without_normalization_or_clipping() -> None:
    distribution = STUDY.LotDistribution(
        coordinates=np.asarray([7.0, 8.0, 10.0]),
        shares=np.asarray([20.0, 45.0, 35.0]),
        ages=np.asarray([180.0, 30.0, 5.0]),
        acquisition_costs=np.asarray([7.0, 8.0, 10.0]),
        free_float=100.0,
        known_fraction=1.0,
    )
    assert STUDY.mass_below(distribution, 8.0) == 0.65
    assert STUDY.mass_below(distribution, 8.0, min_age=60) == 0.20
    assert STUDY.mass_below(distribution, 6.0) == 0.0


def test_future_outcomes_start_after_decision_bar() -> None:
    dates = pd.bdate_range("2020-01-02", periods=130)
    close = np.arange(100.0, 230.0)
    frame = pd.DataFrame(
        {"trade_date": dates, "close": close, "high": close + 1.0, "low": close - 1.0}
    )
    by_symbol = {"000001.SZ": frame}
    lookup = {("000001.SZ", day): index for index, day in enumerate(dates)}
    result = STUDY.future_outcomes(by_symbol, lookup, "000001.SZ", dates[0])
    assert math.isclose(result["future_return_5"], 105.0 / 100.0 - 1.0)
    assert math.isclose(result["mfe_5"], 106.0 / 100.0 - 1.0)
    assert result["time_to_peak_5"] == 5.0


def test_catalog_does_not_substitute_for_unavailable_cyqk() -> None:
    catalog = STUDY.method_catalog().set_index("method_id")
    row = catalog.loc["CYQK_LOW_TURNOVER_LONG_POSITIVE"]
    assert row["reproducibility"] == "UNAVAILABLE"
    assert "No proxy substituted" in row["frozen_operationalization"]


def test_gate_preserves_seller_model_disagreement() -> None:
    rows = []
    for model in (*STUDY.MODELS, "ENSEMBLE"):
        for split in ("validation", "holdout"):
            for horizon in (40, 60, 120):
                effect = 0.02
                if model in ("UNIFORM", "ACTIVE_STICKY") and split == "holdout":
                    effect = -0.02
                rows.append(
                    {
                        "group": "TARGET",
                        "market_scope": "ALL",
                        "position_scope": "ALL",
                        "horizon": horizon,
                        "model": model,
                        "split": split,
                        "matched_future_return_excess": effect,
                        "independent_symbols": 40,
                    }
                )
    gate, _ = STUDY.classification_from_results(
        pd.DataFrame(rows), target="TARGET", direction=1.0
    )
    assert gate == "MIXED"


def test_generated_manifest_binds_every_required_deliverable() -> None:
    results = STUDY_DIR / "results"
    manifest = json.loads((results / "result_manifest.json").read_text())
    required = {
        "method_reproducibility_catalog.csv",
        "locked_profitable_inventory.csv",
        "dealer_profit_state_outcomes.csv",
        "downshift_method_results.csv",
        "consolidation_method_results.csv",
        "ninety_vs_three_results.csv",
        "low_turnover_crossing_results.csv",
        "base_retention_vs_migration.csv",
        "dealer_state_transitions.csv",
        "wounded_dealer_results.csv",
        "double_peak_results.csv",
        "market_regime_interactions.csv",
        "seller_model_dealer_state_scorecard.csv",
        "horizon_comparison.csv",
        "dealer_method_scorecard.csv",
    }
    assert required <= {Path(path).name for path in manifest["artifacts"]}
    assert manifest["study_protocol_sha256"] == STUDY.sha256(STUDY_DIR / "preregistered_protocol.json")
    for relative, binding in manifest["artifacts"].items():
        path = STUDY_DIR / relative
        assert path.stat().st_size == binding["bytes"]
        assert STUDY.sha256(path) == binding["sha256"]
    assert manifest["gates"]["SAFE_TO_CHANGE_PRODUCTION_CHIP_SEMANTICS"] == "NO"
    assert manifest["gates"]["SAFE_TO_EXPAND_RESEARCH_TO_FULL_MARKET_3941"] == "NO"
