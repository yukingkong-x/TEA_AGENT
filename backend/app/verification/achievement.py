"""REQ-F-016:达成率计算(PRD 11.1)。

公式本体:
- L ≤ M ≤ H        → 100.00
- M < L            → max(0, (M − B) / (L − B)) × 100
- M > H            → 100.00,并标注 over_irrigated

本模块是**权威实现**;`agents/tools.py` 里的 `calc_achievement` 只是给 LLM 用的薄包装,
数值口径必须一致(两边都有单测,改公式会同时红)。

PRD 未写但实际会撞到的边界,这里显式定死:
1. 基线 B 已经在目标区间内(B ≥ L):这一轮本就不该浇水,达成率记 100,
   标 `baseline_in_range=True`,避免 (L−B) ≤ 0 除零;
2. B > H(渍涝基线):同样按已达标处理,防止出现负分母;
3. 复测值低于基线(M < B,浇了反而降):公式给负值,按 0 截断,由置信度判「数据可疑」。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Achievement:
    value: float                 # 0-100,保留两位
    over_irrigated: bool         # 超过目标上限
    baseline_in_range: bool      # 基线已达标(本轮无需作业)
    gap: float                   # 距目标下限的缺口(L − M),已达标为 0
    baseline: float
    target_low: float
    target_high: float
    measured: float

    @property
    def reached(self) -> bool:
        return self.value >= 100.0 and not self.over_irrigated


def compute(
    baseline: float,
    target_low: float,
    target_high: float,
    measured: float,
) -> Achievement:
    """按 PRD 11.1 计算达成率。"""
    if target_low >= target_high:
        raise ValueError(f"target_low({target_low}) 必须小于 target_high({target_high})")

    def make(value: float, over: bool = False, in_range: bool = False) -> Achievement:
        return Achievement(
            value=round(max(0.0, min(100.0, value)), 2),
            over_irrigated=over,
            baseline_in_range=in_range,
            gap=round(max(0.0, target_low - measured), 2),
            baseline=baseline,
            target_low=target_low,
            target_high=target_high,
            measured=measured,
        )

    if target_low <= measured <= target_high:
        return make(100.0)
    if measured > target_high:
        return make(100.0, over=True)
    # measured < target_low:先处理「基线已达标/渍涝」的退化情形
    if baseline >= target_low:
        return make(100.0, in_range=True)
    span = target_low - baseline
    return make((measured - baseline) / span * 100)
