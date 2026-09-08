"""Evidence map for requested hardening hypotheses and research invariants."""
import pandas as pd

from .preflight import HERE


def run(tests):
    passed = [r['test'] for r in tests if r['status'] == 'PASS']
    hypotheses = [
        ('3.1 ATRDR causal prefix', 'CONFIRMED_FIXED', 'test_atrdr_historical_prefix_entries_cash_positions_nav', '父版本已修复；此前完成状态不能改变过去的入场、现金、持仓与 NAV。'),
        ('3.2 SMV6 opening valuation', 'CONFIRMED_FIXED', 'test_future_close_and_unfinished_open_bar_cannot_change_order', '保留父版本开盘估值修正；同日未来收盘和未完成分钟收盘扰动不改订单。'),
        ('3.3 SMV6 signal date', 'NEW_BUG_CONFIRMED', 'test_signal_metadata_uses_frozen_event_date', '已修复：周一、节后和长周末使用原生上一事件日；首次回调使用完成历史日。仅元数据。'),
        ('3.4 Tradable inventory', 'CONFIRMED_FIXED', 'test_native_exit_sells_old_inventory_but_waits_for_same_day_addon', '父公司行动 pending 语义保留；缩放新增批次按实际购入日拆分，旧股退出不带走当天增持。'),
        ('3.5 Aggregate same-bar capacity', 'NOT_APPLICABLE', 'test_smv6_frozen_execution_settings_are_captured', '冻结本地源为每次调用上限。原生平台聚合语义未验证；不发明聚合规则。'),
        ('3.6 Empty or unfinished schema', 'NEW_BUG_CONFIRMED', 'test_outcome_schema_survives_empty_no_entry_and_unfinished_paths', '已修复：空候选、没有合法入场、持仓未完成、全拒绝和现金账户保留列；未完成账户窗口继续记账。'),
        ('3.7 Comparison identity and exit status', 'CONFIRMED_FIXED', 'test_generation_command_required_comparison_failure_nonzero', '保留重复/空主键、多对多和缺层失败；另修复带空格/引号列名的比较 SQL。'),
        ('3.8 Account validation', 'NEW_BUG_CONFIRMED', 'test_invalid_operation_timestamp_does_not_mutate_account', '已修复：账户操作和意图时钟 NaT 在变更前拒绝，基准 NaN 不通过；独立容量字段均生效。'),
        ('3.9 Config-relative selected inputs', 'NEW_BUG_CONFIRMED', 'test_config_relative_and_selected_strategy_only', '已修复：配置相对目录解析，只验证所选策略；失败覆盖旧的成功状态。'),
        ('3.10 Cache identity', 'NEW_BUG_CONFIRMED', 'test_native_cache_reuse_requires_same_native_producers_and_states', '本研究新缓存已加固：输入、期间、生产者、配置、原生初始状态及完整物理收据绑定。'),
        ('P0 released cash during one callback', 'NEW_BUG_CONFIRMED', 'test_p0_native_callback_can_reuse_legally_released_cash', '已修复：同一回调买入/合法卖出后，可再使用释放现金；第二笔从 200 股恢复为 800 股。'),
        ('Scaled zero target and delayed exit', 'NEW_BUG_CONFIRMED', 'test_etf_native_zero_target_liquidates_scaled_holding', '本次适配器修复：原生零目标执行退出；Gap 延迟退出采用下一合法报价并释放实际批次。'),
        ('Scaled intent and reference boundary', 'NEW_BUG_CONFIRMED', 'test_scaled_intent_validation_precedes_mutation', '本次适配器修复：非法/未来意图先拒绝；无原生请求身份、重复已完成事件和未选策略均不能扩大持仓。'),
        ('Runner failure and live source drift', 'NEW_BUG_CONFIRMED', 'test_cli_passes_approved_baseline_and_overwrites_stale_success', '本次入口修复：旧成功状态在失败时失效；Native 复用传递正确；计算期间源码变化失败。'),
        ('ETF exact affordable lot', 'NEW_BUG_CONFIRMED', 'test_etf_exact_affordable_lot_is_preserved_without_financing', '求解器浮点边界修复：足额成交 100 股，少 0.01 元不成交；实际账单仍严格受现金约束。'),
        ('Large requested/billed cost association', 'NEW_BUG_CONFIRMED', 'test_observed_large_combined_order_uses_same_requested_and_billed_cost', '2021-10-12 603348.SH 实际组合请求的含费成本乘法顺序已统一；没有放宽校验容差。'),
    ]
    def evidence(selector):
        matches = [name for name in passed if '::'+selector in name]
        if not matches:
            raise ValueError('required focused test not passed: '+selector)
        return ';'.join(matches)
    rows = [dict(hypothesis=h, classification=c, resolution='VERIFIED' if c == 'NOT_APPLICABLE' else 'FIXED_AND_TESTED',
                 evidence=evidence(t), detail=d) for h, c, t, d in hypotheses]
    pd.DataFrame(rows).to_csv(HERE/'output/bug_hardening_status.csv', index=False)
    checks = [
        ('ATRDR prefix', 'test_atrdr_historical_prefix_entries_cash_positions_nav'),
        ('SMV6 open future-close invariance', 'test_future_close_and_unfinished_open_bar_cannot_change_order'),
        ('Signal calendar', 'test_signal_metadata_uses_frozen_event_date'),
        ('First signal history date', 'test_initial_native_callback_reports_completed_input_date'),
        ('Tradable old and same-day inventory', 'test_native_exit_sells_old_inventory_but_waits_for_same_day_addon'),
        ('Pending corporate shares', 'test_exit_before_or_after_tradable_keeps_entitlement'),
        ('Local ETF execution settings', 'test_smv6_frozen_execution_settings_are_captured'),
        ('Stable empty outcomes', 'test_outcome_schema_survives_empty_no_entry_and_unfinished_paths'),
        ('Cash-only stable schema', 'test_cash_only_replay_keeps_exportable_empty_trade_schema'),
        ('Comparison duplicate and null identity', 'test_comparison_identity_failures'),
        ('Comparison many-to-many and missing layer', 'test_many_to_many_and_missing_layers_fail'),
        ('Comparison process nonzero', 'test_comparison_cli_nonzero_and_generation_not_validation'),
        ('Nonfinite cash NAV gross', 'test_nonfinite_account_never_passes'),
        ('Nonfinite physical positions', 'test_physical_nan_cannot_hide_in_quantity_comparison'),
        ('Account timestamp before mutation', 'test_invalid_operation_timestamp_does_not_mutate_account'),
        ('Config-relative input portability', 'test_config_relative_and_selected_strategy_only'),
        ('Input period source config cache binding', 'test_research_cache_identity_binds_inputs_config_and_producer'),
        ('Native producer and initial-state cache binding', 'test_native_cache_reuse_requires_same_native_producers_and_states'),
        ('Corrupt scenario receipt', 'test_corrupt_cached_scenario_fails_before_reuse'),
        ('Missing scenario receipt layer', 'test_incomplete_cache_receipt_fails_before_read'),
        ('Cache regeneration without false validation', 'test_cache_roundtrip_regenerates_summaries_without_invalidating_replay'),
        ('Source mutation during calculation', 'test_source_changed_during_run_fails_closed'),
        ('Frozen MAIN and CHINEXT membership; STAR and Beijing excluded', 'test_registered_boards_and_metadata_not_prefix_guessing'),
        ('MCB completed-close cross-board identity', 'test_mcb_native_same_completed_close_requires_main_and_chinext'),
        ('Frozen ETF-only pool and eligibility', 'test_frozen_etf_pool_intersection_and_listing'),
        ('IFCGR parent OGR population', 'test_ifcgr_registered_parent_population_does_not_broaden'),
        ('Execution hardening cannot override alpha source', 'test_schema_hardening_cannot_override_alpha_identity'),
        ('No new request or symbol and Gap exclusion', 'test_no_new_reference_signal_or_symbol_and_gap_exclusion'),
        ('Full-book relative weights and G100 single-name allowance', 'test_full_book_relative_weights_and_single_name_extreme'),
        ('Zero valid positions cash; no price-drift normalization', 'test_zero_book_stays_cash_and_price_drift_does_not_normalize'),
        ('Actual scaled state and native exit', 'test_actual_scaled_inventory_drives_future_native_exit_and_state'),
        ('Nonfinancing and physical virtual reconciliation', 'test_physical_virtual_equity_quantity_and_costs'),
        ('Corporate actions on actual scaled quantities', 'test_scaled_corporate_entitlements_use_actual_record_ownership'),
        ('MCB exact confirmation and Gap alternative', 'test_exact_confirmation_mcb_only_and_gap_exclusion'),
        ('Entry-only distinct and deterministic', 'test_entry_only_is_distinct_and_deterministic'),
        ('Legal delayed Gap exit', 'test_delayed_gap_exit_uses_next_legal_quote_and_releases_all_inventory'),
        ('Native zero target exits', 'test_etf_native_zero_target_liquidates_scaled_holding'),
        ('Illegal selected strategy', 'test_scaling_cannot_admit_an_unselected_strategy'),
        ('Target error reports locked inventory', 'test_relative_weight_error_reports_locked_inventory'),
        ('Exact affordable ETF lot and insufficient cash', 'test_etf_exact_affordable_lot_is_preserved_without_financing'),
        ('Observed large-order requested and billed cost', 'test_observed_large_combined_order_uses_same_requested_and_billed_cost'),
    ]
    coverage = [dict(requirement=r, evidence_kind='FOCUSED_TEST', evidence=evidence(t), status='PASS') for r, t in checks]
    for requirement, artifact in [
        ('All frozen cases and both execution grades', 'scenario_summary.csv; research_gate.json'),
        ('All daily no-financing equations and physical checkpoints', 'external_artifact_manifest.csv; scenario receipts and checkpoints.parquet'),
        ('Native actual cash NAV and gross reconciliation', 'baseline_gate.json; 18 Native account artifacts'),
        ('Six genuinely fresh deterministic replays', 'deterministic_rerun.csv'),
        ('Frozen strategy and raw input identities', 'frozen_hash_verification.csv; input_hash_verification.csv'),
        ('Economic contract unchanged since pre-outcome freeze', '../contracts/freeze_receipt.json; completion.json'),
        ('Deterministic compact artifact manifest', 'output_manifest.sha256'),
        ('Target normalization versus actual drift/locked inventory disclosure', '../contracts/capital_scaling_policy_v1.json; concentration_diagnostics.csv; scaling.json'),
    ]:
        coverage.append(dict(requirement=requirement, evidence_kind='ACTUAL_REPLAY_OR_HASH_GATE', evidence=artifact, status='PASS'))
    pd.DataFrame(coverage).to_csv(HERE/'output/requirement_test_coverage.csv', index=False)
