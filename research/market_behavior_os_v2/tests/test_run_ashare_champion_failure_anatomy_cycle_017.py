from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT
    / "research/market_behavior_os_v2/scripts/"
    "run_ashare_champion_failure_anatomy_cycle_017.py"
)
RESULT = (
    ROOT
    / "research/market_behavior_os_v2/artifacts/"
    "ASHARE-CHAMPION-FAILURE-ANATOMY-CYCLE-017_result.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("champion_failure_cycle_017_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_contract_freezes_diagnostic_only_failure_anatomy() -> None:
    spec = _module()._load_spec()
    assert spec["starting_checkpoint"] == "c5a38ef68a"
    assert spec["champion"]["changes_authorized"] is False
    assert spec["chronology"]["losing_years"] == [2018, 2022]
    assert spec["continuation_rotation"]["checkpoints"] == [5, 10, 15, 20]
    assert any("hypothetical improved return" in item for item in spec["prohibited"])


def test_result_preserves_champion_and_classifies_each_year() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    annual = {row["year"]: row for row in result["annual_chronology"]}
    assert annual[2018]["champion_return"] < 0
    assert annual[2022]["champion_return"] < 0
    assert all(annual[year]["champion_return"] > 0 for year in (2019, 2020, 2021, 2023))
    assert result["failure_classification"]["2018"]["market_exposure"] == "BETA_DOMINATED"
    assert result["failure_classification"]["2022"]["market_exposure"] == "BETA_DOMINATED"
    assert result["common_failure_conclusion"] == "COMMON_MARKET_BETA_FAILURE"


def test_result_does_not_convert_diagnosis_into_strategy_change() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    assert result["boundaries"] == {
        "champion_changed": False,
        "cy011_read": False,
        "filter_tested": False,
        "hypothetical_improved_return_reported": False,
        "new_alpha_implemented": False,
        "oos_claim": False,
        "post_2023_read": False,
    }
    for year in ("2018", "2022"):
        assert (
            result["failure_classification"][year]["strategy_layer"]
            == "UPSTREAM_INDUSTRY_FAILURE_LOWMAX_STILL_HELPFUL"
        )
