"""看板页共用组件：页面初始化、页头、KPI、图例、区块标题、地图与图表封装。

颜色分三路：控件 / 图表 / 底图走 .streamlit/config.toml 的原生主题；自己输出的 HTML
走 styles/base.css 里用 light-dark() 定义的令牌；deck.gl 图层在 WebGL 里绘制，
CSS 管不到，按 mode() 从 app.palette 取色。
"""

from __future__ import annotations

import html
import math
from pathlib import Path

import pydeck as pdk
import streamlit as st

from app import palette, theme_watch

STYLES = Path(__file__).with_name("styles")

# 数据源色（RGB），pydeck 图层直接使用
C_AIS = palette.rgb(palette.SOURCE["ais"])
C_ACLED = palette.rgb(palette.SOURCE["acled"])
C_GDELT = palette.rgb(palette.SOURCE["gdelt"])
C_NEWS = palette.rgb(palette.SOURCE["news"])

_TOOLTIP = {
    "light": {"backgroundColor": "#FFFFFF", "color": "#1B1D1F", "border": "1px solid #E4E3DE"},
    "dark": {"backgroundColor": "#111827", "color": "#E7ECF3", "border": "1px solid #243044"},
}
_TOOLTIP_BASE = {"fontSize": "12px", "borderRadius": "8px", "padding": "8px 10px",
                 "boxShadow": "0 8px 24px rgba(0, 0, 0, .18)"}


def inject_css(*names: str) -> None:
    css = "\n".join((STYLES / name).read_text(encoding="utf-8") for name in names)
    st.html(f"<style>{css}</style>")


def setup(title: str, *, watch: bool = True) -> None:
    """每个页面第一个调用。watch=False 时由页面在合适的时机自行调用 theme_watch.mode。"""
    st.set_page_config(page_title=f"{title} · GeoScope", layout="wide", initial_sidebar_state="expanded")
    inject_css("base.css")
    if watch:
        theme_watch.mode()


def mode() -> str:
    """本次运行中已确定的主题（由 setup 或 theme_watch.mode 写入会话状态）。"""
    current = st.session_state.get(theme_watch.STATE_KEY)
    return current if current in palette.MODES else "light"


def tooltip_style() -> dict:
    return {**_TOOLTIP_BASE, **_TOOLTIP[mode()]}


def _mercator(lat: float) -> float:
    lat = max(-85.0, min(85.0, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def fit_bounds(left: float, bottom: float, right: float, top: float,
               viewport: tuple[int, int] = (720, 560), padding: float = 0.12) -> tuple[float, float, float]:
    """(纬度, 经度, 缩放)：按名义视口在 Web 墨卡托投影下分别算出经纬两向需要的缩放，
    取较小值并留边距，限制在 2–9 级；极小范围用 7 级。中心取经纬度算术中点。"""
    width, height = viewport
    if max(right - left, top - bottom) < 0.01:
        zoom = 7.0
    else:
        zoom_x = math.log2(width * (1 - 2 * padding) * 360 / (512 * max(right - left, 1e-9)))
        zoom_y = math.log2(height * (1 - 2 * padding) * 2 * math.pi
                           / (512 * max(_mercator(top) - _mercator(bottom), 1e-9)))
        zoom = min(zoom_x, zoom_y)
    return ((bottom + top) / 2, (left + right) / 2, round(max(2.0, min(9.0, zoom)), 2))


def page_header(title: str, subtitle: str = "", chips: list | None = None) -> None:
    """chips: [文本] 或 [(文本, "live")]，live 带绿色状态点。"""
    tags = []
    for chip in chips or []:
        text, kind = chip if isinstance(chip, tuple) else (chip, "")
        tags.append(f'<span class="gs-tag {kind}">{html.escape(str(text))}</span>')
    st.markdown(
        f'<div class="gs-header"><div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>'
        f'<div class="gs-tags">{"".join(tags)}</div></div>', unsafe_allow_html=True,
    )


def kpi_row(items: list) -> None:
    """items: [(标签, 数值, 说明)] 或 [(标签, 数值, 说明, "#色值")]；不给颜色时用主色。"""
    cards = []
    for item in items:
        label, value, caption = item[0], item[1], item[2]
        style = f' style="--kc:{item[3]}"' if len(item) > 3 else ""
        cards.append(f'<div class="gs-kpi"{style}><div class="l">{label}</div>'
                     f'<div class="v">{value}</div><div class="c">{caption}</div></div>')
    st.markdown(f'<div class="gs-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)


def legend(items: list) -> None:
    """items: [(名称, [r, g, b])] 或 [(名称, "#色值")]。"""
    chips = []
    for name, color in items:
        css = color if isinstance(color, str) else f"rgb({color[0]},{color[1]},{color[2]})"
        chips.append(f'<span><i style="background:{css}"></i>{html.escape(name)}</span>')
    st.markdown(f'<div class="gs-legend">{"".join(chips)}</div>', unsafe_allow_html=True)


def panel(title: str) -> None:
    st.markdown(f'<div class="gs-panel-t">{html.escape(title)}</div>', unsafe_allow_html=True)


def deck(layers, lat: float, lon: float, zoom: float, tooltip=None, height: int = 560) -> None:
    """不传 map_style：Streamlit 前端按主题选 Positron / Dark Matter 底图。"""
    tip = {"text": tooltip, "style": tooltip_style()} if isinstance(tooltip, str) else tooltip
    st.pydeck_chart(
        pdk.Deck(map_style=None, layers=layers, tooltip=tip,
                 initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom, pitch=0)),
        height=height,
    )


def chart(fig, height: int = 320) -> None:
    """theme="streamlit"：坐标轴、网格、悬浮框与分类色板都跟随当前主题。"""
    st.plotly_chart(style_fig(fig, height), width="stretch", theme="streamlit")


def style_fig(fig, height: int = 320):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=14, b=0), bargap=0.25,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, title_text=""))
    return fig
