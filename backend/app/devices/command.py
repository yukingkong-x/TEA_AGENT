"""指令下发与回执跟踪（PRD 5.3 / 5.4）——**全平台唯一允许下发设备指令的地方**。

权限铁律（PRD 7.3）：`send_device_cmd` 工具只绑给 executor。这里再做一层纵深防御：
`issued_by` 不在白名单直接 PermissionError，任何绕过工具层的裸调用都会留痕失败。

回执两阶段：
    received → 任务转 running，启动「执行超时」计时（duration + 15s 余量）
    finished → 任务转 success/failed，清计时，触发验证钩子（队长 verification 挂这里）
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import ids, task_trail
from ..core.redis_client import Keys, get_redis
from ..core.ws_manager import manager
from ..models.alerts import Alert
from ..models.tasks import Task
from .registry import ensure_device

# ------------------------------------------------------------------ 常量
ACTIONS = {"pump", "read_now", "relay_off", "calibrate_dry", "calibrate_wet", "reboot"}
ROLE_ACTIONS = {
    "pump": {"actuator"},
    "relay_off": {"actuator"},
    "calibrate_dry": {"soil"},
    "calibrate_wet": {"soil"},
    "read_now": {"field", "soil", "actuator"},
    "reboot": {"field", "soil", "actuator"},
}
ALLOWED_ISSUERS = {"agent:executor", "api:manual", "system:scheduler", "system:safety", "system:simulator"}
MAX_PUMP_DURATION_S = 120  # PRD 4.3 安全阀
DEFAULT_ACK_TIMEOUT_S = 30

TOPIC_DEVICE_CMD = "tea/device/{device_id}/cmd"
TOPIC_TASK_CMD = "tea/cmd/{task_no}"

# 回执完成后的外部钩子（队长把 verification.on_device_finished 注册进来即可）
_finish_handlers: list[Callable[[dict[str, Any]], None]] = []
_timeout_handlers: list[Callable[[dict[str, Any]], None]] = []


def register_finish_handler(fn: Callable[[dict[str, Any]], None]) -> None:
    if fn not in _finish_handlers:
        _finish_handlers.append(fn)


def register_timeout_handler(fn: Callable[[dict[str, Any]], None]) -> None:
    if fn not in _timeout_handlers:
        _timeout_handlers.append(fn)


# ------------------------------------------------------------------ 下发
def _clamp_params(action: str, params: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    """pump 的 duration_s 单次上限 120s，超限截断并在 ack 侧由设备标注 clamped。"""
    params = dict(params or {})
    clamped = False
    if action == "pump":
        dur = params.get("duration_s", 30)
        try:
            dur = int(dur)
        except (TypeError, ValueError):
            dur = 30
        if dur > MAX_PUMP_DURATION_S:
            dur, clamped = MAX_PUMP_DURATION_S, True
        params["duration_s"] = max(1, dur)
    return params, clamped


def send_cmd(
    db: Session,
    device_id: str,
    action: str,
    params: dict[str, Any] | None = None,
    *,
    task_no: str | None = None,
    issued_by: str = "api:manual",
    timeout_s: int | None = None,
) -> dict[str, Any]:
    """构造 cmd → 双主题下发 → 建/更新任务 → 挂回执计时。返回下发结果摘要。"""
    if issued_by not in ALLOWED_ISSUERS:
        logger.error("拒绝下发：issued_by={} 无下发权限（device={}, action={}）", issued_by, device_id, action)
        raise PermissionError(f"issued_by={issued_by} 无权下发设备指令（PRD 7.3 权限铁律）")
    if action not in ACTIONS:
        raise ValueError(f"不支持的 action: {action}（全集 {sorted(ACTIONS)}）")

    device = ensure_device(db, device_id)
    allowed_roles = ROLE_ACTIONS.get(action, set())
    if allowed_roles and device.role not in allowed_roles:
        raise ValueError(f"设备 {device_id}（role={device.role}）不支持 action={action}")

    params, clamped = _clamp_params(action, params)
    task = None
    prev_status: str | None = None
    if task_no:
        task = db.scalar(select(Task).where(Task.task_no == task_no))
    if task is None:
        task_no = task_no or ids.new_task_no()
        task = Task(
            task_no=task_no,
            run_id=None,
            type="device_cmd",
            payload_json={"device_id": device_id, "action": action, "params": params},
            priority=8,
            status="dispatched",
            assigned_device=device_id,
            retry_count=0,
            timeout_s=timeout_s or DEFAULT_ACK_TIMEOUT_S,
        )
        db.add(task)
    else:
        prev_status = task.status
        task.status = "dispatched"
        task.assigned_device = device_id

    # 轨迹与状态变更同一个事务：跟着下面那次 commit 一起落地。
    # 新任务的 from 是 None（建出来就是 dispatched，从没落过 pending），
    # 别写假的 pending——轨迹上那一跳不存在，写了会误导排查。
    task_trail.record(
        db,
        task_no=task_no,
        from_status=prev_status,
        to_status="dispatched",
        reason="dispatch",
        actor="human" if issued_by.endswith("manual") else "scheduler",
        run_id=task.run_id,
        payload={"action": action, "params": params, "device_id": device_id, "clamped": clamped},
    )

    # 必须先 commit 再 publish，不能只 flush：
    # 模拟器的 ack 是毫秒级回来的，它在 paho 线程用**另一个 session** 查 Task；
    # 停在 flush 的话 INSERT 还在未提交事务里，别的会话看不见 → task=None
    # → handle_ack 只广播不落库 → 任务永远卡在 dispatched，超时后还会补一条假的
    # 「指令超时」报警，_finish_handlers 再拿幽灵 task_no 去触发验证。
    # 提交责任收在这里；调用方之后自己再 commit 一次是无害的（幂等提交）。
    db.commit()

    msg_id = ids.new_msg_id()
    payload = {
        "msg_id": msg_id,
        "task_id": task_no,
        "action": action,
        "params": params,
        "issued_by": issued_by,
        "ts": int(time.time()),
    }

    from ..core import mqtt_client  # 延迟导入，避免循环依赖

    published = mqtt_client.publish(TOPIC_DEVICE_CMD.format(device_id=device_id), payload)
    # 带任务号的通道（主流通道，用于追踪）
    mqtt_client.publish(TOPIC_TASK_CMD.format(task_no=task_no), payload)

    # 回执计时：pump 要等真实执行时间，其余动作给固定余量
    exec_s = int(params.get("duration_s", 0)) if action == "pump" else 0
    ack_timeout = timeout_s or (exec_s + max(DEFAULT_ACK_TIMEOUT_S, 15))
    deadline = time.time() + ack_timeout
    try:
        get_redis().set(
            Keys.ack_wait(msg_id),
            f"{task_no}|{device_id}|{deadline:.3f}|{action}",
            ex=ack_timeout + 120,
        )
    except Exception:  # pragma: no cover
        pass

    manager.publish_threadsafe(
        "task_status",
        {
            "task_no": task_no,
            "status": "dispatched",
            "from": prev_status,
            "to": "dispatched",
            "reason": "dispatch",
            "run_id": task.run_id,
            "type": "device_cmd",
            "assigned_device": device_id,
            "payload": payload,
        },
    )
    logger.info(
        "指令下发 {} → {} {} {}（msg_id={}, task={}, clamped={}, mqtt={}）",
        issued_by, device_id, action, params, msg_id, task_no, clamped, published,
    )
    return {
        "msg_id": msg_id,
        "task_no": task_no,
        "device_id": device_id,
        "action": action,
        "params": params,
        "clamped": clamped,
        "published": published,
    }


# ------------------------------------------------------------------ 回执
def handle_ack(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """处理设备回执：received / finished 两阶段（PRD 5.4）。"""
    ref = payload.get("ref_msg_id") or payload.get("msg_id")
    stage = (payload.get("stage") or "").lower()
    result = (payload.get("result") or "done").lower()
    task_no = payload.get("task_id") or payload.get("task_no")
    device_id = payload.get("device_id")
    detail = payload.get("detail") or {}

    task = db.scalar(select(Task).where(Task.task_no == task_no)) if task_no else None
    prev_status = task.status if task is not None else None

    if stage == "received":
        if task is not None and task.status in {"dispatched", "pending"}:
            task.status = "running"
        status = "running"
    elif stage == "finished":
        status = "success" if result == "done" else ("failed" if result == "failed" else "canceled")
        if task is not None:
            task.status = status
            task.result_json = {"result": result, "stage": stage, "detail": detail, "ack": payload}
        try:
            if ref:
                get_redis().delete(Keys.ack_wait(ref))
        except Exception:  # pragma: no cover
            pass
    else:
        logger.warning("收到未知 stage 的 ack：{}", payload)
        status = "unknown"

    if task is not None:
        # 心跳式刷新 updated_at：调度器用 `updated_at + timeout_s` 判超时
        # （orchestrator/scheduler.py::_scan_timeouts）。只改 status 时，若状态恰好没变
        # （例如重复的 received→running 回执），SQLAlchemy 不会发 UPDATE，`onupdate`
        # 也就不会触发 —— 真机慢但一直有回执的任务会被判超时并触发一次假重试。
        task.updated_at = datetime.now()
        db.flush()
        # 轨迹跟这次 flush 在同一个事务里；重复回执（running→running）由
        # events.is_duplicate 丢掉，不会刷成几百行。stage=unknown 时 from==to，同样被丢。
        task_trail.record(
            db,
            task_no=task.task_no,
            from_status=prev_status,
            to_status=status if status != "unknown" else prev_status,
            reason="ack",
            actor="device",
            run_id=task.run_id,
            payload={"ack_stage": stage, "result": result, "device_id": device_id, "detail": detail},
        )

    manager.publish_threadsafe(
        "task_status",
        {
            "task_no": task_no,
            "status": status,
            # 契约第 9 节要求带状态机的边：任务页轨迹直接画 from/to，不要前端自己推
            "from": prev_status,
            "to": status,
            "reason": "ack",
            "type": "device_cmd",
            "assigned_device": device_id,
            "detail": detail,
            "ack_stage": stage,
        },
    )

    if stage == "finished":
        event = {
            "task_no": task_no,
            "device_id": device_id,
            "result": result,
            "status": status,
            "detail": detail,
            "ack": payload,
        }
        for fn in _finish_handlers:
            try:
                fn(event)
            except Exception as exc:  # pragma: no cover
                logger.exception("回执完成钩子执行失败：{}", exc)

    logger.info("回执 {} stage={} result={} task={}", device_id, stage, result, task_no)
    return {"task_no": task_no, "stage": stage, "result": result, "status": status}


# ------------------------------------------------------------------ 超时巡检
def sweep_ack_timeouts(db: Session) -> list[dict[str, Any]]:
    """扫超时未完成的指令（由后台循环每 5s 调一次）。

    只负责把任务标成 timeout 并广播；重试/熔断策略在队长 scheduler（PRD 10.4）。
    """
    overdue: list[dict[str, Any]] = []
    try:
        keys = list(get_redis().scan_iter(Keys.PREFIX + ":ack:wait:*"))
    except Exception:  # pragma: no cover
        return overdue

    now = time.time()
    for key in keys:
        try:
            raw = get_redis().get(key)
        except Exception:  # pragma: no cover
            continue
        if not raw:
            continue
        parts = raw.split("|")
        if len(parts) < 4:
            get_redis().delete(key)
            continue
        task_no, device_id, deadline_s, action = parts[0], parts[1], float(parts[2]), parts[3]
        if now < deadline_s:
            continue

        task = db.scalar(select(Task).where(Task.task_no == task_no))
        if task is not None and task.status in {"dispatched", "running"}:
            prev_status = task.status
            task.status = "timeout"
            task.result_json = {"reason": "ack_timeout", "action": action, "deadline": deadline_s}
            db.add(
                Alert(
                    level="warning",
                    source=f"device:{device_id}",
                    message=f"指令 {action} 超时未完成（task={task_no}, 超过 {int(now - deadline_s)}s）",
                )
            )
            db.flush()
            task_trail.record(
                db,
                task_no=task_no,
                from_status=prev_status,
                to_status="timeout",
                reason="ack_timeout",
                actor="scheduler",
                run_id=task.run_id,
                payload={"action": action, "device_id": device_id, "overdue_s": int(now - deadline_s)},
            )
            event = {
                "task_no": task_no,
                "device_id": device_id,
                "action": action,
                "overdue_s": int(now - deadline_s),
            }
            overdue.append(event)
            manager.publish_threadsafe(
                "task_status",
                {
                    "task_no": task_no,
                    "status": "timeout",
                    "from": prev_status,
                    "to": "timeout",
                    "reason": "ack_timeout",
                    "run_id": task.run_id,
                    "type": "device_cmd",
                    "assigned_device": device_id,
                },
            )
            logger.warning("指令超时：task={} device={} action={}", task_no, device_id, action)
            for fn in _timeout_handlers:
                try:
                    fn(event)
                except Exception as exc:  # pragma: no cover
                    logger.exception("超时钩子执行失败：{}", exc)
        get_redis().delete(key)
    return overdue
