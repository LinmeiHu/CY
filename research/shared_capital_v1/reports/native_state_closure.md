# 原生初始状态 V0.6

股票 ATRDR/MCB 从 2014 原生账户连续重放。ATRDR 两个正式边界均不可达；缺失字段写 JSON null，绝不以最后有效日状态或重置百万现金替代。MCB 2018 边界已和冻结原生 replay_sleeves 独立对比，2022 被它自己的 603368 公司行动阻塞。

OGR/IFCGR 保留原生 _replay_board 的 2018 账户起点，行情从 2013 预热，2022 延续账户权益。两条连续 2018–2023 账户与独立原生参考现金/NAV/敞口最大差小于 1e-6，2021 截断账户重放与延长回放前缀一致。已重建边界实际均为空仓，这来自回放结果；2022 现金不是 100 万。信号层 Gap 生命周期与 IFCGR 120 天公告窗继续使用原生历史输入，不在边界重置。

SMV6 原生 _run_callbacks 在每个独立区间调用 init，因此保留原生 reset。JSON 保存实际 init 后 context、集合字段类型列表与空持仓；before_trading 仍读取当前日之前的全部已注册历史。该状态是本地原生适配语义，未验证平台等价。

状态哈希覆盖有效标记及所有保存字段，未来 exit_date、最终收益和 outcome status 不作为已知初始状态保存。未解决状态也有文件哈希，但它不是有效账户状态。后续新出现 pending/nontradable 边界必须有完整事件转换凭证才能恢复，当前 P0 启动器拒绝缺失凭证。

```csv
strategy,period,reset_or_continuation,initial_cash,initial_nav,position_count,validation_status
ATRDR,2018_2021,NATIVE_CONTINUATION,,,,CORPORATE_ACTION_STATE_UNRESOLVED
ATRDR,2022_2023,NATIVE_CONTINUATION,,,,CORPORATE_ACTION_STATE_UNRESOLVED
MCB,2018_2021,NATIVE_CONTINUATION,1312987.896579233,1312987.896579233,0.0,VALIDATED
MCB,2022_2023,NATIVE_CONTINUATION,,,,CORPORATE_ACTION_STATE_UNRESOLVED
OGR,2018_2021,NATIVE_ACCOUNT_ORIGIN_RESET,1000000.0,1000000.0,0.0,VALIDATED
OGR,2022_2023,NATIVE_CONTINUATION,1110169.4677651073,1110169.4677651073,0.0,VALIDATED
IFCGR,2018_2021,NATIVE_ACCOUNT_ORIGIN_RESET,1000000.0,1000000.0,0.0,VALIDATED
IFCGR,2022_2023,NATIVE_CONTINUATION,1105177.2081431411,1105177.2081431411,0.0,VALIDATED
SMV6,2018_2021,NATIVE_CALLBACK_INIT_RESET,1000000.0,1000000.0,0.0,VALIDATED
SMV6,2022_2023,NATIVE_CALLBACK_INIT_RESET,1000000.0,1000000.0,0.0,VALIDATED
```
