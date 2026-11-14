"""REQ-F-022:执行报告渲染(Markdown)。

PRD 11.4.4 的硬要求:报告必须完整呈现「第 1 轮基线/复测/达成率 → 诊断 → 修正 →
第 2 轮结果 → outcome 回填」。这是「反馈循环与优化」这个模块的满分答卷,
所以表格的列是照着这句话排的,不是随便设计的。

本模块只做渲染(纯字符串),不查库、不推 WS;数据由接缝层组装成 ReportData 传进来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

VERDICT_LABEL = {
    "success": "✅ 闭环成功",
    "failed": "🔄 未达标,已触发修正",
    "needs_human": "🚨 转人工",
    "running": "⏳ 执行中",
    "pending": "⏸ 未开始",
    # run 跑完但验证官没出结论:流程走完 ≠ 达标,不能显示成「闭环成功」
    "unverified": "⚠️ 未产生验证结果",
}

CN_NUM = "一二三四五六七八九十"

STRATEGY_LABEL = {
    "topup": "单次补灌",
    "split": "分次灌溉",
    "suspect_data": "数据复核",
    "give_up": "放弃修正",
}


@dataclass
class RoundView:
    """一轮「执行 → 渗透 → 复测 → 判定」的证据。"""
    round_no: int
    baseline: Optional[float]          # 缺基线时为 None(报告里显示「—」,不显示 0.00)
    measured: float
    achievement: float
    confidence: float
    verdict: str
    target_low: float = 55.0
    target_high: float = 65.0
    duration_s: float = 0.0
    note: str = ""

    @property
    def gap(self) -> float:
        return round(max(0.0, self.target_low - self.measured), 2)


@dataclass
class ReportData:
    run_id: Optional[int] = None
    wf_name: str = "巡园浇水工作流"
    trigger: str = "manual"
    started_at: str = ""
    finished_at: str = ""
    outcome: str = "running"
    rounds: list[RoundView] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)   # {ts, name, event, status, duration_ms}
    alerts: list[dict] = field(default_factory=list)     # {level, message, source}
    confidence_reasons: list[str] = field(default_factory=list)
    achievement_detail: dict = field(default_factory=dict)

    @property
    def final_round(self) -> Optional[RoundView]:
        return self.rounds[-1] if self.rounds else None


def _fmt(value: float, unit: str = "%") -> str:
    if value is None:
        return "—"        # 取不到的数不写成 0.00,报告里一眼看得出「没测到」
    return f"{value:.2f}{unit}" if isinstance(value, (int, float)) else str(value)


def render_report(data: ReportData) -> str:
    lines: list[str] = []
    add = lines.append
    # 章节号跟着「实际写出来的章节」递增:没验证结果时「逐轮对照」整节不出现,
    # 若还用固定序号就会变成 一、三、四 跳号,看着像报告缺页。
    counter = [0]

    def heading(title: str) -> None:
        counter[0] += 1
        number = CN_NUM[counter[0] - 1] if counter[0] <= len(CN_NUM) else str(counter[0])
        add(f"## {number}、{title}")

    add(f"# {data.wf_name} · 执行报告")
    add("")
    meta = [f"run #{data.run_id}" if data.run_id is not None else "run (未编号)",
            f"触发:{data.trigger}"]
    if data.started_at:
        meta.append(f"{data.started_at}" + (f" → {data.finished_at}" if data.finished_at else ""))
    add("> " + " · ".join(meta))
    add(f"> 结论:**{VERDICT_LABEL.get(data.outcome, data.outcome)}**")
    add("")

    # ── 一、结论 ──
    heading("结论")
    final = data.final_round
    if final:
        add("")
        add(f"第 {final.round_no} 轮复测 {_fmt(final.measured)}，达成率 "
            f"**{_fmt(final.achievement)}**，置信度 **{final.confidence * 100:.0f}%**，"
            f"判定 `{final.verdict}`" + (f"：{final.note}" if final.note else "。"))
    else:
        add("")
        # run 走完不等于达标:没有验证记录就不说成败,只说「没判定」
        add(f"本次运行没有产生验证记录(run 状态:`{data.outcome}`),"
            "无法判定是否达标——流程跑通不等于浇水达标,不能算作一次成功的闭环。")
    add("")

    # ── 逐轮对照 ──
    if data.rounds:
        heading("逐轮对照")
        add("")
        add("| 轮次 | 浇水时长 | 基线 | 复测 | 目标区间 | 缺口 | 达成率 | 置信度 | 判定 |")
        add("| ---- | -------- | ---- | ---- | -------- | ---- | ------ | ------ | ---- |")
        for item in data.rounds:
            add(f"| 第 {item.round_no} 轮 | {_fmt(item.duration_s, 's')} | {_fmt(item.baseline)} | "
                f"{_fmt(item.measured)} | [{_fmt(item.target_low)}, {_fmt(item.target_high)}] | "
                f"{_fmt(item.gap)} | {_fmt(item.achievement)} | {item.confidence * 100:.0f}% | "
                f"{VERDICT_LABEL.get(item.verdict, item.verdict)} |")
        add("")

    # ── 诊断与修正(证据链的关键一段) ──
    heading("诊断与修正")
    add("")
    corrections = [r for r in data.rounds if r.verdict in {"failed", "needs_human"}]
    if corrections:
        for item in corrections:
            # note 来自 feedback_logs 的诊断(缺口多少、按什么策略补灌);
            # 取不到就按数字说清楚,不能因为少了句文案就把整段写成「无需修正」。
            detail = item.note or (f"达成率 {_fmt(item.achievement)}%、缺口 {_fmt(item.gap)}%，"
                                   f"已生成修正任务进入下一轮")
            add(f"- **第 {item.round_no} 轮**：{detail}")
    else:
        # 别写成「首轮即达标」:达成率 94.85% 判 success 是因为过了 PRD 11.3 的 60% 线,
        # 不是已经命中目标区间。措辞得对得上数字。
        add("- 首轮达成率已达通过线(≥60%),无需修正。")
    add("")

    # ── 执行时间线 ──
    heading("执行时间线")
    add("")
    if data.timeline:
        add("| 时间 | 节点 | 事件 | 状态 | 耗时 |")
        add("| ---- | ---- | ---- | ---- | ---- |")
        for row in data.timeline[:40]:
            add(f"| {row.get('ts', '')} | {row.get('name', '')} | {row.get('event', '')} | "
                f"{row.get('status', '')} | {row.get('duration_ms', '')}ms |")
        if len(data.timeline) > 40:
            add(f"| … | 共 {len(data.timeline)} 条,此处截断 | | | |")
    else:
        add("- 无事件记录。")
    add("")

    # ── 置信度明细 ──
    if final:
        heading("置信度明细")
        add("")
        add(f"- 综合 **{final.confidence * 100:.0f}%**(权重:数据质量 0.5 / 规则交叉 0.3 / 一致性 0.2)")
        if data.confidence_reasons:
            for reason in data.confidence_reasons:
                add(f"- {reason}")
        else:
            add("- 三路证据均无扣分项。")
        if data.achievement_detail.get("over_irrigated"):
            add("- ⚠️ 复测值超过目标上限,存在过浇风险。")
        if data.achievement_detail.get("baseline_in_range"):
            add("- ℹ️ 执行前基线已在目标区间内,本轮本无需作业。")
        add("")

    # ── 报警 ──
    if data.alerts:
        heading("本轮报警")
        add("")
        for alert in data.alerts:
            add(f"- `{alert.get('level', 'info')}` **{alert.get('source', 'agent')}**："
                f"{alert.get('message', '')}")
        add("")

    return "\n".join(lines).rstrip() + "\n"


def generate_report(run_id: int) -> int:
    """接缝别名：基座 `seams._CANDIDATES` 第一个候选就是本模块的 generate_report。

    实现在 engine.py（要读库、要注入 deps），这里延迟导入避免 report ↔ engine 循环。
    """
    from app.verification.engine import generate_report as _generate

    return _generate(run_id)
