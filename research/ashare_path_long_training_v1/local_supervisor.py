"""One local research owner: process-exit events, durable decisions and bounded recovery.

ponytail: a finite, auditable mechanism ladder, not an autonomous hypothesis-generating LLM.
Unknown bugs return NEEDS_AGENT_REPAIR to the existing app watchdog, never a fake verdict.
"""
import argparse, contextlib, fcntl, os, select, subprocess, time
from pathlib import Path
if __name__=='__main__' and not Path('/Volumes/quant').is_mount():
    raise RuntimeError('External data volume not mounted; stop before importing data helpers')
from common import *
from risk_incrementality import contract

PY='/opt/anaconda3/bin/python'
CARD='FORWARD_DEVELOPMENT'
STATE='SUPERVISOR_STATE.json'
EVENTS=HERE/'SUPERVISOR_EVENTS.jsonl'

def read(name,default=None):
    p=HERE/name
    return json.loads(p.read_text()) if p.exists() else default

def emit(event,**kw):
    row=dict(at=now(),event=event,pid=os.getpid(),**kw)
    # Single supervisor writer, each append is one OS write.
    fd=os.open(EVENTS,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    try:os.write(fd,(json.dumps(row,ensure_ascii=False,default=str)+'\n').encode())
    finally:os.close(fd)

def processes():
    out=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True)
    result={}
    for line in out.splitlines():
        fields=line.strip().split(None,2)
        if len(fields)==3:result[int(fields[0])]=dict(ppid=int(fields[1]),command=fields[2])
    return result

def born(pid):
    return subprocess.run(['ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True).stdout.strip()

def wait_exit(pid,timeout=60):
    """kqueue handles pre-existing non-child processes too; timeout is a fallback audit."""
    if not born(pid):return 'ALREADY_EXITED'
    try:
        with contextlib.closing(select.kqueue()) as q:
            event=select.kevent(pid,filter=select.KQ_FILTER_PROC,flags=select.KQ_EV_ADD|select.KQ_EV_ONESHOT,fflags=select.KQ_NOTE_EXIT)
            return 'PROCESS_EXIT' if q.control([event],1,timeout) else 'WATCHDOG_TIMEOUT'
    except ProcessLookupError:return 'ALREADY_EXITED'
    except OSError:
        time.sleep(min(timeout,2));return 'EVENT_REGISTRATION_RETRY'

@contextlib.contextmanager
def exclusive(path,blocking=False):
    f=open(path,'a+')
    try:
        fcntl.flock(f,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB));yield f
    finally:f.close()

def model_names(phase,seed=17):
    family='M1_PATHRISK' if phase=='path_risk' else 'M1_FULLFACTOR' if phase in ('factor','factor_control') else 'M1_OFFSET'
    suffix='_RECENT8' if phase=='recent' else '_FACTOROFF' if phase=='factor_control' else ''
    return [f'{family}_{y}_s{seed}_O{3 if phase=="ranking" else 2}{suffix}_B32768' for y in [2022,2023]]

def account_path(names,card=CARD,gross=False):
    return '__'.join(names)+'_'+card+('_GROSS' if gross else '_NET')+'_ACCOUNT.json'

def verified_account(name):
    obj=read(name)
    if obj and obj['status']=='BLOCKED_AT_ACTUAL_HELD_FACT':
        replacement=read('ACCOUNT_REPLACEMENTS.json',{}).get(name)
        if replacement:
            assert sha(HERE/name)==replacement['original_sha256']
            target=HERE/replacement['replacement'];assert target.parent==HERE
            assert sha(target)==replacement['replacement_sha256']
            repaired=read(target.name);identity=repaired['input_identity']['corporate_action_supplement']
            assert identity['original_report_sha256']==replacement['original_sha256']
            assert identity['pre_gap_exact_prefix_parity']
            assert identity['original_prediction_sha256']==obj['input_identity']['predictions'][0]['sha256']
            assert identity['registry_sha256']==sha(HERE/'ACTION_SUPPLEMENT_REGISTRY.json')
            from action_supplement import load_registration
            registration,source=load_registration()
            assert identity['changed_event']==obj['block']['event_id']==registration['event_id']
            assert obj['block']['missing']==[identity['changed_field']]==['share_credit_date']
            assert identity['source_pdf_sha256']==source['sha256']
            assert identity['source_manifest_sha256']==registration['source_manifest_sha256']
            obj=repaired
    if not obj or obj['status']!='COMPLETE_RESEARCH_ACCOUNT':return False
    assert obj['verification']['exact_cash_inventory_nav']
    for b in obj['input_identity']['predictions']:assert sha(b['path'])==b['sha256'], 'Account prediction identity mismatch'
    return True

def phase_complete(phase,seed=17):
    names=model_names(phase,seed)
    for n in names:
        m=read(n+'_TRAINING.json')
        if not m or m['steps']!=32768:return False
        assert sha(OUT/(n+'.pt'))==m['checkpoint_sha256']
        assert m['coverage']['anniversary_gate'] and all(x['actual_draws']>0 for x in m['actual_annual_sampling'])
        for gross in [False,True]:
            if not verified_account(account_path([n],'TRAIN_FITTED_DIAGNOSTIC_ONLY',gross)):return False
    for gross in [False,True]:
        if not verified_account(account_path(names,gross=gross)):return False
    if phase=='path_risk':
        for gross in [False,True]:
            if not verified_account(account_path([n+'_RISKGATE' for n in names],gross=gross)):return False
    return True

def metrics(phase,seed=17):
    return read(account_path(model_names(phase,seed)))['verification']['full_period_metrics']

def material(candidate,base,rules):
    gain=candidate['cagr']-base['cagr'];risk=candidate['maxdd']-base['maxdd']
    return (gain>=rules['cagr'] and risk>=0) or (risk>=rules['maxdd_reduction'] and gain>=-rules['cagr_tolerance'])

def meets(m,c):
    return m['cagr']>=c['targets']['cagr'] and m['maxdd']>=-c['targets']['max_drawdown'] and all(x['net_return']>=c['targets']['full_year_return'] for x in m['annual'])

def action_log_path(script,args):
    # Arguments can include a complete JSON command; filesystem basenames are bounded.
    identity=hashlib.sha256(json.dumps([script,*map(str,args)]).encode()).hexdigest()[:16]
    return HERE/f'supervisor_{Path(script).stem}_{identity}.log'

def review_revision(done,c):
    return hashlib.sha256(json.dumps([c['version'],sorted(k for k in done if not k.startswith('bottleneck_review_'))]).encode()).hexdigest()[:16]

def choose(facts,done,c):
    """Pure state machine tested independently of the real training process."""
    if 'A_verified' not in done:return ('verify_A',None)
    for phase in ['recent','path_risk']:
        if not facts.get(phase):return ('stage',phase)
        if 'assess_'+phase not in done:return ('assess',phase)
    risk=facts.get('risk')
    if risk is None:return ('risk_test',17)
    if risk['risk_information'] and risk.get('return_preservation'):
        for mode in ['A','B']:
            if 'risk_decision_17_'+mode not in done:return ('risk_decision',(17,False,mode))
    if c.get('network_diagnosis_required'):
        if 'network_diagnostic' not in done:return ('network_diagnostic',None)
        return ('architecture_next',None)
    if facts.get('risk_gain'):
        for seed in [29,43]:
            if not facts.get('path_risk_'+str(seed)):return ('replicate_risk',seed)
            if 'risk_test_'+str(seed) not in done:return ('risk_test',seed)
            sr=facts.get('risk_'+str(seed),{})
            if sr.get('risk_information') and sr.get('return_preservation'):
                for mode in ['A','B']:
                    if f'risk_decision_{seed}_{mode}' not in done:return ('risk_decision',(seed,False,mode))
        if 'risk_replication' not in done:return ('assess_replication',None)
    for phase in ['ranking','factor','factor_control']:
        if facts.get(phase) and 'assess_'+phase not in done:return ('assess',phase)
    revision=review_revision(done,c);review=facts.get('review')
    if not review or review.get('revision')!=revision:return ('bottleneck_review',revision)
    action,arg=review['selected_action']
    return action,arg

def current_facts():
    f={p:phase_complete(p) for p in ['recent','path_risk','ranking','factor','factor_control']}
    f['review']=read('NEXT_EXPERIMENT.json')
    f['risk']=read('PATHRISK_s17_CONDITIONAL_RISK.json')
    f['probe_risk']=read('FROZENRISK_s17_CONDITIONAL_RISK.json');f['risk_gain']=False
    for mode in ['A','B']:
        comp=read(f'PATHRISK_s17_{mode}_DECISION_COMPARISON.json')
        if comp and comp['matching_status']=='EXPOSURE_MATCHED' and comp.get('selected_control'):
            rule=contract()['material_gain'];f['risk_gain']|=all(material(comp['ranking_metrics'],b,rule) for b in [comp['return_only_metrics'],comp['original_32k_metrics'],comp['selected_control']['metrics']])
    if f['risk_gain']:
        for seed in [29,43]:f['path_risk_'+str(seed)]=phase_complete('path_risk',seed);f['risk_'+str(seed)]=read(f'PATHRISK_s{seed}_CONDITIONAL_RISK.json')
    return f

class Supervisor:
    def __init__(self):
        self.c=contract();self.s=read(STATE,dict(done=[],actions=[],status='NEW'))
        assert self.c['started_at']==read('STATE.json')['started_at']
        self.s.update(pid=os.getpid(),process_started=born(os.getpid()),contract_sha256=sha(HERE/'RESEARCH_CONTRACT.md'))
        self.save()
    def save(self):self.s['updated_at']=now();dump(STATE,self.s)
    def record(self,key,reason,expectation,result,adoption):
        if key not in self.s['done']:self.s['done'].append(key)
        row=dict(key=key,reason=reason,expectation=expectation,result=result,adoption=adoption,
                 contract_sha256=sha(HERE/'RESEARCH_CONTRACT.md'),diagnosis_sha256=sha(HERE/'DIAGNOSIS_AND_REPAIRS.md'))
        self.s['actions'].append(dict(at=now(),**row));self.save();emit('RESEARCH_DECISION',**row)
        with (HERE/'DIAGNOSIS_AND_REPAIRS.md').open('a') as f:f.write(f'\n\n{now()} — {key}\n\n原因：{reason}\n\n预期：{expectation}\n\n结果：{json.dumps(result,ensure_ascii=False)}\n\n判断：{adoption}\n')
    def external(self):
        ps=processes()
        for pid,p in ps.items():
            if pid==os.getpid():continue
            if str(HERE/'run_stage.py') in p['command'] and not p['command'].startswith('/bin/'):
                return pid
        state=read('STATE.json')
        for k in ['supervisor_pid','worker_pid']:
            pid=state.get(k)
            if pid!=os.getpid() and pid in ps and str(HERE) in ps[pid]['command']:return pid
        return None
    def execute(self,script,*args):
        command=[PY,'-u',str(HERE/script),*map(str,args)];key=script+'_'+('_'.join(map(str,args)) or 'default')
        logfile=action_log_path(script,args)
        self.s.update(status='EXECUTING',next_command=command,current_action=key);self.save()
        with logfile.open('a') as logf:
            child=subprocess.Popen(command,cwd=ROOT,stdout=logf,stderr=subprocess.STDOUT,start_new_session=True)
            self.s.update(child_pid=child.pid,child_birth=born(child.pid),current_log=str(logfile));self.save();emit('ACTION_START',command=command,child_pid=child.pid,log=str(logfile))
            code=child.wait()
        self.s.update(child_pid=None,child_birth=None,last_exit_code=code);self.save();emit('ACTION_END',command=command,returncode=code)
        if code:raise RuntimeError(f'Action failed ({code}); inspect {logfile}')
    def summaries(self):
        for script in ['round_metrics.py','diagnose.py','report.py']:self.execute(script)
    def verify_a(self):
        evidence=[]
        for seed in self.c['seeds']:
            assert phase_complete('extend',seed), f'A incomplete seed{seed}; do not retrain automatically'
        for y in [2022,2023]:
            n=f'M1_OFFSET_{y}_ENSEMBLE3_O2_B32768';m=read(n+'_ENSEMBLE.json');assert m and m['seeds']==[17,29,43]
            for line in m['lineage']:
                for b in line['inputs']:assert sha(b['path'])==b['sha256']
                assert sha(OUT/f'{n}_{line["card"]}_pred.parquet')==line['output_sha256']
            for gross in [False,True]:assert verified_account(account_path([n],'TRAIN_FITTED_DIAGNOSTIC_ONLY',gross))
            evidence.append(dict(name=n,manifest_sha256=sha(HERE/(n+'_ENSEMBLE.json'))))
        ns=[f'M1_OFFSET_{y}_ENSEMBLE3_O2_B32768' for y in [2022,2023]]
        for gross in [False,True]:assert verified_account(account_path(ns,gross=gross))
        self.summaries();self.record('A_verified','用户优先级A已有完整产物，先核验身份，禁止重训','三seed两折和等权净毛账户完整',evidence,'COMPLETE_VERIFIED_NO_RESTART')
    def assess(self,phase):
        self.summaries();m=metrics(phase);base=metrics('extend');gain=material(m,base,self.c['material_gain'])
        reason={'recent':'长期共同成分可能漂移；只改变温和近期采样','path_risk':'终点收益不反映持有期风险；先完成原账户，再做条件风险检验','factor':'三线性Ridge输出未必保留完整普通因子信息','factor_control':'区分普通因子信息增量与额外容量','ranking':'风险或因子接口不足后，检验同日排序目标与头部决策错配'}[phase]
        adoption='MATERIAL_GAIN_REQUIRES_REPLICATION' if gain else 'NO_MATERIAL_JOINT_GAIN; continue path-risk mechanism'
        if phase=='recent' and not gain:adoption='RECENCY_BRANCH_CLOSED_NO_MORE_DECAY_SEARCH'
        self.record('assess_'+phase,reason,'开发收益与风险相对同账户控制改善；收益回撤与年度目标分别判断',dict(metrics=m,baseline=base,material_gain=gain,targets_met=meets(m,self.c)),adoption)
        # A strong positive result is an agent review trigger, never an automatic live promotion.
        if meets(m,self.c):emit('CANDIDATE_NEEDS_FREEZE_REPLAY',phase=phase,metrics=m)
    def recover_stage(self):
        s=read('STATE.json')
        if s['status'] not in ['RUNNING','JOB_FAILED_NEEDS_REPAIR','BUDGET_CHECKPOINT']:return False
        if not s.get('jobs') or all(j['status']=='COMPLETE' for j in s['jobs']):return False
        with exclusive(OUT/'supervisor.lock'):
            if self.external():return False
            for i,j in enumerate(s['jobs']):
                if j['status']=='COMPLETE':continue
                if datetime.datetime.now(datetime.timezone.utc)>=datetime.datetime.fromisoformat(s['batch_deadline']):return False
                command=j['command'];script=Path(command[0]).name
                assert Path(command[0]).parent==HERE
                attempts=j.get('supervisor_recovery_attempts',0)
                if attempts>=2:raise RuntimeError('Repeated stage failure needs agent repair; no blind retry')
                # Do not overwrite a complete final checkpoint by reinitializing a model.
                if script=='train.py':
                    self.execute('recover_training.py','--check-command',json.dumps(command))
                j.update(status='RUNNING',supervisor_recovery_attempts=attempts+1,started_at=now());s.update(supervisor_pid=os.getpid(),worker_pid=None,current_command=[PY,*command]);dump('STATE.json',s)
                try:
                    if script=='train.py':self.execute('recover_training.py','--run-command',json.dumps(command))
                    else:self.execute(script,*command[1:])
                except Exception:
                    j['status']='FAILED';s.update(status='JOB_FAILED_NEEDS_REPAIR',supervisor_pid=None,worker_pid=None);dump('STATE.json',s);raise
                j.update(status='COMPLETE',returncode=0,finished_at=now());dump('STATE.json',s)
            s.update(status='STAGE_COMPLETE_REQUIRES_DIAGNOSIS',worker_pid=None,supervisor_pid=None,current_command=None);dump('STATE.json',s)
            emit('STAGE_RECOVERED',phase=s['phase']);return True
    def run(self,once=False):
        emit('SUPERVISOR_STARTED',state_sha256=sha(HERE/'STATE.json'),mode='kqueue process-exit; serial result-driven actions')
        # Adopt an orphan action on launchd restart; no duplicate trainer/account writer.
        pid=self.s.get('child_pid')
        if pid and born(pid)==self.s.get('child_birth'):
            emit('ADOPT_ORPHAN_ACTION',pid_to_watch=pid)
            while born(pid)==self.s.get('child_birth'):wait_exit(pid)
            self.s.update(child_pid=None,child_birth=None);self.save()
        while True:
            now_=datetime.datetime.now(datetime.timezone.utc)
            if now_>=datetime.datetime.fromisoformat(self.c['hard_deadline']):
                self.s.update(status='RESOURCE_CHECKPOINT_WITH_BEST',next_command=[PY,str(HERE/'local_supervisor.py')]);self.save();emit('RESOURCE_CHECKPOINT',reason='Original hard deadline reached; budget not reset');return
            # A mapped-file SIGBUS and simultaneous ENOMEM occurred during training.
            # Never hash old prediction files or run full-history summaries while a stage owns compute.
            external_pid=self.external()
            if external_pid:
                self.s.update(status='WAITING_PROCESS_EXIT',observed_stage=read('STATE.json')['phase'],observed_pid=external_pid);self.save()
                if once:return
                event=wait_exit(external_pid)
                if event!='WATCHDOG_TIMEOUT':emit(event,observed_pid=external_pid)
                continue
            facts=current_facts();action,arg=choose(facts,set(self.s['done']),self.c)
            self.s.update(status='DECIDING',next_action=[action,arg]);self.save()
            if action in ['stage','replicate_risk']:
                pid=self.external()
                if pid:
                    self.s.update(status='WAITING_PROCESS_EXIT',observed_stage=read('STATE.json')['phase'],observed_pid=pid,next_action=[action,arg]);self.save()
                    if once:return
                    event=wait_exit(pid)
                    if event!='WATCHDOG_TIMEOUT':emit(event,observed_pid=pid)
                    continue
                # Existing one-shot C queue gets first opportunity to acquire its original lock.
                adoption=read('SUPERVISOR_PREFLIGHT.json',{})
                queue=adoption.get('queued_process',{});qid=queue.get('pid')
                if qid and born(qid)==queue.get('birth'):
                    if once:return
                    wait_exit(qid,2);continue
                if self.recover_stage():continue
                s=read('STATE.json')
                if now_>=datetime.datetime.fromisoformat(s['batch_deadline']):
                    with exclusive(OUT/'supervisor.lock'):
                        s=read('STATE.json');s['batch_deadline']=self.c['hard_deadline'];s['budget_extension_reason']='Predeclared path-risk mechanism still unresolved; bounded continuation within original96h';dump('STATE.json',s)
                    emit('SOFT_BATCH_EXTENDED',hard_deadline=self.c['hard_deadline'],clock_reset=False)
                phase=arg if action=='stage' else 'path_risk';seed=17 if action=='stage' else arg
                assert phase in self.c['allowed_phases']
                self.execute('run_stage.py','--phase',phase,'--seed',seed,'--steps',self.c['steps'])
            elif action=='verify_A':self.verify_a()
            elif action=='assess':self.assess(arg)
            elif action=='risk_test':
                self.execute('risk_incrementality.py','--seed',arg);r=read(f'PATHRISK_s{arg}_CONDITIONAL_RISK.json')
                self.record('risk_test_'+str(arg),'检验相似预测Ret20下是否存在独立风险排序信息','同日期收益分组内的风险秩相关、MAE和大回撤差异跨年一致',r,'PROCEED_TO_ONE_RISK_RANKING' if r['risk_information'] else 'REJECT_RISK_RANKING_FOR_THIS_SEED; examine next mechanism')
            elif action=='risk_decision':
                seed,probe,mode=arg;self.execute('risk_decision.py','--seed',seed,'--mode',mode,*(['--probe'] if probe else []));self.summaries();r=read(f'{"FROZENRISK" if probe else "PATHRISK"}_s{seed}_{mode}_DECISION_COMPARISON.json')
                self.record(f'{"probe_decision" if probe else "risk_decision"}_{seed}_{mode}','风险信息通过后检验真实排序增量与单纯降低敞口','原32k、同预测return-only、risk-ranking与同敞口简单降仓比较',r,'ACCOUNT_EVIDENCE_RECORDED; preserved-return joint gain rule determines replication')
            elif action=='assess_replication':
                result={str(seed):dict(risk=read(f'PATHRISK_s{seed}_CONDITIONAL_RISK.json'),policies=[read(f'PATHRISK_s{seed}_{mode}_DECISION_COMPARISON.json') for mode in ['A','B']]) for seed in [17,29,43]}
                self.record('risk_replication','风险账户重要改善需排除随机种子选择','三个种子同方向经济增量',result,'REQUIRES_AGENT_FREEZE_ADJUDICATION; no automatic candidate promotion')
            elif action=='root_diagnosis':
                self.execute('round_metrics.py');self.execute('risk_root_diagnostic.py');r=read('PATH_RISK_ROOT_DIAGNOSTIC.json')
                self.record('root_diagnosis','用户收紧主线：保留收益Alpha，定位路径风险来源','按实际共同下跌、持仓相关性、极端损失、持仓时间及集中度证据选择单一修复',r,r['next_mechanism'])
            elif action=='frozen_probe':
                self.execute('frozen_risk_probe.py','--seed',17)
                self.record('frozen_probe','共享multi-task风险头无稳定信息，检查表征是否含风险信息及目标冲突','冻结原return-only编码器和所有收益预测，仅拟合概率与MAE探针',dict(manifests=[str(HERE/f'M1_FROZENRISK_{y}_s17_RISK_PROBE.json') for y in [2022,2023]]),'PROBE_FIT_COMPLETE; no return alpha changed')
            elif action=='probe_risk_test':
                self.execute('risk_incrementality.py','--seed',17,'--probe');r=read('FROZENRISK_s17_CONDITIONAL_RISK.json')
                self.record('probe_risk_test','冻结收益表征探针时间外开发检验','条件风险排序与Ret20保留同时评价',r,'PROCEED_TO_LIMITED_POLICY' if r['risk_information'] and r.get('return_preservation') else 'RISK_PROBE_NOT_ADMITTED; compression/capacity diagnosis remains, not a global no-alpha verdict')
            elif action=='network_diagnostic':
                self.execute('network_diagnostics.py');r=read('NETWORK_DIAGNOSTIC_RESULT.json')
                self.record('network_diagnostic','A/B没有改善原收益回撤前沿；用户要求先定位网络瓶颈','冻结checkpoint诊断seed、时间依赖、scale与收益风险梯度；不更新模型',r,'CHECKPOINT_DIAGNOSTICS_COMPLETE; measured evidence guides next repair')
            elif action=='architecture_next':
                if not (HERE/'architecture_next.py').exists():
                    self.s.update(status='NEEDS_AGENT_REPAIR',reason='Implement measured architecture continuation; no research-complete verdict');self.save();return
                self.execute('architecture_next.py')
                self.s.update(status='NEEDS_AGENT_REPAIR',reason='Read architecture next experiment evidence and implement next bounded repair');self.save();return
            elif action=='bottleneck_review':
                self.execute('bottleneck_review.py','--done',json.dumps(self.s['done']));r=read('NEXT_EXPERIMENT.json')
                self.record('bottleneck_review_'+arg,'最高目标：受控回撤下提高扣费账户收益；重新比较Alpha/泛化与风险瓶颈','选择当前证据最支持、最能区分根因的单项实验',r,'NEXT_ACTION_SELECTED_FROM_CURRENT_EVIDENCE; no permanent risk-only branch')
            else:
                self.s.update(status='NEEDS_AGENT_REPAIR',reason=arg,next_command=[PY,str(HERE/'local_supervisor.py')]);self.save();emit('NEEDS_AGENT_REPAIR',reason=arg);return
            if once:return

def main():
    p=argparse.ArgumentParser();p.add_argument('--once',action='store_true');a=p.parse_args()
    if not Path('/Volumes/quant').is_mount():raise RuntimeError('External data volume is not mounted; do not fabricate local replacement')
    try:
        with exclusive(HERE/'local_supervisor.lock'):
            supervisor=Supervisor()
            if supervisor.s.get('status')=='NEEDS_AGENT_REPAIR' and not a.once:return
            try:supervisor.run(a.once)
            except Exception as e:
                supervisor.s.update(status='NEEDS_AGENT_REPAIR',error=repr(e),next_command=supervisor.s.get('next_command'));supervisor.save();emit('SUPERVISOR_ERROR',error=repr(e));raise
    except BlockingIOError:return

if __name__=='__main__':main()
