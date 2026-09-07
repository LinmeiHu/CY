"""Read only registered action lineage. No inferred execution dates."""
import json
import subprocess
from pathlib import Path
import duckdb
import pandas as pd
from research.shared_capital_v1.run_shared_capital_v1 import HERE, ROOT, sha256


def run():
    out = HERE / 'output'
    reports = HERE / 'reports'; reports.mkdir(exist_ok=True)
    config = json.loads((HERE.parent / 'five_strategy_exit_risk_v1/input_config.json').read_text())
    source = Path(config['inputs']['qd010_distributions'])
    root = source.parent.parent
    manifest = json.loads((root / 'manifest.json').read_text())
    producer = root / manifest['normalization_runtime']['capture_producer']['sealed_path']
    assert sha256(producer) == manifest['normalization_runtime']['capture_producer']['sha256']
    assert sha256(source) == manifest['normalized_files']['distributions']['sha256']
    rows, hashes = [], {}
    def register(path):
        hashes[str(path)] = sha256(path)
        return hashes[str(path)]
    for path in (source, root/'manifest.json', root/'run_contract.json', producer):
        register(path)
    con = duckdb.connect()
    for symbol, day in [('600622', '2017-06-30'), ('603368', '2020-06-24'), ('600195', '2019-07-16')]:
        action = con.execute('SELECT * FROM read_parquet(?) WHERE symbol=? AND effective_date=?::DATE', [str(source),symbol,day]).fetchdf()
        assert len(action) == 1
        a = json.loads(action.to_json(orient='records', date_format='iso'))[0]
        rawpath, bodypath, receiptpath = [root / name / 'distribution' / (symbol + ext) for name,ext in [('raw','.parquet'),('responses','.json'),('receipts','.json')]]
        for p in (rawpath,bodypath,receiptpath): register(p)
        receipt = json.loads(receiptpath.read_text())
        assert hashes[str(rawpath)] == receipt['parquet_sha256']
        assert hashes[str(bodypath)] == receipt['response_body_sha256']
        body = json.loads(bodypath.read_text())
        raw = [r for r in body['records'] if r.get('F020D') == day]
        assert len(raw) == 1 and raw[0].get('F025D') is None and a['share_credit_date'] is None
        common = dict(symbol=symbol+'.SH', action_type=a['event_type'], announcement_date=a['announcement_date'],
            record_date=a['record_date'], ex_right_date=a['effective_date'], accounting_effective_date=None,
            share_arrival_date=None, listing_tradable_date=None, conversion_ratio=a['capitalized_share_ratio'],
            cash_per_share=a['cash_per_share_gross'], available_at=a['known_at'],
            available_at_semantics=a['known_at_semantics'], historical_revision_limit=a['knowledge_quality'],
            manifest=str(root/'manifest.json'), manifest_sha256=hashes[str(root/'manifest.json')],
            producer_code=str(producer), producer_sha256=hashes[str(producer)],
            status='CORPORATE_ACTION_STATE_UNRESOLVED')
        for layer,p,field,value,treatment in [
            ('NORMALIZED',source,'share_credit_date',None,a['execution_unresolved_reason']),
            ('OFFICIAL_RESPONSE',bodypath,'F025D',raw[0].get('F025D'),'source itself null; no dropped populated field'),
            ('RAW_PARQUET',rawpath,'股份到账日',None,'F025D preserved by explicit field map'),
            ('PRODUCER',producer,'execution_timing_resolved',False,'requires share_credit_date for share distributions'),
            ('CONTRACT',HERE/'contracts/initial_state_v05.json','missing_credit_state',None,'no ex-date/pay-date inference'),
        ]:
            rows.append({**common,'layer':layer,'source':str(p),'source_sha256':register(p),'field':field,'value':value,'downstream_treatment':treatment})
    con.close()
    history = subprocess.check_output(['git','log','--all','--format=%h %s','-S','missing_share_credit_date','--','*.py'],cwd=ROOT,text=True)
    (out/'ca_schema_history.txt').write_text(history)
    pd.DataFrame(rows).to_csv(out/'ca_600622_forensic.csv',index=False)
    pd.DataFrame([{'path':p,'sha256':h} for p,h in sorted(hashes.items())]).to_csv(out/'ca_forensic_input_hashes.csv',index=False)
    text = f'''# 600622 公司行动取证 V0.6

CORPORATE_ACTION_600622_STATUS = CORPORATE_ACTION_STATE_UNRESOLVED
ATRDR_CORPORATE_ACTION_DATA_STATUS = DATA_INPUT_MISSING

官方现有原始响应 p_sysapi1139 的 F025D 就是 null。它经封存生产代码映射到「股份到账日」，再成为 normalized/distributions.parquet.share_credit_date；不存在归一化漏取非空日期的证据。

2016 年报实施方案：2017-06-23 公告，2017-06-29 登记，2017-06-30 除权及派息，每 10 股转增 3 股、派 2.1 元。known_at 为 2017-06-24，含义为日期精度公告次日，并非抓取时刻。股份会计生效、到账、上市可交易的独立字段均未被证据解决，派息日也不是券商现金入账时刻。

精确缺失：该事件 F025D / share_credit_date，以及可验证的 tradable_date 或与到账绑定的冻结可交易状态规则。原始响应没有分红股份 listing 字段；rights_listing_date 属于配股另一事件类型，不能移用。登记权利可计量，不足以宣布新增股已到账可卖。不能以价格、收益对账或除权日反推。

证据层级 A：官方响应、raw、normalized 均未提供到账状态。B：已消费 daily 在除权日 corporate_action_valid=False、invalid_step_cum 改变，是阻塞标记而非到账转换。C：initial_state_v05 明确禁止推定；冻结执行路径只有坐标变化后阻塞，没有唯一到账规则。结论 D：保持未解决。

查询范围为当前 input config/manifest 注册 distributions、rights、daily 及该 vintage manifest 指向的原始响应、receipt、封存 producer；当前 Git 的 schema/producer 历史查询结果在 ca_schema_history.txt。既有 IFCGR 路由是公告目录及标题，不含该事件股份账户可交易状态，不把目录当执行证据。未联网、未新购数据、未运行其他工作树代码。

同样独立核实 603368.SH / 2020-06-24（MCB）与 600195.SH / 2019-07-16（ATRDR 重置诊断）F025D 也为空。MCB 的连续阻塞不依赖 ATRDR，因此不能如实填 CAUSALLY_VALIDATED。

来源：{source}
封存生产代码：{producer}
所有本次取证文件真实 SHA256 见 ca_forensic_input_hashes.csv，逐层日期、知识时点和处理见 ca_600622_forensic.csv。
'''
    (reports/'ca_600622_forensic.md').write_text(text)
    return rows


if __name__ == '__main__': run()
