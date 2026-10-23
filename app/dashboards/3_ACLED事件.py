import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT in sys.path:  # 每次 rerun 都会重跑本文件；Streamlit 还会把它自己插入的脚本路径留在表头
    sys.path.remove(ROOT)  # 先移除再插回，表头始终是本仓库，也不会随 rerun 越积越多
sys.path.insert(0, ROOT)
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("ACLED 事件")
mode = ui.mode()
ui.page_header(
    "ACLED 红海危机事件",
    "LLM 筛选增强版 · 危机阶段 / 风险等级 / 因果角色 / AIS 关联层级 / 咽喉要道 全维度标注",
    chips=["LLM 筛选增强", "1,565 事件"],
)

meta = query("SELECT MIN(event_date) a, MAX(event_date) b FROM acled_events")
if meta["a"][0] is None:
    st.info("暂无 ACLED 数据，请先入库。")
    st.stop()

dmin, dmax = pd.Timestamp(meta["a"][0]).date(), pd.Timestamp(meta["b"][0]).date()

PHASE_LABELS = {
    "precursor": "前兆期",
    "trigger_chain": "触发链",
    "maritime_crisis": "海上危机期",
}
# 危机阶段是有序类别：单一红色由浅到深（深色主题由暗到亮）
PHASE_COLORS = dict(zip(PHASE_LABELS, (palette.rgb(c) for c in palette.ordinal(3, mode))))
CAUSAL_LABELS = {
    "direct_maritime_attack": "直接海上袭击",
    "coalition_response": "联军回应",
    "coastal_control": "沿岸控制",
    "regional_escalation": "地区升级",
    "geopolitical_context": "地缘背景",
}
TIER_LABELS = {
    "tier_A_direct": "A级·直接相关",
    "tier_A_enabling": "A级·支撑行动",
    "tier_B_signal": "B级·信号事件",
    "tier_C_context": "C级·背景事件",
}
DOMAIN_LABELS = {"maritime": "海上", "air": "空中", "land": "陆上"}

with st.sidebar:
    st.subheader("筛选")
    d1, d2 = ui.date_range(st.date_input("日期范围", (dmin, dmax), min_value=dmin, max_value=dmax))
    sel_phase = st.multiselect(
        "危机阶段", list(PHASE_LABELS.keys()),
        format_func=lambda x: PHASE_LABELS.get(x, x), placeholder="全部",
    )
    risk_range = st.slider("风险等级", 1, 5, (1, 5))
    sel_causal = st.multiselect(
        "危机因果角色", list(CAUSAL_LABELS.keys()),
        format_func=lambda x: CAUSAL_LABELS.get(x, x), placeholder="全部",
    )
    sel_tier = st.multiselect(
        "AIS 关联层级", list(TIER_LABELS.keys()),
        format_func=lambda x: TIER_LABELS.get(x, x), placeholder="全部",
    )
    sel_domain = st.multiselect(
        "事件域", list(DOMAIN_LABELS.keys()),
        format_func=lambda x: DOMAIN_LABELS.get(x, x), placeholder="全部",
    )
    countries = query("SELECT DISTINCT country FROM acled_events ORDER BY 1")
    sel_countries = st.multiselect("国家", countries["country"].tolist(), placeholder="全部")
    only_kinetic = st.checkbox("仅动能事件")
    only_vessel = st.checkbox("仅船舶目标事件")


conds, params = ["event_date BETWEEN ? AND ?", "risk_level BETWEEN ? AND ?"], [d1, d2, *risk_range]
if sel_phase:
    conds.append(ui.in_list("phase", sel_phase))
if sel_causal:
    conds.append(ui.in_list("causal_role", sel_causal))
if sel_tier:
    conds.append(ui.in_list("ais_tier", sel_tier))
if sel_domain:
    conds.append(ui.in_list("domain", sel_domain))
if sel_countries:
    conds.append(ui.in_list("country", sel_countries))
if only_kinetic:
    conds.append("is_kinetic")
if only_vessel:
    conds.append("target_class = 'vessel'")
where = " AND ".join(conds)

df = query(f"SELECT * FROM acled_events WHERE {where}", tuple(params))

if df.empty:
    st.warning("筛选结果为空")
    st.stop()

tier_a = int(df["ais_tier"].str.startswith("tier_A").sum())
ui.kpi_row([
    ("事件总数", f"{len(df):,}",
     f"{df['country'].nunique()} 个国家 · 平均风险 {df['risk_level'].mean():.1f}/5"),
    ("A级 AIS 关联", f"{tier_a}",
     f"直接影响航运 · 5级事件 {int((df['risk_level'] == 5).sum())} 起"),
    ("海上域事件", f"{int((df['domain'] == 'maritime').sum())}",
     f"船舶目标 {int((df['target_class'] == 'vessel').sum())} 起"),
    ("死亡总数", f"{int(df['fatalities'].sum()):,}",
     f"动能事件 {int(df['is_kinetic'].sum())} 起"),
])

_unknown = palette.rgb(palette.OTHER_GRAY[mode])
df["color"] = df["phase"].map(lambda p: PHASE_COLORS.get(p, _unknown))
df["phase_cn"] = df["phase"].map(PHASE_LABELS).fillna("未知")
df["causal_cn"] = df["causal_role"].map(CAUSAL_LABELS).fillna(df["causal_role"])

lat, lon, zoom = ui.fit_bounds(df["lon"].min(), df["lat"].min(), df["lon"].max(), df["lat"].max(),
                               viewport=(1100, 540))
ui.deck(
    [
        pdk.Layer(
            "ScatterplotLayer",
            data=df,
            get_position="[lon, lat]",
            get_radius="4000 + risk_level * 5000",
            get_fill_color="color",
            opacity=0.9,
            pickable=True,
        )
    ],
    lat=lat, lon=lon, zoom=zoom,
    tooltip="{phase_cn} · 风险{risk_level}级\n{event_type} / {sub_event_type}\n{location}, {country} · {event_date}\n因果角色: {causal_cn}\n咽喉要道: {chokepoint}",
    height=540,
)
ui.legend([(PHASE_LABELS[p], c) for p, c in PHASE_COLORS.items()])
st.caption("点径 = 风险等级 · 颜色 = 危机阶段")

left, right = st.columns(2, gap="medium")
with left:
    ui.panel("危机演化时间线（每周 · 按阶段）")
    weekly = (
        df.assign(week=pd.to_datetime(df["event_date"]).dt.to_period("W").dt.start_time)
        .groupby(["week", "phase_cn"]).size().reset_index(name="事件数")
    )
    fig = px.bar(weekly, x="week", y="事件数", color="phase_cn", barmode="stack",
                 color_discrete_map={PHASE_LABELS[p]: f"rgb({c[0]},{c[1]},{c[2]})"
                                     for p, c in PHASE_COLORS.items()},
                 category_orders={"phase_cn": list(PHASE_LABELS.values())},
                 labels={"week": "周", "phase_cn": "阶段"})
    ui.chart(fig, height=320)
with right:
    ui.panel("危机因果角色分布")
    causal = df["causal_cn"].value_counts().reset_index()
    causal.columns = ["因果角色", "事件数"]
    fig = px.bar(causal, x="事件数", y="因果角色", orientation="h")
    fig.update_traces(marker_color=palette.SOURCE["acled"])
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig, height=320)

c1, c2, c3 = st.columns(3, gap="medium")
with c1:
    ui.panel("咽喉要道关联")
    choke = (
        df.groupby("chokepoint")
        .agg(事件数=("event_id", "count"), 平均距离_km=("chokepoint_km", "mean"))
        .reset_index().dropna()
    )
    choke["平均距离_km"] = choke["平均距离_km"].round(0)
    fig = px.bar(choke, x="chokepoint", y="事件数", hover_data=["平均距离_km"])
    fig.update_traces(marker_color=palette.SOURCE["acled"])
    fig.update_layout(xaxis_title=None)
    ui.chart(fig, height=280)
with c2:
    ui.panel("AIS 关联层级")
    tier = df["ais_tier"].map(TIER_LABELS).value_counts().reset_index()
    tier.columns = ["层级", "事件数"]
    # 关联层级同样有序：C 背景 → B 信号 → A 支撑 → A 直接
    tier_order = [TIER_LABELS[t] for t in ("tier_C_context", "tier_B_signal", "tier_A_enabling", "tier_A_direct")]
    fig = px.pie(tier, names="层级", values="事件数", hole=0.55, color="层级",
                 color_discrete_map=dict(zip(tier_order, palette.ordinal(4, mode))),
                 category_orders={"层级": tier_order})
    ui.chart(fig, height=280)
with c3:
    ui.panel("事件域 × 动能")
    dom = (
        df.assign(域=df["domain"].map(DOMAIN_LABELS), 动能=df["is_kinetic"].map({True: "动能", False: "非动能"}))
        .groupby(["域", "动能"]).size().reset_index(name="事件数")
    )
    fig = px.bar(dom, x="域", y="事件数", color="动能", barmode="group",
                 color_discrete_map={"动能": palette.SOURCE["acled"], "非动能": palette.PALETTE[0]})
    fig.update_layout(xaxis_title=None)
    ui.chart(fig, height=280)

ui.panel("事件明细")
show_all = st.toggle("显示全部字段（25 个入库字段：专题标注、AIS 层级、港口/咽喉要道距离等）")
if show_all:
    full = df.drop(columns=["color", "phase_cn", "causal_cn"], errors="ignore").copy()
    full["event_date"] = pd.to_datetime(full["event_date"]).dt.date
    full = full.sort_values("event_date", ascending=False)
    st.dataframe(full, width="stretch", hide_index=True, height=420)
else:
    detail = df[["event_date", "phase_cn", "risk_level", "causal_cn", "event_type",
                 "sub_event_type", "country", "location", "target_class", "chokepoint",
                 "fatalities", "notes"]].copy()
    detail["event_date"] = pd.to_datetime(detail["event_date"]).dt.date
    detail = detail.sort_values("event_date", ascending=False)
    detail.columns = ["日期", "阶段", "风险", "因果角色", "事件类型", "子类型", "国家",
                      "地点", "目标类型", "咽喉要道", "死亡", "描述"]
    st.dataframe(detail, width="stretch", hide_index=True, height=360)
