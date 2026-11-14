"""把「自然语言设备指代」解析成真实 device_id。

## 为什么需要这一层

LLM 不会按 `mock-esp32-soil-02` 这种格式传参。实测一次巡园浇水工作流，
四个 Agent 调工具时传的 `device_id` 分别是：

    get_env_status(device_id="A区茶垄")
    get_soil_status(device_id="A区")
    get_soil_status(device_id="A区土壤传感器ID")

精确匹配必然落空 → 工具抛 ValueError → Agent 回「设备ID不存在」→
决策判 none → 不下发指令。闭环断在第一步，而且断得很像"数据质量问题"，
排查时容易去怀疑传感器而不是参数解析。

## 匹配顺序（命中即停，分数只用于同分排序）

1. `device_id` 精确相等                         100
2. `device_id` 归一后相等（忽略大小写/空格/横线）  95
3. `location` 归一后相等                        90
4. `name` 归一后相等                            85
5. 互相包含（query ⊂ device_id / location / name）80
6. 仅 role 命中（query 里出现「土壤」「气象」「泵」等词）  50
7. 什么都没中但指定了 role，且该 role 只有一台 → 30（兜底，打 warning）

第 6、7 条是有意的「宁可给数据也不要抛错」：工具层抛错会让 LLM 编出
「传感器坏了」这种结论，比拿到一台近似设备的数据更误导。
返回结果里带 `matched_by`，调用方据此打日志，事后能看出是精确命中还是兜底。

## 与 Mock/Real 的关系

同分时优先与当前 mode 同批次的设备：mock 模式下选 `is_mock=1`，
避免演示时把真机历史读数混进 mock 场景（两套量纲）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

# query 里出现这些词就把 role 锁死，避免「土壤传感器」被解析成气象站
ROLE_HINTS: dict[str, tuple[str, ...]] = {
    "soil": ("土壤", "墒情", "含水率", "soil"),
    "field": ("气象", "环境", "空气", "光照", "巡园", "field", "env"),
    "actuator": ("泵", "阀", "执行", "relay", "pump", "actuator", "灌溉终端"),
}

_DROP = re.compile(r"[\s\-_/·,，。()（）\[\]【】]+")


def normalize(text: Any) -> str:
    """统一成可比形式：小写、去掉空白与常见分隔符。"""
    if text is None:
        return ""
    return _DROP.sub("", str(text)).lower()


@dataclass(frozen=True)
class Match:
    device_id: str
    score: int
    matched_by: str

    def __bool__(self) -> bool:  # 方便 `if hit:`
        return bool(self.device_id and self.score > 0)


def _as_dict(item: Any) -> dict[str, Any]:
    """同时支持 ORM 对象与 dict，纯函数才好单测。"""
    if isinstance(item, dict):
        return item
    out = {}
    for key in ("device_id", "name", "location", "role", "is_mock"):
        out[key] = getattr(item, key, None)
    return out


def role_of_query(query: str) -> Optional[str]:
    """从 query 文本猜角色（「土壤传感器」→ soil）。猜不出返回 None。"""
    norm = normalize(query)
    if not norm:
        return None
    for role, words in ROLE_HINTS.items():
        if any(normalize(word) in norm for word in words):
            return role
    return None


def match(
    query: str | None,
    candidates: Iterable[Any],
    *,
    role: Optional[str] = None,
    prefer_mock: Optional[bool] = None,
) -> Optional[Match]:
    """在候选设备里找出最可能的那一台。找不到返回 None。

    role 为 None 时先用 query 里的关键词推断；仍推不出则不按角色过滤。
    prefer_mock 为 True/False 时，同分优先取该批次。
    """
    rows = [_as_dict(c) for c in candidates]
    if not rows:
        return None

    want_role = role or role_of_query(query or "")
    if want_role:
        scoped = [r for r in rows if r.get("role") == want_role]
        # 角色过滤后为空说明这个 role 压根没有设备，退回全集再试（宁可给近似设备）
        if scoped:
            rows = scoped

    norm_q = normalize(query)
    best: Optional[Match] = None

    if norm_q:
        for row in rows:
            did = row.get("device_id") or ""
            score, how = 0, ""
            if did == query:
                score, how = 100, "device_id"
            elif normalize(did) == norm_q:
                score, how = 95, "device_id_loose"
            elif normalize(row.get("location")) == norm_q:
                score, how = 90, "location"
            elif normalize(row.get("name")) == norm_q:
                score, how = 85, "name"
            else:
                norm_did = normalize(did)
                norm_loc = normalize(row.get("location"))
                norm_name = normalize(row.get("name"))
                for value, label in ((norm_did, "device_id_contains"), (norm_loc, "location_contains"), (norm_name, "name_contains")):
                    if value and (norm_q in value or value in norm_q) and len(value) >= 2:
                        score, how = 80, label
                        break
            if score:
                best = _pick_better(best, Match(did, score, how), prefer_mock, rows)
        if best:
            return best

    # 兜底：query 里点了「土壤/气象/泵」这类词，或调用方指定了 role，
    # 且该角色只有一台设备 —— 那就用它，别让 LLM 因为一个 id 格式拿不到数据。
    if want_role:
        same_role = [_as_dict(r) for r in candidates if _as_dict(r).get("role") == want_role]
        chosen = _one_of(same_role, prefer_mock)
        if chosen is not None:
            return Match(chosen.get("device_id") or "", 30, f"role:{want_role}")
    return None


def _one_of(rows: Sequence[dict[str, Any]], prefer_mock: Optional[bool]) -> Optional[dict[str, Any]]:
    if not rows:
        return None
    if prefer_mock is not None:
        for row in rows:
            if bool(row.get("is_mock")) == bool(prefer_mock):
                return row
    return rows[0]


def _pick_better(
    current: Optional[Match],
    candidate: Match,
    prefer_mock: Optional[bool],
    rows: Sequence[dict[str, Any]],
) -> Match:
    if current is None:
        return candidate
    if candidate.score != current.score:
        return candidate if candidate.score > current.score else current
    if prefer_mock is None:
        return current
    flag = {r.get("device_id"): bool(r.get("is_mock")) for r in rows}
    want = bool(prefer_mock)
    cur_ok = flag.get(current.device_id) == want
    cand_ok = flag.get(candidate.device_id) == want
    return candidate if (cand_ok and not cur_ok) else current
