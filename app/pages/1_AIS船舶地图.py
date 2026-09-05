import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ui
from db import query

ui.setup("AIS 船舶地图", accent="#22d3ee")
ui.page_header(
    "AIS 船舶时空轨迹",
    "红海海域船舶航行轨迹与密度分析 · 动态位置关联静态船舶档案",
    chips=["红海海域 88 天", "37.6M 位置点"],
)

meta = query("SELECT MIN(ts) a, MAX(ts) b FROM ais_positions")
if meta["a"][0] is None:
    st.info("暂无 AIS 数据，请先入库。")
    st.stop()

tmin, tmax = pd.Timestamp(meta["a"][0]), pd.Timestamp(meta["b"][0])
default_start = max(tmin, tmax - timedelta(hours=24))

with st.sidebar:
    st.header("筛选")
    date_range = st.slider(
        "时间窗口",
        min_value=tmin.to_pydatetime(),
        max_value=tmax.to_pydatetime(),
        value=(default_start.to_pydatetime(), tmax.to_pydatetime()),
        format="MM-DD HH:mm",
        help="数据量大，默认展示最后 24 小时",
    )
    ships = query(
        """
        SELECT mmsi, COALESCE(ship_name, CAST(mmsi AS VARCHAR)) AS name
        FROM ais_ships ORDER BY name
        """
    )
    sel_names = st.multiselect("船舶（可搜索，默认全部）", ships["name"].tolist())
    types = query("SELECT DISTINCT ship_type FROM ais_ships WHERE ship_type IS NOT NULL ORDER BY 1")
    sel_types = st.multiselect("船舶类型（默认全部）", types["ship_type"].tolist())
    view_mode = st.radio("图层模式", ["轨迹线", "密度热力图"], horizontal=True)
    if view_mode == "轨迹线":
        max_ships = st.slider("最多显示船舶数（按活跃度取 Top N）", 20, 500, 120, step=20)

conds, params = ["p.ts BETWEEN ? AND ?"], [date_range[0], date_range[1]]
if sel_names:
    mmsis = ships[ships["name"].isin(sel_names)]["mmsi"].tolist()
    conds.append(f"p.mmsi IN ({','.join(str(m) for m in mmsis)})")
if sel_types:
    quoted = ",".join("'" + t.replace("'", "''") + "'" for t in sel_types)
    conds.append(f"s.ship_type IN ({quoted})")
where = " AND ".join(conds)

BASE = f"""
    FROM ais_positions p
    LEFT JOIN ais_ships s USING (mmsi)
    WHERE {where}
"""

stat = query(f"SELECT COUNT(*) n, COUNT(DISTINCT p.mmsi) ships, AVG(p.sog) sog {BASE}", tuple(params))
n_total, n_ships = int(stat["n"][0]), int(stat["ships"][0])
if n_total == 0:
    st.warning("筛选结果为空")
    st.stop()

hours = max((date_range[1] - date_range[0]).total_seconds() / 3600, 1)
ui.kpi_row([
    ("位置点", f"{n_total:,}", f"时间窗 {hours:.0f} 小时"),
    ("在航船舶", f"{n_ships:,}", "本时间窗内上报过位置"),
    ("平均航速", f"{stat['sog'][0]:.1f} kn", "对地航速"),
    ("船舶档案", f"{query('SELECT COUNT(*) n FROM ais_ships')['n'][0]:,}", "静态数据档案总数"),
])

if view_mode == "轨迹线":
    # 每船每 10 分钟抽稀一个点，并只取活跃度 Top N 船舶，保证渲染流畅
    df = query(
        f"""
        WITH active AS (
            SELECT p.mmsi {BASE}
            GROUP BY p.mmsi ORDER BY COUNT(*) DESC LIMIT {max_ships}
        ),
        thinned AS (
            SELECT DISTINCT ON (p.mmsi, time_bucket(INTERVAL 10 MINUTE, p.ts))
                   p.mmsi, p.ts, p.lat, p.lon,
                   COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS ship_name,
                   COALESCE(s.ship_type, '未知') AS ship_type
            {BASE} AND p.mmsi IN (SELECT mmsi FROM active)
        )
        SELECT * FROM thinned ORDER BY mmsi, ts
        """,
        tuple(params * 2),
    )
    paths = (
        df.groupby(["mmsi", "ship_name", "ship_type"])
        .apply(lambda g: g[["lon", "lat"]].values.tolist(), include_groups=False)
        .reset_index(name="path")
    )
    TYPE_COLORS = {
        "货船": [34, 211, 238], "油轮": [251, 191, 36], "渔船": [52, 211, 153],
        "客船": [167, 139, 250], "军用船": [248, 113, 113], "高速船": [96, 165, 250],
        "拖轮": [251, 146, 60], "未知": [120, 130, 150],
    }
    paths["color"] = paths["ship_type"].map(lambda t: TYPE_COLORS.get(t, [148, 163, 184]))
    last_pos = df.sort_values("ts").groupby("mmsi").tail(1)
    layers = [
        pdk.Layer(
            "PathLayer",
            data=paths,
            get_path="path",
            get_color="color",
            width_min_pixels=2,
            opacity=0.75,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=last_pos,
            get_position="[lon, lat]",
            get_radius=2200,
            get_fill_color=[241, 245, 249],
            get_line_color=[34, 211, 238],
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        ),
    ]
    tooltip = "{ship_name} ({ship_type})"
    center_lat, center_lon = df["lat"].mean(), df["lon"].mean()
    st.caption(f"轨迹已按活跃度取 Top {min(max_ships, paths.shape[0])} 艘、每 10 分钟抽稀")
else:
    # 热力图 12 万采样点在视觉上与 40 万几乎无差别，但浏览器渲染负担小得多
    df = query(
        f"SELECT p.lat, p.lon {BASE} USING SAMPLE reservoir(120000 ROWS) REPEATABLE (42)",
        tuple(params),
    )
    layers = [
        pdk.Layer(
            "HeatmapLayer",
            data=df[["lon", "lat"]],
            get_position="[lon, lat]",
            radius_pixels=28,
            color_range=[
                [13, 21, 38, 0], [30, 64, 120, 120], [34, 211, 238, 170],
                [251, 191, 36, 200], [248, 113, 113, 230], [255, 240, 220, 255],
            ],
        )
    ]
    tooltip = None
    center_lat, center_lon = df["lat"].mean(), df["lon"].mean()

ui.deck(layers, lat=center_lat, lon=center_lon, zoom=5, tooltip=tooltip, height=560)
if view_mode == "轨迹线":
    ui.legend([(t, c) for t, c in TYPE_COLORS.items()] + [("最新位置", [241, 245, 249])])

ui.panel("船舶概况（本时间窗 Top 200）")
summary = query(
    f"""
    SELECT COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS 船名, p.mmsi AS MMSI,
           COALESCE(s.ship_type, '未知') AS 类型, s.length_m AS 船长_米,
           s.destination AS 目的地, COUNT(*) AS 位置点数,
           ROUND(AVG(p.sog), 1) AS 平均航速_节, MAX(p.ts) AS 最后上报时间
    {BASE}
    GROUP BY 1, 2, 3, 4, 5 ORDER BY 位置点数 DESC LIMIT 200
    """,
    tuple(params),
)
st.dataframe(summary, use_container_width=True, hide_index=True)
