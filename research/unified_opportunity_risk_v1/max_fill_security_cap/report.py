"""Publish all X/Y cells and all yearly drawdowns; retain the existing verdict."""
import json
import re
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.max_fill_security_cap.grid import HERE,OUT,XS,YS
from research.unified_opportunity_risk_v1.exposure_scale import run as previous


def markdown(frame,percent):
    data=frame.copy()
    for c in percent:data[c]=data[c].map(lambda v:f'{v:.2%}')
    return '\n'.join(['| '+' | '.join(data.columns)+' |','| '+' | '.join(['---']*len(data.columns))+' |']+['| '+' | '.join(map(str,row))+' |' for row in data.itertuples(index=False,name=None)])


def main():
    full=pd.read_csv(OUT/'candidate_b_xy_full_metrics.csv');annual=pd.read_csv(OUT/'candidate_b_xy_yearly_metrics.csv');effect=pd.read_csv(OUT/'paired_Y_effects.csv')
    assert len(full)==32 and len(annual)==288
    order=[previous.label(x) for x in XS]
    combined=full.pivot(index='X',columns='Y',values='CAGR').reindex(order).astype(object)
    for x in order:
        for y in YS:
            row=full.loc[full.X.eq(x)&full.Y.eq(y)].iloc[0]
            combined.loc[x,y]=f"{row.CAGR:.2%} / {row.MaxDD:.2%}"
    combined.columns=[f'Y={y:.0%}' for y in YS];combined=combined.reset_index()
    annual_tables=[]
    for x in order:
        m=annual.loc[annual.X.eq(x)].pivot(index='year',columns='Y',values='MaxDD');m.columns=[f'Y={y:.0%}' for y in YS]
        m.index=m.index.map(lambda y:f'{y} YTD' if y==2026 else str(y));m=m.reset_index()
        annual_tables.append('### '+x+'：每年最大回撤\n\n'+markdown(m,list(m.columns[1:])))
    log=(OUT/'tests.log').read_text();match=re.search(r'(\d+) passed',log);assert match and 'failed' not in log
    repair.write_json(OUT/'test_results.json',dict(passed=int(match[1]),exit_code=0,summary=log))
    strict=effect.loc[effect.Y.ne(.1)&effect.CAGR_not_lower_and_MaxDD_not_higher&effect.strict_improvement]
    strict_text='；'.join(f'{r.X}/Y={r.Y:.0%}' for r in strict.itertuples()) or '无'
    frozen=json.loads((previous.PARENT_OUT/'calibration_frozen.json').read_text());floor=min(r['conservative_tail_loss'] for r in frozen['rows'])
    reference=json.loads((previous.PARENT_OUT/'risk_references_frozen.json').read_text())['references']['security']
    bounds=pd.DataFrame([dict(X=previous.label(x),security_tail_budget=x*reference,min_frozen_tail_loss=floor,soft_security_exposure_bound=x*reference/floor) for x in XS[:-1]])
    bounds.to_csv(OUT/'soft_security_budget_bounds.csv',index=False)
    test_count=int(match[1]);audit=pd.read_csv(OUT/'account_validation.csv');assert len(audit)==32 and audit.status.eq('PASS').all()
    text=f'''# Candidate B：X × 单票上限 Y 二维诊断

已完成32组真实连续账户：X=1、1.5、2、3、5、8、10、MAX_FILL，分别交叉Y=10%、15%、20%、30%。已有Y=10%八组及本轮先完成的MAX_FILL三组逐文件哈希复核后复用，另外21组均独立实际重跑。没有以净值相乘、收益拼接或静态生命周期加总代替账户。

相同X下，相较Y=10%，新增Y档位中同时满足“CAGR不低、MaxDD不高，且至少一项严格改善”的组合为：**{strict_text}**。相等不算改善。此处只描述预定网格，不挑选或推广新的生产参数；原KEEP_NATIVE结论保持不变。

## 全期：每格为年化CAGR / 最大回撤

2018-01-01至2026-09-04，继承初始NAV/持仓连续运行。

{markdown(combined,[])}

Y是单票新增仓位的硬上限，不是每只必须买到的目标。有限X仍保留按X缩放的机会、单票尾部、总尾部和family软风险预算。因此提高Y可能没有任何实际作用。MAX_FILL才取消这些软预算。

冻结校准中的最小尾部损失是{floor:.2%}，单票RP100尾部预算为{reference:.8%} NAV。由此，有限X下单票新增后暴露还受约X×{reference/floor:.4%}的软约束：X5约9.44%，X8约15.11%，X10约18.88%。所以Y20和Y30不一定产生差别。真实重跑的低X每日NAV、现金、gross、原生回调及最终账户完全一致；成交/分lot明细按绝对1e-10容差检查，实际最大差异另见nonbinding_Y_replay_validation.csv，不能把相等表格误解为未运行。

本次证据不支持通过单纯放宽单票上限来稳定地“保持利润、控制最大回撤”：X≤5不产生经济变化，X8/X10增加收益也增加全期回撤，MAX_FILL则收益下降且回撤明显扩大。年度效果并不一致，例如X10/Y20相对Y10在2020、2025年回撤较小，但2022年从13.79%扩大到17.39%。X10/Y20相对Y15有微小的收益/回撤双改善，但相对Y10仍是更高回撤，不能据此认定稳定风险改进。

## 全部32条曲线

![全部X/Y净值与双轴市场指数](output/candidate_b_xy_nav.png)

![全部X/Y回撤](output/candidate_b_xy_drawdown.png)

每个Y面板都画出全部8个X，四个面板使用相同账户纵轴。指数使用独立右轴、首日收盘归一100；左右轴曲线高度不能直接比较收益。指数仅展示，复用前轮已校验的本地价格文件。

## 全部逐年最大回撤

每年以该年开始前的实际账户权益为起点计算年内峰谷回撤。全期MaxDD则保留跨年高点，所以二者不能互相替代。2026截至9月4日，2024–2026仍为事后诊断。

{chr(10).join(annual_tables)}

## 冻结与审计边界

Candidate B的信号来源、R1、发现期校准、正质量门槛、原生时钟和退出不变；按用户已确认口径允许原生持仓状态反馈改变后续合法请求。有限X的B_i由当前诊断账户NAV按冻结B公式计算，仅新增/增持目标乘X，已有仓位不重归一。总gross≤100%、现金不融资、同票聚合和注册流动性/执行限制不变，Y是唯一新增的硬约束实验维度。

每个新获资证券的时点完成占比均不超过对应Y，后续价格漂移可能使已有持仓超过Y，不强行退出。全部32组现金/gross/P&L、正质量准入及注册流动性检查通过；MAX_FILL的两类软预算均为0。沿用Native现金1e-8元数值容差，无clip、借款或保证金。

{test_count}项测试通过，442个注册输入哈希通过。前一轮仓位倍数研究文件哈希保持不变；本轮账户路径、生成身份和文件哈希见account_run_manifest.json。大体积账户缓存留在本地且不进入Git，代码、合同、完整结果和摘要清单进入Git。

## 文件与复现

- candidate_b_xy_full_metrics.csv：32组全期CAGR、MaxDD、CVaR5、Sharpe、平均gross、现金、费用、换手等。
- candidate_b_xy_yearly_metrics.csv：288条逐年记录，含实际收益、年化CAGR、MaxDD等；2026的年化不代表全年已实现收益。
- candidate_b_xy_cagr_matrix.csv / candidate_b_xy_max_drawdown_matrix.csv：完整二维矩阵。
- candidate_b_xy_yearly_max_drawdown.csv：全部逐年回撤矩阵。
- paired_Y_effects.csv：同X下相对Y10的收益/回撤变化，不是参数优化。
- account_validation.csv / liquidity_validation.csv / nonbinding_Y_replay_validation.csv：账户、流动性及低X不绑定路径核对。

```sh
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.max_fill_security_cap.run
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.max_fill_security_cap.grid
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.max_fill_security_cap.analyze
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.max_fill_security_cap.plot
PYTHONPATH=.:src /opt/anaconda3/bin/python -m research.unified_opportunity_risk_v1.max_fill_security_cap.report
```

run.py只负责MAX_FILL三组，是网格的一个子集；grid.py补齐其他21组。grid_contract.json是最终用户更正后的研究合同，contract.json保留三个已运行MAX_FILL账户的原始生成身份，不改写历史receipt。
'''
    (HERE/'REPORT.md').write_text(text)
    (HERE/'RUN_STATE.md').write_text('COMPLETE: 32 X/Y cells, 288 yearly rows, actual continuous physical accounts; KEEP_NATIVE unchanged. No parameter promotion.\n')
    manifest=json.loads((HERE/'input_manifest.json').read_text());manifest['research_sources']={p.name:repair.digest(p) for p in HERE.glob('*.py')};repair.write_json(HERE/'input_manifest.json',manifest)
    files=[p for p in HERE.iterdir() if p.is_file() and p.name!='.DS_Store']+[p for p in OUT.iterdir() if p.is_file() and p.suffix!='.log' and p.name!='output_manifest.sha256']
    (OUT/'output_manifest.sha256').write_text(''.join(f'{repair.digest(p)}  {p.relative_to(HERE)}\n' for p in sorted(files)))
    print(combined.to_string(index=False));print('STRICT IMPROVEMENTS vs same-X Y10:',strict_text)

if __name__=='__main__':main()
