"""只读端到端核对:真实库里的 device_cmd 任务,验证引擎的取数与判定。

不写库:只调 load_task / load_samples / previous_value / history_stats / device_online,
最后跑纯函数 verify()。用来证明「改之前必 500、改之后有真读数且有结论」。
"""
from __future__ import annotations

import traceback

from app.verification import wiring
from app.verification.verify import verify


def check(task_no: str) -> None:
    print("=" * 70)
    print("任务", task_no)
    task = wiring._load_task(task_no)
    print("load_task      ->", {k: task[k] for k in ("device_id", "sensor_id", "baseline", "duration_s", "round_no", "max_rounds")})

    # 改之前的写法:键存在、值为 None → TypeError(这就是评审说的 500)
    try:
        float(task.get("baseline", 0.0))
        print("旧写法 float(task.get('baseline', 0.0)) -> 没炸(说明这条任务带 baseline)")
    except TypeError as exc:
        print("旧写法 float(task.get('baseline', 0.0)) -> TypeError:", exc, "← 原来就是这里 500")

    samples = wiring._load_samples(task_no)
    previous = wiring._previous_value(task_no)
    base_before = wiring._baseline_before(task_no)
    mean, sigma = wiring._history_stats(task["device_id"])
    online = wiring._device_online(task["device_id"])
    print("samples        ->", samples)
    print("previous(兜底基线) ->", previous)
    print("baseline_before(执行前最后一条) ->", base_before)
    print("history        ->", (mean, sigma))
    print("device_online  ->", online)

    baseline = task.get("baseline")
    if baseline is None:
        baseline = base_before
    if baseline is None:
        baseline = previous
    result = verify(
        samples=samples,
        baseline=baseline,
        duration_s=task.get("duration_s") or 0.0,
        target_low=task.get("target_low") or 55.0,
        target_high=task.get("target_high") or 65.0,
        round_no=task.get("round_no") or 1,
        max_rounds=task.get("max_rounds") or 2,
        device_online=online,
        previous_value=previous,
        history_mean=mean,
        history_sigma=sigma,
    )
    print("baseline用于判定 ->", baseline, "(缺基线)" if result.baseline_missing else "")
    print("measured       ->", result.achievement.measured)
    print("achievement    ->", result.achievement.value, "%")
    print("confidence     ->", round(result.confidence.total * 100, 2), "%", result.confidence.reasons)
    print("verdict        ->", result.verdict, "|", result.note)


if __name__ == "__main__":
    import sys
    for no in sys.argv[1:]:
        try:
            check(no)
        except Exception:                                    # noqa: BLE001
            print("任务", no, "核对失败:")
            traceback.print_exc()
