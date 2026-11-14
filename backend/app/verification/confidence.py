"""REQ-F-017:三路置信度(PRD 11.2)。

confidence = 0.5 × 数据质量分 + 0.3 × 规则交叉分 + 0.2 × 一致性分

每一路的扣分都要留下**可读的理由**,报告页要拿它解释「为什么转人工」(PRD 11.4 证据链)。
所以本模块不只返回一个数,还返回 `reasons`——演示时评委真的会问「凭什么是 62%」。
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

# PRD 11.2 的阈值,集中在这里方便调参和对照文档
SPREAD_OK = 5.0            # 3 次读数极差 <5% 算稳定
JUMP_LIMIT = 20.0          # 与上一点差 ≥20 视为跳变
RATE_LOW, RATE_HIGH = 0.1, 1.0   # 单位时间提升量的合理区间(%/s)
SIGMA_K = 3.0              # 24h 均值偏差阈值(3σ)


@dataclass
class Evidence:
    """一次复测能拿到的全部证据。缺的填 None,由本模块按保守原则扣分。"""
    samples: list[float]                 # 渗透期后连续 3 次读数
    baseline: float                      # 执行前基线
    duration_s: float                    # 浇水时长
    device_online: bool = True
    previous_value: float | None = None  # 复测前一个点,用于跳变判定
    history_mean: float | None = None    # 该设备近 24h 均值
    history_sigma: float | None = None   # 近 24h 标准差

    @property
    def measured(self) -> float:
        """复测值 = 连续 3 次读数的中位数(PRD 11.1 注),防单点抖动。"""
        return round(statistics.median(self.samples), 2) if self.samples else 0.0


@dataclass
class Confidence:
    total: float
    data_quality: float
    rule_cross: float
    consistency: float
    reasons: list[str] = field(default_factory=list)

    @property
    def low(self) -> bool:
        """PRD 11.3:置信度 <60% 一律转人工。"""
        return self.total < 0.6


def _data_quality(ev: Evidence, reasons: list[str]) -> float:
    score = 0.0
    if ev.device_online:
        score += 0.4
    else:
        reasons.append("复测设备离线(数据质量 -0.4)")

    if len(ev.samples) >= 3:
        median = statistics.median(ev.samples)
        if median > 0:
            spread = (max(ev.samples) - min(ev.samples)) / median * 100
            if spread < SPREAD_OK:
                score += 0.4
            else:
                # 超过 5% 按比例衰减,20% 极差直接 0
                kept = max(0.0, 1 - (spread - SPREAD_OK) / (20.0 - SPREAD_OK))
                score += 0.4 * kept
                reasons.append(f"读数抖动大(极差 {spread:.1f}%,数据质量 -{0.4 * (1 - kept):.2f})")
        else:
            score += 0.2
            reasons.append("读数中位数为 0,无法判断抖动(数据质量 -0.2)")
    else:
        score += 0.2
        reasons.append(f"复测读数只有 {len(ev.samples)} 个(应 3 个,数据质量 -0.2)")

    if ev.previous_value is None or abs(ev.measured - ev.previous_value) < JUMP_LIMIT:
        score += 0.2
    else:
        reasons.append(f"读数跳变 {abs(ev.measured - ev.previous_value):.1f}(数据质量 -0.2)")
    return min(1.0, score)


def _rule_cross(ev: Evidence, reasons: list[str]) -> float:
    physical = 1.0 if ev.measured > ev.baseline else 0.0
    if physical == 0.0:
        reasons.append("浇水后读数未上升(规则交叉:物理合理性 0)")

    if ev.duration_s <= 0:
        rate_score = 0.0
        reasons.append("浇水时长非正,无法评估提升速率(规则交叉 0)")
    else:
        rise_pct = (ev.measured - ev.baseline) / ev.baseline * 100 if ev.baseline else 0.0
        rate = rise_pct / ev.duration_s
        if RATE_LOW <= rate <= RATE_HIGH:
            rate_score = 1.0
        else:
            rate_score = 0.5
            reasons.append(f"单位时间提升量 {rate:.2f}%/s 不在 {RATE_LOW}-{RATE_HIGH} 区间(规则交叉 0.5)")
    return (physical + rate_score) / 2


def _consistency(ev: Evidence, reasons: list[str]) -> float:
    if ev.history_mean is None or ev.history_sigma is None or ev.history_sigma <= 0:
        return 1.0  # 无历史分布时不臆造扣分
    deviation = abs(ev.measured - ev.history_mean)
    limit = SIGMA_K * ev.history_sigma
    if deviation < limit:
        return 1.0
    kept = max(0.0, 1 - (deviation - limit) / limit)
    reasons.append(
        f"复测值偏离 24h 均值 {deviation:.1f}(超 {SIGMA_K}σ={limit:.1f},一致性 {kept:.2f})"
    )
    return kept


def compute(ev: Evidence) -> Confidence:
    reasons: list[str] = []
    quality = _data_quality(ev, reasons)
    rule = _rule_cross(ev, reasons)
    consistency = _consistency(ev, reasons)
    total = round(0.5 * quality + 0.3 * rule + 0.2 * consistency, 4)
    if not ev.samples:
        reasons.append("没有复测读数,置信度按最低处理")
        total = 0.0
    return Confidence(
        total=total,
        data_quality=round(quality, 4),
        rule_cross=round(rule, 4),
        consistency=round(consistency, 4),
        reasons=reasons,
    )
