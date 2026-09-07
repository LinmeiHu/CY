"""Rule-selected discovery archetypes, full packets plus price-only index sheets."""
from packets import *


def overview(route, cases, coverage):
    fig,axes=plt.subplots(6,2,figsize=(13,17),squeeze=False)
    cats=list(C['galleries']['categories'])
    for row,category in enumerate(cats):
        group=[x for x in cases if x['category']==category]
        for j,ax in enumerate(axes[row]):
            ax.set_xlim(0,160);ax.set_ylim(.4,1.6);ax.axhline(1,color='#777',lw=.5);ax.grid(alpha=.2)
            if j>=len(group):
                ax.text(.5,.5,category+'\nNO ELIGIBLE CASE / NOT OPENED',ha='center',transform=ax.transAxes);continue
            case=group[j];p=pd.DataFrame(case['path'])
            ax.plot(p.age,p.close,color='#126782',lw=1.2)
            ax.plot(p.age,p.anchor,'--',color='#b5651d',lw=.8)
            ax.plot(p.age,p.target,':',color='#6a4c93',lw=.8)
            ax.scatter([0],[1],marker='>',color='black',s=20)
            ax.scatter([case['native_exit_age']],[case['native_exit_price']],marker='x',color='#d1495b')
            ax.plot([p.age.iloc[-1],case['native_exit_age']],[p.close.iloc[-1],case['native_exit_price']],':',color='#d1495b')
            ax.set_title(f"{case['case_id']} | {category} | net {case['native_return']:+.1%}\n{case['sampling_role']}",fontsize=9)
            inset=ax.inset_axes([.54,.50,.43,.42]);inset.plot(p.age,p.close,color='#126782',lw=1);inset.set_xlim(0,20);inset.set_ylim(.4,1.6);inset.set_yticks([]);inset.tick_params(labelsize=6);inset.set_title('fixed 0..20 zoom',fontsize=6)
    fig.suptitle(route+' | FULL-PATH-POSTMORTEM | DISCOVERY\nPrice-only index: all five-panel source packets are linked in manifest; no early prediction claim',fontsize=13)
    fig.tight_layout(rect=[0,0,1,.95]);p=OUT/'postmortem'/f'{route}_overview.png';fig.savefig(p,dpi=150);plt.close(fig)
    return p


def run():
    if not (HERE/'visual_outcome_reveal.csv').exists():raise RuntimeError('Finish and seal blind round first')
    states=discovery_states()
    loss=read_bound(OLD/'loss_episodes.parquet',"route<>'IFCGR' AND mature AND entry_date>=CASE WHEN route='OGR' THEN DATE '2018-01-01' ELSE DATE '2014-01-01' END AND native_time<CASE WHEN route='OGR' THEN DATE '2022-01-01' ELSE DATE '2021-01-01' END")
    smv=smv_source(states.loc[states.route.eq('SMV6'),'episode_id'])
    extrema=states.loc[states.route.eq('SMV6')].groupby('episode_id').agg(mae_observed=('mae_sofar','min'),mfe_observed=('mfe_sofar','max'))
    residual=smv.join(extrema).reset_index().rename(columns={'native_return':'native_net_return'})
    loss=pd.concat([loss,residual],ignore_index=True)
    selections=[];coverage=[]
    for route in ROUTES:
        d=loss.loc[loss.route.eq(route)].copy()
        if route!='SMV6':
            end=PC['splits'][route][2]
            stop=read_bound(OLD/f'events_{route}_fixed_0.1.parquet',f"native_time<DATE '{end}' AND (exit_time_policy IS NULL OR exit_time_policy<DATE '{end}')",'episode_id,filled,advantage_return')
            d=d.merge(stop,on='episode_id',validate='one_to_one')
        else:d['filled']=False;d['advantage_return']=np.nan
        masks={
            'severe_loss':d.native_net_return.le(-.10),
            'recovered_deep_winner':d.mae_observed.le(-.10)&d.native_net_return.ge(.05),
            'never_worked':d.mfe_observed.lt(.02)&d.native_net_return.lt(0),
            'worked_gave_back':d.mfe_observed.ge(.05)&d.native_net_return.le(0),
            'simple_stop_rescued':d.filled.fillna(False)&d.native_net_return.le(-.10)&d.advantage_return.gt(0),
            'simple_stop_harmed':d.filled.fillna(False)&d.native_net_return.ge(.05)&d.advantage_return.lt(0)}
        for category,mask in masks.items():
            group=d.loc[mask].copy();chosen=[]
            if len(group):
                group['median_distance']=(group.native_net_return-group.native_net_return.median()).abs()
                group['random_key']=group.episode_id.map(lambda x:token(category+'|'+x))
                first=group.sort_values(['median_distance','random_key']).iloc[0];chosen.append((first,'TYPICAL_MEDIAN'))
                rest=group.loc[group.episode_id.ne(first.episode_id)].sort_values('random_key')
                if len(rest):chosen.append((rest.iloc[0],'HASH_SAMPLED_VARIATION'))
            coverage.append(dict(route=route,category=category,eligible_episodes=len(group),selected=len(chosen),status='NOT_OPENED_SMV6_STOP_GRID' if route=='SMV6' and category.startswith('simple_') else 'SAMPLED' if chosen else 'EMPTY_NO_THRESHOLD_RELAXATION'))
            for r,role in chosen:
                selections.append(dict(r,category=category,sampling_role=role,case_id='POST_'+token(category+'|'+r.episode_id)[:8].upper()))
    choice=pd.DataFrame(selections);source=source_for(choice.episode_id);smv=smv_source(choice.episode_id)
    packets=[];manifest=[]
    for r in choice.itertuples(index=False):
        e=(smv if r.route=='SMV6' else source).loc[r.episode_id].copy();e['episode_id']=r.episode_id
        p=smv_path(e,e.native_time) if r.route=='SMV6' else stock_path(e,e.native_time)
        if p.empty:continue
        if r.route=='SMV6':
            end=pd.Timestamp(e.native_time).normalize();symbol=e.symbol
            fills=read_bound(OLD/'SMV6_current_events.parquet',f"symbol='{symbol}' AND trade_date=DATE '{end.date()}' AND event_type='SELL_FILLED'",'price_pre_adj')
            exitprice=float(fills.price_pre_adj.iloc[-1])/float(e.entry_price);exitage=float(p.age.max()+1)
        else:exitprice=float(e.exit_price)/float(e.entry_price);exitage=float(e.exit_cal_idx-e.entry_cal_idx)
        case=payload(p,r.case_id,p.age.max());case.update(route=r.route,category=r.category,sampling_role=r.sampling_role,native_return=r.native_net_return,native_exit_age=exitage,native_exit_price=exitprice)
        packets.append(case)
        manifest.append(dict(route=r.route,period='DISCOVERY',case_id=r.case_id,episode_id=r.episode_id,category=r.category,sampling_role=r.sampling_role,
            chart_type='FULL_PATH_POSTMORTEM',labels_visible=True,future_path_visible=True,observation_age=p.age.max(),
            native_time=r.native_time,native_return=r.native_net_return,price_clipped_points=int((p.low.lt(.4)|p.high.gt(1.6)).sum()),
            age_clipped_points=int(p.age.gt(160).sum())+int(exitage>160),source_packet=str(OUT/'postmortem'/f'{r.route}_{r.category}.png'),
            rs_available=bool(p.relative_strength.notna().any()),minute_available=bool(p.critical_change.notna().any()),purpose='FAILURE_ANATOMY_NOT_PREDICTIVE_VALIDATION'))
    for route in ROUTES:
        cases=[x for x in packets if x['route']==route]
        for category in C['galleries']['categories']:
            group=[x for x in cases if x['category']==category]
            if group:draw(group,'full',OUT/'postmortem'/f'{route}_{category}.png',post=True)
        overview(route,cases,coverage)
    write_json(OUT/'postmortem_payload.json',packets)
    pd.DataFrame(coverage).to_csv(HERE/'visual_gallery_coverage.csv',index=False)
    choice.to_parquet(OUT/'private/gallery_selection.parquet',index=False)
    old=pd.read_csv(HERE/'visual_case_manifest.csv')
    pd.concat([old.loc[old.chart_type.ne('FULL_PATH_POSTMORTEM')],pd.DataFrame(manifest)],ignore_index=True).to_csv(HERE/'visual_case_manifest.csv',index=False)
    log('DISCOVERY_GALLERIES_RENDERED',cases=len(packets),selection_sha256=digest(OUT/'private/gallery_selection.parquet'))
    print('Discovery archetype cases:',len(packets),'| full packets and price-only index sheets generated.')


if __name__=='__main__':run()
