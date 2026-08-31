from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
RUNNER = PROGRAM / "scripts/run_mkt_formdepth_own_data_001.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "run_mkt_formdepth_own_data_001_test", RUNNER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_data_only_boundary_and_activation() -> None:
    module = _module()
    spec = module._load_spec()
    assert module.sha256_file(module.SPEC_PATH) == module.EXPECTED_SPEC_SHA256
    assert spec["membership"]["membership_fixed_before_future_response"] is True
    assert spec["response"]["future_response_only"] is True
    assert spec["resource_budget"]["duckdb_threads"] == 1
    prohibited = "|".join(spec["prohibited_computations"])
    assert "own/shared association" in prohibited
    assert "raw QD-004/CY-008" in prohibited
    assert "post-2023" in prohibited
    assert "CY-011" in prohibited


def test_ntile_matches_frozen_larger_buckets_first_rule() -> None:
    module = _module()
    for count in range(25, 36):
        observed = [
            module._expected_ntile(row, count) for row in range(1, count + 1)
        ]
        sizes = [observed.count(bucket) for bucket in range(1, 6)]
        assert max(sizes) - min(sizes) <= 1
        assert sizes == sorted(sizes, reverse=True)
        assert observed == sorted(observed)


def test_anchor_membership_is_built_before_future_response() -> None:
    module = _module()
    source = inspect.getsource(module.main)
    assert source.index("_create_anchor_strata(") < source.index(
        "path_runner._create_response_security("
    )


def test_path_domain_bind_retains_structurally_unavailable_response_cells() -> None:
    module = _module()
    keys = ["trade_date", "market_view", "denominator"]
    rows = []
    for date, responses in (("2023-12-22", 5), ("2023-12-25", 0)):
        for stratum in range(1, 6):
            rows.append(
                {
                    "trade_date": pd.Timestamp(date),
                    "market_view": "ALL_A",
                    "denominator": "ALL_STATUS",
                    "stratum": stratum,
                    "stratum_response_count": responses,
                }
            )
    panel = pd.DataFrame(rows)
    path = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2023-12-22"),
                "market_view": "ALL_A",
                "denominator": "ALL_STATUS",
                "crossing_response_count": 25,
            },
            {
                "trade_date": pd.Timestamp("2023-12-25"),
                "market_view": "ALL_A",
                "denominator": "ALL_STATUS",
                "crossing_response_count": float("nan"),
            },
        ]
    )
    bounded = module._bind_path_domain(panel, path)
    assert len(bounded) == 10
    assert len(bounded[keys].drop_duplicates()) == 2
    later = bounded["trade_date"].eq(pd.Timestamp("2023-12-25"))
    assert bounded.loc[later, "crossing_response_count"].isna().all()
    assert bounded.loc[later, "stratum_response_count"].eq(0).all()

    with pytest.raises(module.OwnSharedDataError, match="absent from bound"):
        module._bind_path_domain(panel, path.iloc[:1])
