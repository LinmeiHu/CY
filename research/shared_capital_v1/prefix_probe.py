"""Actual raw-bar entry/account prefix probes and the legacy completion control."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from five_strategy_bundle.execution.daily import load_daily, strict_fixed_target_outcomes, replay_shared_router
from research.shared_capital_v1.build_inputs import execution_paths
from research.shared_capital_v1.causal_adapters import causal_fixed_target_outcomes, entered_population
from research.shared_capital_v1.stock_p0 import replay

HERE = Path(__file__).resolve().parent


def run():
    inputs = {k: Path(v) for k, v in json.loads((HERE.parent / "five_strategy_exit_risk_v1/input_config.json").read_text())["inputs"].items()}
    probes = []
    for route in ("bull", "fast", "slow"):
        root = HERE / "cache/atrdr"
        signals = pd.read_parquet(root / (route + "_signals.parquet"))
        outcomes = pd.read_parquet(root / (route + "_outcomes.parquet"))
        chosen = outcomes.loc[outcomes.status.eq("COMPLETED") & outcomes.entry_date.between("2018-01-01", "2021-12-31") & outcomes.holding_sessions.gt(5)].iloc[0]
        candidate = signals.loc[signals.event_id.eq(chosen.event_id)]
        daily = load_daily(execution_paths(inputs), [chosen.symbol])
        dates = daily.loc[daily.trade_date.ge(chosen.entry_date)].trade_date.sort_values().unique()
        cutoff = pd.Timestamp(dates[2])
        results = []
        for label, data in (("PREFIX", daily.loc[daily.trade_date.le(cutoff)]), ("EXTENDED", daily)):
            function = strict_fixed_target_outcomes if route == "slow" else causal_fixed_target_outcomes
            kwargs = {"target": .15 if route == "bull" else .1, "horizon": 15 if route == "bull" else 20, "profile": "NATIVE_PREFIX_PROBE"}
            if route == "slow":
                kwargs["max_path_sessions"] = 100
            result = function(candidate, data, **kwargs)
            entries = entered_population(result)
            entries["source_rank_order"] = 0
            entries["route"] = route.upper()
            account, intents, _, nav, blocker = replay("ATRDR", entries, data, str(pd.Timestamp(chosen.entry_date).date()), str(cutoff.date()))
            if blocker:
                raise ValueError(blocker)
            results.append((label, result, account, intents, nav))
        a, b = results
        pd.testing.assert_frame_equal(a[3], b[3])
        pd.testing.assert_frame_equal(a[4], b[4])
        if a[2].positions != b[2].positions or a[2].cash != b[2].cash:
            raise ValueError("actual prefix funding/state mismatch")
        probes.append({"route": route, "event_id": chosen.event_id, "symbol": chosen.symbol, "entry_date": chosen.entry_date, "cutoff": cutoff,
            "prefix_outcome_status": a[1].status.iloc[0], "extended_outcome_status": b[1].status.iloc[0],
            "legacy_completed_filter_prefix_entries": int(a[1].status.eq("COMPLETED").sum()), "legacy_completed_filter_extended_entries": int(b[1].status.eq("COMPLETED").sum()),
            "completed_only_filter_applies_to_this_legacy_route": route in ("bull", "slow"),
            "corrected_prefix_entries": len(a[3]), "corrected_extended_entries": len(b[3]), "max_abs_cash_diff": 0., "max_abs_nav_diff": 0., "max_abs_position_diff": 0.,
            "status": "PASS", "scope": "fixed actual native parent; independently recomputed outcomes and physical funding under raw bar truncation"})
    pd.DataFrame(probes).to_csv(HERE / "output/atrdr_actual_prefix_probes.csv", index=False)
    entries = pd.read_parquet(HERE / "cache/atrdr/precapital_entry_population.parquet")
    bull = pd.read_parquet(HERE / "cache/atrdr/bull_outcomes.parquet")
    slow = pd.read_parquet(HERE / "cache/atrdr/slow_outcomes.parquet")
    completed = set(bull.loc[bull.status.eq("COMPLETED"), "event_id"]) | set(slow.loc[slow.status.eq("COMPLETED"), "event_id"])
    legacy = entries.loc[entries.parent_event_id.isin(completed) | entries.parent_event_id.str.startswith("OAI")].copy()
    daily = load_daily(execution_paths(inputs), entries.symbol.tolist())
    rows = []
    for period, start, end in (("2018_2021", "2018-01-01", "2019-07-15"), ("2022_2023", "2022-01-01", "2023-12-29")):
        cohort = legacy.loc[legacy.entry_date.between(start, end)]
        data = daily.loc[daily.trade_date.between(start, end)]
        accepted, _, control = replay_shared_router(cohort, data, nav_end=pd.Timestamp(end))
        corrected = pd.read_parquet(HERE / "cache/atrdr" / period / "p0_nav.parquet")
        merged = corrected.merge(control, on="trade_date", validate="one_to_one")
        rows.append({"strategy": "ATRDR", "period": period, "comparison_end": end,
            "reference_kind": "LEGACY_COMPLETION_FILTER_CONTROL_SAME_RESET_NOT_SEALED_CONTINUATION",
            "legacy_end_nav": float(merged.combined_nav.iloc[-1] * 1e6), "corrected_end_nav": float(merged.nav.iloc[-1]),
            "end_nav_difference": float(merged.nav.iloc[-1] - merged.combined_nav.iloc[-1] * 1e6),
            "max_abs_nav_difference": float((merged.nav - merged.combined_nav * 1e6).abs().max()),
            "legacy_funded_entries": len(accepted), "corrected_funded_entries": int(pd.read_parquet(HERE / "cache/atrdr" / period / "p0_fills.parquet").side.eq("BUY").sum()),
            "scope": "only validated account prefix; no hypothetical NAV beyond unresolved corporate action"})
    pd.DataFrame(rows).to_csv(HERE / "output/atrdr_legacy_baseline_difference.csv", index=False)
    print(pd.DataFrame(probes).to_string(index=False), flush=True)
    print(rows, flush=True)


if __name__ == "__main__":
    run()
