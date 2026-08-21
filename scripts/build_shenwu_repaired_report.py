"""Render the repaired 000820.SZ point-in-time chip research report."""

# The embedded HTML is deliberately kept as a readable template.
# ruff: noqa: E501

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULT = ROOT / "artifacts/shenwu_000820_chip_result_20260820.json"
OUTPUT = ROOT / "artifacts/shenwu_jieneng_000820_20260820.html"


def pct(value: float, digits: int = 2) -> str:
    return f"{value * 100:.{digits}f}%"


def main() -> None:
    data = json.loads(RESULT.read_text(encoding="utf-8"))
    price = data["price_context"]
    primary = data["primary"]
    pre = primary["pre_trade_features"]
    post = primary["post_close_features"]
    snaps = primary["snapshots"]
    sensitivity_rows = "".join(
        f"<tr><td>{row['engine']}</td><td>{row['lambda_turnover']:.1f}</td>"
        f"<td>{pct(row['profit_ratio'])}</td><td>{row['average_cost']:.3f}</td>"
        f"<td>{row['p50']:.3f}</td><td>{row['p90']:.3f}</td></tr>"
        for row in data["sensitivity"]
    )
    snapshot_rows = "".join(
        f"<tr><td>{date}</td><td>{values['close']:.2f}</td><td>{values['turnover_pct']:.2f}%</td>"
        f"<td>{pct(values['profit_ratio'])}</td><td>{values['average_cost']:.3f}</td>"
        f"<td>{values['p50']:.3f}</td><td>{values['p90']:.3f}</td></tr>"
        for date, values in snaps.items()
    )
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>神雾节能 000820.SZ｜修复后筹码博弈分析</title>
<style>
:root{{--ink:#183149;--muted:#66727e;--paper:#f4f1ea;--card:#fffdf8;--line:#d8d2c6;--red:#a43c2e;--redbg:#f9e6df;--amber:#84651e;--amberbg:#f6edcf;--green:#326b54;--greenbg:#e4f0e9}}
*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);background:var(--paper);font:15px/1.72 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}a{{color:#165b86}}main{{max-width:1180px;margin:auto;padding:30px 30px 70px}}.hero{{padding:38px 42px;border:1px solid #c9d0d4;background:linear-gradient(135deg,#fcfbf6,#edf3f5);border-radius:22px;box-shadow:0 12px 30px #24364114}}.eyebrow{{font-size:12px;letter-spacing:.14em;font-weight:750;color:#637381}}h1{{margin:7px 0 10px;font-size:clamp(30px,5vw,54px);line-height:1.06;letter-spacing:-.035em}}.deck{{max-width:950px;margin:0;color:#51616e;font-size:18px}}.verdict{{margin-top:26px;padding:22px 25px;border-left:6px solid var(--red);background:#fffdf8eb;border-radius:7px 15px 15px 7px}}.verdict strong{{display:block;color:var(--red);font-size:24px}}.chips{{display:flex;gap:9px;flex-wrap:wrap;margin-top:18px}}.chip,.tag{{padding:5px 10px;border-radius:999px;font-size:12px;font-weight:750;background:#fff;border:1px solid #ccd4d9}}.chip.red,.tag.no{{color:var(--red);background:var(--redbg);border-color:#ddb7aa}}.chip.green,.tag.ok{{color:var(--green);background:var(--greenbg);border-color:#b9d3c5}}section{{margin-top:42px}}h2{{margin:0 0 14px;font-size:27px;line-height:1.2}}h3{{margin:0 0 7px;font-size:17px}}.lead{{max-width:940px;margin:0 0 18px;color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}}.card{{grid-column:span 4;padding:20px;background:var(--card);border:1px solid var(--line);border-radius:14px}}.wide{{grid-column:span 6}}.full{{grid-column:1/-1}}.metric{{margin:3px 0 2px;font-size:29px;font-weight:780;line-height:1.12}}.red{{color:var(--red)}}.small{{color:var(--muted);font-size:12px}}table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}}th,td{{padding:11px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{background:#e8ecec;color:#374c5a;font-size:12px}}figure{{margin:0;padding:16px;background:#fbfaf6;border:1px solid var(--line);border-radius:16px}}figure img{{display:block;width:100%;border-radius:8px}}figcaption{{margin:10px 7px 2px;color:var(--muted);font-size:12px}}.callout{{padding:17px 20px;border:1px solid #d3c28e;background:var(--amberbg);border-radius:12px}}.callout.redbox{{border-color:#d9afa3;background:var(--redbg)}}.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.flow div{{padding:14px;border:1px solid var(--line);background:var(--card);border-radius:12px}}.flow b{{display:block}}ul,ol{{margin:7px 0 0;padding-left:21px}}li+li{{margin-top:5px}}code,.mono{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;overflow-wrap:anywhere}}footer{{margin-top:44px;padding-top:19px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}}@media(max-width:820px){{main{{padding:16px 14px 50px}}.hero{{padding:25px 20px}}.card,.wide{{grid-column:1/-1}}.flow{{grid-template-columns:1fr}}th,td{{padding:9px 7px;font-size:13px}}}}
</style></head><body><main>
<header class="hero">
<div class="eyebrow">CYQ-GAME · 修复后点时研究｜decision_at 2026-08-20 收盘</div>
<h1>神雾节能 <span style="font-weight:520">000820.SZ</span></h1>
<p class="deck">筹码链已经修复。当前不是“无筹码可算”，而是<strong>摘帽脉冲后的快速退潮与弱修复</strong>：现价落在近端成本峰，但仍低于中央成本区，大量高位换手筹码处于浮亏，上方解套压力明确。</p>
<div class="verdict"><strong>筹码态势有效：T8/T9 多标签候选｜动作仍为 NO_TRADE</strong><p>筹码结论不再是 UNKNOWN；但股票状态不是订单。单股筹码修复没有补齐当日大盘、点时行业、调查结论、OOS EdgeCard 与真实成交能力，因此新增风险仓位仍被风控层阻断。</p></div>
<div class="chips"><span class="chip green">筹码质量守恒 PASS</span><span class="chip red">浮亏筹码 {pct(post['trapped_ratio'])}</span><span class="chip">收盘 {price['close']:.2f} 元</span><span class="chip">平均成本 {post['average_cost']:.3f} 元</span><span class="chip">PIT-B 条件研究</span></div>
</header>

<section><h2>一页结论</h2><div class="grid">
<article class="card"><div class="small">当前获利盘 / 浮亏盘</div><div class="metric red">{pct(post['profit_ratio'])} / {pct(post['trapped_ratio'])}</div><p>多数估计持仓成本高于3.40元。反弹首先面对解套盘，而不是已经形成普遍盈利的趋势结构。</p></article>
<article class="card"><div class="small">成本中枢</div><div class="metric">{post['average_cost']:.3f} 元</div><p>平均成本3.715元、成本中位数3.719元；现价低约8.5%。3.69–3.76元是中央确认区。</p></article>
<article class="card"><div class="small">上方90%成本分位</div><div class="metric red">{post['p90']:.3f} 元</div><p>4.07–4.11元为重压力区，4.45元附近是P99尾部；与近期4.50元高点相互印证。</p></article>
<article class="card"><div class="small">短线位置</div><div class="metric">MA5≈3.406</div><p>收盘贴近MA5，低于MA10 3.653和MA20 3.546，高于MA60 3.218；是下跌后的弱修复，不是趋势重建。</p></article>
<article class="card"><div class="small">20日 / 5日收益</div><div class="metric">+{price['return_20d_pct']:.2f}% / <span class="red">{price['return_5d_pct']:.2f}%</span></div><p>中周期仍保留摘帽脉冲涨幅，最近一周却明显回吐，时间尺度出现冲突。</p></article>
<article class="card"><div class="small">模型稳定性</div><div class="metric">获利盘 14.75–18.57%</div><p>cohort λ=0.8/1.2 与 uniform 三组结果方向一致；“多数套牢、成本中枢在3.7元上方”不是单一参数幻觉。</p></article>
</div></section>

<section><h2>筹码分布：两座成本山，现价卡在低峰</h2><figure><img src="shenwu_000820_chip_map.png" alt="神雾节能2026年8月20日收盘后筹码成本分布"><figcaption>主模型 cohort / λ=1.0。局部众数约3.40元与3.83元；峰宽重叠，不能把每个峰的窗口质量相加。筹码是带记忆和模型误差的持仓成本估计，不代表任何真实账户。</figcaption></figure>
<div class="grid" style="margin-top:16px"><article class="card wide"><h3>近端承接：3.33–3.40元</h3><p>P10为{post['p10']:.3f}元，低位局部峰约3.40元，8月20日低点3.30元。这里是当前最直接的承接带；若失守3.30，下一层模型尾部在P01≈{post['p01']:.3f}元，极端再看20日低点2.70元。</p></article><article class="card wide"><h3>中央与重压力：3.69–3.76 / 4.07–4.11元</h3><p>平均成本、P50与CYC13/34都聚集在3.72元附近；真正趋势修复至少要重新站稳该区。P90≈4.108元对应第二道重压力，向上仍有4.45–4.50元尾部套牢。</p></article></div></section>

<section><h2>筹码迁移：脉冲怎样变成套牢</h2><p class="lead">最重要的不是某一天的静态峰，而是成本和获利盘怎样随高换手迁移。</p><table><thead><tr><th>日期</th><th>收盘</th><th>换手</th><th>获利盘</th><th>平均成本</th><th>P50</th><th>P90</th></tr></thead><tbody>{snapshot_rows}</tbody></table>
<div class="callout redbox" style="margin-top:15px"><b>迁移解释：</b>7月30日摘帽复牌后，8月4日以32.30%换手冲至4.26元，当时获利盘达到93.74%；随后大量筹码在高位重置。到8月13日，股价3.74元而平均成本升至3.895元，获利盘骤降至19.96%；8月19日进一步降至3.02%。8月20日反弹只把获利盘修复到15.93%。这更符合“高位换手后承接失败、上方套牢形成”，而非“洗盘完成”。</div></section>

<section><h2>盘面路径：事件驱动很强，持续性尚未证明</h2><figure><img src="shenwu_000820_price_turnover.png" alt="神雾节能2026年价格与换手率"><figcaption>注册修复资产CY-004，未复权日线，截至2026-08-20。7月30日交易规则恢复10%后，8月初出现极端换手与快速价格再定价。</figcaption></figure></section>

<section><h2>CYQ-GAME 指标拆解</h2><table><thead><tr><th>指标</th><th>数值</th><th>含义</th></tr></thead><tbody>
<tr><td>PR（收盘后获利盘）</td><td>{pct(post['profit_ratio'])}</td><td>只有少数筹码在3.40元下方，反弹容易遭遇解套供应。</td></tr>
<tr><td>ASR（现价±10%）</td><td>{pct(post['asr'])}</td><td>约一半筹码集中在现价邻域，短期价格对换手与情绪敏感。</td></tr>
<tr><td>Concentration20</td><td>{pct(post['concentration_20'])}</td><td>约78%筹码落在20%宽度窗口内，筹码较集中，但“集中”不等于庄家控盘。</td></tr>
<tr><td>CYQK_pre</td><td>开 {pre['cyqk_pre']['open']:.2f}% → 收 {pre['cyqk_pre']['close']:.2f}%</td><td>使用8月20日交易前筹码状态计算，收盘相对开盘的获利覆盖增加4.52个百分点；只是日内修复。</td></tr>
<tr><td>CYC5 / CYC13 / CYC34</td><td>{post['cyc5']:.3f} / {post['cyc13']:.3f} / {post['cyc34']:.3f}</td><td>短成本线仍高于现价，13/34周期成本线在3.72元附近粘合。</td></tr>
<tr><td>CYS13 / CYS34</td><td>{post['cys13']:.2f}% / {post['cys34']:.2f}%</td><td>现价相对中期筹码成本仍为约-8.6%，尚未摆脱套牢区。</td></tr>
<tr><td>质量守恒</td><td>{primary['max_mass_error']:.2e}</td><td>远小于1e-8门槛；没有通过强制归一化掩盖链路错误。</td></tr>
</tbody></table></section>

<section><h2>状态判定：T8/T9可以成立为候选，但不是买卖指令</h2><div class="grid"><article class="card wide"><h3>T8：高位换手/承接失败风险——证据强</h3><p>事件脉冲后连续大换手，平均成本先上移至3.895元，价格却回落到3.40元；当前84%筹码浮亏。这支持高位筹码交换后供应滞留。它只能描述潜在结构，不能声称某个“主力账户”在派发。</p></article><article class="card wide"><h3>T9：高波动退潮后的博弈——候选</h3><p>20日仍上涨25.93%，5日却下跌9.09%，现价在MA60上但低于MA10/20，说明事件涨幅尚未完全消失、短线退潮也没有结束。多时间尺度冲突使NO_TRADE具有更高基准价值。</p></article></div>
<div class="callout" style="margin-top:15px"><b>不是T7趋势确认：</b>若要把它升级为可持续快速拉升结构，至少需要重新站稳3.72–3.76元、获利盘持续恢复到50%以上、换手不再伴随价格重心下移，并进一步消化4.07–4.11元压力。目前这些条件没有同时成立。</div></section>

<section><h2>三种后续路径：看条件，不猜庄</h2><table><thead><tr><th>路径</th><th>可验证条件</th><th>筹码含义</th><th>当前判断</th></tr></thead><tbody>
<tr><td><b>修复成立</b></td><td>收复并连续守住3.72–3.76；PR升破50%；回踩时成本中枢不再上压，换手趋于可控。</td><td>中央套牢盘被吸收，弱修复升级为结构修复。</td><td>未满足</td></tr>
<tr><td><b>区间消化</b></td><td>3.30–3.76之间反复，成本峰逐渐向3.4附近迁移，波动和换手下降。</td><td>用时间和换手消化上方筹码，但机会成本高。</td><td>较符合当前</td></tr>
<tr><td><b>退潮延续</b></td><td>有效跌破3.30，反抽不能收回；P10继续下移，PR再次靠近低个位数。</td><td>近端承接失败，先看3.20模型尾部，再评估2.70前低。</td><td>需防范</td></tr>
</tbody></table></section>

<section><h2>参数敏感性：结论不是调一个λ调出来的</h2><table><thead><tr><th>引擎</th><th>λ</th><th>获利盘</th><th>平均成本</th><th>P50</th><th>P90</th></tr></thead><tbody>{sensitivity_rows}</tbody></table><p class="small">三组模型的获利盘落在14.75%–18.57%，平均成本3.691–3.731元，P90为4.067–4.108元。数值有模型误差，但方向稳定。</p></section>

<section><h2>为什么之前生成不了，以及以后怎么自动处理</h2><p class="lead">原数据在ST撤销前后把交易状态/涨跌停规则写错，导致15个交易日状态冲突。筹码是递归状态，不能跳过几天后继续算，也不能靠归一化把错误抹平。</p><div class="flow">
<div><b>1. 冻结替代快照</b>按symbol与decision_at下载原始未复权日线，保存响应与manifest，禁止静默替换。</div>
<div><b>2. 多源审计</b>逐日核对OHLC、换手、停牌、ST状态；本次2088个重叠日OHLC一致。</div>
<div><b>3. 官方事件对账</b>用深交所/巨潮公告确认7月29日停牌、7月30日摘帽及10%涨跌幅。</div>
<div><b>4. 注册后重放</b>将修复资产CY-004登记到唯一allowlist，检查复权事件后从2018年因果重放。</div>
<div><b>5. 守恒与敏感性门</b>筹码质量误差≤1e-8且多模型方向一致，才发布筹码；否则继续fail closed。</div>
</div><div class="callout" style="margin-top:15px"><b>以后会处理：</b>同类异常不再停留在“数据坏了所以不算”。系统会先阻断错误输出，同时启动可审计修复链；只有来源、时点、规则、哈希、守恒都通过才恢复发布。修复失败时仍明确标记UNKNOWN，而不是编造筹码峰。</div></section>

<section><h2>基本面与事件风险：筹码修复不等于风险解除</h2><div class="grid"><article class="card"><div class="small">2026H1业绩预告</div><div class="metric red">预计继续亏损</div><p>公司公告口径：营收约5,500万–7,000万元；扣非净亏损约795万–895万元。经营反转尚未由盈利与现金流确认。</p></article><article class="card"><div class="small">2025基准</div><div class="metric">扣非亏损约6,704万元</div><p>期末净资产约8,701万元、未弥补亏损约6.56亿元，基本面缓冲仍薄。</p></article><article class="card"><div class="small">监管/调查</div><div class="metric red">风险仍激活</div><p>摘帽公告明确提示公司仍处于中国证监会立案调查期间。摘帽是交易规则变化，不等于调查结论落地。</p></article></div></section>

<section><h2>数据、可复现性与边界</h2><table><thead><tr><th>项目</th><th>状态</th><th>说明</th></tr></thead><tbody>
<tr><td>输入资产</td><td><span class="tag ok">CY-004</span></td><td>2095行，2018-01-02至2026-08-20；2042交易行、53停牌行；snapshot <span class="mono">{data['snapshot_id']}</span>。</td></tr>
<tr><td>交叉审计</td><td><span class="tag ok">PASS</span></td><td>与CY-003重叠2088行OHLC一致；换手最大差0.000104个百分点；识别旧状态冲突15日。</td></tr>
<tr><td>公司行动</td><td><span class="tag ok">PASS</span></td><td>QD-010显示2018年后无需要重置本次回放的000820公司行动。</td></tr>
<tr><td>点时等级</td><td><span class="tag no">PIT-B</span></td><td>可做条件研究，不得宣称严格PIT-A，不得进入实盘或自动订单。</td></tr>
<tr><td>缺失门</td><td><span class="tag no">NO_TRADE</span></td><td>当日大盘、点时行业剔除本股、盘口可成交性、调查结论、OOS概率与完整EdgeCard未同时通过。</td></tr>
</tbody></table>
<p class="small">原始数据：<a href="../data/raw/shenwu_000820_repair_20260820/baostock_daily/response.csv">CY-004 response.csv</a> · <a href="../data/audits/shenwu_000820_repair_20260820.json">交叉审计JSON</a> · <a href="shenwu_000820_chip_result_20260820.json">筹码结果JSON</a> · <a href="shenwu_000820_chip_distribution_20260820.csv">分布CSV</a> · <a href="https://static.cninfo.com.cn/finalpage/2026-07-29/1225445676.PDF">巨潮资讯摘帽公告</a></p></section>

<footer>本报告是截至decision_at的点时条件研究，不是投资建议。价格区间是验证/失效条件，不是收益承诺或下单指令。任何新增仓位必须另行通过大盘、行业、收益来源、替代解释、尾部风险与真实可成交性门控。</footer>
</main></body></html>"""
    OUTPUT.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
