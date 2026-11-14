"""调度器（REQ-F-014，PRD 10.1-10.4）：打分 → 并行/串行派发 → 超时 → 重试 → 熔断。

与 `workflow/` 一样只做纯逻辑、不 import ORM：任务快照由调用方给、状态回写走回调，
这样既能在单测里跑几百次 tick，也不和队友 B 的会话/事务边界打架。

对外三件套：
    scorer.score_task / scorer.rank   —— 10.3 打分公式
    breaker.Breaker                   —— 10.4 设备维度熔断
    scheduler.Scheduler.tick()        —— 10.1 一轮循环（1s 一次，由主程序驱动）
"""
