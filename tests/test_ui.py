"""看板公共层：视野计算，以及 6 个看板页都已接入设计系统（设计文档 7.4、第 8 节）。"""

import datetime as dt
import math
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import ui

DASHBOARDS = Path(__file__).resolve().parents[1] / "app" / "pages"
# 换皮前写死在页面里的霓虹色、旧接口和旧文案
LEGACY = ("#22d3ee", "#fbbf24", "#f87171", "#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c",
          "accent=", "use_container_width", "\nimport ui\n", "from db import", "（默认全部）", "GeoAgent",
          "d1, d2 = st.date_input")


def _escaping_page():
    from app import ui

    ui.kpi_row([("x", "12", "<img src=x onerror=alert(1)>")])
    ui.legend([("<b>x</b>", "#DC2626")])
    ui.page_header("t", "s", chips=["<script>alert(1)</script>"])


def test_fit_bounds_uses_web_mercator():
    # 10°N–30°N 在墨卡托下比按度数算更"高"：缩放 3.80，按度数线性算会得到 3.90
    assert ui.fit_bounds(30.0, 10.0, 50.0, 30.0) == (20.322, 40.0, 3.8)


def test_fit_bounds_centres_high_latitudes_in_mercator():
    # 墨卡托中点：按算术中点会让上边界先出画面
    assert ui.fit_bounds(0, 20, 10, 70)[0] == 51.279


def test_fit_bounds_falls_back_on_non_finite_bounds():
    for bad in (math.nan, math.inf, -math.inf):
        assert ui.fit_bounds(bad, 0.0, 10.0, 10.0) == (0.0, 0.0, 2.0)
        assert ui.fit_bounds(0.0, 0.0, bad, 10.0) == (0.0, 0.0, 2.0)


def test_fit_bounds_limits():
    assert ui.fit_bounds(43.3, 12.6, 43.3, 12.6) == (12.6, 43.3, 7.0)  # 单点
    assert ui.fit_bounds(-180, -60, 180, 70)[2] == 2.0  # 全球范围不低于 2 级
    assert ui.fit_bounds(43.30, 12.60, 43.35, 12.65)[2] == 9.0  # 小范围不高于 9 级


def test_in_list_escapes_quotes():
    assert ui.in_list("country", ["Cote d'Ivoire"]) == "country IN ('Cote d''Ivoire')"


def test_in_list_rejects_an_empty_list():
    with pytest.raises(ValueError):
        ui.in_list("country", [])


def test_date_range_accepts_a_single_picked_day():
    first, last = dt.date(2023, 10, 1), dt.date(2023, 12, 31)
    assert ui.date_range((first,)) == (first, first)
    assert ui.date_range((first, last)) == (first, last)


def test_helpers_escape_untrusted_text():
    app = AppTest.from_function(_escaping_page, default_timeout=20).run()
    assert not app.exception
    rendered = "\n".join(str(element.value) for element in app.markdown)
    assert "&lt;img" in rendered and "<img" not in rendered
    assert "&lt;b&gt;x&lt;/b&gt;" in rendered and "<b>" not in rendered
    assert "&lt;script&gt;" in rendered and "<script>" not in rendered


@pytest.mark.parametrize("color", [("#F87171", "#DC2626", "#991B1B"), "red"])
def test_legend_rejects_unvalidated_colour(color):
    with pytest.raises(ValueError):
        ui.legend([("A", color)])
    with pytest.raises(ValueError):
        ui.legend([("A", [True, 2, 3])])  # bool 是 int 子类，不能混进 rgb()


def test_dashboards_use_the_design_system():
    pages = sorted(DASHBOARDS.glob("*.py"))
    assert len(pages) == 6
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert "from app import palette, ui" in text or "from app import ui" in text, page.name
        assert not [token for token in LEGACY if token.lower() in text.lower()], page.name
