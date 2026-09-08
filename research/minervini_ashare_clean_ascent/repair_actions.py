"""Fetch exact missing issuer documents; accept only explicit matched date rows."""
import subprocess,json,re
from pathlib import Path
from urllib.parse import urlencode
import pandas as pd
from .common import HERE,OUT,sha,dump
from .replay import load_actions

def curl(url,p,data=None,referer=None):
    cmd=['curl','-L','--compressed','--fail','--max-time','30','-sS',url,'-o',str(p)]
    if data:cmd+=['-d',urlencode(data)]
    if referer:cmd+=['-H','Referer: '+referer]
    subprocess.run(cmd,check=True)

def run():
    root=OUT/'official_ca';root.mkdir(exist_ok=True);a=load_actions().set_index('event_id');gaps=pd.concat([pd.read_csv(p) for p in OUT.glob('*/action_gaps.csv')]).drop_duplicates('action_id')
    facts=pd.read_csv(HERE/'action_backfill.csv');sources=json.loads((HERE/'official_sources.json').read_text());known=set(facts.action_id)
    for row in gaps.to_dict('records'):
        aid=row['action_id']
        if aid in known:continue
        z=a.loc[aid];sym=z.symbol;day=str(z.announcement_date.date());start=str((z.announcement_date-pd.Timedelta(days=1)).date());p=root/f'{sym}_{day}_repair.json'
        params=dict(pageNum=1,pageSize=30,column='szse' if sym.startswith(('00','30')) else 'sse',tabName='fulltext',searchkey=sym,seDate=f'{start}~{day}',isHLtitle='false')
        if not p.exists():curl('https://www.cninfo.com.cn/new/hisAnnouncement/query',p,params,'https://www.cninfo.com.cn/')
        d=json.loads(p.read_text());candidates=[x for x in d.get('announcements') or [] if x['secCode']==sym and any(k in x['announcementTitle'] for k in ['权益分派实施公告','权益分配实施公告','利润分配实施公告'])]
        url='https://static.cninfo.com.cn/'+candidates[0]['adjunctUrl'] if len(candidates)==1 else None
        grade='OFFICIAL_EX_POST_EXECUTION_FACT'
        if url is None:
            ep=root/f'{sym}_{day}_eastmoney.json';params=dict(sr=-1,page_size=50,page_index=1,ann_type='A',client_source='web',stock_list=sym,begin_time=start,end_time=day)
            if not ep.exists():curl('https://np-anotice-stock.eastmoney.com/api/security/ann?'+urlencode(params),ep)
            ed=json.loads(ep.read_text());cs=[x for x in ed.get('data',{}).get('list',[]) if any(k in x['title'] for k in ['权益分派实施公告','权益分配实施公告','利润分配实施公告'])]
            if len(cs)!=1:print('NO_DOCUMENT',sym,day,flush=True);continue
            url='https://pdf.dfcfw.com/pdf/H2_'+cs[0]['art_code']+'_1.pdf';grade='ISSUER_ORIGINAL_DOCUMENT_MIRROR'
        pdf=root/f'{sym}_{day}_repair.pdf';txt=pdf.with_suffix('.txt')
        if not pdf.exists():curl(url,pdf)
        if not pdf.read_bytes().startswith(b'%PDF'):print('NOT_PDF',sym,flush=True);continue
        if not txt.exists():
            with txt.open('w') as f:subprocess.run(['/Users/linmei/.local/bin/markitdown',str(pdf)],stdout=f,check=True)
        text=txt.read_text();flat=re.sub(r'\s+','',text);tr=None;pay=None;excerpt=''
        # Shenzhen explicitly states starting trade day in prose.
        hit=re.search(r'(?:起始交易日|上市流通日)[^。]{0,12}?(20\d{2})年(\d{1,2})月(\d{1,2})日',flat)
        if hit:tr=pd.Timestamp('-'.join(hit.groups()));excerpt=hit.group()
        # Shanghai tabular dates: explicit header followed by record/ex/tradable/payment.
        normalized=re.sub(r'\s+',' ',text)
        for head in re.finditer(r'上\s*市\s*日',normalized):
            seg=normalized[head.end():head.end()+450]
            dates=[pd.Timestamp(f'{y}-{mo}-{d}') for y,mo,d in re.findall(r'(20\d{2})\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})(?:日)?',seg)]
            if len(dates)>=4 and dates[0]==z.record_date and dates[1]==z.effective_date and dates[2]>=dates[1]:tr=dates[2];pay=dates[3];excerpt=seg;break
        source=dict(action_id=aid,symbol=sym,document_date=day,source_url=url,raw_path=str(pdf),raw_hash=sha(pdf),text_path=str(txt),text_hash=sha(txt),grade=grade,alpha_use='PROHIBITED',date_evidence=excerpt)
        sources.append(source)
        if tr is None:print('MANUAL_DATE_REVIEW',sym,day,str(txt),flush=True);continue
        fact=dict(action_id=aid,tradable_date=str(tr.date()),cash_payment_date=str(pay.date()) if pay is not None else '',source_url=url,raw_hash=sha(pdf));facts=pd.concat([facts,pd.DataFrame([fact])],ignore_index=True)
        print('VERIFIED_EXPLICIT_DATES',sym,day,fact['tradable_date'],fact['cash_payment_date'],flush=True)
    facts.drop_duplicates('action_id',keep='last').to_csv(HERE/'action_backfill.csv',index=False);dump(HERE/'official_sources.json',list({x['action_id']:x for x in sources}.values()))
if __name__=='__main__':run()
