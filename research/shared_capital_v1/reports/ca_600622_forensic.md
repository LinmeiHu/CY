# 600622 公司行动取证 V0.6

CORPORATE_ACTION_600622_STATUS = CORPORATE_ACTION_STATE_UNRESOLVED
ATRDR_CORPORATE_ACTION_DATA_STATUS = DATA_INPUT_MISSING

官方现有原始响应 p_sysapi1139 的 F025D 就是 null。它经封存生产代码映射到「股份到账日」，再成为 normalized/distributions.parquet.share_credit_date；不存在归一化漏取非空日期的证据。

2016 年报实施方案：2017-06-23 公告，2017-06-29 登记，2017-06-30 除权及派息，每 10 股转增 3 股、派 2.1 元。known_at 为 2017-06-24，含义为日期精度公告次日，并非抓取时刻。股份会计生效、到账、上市可交易的独立字段均未被证据解决，派息日也不是券商现金入账时刻。

精确缺失：该事件 F025D / share_credit_date，以及可验证的 tradable_date 或与到账绑定的冻结可交易状态规则。原始响应没有分红股份 listing 字段；rights_listing_date 属于配股另一事件类型，不能移用。登记权利可计量，不足以宣布新增股已到账可卖。不能以价格、收益对账或除权日反推。

证据层级 A：官方响应、raw、normalized 均未提供到账状态。B：已消费 daily 在除权日 corporate_action_valid=False、invalid_step_cum 改变，是阻塞标记而非到账转换。C：initial_state_v05 明确禁止推定；冻结执行路径只有坐标变化后阻塞，没有唯一到账规则。结论 D：保持未解决。

查询范围为当前 input config/manifest 注册 distributions、rights、daily 及该 vintage manifest 指向的原始响应、receipt、封存 producer；当前 Git 的 schema/producer 历史查询结果在 ca_schema_history.txt。既有 IFCGR 路由是公告目录及标题，不含该事件股份账户可交易状态，不把目录当执行证据。未联网、未新购数据、未运行其他工作树代码。

同样独立核实 603368.SH / 2020-06-24（MCB）与 600195.SH / 2019-07-16（ATRDR 重置诊断）F025D 也为空。MCB 的连续阻塞不依赖 ATRDR，因此不能如实填 CAUSALLY_VALIDATED。

来源：/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5/normalized/distributions.parquet
封存生产代码：/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5/lineage/fetch_crsp_lean_cninfo_corporate_actions_v1.py
所有本次取证文件真实 SHA256 见 ca_forensic_input_hashes.csv，逐层日期、知识时点和处理见 ca_600622_forensic.csv。

补充核对：ca_600622_daily_lineage.csv 保存已注册历史 daily 在事件前后的状态与源哈希；ca_600622_rights_search.csv 记录同日期配股事件检索，配股上市字段不被移用于该分红转增事件。ca_600622_registered_title_search.csv 另记录三条已注册官方公告标题源中的该证券检索。
