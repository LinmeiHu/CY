from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

SCRIPT = Path(__file__).with_name("benchmark_primitive_layout.py")
SPEC = importlib.util.spec_from_file_location("benchmark_primitive_layout", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_grid_is_exact_auction_and_continuous_session() -> None:
    expected = MODULE.EXPECTED_MINUTES
    assert len(expected) == 241
    assert expected[0] == 570
    assert np.array_equal(expected[1:121], np.arange(571, 691))
    assert np.array_equal(expected[121:], np.arange(781, 901))


def test_sample_is_frozen_and_outcome_blind() -> None:
    assert str(MODULE.SAMPLE_DATE.date()) == "2020-02-03"
    assert MODULE.SAMPLE_SIZE == 128
    source = SCRIPT.read_text(encoding="utf-8")
    for prohibited in ("strategy membership", "MFE", "MAE", "CY-011"):
        assert prohibited not in source


def test_packet_result_binds_benchmark_and_code() -> None:
    packet = SCRIPT.parent
    result = json.loads((packet / "result.json").read_text(encoding="utf-8"))
    benchmark = json.loads(
        (packet / "benchmark_result.json").read_text(encoding="utf-8")
    )
    assert result["cache_published"] is False
    assert result["outcome_access"] is False
    assert result["source_hashes"]["benchmark_code"] == MODULE.sha256_file(SCRIPT)
    assert result["benchmark"]["benchmark_result_sha256"] == MODULE.sha256_file(
        packet / "benchmark_result.json"
    )
    assert result["benchmark"]["array241_sha256"] == benchmark["candidates"][
        "array241"
    ]["sha256"]
