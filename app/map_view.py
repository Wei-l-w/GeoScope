"""只渲染已验证的本地地图文件，显式报告缺失/损坏与空结果。"""

from dataclasses import dataclass, field
import math

import pydeck as pdk
import streamlit as st

from agent import artifacts
from app import ui


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
