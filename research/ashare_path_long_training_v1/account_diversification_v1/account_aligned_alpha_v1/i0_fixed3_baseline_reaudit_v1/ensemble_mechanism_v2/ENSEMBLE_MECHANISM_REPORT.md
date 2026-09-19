# I0 FIXED3 ENSEMBLE MECHANISM AUDIT V2

## 裁决摘要

I0 fixed3 的实现与 fresh common-contract replay 已在前序 reaudit 中验证。本报告不重新证明收益、也不搜索新规则；它只用认证后的 `(t,j)` keyed score、2020/2021 标签和四份 fresh ledger 解释既有差异。

2020 的主要解释不是“多数投票”。它是三个同时存在的过程：

1. rank averaging 排除了大量“一个 seed 极高、另两个 seed 很低”的不一致极端；
2. fixed3 Top10 中约 25.9% 是 C0，即没有任何 seed 单独排进 Top10、但平均 rank 足够高的股票；
3. 这些信号差异几乎原样转化为计划与成交名称差异，之后再由 H10 的现金、持仓和重叠路径作次级放大。

2021 的机制仍改善左尾，但不再胜过最强 seed。fixed3 相对三个单 seed 平均收益高 5.9404 个百分点，却比 s17 低 3.7459 个百分点；对应的 signal 诊断也显示 fixed3 的 Ret20 均值低于 s17，只是 large-loss frequency 更低。因此 2021 是“稳健化而非全面支配”。

旧标签 `CONSENSUS_DENOISING_AND_TAIL_SHARPENING` 应判为 **REVISED**：denoising 和 tail sharpening 在 signal 层得到支持，但它遗漏了 C0 mid-rank promotion、共同 gate 的条件化，以及 stateful account path；它也不能解释 2021 为什么低于 s17。

## 冻结对象与边界

- fixed3：每个决策日分别对三个 composed CENTERED prediction 做 same-date percentile，再取三者均值并降序排序；平分按 `j` 升序。
- `support_count` 仅为诊断，不是策略规则。
- 主比较始终使用共同 fixed3 positive gate、canonical snapshot、Top10、H10 和同一执行合同。
- Ret10/Ret20 均为“先选股、后报告有限标签覆盖”，没有以标签补位。
- 只读取 2020、2021；两年均为已消费 development evidence。
- 没有训练、调权、换聚合器、调 gate/TopN/H10，也没有打开 2022 以后结果。

详细 keyed 几何有 1,748,062 行，保存在外置盘 `ensemble_mechanism_v2/SEED_GEOMETRY_2020_2021.parquet`，SHA256 为 `258f3dd9339d9808d31727c22b5024801c8a25bde1442260190225769138c4ee`。

## A. Seed 几何

下表为逐日三组 pair 的平均值：

| 年份 | 范围 | Spearman | Top10 overlap | Top20 | Top50 | Top100 |
|---|---|---:|---:|---:|---:|---:|
| 2020 | 完整 legal universe | 0.7122 | 0.2712 | 0.2798 | 0.3129 | 0.3552 |
| 2020 | common gate | 0.3581 | 0.2888 | 0.3007 | 0.3382 | 0.3968 |
| 2021 | 完整 legal universe | 0.7525 | 0.2599 | 0.2746 | 0.3096 | 0.3509 |
| 2021 | common gate | 0.4862 | 0.2866 | 0.2959 | 0.3246 | 0.3570 |

结论：全域相关性高，但 extreme Top10 overlap 只有约 26%–29%。也就是说，三个 seed 对“大方向”较一致，对真正进入每日最顶端的名字却分歧很大。2021 的全域相关性稍高，但 Top10 overlap 没有随之提高。

## B. fixed3 Top10 构成

`Ck` 表示同一股票进入 `k` 个单 seed common-gate Top10。少数日期 gate 内不足 10 只，因此 2020/2021 的 fixed3 选择总数分别为 2,419/2,319，而不是机械补足到 2,430。

| 年份 | 类别 | fixed3 Top10 占比 | Ret20 均值 | 正收益率 | 大亏频率 | Ret20 p05 |
|---|---|---:|---:|---:|---:|---:|
| 2020 | C0 | 25.88% | 2.3617% | 50.00% | 9.45% | -12.53% |
| 2020 | C1 | 34.49% | 1.3150% | 46.67% | 15.03% | -15.55% |
| 2020 | C2 | 23.21% | 3.1071% | 46.80% | 16.60% | -17.25% |
| 2020 | C3 | 15.97% | 6.2747% | 55.06% | 20.89% | -16.69% |
| 2021 | C0 | 25.27% | 3.0726% | 58.00% | 6.21% | -10.54% |
| 2021 | C1 | 29.67% | 4.8793% | 61.33% | 8.72% | -11.94% |
| 2021 | C2 | 24.07% | 5.5278% | 59.93% | 10.39% | -15.61% |
| 2021 | C3 | 16.42% | 7.5256% | 62.50% | 11.99% | -19.15% |

2020 的盈利来源是混合而非单一类别：C3 的每个有限标签 Ret20 均值最高，但 C0 占比大、左尾较轻，并且在修正后的新买入 lot PnL 中贡献最大。2021 也是混合结构，实际新买入 PnL 以 C1 最大，C0 仍为正但不是主导。

对 C0 的“稳定中高排名”要精确限定：

| 年份 | 平均 rank | 平均 best rank | 平均 worst rank | 三 seed 全 Top20 | 三 seed 全 Top50 |
|---|---:|---:|---:|---:|---:|
| 2020 | 34.97 | 18.69 | 56.13 | 4.29% | 53.42% |
| 2021 | 37.31 | 19.65 | 60.04 | 3.91% | 45.77% |

所以 C0 确实是 mid-rank promotion，但不能笼统说成“三个模型都进 Top20”。更准确的表述是：没有 seed 单独把它排进 Top10，约一半样本在三个 seed 中都位于 Top50，其余样本由更不均匀但仍有竞争力的平均 rank 推入 fixed3 Top10。

## C. Denoising 检验

对每个 seed 的 common-gate Top10，先机械划分 retained/dropped，再看结果。六个 seed×year 单元中，retained 的另外两个 seed rank、rank dispersion 和 Ret20 均优于 dropped：

| 年份/seed | dropped 另两 seed 平均 rank | retained | dropped rank std | retained | dropped Ret20 | retained Ret20 |
|---|---:|---:|---:|---:|---:|---:|
| 2020/s17 | 509.5 | 20.6 | 340.0 | 13.8 | 0.07% | 3.50% |
| 2020/s29 | 407.0 | 22.7 | 303.4 | 14.6 | 0.45% | 3.71% |
| 2020/s43 | 581.1 | 18.9 | 401.2 | 13.6 | 0.76% | 3.94% |
| 2021/s17 | 586.4 | 22.0 | 380.1 | 15.3 | 5.35% | 6.25% |
| 2021/s29 | 498.4 | 20.1 | 306.9 | 16.2 | 3.84% | 5.51% |
| 2021/s43 | 423.5 | 25.3 | 303.4 | 17.3 | 3.75% | 6.84% |

这支持 signal-level consensus denoising。但 corrected realized H10 lot PnL 并非六格全同向：2020 s17/s29 的 retained 明显优于 dropped，s43 却是 dropped `+21.3k`、retained `-8.4k`。因此不能把 2020 全部账户差异归结为“每个 seed 的坏极端都被成功删除”。

2021 s17 的 dropped 部分本身仍有 Ret20 `5.35%`、corrected lot PnL `+240.8k`，说明 fixed3 的稳健过滤同时放弃了一部分 s17 的有效独有信号。这正是 fixed3 最终低于 s17 的直接机制证据。

## D. Gate alignment

| 年份 | 日均 legal universe | 日均 gate size | 平均通过率 | fixed3 rank 与 gate margin 日均 Spearman |
|---|---:|---:|---:|---:|
| 2020 | 3,365.3 | 1,909.5 | 56.74% | 0.9958 |
| 2021 | 3,828.3 | 2,502.9 | 65.20% | 0.9971 |

固定 gate 和 fixed3 rank 几乎共线，这是结构事实：二者都由三个 composed prediction 产生。但 signal-only 去 gate 对照不支持“gate 制造了 2020 优势”：

| 年份 | 范围 | fixed3 Ret20 | 单 seed 平均 Ret20 | fixed3 差值 |
|---|---|---:|---:|---:|
| 2020 | 完整 legal universe | 2.6734% | 1.7301% | +0.9433pp |
| 2020 | common gate | 2.7355% | 1.8092% | +0.9263pp |
| 2021 | 完整 legal universe | 4.8427% | 4.8152% | +0.0275pp |
| 2021 | common gate | 5.0836% | 5.1776% | -0.0940pp |

因此 gate 提供强烈的结构性条件化与比较范围，但没有解释 2020 的 signal 均值优势；2021 在 common gate 内甚至不具备相对单 seed 平均的 Ret20 均值优势。由于三个 own-gate 单 seed 账户是可选诊断且本轮未运行，gate 对正式账户收益的精确因果百分点不能识别。

## E. 从候选到执行与状态路径

fixed3 与每个 seed 每日 Top10 的平均重合只有 3.93–4.53 只（2020）和 4.16–4.33 只（2021）。候选名称的对称差约 10.4–12.0，只在 planned/fill 层发生很小变化：

- 2020 实际成交名称对称差平均 10.76–12.37；fixed3 平均成交 9.87 单，单 seed 为 9.85–9.86 单。
- 2021 实际成交名称对称差平均 10.28–10.82；fixed3 平均成交 9.41 单，单 seed 为 9.40–9.44 单。
- 两年 aggregate same-name cap rejection 日均均为 0；流动性拒单日均约 0.02–0.06。
- 相对各 seed，fixed3 平均 exposure 差为 0.3–2.3 个百分点、live lots 差绝对值低于 0.42；现金路径存在差异，但不是大量候选在执行层被统一抹掉造成的。

分类结论：主要是 `SIGNAL_DIFFERENCE`；`EXECUTION_CONVERSION` 很高；`STATE_PROPAGATION` 存在并可放大收益，但现有证据不支持它是最初差异来源。

## F. 修正后的真实 PnL

交易现金流只取 lot fills 一次；cashflows 中的 BUY/SELL 不重复相加。费用已包含在 lot cashflow PnL 中，单列仅作 memo。两年这些 ledger 没有额外股息、税或公司行动现金项。

| 年份/账户 | closed lot | open/end inventory | reconciled total | NAV change | residual |
|---|---:|---:|---:|---:|---:|
| 2020/s17 | -3,919.98 | -17,347.03 | -21,267.01 | -21,267.01 | < 1e-9 |
| 2020/s29 | -1,634.07 | -19,482.37 | -21,116.44 | -21,116.44 | < 1e-9 |
| 2020/s43 | 125,464.44 | -30,092.09 | 95,372.34 | 95,372.34 | < 1e-9 |
| 2020/fixed3 | 184,536.83 | -10,140.67 | 174,396.16 | 174,396.16 | 0 |
| 2021/s17 | 521,124.25 | 700.90 | 521,825.15 | 521,825.15 | < 1e-9 |
| 2021/s29 | 375,865.49 | 19,611.10 | 395,476.59 | 395,476.59 | < 1e-9 |
| 2021/s43 | 343,912.87 | 13,670.16 | 357,583.03 | 357,583.03 | < 1e-9 |
| 2021/fixed3 | 462,107.53 | 22,258.54 | 484,366.07 | 484,366.07 | < 1e-9 |

fixed3 新买入 lot 的描述性 PnL 分类如下；这些值含费用，但不包括由共同年初 snapshot 继承的 lot，因此不能独立加总成完整 NAV 因果贡献：

| 年份 | C0 | C1 | C2 | C3 | 扫描到 Top10 后续候选 |
|---|---:|---:|---:|---:|---:|
| 2020 | +50.8k | +23.8k | +26.9k | +24.8k | +22.8k |
| 2021 | +81.8k | +189.8k | +132.7k | +93.2k | +38.0k |

归因修复没有改变订单、交易、NAV 或年度收益；它只撤销旧 stock contribution 排名及由双重记账支持的机制叙述。

## G. 日期与 block 稳健性

日度 active return 定义为 fixed3 账户日收益减去三个单 seed 账户日收益均值，仅作描述性比较：

| 年份 | 日均 | 中位数 | 正日比例 | active sum | leave-best1 | leave-best3 |
|---|---:|---:|---:|---:|---:|---:|
| 2020 | 0.0582% | 0.0478% | 57.20% | 14.1503% | 13.0219% | 11.2850% |
| 2021 | 0.0171% | 0.0158% | 51.44% | 4.1474% | 3.2197% | 1.6503% |

固定的不重叠 20-session blocks 中，2020 有 11/13 个 block 的 active sum 为正；去掉最佳三日仍保留 11.2850% 的 active sum，故“2020 完全由少数日期造成”不受支持。2021 只有 8/13 为正，最佳三个 block 的正贡献超过全年净 active sum，表现更具阶段性。

更强的 78 次 stateful block replacement replay 没有在本轮运行：单次 fresh replay 基准约 18–19 秒，矩阵估计约 24 分钟持续 CPU/IO，而主 MPS 训练仍在运行。按资源隔离合同，本报告不让该可选诊断与主训练竞争。因此 block 层的因果 account-path 结论仍为 `INCONCLUSIVE`，静态 block 结果不能冒充反事实回放。

## 直接回答

1. **2020 为什么 fixed3 明显更好？** 全域相关高但 Top10 分歧大；rank average 同时过滤不一致极端、保留 C2/C3，并提升约四分之一的 C0。fixed3 common-gate Top10 的 Ret20 为 2.7355%，三个 seed 为 1.5493%/1.8896%/1.9888%，且大亏频率更低。候选差异几乎都转成成交差异，账户路径再作次级放大。
2. **2021 为什么高于单 seed 平均但低于 s17？** fixed3 仍降低左尾并优于弱两个 seed 的组合平均，但 s17 的独有/dropped 股票仍有较强正收益；fixed3 Ret20 均值低于 s17，稳健化代价是放弃一部分 s17 有效 tail。
3. **主要机制是什么？** 是混合：过滤单 seed 错误极端最稳定地出现在 signal 诊断；C0 mid-rank promotion 对 2020 实际 PnL 很重要；C3 共同支持的有限标签均值最高，但数量不足以单独解释账户收益。不是多数投票。
4. **positive gate 贡献多少结构性优势？** 它与 fixed3 rank 的 Spearman 约 0.996–0.997，结构耦合极强；但去 gate 后 2020 signal edge 仍为 +0.9433pp，gate 内为 +0.9263pp。2021 gate 内均值 edge 反而为 -0.0940pp。正式账户的 gate 因果百分点未识别。
5. **+15.67pp 中 signal 与账户路径各多少？** signal 层可直接看到 +0.9433pp 的 Ret20 均值差和明显左尾改善；账户层为 +15.6733pp。两者单位和路径不同，不能相减分摊。成交差异主要继承信号差异，状态放大存在但没有被独立反事实量化。
6. **改善是否集中少数阶段？** 2020 描述性证据偏广泛：11/13 blocks 为正，leave-best3 仍强。2021 更集中：8/13 为正且最佳 blocks 权重大。stateful block 因果检查未运行，所以这一结论仅为描述性。
7. **旧标签是否成立？** 部分成立但必须修订。signal denoising/tail sharpening 有证据；“只靠 consensus denoising”不足，必须加入 C0 mid-rank promotion、gate conditioning 和 account state，并注明 2021 不胜 s17。
8. **哪些只能称描述性？** Ret10/Ret20、bucket PnL、日度 active return、静态 blocks，以及 gate 对正式账户的收益贡献都不是独立因果分解。2020/2021 也不能提供新的泛化证据。

## 最终机制裁决

- `M1_CONSENSUS_DENOISING = PARTIAL`：signal 层支持；2020 s43 的 corrected realized lot PnL 反向，故账户层非全支持。
- `M2_STABLE_MIDRANK_PROMOTION = PARTIAL`：C0 约占四分之一且 2020 实际贡献重要；“三个 seed 都稳定 Top20”不成立。
- `M3_GATE_ALIGNMENT = PARTIAL`：结构耦合很强，但 gate 不是 2020 signal edge 的来源，账户因果量未识别。
- `M4_ACCOUNT_STATE_AMPLIFICATION = PARTIAL`：状态路径确实分化，但执行层基本保留信号名称差异，放大是次级机制。
- `M5_FEW_EPISODE_PATH_DEPENDENCE = PARTIAL`：2020 描述上不支持，2021 较支持；stateful block 因果结论不确定。
- `M6_BROAD_RECURRENT_ENSEMBLE_EDGE = PARTIAL`：2020 描述性证据支持，2021 只支持“胜平均、不胜 s17”，反事实 block 尚缺。

`I0_FIXED3_IMPLEMENTATION = VERIFIED`

`2020_EXPLANATION = RANK_DENOISING_PLUS_C0_PROMOTION_WITH_SECONDARY_ACCOUNT_PATH_AMPLIFICATION`

`2021_EXPLANATION = TAIL_ROBUSTIFICATION_BEATS_MEAN_SINGLE_BUT_SACRIFICES_VALID_S17_EXTREMES`

`OLD_MECHANISM_LABEL = REVISED`

`NEW_STRATEGY_SELECTED = NO`

`TRAINING_MODIFIED = NO`

`2022_OPENED = NO`

`2023_OPENED = NO`

`2024_2026_OPENED = NO`

`PRODUCTION_APPROVED = NO`
