"""Pure helpers for the frozen ChinNext V1 Phase 4 diagnostic."""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy.chinext_v1_exploratory import sort_candidates

MATCHED_ARM_ORDER = (
    "M2_MINUS_B60_BASELINE_CAPACITY",
    "M3_MINUS_FULL40_BASELINE_CAPACITY",
)

MATCHED_TO_RAW = {
    "M2_MINUS_B60_BASELINE_CAPACITY": "A2_MINUS_B60",
    "M3_MINUS_FULL40_BASELINE_CAPACITY": "A3_MINUS_FULL40",
}

REMOVED_DIAGNOSTIC = {
    "A2_MINUS_B60": "b60_diagnostic_passed",
    "A3_MINUS_FULL40": "full40_diagnostic_passed",
}

CROWDOUT_CATEGORIES = (
    "CAPTURED_SAME_EPISODE",
    "ELIGIBLE_BUT_OUTRANKED",
    "NO_VACANCY_AT_SIGNAL_DATE",
    "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES",
    "PORTFOLIO_PATH_ALREADY_DIVERGED",
    "NOT_ELIGIBLE_FOR_OTHER_FROZEN_REASON",
    "INSUFFICIENT_LOG_DATA",
    "OTHER_EXPLAINED",
)


def select_with_capacity_envelope(
    current_members: Iterable[str],
    forced_exits: Iterable[str],
    ranked_candidates: Sequence[str],
    capacity: int,
) -> tuple[str, ...]:
    """Apply a frozen entry-slot ceiling without inventing capacity-driven exits.

    Existing survivors remain sticky, preserving the baseline no-replacement and
    exit semantics.  If they already exceed the A0 envelope, no new member is
    admitted until ordinary frozen exits bring the set back under the ceiling.
    """

    if capacity < 0 or capacity > 10:
        raise ValueError("capacity envelope must be between zero and ten")
    forced = set(forced_exits)
    survivors = sorted(set(current_members) - forced)
    vacancies = max(0, capacity - len(survivors))
    additions = [
        symbol
        for symbol in ranked_candidates
        if symbol not in survivors and symbol not in forced
    ][:vacancies]
    return tuple(sorted(survivors + additions))


def canonical_envelope(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    envelope = [
        {
            "trade_date": str(row["trade_date"]),
            "allowed_target_member_count": int(row["planned_members"]),
        }
        for row in rows
    ]
    dates = [row["trade_date"] for row in envelope]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError("baseline capacity dates must be unique and ordered")
    if any(not 0 <= row["allowed_target_member_count"] <= 10 for row in envelope):
        raise ValueError("baseline capacity count outside frozen portfolio bounds")
    return envelope


def crowdout_rows(
    *,
    raw_arm: str,
    top20: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    executions: Sequence[Mapping[str, Any]],
    daily_nav: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Classify each frozen A0 Top20 episode using only Phase 3 ledgers."""

    diagnostic_key = REMOVED_DIAGNOSTIC[raw_arm]
    evaluations = {
        (str(row["signal_date"]), str(row["symbol"])): row
        for row in events
        if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
    }
    changes = {
        str(row["signal_date"]): row
        for row in events
        if row.get("event") == "DESIRED_SET_CHANGED"
    }
    nav_by_date = {str(row["trade_date"]): row for row in daily_nav}
    captured = {
        (str(row["signal_date"]), str(row["symbol"]))
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
    }
    targets_by_date: dict[str, list[tuple[int, Mapping[str, Any]]]] = {}
    for rank, row in enumerate(top20, start=1):
        targets_by_date.setdefault(str(row["entry_signal_date"]), []).append((rank, row))

    planned: set[str] = set()
    origins: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for signal_date in sorted(set(changes) | set(targets_by_date)):
        change = changes.get(signal_date)
        previous = set(change["previous"]) if change else set(planned)
        desired = set(change["desired"]) if change else set(planned)
        if previous != planned:
            raise RuntimeError(f"Phase 3 desired-set lineage diverged on {signal_date}")
        survivors = previous & desired
        additions = desired - previous
        extra_survivors = sorted(
            symbol for symbol in survivors if origins.get(symbol, {}).get("extra") is True
        )
        eligible_rows = {
            symbol: evaluation
            for (day, symbol), evaluation in evaluations.items()
            if day == signal_date
            and evaluation["price_structure_pass"] is True
            and evaluation["minvol"]["passed"] is True
            and evaluation.get("rs") is not None
        }
        ranked = sort_candidates(eligible_rows, {symbol: row["rs"] for symbol, row in eligible_rows.items()})

        for baseline_rank, target in targets_by_date.get(signal_date, []):
            symbol = str(target["symbol"])
            episode = (signal_date, symbol)
            evaluation = evaluations.get(episode)
            remaining_eligible = bool(
                evaluation
                and evaluation["price_structure_pass"] is True
                and evaluation["minvol"]["passed"] is True
                and evaluation.get("rs") is not None
                and nav_by_date[signal_date]["market_entry_permission"] is True
            )
            detail = ""
            if episode in captured:
                category = "CAPTURED_SAME_EPISODE"
            elif symbol in previous:
                category = "PORTFOLIO_PATH_ALREADY_DIVERGED"
                detail = "same symbol was already a planned member from an earlier episode"
            elif evaluation is None:
                category = "INSUFFICIENT_LOG_DATA"
                detail = "no entry evaluation persisted for the episode"
            elif not remaining_eligible:
                category = "NOT_ELIGIBLE_FOR_OTHER_FROZEN_REASON"
                detail = "one or more remaining frozen admission conditions did not pass"
            elif symbol in desired:
                category = "OTHER_EXPLAINED"
                detail = "selected into desired set but no filled new-position buy was recorded"
            elif len(survivors) >= 10:
                if extra_survivors:
                    category = "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES"
                    detail = "all ten survivor slots were occupied and at least one survivor was an earlier extra entry"
                else:
                    category = "NO_VACANCY_AT_SIGNAL_DATE"
                    detail = "all ten survivor slots were occupied"
            elif len(additions) >= 10 - len(survivors):
                category = "ELIGIBLE_BUT_OUTRANKED"
                detail = "remaining vacancies were filled by higher frozen-RS candidates"
            else:
                category = "OTHER_EXPLAINED"
                detail = "eligible candidate was not selected despite an unfilled capacity slot"

            result = {
                "raw_arm": raw_arm,
                "baseline_rank": baseline_rank,
                "symbol": symbol,
                "entry_signal_date": signal_date,
                "classification": category,
                "remaining_conditions_eligible": remaining_eligible,
                "captured_same_episode": episode in captured,
                "previous_member_count": len(previous),
                "survivor_count_after_frozen_exits": len(survivors),
                "vacancies_before_additions": max(0, 10 - len(survivors)),
                "selected_additions": "|".join(sorted(additions)),
                "extra_survivor_count": len(extra_survivors),
                "extra_survivors": "|".join(extra_survivors),
                "candidate_rs_rank": ranked.index(symbol) + 1 if symbol in ranked else None,
                "removed_module_diagnostic_passed": (
                    evaluation["phase3_ablation"][diagnostic_key] if evaluation else None
                ),
                "earlier_same_symbol_origin": json.dumps(
                    origins.get(symbol), ensure_ascii=False, sort_keys=True
                )
                if symbol in previous
                else "",
                "finite_capacity_crowdout": category
                in {
                    "ELIGIBLE_BUT_OUTRANKED",
                    "NO_VACANCY_AT_SIGNAL_DATE",
                    "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES",
                },
                "evidence": detail,
            }
            if category not in CROWDOUT_CATEGORIES:
                raise AssertionError(category)
            results.append(result)

        if change:
            new_planned = set(change["desired"])
            for symbol in planned - new_planned:
                origins.pop(symbol, None)
            for symbol in new_planned - planned:
                evaluation = evaluations.get((signal_date, symbol))
                origins[symbol] = {
                    "signal_date": signal_date,
                    "extra": bool(
                        evaluation
                        and evaluation["phase3_ablation"][diagnostic_key] is False
                    ),
                    "removed_module_diagnostic_passed": (
                        evaluation["phase3_ablation"][diagnostic_key]
                        if evaluation
                        else None
                    ),
                }
            planned = new_planned

    return sorted(results, key=lambda row: (row["raw_arm"], row["baseline_rank"]))


def crowdout_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(row["classification"]) for row in rows)
    captured = counts["CAPTURED_SAME_EPISODE"]
    not_captured = len(rows) - captured
    finite = sum(bool(row["finite_capacity_crowdout"]) for row in rows)
    out = {
        "baseline_top20_captured_count": captured,
        "baseline_top20_not_captured_count": not_captured,
        "eligible_but_not_selected_count": counts["ELIGIBLE_BUT_OUTRANKED"]
        + counts["NO_VACANCY_AT_SIGNAL_DATE"]
        + counts["NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES"],
        "outranked_count": counts["ELIGIBLE_BUT_OUTRANKED"],
        "no_vacancy_count": counts["NO_VACANCY_AT_SIGNAL_DATE"]
        + counts["NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES"],
        "earlier_extra_entry_crowdout_count": counts[
            "NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES"
        ],
        "path_divergence_count": counts["PORTFOLIO_PATH_ALREADY_DIVERGED"],
        "other_count": not_captured
        - counts["ELIGIBLE_BUT_OUTRANKED"]
        - counts["NO_VACANCY_AT_SIGNAL_DATE"]
        - counts["NO_VACANCY_FROM_EARLIER_EXTRA_ENTRIES"]
        - counts["PORTFOLIO_PATH_ALREADY_DIVERGED"],
        "direct_finite_capacity_crowdout_count": finite,
        "direct_finite_capacity_share_of_missing": finite / not_captured,
        "classification_counts": dict(sorted(counts.items())),
    }
    if len(rows) != 20:
        raise RuntimeError("crowd-out analysis must cover exactly twenty frozen episodes")
    return out
