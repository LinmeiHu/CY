"""One-time zero-candidate adjudication; refuse to overwrite frozen contracts."""
import shutil,json
import pandas as pd
from .build import HERE,sha,js

def main():
 p=HERE/'discovery_freeze';assert not p.exists(),'Freeze is immutable';p.mkdir()
 common=dict(version='SIXTH_ALPHA_DISCOVERY_V1',discovery_start='2018-01-01',discovery_end='2021-12-31',candidate_count=0,status='NOT_APPLICABLE_NO_QUALIFIED_VISUAL_SEMANTIC')
 js(p/'FROZEN_MECHANISM_SPEC.json',dict(**common,decision='NO_NEW_MECHANISM_FOUND',failure_layer='VISUAL',mechanisms=[],family_closure=False,reason='No visual dimension combines repeatability with broad multi-year economic outcome separation. Volume alignment has repeat Spearman 0.153; rejection is 95.7% neutral. Other matched winner-loser effects are small and/or change sign.',validation_outcomes_opened=False))
 shutil.copyfile(HERE/'visual/visual_codebook_v1.json',p/'FROZEN_VISUAL_CODEBOOK.json')
 js(p/'FROZEN_FEATURE_SPEC.json',dict(**common,alpha_features=[],quantitative_definitions_tested=0,reason='User section21 permits quantitative translation only after the visual gate; no semantic qualified. Standard controls are diagnostics, not candidate alpha features.'))
 js(p/'FROZEN_SCORE_SPEC.json',dict(**common,score=None,ranking=None))
 js(p/'FROZEN_ENTRY_SPEC.json',dict(**common,entry=None,top_k=None))
 js(p/'FROZEN_EXIT_SPEC.json',dict(**common,exit=None,holding_period=None))
 js(p/'FROZEN_PORTFOLIO_VESSEL.json',dict(**common,max_single_stock=.05,max_active_positions=20,max_gross=1,cash_min=0,leverage=False,note='User prescribed vessel retained as a contract only; no synthetic cash-only strategy account is run.'))
 (p/'DISCOVERY_FREEZE.md').write_text('''# 发现期冻结：零候选

结论 NO_NEW_MECHANISM_FOUND，准确失败层 VISUAL。不是机制家族封闭，不是 STANDARD_FACTOR_REDISCOVERED，也不是可投资性或组合失败。

盲标签于 eb8873f13b 提交后才揭示 2018–2021 个体结果。当前尚未查看任何 2022+ 个体前向结果或策略结果。冻结时保留0个机制、0个特征、0套交易规则。

主要证据：配对赢家减输家 direction +0.017、turn -0.061、retention +0.006、quieting +0.006、spike_distribution +0.017、context +0.056，分数范围为-2至+2。多项逐年变号，分桶无宽阔稳定梯度。volume_alignment 配对+0.098，但重复秩相关0.153且状态间变号。rejection 配对+0.040，但95.7%有效标注为0，非零桶19/4例，不足以支撑可泛化机制。

判断基于效应大小、响应形状、跨年和测量质量综合评估；不是根据p值或事后设定数值门槛。未通过视觉门槛的语义不进入多公式搜索，以免违反第21节。第47节要求的多视觉与多公式家族封闭条件未满足，故不封闭任何经济家族。

提交本目录后所有文件不可修改。2022/2023/2024+验证、生命周期、闲置资金叠加和统一竞争均为条件不适用，不能写成运行失败或运行通过。若仅补齐全期因果覆盖背景，不把它解释成候选验证。无需读取留存验证收益来挽救本轮。
''')
 (p/'discovery_freeze_manifest.sha256').write_text(''.join(f'{sha(f)}  {f.name}\n' for f in sorted(p.iterdir()) if f.is_file()))
 q=HERE/'quant';q.mkdir(exist_ok=True);pd.DataFrame([dict(dimension=d,quantitative_expressions=0,status='NOT_ENTERED_VISUAL_GATE',reason=r) for d,r in {
 'direction':'Matched W-L +0.017; annual sign reversal; no persistent-score gradient',
 'turn':'Matched W-L -0.061; annual sign reversal; nonlinear buckets unstable',
 'retention':'Matched W-L +0.006; neutral differs from both extremes, no winner-loser ordering',
 'quieting':'Matched W-L +0.006; 2018 positive,2019/2020 negative; no +2 formal observations',
 'spike_distribution':'Matched W-L +0.017; annual reversal; +2 bucket only2 observations',
 'volume_alignment':'Repeat Spearman0.153; pooled effect insufficient to overcome measurement instability',
 'rejection':'95.7% valid scores neutral; sparse tails cannot establish broad structure',
 'context':'Matched W-L +0.056; nonmonotone response; not distinct independent mechanism'}.items()]).to_csv(q/'semantic_response_summary.csv',index=False)
 (HERE/'mechanisms').mkdir(exist_ok=True);(HERE/'mechanisms/ADJUDICATION.md').write_text('''# 本轮无合格机制

8个视觉维度的证据见 quant/semantic_response_summary.csv、visual/visual_year_spreads.csv 和 visual/paired_visual_diagnostics.csv。没有构造三份虚拟机制卡。

STANDARD_FACTOR_REDISCOVERED、DUPLICATES_EXISTING_* 和 ALPHA_COLLAPSED 均未被证明。语义层失败也不等于价格路径中不存在可发现的独立alpha。合理的未来工作应先改善测量（尤其影线分辨率和量价判断），另立V2，不能事后改写本轮盲标签。
''')
if __name__=='__main__':main()
