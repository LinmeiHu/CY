from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PATH = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_tail_open_lgbm_v1_absolute_calibration_audit.py"
SPEC = importlib.util.spec_from_file_location("tail_open_absolute_calibration_test", PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def test_positive_slope_with_negative_positive_pool_is_ranking_only() -> None:
    lightgbm = {
        "canonical_zero_threshold": {
            "mean_realized_net_return": -0.01,
            "fraction_all_dates_active": 0.05,
            "yearly_realized_net_return": {str(year): -0.01 for year in AUDIT.YEARS},
        },
        "calibration_regression": {"pooled": {"slope": 0.5}},
    }
    assert AUDIT._classify(lightgbm) == "ABSOLUTE_SCORE_RANKING_ONLY"
