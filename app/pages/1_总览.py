import sys
from pathlib import Path

import plotly.express as px
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("总览")
mode = ui.mode()
ui.page_header(
    "GeoScope · 红海危机时空态势",
    "2023 下半年红海危机专题 —— AIS 船舶动态 · ACLED 危机事件（LLM 筛选增强）· 新闻原文 · GDELT 全球背景",
    chips=[("DATA ONLINE", "live"), "专题窗口 2023-07 ~ 2023-12"],
)

with st.expander("页面导航：我该用哪一页？", expanded=False):
    st.markdown(
        """
| 页面 | 什么时候用 |
| --- | --- |
| **工作台**（推荐入口） | 直接用大白话提问：查数、缓冲区分析、航迹查询、事件背景问答，结果自动上图 |
| **AIS 船舶** | 看具体船舶的航行轨迹与密度分布，按时间窗筛选 |
| **ACLED 事件** | 浏览红海危机事件清单：风险等级 / 咽喉要道 / 伤亡等多维筛选 |
| **时空叠加** | 把船舶轨迹和危机事件叠在一张图上，观察袭击与航运的时空关联 |
| **新闻检索** | 按英文关键词全文检索报道原文（对话式问背景请直接用工作台） |
| **GDELT 背景** | 全球媒体舆情背景（非红海专题数据），用于对比全球冲突基调 |
"""
    )

# ---- KPI ----
stats = {
    "AIS 位置点": ("ais_positions", "ts", palette.SOURCE["ais"], "红海海域 88 天"),
    "ACLED 危机事件": ("acled_events", "event_date", palette.SOURCE["acled"], "LLM 筛选增强版"),
    "新闻原文": ("news_articles", "published_at", palette.SOURCE["news"], "关联 ACLED 事件"),
    "GDELT 背景事件": ("gdelt_events", "event_date", palette.SOURCE["gdelt"], "全球背景参考"),
}
kpis = []
for name, (table, tcol, color, note) in stats.items():
    df = query(f"SELECT COUNT(*) n, MIN({tcol}) a, MAX({tcol}) b FROM {table}")
    n = int(df["n"][0])
    cap = f"{str(df['a'][0])[:10]} ~ {str(df['b'][0])[:10]} · {note}" if n else "暂无数据"
    kpis.append((name, f"{n:,}", cap, color))
ui.kpi_row(kpis)

left, right = st.columns([3, 2], gap="medium")

with left:
    ui.panel("红海危机事件热度（ACLED）")
    pts = query("SELECT lat, lon FROM acled_events WHERE lat IS NOT NULL")
    if pts.empty:
        st.info("暂无事件数据")
    else:
        lat, lon, zoom = ui.fit_bounds(pts["lon"].min(), pts["lat"].min(), pts["lon"].max(), pts["lat"].max(),
                                       viewport=(760, 480))
        ramp = palette.sequential("red", mode)
        ui.deck(
            [
                pdk.Layer(
                    "HeatmapLayer",
                    data=pts,
                    get_position="[lon, lat]",
                    radius_pixels=34,
                    intensity=4,
                    threshold=0.02,
                    color_range=ramp,
                )
            ],
            lat=lat, lon=lon, zoom=zoom, height=480,
        )
        ui.legend([("低", ramp[1][:3]), ("中", ramp[2][:3]), ("较高", ramp[3][:3]), ("高", ramp[5][:3])])

with right:
    ui.panel("危机演化（每周事件 · 按阶段）")
    trend = query(
        """
        SELECT date_trunc('week', event_date) AS 周,
               CASE phase
                   WHEN 'precursor' THEN '前兆期'
                   WHEN 'trigger_chain' THEN '触发链'
                   WHEN 'maritime_crisis' THEN '海上危机期'
                   ELSE '其他' END AS 阶段,
               COUNT(*) AS 事件数
        FROM acled_events GROUP BY 1, 2 ORDER BY 1
        """
    )
    if trend.empty:
        st.info("暂无事件数据")
    else:
        fig = px.bar(trend, x="周", y="事件数", color="阶段", barmode="stack",
                     color_discrete_map=dict(zip(["前兆期", "触发链", "海上危机期"], palette.ordinal(3, mode))),
                     category_orders={"阶段": ["前兆期", "触发链", "海上危机期"]})
        ui.chart(fig, height=260)

    ui.panel("最新相关报道（ACLED 事件原文回填）")
    news = query(
        """
        SELECT published_at, source, title FROM news_articles
        WHERE published_at IS NOT NULL
        ORDER BY published_at DESC LIMIT 5
        """
    )
    if news.empty:
        st.info("暂无新闻数据")
    for _, r in news.iterrows():
        src = str(r["source"])[:36] + ("…" if len(str(r["source"])) > 36 else "")
        st.markdown(
            f'<div class="gs-news"><div class="m">{str(r["published_at"])[:10]} · {src}</div>'
            f'<div class="h">{r["title"]}</div></div>',
            unsafe_allow_html=True,
        )

st.divider()

b1, b2, b3 = st.columns(3, gap="medium")
with b1:
    ui.panel("AIS 活跃船舶 Top 10")
    ships = query(
        """
        SELECT COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS 船舶, COUNT(*) AS 位置点
        FROM ais_positions p LEFT JOIN ais_ships s USING (mmsi)
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """
    )
    if not ships.empty:
        fig = px.bar(ships, x="位置点", y="船舶", orientation="h")
        fig.update_traces(marker_color=palette.SOURCE["ais"])
        fig.update_yaxes(autorange="reversed")
        ui.chart(fig, height=300)
with b2:
    ui.panel("危机事件国家分布")
    by_c = query(
        """
        SELECT country AS 国家, COUNT(*) AS 事件数, SUM(fatalities) AS 死亡
        FROM acled_events GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """
    )
    if not by_c.empty:
        fig = px.bar(by_c, x="国家", y="事件数", color="死亡",
                     color_continuous_scale=list(palette.SEQUENTIAL["red"][mode][1:]))
        ui.chart(fig, height=300)
with b3:
    ui.panel("咽喉要道关联事件")
    choke = query(
        """
        SELECT chokepoint AS 咽喉要道, COUNT(*) AS 事件数
        FROM acled_events WHERE chokepoint IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    if not choke.empty:
        fig = px.pie(choke, names="咽喉要道", values="事件数", hole=0.55)
        ui.chart(fig, height=300)
