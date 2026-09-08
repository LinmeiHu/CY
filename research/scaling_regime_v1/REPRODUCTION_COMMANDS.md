# 身份门禁复跑

仅在 `/Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1`、分支 `research/five-strategy-scaling-regime-v1` 运行。依赖已安装的 Anaconda Python 3.13、pandas、numpy、pyarrow、pytest；没有安装新依赖。

需要真实 `/Volumes/quant` 的父账户与连续滚动账户，以及 `input_manifest.json` 中绑定的输入。未提交滚动生产脚本已快照到 `evidence/`，对应原文件仍按哈希核验。这里不调用任何生产者，也不写外盘或父工作区。

```bash
cd /Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.scaling_regime_v1.audit
```

**预期退出码为 2**，并产生 `BLOCKED_ROLLFORWARD_IDENTITY_MISMATCH`。这表示门禁正确拒绝，不是账户计算已通过。输入缺失或漂移则会抛出异常；不能把任何非零退出码都当预期的身份拒绝。

父测试要求已登记缓存位于当前树 `research/shared_capital_v1/cache`。当前该路径为 Git 已忽略的软链接，指向 `/Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1/research/shared_capital_v1/cache`。新检出时若路径不存在，可执行：

```bash
ln -s /Users/linmei/Documents/CY-worktrees/five-strategy-shared-capital-v1/research/shared_capital_v1/cache research/shared_capital_v1/cache
```

路径已经存在时不要覆盖。测试只复用已登记的缓存版本，随后 `finalize` 再验其哈希。

```bash
/opt/anaconda3/bin/python -m pytest -q tests research --junitxml=research/scaling_regime_v1/output/tests.xml
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.scaling_regime_v1.finalize
```

`finalize` 要求真实测试 XML 无失败，提取稳定的测试名称/结果，独立执行两次完整身份核验与报告生成并比较 SHA256。它的退出码应为 0；业务身份拒绝继续保持。XML、日志、运行耗时不纳入确定性清单，`test_results.json` 保存实际测试结论。

```bash
cd research/scaling_regime_v1
shasum -a 256 -c output/output_manifest.sha256
```

不重跑资本前沿，不生成年度收益、状态归因、容量、leave-year 或路由伪结果。18 个新增测试要求的未执行部分见 `output/requirement_test_coverage.csv`。继续经济研究前须明确父分段协议与连续扩展的权威关系，并闭合 MCB 快照资格证据；不应通过修改本门禁或放松误差来消除差异。
