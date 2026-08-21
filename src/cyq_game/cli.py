from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from cyq_game.backtest import BacktestEngine, run_robustness_suite
from cyq_game.config import SystemConfig, load_config
from cyq_game.data import (
    CorporateActionRecord,
    DataAssetRegistry,
    DataExecutionAuthorization,
    DataOperation,
    DataPurpose,
    EventStore,
    FundamentalRecord,
    IndustryMembershipRecord,
    InputBinding,
    InputSnapshotManifest,
    MarketRuleRecord,
    PITBDailyStore,
    PITStore,
    read_fundamentals_csv,
    read_industry_memberships_csv,
    replay_state,
)
from cyq_game.data.demo import (
    generate_demo_csv,
    generate_demo_fundamentals_csv,
    generate_demo_industry_csv,
)
from cyq_game.data.pit import filter_date_range, read_bars_csv
from cyq_game.execution import (
    AccountSnapshot,
    IntendedAccountState,
    ShadowController,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-demo":
            return _generate_demo(args)
        if args.command == "build-pit":
            return _build_pit(args)
        if args.command == "data-status":
            return _data_status(args)
        if args.command == "backtest":
            return _backtest(args)
        if args.command == "robustness":
            return _robustness(args)
        if args.command == "replay":
            return _replay(args)
        if args.command == "shadow-reconcile":
            return _shadow_reconcile(args)
        if args.command == "kill-switch-status":
            return _kill_switch_status(args)
        if args.command == "kill-switch-reset":
            return _kill_switch_reset(args)
        parser.error("a command is required")
    except (FileNotFoundError, KeyError, ValueError) as error:
        print(
            json.dumps({"status": "ERROR", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cyq-game")
    subparsers = parser.add_subparsers(dest="command")

    demo = subparsers.add_parser("generate-demo", help="generate deterministic synthetic bars")
    demo.add_argument("--output", required=True)
    demo.add_argument("--start", type=date.fromisoformat, default=date(2023, 1, 2))
    demo.add_argument("--end", type=date.fromisoformat, default=date(2024, 12, 31))
    demo.add_argument("--seed", type=int, default=20260818)
    demo.add_argument("--industry-output", help="optional companion PIT membership CSV")
    demo.add_argument("--fundamental-output", help="optional companion PIT fundamentals CSV")

    build = subparsers.add_parser("build-pit", help="ingest immutable point-in-time data")
    build.add_argument("--input", help="daily bar CSV; must equal the bound daily_bars path")
    build.add_argument("--start", required=True, type=date.fromisoformat)
    build.add_argument("--end", required=True, type=date.fromisoformat)
    build.add_argument("--config", required=True)
    build.add_argument("--registry", default="configs/data_asset_registry.json")
    build.add_argument("--input-manifest", required=True)
    build.add_argument("--software-test", action="store_true")
    build.add_argument("--run-id")
    build.add_argument("--corporate-actions", help="optional corporate-action CSV")
    build.add_argument("--industry-memberships", help="optional PIT industry-membership CSV")
    build.add_argument("--fundamentals", help="optional PIT fundamental-disclosure CSV")
    build.add_argument("--market-rules", help="optional effective-dated market-rule CSV")

    data_status = subparsers.add_parser(
        "data-status", help="validate the data registry and an optional activation manifest"
    )
    data_status.add_argument("--registry", default="configs/data_asset_registry.json")
    data_status.add_argument("--input-manifest")

    backtest = subparsers.add_parser("backtest", help="run the CYQ game strategy")
    backtest.add_argument("--config", required=True)
    backtest.add_argument("--registry", default="configs/data_asset_registry.json")
    backtest.add_argument("--input-manifest", required=True)
    backtest.add_argument("--software-test", action="store_true")
    backtest.add_argument("--strategy", default="cyq_game_v5", choices=["cyq_game_v5"])
    backtest.add_argument(
        "--history-start",
        type=date.fromisoformat,
        help="optional pre-roll start; state updates before --start are excluded from evaluation",
    )
    backtest.add_argument("--start", type=date.fromisoformat)
    backtest.add_argument("--end", type=date.fromisoformat)
    backtest.add_argument(
        "--symbols",
        nargs="+",
        help="space-separated symbols to backtest (e.g. 000001 000002)",
    )
    backtest.add_argument(
        "--symbols-file",
        help="text file with one symbol per line to backtest",
    )
    backtest.add_argument("--run-id")
    backtest.add_argument("--walk-forward", action="store_true")
    holdout = backtest.add_mutually_exclusive_group()
    holdout.add_argument("--final-holdout-locked", action="store_true")
    holdout.add_argument("--access-final-holdout", action="store_true")

    robustness = subparsers.add_parser(
        "robustness",
        help="independently rerun the declared development-sample robustness matrix",
    )
    robustness.add_argument("--config", required=True)
    robustness.add_argument("--registry", default="configs/data_asset_registry.json")
    robustness.add_argument("--input-manifest", required=True)
    robustness.add_argument("--software-test", action="store_true")
    robustness.add_argument("--start", type=date.fromisoformat)
    robustness.add_argument("--end", type=date.fromisoformat)
    robustness.add_argument("--run-id")
    robustness.add_argument("--final-holdout-locked", action="store_true", required=True)

    replay = subparsers.add_parser("replay", help="verify and replay a completed run")
    replay.add_argument("--run-id", required=True)
    replay.add_argument("--config", default="configs/research.yaml")
    replay.add_argument("--deterministic", action="store_true")

    reconcile = subparsers.add_parser(
        "shadow-reconcile",
        help="compare a read-only account snapshot with a verified run state",
    )
    reconcile.add_argument("--config", default="configs/shadow.yaml")
    reconcile.add_argument("--run-id", required=True)
    reconcile.add_argument("--account-snapshot", required=True)
    reconcile.add_argument("--checked-at", type=datetime.fromisoformat)

    status = subparsers.add_parser(
        "kill-switch-status", help="show the durable shadow kill-switch state"
    )
    status.add_argument("--config", default="configs/shadow.yaml")
    status.add_argument("--run-id", required=True)

    reset = subparsers.add_parser(
        "kill-switch-reset", help="release an engaged switch with human approval evidence"
    )
    reset.add_argument("--config", default="configs/shadow.yaml")
    reset.add_argument("--run-id", required=True)
    reset.add_argument("--approval-id", required=True)
    reset.add_argument("--reason", required=True)
    reset.add_argument("--released-at", type=datetime.fromisoformat)
    return parser


def _generate_demo(args: argparse.Namespace) -> int:
    count = generate_demo_csv(
        args.output,
        start=args.start,
        end=args.end,
        seed=args.seed,
    )
    industry_rows = 0
    if args.industry_output:
        industry_rows = generate_demo_industry_csv(
            args.industry_output,
            effective_from=args.start,
        )
    fundamental_rows = 0
    if args.fundamental_output:
        fundamental_rows = generate_demo_fundamentals_csv(
            args.fundamental_output,
            start=args.start,
            end=args.end,
        )
    _print_json(
        {
            "status": "COMPLETE",
            "output": str(Path(args.output)),
            "rows": count,
            "industry_output": (str(Path(args.industry_output)) if args.industry_output else None),
            "industry_rows": industry_rows,
            "fundamental_output": (
                str(Path(args.fundamental_output)) if args.fundamental_output else None
            ),
            "fundamental_rows": fundamental_rows,
        }
    )
    return 0


def _build_pit(args: argparse.Namespace) -> int:
    registry, input_manifest = _active_data(args.registry, args.input_manifest)
    input_manifest.authorize(
        DataOperation.INGEST,
        registry=registry,
        software_test=args.software_test,
    )
    input_manifest.require_range(args.start, args.end, exact=True)
    supported_roles = {
        "daily_bars",
        "market_rules",
        "corporate_actions",
        "industry_memberships",
        "fundamentals",
    }
    unsupported_roles = set(input_manifest.bindings) - supported_roles
    if unsupported_roles:
        raise ValueError(
            "build-pit has no adapter for active roles: " + ", ".join(sorted(unsupported_roles))
        )

    cfg = load_config(args.config)
    bar_binding = input_manifest.binding("daily_bars")
    input_path = _selected_binding_path(bar_binding, args.input)
    if not input_path.is_file():
        raise ValueError("the current daily-bar adapter requires a bound CSV file")
    run_id = args.run_id or f"pit-{input_manifest.sha256[:16]}"
    bars = filter_date_range(
        read_bars_csv(input_path, require_available_at=True),
        args.start,
        args.end,
    )
    if not bars:
        raise ValueError("no bars fall inside the requested date range")

    # Parse and validate every bound source before mutating the PIT store. A
    # failed adapter therefore cannot leave a partially populated source store.
    if "market_rules" in input_manifest.bindings:
        rule_binding = input_manifest.binding("market_rules")
        rule_path = _selected_binding_path(rule_binding, args.market_rules)
        rules = _read_market_rules(rule_path, rule_binding, run_id)
    elif input_manifest.purpose is DataPurpose.SOFTWARE_TEST:
        if args.market_rules:
            raise ValueError("--market-rules is not bound by the input manifest")
        rules = _default_market_rules(run_id)
    else:
        raise ValueError("non-test PIT construction requires a bound market_rules asset")

    actions: list[CorporateActionRecord] = []
    if "corporate_actions" in input_manifest.bindings:
        action_binding = input_manifest.binding("corporate_actions")
        action_path = _selected_binding_path(action_binding, args.corporate_actions)
        actions = _read_corporate_actions(action_path, run_id, action_binding)
    elif args.corporate_actions:
        raise ValueError("--corporate-actions is not bound by the input manifest")

    industry_records: list[IndustryMembershipRecord] = []
    if "industry_memberships" in input_manifest.bindings:
        industry_binding = input_manifest.binding("industry_memberships")
        industry_path = _selected_binding_path(industry_binding, args.industry_memberships)
        industry_records = read_industry_memberships_csv(
            industry_path,
            run_id=run_id,
            snapshot_id=industry_binding.snapshot_id,
            default_source=industry_binding.source,
            enforce_identity=True,
        )
        if not industry_records:
            raise ValueError("bound industry-membership file contains no records")
    elif args.industry_memberships:
        raise ValueError("--industry-memberships is not bound by the input manifest")

    fundamental_records: list[FundamentalRecord] = []
    if "fundamentals" in input_manifest.bindings:
        fundamental_binding = input_manifest.binding("fundamentals")
        fundamental_path = _selected_binding_path(fundamental_binding, args.fundamentals)
        fundamental_records = read_fundamentals_csv(
            fundamental_path,
            run_id=run_id,
            snapshot_id=fundamental_binding.snapshot_id,
            default_source=fundamental_binding.source,
            enforce_identity=True,
        )
        if not fundamental_records:
            raise ValueError("bound fundamental file contains no records")
    elif args.fundamentals:
        raise ValueError("--fundamentals is not bound by the input manifest")

    store = PITStore(cfg.database_path)
    store.initialize()
    store.bind_input_manifest(
        registry_id=registry.registry_id,
        registry_sha256=registry.sha256,
        input_manifest_id=input_manifest.manifest_id,
        input_manifest_sha256=input_manifest.sha256,
        purpose=input_manifest.purpose.value,
        hard_valid=input_manifest.hard_valid,
        run_id=run_id,
        bound_at=datetime.now(UTC),
    )
    bars_inserted = store.ingest_bars(
        bars,
        source=bar_binding.source,
        snapshot_id=bar_binding.snapshot_id,
        run_id=run_id,
    )
    rules_inserted = store.ingest_market_rules(rules)
    actions_inserted = store.ingest_corporate_actions(actions)
    industry_rows_inserted = store.ingest_industry_memberships(industry_records)
    fundamental_rows_inserted = store.ingest_fundamentals(fundamental_records)
    identity = store.complete_input_manifest(
        input_manifest_id=input_manifest.manifest_id,
        input_manifest_sha256=input_manifest.sha256,
        completed_at=datetime.now(UTC),
    )
    manifest = {
        "run_id": run_id,
        "status": "COMPLETE",
        "purpose": input_manifest.purpose.value,
        "hard_valid": input_manifest.hard_valid,
        "scope": {
            "start": input_manifest.scope_start.isoformat(),
            "end": input_manifest.scope_end.isoformat(),
        },
        "registry_id": registry.registry_id,
        "registry_sha256": registry.sha256,
        "input_manifest_id": input_manifest.manifest_id,
        "input_manifest_sha256": input_manifest.sha256,
        "store_identity_status": identity.status,
        "source": bar_binding.source,
        "input": str(input_path.resolve()),
        "input_sha256": bar_binding.sha256,
        "snapshot_id": bar_binding.snapshot_id,
        "requested_start": args.start.isoformat(),
        "requested_end": args.end.isoformat(),
        "bar_rows_read": len(bars),
        "bar_rows_inserted": bars_inserted,
        "market_rules_inserted": rules_inserted,
        "corporate_actions_inserted": actions_inserted,
        "industry_memberships_inserted": industry_rows_inserted,
        "fundamentals_inserted": fundamental_rows_inserted,
        "database": str(cfg.database_path.resolve()),
    }
    manifest_dir = cfg.database_path.parent / "ingest_manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"{run_id}.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    _print_json({**manifest, "manifest": str(manifest_path)})
    return 0


def _backtest(args: argparse.Namespace) -> int:
    if not args.walk_forward:
        raise ValueError(
            "--walk-forward is required; single-split research is intentionally disabled"
        )
    cfg_path = Path(args.config)
    config_text = cfg_path.read_text(encoding="utf-8")
    cfg = load_config(cfg_path)
    registry, input_manifest = _active_data(args.registry, args.input_manifest)
    data_authorization = input_manifest.authorize(
        DataOperation.BACKTEST,
        registry=registry,
        software_test=args.software_test,
    )
    store = _strategy_store(cfg, input_manifest, data_authorization)
    try:
        store.initialize()
        store.require_input_manifest(
            registry_id=registry.registry_id,
            registry_sha256=registry.sha256,
            input_manifest_id=input_manifest.manifest_id,
            input_manifest_sha256=input_manifest.sha256,
        )
        first, last = store.date_bounds()
        start = args.start or first
        end = args.end or last
        history_start = args.history_start or start
        if history_start > start:
            raise ValueError("--history-start must not follow --start")
        input_manifest.require_range(history_start, end)
        if history_start < first or end > last:
            raise ValueError(f"requested range must be within PIT data bounds {first}..{last}")
        run_id = args.run_id or _new_run_id(config_text, cfg)
        requested_symbols = args.symbols or []
        if args.symbols_file:
            symbol_lines = Path(args.symbols_file).read_text(encoding="utf-8").splitlines()
            requested_symbols.extend(line.strip() for line in symbol_lines if line.strip())
        if not requested_symbols:
            symbols = None
        else:
            seen = set[str]()
            deduped_symbols = []
            for symbol in requested_symbols:
                if symbol in seen:
                    continue
                seen.add(symbol)
                deduped_symbols.append(symbol)
            symbols = deduped_symbols
            if not symbols:
                raise ValueError("no valid symbols provided")
        result = BacktestEngine(
            cfg,
            run_id=run_id,
            config_text=config_text,
            data_authorization=data_authorization,
            store=store,
        ).run(
            start,
            end,
            history_start=history_start,
            symbols=symbols,
            access_final_holdout=args.access_final_holdout,
        )
    finally:
        store.close()
    _print_json(
        {
            "status": "COMPLETE",
            "run_id": result.run_id,
            "run_dir": str(result.run_dir),
            "summary": str(result.summary_path),
            "event_digest": result.event_digest,
            "holdout_tainted": result.holdout_tainted,
            "metrics": result.metrics,
        }
    )
    return 0


def _robustness(args: argparse.Namespace) -> int:
    cfg_path = Path(args.config)
    config_text = cfg_path.read_text(encoding="utf-8")
    cfg = load_config(cfg_path)
    registry, input_manifest = _active_data(args.registry, args.input_manifest)
    data_authorization = input_manifest.authorize(
        DataOperation.ROBUSTNESS,
        registry=registry,
        software_test=args.software_test,
    )
    store = _strategy_store(cfg, input_manifest, data_authorization)
    try:
        store.initialize()
        store.require_input_manifest(
            registry_id=registry.registry_id,
            registry_sha256=registry.sha256,
            input_manifest_id=input_manifest.manifest_id,
            input_manifest_sha256=input_manifest.sha256,
        )
        first, last = store.date_bounds()
    finally:
        store.close()
    start = args.start or first
    end = args.end or last
    input_manifest.require_range(start, end)
    if start < first or end > last:
        raise ValueError(f"requested range must be within PIT data bounds {first}..{last}")
    suite_id = args.run_id or f"robustness-{_new_run_id(config_text, cfg)}"
    report_path, report = run_robustness_suite(
        cfg,
        suite_id=suite_id,
        start=start,
        end=end,
        data_authorization=data_authorization,
        store_factory=lambda effective_cfg: _strategy_store(
            effective_cfg,
            input_manifest,
            data_authorization,
        ),
    )
    _print_json(
        {
            "status": report["status"],
            "suite_id": suite_id,
            "report": str(report_path),
            "variant_count": report["variant_count"],
            "final_holdout_locked": True,
        }
    )
    return 0


def _replay(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    run_dir = _resolve_run_dir(cfg.run_dir, args.run_id)
    report, _state = _verify_run(run_dir, deterministic=args.deterministic)
    passed = report["status"] == "PASS"
    (run_dir / "replay_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    _print_json(report)
    return 0 if passed else 3


def _verify_run(
    run_dir: Path,
    *,
    deterministic: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    summary = _read_json_object(run_dir / "summary.json")
    manifest = _read_json_object(run_dir / "manifest.json")
    events = EventStore(run_dir / "events.jsonl")
    envelopes = events.read_all(verify=True)
    state = replay_state(envelopes)
    digest = events.digest()
    expected_event_summary = dict(summary)
    expected_event_summary.pop("event_digest", None)
    checks: dict[str, bool] = {
        "event_digest": digest == summary.get("event_digest") == manifest.get("event_digest"),
        "summary_state": state.get("summary") == expected_event_summary,
        "final_positions_present": isinstance(state.get("final_positions"), dict),
        "final_cash_present": isinstance(state.get("final_cash"), (float, int)),
        "run_id": summary.get("run_id") == run_dir.name,
    }
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("manifest artifacts must be a mapping")
    for filename, expected_digest in artifacts.items():
        artifact = run_dir / str(filename)
        checks[f"artifact:{filename}"] = (
            artifact.is_file() and _file_digest(artifact) == expected_digest
        )
    if deterministic:
        checks["sequence"] = all(
            item.sequence == index for index, item in enumerate(envelopes, start=1)
        )
        checks["unique_event_ids"] = len({item.event_id for item in envelopes}) == len(envelopes)
    passed = all(checks.values())
    report = {
        "status": "PASS" if passed else "FAIL",
        "run_id": run_dir.name,
        "events": len(envelopes),
        "event_digest": digest,
        "checks": checks,
        "final_cash": state.get("final_cash"),
        "final_positions": state.get("final_positions"),
    }
    return report, state


def _shadow_reconcile(args: argparse.Namespace) -> int:
    cfg = _shadow_config(args.config)
    run_dir = _resolve_run_dir(cfg.run_dir, args.run_id)
    verification, state = _verify_run(run_dir, deterministic=True)
    if verification["status"] != "PASS":
        raise ValueError("source run failed deterministic integrity verification")
    intended = IntendedAccountState(
        run_id=run_dir.name,
        cash=_required_number(state, "final_cash"),
        positions=_required_quantities(state, "final_positions"),
        available_quantities=_required_quantities(state, "final_available_quantities"),
    )
    actual = AccountSnapshot.from_file(args.account_snapshot)
    checked_at = args.checked_at or datetime.now(UTC)
    controller = ShadowController(cfg.run_dir / "shadow", run_dir.name)
    result, switch, report_path = controller.reconcile(
        intended,
        actual,
        checked_at=checked_at,
        cash_tolerance=cfg.shadow.cash_tolerance,
        quantity_tolerance=cfg.shadow.quantity_tolerance,
        max_snapshot_age_seconds=cfg.shadow.max_snapshot_age_seconds,
    )
    passed = result.passed and not switch.engaged
    status = "PASS" if passed else "RECONCILED_BUT_KILL_SWITCH_ENGAGED" if result.passed else "FAIL"
    _print_json(
        {
            "status": status,
            "run_id": run_dir.name,
            "source_run_verified": True,
            "order_transmission_enabled": False,
            "report": str(report_path),
            "reconciliation": result.to_dict(),
            "effective_kill_switch": switch.to_dict(),
        }
    )
    return 0 if passed else 4


def _kill_switch_status(args: argparse.Namespace) -> int:
    cfg = _shadow_config(args.config)
    run_dir = _resolve_run_dir(cfg.run_dir, args.run_id)
    switch = ShadowController(cfg.run_dir / "shadow", run_dir.name).status()
    _print_json(
        {
            "status": "ENGAGED" if switch.engaged else "CLEAR",
            "run_id": run_dir.name,
            "order_transmission_enabled": False,
            "kill_switch": switch.to_dict(),
        }
    )
    return 4 if switch.engaged else 0


def _kill_switch_reset(args: argparse.Namespace) -> int:
    cfg = _shadow_config(args.config)
    run_dir = _resolve_run_dir(cfg.run_dir, args.run_id)
    controller = ShadowController(cfg.run_dir / "shadow", run_dir.name)
    state = controller.release(
        approval_id=args.approval_id,
        reason=args.reason,
        released_at=args.released_at or datetime.now(UTC),
    )
    _print_json(
        {
            "status": "RELEASED",
            "run_id": run_dir.name,
            "order_transmission_enabled": False,
            "kill_switch": state.to_dict(),
        }
    )
    return 0


def _active_data(
    registry_path: str | Path,
    input_manifest_path: str | Path,
) -> tuple[DataAssetRegistry, InputSnapshotManifest]:
    registry = DataAssetRegistry.load(registry_path)
    manifest = InputSnapshotManifest.load(input_manifest_path, registry=registry)
    return registry, manifest


def _strategy_store(
    config: SystemConfig,
    input_manifest: InputSnapshotManifest,
    authorization: DataExecutionAuthorization,
) -> PITStore:
    binding = input_manifest.bindings.get("daily_pit_b")
    if binding is None:
        dependent_roles = {"minute_pit_b", "chip_state_features"} & set(
            input_manifest.bindings
        )
        if dependent_roles:
            raise ValueError(
                ", ".join(sorted(dependent_roles))
                + " requires the daily_pit_b runtime input"
            )
        return PITStore(config.database_path)
    supported_roles = {"daily_pit_b", "minute_pit_b", "chip_state_features"}
    unsupported = set(input_manifest.bindings) - supported_roles
    if unsupported:
        raise ValueError(
            "unsupported strategy-runtime input bindings: " + ", ".join(sorted(unsupported))
        )
    metadata_path = (
        config.database_path.parent
        / "runtime_metadata"
        / f"pit-b-{input_manifest.sha256[:16]}.sqlite3"
    )
    return PITBDailyStore(
        metadata_path,
        binding=binding,
        minute_binding=input_manifest.bindings.get("minute_pit_b"),
        chip_feature_binding=input_manifest.bindings.get("chip_state_features"),
        authorization=authorization,
    )


def _selected_binding_path(binding: InputBinding, supplied: str | None) -> Path:
    if supplied is None:
        return binding.path
    candidate = Path(supplied).expanduser().resolve()
    if candidate != binding.path:
        raise ValueError(
            f"supplied path for role {binding.role} does not match the active manifest: "
            f"{candidate} != {binding.path}"
        )
    return candidate


def _data_status(args: argparse.Namespace) -> int:
    registry = DataAssetRegistry.load(args.registry)
    payload: dict[str, Any] = {
        "status": "PASS",
        "registry": str(registry.path),
        "registry_id": registry.registry_id,
        "registry_sha256": registry.sha256,
        "global_gate": registry.global_gate,
        "asset_count": len(registry.assets),
    }
    if args.input_manifest:
        manifest = InputSnapshotManifest.load(args.input_manifest, registry=registry)
        payload["input_manifest"] = {
            "path": str(manifest.path),
            "manifest_id": manifest.manifest_id,
            "sha256": manifest.sha256,
            "purpose": manifest.purpose.value,
            "hard_valid": manifest.hard_valid,
            "scope": {
                "start": manifest.scope_start.isoformat(),
                "end": manifest.scope_end.isoformat(),
            },
            "bindings": {
                role: {
                    "asset_id": binding.asset.asset_id,
                    "path": str(binding.path),
                    "source": binding.source,
                    "snapshot_id": binding.snapshot_id,
                }
                for role, binding in sorted(manifest.bindings.items())
            },
            "audits": {
                name: {
                    "status": audit.status,
                    "evidence": audit.evidence,
                }
                for name, audit in sorted(manifest.audits.items())
            },
        }
    _print_json(payload)
    return 0


def _default_market_rules(run_id: str) -> list[MarketRuleRecord]:
    def record(
        rule_id: str,
        board: str,
        limit: float,
        effective_from: date,
        effective_to: date | None = None,
    ) -> MarketRuleRecord:
        announced = datetime.combine(effective_from, time(0), tzinfo=UTC)
        return MarketRuleRecord(
            rule_id=rule_id,
            board=board,
            security_pattern="*",
            price_limit_pct=limit,
            t_plus_one=True,
            lot_size=100,
            effective_from=effective_from,
            effective_to=effective_to,
            available_at=announced,
            source="software-test-effective-dated-market-rules-v1",
            snapshot_id="software-test-rules-v1",
            revision_id="1",
            run_id=run_id,
        )

    return [
        record("MAIN-10", "MAIN", 0.10, date(1990, 12, 19)),
        record("CHINEXT-10", "CHINEXT", 0.10, date(2009, 10, 30), date(2020, 8, 23)),
        record("CHINEXT-20", "CHINEXT", 0.20, date(2020, 8, 24)),
        record("STAR-20", "STAR", 0.20, date(2019, 7, 22)),
        record("BSE-30", "BSE", 0.30, date(2021, 11, 15)),
    ]


def _read_market_rules(
    path: Path,
    binding: InputBinding,
    run_id: str,
) -> list[MarketRuleRecord]:
    if not path.is_file():
        raise ValueError("the current market-rule adapter requires a bound CSV file")
    result: list[MarketRuleRecord] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, raw in enumerate(csv.DictReader(handle), start=2):
            try:
                effective_from = date.fromisoformat(raw["effective_from"])
                effective_to = (
                    date.fromisoformat(raw["effective_to"]) if raw.get("effective_to") else None
                )
                if effective_to is not None and effective_to < effective_from:
                    raise ValueError("effective_to precedes effective_from")
                if not raw.get("available_at"):
                    raise ValueError("available_at is required")
                available_at = _aware_datetime(raw["available_at"], effective_from, time(0))
                if available_at.astimezone(UTC).date() > effective_from:
                    raise ValueError("rule was not available by effective_from")
                _require_bound_row_identity(raw, binding, "market-rule")
                result.append(
                    MarketRuleRecord(
                        rule_id=raw["rule_id"],
                        board=raw["board"],
                        security_pattern=raw.get("security_pattern") or "*",
                        price_limit_pct=_optional_float(raw.get("price_limit_pct")),
                        t_plus_one=_parse_bool(raw.get("t_plus_one"), "t_plus_one"),
                        lot_size=int(raw["lot_size"]),
                        effective_from=effective_from,
                        effective_to=effective_to,
                        available_at=available_at,
                        source=binding.source,
                        snapshot_id=binding.snapshot_id,
                        revision_id=raw.get("revision_id") or "1",
                        run_id=run_id,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid market-rule row {row_number}: {exc}") from exc
    if not result:
        raise ValueError("bound market-rule file contains no records")
    return result


def _read_corporate_actions(
    path: Path,
    run_id: str,
    binding: InputBinding,
) -> list[CorporateActionRecord]:
    if not path.is_file():
        raise ValueError("the current corporate-action adapter requires a bound CSV file")
    result: list[CorporateActionRecord] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row_number, raw in enumerate(csv.DictReader(handle), start=2):
            try:
                ex_date = date.fromisoformat(raw["ex_date"])
                if not raw.get("event_time") or not raw.get("available_at"):
                    raise ValueError("event_time and available_at are required")
                event_time = _aware_datetime(raw["event_time"], ex_date, time(0))
                available_at = _aware_datetime(raw["available_at"], ex_date, time(0))
                if event_time > available_at:
                    raise ValueError("event_time follows available_at")
                if available_at.astimezone(UTC).date() > ex_date:
                    raise ValueError("action was not available by ex_date")
                _require_bound_row_identity(raw, binding, "corporate-action")
                result.append(
                    CorporateActionRecord(
                        action_id=raw["action_id"],
                        symbol=raw["symbol"],
                        action_type=raw["action_type"],
                        ex_date=ex_date,
                        ratio=_optional_float(raw.get("ratio")),
                        cash_per_share=_optional_float(raw.get("cash_per_share")),
                        issue_price=_optional_float(raw.get("issue_price")),
                        shares=_optional_float(raw.get("shares")),
                        event_time=event_time,
                        available_at=available_at,
                        effective_from=datetime.combine(ex_date, time(0), tzinfo=UTC),
                        source=binding.source,
                        snapshot_id=binding.snapshot_id,
                        revision_id=raw.get("revision_id") or "1",
                        run_id=run_id,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid corporate-action row {row_number}: {exc}") from exc
    return result


def _require_bound_row_identity(
    row: dict[str, str | None],
    binding: InputBinding,
    label: str,
) -> None:
    source = row.get("source")
    snapshot_id = row.get("snapshot_id")
    if source and source != binding.source:
        raise ValueError(f"{label} source differs from active binding")
    if snapshot_id and snapshot_id != binding.snapshot_id:
        raise ValueError(f"{label} snapshot_id differs from active binding")


def _aware_datetime(value: str | None, fallback_date: date, fallback_time: time) -> datetime:
    parsed = (
        datetime.fromisoformat(value)
        if value
        else datetime.combine(fallback_date, fallback_time, tzinfo=UTC)
    )
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _optional_float(value: object) -> float | None:
    return None if value in {None, ""} else float(str(value))


def _parse_bool(value: object, field: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ValueError(f"{field} must be a boolean")


def _shadow_config(path: str | Path) -> SystemConfig:
    cfg = load_config(path)
    if cfg.mode != "shadow":
        raise ValueError("shadow commands require a configuration with mode: shadow")
    return cfg


def _required_number(state: dict[str, Any], key: str) -> float:
    value = state.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"verified run state is missing numeric {key}")
    return float(value)


def _required_quantities(state: dict[str, Any], key: str) -> dict[str, int]:
    value = state.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"verified run state is missing quantity mapping {key}")
    result: dict[str, int] = {}
    for symbol, quantity in value.items():
        if isinstance(quantity, bool) or not isinstance(quantity, int | float):
            raise ValueError(f"{key}.{symbol} must be an integer")
        parsed = float(quantity)
        if parsed < 0 or not parsed.is_integer():
            raise ValueError(f"{key}.{symbol} must be a non-negative integer")
        result[str(symbol)] = int(parsed)
    return result


def _resolve_run_dir(root: Path, run_id: str) -> Path:
    if run_id != "latest":
        candidate = root / run_id
        if not candidate.is_dir():
            raise FileNotFoundError(f"run not found: {candidate}")
        return candidate
    candidates = [
        path for path in root.iterdir() if path.is_dir() and (path / "summary.json").is_file()
    ]
    if not candidates:
        raise FileNotFoundError(f"no completed runs beneath {root}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _new_run_id(config_text: str, cfg: SystemConfig) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{config_text}|{cfg.seed}".encode()).hexdigest()[:8]
    return f"cyq-game-v5-{stamp}-{digest}"


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
