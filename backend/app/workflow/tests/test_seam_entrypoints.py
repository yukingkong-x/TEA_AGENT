"""接缝入口守卫：基座 `seams._CANDIDATES` 写的路径必须真的能取到函数。

断点背景：基座找 `app.workflow.service.start_run` / `app.verification.service.verify_task` /
`app.verification.report.generate_report`，而实现分别落在 `engine.py` 与 `dag.py`。
一旦别名模块被谁删了或改了名，接缝会静默回落到「未就绪」→ 路由 503，
表现是「功能接入中」，现场没人会想到是路径对不上。所以这里把五个候选钉成测试。
"""
from __future__ import annotations

import importlib
import inspect

import pytest

# 与 backend/app/seams.py 的 _CANDIDATES 逐条对应（改了那边要同步这里）
CANDIDATES = {
    "start_run": [("app.workflow.service", "start_run")],
    "validate_dag": [("app.workflow.engine", "validate_dag")],
    "verify_task": [("app.verification.service", "verify_task")],
    "generate_report": [("app.verification.report", "generate_report")],
    "ingest": [("app.knowledge.loader", "ingest")],
    "search": [("app.knowledge.retriever", "search")],
}

# 每个接缝的首个入参名（seams._invoke 会优先按关键字调）
FIRST_PARAM = {
    "start_run": "wf_id",
    "validate_dag": "dag",
    "verify_task": "task_no",
    "generate_report": "run_id",
    "ingest": "path",
    "search": "question",
}


@pytest.mark.parametrize("seam", sorted(CANDIDATES))
def test_first_candidate_exists_and_is_callable(seam: str):
    module_path, attr = CANDIDATES[seam][0]
    module = importlib.import_module(module_path)
    fn = getattr(module, attr, None)
    assert callable(fn), f"{seam} 的接缝入口 {module_path}.{attr} 不存在"


@pytest.mark.parametrize("seam", sorted(FIRST_PARAM))
def test_first_param_name_matches_contract(seam: str):
    module_path, attr = CANDIDATES[seam][0]
    fn = getattr(importlib.import_module(module_path), attr)
    params = list(inspect.signature(fn).parameters)
    assert params[:1] == [FIRST_PARAM[seam]], (
        f"{seam} 首参名是 {params[:1]}，接缝按关键字传 {FIRST_PARAM[seam]}"
    )


def test_all_six_seams_wired_before_bootstrap():
    """未注入 deps 时必须「响亮地拒绝」，不能返回空结果假装成功。"""
    from app.verification import engine as verify_engine
    from app.workflow import engine as workflow_engine

    workflow_engine._deps = None
    verify_engine._deps = None

    with pytest.raises(Exception):
        importlib.import_module("app.workflow.service").start_run(1)
    with pytest.raises(Exception):
        importlib.import_module("app.verification.service").verify_task("task-x")
