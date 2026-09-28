import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui
from db import query

ui.setup("全球背景参考", accent="#fbbf24")
ui.page_header(
    "全球背景参考（GDELT 媒体事件流）",
    "航运相关国家的媒体事件流（估值任务筛选版，非红海专题数据）· 默认聚焦 2023 下半年危机窗口",
    chips=["全球背景参考", "1920 ~ 2025"],
)

meta = query("SELECT MIN(event_date) a, MAX(event_date) b FROM gdelt_events")
if meta["a"][0] is None:
    st.info("暂无 GDELT 数据，请先入库。")
    st.stop()

dmin, dmax = pd.Timestamp(meta["a"][0]).date(), pd.Timestamp(meta["b"][0]).date()
# 默认聚焦红海危机窗口（与 AIS / ACLED 时间对齐），可手动放宽
CRISIS_START, CRISIS_END = pd.Timestamp("2023-07-01").date(), pd.Timestamp("2023-12-31").date()
default_range = (max(dmin, CRISIS_START), min(dmax, CRISIS_END))
if default_range[0] > default_range[1]:
    default_range = (dmin, dmax)

with st.sidebar:
    st.header("筛选")
    d1, d2 = st.date_input("日期范围", default_range, min_value=dmin, max_value=dmax,
                           help="GDELT 为全球背景数据（1920~2025），默认只看危机窗口")
    countries = query("SELECT DISTINCT country FROM gdelt_events WHERE country IS NOT NULL ORDER BY 1")
    sel_countries = st.multiselect("国家/地区（默认全部）", countries["country"].tolist())
    codes = query("SELECT DISTINCT event_code FROM gdelt_events ORDER BY 1")
    sel_codes = st.multiselect("事件类型（默认全部）", codes["event_code"].tolist())
    tone_range = st.slider("Goldstein 分值（负=冲突 / 正=合作）", -10.0, 10.0, (-10.0, 10.0))

conds = ["event_date BETWEEN ? AND ?", "goldstein BETWEEN ? AND ?"]
params = [d1, d2, tone_range[0], tone_range[1]]
if sel_countries:
    conds.append("country IN (" + ",".join("'" + c + "'" for c in sel_countries) + ")")
if sel_codes:
    conds.append("event_code IN (" + ",".join("'" + c + "'" for c in sel_codes) + ")")
where = " AND ".join(conds)

df = query(
    f"""
    SELECT event_id, event_date, actor1, actor2, event_code, goldstein,
           avg_tone, lat, lon, country, num_mentions, source_url
    FROM gdelt_events WHERE {where} LIMIT 200000
    """,
    tuple(params),
)

if df.empty:
    st.warning("筛选结果为空")
    st.stop()

conflict_ratio = (df["goldstein"] < 0).mean() * 100
ui.kpi_row([
    ("事件总数", f"{len(df):,}", f"{df['country'].nunique()} 个国家/地区"),
    ("平均 Goldstein", f"{df['goldstein'].mean():+.2f}", "负值偏冲突，正值偏合作"),
    ("冲突事件占比", f"{conflict_ratio:.0f}%", "Goldstein < 0", "#f87171"),
    ("媒体总提及", f"{int(df['num_mentions'].sum()):,}", f"平均语调 {df['avg_tone'].mean():+.2f}"),
])

# 颜色: 冲突(红) <- Goldstein -> 合作(青)
df["color_r"] = ((10 - df["goldstein"]) / 20 * 235 + 20).astype(int)
df["color_g"] = 80
df["color_b"] = ((10 + df["goldstein"]) / 20 * 235 + 20).astype(int)

ui.deck(
    [
        pdk.Layer(
            "ScatterplotLayer",
            data=df,
            get_position="[lon, lat]",
            get_radius="1500 + num_mentions * 80",
            get_fill_color="[color_r, color_g, color_b, 150]",
            pickable=True,
        )
    ],
    lat=df["lat"].mean(), lon=df["lon"].mean(), zoom=3,
    tooltip="{actor1} → {actor2}\n{event_code} | Goldstein {goldstein}\n{country} · {event_date}",
    height=520,
)
ui.legend([("冲突（Goldstein -10）", [255, 80, 40]),
           ("中性（0）", [148, 80, 148]),
           ("合作（+10）", [40, 80, 255])])

left, right = st.columns(2, gap="medium")
with left:
    ui.panel("每日事件数")
    daily = df.groupby("event_date").size().reset_index(name="事件数")
    fig = px.bar(daily, x="event_date", y="事件数")
    fig.update_traces(marker_color="#fbbf24")
    fig.update_layout(xaxis_title=None)
    ui.chart(fig)
with right:
    ui.panel("Top 行为方")
    top = df["actor1"].value_counts().head(10).reset_index()
    top.columns = ["行为方", "事件数"]
    fig = px.bar(top, x="事件数", y="行为方", orientation="h")
    fig.update_traces(marker_color="#fbbf24")
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig)

ui.panel("事件明细")
show_all = st.toggle("显示全部字段（含事件 ID 与经纬度）")
cols = (["event_id", "event_date", "actor1", "actor2", "event_code", "goldstein",
         "avg_tone", "lat", "lon", "country", "num_mentions", "source_url"]
        if show_all else
        ["event_date", "actor1", "actor2", "event_code", "goldstein", "avg_tone",
         "country", "num_mentions", "source_url"])
detail = df[cols].copy()
detail["event_date"] = pd.to_datetime(detail["event_date"]).dt.date
st.dataframe(
    detail.sort_values("event_date", ascending=False),
    use_container_width=True,
    hide_index=True,
    height=340,
)
