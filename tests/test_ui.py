"""看板公共层：视野计算，以及 6 个看板页都已接入设计系统（设计文档 7.4、第 8 节）。"""

from pathlib import Path

from app import ui

DASHBOARDS = Path(__file__).resolve().parents[1] / "app" / "pages"
# 换皮前写死在页面里的霓虹色、旧接口和旧文案
LEGACY = ("#22d3ee", "#fbbf24", "#f87171", "#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c",
          "accent=", "use_container_width", "\nimport ui\n", "from db import", "（默认全部）", "GeoAgent")


def test_fit_bounds_uses_web_mercator():
    # 10°N–30°N 在墨卡托下比按度数算更"高"：缩放 3.80，按度数线性算会得到 3.90
    assert ui.fit_bounds(30.0, 10.0, 50.0, 30.0) == (20.0, 40.0, 3.8)


def test_fit_bounds_limits():
    assert ui.fit_bounds(43.3, 12.6, 43.3, 12.6) == (12.6, 43.3, 7.0)  # 单点
    assert ui.fit_bounds(-180, -60, 180, 70)[2] == 2.0  # 全球范围不低于 2 级
    assert ui.fit_bounds(43.30, 12.60, 43.35, 12.65)[2] == 9.0  # 小范围不高于 9 级


def test_dashboards_use_the_design_system():
    pages = sorted(DASHBOARDS.glob("*.py"))
    assert len(pages) == 6
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert "from app import palette, ui" in text or "from app import ui" in text, page.name
        assert not [token for token in LEGACY if token.lower() in text.lower()], page.name
