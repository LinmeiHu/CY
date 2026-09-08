# 资本缩放与结构闲置研究复跑

运行目录为 `/Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1`，目标分支为 `research/five-strategy-capital-scaling-v1`。父基准为 `research/five-strategy-shared-capital-v1` / `7fc40594377c3ec11148e10c5c8a907b43fbd04f`。

## 输入与执行环境

必须先挂载真实 `/Volumes/quant`。大额事件、账户和确定性重复文件保存在 `/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_v1`。运行器不会把未挂载的同名目录当外盘。

本机已存在的只读父缓存和运行环境连接如下，均被 Git 忽略：

```
research/shared_capital_v1/cache
  -> /Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1/research/shared_capital_v1/cache
research/shared_capital_v1/.venv
  -> /Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1/research/shared_capital_v1/.venv
```

`runtime.json` 记录实际 Python 与依赖版本。绘图使用本机已安装、包含 Matplotlib 和 Pandas 的 Python；账户计算始终使用上面的研究环境。原始输入位置和 SHA256 在 `input_manifest.json`；136 个父策略缓存、413 个登记原始输入、独立原生请求和 48 个封存父场景另有哈希绑定。源数据不随 Git 分发。缺失输入须恢复已登记版本，不得凭同名文件绕过验证，也不得重新生成封存中间件来追平差异。

宇宙契约和 26 个冻结 alpha/原始来源/配置/身份哈希保持不变。`contracts/execution_hardening_v1.json` 只登记底层 `execution/daily.py` 的空结果结构和未完成账户窗口修补前后哈希；它不能覆盖任何策略或宇宙源文件。此例外由用户请求的执行/结构加固范围授权，不修改父宇宙清单。

## 全流程

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1
/opt/anaconda3/bin/python -m pytest -q tests research --junitxml=research/capital_scaling_v1/output/hardening_tests.xml
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.capital_scaling_v1.run --stage all --revalidate-native --workers 4
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.capital_scaling_v1.finalize --derived --deterministic
```

顺序固定：18 个 Native 对账 → 全部 36 个 G100 双等级极限 → 54 个中间档位 → 8 个入场式 G100 → 16 个单策略优先诊断 → 归因、风险参考、结构闲置、报告和图。两段为 2018–2021、2022–2023；不加载 2023 年后的收益结果，不打开新封存验证集。

全工程测试使用本机已安装额外历史研究依赖的 Anaconda Python；数值核心依赖与 `requirements.lock` 一致。账户计算的精确环境在 `runtime.json`。默认 `python -m pytest` 仍覆盖生产测试、共享账户和本次资本测试；上面的显式 `tests research` 另外保留旧研究的全部可运行回归。MCB 外部全量复现测试若缺少 `FIVE_STRATEGY_INPUT_CONFIG` 会明确跳过；本研究的 MCB 实際 Native 和缩放账户仍必须完成，没有将该跳过当成真实数据缺失或计算通过。

已有完整案例只有在输入、配置、期间、生产者及物理账户文件哈希通过时才能复用。`--revalidate-native` 禁止沿用其他生产者的 Native 根目录；当前生产者的完整已验收物理输出仍按收据验证。收尾 `--deterministic` 另建空目录，强制实际计算六个已登记设置，逐一比较 daily、fills、timeline、demand、checkpoints、account 和 scaling 七类文件，共 42 项哈希；它不增加参数设置。运行期间源码或初始状态变化会非零退出。

若仅重建派生 CSV、报告和图，可运行：

```bash
PYTHONPATH=.:src research/shared_capital_v1/.venv/bin/python -m research.capital_scaling_v1.run --stage all
```

这条命令仍核验每个被复用案例的收据并重新计算摘要。派生报告逻辑变动之后还需重跑受影响测试、图表确定性检查和 `finalize`，不能把生成成功等同于全门禁通过。

`finalize --derived` 会实际重绘四个 PNG/SVG，再调用正式入口重建全部派生表、报告和图，比较 35 个输出的原始字节哈希。`plot_determinism.csv` 与 `derived_output_determinism.csv` 保留前后哈希；之后的普通 `finalize` 还会检查当前文件仍与这些证明一致。`--deterministic` 的新目录名属于运行出处，不要求两次出处名相同；需要一致的是六次重算的 42 个物理经济文件。

`--workers` 只接受 1、2、4，默认 1。四进程模式按场景独立加载已核验数据和建立账户；主进程按固定案例顺序写总表，并在 Native、全部 G100、G25、G50、G75、入场式和优先诊断之间等待全部完成。进程数不是策略参数，六个新目录的串行重算会检验与并行账户文件相同。

从研究目录校验交付文件：

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-capital-scaling-v1/research/capital_scaling_v1
shasum -a 256 -c output/output_manifest.sha256
```

`hardening_tests.xml` 的时间和主机信息仅作运行诊断；确定性清单使用 `output/test_results.json` 中实际测试名称及结论。中途失败的临时日志和 `parent_tests.xml` 不作为最终通过证据。`output/external_artifact_manifest.csv` 指向每个实际外盘文件及 SHA256。`output/completion.json` 只证明计算门禁；最终 `TASK_STATUS=COMPLETE` 还要求本次正常提交与远端 HEAD 一致。

## 历史入口

`LEGACY_DO_NOT_USE_FOR_CURRENT_RESULTS`：共享资本早期 V0、V05、V06 和 `final_progress_v1` 总控，以及冻结策略目录中的旧直接现金回放，不是本次资本研究的正式入口。它们保留用于源码与历史证据对照，不得覆盖本目录的结果。父 `reproduce_v2` 属于父任务的封存复跑程序；在本次加固工作树中不要用它重建或覆盖父缓存。当前唯一资本研究入口为本文件列出的 `research.capital_scaling_v1.run`。

单策略生产 CLI 的输入路径按配置文件目录解析，仅校验所选策略需要的输入；研究的登记绝对数据位置仍由清单核验。这两种职责不同，不能用方便迁移为由解除数据身份约束。
