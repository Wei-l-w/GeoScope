"""GIS 工具层：封装为 LangChain Tools，供 ReAct Agent 点名调用（JD 第 2 条）。

设计取舍：
- 点面类空间运算（缓冲区/范围内统计）一律下推 DuckDB SQL 执行——
  千万行级数据下比 geopandas 全表拉取快几个数量级；
- 工具返回值统一为文本摘要；涉及几何的结果同时落盘 GeoJSON 到
  data/agent_output/（M4 地图界面直接读取渲染），路径写进返回值里。
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests
from langchain_core.tools import tool

from . import config, db

OUTPUT_DIR = config.ROOT / "data" / "agent_output"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_UA = {"User-Agent": "geoagent-demo/0.1 (educational project)"}

_MAX_TRACK_POINTS = 500  # 航迹抽稀上限，避免超大 GeoJSON

# 内置地名库：Nominatim 不可达时的离线兜底（覆盖本项目高频地名）
GAZETTEER = {
    "霍尔木兹海峡": (26.57, 56.25), "strait of hormuz": (26.57, 56.25),
    "曼德海峡": (12.58, 43.33), "bab el-mandeb": (12.58, 43.33),
    "苏伊士运河": (30.46, 32.34), "suez canal": (30.46, 32.34),
    "马六甲海峡": (2.20, 102.20), "strait of malacca": (2.20, 102.20),
    "红海": (19.0, 39.5), "red sea": (19.0, 39.5),
    "亚丁湾": (12.0, 47.0), "gulf of aden": (12.0, 47.0),
    "波斯湾": (26.5, 52.0), "persian gulf": (26.5, 52.0),
    "台湾海峡": (24.5, 119.5), "taiwan strait": (24.5, 119.5),
    "巴拿马运河": (9.08, -79.68), "panama canal": (9.08, -79.68),
}


def _gazetteer_lookup(place: str) -> tuple[float, float] | None:
    p = place.strip().lower()
    for name, coord in GAZETTEER.items():
        if name in p or p in name:
            return coord
    return None


def _save_geojson(name: str, geojson: dict) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{int(time.time())}_{name}.geojson"
    path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _circle_polygon(lat: float, lon: float, radius_km: float, n: int = 64) -> list:
    """近似圆多边形（WGS84 等距圆柱近似，小半径足够精确）。"""
    dlat = radius_km / 111.32
    dlon = radius_km / (111.32 * math.cos(math.radians(lat)))
    coords = [
        [lon + dlon * math.cos(2 * math.pi * i / n), lat + dlat * math.sin(2 * math.pi * i / n)]
        for i in range(n)
    ]
    coords.append(coords[0])
    return [coords]


@tool
def geocode(place: str) -> str:
    """地理编码：把地名（中英文均可，如"霍尔木兹海峡"/"Strait of Hormuz"）翻译成经纬度。
    涉及地名的空间分析必须先用本工具拿坐标，禁止凭印象猜坐标。"""
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place, "format": "json", "limit": 3},
            headers=_UA,
            timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json()
    except Exception as e:
        coord = _gazetteer_lookup(place)
        if coord:
            return f"在线地理编码不可用（{type(e).__name__}），已命中内置地名库：{place} -> lat={coord[0]}, lon={coord[1]}"
        return f"地理编码服务不可用：{e}。可改用 query_database 工具结合已知坐标范围查询。"
    if not hits:
        coord = _gazetteer_lookup(place)
        if coord:
            return f"在线服务无结果，已命中内置地名库：{place} -> lat={coord[0]}, lon={coord[1]}"
        return f"未找到地名：{place}。换个更通用的名称（如英文官方名）重试。"
    lines = [f"{h['display_name']} -> lat={h['lat']}, lon={h['lon']}" for h in hits]
    return "候选结果（取第一个最准）：\n" + "\n".join(lines)


@tool
def buffer_analysis(lat: float, lon: float, radius_km: float, table: str = "acled_events") -> str:
    """缓冲区分析：以 (lat, lon) 为圆心、radius_km 为半径画圈，统计圈内事件并输出 GeoJSON。
    table 可选 acled_events / gdelt_events。适合"某海峡/港口周边 X 公里内发生了什么"。"""
    if table not in ("acled_events", "gdelt_events"):
        return f"不支持的表 {table}，仅支持 acled_events / gdelt_events。"
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or radius_km <= 0:
        return "参数非法：纬度 [-90,90]，经度 [-180,180]，半径必须为正数。"

    dlat = radius_km / 111.32
    dlon = radius_km / max(0.01, 111.32 * math.cos(math.radians(lat)))
    sql = f"""
        SELECT event_date, event_type, location, lat, lon,
               {111.32} * SQRT(POW(lat - {lat}, 2) +
                    POW((lon - {lon}) * COS(RADIANS({lat})), 2)) AS dist_km
        FROM {table}
        WHERE lat BETWEEN {lat - dlat} AND {lat + dlat}
          AND lon BETWEEN {lon - dlon} AND {lon + dlon}
    """ if table == "acled_events" else f"""
        SELECT event_date, event_code AS event_type, country AS location, lat, lon,
               {111.32} * SQRT(POW(lat - {lat}, 2) +
                    POW((lon - {lon}) * COS(RADIANS({lat})), 2)) AS dist_km
        FROM {table}
        WHERE lat BETWEEN {lat - dlat} AND {lat + dlat}
          AND lon BETWEEN {lon - dlon} AND {lon + dlon}
    """
    with db.connect() as con:
        rows = con.execute(sql).fetchall()
    inside = [r for r in rows if r[5] <= radius_km]

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"kind": "buffer", "radius_km": radius_km},
                "geometry": {"type": "Polygon", "coordinates": _circle_polygon(lat, lon, radius_km)},
            }
        ]
        + [
            {
                "type": "Feature",
                "properties": {"date": str(r[0]), "event_type": r[1], "location": r[2], "dist_km": round(r[5], 1)},
                "geometry": {"type": "Point", "coordinates": [r[4], r[3]]},
            }
            for r in inside
        ],
    }
    path = _save_geojson("buffer", geojson)
    return (
        f"缓冲区（{lat}, {lon}）半径 {radius_km}km：圈内共 {len(inside)} 条记录"
        f"（{table}）。GeoJSON 已保存：{path}"
    )


@tool
def ship_track(mmsi: int, days: int = 7) -> str:
    """船舶航迹：取指定 MMSI 最近 days 天的 AIS 位置点，输出抽稀后的 GeoJSON 航迹线。
    适合"这艘船最近走过哪里/是否经过某区域"。"""
    with db.connect() as con:
        total = con.execute(
            "SELECT COUNT(*) FROM ais_positions WHERE mmsi = ? "
            "AND ts >= (SELECT MAX(ts) FROM ais_positions) - INTERVAL (?) DAY",
            [mmsi, days],
        ).fetchone()[0]
        if total == 0:
            return f"未找到 MMSI={mmsi} 最近 {days} 天的位置（可能无数据或时间窗不对）。"
        step = max(1, total // _MAX_TRACK_POINTS)
        rows = con.execute(
            f"""
            SELECT ts, lat, lon, sog FROM (
                SELECT ts, lat, lon, sog,
                       ROW_NUMBER() OVER (ORDER BY ts) AS rn
                FROM ais_positions
                WHERE mmsi = ?
                  AND ts >= (SELECT MAX(ts) FROM ais_positions) - INTERVAL (?) DAY
            ) WHERE rn % {step} = 1 ORDER BY ts
            """,
            [mmsi, days],
        ).fetchall()

    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"mmsi": mmsi, "days": days, "points_total": total, "points_shown": len(rows)},
            "geometry": {"type": "LineString", "coordinates": [[r[2], r[1]] for r in rows]},
        }],
    }
    path = _save_geojson(f"track_{mmsi}", geojson)
    t0, t1 = rows[0][0], rows[-1][0]
    return (
        f"MMSI={mmsi} 航迹：{t0} ~ {t1}，共 {total} 个位置点，抽稀为 {len(rows)} 点。"
        f"GeoJSON 已保存：{path}"
    )


_LAT_NAMES = {"lat", "latitude"}
_LON_NAMES = {"lon", "lng", "longitude"}
_MAX_GEO_POINTS = 2000  # 查询结果上图的点数上限


def _rows_to_geojson(result) -> str | None:
    """查询结果含经纬度列时转成 GeoJSON 点集并落盘，供地图渲染。无坐标列返回 None。"""
    cols = [c.lower() for c in result.columns]
    try:
        lat_i = next(i for i, c in enumerate(cols) if c in _LAT_NAMES)
        lon_i = next(i for i, c in enumerate(cols) if c in _LON_NAMES)
    except StopIteration:
        return None

    features = []
    for row in result.rows[:_MAX_GEO_POINTS]:
        lat, lon = row[lat_i], row[lon_i]
        if lat is None or lon is None:
            continue
        props = {}
        for name, value in zip(result.columns, row):
            if name.lower() in _LAT_NAMES | _LON_NAMES:
                continue
            props[name] = str(value)[:80] if value is not None else ""
        features.append({
            "type": "Feature",
            "properties": props,
            "geometry": {"type": "Point", "coordinates": [float(lon), float(lat)]},
        })
    if not features:
        return None
    path = _save_geojson("query", {"type": "FeatureCollection", "features": features})
    note = f"\nGeoJSON 已保存：{path}"
    if len(result.rows) > _MAX_GEO_POINTS:
        note += f"（仅前 {_MAX_GEO_POINTS} 个点上图）"
    return note


@tool
def query_database(question: str) -> str:
    """通用查数工具：把自然语言统计/筛选问题转成 SQL 查询数据仓库
    （AIS 船舶、GDELT/ACLED 事件、新闻）。空间范围统计优先用 buffer_analysis。
    若问题涉及具体地点/事件位置，请在 SQL 中带上 lat、lon 列，结果会自动上图。"""
    from . import geosql  # 延迟导入避免循环依赖

    result = geosql.ask(question, verbose=False)
    if not result.ok:
        return f"查询失败：{result.error}"
    preview = "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in result.rows[:15])
    if len(result.rows) > 15:
        preview += f"\n... 共 {len(result.rows)} 行，仅展示前 15 行"
    geo_note = _rows_to_geojson(result) or ""
    return f"SQL：{result.sql}\n\n列：{' | '.join(result.columns)}\n{preview}{geo_note}"


@tool
def knowledge_search(query: str) -> str:
    """空间知识库检索：从新闻报道和事件描述中找背景信息（RAG）。
    语料为英文，请把查询改写为英文关键词（如 "Houthi attack cargo ship"）。
    适合"这起事件的背景是什么/有哪些相关报道"类问题，返回结果附出处。"""
    from . import rag

    try:
        hits = rag.search(query)
    except Exception as e:
        return f"知识库检索失败：{e}"
    if not hits:
        return f"知识库中未找到与「{query}」相关的内容（语料覆盖 2023-2024 红海危机窗口）。"
    lines = []
    for chunk, score in hits:
        cite = f"（来源：{chunk.source_table}#{chunk.ref_id}"
        if chunk.url:
            cite += f"，{chunk.url}"
        cite += f"，{chunk.date[:10]}）"
        lines.append(f"[相关度 {score:.2f}] {chunk.title}{cite}\n  {chunk.text[:300]}")
    return "\n\n".join(lines)


ALL_TOOLS = [geocode, buffer_analysis, ship_track, query_database, knowledge_search]
