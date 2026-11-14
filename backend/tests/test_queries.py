"""统一查询口径（app/core/queries.py）的纯逻辑单测：不连库。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core import queries


def _pt(value: float, minutes_ago: float) -> dict:
    ts = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(sep=" ", timespec="seconds")
    return {"value": value, "ts": ts}


def test_trend_negative_when_drying():
    """湿度在掉，斜率必须是负的（名字以前写成 positive，和断言正好相反，容易误读）。"""
    points = [_pt(40.0, 10), _pt(38.0, 5), _pt(37.0, 0)]
    slope = queries.trend_per_min(points)
    assert slope == pytest.approx(-0.3, abs=0.01)  # 3% / 10min


def test_trend_zero_with_single_point():
    assert queries.trend_per_min([_pt(40.0, 1)]) == 0.0
    assert queries.trend_per_min([]) == 0.0


def test_trend_zero_when_span_too_short():
    """30s 上报间隔只有 1 个点时跨度不足，抖动不能被当成趋势。"""
    points = [_pt(40.0, 0.05), _pt(41.5, 0)]
    assert queries.trend_per_min(points) == 0.0


def test_trend_survives_malformed_points():
    assert queries.trend_per_min([{"value": "x", "ts": "not-a-date"}]) == 0.0
    assert queries.trend_per_min([{"value": 1}]) == 0.0


def test_classify_soil_three_states():
    lo, hi = 55.0, 65.0
    assert queries.classify_soil(40.0, lo, hi) == "dry"
    assert queries.classify_soil(55.0, lo, hi) == "ok"
    assert queries.classify_soil(60.0, lo, hi) == "ok"
    assert queries.classify_soil(65.1, lo, hi) == "wet"


def test_raise_alert_rejects_bad_level_before_touching_db():
    """level 白名单在写库前就拦 —— 传 None 当 db 也不会炸出数据库错误。"""
    with pytest.raises(ValueError) as ei:
        queries.raise_alert(None, "urgent", "agent:x", "test")
    assert "level" in str(ei.value)


def test_alert_levels_match_model():
    assert queries.ALERT_LEVELS == ("info", "warning", "critical")
