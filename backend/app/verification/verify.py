"""REQ-F-016/017/018 的组合层:一次复测 → 达成率 + 置信度 + 结论 + 修正方案。

结论分流严格按 PRD 11.3 + 11.4.3:
- 置信度 <60%          → needs_human(不管达成率多好,数据不可信就不算过)
- 达成率 ≥60%          → success
- 达成率 <60% 且还有轮次 → failed(附带修正方案,进 Self-Loop)
- 达成率 <60% 且轮次用尽 → needs_human(防无限循环)

这个顺序有讲究:先看置信度再看达成率。先看达成率的话,「浇水后读数反而大跌」
会被判 failed 然后继续补水,越补越糟——实际是探针掉了或者设备离线。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.verification.achievement import Achievement, compute as compute_achievement
from app.verification.confidence import Confidence, Evidence, compute as compute_confidence
from app.verification.feedback import Correction, diagnose

ACHIEVEMENT_PASS = 60.0
CONFIDENCE_FLOOR = 0.6


@dataclass
class VerifyResult:
    verdict: str                        # success / failed / needs_human
    achievement: Achievement
    confidence: Confidence
    correction: Optional[Correction]
    round_no: int
    note: str = ""

    @property
    def passed(self) -> bool:
        return self.verdict == "success"

    @property
    def needs_human(self) -> bool:
        return self.verdict == "needs_human"

    def summary(self) -> str:
        """一句话结论,写进 verifications 表与报告首页。"""
        base = (f"第 {self.round_no} 轮:达成率 {self.achievement.value:.2f}%,"
                f"置信度 {self.confidence.total * 100:.0f}%,判定 {self.verdict}")
        return f"{base}({self.note})" if self.note else base


def verify(
    *,
    samples: list[float],
    baseline: float,
    duration_s: float,
    target_low: float = 55.0,
    target_high: float = 65.0,
    round_no: int = 1,
    max_rounds: int = 2,
    device_online: bool = True,
    previous_value: Optional[float] = None,
    history_mean: Optional[float] = None,
    history_sigma: Optional[float] = None,
) -> VerifyResult:
    """一次复测的完整判定。samples 为渗透期后的连续读数,取中位数作为实测值。"""
    evidence = Evidence(
        samples=list(samples),
        baseline=baseline,
        duration_s=duration_s,
        device_online=device_online,
        previous_value=previous_value,
        history_mean=history_mean,
        history_sigma=history_sigma,
    )
    measured = evidence.measured
    achievement = compute_achievement(baseline, target_low, target_high, measured)
    confidence = compute_confidence(evidence)

    note = ""
    correction: Optional[Correction] = None

    if confidence.total < CONFIDENCE_FLOOR:
        verdict = "needs_human"
        note = f"置信度 {confidence.total * 100:.0f}% 低于 {CONFIDENCE_FLOOR * 100:.0f}%,数据不可信"
    elif achievement.value >= ACHIEVEMENT_PASS:
        verdict = "success"
        if achievement.over_irrigated:
            note = "已超目标上限,存在过浇风险"
    elif round_no >= max_rounds:
        verdict = "needs_human"
        note = f"已修正 {round_no} 轮仍未达标(缺口 {achievement.gap}%),转人工"
    else:
        verdict = "failed"
        correction = diagnose(
            baseline=baseline,
            measured=measured,
            target_low=target_low,
            target_high=target_high,
            duration_s=duration_s,
            round_no=round_no,
            max_rounds=max_rounds,
        )
        note = correction.reason
        if correction.strategy == "suspect_data":
            # 数据可疑时先复核,不消耗修正轮次,但也别继续补水
            verdict = "needs_human"

    return VerifyResult(
        verdict=verdict,
        achievement=achievement,
        confidence=confidence,
        correction=correction,
        round_no=round_no,
        note=note,
    )
