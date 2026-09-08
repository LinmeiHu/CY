# 代码精简审查

审查在全部 132 个实际账户场景完成后进行。仅精简本次派生统计、绘图和收尾入口；物理账户生产者仍为 `ec3ca1bc3c61b7a23bae252af91b5a23620b0efef66e38a3d5efd705d2c50925`，经济契约保持首次结果前的哈希。没有重构冻结 alpha，也没有删除历史研究证据。

| issue | file | action | reason | behavioral risk | changed/not changed |
| --- | --- | --- | --- | --- | --- |
| 绘图在 import 时读取命令行并写图 | plot.py | 将运行体与 backend/rc 设置移入 main，加入 main guard | 模块导入不再要求 argv 或生成文件 | 仅 CLI 启动位置变化；复跑并视觉检查图表 | CHANGED |
| SVG 包含日期与随机对象 ID | plot.py | 固定 svg.hashsalt，移除 SVG Date；保留数值与布局 | 同一环境重新渲染可比较原始图文件哈希 | 不改变科学数据；重复渲染验证 | CHANGED |
| 已不使用的循环变量与局部 JSON 解析 | plot.py; metrics.py | 删除 enumerate 索引及 npnl/ppnl 局部变量 | 峰谷归因已经使用真实资金袖 NAV，旧解析没有参与计算 | 无账户行为变化；派生表重建核对 | CHANGED |
| 派生入口的无用 import | contract.py; report.py; finalize.py | 删除 Path/json/ROOT 无用导入 | 缩小误导性的模块依赖 | 冻结 JSON 与物理生产者不受影响 | CHANGED |
| 物理生产者中两处无用 import | data.py ROOT; scaling.py json | 本轮保留并明列 | 它们没有行为作用；保留已计算物理账户的精确源码身份 | 不改变当前行为；静态关键错误检查不把它们当功能缺陷 | NOT CHANGED |
| 重复账户算术与虚拟批次对账 | shared_account/engine.py; scaling.py | 确认统一 fill/close/checkpoint；请求与账单成本已在实际 bug 修复阶段统一 | 缩放器负责目标股数，底层账户负责扣款与物理对账，职责不同 | 不合并经济职责不同的函数 | NOT CHANGED AFTER RESULTS |
| 公司行动看似重复 | shared_account/held_actions.py; stock_p0.py; gap_p0.py; smv6_physical.py | 保留已有原始股数权益服务与 ETF 本地调整单位边界 | 原始股票权益和 ETF 本地价格单位不能简单合并 | 合并会危及冻结经济语义 | NOT CHANGED |
| 指标与结果验证重复 | metrics.py; run.py; finalize.py | 复用父 metrics；复用 verify_case_receipt；保留各层不同门禁 | Native 数值对账、完整物理收据、时钟检查、最终实际文件哈希分别防止不同错误 | 不删除看似重复但覆盖边界不同的校验 | NOT CHANGED AFTER RESULTS |
| 旧入口仍可能被误认为正式入口 | REPRODUCTION_COMMANDS.md | 标记 LEGACY_DO_NOT_USE_FOR_CURRENT_RESULTS，明确当前唯一资本入口 | 保留 V0/V05/V06 与父封存证据的历史用途 | 只改说明，不删除历史文件 | CHANGED DOCUMENTATION |
| 硬编码路径与缓存归属 | preflight.py; data.py; REPRODUCTION_COMMANDS.md | 保留用户指定真实外盘，文档列出父缓存只读连接、当前 engine 根和新重算根 | 这是登记数据身份和真实挂载约束；通用配置相对路径已在 io.py 修复 | 不用任意同名目录替代登记外盘；不迁移父缓存 | DOCUMENTED |
| 星号导入与新增死 helper | 当前资本模块、共同调度器、账户与验证器 | 定向搜索未发现新增星号导入；未发现需要删除的新增死 helper | 保留封存策略内部结构 | 不扩大清理范围 | NOT CHANGED |
| 冻结平台注入符号的静态识别 | src/five_strategy_bundle/strategies/smv6_frozen.py | 将原生平台注入的 85 处静态引用单列；关键静态检查排除此冻结文件 | set_benchmark/log 等由平台适配器注入，Native 真实回放已覆盖该路径 | 不为静态工具重写冻结平台代码 | NOT CHANGED |

完成门禁要求精简后全工程测试、六个新目录实际重放的 42 个物理文件哈希、全部派生结果重建及图表重复渲染通过。最终证据见 output/test_results.json、deterministic_rerun.csv、plot_determinism.csv、derived_output_determinism.csv 和 output_manifest.sha256。XML 运行时间和新重算目录名属于执行出处；不把这类运行元数据等同于经济输出的不确定性。
