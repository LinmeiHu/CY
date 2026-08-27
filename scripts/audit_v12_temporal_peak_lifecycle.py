#!/usr/bin/env python3
"""Read-only five-symbol temporal-peak lifecycle audit.

This diagnostic replays only the governed five-symbol 2018--2020 sample.  It
does not write production artifacts and deliberately uses the unchanged V2
tracker implementation.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import build_real_chip_year as builder

from cyq_game.chip.daily_feature_fact import (
    _apply_peak_action,
    _canonical_peaks_from_json,
)
from cyq_game.chip.peaks import (
    CanonicalPeak,
    EnsembleTemporalPeakTracker,
    PeakTrackingResult,
    TrackedPeak,
    _canonical_match_score,
    _ensemble_candidates,
)
from cyq_game.chip.state_v2 import ChipSnapshotV2, SellerModel

SYMBOLS = (
    "000001.SZ",
    "002260.SZ",
    "002706.SZ",
    "300604.SZ",
    "600519.SH",
)
YEARS = (2018, 2019, 2020)


def _serialized_peak(peak: TrackedPeak | None) -> dict[str, Any] | None:
    if peak is None:
        return None
    return {
        "id": peak.peak_track_id,
        "age": peak.age,
        "center": peak.center_price,
        "band": list(peak.band),
        "mass": peak.mass,
        "ambiguity": peak.ambiguity,
        "split": peak.split,
        "merge": peak.merge,
        "lost": peak.lost,
    }


def _state(result: PeakTrackingResult) -> str:
    return result.fail_closed_reason or (
        "TRACKED" if result.tracked_base_peak is not None else "LOST"
    )


def _consensus_ambiguity_causes(
    candidates_by_model: Mapping[str, tuple[CanonicalPeak, ...]],
    models: tuple[str, ...],
) -> tuple[str, ...]:
    anchor_model = models[0]
    proposals: list[tuple[int, tuple[int, ...]]] = []
    causes: list[str] = []
    for anchor_index, anchor in enumerate(candidates_by_model[anchor_model]):
        selected = [anchor_index]
        for model in models[1:]:
            scored = sorted(
                (
                    (score, index)
                    for index, candidate in enumerate(candidates_by_model[model])
                    if (score := _canonical_match_score(anchor, candidate)) is not None
                ),
                reverse=True,
            )
            if not scored:
                causes.append(f"ANCHOR_{anchor_index}_UNMATCHED_IN_{model}")
                selected = []
                break
            if len(scored) > 1 and abs(scored[0][0] - scored[1][0]) <= 0.05:
                causes.append(f"ANCHOR_{anchor_index}_TIE_IN_{model}")
                selected = []
                break
            selected.append(scored[0][1])
        if selected:
            proposals.append((anchor_index, tuple(selected)))

    for model_offset in range(1, len(models)):
        counts = Counter(selected[model_offset] for _, selected in proposals)
        for candidate_index, count in sorted(counts.items()):
            if count > 1:
                causes.append(
                    f"NON_UNIQUE_{models[model_offset]}_CANDIDATE_{candidate_index}"
                )
    consensus, ambiguous = _ensemble_candidates(
        candidates_by_model, models, date.min
    )
    if ambiguous and len(consensus) != len(candidates_by_model[anchor_model]):
        causes.append(
            f"INCOMPLETE_ANCHOR_COVERAGE_{len(consensus)}_OF_"
            f"{len(candidates_by_model[anchor_model])}"
        )
    return tuple(dict.fromkeys(causes))


def _partition(stage_root: Path, kind: str, symbol: str) -> Path:
    matches = tuple(stage_root.glob(f"{kind}/bucket=*/symbol={symbol}"))
    if len(matches) != 1:
        raise ValueError(
            f"expected one {kind} partition for {symbol}, found {len(matches)}"
        )
    return matches[0]


def _raw_ensemble_base(
    tracker: EnsembleTemporalPeakTracker,
) -> TrackedPeak | None:
    base_track_id = tracker._ensemble._base_track_id
    return next(
        (
            peak
            for peak in tracker._ensemble._previous
            if peak.peak_track_id == base_track_id and not peak.ambiguity
        ),
        None,
    )


def _strict_invalid(record: Mapping[str, Any]) -> bool:
    ensemble = record["ensemble"]
    return bool(
        ensemble["base"] is None
        or record["events"]["split"]
        or record["events"]["merge"]
        or record["events"]["lost"]
    )


def _invalid_episodes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    start: int | None = None
    for index in range(len(records) + 1):
        invalid = index < len(records) and _strict_invalid(records[index])
        if invalid and start is None:
            start = index
        if invalid or start is None:
            continue
        rows = records[start:index]
        recovery = records[index] if index < len(records) else None
        born_ids = sorted(
            {
                track_id
                for row in rows
                for track_id in row["birth_ids"]
            }
        )
        episodes.append(
            {
                "start": rows[0]["date"],
                "end": rows[-1]["date"],
                "trading_days": len(rows),
                "calendar_days": (
                    date.fromisoformat(rows[-1]["date"])
                    - date.fromisoformat(rows[0]["date"])
                ).days
                + 1,
                "states": dict(Counter(row["ensemble"]["state"] for row in rows)),
                "ensemble_ambiguous_days": sum(
                    row["same_day_ensemble_ambiguous"] for row in rows
                ),
                "no_base_days": sum(row["ensemble"]["base"] is None for row in rows),
                "split_days": sum(row["events"]["split"] for row in rows),
                "merge_days": sum(row["events"]["merge"] for row in rows),
                "lost_days": sum(row["events"]["lost"] for row in rows),
                "new_track_ids": born_ids,
                "new_track_count": len(born_ids),
                "recovery_state": (
                    "NO_RECOVERY_IN_REPLAY"
                    if recovery is None
                    else recovery["ensemble"]["state"]
                ),
                "recovery_date": None if recovery is None else recovery["date"],
            }
        )
        start = None
    return episodes


def _first_date(records: list[dict[str, Any]], predicate: Any) -> str | None:
    return next((row["date"] for row in records if predicate(row)), None)


def _transition_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    labels: list[str] = []
    previous: str | None = None
    for record in records:
        label = record["ensemble"]["state"]
        if previous is not None and label != previous:
            labels.append(f"{previous}->{label}")
        previous = label
    return dict(Counter(labels))


def _summary(symbol: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    first_base_id = next(
        (
            row["tracker_base_id"]
            for row in records
            if row["tracker_base_id"] is not None
        ),
        None,
    )
    absorbed = next(
        (
            row["date"]
            for index, row in enumerate(records)
            if first_base_id is not None
            and row["tracker_base_id"] == first_base_id
            and first_base_id not in row["active_ensemble_ids"]
            and all(
                first_base_id not in later["active_ensemble_ids"]
                for later in records[index:]
            )
        ),
        None,
    )
    base_ids = sorted(
        {
            row["ensemble"]["base"]["id"]
            for row in records
            if row["ensemble"]["base"] is not None
        }
    )
    born_ids = sorted({track_id for row in records for track_id in row["birth_ids"]})
    later_born = tuple(track_id for track_id in born_ids if track_id != first_base_id)
    rows_2020 = [row for row in records if row["date"].startswith("2020-")]
    rows_2019 = [row for row in records if row["date"].startswith("2019-")]
    entering = rows_2019[-1] if rows_2019 else None
    return {
        "symbol": symbol,
        "rows": len(records),
        "coverage": {
            "tracked": sum(row["ensemble"]["base"] is not None for row in records),
            "strict_valid": sum(not _strict_invalid(row) for row in records),
            "2020_rows": len(rows_2020),
            "2020_tracked": sum(
                row["ensemble"]["base"] is not None for row in rows_2020
            ),
            "2020_strict_valid": sum(not _strict_invalid(row) for row in rows_2020),
        },
        "firsts": {
            "local_candidate": _first_date(
                records, lambda row: any(row["candidate_counts"].values())
            ),
            "consensus_candidate": _first_date(
                records, lambda row: row["consensus_candidate_count"] > 0
            ),
            "track_birth": _first_date(records, lambda row: bool(row["birth_ids"])),
            "valid_base": _first_date(
                records, lambda row: row["ensemble"]["base"] is not None
            ),
            "ambiguity": _first_date(
                records,
                lambda row: row["same_day_ensemble_ambiguous"]
                or any(peak["ambiguity"] for peak in row["ensemble"]["peaks"]),
            ),
            "split": _first_date(records, lambda row: row["events"]["split"]),
            "merge": _first_date(records, lambda row: row["events"]["merge"]),
            "lost": _first_date(records, lambda row: row["events"]["lost"]),
            "absorbing_base_loss": absorbed,
        },
        "track_birth_count": len(born_ids),
        "later_track_birth_count": len(later_born),
        "effective_base_ids": base_ids,
        "new_track_became_base": any(track_id in base_ids for track_id in later_born),
        "state_entering_2020": None
        if entering is None
        else {
            "date": entering["date"],
            "effective_state": entering["ensemble"]["state"],
            "tracker_base_id": entering["tracker_base_id"],
            "raw_base": entering["raw_ensemble_base"],
            "active_ensemble_ids": entering["active_ensemble_ids"],
            "active_ensemble_peaks": entering["active_ensemble_peaks"],
        },
        "state_counts": dict(Counter(row["ensemble"]["state"] for row in records)),
        "state_counts_2020": dict(
            Counter(row["ensemble"]["state"] for row in rows_2020)
        ),
        "transition_counts": _transition_counts(records),
        "transition_counts_2020": _transition_counts(rows_2020),
        "event_counts": {
            name: sum(row["events"][name] for row in records)
            for name in ("split", "merge", "lost")
        },
        "event_counts_2020": {
            name: sum(row["events"][name] for row in rows_2020)
            for name in ("split", "merge", "lost")
        },
        "invalid_episodes": _invalid_episodes(records),
    }


def _audit_symbol(stage_root: Path, symbol: str) -> dict[str, Any]:
    daily_rows = builder._read_symbol_partition(_partition(stage_root, "daily", symbol), symbol)
    minute_rows = builder._read_symbol_partition(
        _partition(stage_root, "minute", symbol), symbol
    )
    tracker = EnsembleTemporalPeakTracker(
        symbol=symbol, models=("uniform", "disposition", "active_sticky")
    )
    records: list[dict[str, Any]] = []
    terminal: dict[SellerModel, ChipSnapshotV2] | None = None

    for year in YEARS:
        year_daily = [
            row for row in daily_rows if builder._date(row["trade_date"]).year == year
        ]
        year_minute = [
            row for row in minute_rows if builder._date(row["trade_date"]).year == year
        ]

        def consume_day(
            fact: builder.ReplayableDayFact,
            model_rows: tuple[dict[str, Any], ...],
            _states: Mapping[SellerModel, ChipSnapshotV2 | builder.MutableChipState],
        ) -> None:
            day = fact.trading_date
            models = list(model_rows)
            candidates_by_model = {
                str(model["seller_model"]): (
                    ()
                    if model["canonical_peaks_json"] is None
                    else _canonical_peaks_from_json(
                        model["canonical_peaks_json"], expected_day=day
                    )
                )
                for model in models
            }
            _apply_peak_action(tracker, models, day)
            consensus, same_day_ambiguous = _ensemble_candidates(
                candidates_by_model, tracker._models, day
            )
            tracking = tracker.update(
                as_of=day, candidates_by_model=candidates_by_model
            )
            ensemble = tracking.ensemble
            active = tracker._ensemble._previous
            record = {
                "date": day.isoformat(),
                "candidate_counts": {
                    model: len(candidates_by_model[model]) for model in tracker._models
                },
                "candidate_centers": {
                    model: [peak.center_price for peak in candidates_by_model[model]]
                    for model in tracker._models
                },
                "consensus_candidate_count": len(consensus),
                "consensus_candidate_centers": [
                    peak.center_price for peak in consensus
                ],
                "same_day_ensemble_ambiguous": same_day_ambiguous,
                "ensemble_ambiguity_causes": _consensus_ambiguity_causes(
                    candidates_by_model, tracker._models
                ),
                "tracker_base_id": tracker._ensemble._base_track_id,
                "raw_ensemble_base": _serialized_peak(_raw_ensemble_base(tracker)),
                "active_ensemble_ids": [peak.peak_track_id for peak in active],
                "active_ensemble_peaks": [
                    _serialized_peak(peak) for peak in active
                ],
                "birth_ids": [
                    peak.peak_track_id
                    for peak in active
                    if peak.age == 1 and not peak.lost
                ],
                "events": {
                    "split": any(peak.split for peak in ensemble.peaks),
                    "merge": any(peak.merge for peak in ensemble.peaks),
                    "lost": any(peak.lost for peak in ensemble.peaks),
                },
                "ensemble": {
                    "state": _state(ensemble),
                    "base": _serialized_peak(ensemble.tracked_base_peak),
                    "dominant": _serialized_peak(ensemble.dominant_peak_today),
                    "peaks": [_serialized_peak(peak) for peak in ensemble.peaks],
                },
                "by_model": {
                    model: {
                        "state": _state(result),
                        "base": _serialized_peak(result.tracked_base_peak),
                        "dominant": _serialized_peak(result.dominant_peak_today),
                        "peaks": [_serialized_peak(peak) for peak in result.peaks],
                    }
                    for model, result in tracking.by_model.items()
                },
            }
            records.append(record)

        _, terminal = builder._run_symbol(
            symbol,
            year_daily,
            year_minute,
            year,
            None,
            initial_snapshots=terminal,
            replayable_day_facts=None,
            day_sink=consume_day,
        )

    return {"summary": _summary(symbol, records), "records": records}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "stage_root": str(args.stage_root),
        "symbols": {
            symbol: _audit_symbol(args.stage_root, symbol) for symbol in SYMBOLS
        },
    }
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                symbol: payload["summary"]
                for symbol, payload in result["symbols"].items()
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
