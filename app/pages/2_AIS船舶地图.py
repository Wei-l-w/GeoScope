import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("AIS 船舶")
mode = ui.mode()
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
    st.subheader("筛选")
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
    sel_names = st.multiselect("船舶", ships["name"].tolist(), placeholder="全部（可搜索）")
    types = query("SELECT DISTINCT ship_type FROM ais_ships WHERE ship_type IS NOT NULL ORDER BY 1")
    sel_types = st.multiselect("船舶类型", types["ship_type"].tolist(), placeholder="全部")
    view_mode = st.radio("图层模式", ["轨迹线", "密度热力图"], horizontal=True)
    if view_mode == "轨迹线":
        max_ships = st.slider("最多显示船舶数（按活跃度取 Top N）", 20, 500, 120, step=20)

conds, params = ["p.ts BETWEEN ? AND ?"], [date_range[0], date_range[1]]
if sel_names:
    mmsis = ships[ships["name"].isin(sel_names)]["mmsi"].tolist()
    conds.append(f"p.mmsi IN ({','.join(str(m) for m in mmsis)})")
if sel_types:
    conds.append(ui.in_list("s.ship_type", sel_types))
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
    # 实际数据里货船、油轮占绝大多数，其余船型合计约 5%，归入"其他"（地图上最多 3 类颜色）
    TYPE_COLORS = {"货船": palette.PALETTE[0], "油轮": palette.PALETTE[1], "其他": palette.OTHER_GRAY[mode]}
    paths["color"] = paths["ship_type"].map(lambda t: palette.rgb(TYPE_COLORS.get(t, TYPE_COLORS["其他"])))
    marker = palette.MAP[mode]  # 最新位置：正文色实心点 + 背景色描边，两种主题下都醒目
    last_pos = df.sort_values("ts").groupby("mmsi").tail(1)
    layers = [
        pdk.Layer(
            "PathLayer",
            data=paths,
            get_path="path",
            get_color="color",
            width_min_pixels=2,
            opacity=0.86,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=last_pos,
            get_position="[lon, lat]",
            get_radius=2200,
            get_fill_color=palette.rgb(marker["ring"]),
            get_line_color=palette.rgb(marker["stroke"]),
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        ),
    ]
    tooltip = "{ship_name} ({ship_type})"
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
            color_range=palette.sequential("blue", mode),
        )
    ]
    tooltip = None

lat, lon, zoom = ui.fit_bounds(df["lon"].min(), df["lat"].min(), df["lon"].max(), df["lat"].max(),
                               viewport=(1100, 560))
ui.deck(layers, lat=lat, lon=lon, zoom=zoom, tooltip=tooltip, height=560)
if view_mode == "轨迹线":
    ui.legend(list(TYPE_COLORS.items()) + [("最新位置", marker["ring"])])

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
st.dataframe(summary, width="stretch", hide_index=True)
