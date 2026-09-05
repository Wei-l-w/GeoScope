import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui
from db import query

ui.setup("新闻检索", accent="#a78bfa")
ui.page_header(
    "新闻文本检索与趋势",
    "全文关键词检索 · 报道热度时间线 · 来源结构分析",
    chips=["ACLED 原文回填", "568 篇"],
)

meta = query("SELECT COUNT(*) n FROM news_articles")
if int(meta["n"][0]) == 0:
    st.info("暂无新闻数据，请先入库。")
    st.stop()

kw = st.text_input("关键词检索（标题+正文，多个关键词空格分隔，AND 关系）", "",
                   placeholder="新闻正文为英文，例如：Houthi vessel / Red Sea attack")

conds, params = [], []
for w in kw.split():
    conds.append("(title ILIKE ? OR body ILIKE ?)")
    params += [f"%{w}%", f"%{w}%"]
where = " AND ".join(conds) if conds else "1=1"

df = query(
    f"""
    SELECT published_at, source, title, body, url, lang, related_event_id
    FROM news_articles WHERE {where}
    ORDER BY published_at DESC NULLS LAST LIMIT 5000
    """,
    tuple(params),
)

if df.empty:
    st.warning("没有匹配的文章")
    st.stop()

valid_dates = pd.to_datetime(df["published_at"]).dropna()
span_days = (valid_dates.max() - valid_dates.min()).days + 1 if len(valid_dates) else 0
ui.kpi_row([
    ("命中文章", f"{len(df):,}", f"检索词：{kw or '（全部）'}"),
    ("涉及来源", f"{df['source'].nunique()}", "按文章 URL 域名统计"),
    ("时间跨度", f"{span_days} 天",
     f"{str(valid_dates.min())[:10]} ~ {str(valid_dates.max())[:10]}" if len(valid_dates) else "无有效日期"),
])

left, right = st.columns([3, 2], gap="medium")
with left:
    ui.panel("报道量趋势（按天）")
    daily = (
        df.dropna(subset=["published_at"])
        .assign(day=lambda x: pd.to_datetime(x["published_at"]).dt.date)
        .groupby("day").size().reset_index(name="文章数")
    )
    fig = px.area(daily, x="day", y="文章数")
    fig.update_traces(line_color="#a78bfa", fillcolor="rgba(167,139,250,.18)")
    fig.update_layout(xaxis_title=None)
    ui.chart(fig, height=300)
with right:
    ui.panel("来源分布（Top 15）")
    src = df["source"].value_counts().head(15).reset_index()
    src.columns = ["来源", "数量"]
    fig = px.bar(src, x="数量", y="来源", orientation="h")
    fig.update_traces(marker_color="#a78bfa")
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig, height=300)

ui.panel("文章列表")
page_size = 20
total_pages = (len(df) - 1) // page_size + 1
page = st.number_input(f"页码（共 {total_pages} 页）", min_value=1, max_value=total_pages, value=1) - 1
for _, r in df.iloc[page * page_size:(page + 1) * page_size].iterrows():
    src = str(r["source"])[:40] + ("…" if len(str(r["source"])) > 40 else "")
    with st.expander(f"[{src}] {r['title']}  ·  {str(r['published_at'])[:10]}"):
        st.write(r["body"])
        cols = st.columns([1, 3])
        cols[0].caption(f"关联 ACLED 事件: {r['related_event_id'] or '无'}")
        cols[1].markdown(f"[原文链接]({r['url']})")
