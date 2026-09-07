# common_scheduler_accounting

唯一生产调度为 shared_account.scheduler.run_streams，资金会合由 NativeFunding 负责；物理总现金/持仓和虚拟 lot 每一步对账。开盘、分钟、14:57、close、record 尾部保留各自时点。SMV6 保留原生回调内卖出/调整/新买顺序，部分调整依赖先前实际成交，不能把未来回调请求提前制造出来。P0 与共享模式使用相同实现；P0禁借、共享保留策略归属现金（可负），物理总现金不可负，归属现金不代表第二个真实融资账户。

详见 ../REPORT.md 与相关 CSV。
