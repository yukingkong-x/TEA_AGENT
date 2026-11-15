"""REQ-F-018:反馈修正(PRD 11.4)。

**规则引擎,不调 LLM** —— 诊断必须 100% 可复现,现场翻车就没有第二次机会。
三条规则按优先级判,先判「数据可疑」再判「补多少」:数据可疑时补水只会越补越糟。
"""
from __future__ import annotations

from dataclasses import dataclass, field

GAP_SPLIT = 15.0        # 缺口 >15 走分次灌溉
SPLIT_FACTOR = 0.67     # 分次时单次时长 = 原时长 × 0.67
SPLIT_TIMES = 2
SPLIT_INTERVAL = 60     # 间隔 60s
TOPUP_BASE = 10         # 单次补灌 = 10 + 缺口 s


@dataclass
class Correction:
    strategy: str                    # split / topup / suspect_data / give_up
    reason: str                      # 一句话诊断,报告页直接展示
    duration_s: float = 0.0
    times: int = 0
    interval_s: int = 0
    payload: dict = field(default_factory=dict)

    @property
    def is_action(self) -> bool:
        """是否需要真的下发设备指令(suspect_data 只复核、give_up 不动设备)。"""
        return self.strategy in {"split", "topup"}


def diagnose(
    *,
    baseline: float,
    measured: float,
    target_low: float,
    target_high: float,
    duration_s: float,
    round_no: int = 1,
    max_rounds: int = 2,
) -> Correction:
    """给出下一轮修正方案;无法修正时返回 strategy=give_up(由调用方转人工)。"""
    gap = round(target_low - measured, 2)

    if measured <= baseline:
        return Correction(
            strategy="suspect_data",
            reason=(f"浇水后复测 {measured}% 未高于基线 {baseline}%,先复核数据再补水"
                    f"(疑似设备异常或探针未入土)"),
            payload={"action": "read_now", "times": 2,
                     "target_range": [target_low, target_high]},
        )

    if round_no >= max_rounds:
        return Correction(
            strategy="give_up",
            reason=f"已完成 {round_no} 轮修正仍未达标(缺口 {gap}%),转人工处理",
        )

    if gap > GAP_SPLIT:
        # 整秒:设备层 `_clamp_params` 会把 duration_s 转成 int(硬件只认整秒),
        # 这里给 20.1 的话执行时变 20、载荷里却仍写 20.1,报告两列自相矛盾。
        duration = max(1.0, float(round(duration_s * SPLIT_FACTOR)))
        return Correction(
            strategy="split",
            reason=f"缺口 {gap}% 超过 {GAP_SPLIT}%,分 {SPLIT_TIMES} 次灌溉,单次 {duration}s、间隔 {SPLIT_INTERVAL}s",
            duration_s=duration,
            times=SPLIT_TIMES,
            interval_s=SPLIT_INTERVAL,
            payload={"action": "pump", "duration_s": duration, "times": SPLIT_TIMES,
                     "interval_s": SPLIT_INTERVAL, "target_range": [target_low, target_high],
                     "baseline": measured},
        )

    duration = max(1.0, float(round(TOPUP_BASE + max(0.0, gap))))
    return Correction(
        strategy="topup",
        reason=f"缺口 {gap}% 在 {GAP_SPLIT} 以内,单次补灌 {duration}s",
        duration_s=duration,
        times=1,
        interval_s=0,
        payload={"action": "pump", "duration_s": duration, "times": 1,
                 "target_range": [target_low, target_high], "baseline": measured},
    )
