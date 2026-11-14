"""跑一轮巡园并把 WS 上真实发出的消息全录下来（A 的联调核对用）。

用法（容器内）：python scripts/ws_watch_run.py [wf_id] [超时秒]
产出：/tmp/ws_run.jsonl 逐条原文 + 终端汇总（事件类型分布、节点进出、agent 发言、回边）
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

import httpx
import websockets

WF_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 3
TIMEOUT = float(sys.argv[2]) if len(sys.argv) > 2 else 420.0
OUT = "/tmp/ws_run.jsonl"


async def main() -> None:
    records: list[dict] = []
    started = time.time()
    async with websockets.connect("ws://localhost:8000/ws/dashboard", open_timeout=10) as ws:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"http://localhost:8000/api/workflows/{WF_ID}/run", json={})
            print("POST run ->", resp.status_code, resp.text[:200])
        run_id = None
        try:
            run_id = resp.json().get("run_id")
        except Exception:
            pass

        deadline = started + TIMEOUT
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            item = json.loads(raw)
            item["_recv_at"] = round(time.time() - started, 2)
            records.append(item)
            data = item.get("data") or {}
            if run_id and data.get("run_id") not in (None, run_id):
                continue
            if item.get("type") == "run_status" and data.get("status") in {"success", "failed"}:
                break

    with open(OUT, "w", encoding="utf-8") as fh:
        for row in records:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    types: dict[str, int] = {}
    nodes: list[str] = []
    agents: list[str] = []
    for row in records:
        data = row.get("data") or {}
        key = row.get("type", "?")
        if key == "node_state":
            key = f"node_state:{data.get('state')}"
            if data.get("state") == "started":
                nodes.append(f"{data.get('node_id')}({data.get('node_type')})")
        if key == "agent_message":
            agents.append(str(data.get("agent_key")))
        types[key] = types.get(key, 0) + 1

    print("\n== 事件分布 ==")
    for key, count in types.items():
        print(f"{key:24s} {count}")
    print("\n== 节点进入顺序(%d) ==" % len(nodes))
    print(" -> ".join(nodes))
    print("\n== agent 发言顺序(%d) ==" % len(agents))
    print(" -> ".join(agents))
    print("\n原始记录:", OUT, "共", len(records), "条")


asyncio.run(main())
