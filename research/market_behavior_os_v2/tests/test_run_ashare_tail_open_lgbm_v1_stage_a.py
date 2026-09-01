from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "research/market_behavior_os_v2/scripts/run_ashare_tail_open_lgbm_v1_stage_a.py"
MODULE_SPEC = importlib.util.spec_from_file_location("tail_open_stage_a", SCRIPT)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


def _manifest() -> dict:
    return json.loads(MODULE.FEATURE_PATH.read_text(encoding="utf-8"))


def _spec() -> dict:
    return json.loads(MODULE.SPEC_PATH.read_text(encoding="utf-8"))


def test_feature_manifest_is_compact_unique_and_cutoff_safe() -> None:
    audit = MODULE.validate_feature_manifest(_manifest())
    assert audit == {"feature_count": 59, "unique_names": 59}


def test_post_cutoff_feature_is_rejected() -> None:
    manifest = copy.deepcopy(_manifest())
    manifest["features"][0]["formula"] = "price at 14:55"
    with pytest.raises(MODULE.StageAAuditError, match="post-cutoff"):
        MODULE.validate_feature_manifest(manifest)


def test_execution_clock_and_final_oos_are_frozen() -> None:
    spec = _spec()
    assert spec["clock"]["feature_cutoff"] == "14:25:00"
    assert spec["clock"]["entry_bar_end_time"] == "14:56:00"
    assert spec["portfolio"]["top_n"] == 10
    assert spec["final_oos_governance"]["status"] == "LOCKED_UNREAD"
    assert spec["stage_a_boundaries"]["forward_outcomes_read"] is False
    assert spec["stage_a_boundaries"]["post_2023_security_rows_read"] is False


def test_registered_schemas_and_calendar_metadata_only() -> None:
    schemas = MODULE.validate_schemas()
    assert set(schemas) == {"daily", "minute_daily", "execution", "raw"}
    calendar = MODULE.calendar_metadata()
    assert calendar["first_signal_after_60_session_warmup"] == "2018-04-02"
    assert calendar["security_columns_read_post_2023"] is False
