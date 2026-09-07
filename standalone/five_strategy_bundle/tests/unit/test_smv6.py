from types import SimpleNamespace

import pandas as pd

from five_strategy_bundle.strategies.smv6 import (
    FROZEN_SHA256,
    ShadowPlatform,
    frozen_namespace,
    raw_pool,
    source_sha256,
)


def test_smv6_source_sha256_and_pool() -> None:
    assert source_sha256() == FROZEN_SHA256
    pool = raw_pool()
    assert len(pool) == len(set(pool))
    assert pool


def test_smv6_frozen_execution_settings_are_captured() -> None:
    availability = pd.DataFrame(columns=["trade_date", "symbol"])
    platform = ShadowPlatform({}, {}, availability, [pd.Timestamp("2020-01-02")])
    namespace = frozen_namespace(platform)
    context = SimpleNamespace()
    namespace["init"](context)
    assert platform.commission_rate == 0.0002
    assert platform.slippage_total == 0.0016
    assert platform.daily_volume_limit == 0.25
    assert platform.minute_volume_limit == 0.5
