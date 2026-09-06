from __future__ import annotations

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_demand_not_locked_v28r1 as subject,
)


def test_demand_not_locked_gate_fails_closed_and_rejects_limit_close() -> None:
    frame = pd.DataFrame(
        {
            "signal_raw_close": [9.99, 10.00, 9.994, np.nan, 9.00],
            "signal_up_limit_price": [10.00, 10.00, 10.00, 10.00, np.nan],
            "signal_price_hard_valid": [True, True, True, True, True],
            "signal_price_available_by_decision": [True, True, True, True, True],
        }
    )

    assert subject.demand_not_locked_mask(frame).tolist() == [True, False, False, False, False]
