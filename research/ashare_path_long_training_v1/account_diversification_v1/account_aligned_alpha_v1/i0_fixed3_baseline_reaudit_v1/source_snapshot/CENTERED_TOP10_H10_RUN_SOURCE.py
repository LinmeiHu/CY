def run(policy,signals,market,actions,dates,symbols,forecast_through=None,ranker=None,stagger=False,stagger_scale=D(1), resume_path=None, save_before_t=None, snapshot_path=None, entitlement_branch=None):
 assert D(0)<NEW_POSITION_WEIGHT<=D('.1')
 assert D(0)<stagger_scale<=D(1) and (stagger or stagger_scale==D(1))
 assert not signals.duplicated(['t','j']).any()
 sy={s[:6]:j for j,s in enumerate(symbols)};records=defaultdict(list);effective=defaultdict(list)
 for a in actions.to_dict('records'):
  if a['symbol'] not in sy:continue
  if pd.notna(a['record_date']):records[str(a['record_date'].date())].append(a)
  if pd.notna(a['effective_date']):effective[str(a['effective_date'].date())].append(a)
 action_rows=actions.to_dict('records');risk_by_t=defaultdict(set)
 for event in action_rows:
  known=event.get('known_at');rd=event.get('record_date')
  if pd.isna(rd):rd=event.get('effective_date')
  j=sy.get(event['symbol'])
  if j is None or pd.isna(known) or pd.isna(rd):continue
  risk_t=int(np.searchsorted(dates,str(rd.date())))
  first=max(0,risk_t-21,int(np.searchsorted(dates,str(known.date()))))
  for u in range(first,min(risk_t+1,len(dates))):
   if known<=pd.Timestamp(dates[u])+pd.Timedelta(hours=15) and str(rd.date())>=dates[u]:risk_by_t[u].add(j)
 schedule={int(t):g.sort_values(['score','j'],ascending=[False,True]) for t,g in signals.groupby('t')}
 cash=D(1000000);navprev=cash;positions={};rights=[];nav=[];flows=[];orders=[];inventory=[];inventory_events=[];planned=[];block=None;lot_inventory=[];lot_fills=[];all_lots=[];lot_actions=[]
 resume_t=0
 if resume_path is not None:
  with open(resume_path,'rb') as f:snap=pickle.load(f)
  assert snap['dates']==dates and snap['symbols']==symbols
  cash,navprev,positions,rights,nav,flows,orders,inventory,inventory_events,planned,lot_inventory,lot_fills,all_lots,lot_actions= snap['state']
  resume_t=snap['t']
 def move(t,kind,amount,j=-1,event=''):
  nonlocal cash
  cash+=amount;flows.append(dict(t=t,date=dates[t],kind=kind,cash_delta=str(amount),j=j,event_id=event,cash_after=str(cash)))
 def reserve():return sum((a['reserve'] for a in rights if not a['settled']),D(0))
 for t,day in enumerate(dates):
  if day<START_DATE or t<resume_t:continue
  if t==save_before_t:
   with open(str(snapshot_path)+'.tmp','wb') as f:pickle.dump(dict(t=t,dates=dates,symbols=symbols,state=(cash,navprev,positions,rights,nav,flows,orders,inventory,inventory_events,planned,lot_inventory,lot_fills,all_lots,lot_actions)),f,protocol=5)
   Path(str(snapshot_path)+'.tmp').replace(snapshot_path)
   break
  if forecast_through is not None and t>forecast_through:break
  try:
   try:
    allocations=resolve_event(rights,t,day,entitlement_branch) if entitlement_branch is not None else {}
   except BranchRequired as need:
    with open(str(snapshot_path)+'.tmp','wb') as f:pickle.dump(dict(t=t,dates=dates,symbols=symbols,state=(cash,navprev,positions,rights,nav,flows,orders,inventory,inventory_events,planned,lot_inventory,lot_fills,all_lots,lot_actions)),f,protocol=5)
    Path(str(snapshot_path)+'.tmp').replace(snapshot_path)
    block=dict(reason='ENTITLEMENT_BRANCH_REQUIRED',**need.evidence);break
   # Position entitlements were enrolled on an observed record-date close.
   for a in rights:
    src=a['source'];p=a['position'];ex=str(src['effective_date'].date())
    if day==ex and not a['effective']:
     if pd.isna(src['known_at']) or src['known_at']>pd.Timestamp(day)+pd.Timedelta(hours=9,minutes=15):raise AccountGap('ACTION_NOT_KNOWN_PREOPEN:'+src['event_id'])
     extra=dec(a['base_q'])*(dec(src['share_multiplier'])-1)
     if (src['event_id'],p['lot_id']) in allocations:extra=D(allocations[(src['event_id'],p['lot_id'])])
     if extra!=extra.to_integral_value():raise AccountGap('EXACT_FRACTIONAL_SHARE_ALLOCATION_UNKNOWN:'+src['event_id'])
     a['extra']=int(extra);p['pending']+=int(extra);inventory_events.append(dict(t=t,j=p['j'],kind='EX_ENTITLEMENT',delta=int(extra),event_id=src['event_id']));a['receivable']=dec(a['base_q'])*dec(src['cash_per_share_gross']);a['effective']=True
     lot_actions.append(dict(t=t,lot_id=p['lot_id'],j=p['j'],event_id=src['event_id'],kind='EX_ENTITLEMENT',delta=int(extra),receivable=str(a['receivable'])))
     bonus=src.get('bonus_share_ratio',0.)
     if pd.isna(bonus):
      if dec(src['share_multiplier'])>1:raise AccountGap('BONUS_TAX_TERMS_UNKNOWN:'+src['event_id'])
      bonus=0.
     a['tax_base']=dec(a['base_q'])*(dec(src['cash_per_share_gross'])+dec(bonus));a['reserve']=a['tax_base']*maximum_dividend_rate(str(src['record_date'].date()))
    if a['effective'] and not a['credited'] and (a['extra']==0 or day>=str(src['share_credit_date'].date())):
     p['q']+=a['extra'];p['pending']-=a['extra'];a['credited']=True
     lot_actions.append(dict(t=t,lot_id=p['lot_id'],j=p['j'],event_id=src['event_id'],kind='SHARE_CREDIT',delta=0,quantity=a['extra']))
    if a['effective'] and not a['paid'] and (a['receivable']==0 or day>=str(src['pay_date'].date())):
     lot_actions.append(dict(t=t,lot_id=p['lot_id'],j=p['j'],event_id=src['event_id'],kind='DIVIDEND_PAYMENT',delta=0,cash_delta=str(a['receivable'])))
     move(t,'DIVIDEND_PAYMENT',a['receivable'],p['j'],src['event_id']);a['receivable']=D(0);a['paid']=True
   # Unknown ex-date events cannot be bypassed by a missing record-date row.
   for a in effective.get(day,[]):
    j=sy[a['symbol']]
    if any(p['j']==j and p['entry_t']<t for p in positions.values()):
     if a.get('event_type')=='rights_issue':raise AccountGap('RIGHTS_EXECUTION_UNSUPPORTED:'+a['event_id'])
     if not any(r['source']['event_id']==a['event_id'] for r in rights):raise AccountGap('MISSING_RECORD_OWNERSHIP:'+a['event_id'])
   # Sell actual available shares first. Buy reservations do not assume these proceeds.
   due=defaultdict(list)
   for lot_id,p in positions.items():
    if t>=p['due'] and t>p['entry_t']:
     p.setdefault('first_requested_exit_t',t);due[p['j']].append((lot_id,p))
   for j,group in due.items():
    if not get('exitok')[t,j]:
     orders.append(dict(t=t,j=j,side='SELL',status='RETRY_BLOCKED'));continue
    total=sum(p['q'] for _,p in group)
    if total:
     op=dec(get('open')[t,j]);charge=fees(dec(total)*op,day,True,total,symbols[j]);move(t,'SELL',dec(total)*op-charge,j)
     orders.append(dict(t=t,j=j,side='SELL',status='FILLED',quantity=total,price=str(op)))
     inventory_events.append(dict(t=t,j=j,kind='SELL',delta=-total,event_id=''))
     nonzero=[(lid,p) for lid,p in group if p['q']]
     for (lid,p),allocated in zip(nonzero,allocate_fee(charge,[p['q'] for _,p in nonzero])):
      qty=p['q']
      lot_fills.append(dict(t=t,lot_id=lid,j=j,side='SELL',quantity=qty,price=str(op),fees=str(allocated),cash_delta=str(dec(qty)*op-allocated)))
      p['q']=0;p['last_sale_t']=t
    for lot_id,p in group:
     if p['pending']==0:
      acquired=pd.Timestamp(dates[p['entry_t']]);today=pd.Timestamp(day)
      for a in rights:
       if a['position'] is p and not a['settled']:
        liability=a['tax_base']*dividend_rate(acquired,today,str(a['source']['record_date'].date()));move(t,'DIVIDEND_TAX',-liability,j,a['source']['event_id']);a['reserve']=D(0);a['settled']=True
        lot_actions.append(dict(t=t,lot_id=p['lot_id'],j=j,event_id=a['source']['event_id'],kind='DIVIDEND_TAX',delta=0,cash_delta=str(-liability)))
      p['actual_exit_t']=t;del positions[lot_id]
   for q in planned:
    j=q['j'];base=dict(t=t,decision_t=q['decision_t'],j=j,side='BUY',quantity=q['q'],limit=str(q['limit']),decision_nav=str(q['decision_nav']),reserved=str(q['reserve']))
    if not stagger and (j in positions or len(positions)>=10):orders.append(dict(base,status='SLOT_OR_HELD'));continue
    if not get('entryok')[t,j]:orders.append(dict(base,status='CANCELLED_UNBUYABLE'));continue
    op=dec(get('open')[t,j])
    if q['limit']>dec(market['up_limit_price'][t,j]):orders.append(dict(base,status='CANCELLED_LIMIT_OUTSIDE_EXCHANGE_RANGE'));continue
    if op>q['limit']:orders.append(dict(base,status='CANCELLED_ABOVE_LIMIT'));continue
    debit=dec(q['q'])*op+fees(dec(q['q'])*op,day,quantity=q['q'],symbol=symbols[j])
    if debit>q['reserve'] or debit>cash-reserve():orders.append(dict(base,status='CANCELLED_ACTUAL_FEE_EXCEEDS_RESERVATION'));continue
    assert dec(q['q'])*op<=q['decision_nav']*((D('.05')*D(20)/D(10)/D(10)) if stagger else D('.1'))
    if stagger and dec(sum(p['q']+p['pending'] for p in positions.values() if p['j']==j)+q['q'])*op>q['decision_nav']*D('.1'):
     orders.append(dict(base,status='CANCELLED_AGGREGATE_CAP'));continue
    move(t,'BUY',-debit,j);lid=f"{q['decision_t']}:{j}" if stagger else j
    p=dict(lot_id=lid,j=j,q=q['q'],initial_q=q['q'],pending=0,signal_t=q['decision_t'],entry_t=t,scheduled_expiry=t+10,due=t+10,entry_price=str(op),entry_cost=str(debit))
    positions[lid]=p;all_lots.append(p);lot_fills.append(dict(t=t,lot_id=lid,j=j,side='BUY',quantity=q['q'],price=str(op),fees=str(debit-dec(q['q'])*op),cash_delta=str(-debit)))
    orders.append(dict(base,status='FILLED',price=str(op),debit=str(debit)));inventory_events.append(dict(t=t,j=j,kind='BUY',delta=q['q'],event_id=''))
   planned=[]
   for a in records.get(day,[]):
    j=sy[a['symbol']]
    held=[p for p in positions.values() if p['j']==j]
    if not held:continue
    if a.get('event_type')=='rights_issue':raise AccountGap('HELD_RIGHTS_UNSUPPORTED:'+a['event_id'])
    missing=[]
    if pd.isna(a['known_at']) or a['known_at']>pd.Timestamp(day)+pd.Timedelta(hours=15):missing.append('known_at')
    if pd.isna(a['effective_date']):missing.append('effective_date')
    if float(a['share_multiplier'])>1 and pd.isna(a['share_credit_date']):missing.append('share_credit_date')
    if float(a['cash_per_share_gross'])>0 and pd.isna(a['pay_date']):missing.append('pay_date')
    if missing:
     block=dict(policy=policy,date=day,j=j,symbol=symbols[j],event_id=a['event_id'],missing=missing,held_quantity=sum(p['q']+p['pending'] for p in held),entry_date=dates[min(p['entry_t'] for p in held)],source_response_sha256=a['response_sha256'])
     raise AccountGap('HELD_ACTION_MISSING:'+a['event_id']+':'+','.join(missing))
    for p in held:rights.append(dict(source=a,position=p,base_q=p['q']+p['pending'],extra=0,effective=False,credited=False,paid=False,settled=False,receivable=D(0),tax_base=D(0),reserve=D(0)))
   mv=D(0);physical={}
   for lid,p in positions.items():
    j=p['j'];px=get('close')[t,j]
    if not np.isfinite(px) or px<=0:raise AccountGap('HELD_VALUATION_MISSING:'+symbols[j]+':'+day)
    value=dec(p['q']+p['pending'])*dec(px);mv+=value
    lot_inventory.append(dict(t=t,date=day,lot_id=lid,j=j,available_q=p['q'],pending_q=p['pending'],close=str(dec(px)),value=str(value),entry_t=p['entry_t'],signal_t=p['signal_t'],scheduled_expiry=p['scheduled_expiry'],due=p['due']))
    if j not in physical:physical[j]=dict(t=t,date=day,j=j,available_q=0,pending_q=0,close=str(dec(px)),value=D(0))
    z=physical[j];z['available_q']+=p['q'];z['pending_q']+=p['pending'];z['value']+=value
   for z in physical.values():z['value']=str(z['value']);inventory.append(z)
   receivable=sum((a['receivable'] for a in rights),D(0));free=cash-reserve();navnow=free+mv+receivable
   if t==normalize_t:
    adjustment=D(1000000)-navnow
    if free+adjustment<0:raise AccountGap('NORMALIZATION_NEGATIVE_CASH')
    move(t,'ANNUAL_CAPITAL_NORMALIZATION',adjustment);free=cash-reserve();navnow=free+mv+receivable
   assert free>=0 and navnow>0 and mv<=navnow and (stagger or len(positions)<=10)
   assert cash==D(1000000)+sum((dec(f['cash_delta']) for f in flows),D(0))
   nav.append(dict(date=day,t=t,book_cash=str(cash),tax_reserve=str(reserve()),cash=str(free),market_value=str(mv),receivable=str(receivable),nav=str(navnow),holdings=len(physical)))
   if stagger:nav[-1].update(live_lots=len(positions),live_cohorts=len({p['signal_t'] for p in positions.values()}),over_cap_stocks=sum(dec(v['value'])>navnow*D('.1') for v in physical.values()))
   # One predeclared operational policy: after an action is known, exit next
   # open if within the holding horizon. Apply identically to every model.
   known_risks=risk_by_t.get(t,set())
   for p in positions.values():
    if p['j'] in known_risks:p['due']=min(p['due'],t+1)
   # Next-open share orders precommitted from this decision's NAV, cash, and slots.
   # Freeze price cap from today's close and known rule; no future opening price in sizing.
   # If tomorrow's legal range differs (e.g. ex-date), cancel the invalid frozen limit.
   day_scale=scale_for(t);available=min(free,navnow*(D('.05')*D(20)/D(10))*day_scale) if stagger else free;slots=10 if stagger else 10-len(positions)
   if t in schedule and t+1<len(dates):
    candidates=schedule[t] if ranker is None else ranker(schedule[t],t,day,navnow,free,market,symbols)
    assert sorted(candidates.j.tolist())==sorted(schedule[t].j.tolist())
    for candidate_rank,r in enumerate(candidates.itertuples(),1):
     j=int(r.j)
     if (not stagger and j in positions) or j in known_risks or len(planned)>=slots:continue
     close=dec(get('close')[t,j]);pct=market['limit_pct'][t,j]
     if not np.isfinite(pct) or pct<=0:continue
     cap=(close*(1+dec(pct))).quantize(D('.01'),rounding=ROUND_HALF_UP)
     budget=min(navnow*((D('.05')*D(20)/D(10)/D(10))*day_scale if stagger else NEW_POSITION_WEIGHT),available,dec(np.exp(r.logamount20))*D('.01'))
     if stagger:
      existing=sum(p['q']+p['pending'] for p in positions.values() if p['j']==j)
      budget=min(budget,max(D(0),navnow*D('.1')-dec(existing)*cap))
     audit=dict(t=t,j=j,candidate_rank=candidate_rank,nav=str(navnow),available=str(available),budget_after_cap=str(budget),existing_q=existing,cap=str(cap),single_name_room=str(max(D(0),navnow*D('.1')-dec(existing)*cap)),per_name_budget=str(navnow*(D('.05')*D(20)/D(10)/D(10))*day_scale),live_lots=sum(p['j']==j for p in positions.values()));qty=size(budget,cap,day,symbols[j]);audit.update(quantity=qty,status='PLANNED' if qty else 'ZERO_SIZE');planning_audit.append(audit)
     if qty==0:continue
     held=dec(qty)*cap+fees(dec(qty)*cap,day,quantity=qty,symbol=symbols[j]);available-=held
     planned.append(dict(j=j,q=qty,limit=cap,reserve=held,decision_t=t,decision_nav=navnow))
   navprev=navnow
  except AccountGap as err:
   block=block or dict(policy=policy,date=day,reason=str(err))
   block['reason']=str(err);break
 pd.DataFrame(lot_inventory).to_parquet(OUT/f'{policy}_funded_prefix_lot_inventory.parquet',index=False)
 pd.DataFrame(lot_actions).to_parquet(OUT/f'{policy}_funded_prefix_lot_actions.parquet',index=False)
 pd.DataFrame(lot_fills).to_parquet(OUT/f'{policy}_funded_prefix_lot_fills.parquet',index=False)
 pd.DataFrame(all_lots).to_parquet(OUT/f'{policy}_funded_prefix_lots.parquet',index=False)
 pd.DataFrame(inventory).to_parquet(OUT/f'{policy}_funded_prefix_inventory.parquet',index=False);pd.DataFrame(inventory_events).to_parquet(OUT/f'{policy}_funded_prefix_inventory_events.parquet',index=False)
 pd.DataFrame(nav).to_parquet(OUT/f'{policy}_funded_prefix_nav.parquet',index=False);pd.DataFrame(orders).to_parquet(OUT/f'{policy}_funded_prefix_orders.parquet',index=False);pd.DataFrame(flows).to_parquet(OUT/f'{policy}_funded_prefix_cashflows.parquet',index=False)
 return dict(policy=policy,status='ENTITLEMENT_BRANCH_REQUIRED' if block and block.get('reason')=='ENTITLEMENT_BRANCH_REQUIRED' else 'STATE_REHYDRATION_CHECKPOINT' if save_before_t is not None else 'BLOCKED_AT_ACTUAL_HELD_FACT' if block else ('PARTIAL_FORECAST_STREAM' if forecast_through is not None and forecast_through<len(dates)-1 else 'COMPLETE_RESEARCH_ACCOUNT'),block=block,verified_prefix_days=len(nav),filled_buys=sum(o['side']=='BUY' and o['status']=='FILLED' for o in orders),filled_sells=sum(o['side']=='SELL' and o['status']=='FILLED' for o in orders),full_period_metrics=None if save_before_t is not None or block or (forecast_through is not None and forecast_through<len(dates)-1) else {'final_nav':float(nav[-1]['nav']) if nav else 1e6},cash_identity='EXACT_DECIMAL',cost_semantics=f'Historical stamp and dividend regimes; conservative pre-2013 SH transfer envelope; commission 3bp min5 and execution charge5bp x{FRICTION_MULTIPLIER}; gross={GROSS}')
