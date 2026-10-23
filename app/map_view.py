"""工作台地图：把会话各轮的真实产物拆成可开关的图层，按主题配色上图（设计文档第 7 节）。

只读取通过 agent/artifacts.py 校验的本地 GeoJSON；回答正文里的路径永远不会变成图层。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pydeck as pdk
import streamlit as st

from agent import artifacts
from app import palette, ui

DEFAULT_VIEW = (15.0, 43.0, 4.5)
NOMINAL_VIEWPORT = (720, 560)  # 计算缩放用的名义视口（像素）
PADDING = 0.12
ORDER = ("buffer", "track", "events", "points", "other")  # 叠放顺序：缓冲区在最下
ICONS = {"buffer": ":material/radio_button_unchecked:", "events": ":material/scatter_plot:",
         "track": ":material/route:", "points": ":material/location_on:", "other": ":material/layers:"}
HIDDEN_KEY = "hidden_layers"
RESET_KEY = "map_reset_nonce"


@dataclass
class MapLayer:
    id: str
    path: str
    turn: int
    kind: str
    label: str
    features: list
    typed: bool = False  # ACLED 事件点：按类型着色


@dataclass
class MapState:
    layers: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    files: list = field(default_factory=list)  # [(轮次, 路径, 内容摘要)]，供下载
    view: tuple = DEFAULT_VIEW
    reset: int = 0  # "复位"计数

    @property
    def feature_count(self) -> int:
        return sum(len(layer.features) for layer in self.layers)


# ---------------------------------------------------------------- 数据
def turns(messages: list[dict]) -> list[tuple[int, list[str]]]:
    """[(轮次, 路径)]：轮次是助手回答的序号（从 1 开始），跳过没有产物的回答。"""
    result, turn = [], 0
    for message in messages:
        if message.get("role") != "assistant":
            continue
        turn += 1
        paths = list(dict.fromkeys(message.get("geojson") or []))
        if paths:
            result.append((turn, paths))
    return result


@st.cache_data(max_entries=256, show_spinner=False)
def _load_cached(path: str, mtime_ns: int, size: int) -> dict:
    return artifacts.load_geojson(path)


def load(path: str) -> dict:
    """按（路径，修改时间，大小）缓存校验结果；切换开关不重复读盘。"""
    try:
        stat = Path(path).stat()
    except (OSError, TypeError, ValueError):
        return artifacts.load_geojson(path)  # 交给校验函数给出统一的错误说明
    return _load_cached(str(path), stat.st_mtime_ns, stat.st_size)


def _kind(feature: dict) -> str:
    geometry = feature.get("geometry") or {}
    shape = geometry.get("type")
    props = feature.get("properties") or {}
    if shape in ("Polygon", "MultiPolygon") and props.get("kind") == "buffer":
        return "buffer"
    if shape == "Point" and "event_type" in props:
        return "events"
    if shape in ("LineString", "Point") and "mmsi" in props:
        return "track"
    if shape in ("Point", "MultiPoint"):
        return "points"
    return "other"


def split(data: dict) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for feature in data["features"]:
        groups.setdefault(_kind(feature), []).append(feature)
    return [(kind, groups[kind]) for kind in ORDER if kind in groups]


def layer_label(kind: str, features: list[dict]) -> str:
    first = features[0].get("properties") or {}
    if kind == "buffer":
        radius = first.get("radius_km")
        return f"缓冲区 {radius:g} km" if isinstance(radius, (int, float)) else "缓冲区"
    if kind == "track":
        return f"航迹 · {first.get('mmsi')}"
    if kind == "events":
        return f"事件点 · {len(features)}"
    if kind == "points":
        return f"查询结果 · {len(features)} 点"
    return f"图层 · {len(features)} 个要素"


def build(turn_paths: list[tuple[int, list[str]]], reset: int = 0) -> MapState:
    state = MapState()
    latest = {path: turn for turn, paths in turn_paths for path in paths}  # 重复出现的文件归到最后一轮
    seen = set()
    for turn, paths in turn_paths:
        for path in paths:
            if latest[path] != turn or path in seen:
                continue
            seen.add(path)
            try:
                data = load(path)
            except artifacts.ArtifactError as exc:
                state.errors.append(str(exc))
                continue
            parts = split(data)
            state.files.append((turn, path, "、".join(layer_label(kind, items) for kind, items in parts)))
            for kind, items in parts:
                typed = kind == "events" and all(
                    (item.get("properties") or {}).get("event_type") in palette.ACLED_TYPES for item in items)
                state.layers.append(MapLayer(f"{path}#{kind}", path, turn, kind,
                                             layer_label(kind, items), items, typed))
    counts = Counter(layer.label for layer in state.layers)
    for layer in state.layers:
        if counts[layer.label] > 1:
            layer.label = f"{layer.label} · 第 {layer.turn} 轮"
    state.errors = list(dict.fromkeys(state.errors))
    state.view = fit_view(state.layers)
    state.reset = reset
    return state


# ---------------------------------------------------------------- 视野
def fit_view(layers: list[MapLayer]) -> tuple[float, float, float]:
    """定位到最新一轮产出图层的范围；与图层是否隐藏无关，所以切换开关不会改变视野。"""
    if not layers:
        return DEFAULT_VIEW
    latest = max(layer.turn for layer in layers)
    features = [item for layer in layers if layer.turn == latest for item in layer.features]
    bounds = artifacts.coordinate_bounds({"type": "FeatureCollection", "features": features})
    return ui.fit_bounds(*bounds, viewport=NOMINAL_VIEWPORT, padding=PADDING)


# ---------------------------------------------------------------- 图层样式
def _tip(kind: str, props: dict) -> str:
    if kind == "buffer":
        radius = props.get("radius_km")
        return f"缓冲区 · 半径 {radius:g} km" if isinstance(radius, (int, float)) else "缓冲区"
    if kind == "track":
        return f"MMSI {props.get('mmsi')} · 展示 {props.get('points_shown')} / 共 {props.get('points_total')} 点"
    if kind == "events":
        parts = [str(props.get("date") or ""), palette.type_label(props.get("event_type")), str(props.get("location") or "")]
        if props.get("dist_km") is not None:
            parts.append(f"距中心 {props['dist_km']} km")
        return " · ".join(part for part in parts if part)
    return " · ".join(f"{key}: {value}" for key, value in list(props.items())[:3])


def _positions(geometry: dict) -> list:
    """Point 与 MultiPoint 统一成位置列表。"""
    coordinates = geometry["coordinates"]
    return [coordinates] if geometry["type"] == "Point" else list(coordinates)


def _records(layer: MapLayer, mode: str) -> list[dict]:
    rows = []
    for feature in layer.features:
        props = feature.get("properties") or {}
        tip = _tip(layer.kind, props)
        group = palette.event_group(props.get("event_type"))
        color = palette.rgb(palette.event_color(props.get("event_type"), mode))
        for position in _positions(feature["geometry"]):
            rows.append({"lon": position[0], "lat": position[1], "tip": tip, "group": group, "color": color})
    return rows


def _collection(layer: MapLayer) -> dict:
    features = [{**item, "properties": {**(item.get("properties") or {}), "tip": _tip(layer.kind, item.get("properties") or {})}}
                for item in layer.features]
    return {"type": "FeatureCollection", "features": features}


def _ring(rows: list[dict], mode: str) -> pdk.Layer:
    return pdk.Layer("ScatterplotLayer", data=rows, get_position="[lon, lat]", get_radius=3000,
                     radius_min_pixels=4, radius_max_pixels=9, filled=False, stroked=True,
                     get_line_color=palette.rgb(palette.MAP[mode]["ring"]), line_width_min_pixels=1.5,
                     pickable=True)


def deck_layers(layers: list[MapLayer], visible: set, mode: str) -> list[pdk.Layer]:
    colors = palette.MAP[mode]
    result = []
    for layer in sorted(layers, key=lambda item: (ORDER.index(item.kind), item.turn)):
        if layer.id not in visible:
            continue
        if layer.kind == "buffer":
            color = palette.rgb(colors["buffer"])
            result.append(pdk.Layer("GeoJsonLayer", data=_collection(layer), stroked=True, filled=True,
                                    get_fill_color=color + [23], get_line_color=color + [235],
                                    line_width_min_pixels=2, pickable=True))
        elif layer.kind == "track":
            color = palette.rgb(colors["track"])
            for feature in layer.features:
                geometry = feature["geometry"]
                tip = _tip("track", feature.get("properties") or {})
                path = geometry["coordinates"] if geometry["type"] == "LineString" else [geometry["coordinates"]]
                if len(path) > 1:
                    result.append(pdk.Layer("PathLayer", data=[{"path": path, "tip": tip}], get_path="path",
                                            get_color=color + [70], width_min_pixels=8,
                                            cap_rounded=True, joint_rounded=True))
                    result.append(pdk.Layer("PathLayer", data=[{"path": path, "tip": tip}], get_path="path",
                                            get_color=color, width_min_pixels=2.5, cap_rounded=True,
                                            joint_rounded=True, pickable=True))
                end = path[-1]
                result.append(pdk.Layer("ScatterplotLayer", data=[{"lon": end[0], "lat": end[1], "tip": tip}],
                                        get_position="[lon, lat]", get_radius=5000, radius_min_pixels=6,
                                        get_fill_color=[255, 255, 255], get_line_color=color, stroked=True,
                                        line_width_min_pixels=3, pickable=True))
        elif layer.kind == "events" and layer.typed:
            rows = _records(layer, mode)
            other = [row for row in rows if row["group"] == palette.OTHER]
            typed = [row for row in rows if row["group"] != palette.OTHER]
            stroke = palette.rgb(colors["stroke"])
            for data, min_px in ((other, 2.5), (typed, 3.5)):  # "其他"先画、点更小
                if data:
                    result.append(pdk.Layer("ScatterplotLayer", data=data, get_position="[lon, lat]",
                                            get_radius=3000, radius_min_pixels=min_px, radius_max_pixels=8,
                                            get_fill_color="color", get_line_color=stroke, stroked=True,
                                            line_width_min_pixels=1, pickable=True))
        elif layer.kind in ("events", "points"):
            result.append(_ring(_records(layer, mode), mode))
        else:
            result.append(pdk.Layer("GeoJsonLayer", data=_collection(layer), stroked=True, filled=False,
                                    get_line_color=palette.rgb(colors["ring"]), line_width_min_pixels=1.5,
                                    point_radius_min_pixels=4, pickable=True))
    return result


# ---------------------------------------------------------------- 渲染
def hidden(sid: str | None) -> set:
    return set(st.session_state.get(HIDDEN_KEY, {}).get(sid or "", set()))


def _store_hidden(key: str, sid: str | None, ids: list[str]) -> None:
    selected = set(st.session_state.get(key) or [])
    st.session_state.setdefault(HIDDEN_KEY, {})[sid or ""] = {item for item in ids if item not in selected}


def _bump_reset() -> None:
    st.session_state[RESET_KEY] = st.session_state.get(RESET_KEY, 0) + 1


def reset_count() -> int:
    return st.session_state.get(RESET_KEY, 0)


def render_bar(state: MapState, sid: str | None, busy: bool) -> set:
    """图层开关 + 复位 + 下载；返回当前可见的图层 id。开关多时在左栏内换行，两个图标固定在右侧。"""
    ids = [layer.id for layer in state.layers]
    visible = [item for item in ids if item not in hidden(sid)]
    layers_col, reset_col, download_col = st.columns([12, 1, 1.5], gap="small", vertical_alignment="center")
    with layers_col:
        if ids:
            digest = hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:10]
            key = f"layers_{sid or 'new'}_{digest}"  # 图层集合变化时换一个控件，默认值由隐藏集合算出
            names = {layer.id: f"{ICONS[layer.kind]} {layer.label}" for layer in state.layers}
            visible = st.pills("图层", ids, selection_mode="multi", default=visible, key=key,
                               format_func=names.get, label_visibility="collapsed", disabled=busy,
                               on_change=_store_hidden, args=(key, sid, ids)) or []
        else:
            st.caption("还没有图层")
    with reset_col:
        st.button("", key="map_reset", icon=":material/center_focus_strong:", type="tertiary",
                  disabled=busy or not ids, on_click=_bump_reset, help="复位：回到最新结果的范围")
    with download_col:
        with st.popover("", icon=":material/download:", disabled=busy or not state.files, key="map_download",
                        help="下载 GeoJSON"):
            for index, (turn, path, summary) in enumerate(state.files):
                file = Path(path)
                st.download_button(f"{summary} · 第 {turn} 轮 · {file.name}", file.read_bytes(),
                                   file_name=file.name, mime="application/geo+json",
                                   key=f"geoagent_download_{index}", on_click="ignore", width="stretch")
    return set(visible)


def render_alerts(state: MapState, last_error: str | None) -> None:
    if state.errors:
        st.warning("地图加载失败：" + "；".join(state.errors))
    if last_error and not state.layers:
        st.warning("本轮未生成可用地图，请查看对话中的执行失败说明。")


def view_state(state: MapState) -> pdk.ViewState:
    """Streamlit 只覆盖初始视野里"变了"的字段；复位时五个字段都挪一个肉眼不可见的量，
    才能把用户拖动、缩放、旋转过的视野全部重置。"""
    lat, lon, zoom = state.view
    nudge = state.reset * 1e-7
    return pdk.ViewState(latitude=lat + nudge, longitude=lon + nudge, zoom=zoom + nudge,
                         pitch=nudge, bearing=nudge)


def render_map(state: MapState, visible: set, mode: str, *, key: str = "workspace_map", slot=None) -> None:
    """平时直接画进当前容器、key 固定，重跑时地图组件保留用户拖动过的视野；
    流式分析时传入 st.empty() 槽位与每次不同的 key，新结果到达时重新定位。

    不要在页面里先建 st.empty() 再填地图：空占位会先替换掉旧地图，视野随之丢失。"""
    deck = pdk.Deck(map_style=None, layers=deck_layers(state.layers, visible, mode),
                    initial_view_state=view_state(state),
                    tooltip={"text": "{tip}", "style": ui.tooltip_style()})
    (slot or st).pydeck_chart(deck, height="stretch", key=key)


def legend_groups(state: MapState, visible: set) -> list[str]:
    present = {palette.event_group((item.get("properties") or {}).get("event_type"))
               for layer in state.layers if layer.id in visible and layer.typed for item in layer.features}
    return [group for group in (*palette.EVENT_COLORS, palette.OTHER) if group in present]


def render_footer(state: MapState, visible: set, mode: str) -> None:
    with st.container(horizontal=True, vertical_alignment="center", key="map_footer"):
        if not state.layers:
            st.caption("提问后，分析结果会作为图层出现在这里")
            return
        hidden_count = sum(layer.id not in visible for layer in state.layers)
        text = f"{len(state.layers)} 个图层 · {state.feature_count} 个要素"
        if hidden_count:
            text += f"（{hidden_count} 个已隐藏）"
        st.caption(text + " · 已定位到最新结果")
        groups = legend_groups(state, visible)
        if groups:
            ui.legend([(palette.group_label(group), palette.event_color(group, mode)) for group in groups])


# ---------------------------------------------------------------- 过渡代码：旧工作台页面仍在调用，任务 7 删除
import math  # noqa: E402


@dataclass
class MapResult:
    layers: list = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    view: tuple = (15.0, 43.0, 4.5)
    points: int = 0
    features: int = 0


def prepare(paths: list[str]) -> MapResult:
    result = MapResult()
    bounds = []
    colors = [[34, 211, 238], [248, 113, 113], [251, 191, 36], [167, 139, 250]]
    for path in dict.fromkeys(paths):
        try:
            data = artifacts.load_geojson(path)
            bounds.append(artifacts.coordinate_bounds(data))
        except artifacts.ArtifactError as exc:
            result.errors.append(str(exc))
            continue
        result.paths.append(path)
        result.features += len(data["features"])
        result.points += sum(feature["geometry"]["type"] == "Point" for feature in data["features"])
        color = colors[len(result.layers) % len(colors)]
        result.layers.append(pdk.Layer(
            "GeoJsonLayer", data=data, stroked=True, filled=True, pickable=True,
            get_fill_color=color + [40], get_line_color=color + [220],
            get_line_width=3, line_width_min_pixels=3, point_radius_min_pixels=5,
        ))
    if bounds:
        left, bottom = min(b[0] for b in bounds), min(b[1] for b in bounds)
        right, top = max(b[2] for b in bounds), max(b[3] for b in bounds)
        span = max(right - left, top - bottom, .01)
        result.view = ((bottom + top) / 2, (left + right) / 2,
                       max(2., min(9., math.log2(180. / span))))
    return result


def render(slot, paths: list[str], *, last_error: str | None = None) -> MapResult:
    result = prepare(paths)
    slot.empty()
    with slot.container():
        if result.errors:
            st.warning("地图加载失败：" + "；".join(dict.fromkeys(result.errors)))
        if last_error and not result.paths:
            st.warning("本轮未生成可用地图，请查看对话中的执行失败说明。")
        lat, lon, zoom = result.view
        ui.deck(result.layers, lat, lon, zoom, tooltip="{date}{event_type}{location}", height=450)
        if result.paths:
            st.caption(f"已加载 {len(result.paths)} 个地图文件 · {result.features} 个要素 · {result.points} 个点要素")
        elif result.errors:
            st.caption("尚无可显示的分析图层；当前仅为默认底图。")
        else:
            st.caption("尚未生成分析图层；模型回答中的文件名不会自动作为地图结果。")
    return result
