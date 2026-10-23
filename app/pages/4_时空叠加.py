import sys
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("时空叠加")
mode = ui.mode()
ui.page_header(
    "红海危机 · 时空叠加分析",
    "AIS 船舶轨迹叠加 ACLED 危机事件（按 AIS 关联层级着色）· 观察袭击事件与航运动态的时空关联",
    chips=["AIS × ACLED 联动", "2023-10 ~ 2023-12"],
)

ais_meta = query("SELECT MIN(ts) a, MAX(ts) b FROM ais_positions")
if ais_meta["a"][0] is None:
    st.info("暂无数据，请先入库。")
    st.stop()

tmin = pd.Timestamp(ais_meta["a"][0]).date()
tmax = pd.Timestamp(ais_meta["b"][0]).date()

REGIONS = {
    "红海全域": (20.5, 38.5, 9.5),
    "曼德海峡": (12.8, 43.3, 2.5),
    "苏伊士湾": (28.5, 33.0, 2.5),
    "亚丁湾": (12.5, 46.5, 4.0),
    "全球": (20.0, 60.0, None),
}

# AIS 关联层级是有序类别：C → B → A 支撑 → A 直接，单一红色由浅到深（深色主题由暗到亮）
_TIER_RAMP = dict(zip(("tier_C_context", "tier_B_signal", "tier_A_enabling", "tier_A_direct"),
                      (palette.rgb(c) for c in palette.ordinal(4, mode))))
TIER_STYLE = {
    "tier_A_direct": ("A级·直接相关", _TIER_RAMP["tier_A_direct"]),
    "tier_A_enabling": ("A级·支撑行动", _TIER_RAMP["tier_A_enabling"]),
    "tier_B_signal": ("B级·信号事件", _TIER_RAMP["tier_B_signal"]),
    "tier_C_context": ("C级·背景事件", _TIER_RAMP["tier_C_context"]),
}

with st.sidebar:
    st.subheader("筛选")
    region = st.selectbox("关注区域", list(REGIONS.keys()))
    d1, d2 = ui.date_range(st.date_input("日期范围", (tmin, tmax)))
    show_ais = st.checkbox("AIS 船舶轨迹", True)
    show_acled = st.checkbox("ACLED 危机事件", True)
    sel_tiers = st.multiselect(
        "ACLED · AIS 关联层级",
        list(TIER_STYLE.keys()),
        default=["tier_A_direct", "tier_A_enabling", "tier_B_signal"],
        format_func=lambda t: TIER_STYLE[t][0], placeholder="全部",
        help="A级=直接影响航运的事件，默认隐藏纯背景类事件",
    )
    show_gdelt = st.checkbox("GDELT 背景事件", False)

lat0, lon0, radius = REGIONS[region]
geo_cond = "1=1" if radius is None else (
    f"lat BETWEEN {lat0 - radius} AND {lat0 + radius} "
    f"AND lon BETWEEN {lon0 - radius} AND {lon0 + radius}"
)

layers, kpis, legend_items = [], [], []

if show_ais:
    # 活跃度 Top 150 船舶、每 15 分钟抽稀，避免千万级点位压垮前端
    ais = query(
        f"""
        WITH active AS (
            SELECT mmsi FROM ais_positions
            WHERE {geo_cond} AND ts BETWEEN ? AND ?
            GROUP BY mmsi ORDER BY COUNT(*) DESC LIMIT 150
        )
        SELECT DISTINCT ON (p.mmsi, time_bucket(INTERVAL 15 MINUTE, p.ts))
               p.mmsi, COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS ship_name,
               s.ship_type, p.ts, p.lat, p.lon
        FROM ais_positions p
        LEFT JOIN ais_ships s USING (mmsi)
        WHERE {geo_cond.replace('lat', 'p.lat').replace('lon', 'p.lon')}
          AND p.ts BETWEEN ? AND ?
          AND p.mmsi IN (SELECT mmsi FROM active)
        ORDER BY p.mmsi, p.ts
        """,
        (str(d1), str(d2) + " 23:59:59", str(d1), str(d2) + " 23:59:59"),
    )
    kpis.append(("AIS 位置点（抽稀后）", f"{len(ais):,}",
                 f"{ais['mmsi'].nunique() if len(ais) else 0} 艘活跃船舶", palette.SOURCE["ais"]))
    if not ais.empty:
        paths = (
            ais.groupby(["mmsi", "ship_name"])
            .apply(lambda g: g[["lon", "lat"]].values.tolist(), include_groups=False)
            .reset_index(name="path")
        )
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=paths,
                get_path="path",
                get_color=ui.C_AIS + [210],
                width_min_pixels=2,
                pickable=True,
            )
        )
        legend_items.append(("AIS 船舶轨迹", ui.C_AIS))

if show_gdelt:
    gdelt = query(
        f"""
        SELECT event_date, actor1, actor2, event_code, goldstein, lat, lon
        FROM gdelt_events
        WHERE {geo_cond} AND event_date BETWEEN ? AND ? LIMIT 100000
        """,
        (str(d1), str(d2)),
    )
    kpis.append(("GDELT 事件", f"{len(gdelt):,}",
                 f"平均 Goldstein {gdelt['goldstein'].mean():+.1f}" if len(gdelt) else "无", palette.SOURCE["gdelt"]))
    if not gdelt.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=gdelt,
                get_position="[lon, lat]",
                get_radius=6000,
                get_fill_color=ui.C_GDELT + [210],
                pickable=True,
            )
        )
        legend_items.append(("GDELT 事件", ui.C_GDELT))

if show_acled:
    tier_cond = "1=1"
    if sel_tiers:
        tier_cond = ui.in_list("ais_tier", sel_tiers)
    acled = query(
        f"""
        SELECT event_date, event_type, sub_event_type, location, country,
               fatalities, risk_level, phase, ais_tier, chokepoint, lat, lon
        FROM acled_events
        WHERE {geo_cond} AND event_date BETWEEN ? AND ? AND {tier_cond}
        LIMIT 100000
        """,
        (str(d1), str(d2)),
    )
    tier_a = int(acled["ais_tier"].str.startswith("tier_A").sum()) if len(acled) else 0
    kpis.append(("ACLED 危机事件", f"{len(acled):,}",
                 f"A级直接相关 {tier_a} 起", palette.SOURCE["acled"]))
    if not acled.empty:
        _unknown = palette.rgb(palette.OTHER_GRAY[mode])
        acled["color"] = acled["ais_tier"].map(lambda t: TIER_STYLE.get(t, ("", _unknown))[1])
        acled["tier_cn"] = acled["ais_tier"].map(lambda t: TIER_STYLE.get(t, (t, None))[0])
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=acled,
                get_position="[lon, lat]",
                get_radius="3000 + risk_level * 4000",
                get_fill_color="color",
                opacity=0.9,
                pickable=True,
            )
        )
        for t in (sel_tiers or TIER_STYLE.keys()):
            legend_items.append(TIER_STYLE[t])

if kpis:
    ui.kpi_row(kpis)

if not layers:
    st.warning("当前筛选下没有可显示的数据")
    st.stop()

# 区域按查询范围定位；全球视图低于 fit_bounds 的最小缩放，单独处理
lat, lon, zoom = (lat0, lon0, 1.8) if radius is None else ui.fit_bounds(
    lon0 - radius, lat0 - radius, lon0 + radius, lat0 + radius, viewport=(1100, 620))
ui.deck(
    layers,
    lat=lat, lon=lon, zoom=zoom,
    tooltip="{ship_name}{event_type}{actor1}",
    height=620,
)
ui.legend(legend_items)
