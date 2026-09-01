# ASHARE-INDUSTRY-LEAD-FOLLOW-CYCLE-013

## Claim boundary

Consumed 2018--2023 development history only. This is not OOS, independent confirmation, validation, live, or production evidence. Post-2023 outcomes and CY-011 were not read.

## Frozen causal contract

A strict event is the first industry-day threshold occurrence: one stock alone has leave-one-out industry-abnormal one-minute return at least 1%, has positive raw return, is the unique maximum, and closes at least one tick below its historical upper limit. Multiple same-minute triggers are unresolved simultaneous clusters. The completed minute is signal formation only.

Followers are all non-triggered peers. Windows are t+1--t+3, t+4--t+10, and t+1--close. Controls come only from the prior 60 market sessions in the same PIT industry and exact clock minute, have no earlier same-day trigger, and are matched on contemporaneous market return, industry return, breadth, and prior liquidity. No future control outcome enters matching.

## Phase A result

Classification: `SIMULTANEOUS_COMOVEMENT_ONLY`.

Strict events: 16,224; matched: 3,526; coverage: 21.73%; industries: 81; decision dates: 1136.

The full matched event/control means make the falsification concrete. Event peers returned +0.0451% abnormal over t+1--t+3 versus +0.0157% for controls, a +0.0294% delta. Positive-breadth expansion was +12.942% versus +6.638%, and new-trigger participation was 0.625% versus 0.330%. But the already-completed t-3--t-1 event/control return delta was larger at +0.0403%.

| Period | Events | Industries | Dates | w1--3 return delta | w1--3 breadth delta | w1--3 new-trigger delta | reverse return delta | w4--10 return delta | remainder return delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full | 3,526 | 81 | 1136 | +0.0294% | +6.304% | +0.295% | +0.0403% | +0.0075% | +0.0668% |
| early | 1,952 | 62 | 586 | +0.0329% | +7.016% | +0.446% | +0.0347% | +0.0019% | +0.0948% |
| late | 1,574 | 66 | 550 | +0.0251% | +5.421% | +0.108% | +0.0474% | +0.0143% | +0.0321% |

Future-minus-reverse falsification margin: -0.0110%.

The return and breadth deltas clear their frozen magnitudes and are positive in both blocks. Confirmation still fails because future response is smaller than reverse-time association, new-trigger expansion is +0.295 pp versus the +0.500 pp floor, and match coverage is 21.73% versus the 80% floor. Positive later-window deltas therefore remain descriptive and do not override the all-required causal gate.

## Advancement decision

Phase A did not clear the preregistered confirmation gate. Per the frozen stopping rule, leader identity, leader/follower action testing, portfolio replay, and Industry Diffusion timing analysis were not accessed.

The corrected full event/control panel is stored outside Git at `/Volumes/quant/CY_quant_research/industry_lead_follow_cycle_013/event_panel.parquet` (16,224 rows, 3,375,628 bytes, SHA-256 `22de762d16160cbb7934da076458ed3026e2ababd4cb41eb146e5459a42bb542`). The implementation audit disqualified 116,251 industry-days whose first threshold occurrence lay outside the preregistered event clock rather than relabeling a later mover as leader. All bound CY-006, CY-008, and QD-004 source partition content hashes passed before checkpointing.

## Family conclusion

Family status: `SIMULTANEOUS_COMOVEMENT_ONLY`. The minute data do not support any stronger within-minute or causal claim than the frozen classification permits.
