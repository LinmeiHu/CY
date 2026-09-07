"""Assemble read-only manifests, review index and final quantitative figure."""
from packets import *
from quantify import check_freeze
import html
import shutil


def run():
    check_freeze()
    m=pd.read_csv(HERE/'visual_case_manifest.csv')
    payload=json.loads((OUT/'blind_payload.json').read_text())+json.loads((OUT/'postmortem_payload.json').read_text())
    for case in payload:
        p=pd.DataFrame(case['path']);ix=m.case_id.eq(case['case_id'])
        m.loc[ix,'volume_clipped_points']=int((p.volume_entry.gt(5)|p.volume_prior5.gt(5)).sum())
        m.loc[ix,'rs_clipped_points']=int(pd.to_numeric(p.relative_strength,errors='coerce').abs().gt(.3).sum())
        m.loc[ix,'minute_clipped_points']=int(pd.to_numeric(p.critical_change,errors='coerce').abs().gt(.03).sum())
    errors=pd.concat([pd.read_csv(HERE/n) for n in ['visual_model_error_cases.csv','visual_complete_state_error_cases.csv']],ignore_index=True)
    src=read_bound(OLD/'all_source_normalized.parquet',"route IN ('ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR') AND entry_date>=CASE WHEN route='OGR' THEN DATE '2022-01-01' ELSE DATE '2021-01-01' END AND native_time<DATE '2024-01-01'")
    src=src.loc[src.episode_id.isin(errors.episode_id)].drop_duplicates('episode_id').set_index('episode_id')
    for r in errors.itertuples(index=False):
        e=src.loc[r.episode_id].copy();e['episode_id']=r.episode_id;p=stock_path(e,e.native_time);ix=m.case_id.eq(r.case_id)
        m.loc[ix,'volume_clipped_points']=int((p.volume_entry.gt(5)|p.volume_prior5.gt(5)).sum())
        m.loc[ix,['rs_clipped_points','minute_clipped_points']]=0
    blind=m.chart_type.eq('DECISION_TIME_BLIND_SNAPSHOT')
    m.loc[blind,'source_packet']=m.loc[blind,'route'].map(lambda r:str(OUT/'blind'/f'{r}_full.png'))
    m['clipped_count_unit']='BAR_ROWS; raw inputs/features remain unclipped'
    m['legal_sell_start_contract']=m.route.map(lambda r:'SMV6_LOCAL_POLICY_NEXT_SESSION; EXCHANGE_NATIVE_ELIGIBILITY_UNVERIFIED' if r=='SMV6' else 'T_PLUS_1_ELIGIBILITY; ACTUAL_OPEN_TRADABILITY_NOT_ASSUMED')
    m.to_csv(HERE/'visual_case_manifest.csv',index=False)
    exp=pd.read_csv(HERE/'visual_exposure_manifest.csv');seen=set(exp.image_path.dropna())
    render=[]
    for p in sorted(OUT.rglob('*.png')):
        render.append(dict(path=str(p),bytes=p.stat().st_size,sha256=digest(p),actually_viewed_by_astra=str(p) in seen,
            purpose='DISCOVERY_BLIND_PACKET' if p.parent.name=='blind' else 'DISCOVERY_POSTMORTEM' if p.parent.name=='postmortem' else 'SIMPLE_RISK_READ_ONLY_COUNTEREXAMPLES' if p.parent.name=='risk_counterexamples' else 'FROZEN_TEMPORAL_ERROR_ANALYSIS'))
    pd.DataFrame(render).to_csv(HERE/'visual_render_manifest.csv',index=False)
    reps=HERE/'representative_figures';reps.mkdir(exist_ok=True)
    for route in ROUTES:shutil.copy2(OUT/'blind'/f'{route}_full.png',reps/f'{route}_blind_full.png')
    a=pd.read_csv(HERE/'visual_admission.csv');fig,axes=plt.subplots(1,2,figsize=(12,4.2))
    routes=list(a.route.unique());y=np.arange(len(routes))
    for phase,offset,color in [('DISCOVERY',-.12,'#126782'),('CONSUMED_TEMPORAL',.12,'#d17a22')]:
        g=a.loc[a.phase.eq(phase)].set_index('route').loc[routes]
        axes[0].scatter(g.mse_gain_b0*1e4,y+offset,color=color,label=phase)
        axes[1].scatter(g.mse_gain_price*1e4,y+offset,color=color,label=phase)
    for ax,title in zip(axes,['Visual representation vs B0','Visual representation vs price control']):
        ax.axvline(0,color='#777',lw=1);ax.set_yticks(y,labels=routes,fontsize=8);ax.invert_yaxis();ax.set_xlim(-.65,.25);ax.grid(alpha=.2);ax.set_title(title);ax.set_xlabel('MSE improvement x 10,000 (positive is better)')
    axes[0].legend(fontsize=7);fig.suptitle('No motif passes the frozen admission gate | consumed history, not untouched OOS');fig.tight_layout();fig.savefig(reps/'visual_quantitative_summary.png',dpi=160);plt.close(fig)
    matrix=[]
    for route in ROUTES+['IFCGR']:
        status='VISUAL_MOTIF_ADDS_NO_INCREMENTAL_INFORMATION' if route in set(a.route) else 'NO_STABLE_VISUAL_FAILURE_MOTIF'
        if route=='IFCGR':status='OGR_INHERITED_NO_INDEPENDENT_VISUAL_EVIDENCE'
        matrix.append(dict(route=route,visual_status=status,robust_state_feature=False,mechanism_exit_candidate='NONE',visual_mechanism_account_replay='NOT_ACTIVATED_NO_ADMITTED_VISUAL_POLICY',simple_risk_account_review='risk_account_comparison.csv',
            inherited_blocker='ATRDR_PRODUCTION_PREFIX_QUARANTINE' if route.startswith('ATRDR') else 'NATIVE_PLATFORM_EQUIVALENCE_UNVERIFIED' if route=='SMV6' else 'PIT_B_ISSUER_COMPLETENESS_UNRESOLVED' if route=='IFCGR' else 'NONE_NEW',current_policy_changed=False))
    pd.DataFrame(matrix).to_csv(HERE/'visual_decision_matrix.csv',index=False)
    pd.DataFrame([dict(category=x,status='NOT_APPLICABLE_NO_MECHANISM_EXIT_CANDIDATE') for x in ['CANDIDATE_TRIGGER_NATIVE_BIG_WIN','CANDIDATE_NO_TRIGGER_NATIVE_SEVERE_LOSS','SAME_PRICE_PATH_OPPOSITE_STATE','SIMILAR_STATE_OPPOSITE_FUTURE']]).to_csv(HERE/'visual_policy_counterexample_scope.csv',index=False)
    # Index opens only discovery blind images by default; other groups require a human click.
    sections=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>Astra视觉研究图册</title><style>body{font:16px system-ui;max-width:1200px;margin:36px auto;color:#233}img{max-width:100%}summary{cursor:pointer;padding:14px;background:#eef2f5;margin:8px 0}a{margin-right:16px}p{line-height:1.7}</style>',
      '<h1>Astra视觉失败机制研究</h1><p>本轮无机制型退出候选。先匿名前缀观察，再揭晓发现段结果，冻结假说后才读取新的后段图。既有路线结果已被消费，不能称为独立盲验证。此索引为已完成研究的回顾入口。</p>']
    for route in ROUTES:
        sections.append(f'<details><summary>{route} · 匿名前缀 / 信息遮挡</summary>')
        for variant in ['price_only','price_volume','price_rs','full']:
            if variant=='price_rs' and route!='SMV6':continue
            sections.append(f'<p>{variant}</p><img loading="lazy" src="blind/{route}_{variant}.png">')
        sections.append('</details>')
    for route in ROUTES:
        sections.append(f'<details><summary>显示未来结果 · {route} 发现段完整路径</summary><img loading="lazy" src="postmortem/{route}_overview.png">')
        for category in C['galleries']['categories']:
            p=OUT/'postmortem'/f'{route}_{category}.png'
            if p.exists():sections.append(f'<p><a href="postmortem/{p.name}">{category} 五面板</a></p>')
        sections.append('</details>')
    for route in a.route.unique():
        sections.append(f'<details><summary>冻结后误差分析 · {route}（含未来）</summary><img loading="lazy" src="temporal_complete_errors/{route}.png"></details>')
    for p in sorted((OUT/'risk_counterexamples').glob('*.png')):
        sections.append(f'<details><summary>风险优先补充 · {p.stem} 既定简单政策反例（含未来）</summary><img loading="lazy" src="risk_counterexamples/{p.name}"></details>')
    sections.append('</html>');(OUT/'index.html').write_text('\n'.join(sections))
    selected=pd.read_csv(HERE/'visual_outcome_reveal.csv');pred=pd.read_parquet(OUT/'visual_predictions.parquet')
    overlap=[]
    for (route,phase),g in pred.groupby(['route','phase']):
        overlap.append(dict(route=route,phase=phase,visual_discovery_episode_overlap=g.loc[g.episode_id.isin(selected.episode_id),'episode_id'].nunique(),evidence='DISCOVERY_REUSE_OR_CONSUMED_TEMPORAL; no pristine OOS'))
    pd.DataFrame(overlap).to_csv(HERE/'visual_discovery_reuse_audit.csv',index=False)
    log('DELIVERABLES_ASSEMBLED',image_files=len(render),actual_astra_image_views=sum(x['actually_viewed_by_astra'] for x in render),mechanism_candidates=0)
    print(json.dumps(dict(images=len(render),actually_viewed=sum(x['actually_viewed_by_astra'] for x in render),case_entries=len(m),external_root=str(OUT))))


if __name__=='__main__':run()
