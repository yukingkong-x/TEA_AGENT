"""演示预演脚本 —— 一键跑完两轮对照（PRD 15.1 剧本的骨架）。

目的：在队长的引擎接上**之前**就把演示剧本跑通。所有动作都走真实 HTTP API，
跟真固件走的是同一条 MQTT 链路；引擎接上后，第 3/7 步从「手动下发」自动升级为
「工作流触发」，其余一步不用改。

剧本：
  第 0 幕  体检：六服务健康、mode=mock、模拟器在跑、接缝就绪情况
  第 1 幕（成功闭环）注入干旱 → 湿度跌破下限 → 解除注入 → 浇水 10s →
          任务 success → 等渗透 → 湿度回升 →（引擎就绪则跑验证引擎）
  第 2 幕（故障对照）注入 stuck_moisture → 浇水 8s → 任务照样 success
          → 但湿度不动 →（引擎就绪则验证应 FAIL，Self-Loop 第 1 轮失败点）
  收尾    清除全部故障，打印对照表

用法：
    python scripts/demo_rehearsal.py                          # 默认 http://127.0.0.1:8000
    python scripts/demo_rehearsal.py --base http://IP:8000    # 打别的机器
    python scripts/demo_rehearsal.py --pump 5                 # 浇水秒数改小（快速过一遍）

只依赖标准库；写操作带 X-Admin-Token（ENFORCE_AUTH=true 时必需）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEV_SOIL = "mock-esp32-soil-02"
DEV_ACT = "mock-k10-act-03"
METRIC_SOIL = "soil_moisture"
TELEMETRY_S = 30  # 模拟器上报周期，轮询等待以它为基准

STEPS: list[tuple[str, str, str]] = []  # (幕, 事项, 结果)


# ------------------------------------------------------------------ HTTP
def http(method: str, path: str, *, body: dict | None = None, base: str = "", token: str = "") -> tuple[int, dict | bytes]:
    url = base + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Admin-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, raw


def is_dict(x: tuple[int, dict | bytes]) -> bool:
    return isinstance(x[1], dict)


def wait_for(desc: str, fn, timeout_s: float, interval_s: float = 3.0) -> bool:
    """轮询直到 fn() 为真。打印等待进度，超时返回 False（不抛异常，剧本继续走对照）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if fn():
                return True
        except Exception as exc:  # 网络抖动按"再等等"处理
            print(f"      轮询异常（继续）：{type(exc).__name__}: {exc}")
        time.sleep(interval_s)
    print(f"      等待超时（{timeout_s:.0f}s）：{desc}")
    return False


def soil_moisture(base: str, token: str) -> float | None:
    status, data = http("GET", f"/api/sensor/history?device_id={DEV_SOIL}&metric={METRIC_SOIL}&limit=1", base=base, token=token)
    if status == 200 and is_dict((status, data)):
        points = data["points"]  # type: ignore[index]
        return float(points[-1]["value"]) if points else None
    return None


def soil_age(base: str, token: str) -> float | None:
    """最新遥测点的数据龄（秒）。宿主机休眠过 / 模拟器没跑时会是很大的数。"""
    status, data = http("GET", f"/api/sensor/history?device_id={DEV_SOIL}&metric={METRIC_SOIL}&limit=1", base=base, token=token)
    if status == 200 and is_dict((status, data)):
        points = data["points"]  # type: ignore[index]
        if points:
            from datetime import datetime
            try:
                ts = datetime.fromisoformat(points[-1]["ts"])
                return abs((datetime.now() - ts).total_seconds())
            except ValueError:
                return None
    return None


def record(act: str, what: str, ok: bool, note: str = "") -> None:
    mark = "OK  " if ok else "FAIL"
    STEPS.append((act, what, mark + ("  " + note if note else "")))
    print(f"   [{mark}] {what}" + (f"（{note}）" if note else ""))


def headline(act: str, title: str) -> None:
    print(f"\n{'=' * 66}\n{act}  {title}\n{'=' * 66}")


# ------------------------------------------------------------------ 各幕
def act0_preflight(base: str, token: str) -> bool:
    headline("第 0 幕", "体检")
    status, data = http("GET", "/api/health", base=base, token=token)
    ok = status == 200 and is_dict((status, data)) and data.get("status") == "ok"  # type: ignore[union-attr]
    if not ok:
        record("0", "服务健康检查", False, f"HTTP {status}：{str(data)[:120]}")
        print("   后端没起来或 db/redis 没就绪 —— 先 `docker compose up -d` 再跑本脚本")
        return False
    h = data  # type: ignore[assignment]
    record("0", "db / redis / mqtt", True, f"{h['db']} / {h['redis']} / {h['mqtt']}")
    record("0", "运行模式", h.get("mode") == "mock", f"mode={h.get('mode')} simulator={h.get('simulator')}")

    if not h.get("simulator"):
        print("   模拟器没在跑 → POST /api/devices/mock/start")
        http("POST", "/api/devices/mock/start", base=base, token=token)
        time.sleep(3)

    seams = h.get("seams") or {}
    ready = [k for k, v in seams.items() if v == "ready"]
    missing = [k for k, v in seams.items() if v != "ready"]
    record("0", "跨地盘接缝", True, f"就绪 {ready or '无'} / 缺失 {missing or '无'}（缺失项本脚本自动跳过验证步骤）")

    m = soil_moisture(base, token)
    record("0", "土壤遥测链路", m is not None, f"当前湿度 {m if m is not None else '暂无数据（等一个上报周期）'}")
    age = soil_age(base, token)
    if m is not None and (age is None or age > TELEMETRY_S * 2 + 10):
        print(f"   [!!] 数据龄 {age:.0f}s 偏旧 —— 宿主机可能休眠过或模拟器刚重启，等新鲜遥测...")
        wait_for("拿到新鲜遥测", lambda: (soil_age(base, token) or 9999) <= TELEMETRY_S * 2, timeout_s=TELEMETRY_S * 2 + 10)
    return m is not None


def target_range(base: str, token: str) -> tuple[float, float]:
    """从设置页读目标区间（默认 55/65）。读不到就用 PRD 缺省值。"""
    status, data = http("GET", "/api/settings", base=base, token=token)
    if status == 200 and is_dict((status, data)):
        for item in data.get("items", []):  # type: ignore[union-attr]
            if item.get("key") == "irrigation_default_range":
                lo, hi = item.get("value") or [55, 65]
                return float(lo), float(hi)
    return 55.0, 65.0


def act1_success_loop(base: str, token: str, pump_s: int, engine_ready: bool) -> None:
    headline("第 1 幕", "成功闭环：干旱 → 浇水 → 回升")
    before = soil_moisture(base, token)
    lo, _hi = target_range(base, token)
    print(f"   浇水前湿度：{before}%（目标区间下限 {lo}%）")

    if before is not None and before > lo:
        status, _ = http("POST", "/api/devices/fault", body={"fault": "dry_soil"}, base=base, token=token)
        record("1", "注入 dry_soil（模拟干旱）", status in (200, 201))
        hit_low = wait_for("湿度跌破下限", lambda: (soil_moisture(base, token) or 100) <= 26.0, timeout_s=TELEMETRY_S * 2 + 10)
        record("1", "湿度跌破下限（决策依据成立）", hit_low, f"读数 {soil_moisture(base, token)}%")
        if not hit_low:
            print("   （读数没降也可能只是还没到上报周期，继续往下走）")
        status, _ = http("DELETE", "/api/devices/fault", base=base, token=token)
        record("1", "解除注入（否则湿度被钳制，看不到回升）", status == 200)
    else:
        # 隔夜/长跑后土壤自然蒸发，可能本来就低于下限 —— 这就是现成的干旱起点
        record("1", "当前湿度已低于目标下限（天然干旱起点）", True, f"{before}% ≤ {lo}%")

    # —— 引擎接上后，这一步换成 POST /api/workflows/{id}/run，其余不变 ——
    status, data = http("POST", f"/api/devices/{DEV_ACT}/cmd", body={"action": "pump", "params": {"duration_s": pump_s}}, base=base, token=token)
    dispatched = status == 200 and is_dict((status, data))
    record("1", f"下发浇水 {pump_s}s", dispatched, f"task={data.get('task_no') if dispatched else data}"[:80])
    if not dispatched:
        return
    task_no = data["task_no"]  # type: ignore[index]

    final = wait_task(base, token, task_no)
    record("1", "任务回执", final == "success", f"status={final}")
    verify_if_ready(base, token, task_no, engine_ready, expect="success")

    gained = wait_for("湿度回升（渗透完成）", lambda: (soil_moisture(base, token) or 0) > (before or 0) + 0.3, timeout_s=75)
    after = soil_moisture(base, token)
    record("1", "湿度回升", bool(gained and after is not None), f"{before}% → {after}%")


def act2_stuck_contrast(base: str, token: str, pump_s: int, engine_ready: bool) -> None:
    headline("第 2 幕", "故障对照：浇水成功，但湿度不动（Self-Loop 失败点）")
    before = soil_moisture(base, token)
    print(f"   注入前湿度：{before}%")

    status, _ = http("POST", "/api/devices/fault", body={"fault": "stuck_moisture"}, base=base, token=token)
    record("2", "注入 stuck_moisture（水照浇，湿度不涨）", status in (200, 201))

    status, data = http("POST", f"/api/devices/{DEV_ACT}/cmd", body={"action": "pump", "params": {"duration_s": pump_s}}, base=base, token=token)
    dispatched = status == 200 and is_dict((status, data))
    record("2", f"下发浇水 {pump_s}s", dispatched, f"task={data.get('task_no') if dispatched else data}"[:80])
    if not dispatched:
        http("DELETE", "/api/devices/fault", base=base, token=token)
        return
    task_no = data["task_no"]  # type: ignore[index]

    final = wait_task(base, token, task_no)
    record("2", "任务回执（设备照常 ack）", final == "success", f"status={final} ← 设备层看不出故障")

    unchanged = wait_for("确认湿度没动（等两个上报周期）", lambda: abs((soil_moisture(base, token) or 0) - (before or 0)) <= 0.3, timeout_s=TELEMETRY_S * 2 + 15)
    after = soil_moisture(base, token)
    record("2", "湿度不动（验证环节必须抓住这一点）", bool(unchanged), f"{before}% → {after}%")

    if engine_ready:
        status, data = http("POST", f"/api/verify/{task_no}", base=base, token=token)
        result = data.get("result", {}) if is_dict((status, data)) else {}
        conclusion = result.get("conclusion") if isinstance(result, dict) else None
        record("2", "验证引擎判定", conclusion == "failed", f"conclusion={conclusion}（期望 failed）")
    else:
        record("2", "验证引擎判定", True, "SKIP：引擎未接上，接上后此处应判 failed")

    status, _ = http("DELETE", "/api/devices/fault", base=base, token=token)
    record("2", "解除故障注入", status == 200)


def wait_task(base: str, token: str, task_no: str) -> str:
    """轮询任务终态：success / failed / timeout。"""

    def done() -> bool:
        status, data = http("GET", f"/api/tasks/{task_no}", base=base, token=token)
        return status == 200 and is_dict((status, data)) and data.get("status") in ("success", "failed", "timeout")  # type: ignore[union-attr]

    wait_for(f"任务 {task_no} 出终态", done, timeout_s=60, interval_s=2.0)
    status, data = http("GET", f"/api/tasks/{task_no}", base=base, token=token)
    return data.get("status", "?") if status == 200 and is_dict((status, data)) else "?"  # type: ignore[union-attr]


def verify_if_ready(base: str, token: str, task_no: str, engine_ready: bool, *, expect: str) -> None:
    if not engine_ready:
        record("1", "验证引擎判定", True, "SKIP：引擎未接上（/api/health 的 seams 字段会显示 ready）")
        return
    status, data = http("POST", f"/api/verify/{task_no}", base=base, token=token)
    result = data.get("result", {}) if is_dict((status, data)) else {}
    conclusion = result.get("conclusion") if isinstance(result, dict) else None
    record("1", "验证引擎判定", conclusion == expect, f"conclusion={conclusion}（期望 {expect}）")


def summary() -> None:
    print(f"\n{'=' * 66}\n对照表\n{'=' * 66}")
    width = max(len(s[1]) for s in STEPS) + 2
    cur = None
    for act, what, res in STEPS:
        if act != cur:
            print(f"\n  —— {act} ——")
            cur = act
        print(f"    {what:<{width}} {res}")
    fails = [s for s in STEPS if s[2].startswith("FAIL")]
    print(f"\n结果：{'全部通过' if not fails else f'{len(fails)} 项失败（见上表 FAIL 行）'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="茶园多智能体平台 · 演示预演脚本")
    parser.add_argument("--base", default=os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--pump", type=int, default=10, help="每次浇水秒数（默认 10）")
    parser.add_argument("--token", default=os.environ.get("ADMIN_TOKEN", "dev-only-admin-token"))
    args = parser.parse_args()

    print(f"目标后端：{args.base}（--base 可改）")

    status, health = http("GET", "/api/health", base=args.base, token=args.token)
    engine_ready = False
    if status == 200 and is_dict((status, health)):
        seams = health.get("seams") or {}
        engine_ready = bool(seams) and all(v == "ready" for v in seams.values())

    if not act0_preflight(args.base, args.token):
        summary()
        return 1

    act1_success_loop(args.base, args.token, args.pump, engine_ready)
    act2_stuck_contrast(args.base, args.token, max(5, args.pump - 2), engine_ready)

    status, _ = http("DELETE", "/api/devices/fault", base=args.base, token=args.token)
    print("\n收尾：故障开关已复位" if status == 200 else "\n收尾：故障复位失败，请手动 DELETE /api/devices/fault")
    summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
