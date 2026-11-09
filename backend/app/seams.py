"""跨地盘接缝门面（seams = 缝）：基座 ↔ 队长模块的唯一对接点。

为什么要有这个文件
------------------
基座（HTTP 层）需要调用队长写的四块能力：工作流引擎、验证引擎、报告生成、知识库。
但这两块是两条分支上并行开发的，谁也 import 不到谁。之前基座是「按约定的模块路径
直接 import」，于是产生一个问题：**队长只要换个模块名或函数名，基座这边就全 503**。

现在只有这一层知道路径。队长落地时只需要改本文件 `_CANDIDATES` 一行（或一个函数体），
基座的 api/*.py 一行都不用动。

队长怎么接（两种方式，选一种即可）
----------------------------------
方式 1（最省事）：什么都不改，只要模块路径和函数名跟 `_CANDIDATES` 对得上，自动生效。
方式 2（想用别的名字）：直接把下面 6 个函数体改成你自己的 import + 调用，例如

    def verify_task(task_no: str):
        from app.verification.engine import check_task   # 你真正的实现
        return check_task(task_no)

调用约定（详细说明见 docs/contracts/api_seams.md 第一节）
--------------------------------------------------------
    start_run(wf_id, trigger)              -> {"run_id": int} / int
    validate_dag(dag)                      -> list[str]（空列表=通过）；未就绪返回 None
    verify_task(task_no)                   -> {"achievement","confidence","conclusion"}
    generate_report(run_id)                -> {"report_id": int} / int
    ingest(path, doc_id)                   -> {"chunk_count": int, "chroma_ids": [...]}
    search(question, top_k)                -> [{"title","chunk_text","score","doc_id"}]

没就绪时统一抛 `SeamNotReady`，main.py 把它转成 HTTP 503 + 一句人话，
前端据此显示「模块未就绪」，而不是白屏的 500。
"""
from __future__ import annotations

import importlib
import inspect
import time
from typing import Any, Callable

from loguru import logger

_status_cache: tuple[float, dict[str, str]] = (0.0, {})

# --------------------------------------------------------------------------- 约定
# key -> 依次尝试的 (模块路径, 函数名)
_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "start_run": (("app.workflow.service", "start_run"),),
    "validate_dag": (("app.workflow.engine", "validate_dag"), ("app.workflow.engine", "validate")),
    "verify_task": (("app.verification.service", "verify_task"),),
    "generate_report": (
        ("app.verification.report", "generate_report"),
        ("app.reports.generator", "generate_report"),
    ),
    "ingest": (("app.knowledge.loader", "ingest"),),
    "search": (("app.knowledge.retriever", "search"),),
}

# key -> (中文名, 约定签名, 谁在调)
_META: dict[str, tuple[str, str, str]] = {
    "start_run": ("触发工作流", "start_run(wf_id: int, trigger: str) -> {run_id}", "POST /api/workflows/{id}/run"),
    "validate_dag": ("DAG 校验", "validate_dag(dag: dict) -> list[str]", "保存/修改工作流"),
    "verify_task": ("任务验证", "verify_task(task_no: str) -> dict", "POST /api/verify/{task_no}"),
    "generate_report": ("生成报告", "generate_report(run_id: int) -> int", "POST /api/reports/generate"),
    "ingest": ("知识入库", "ingest(path: str, doc_id: int) -> dict", "POST /api/knowledge/upload"),
    "search": ("知识检索", "search(question: str, top_k: int) -> list", "POST /api/knowledge/search"),
}


class SeamNotReady(RuntimeError):
    """接缝对面的模块还没落地。路由层统一转 503。"""

    def __init__(self, seam: str, reason: str) -> None:
        self.seam = seam
        name, sig, user = _META.get(seam, (seam, "", ""))
        self.detail = (
            f"{name}尚未就绪（队长地盘）：{reason}｜约定 {sig}｜调用方 {user}"
            f"｜接法见 backend/app/seams.py 或 docs/contracts/api_seams.md"
        )
        super().__init__(self.detail)


# --------------------------------------------------------------------------- 内部
def _invoke(fn: Callable, args: tuple, kwargs: dict) -> Any:
    """按函数签名决定「按关键字」还是「按位置」调，避免 TypeError 重试导致重复执行。

    为什么不能靠 try/except TypeError 兜底：start_run 第一次真的跑起来了，
    只因为参数名不叫 wf_id 而抛 TypeError，再调一次 = 建两条 run。
    """
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # C 扩展/内置函数拿不到签名
        return fn(*args, **kwargs)

    kinds = {p.kind for p in params.values()}
    var_kw = inspect.Parameter.VAR_KEYWORD in kinds
    var_pos = inspect.Parameter.VAR_POSITIONAL in kinds
    if all(k in params or var_kw for k in kwargs):
        return fn(**kwargs)          # 参数名对得上 → 走关键字（对方改顺序也不怕）
    if var_pos or len(params) >= len(args):
        return fn(*args)             # 否则按位置（顺序与约定一致）
    return fn(**kwargs)


def _resolve(seam: str) -> Callable:
    """按 _CANDIDATES 找函数；找不到抛 SeamNotReady（带清一色的原因）。"""
    reasons: list[str] = []
    for dotted, attr in _CANDIDATES[seam]:
        try:
            module = importlib.import_module(dotted)
        except Exception as exc:  # ImportError，或模块内部初始化抛错
            reasons.append(f"{dotted} 导入失败（{type(exc).__name__}: {exc}）")
            continue
        fn = getattr(module, attr, None)
        if fn is None:
            reasons.append(f"{dotted} 里没有 {attr}()")
            continue
        if not callable(fn):
            reasons.append(f"{dotted}.{attr} 不是函数")
            continue
        return fn
    raise SeamNotReady(seam, "；".join(reasons) or "未找到")


# --------------------------------------------------------------------------- 对外
def start_run(wf_id: int, trigger: str = "manual") -> Any:
    """触发一次工作流执行。返回 {"run_id": int} 或 int 都接受。"""
    return _invoke(_resolve("start_run"), (wf_id, trigger), {"wf_id": wf_id, "trigger": trigger})


def validate_dag(dag: dict[str, Any]) -> list[str] | None:
    """可选的引擎级 DAG 校验。返回 None 表示「对面没提供/自己报错」，调用方用自己的兜底校验。"""
    try:
        fn = _resolve("validate_dag")
    except SeamNotReady:
        return None
    try:
        result = _invoke(fn, (dag,), {"dag": dag})
    except Exception as exc:  # 对面校验器自己崩了，不该让保存接口 500
        logger.warning("引擎级 DAG 校验抛错，已回退到基座本地校验：{}: {}", type(exc).__name__, exc)
        return None
    return list(result) if result else []


def verify_task(task_no: str) -> Any:
    """对一个任务跑验证引擎。返回 {achievement, confidence, conclusion}。"""
    return _invoke(_resolve("verify_task"), (task_no,), {"task_no": task_no})


def generate_report(run_id: int) -> Any:
    """为一次执行生成报告。返回 {"report_id": int} 或 int。"""
    return _invoke(_resolve("generate_report"), (run_id,), {"run_id": run_id})


def ingest(path: str, doc_id: int) -> Any:
    """切片 + 向量化入库。返回 {"chunk_count": int, "chroma_ids": [...]}。"""
    return _invoke(_resolve("ingest"), (path, doc_id), {"path": path, "doc_id": doc_id})


def search(question: str, top_k: int = 5) -> Any:
    """向量检索。返回 [{title, chunk_text, score, doc_id}]。"""
    return _invoke(_resolve("search"), (question, top_k), {"question": question, "top_k": top_k})


def ensure(seam: str) -> None:
    """只检查不就绪（上传接口要在落库前先探一下，避免文档永远卡在 processing）。"""
    _resolve(seam)


def status(max_age: float = 30.0, *, refresh: bool = False) -> dict[str, str]:
    """接缝体检：{"start_run": "ready" / "未就绪：原因"}。给 /api/health 用。

    带 30 秒缓存：healthcheck 每 10 秒打一次，没必要每次都去试探 import
    （对面模块 import 若很重，会拖慢健康检查甚至把容器判成 unhealthy）。
    """
    global _status_cache
    now = time.monotonic()
    ts, cached = _status_cache
    if not refresh and cached and now - ts < max_age:
        return dict(cached)

    out: dict[str, str] = {}
    for seam in _CANDIDATES:
        try:
            _resolve(seam)
            out[seam] = "ready"
        except SeamNotReady as exc:
            out[seam] = exc.detail
    _status_cache = (now, out)
    return dict(out)


def log_status() -> None:
    """启动时打一行，一眼看出哪块还没接上。"""
    st = status(refresh=True)
    ready = [k for k, v in st.items() if v == "ready"]
    missing = [k for k, v in st.items() if v != "ready"]
    if missing:
        logger.warning("跨地盘接缝：就绪 {} / 缺失 {}（缺失项相关接口返回 503）", ready or "无", missing)
    else:
        logger.info("跨地盘接缝：6 个全部就绪")
