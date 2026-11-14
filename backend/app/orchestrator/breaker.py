"""设备维度熔断器（PRD 10.4）。

规则：单设备**连续** 3 次 timeout/failed → 熔断 300s；熔断期内该设备的新任务直接
rejected（不烧重试次数）；300s 后自动进入半开——下一次成功即清零，再失败立刻重开。
设置页可手动解除（`reset`）。

为什么「连续」而不是「累计」：设备掉线通常是一段连续故障，累计计数会让一台修好的
设备因为历史故障一直被拉黑，演示里就会出现「设备明明恢复了却一直 rejected」。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_THRESHOLD = 3
DEFAULT_OPEN_SECONDS = 300


@dataclass
class BreakerEntry:
    failures: int = 0
    opened_at: datetime | None = None


class Breaker:
    def __init__(self, threshold: int = DEFAULT_THRESHOLD, open_seconds: int = DEFAULT_OPEN_SECONDS):
        if threshold < 1:
            raise ValueError("threshold 必须 ≥ 1")
        if open_seconds < 0:
            raise ValueError("open_seconds 不能为负")
        self.threshold = threshold
        self.open_seconds = open_seconds
        self._entries: dict[str, BreakerEntry] = {}
        self._lock = threading.RLock()

    # -- 内部 --
    def _entry(self, device_id: str) -> BreakerEntry:
        return self._entries.setdefault(device_id, BreakerEntry())

    def _auto_close(self, device_id: str, now: datetime) -> bool:
        """熔断期满 → 自动解除（半开）。返回是否发生了自动解除。"""
        entry = self._entries.get(device_id)
        if entry is None or entry.opened_at is None:
            return False
        if now - entry.opened_at >= timedelta(seconds=self.open_seconds):
            entry.opened_at = None
            entry.failures = 0
            return True
        return False

    # -- 对外 --
    def record_failure(self, device_id: str, now: datetime) -> bool:
        """记一次失败。返回「本次失败是否刚刚触发熔断」（用于只报一次警）。"""
        if not device_id:
            return False
        with self._lock:
            self._auto_close(device_id, now)
            entry = self._entry(device_id)
            if entry.opened_at is not None:
                return False                 # 已在熔断中，不重复触发
            entry.failures += 1
            if entry.failures >= self.threshold:
                entry.opened_at = now
                return True
            return False

    def record_success(self, device_id: str) -> bool:
        """记一次成功：清零。返回「是否从熔断态恢复」。"""
        if not device_id:
            return False
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is None:
                return False
            recovered = entry.opened_at is not None
            entry.failures = 0
            entry.opened_at = None
            return recovered

    def is_open(self, device_id: str, now: datetime) -> bool:
        if not device_id:
            return False
        with self._lock:
            self._auto_close(device_id, now)
            entry = self._entries.get(device_id)
            return bool(entry and entry.opened_at is not None)

    def remaining_seconds(self, device_id: str, now: datetime) -> int:
        """熔断剩余秒数；未熔断返回 0。"""
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is None or entry.opened_at is None:
                return 0
            if self._auto_close(device_id, now):
                return 0
            left = self.open_seconds - (now - entry.opened_at).total_seconds()
            return max(0, int(left))

    def reset(self, device_id: str) -> None:
        """设置页「手动解除熔断」。"""
        with self._lock:
            entry = self._entries.get(device_id)
            if entry is not None:
                entry.failures = 0
                entry.opened_at = None

    def reset_all(self) -> None:
        with self._lock:
            self._entries.clear()

    def open_devices(self, now: datetime) -> dict[str, int]:
        """当前处于熔断的设备 → 剩余秒数（任务页熔断徽章用它）。"""
        with self._lock:
            for device_id in list(self._entries):
                self._auto_close(device_id, now)
            return {
                device_id: self.remaining_seconds(device_id, now)
                for device_id, entry in self._entries.items()
                if entry.opened_at is not None
            }

    def snapshot(self) -> dict[str, dict]:
        """只读快照，给 /api/health 或设置页展示。"""
        with self._lock:
            return {
                device_id: {"failures": entry.failures, "open": entry.opened_at is not None}
                for device_id, entry in self._entries.items()
            }
