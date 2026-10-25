"""地图产物的统一读取与校验，避免把文字中的路径当作可用图层。"""

import json
import math
from pathlib import Path

from . import config


OUTPUT_DIR = config.ROOT / "data" / "agent_output"
MAX_FILE_BYTES = 20 * 1024 * 1024


class ArtifactError(ValueError):
    """产物不可读取或不是可渲染的 GeoJSON。"""


def _resolve_path(path: str) -> Path:
    try:
        candidate = Path(path).resolve()
        candidate.relative_to(OUTPUT_DIR.resolve())
    except (TypeError, ValueError, OSError, RuntimeError) as exc:
        raise ArtifactError("地图文件必须位于本项目的 data/agent_output 目录内。") from exc
    if candidate.suffix.lower() != ".geojson":
        raise ArtifactError("地图文件必须使用 .geojson 扩展名。")
    if not candidate.is_file():
        raise ArtifactError("地图文件不存在，请重新运行空间分析生成图层。")
    return candidate


def _finite_number(value):
    try:
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ArtifactError("GeoJSON 坐标必须是有限数值。")
    return value


def _position(value):
    if not isinstance(value, list) or len(value) not in (2, 3):
        raise ArtifactError("GeoJSON 坐标必须包含经度、纬度和可选的高度。")
    numbers = [_finite_number(item) for item in value]
    if not -180 <= numbers[0] <= 180 or not -90 <= numbers[1] <= 90:
        raise ArtifactError("GeoJSON 经纬度超出合法范围。")
    return numbers[0], numbers[1]


def _array(value, minimum=1):
    if not isinstance(value, list) or len(value) < minimum:
        raise ArtifactError("GeoJSON 几何坐标为空或点数不足。")
    return value


def _geometry_positions(geometry):
    if not isinstance(geometry, dict):
        raise ArtifactError("GeoJSON 缺少有效几何。")
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if kind == "Point":
        yield _position(coordinates)
    elif kind in ("MultiPoint", "LineString"):
        for position in _array(coordinates, 2 if kind == "LineString" else 1):
            yield _position(position)
    elif kind == "Polygon":
        for ring in _array(coordinates):
            positions = [_position(item) for item in _array(ring, 4)]
            if ring[0] != ring[-1]:
                raise ArtifactError("GeoJSON 多边形的环必须闭合。")
            yield from positions
    elif kind in ("MultiLineString", "MultiPolygon"):
        child_kind = "LineString" if kind == "MultiLineString" else "Polygon"
        for child in _array(coordinates):
            yield from _geometry_positions({"type": child_kind, "coordinates": child})
    elif kind == "GeometryCollection":
        for child in _array(geometry.get("geometries")):
            yield from _geometry_positions(child)
    else:
        raise ArtifactError(f"不支持的 GeoJSON 几何类型：{kind}。")


def coordinate_bounds(data: dict) -> tuple[float, float, float, float]:
    """严格遍历所有 Feature，返回 (最小经度、最小纬度、最大经度、最大纬度)。"""
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ArtifactError("地图文件必须是 GeoJSON FeatureCollection。")
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise ArtifactError("地图结果为空，没有可显示的几何图层。")
    bounds = [math.inf, math.inf, -math.inf, -math.inf]
    try:
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                raise ArtifactError("GeoJSON 包含无效 Feature。")
            for lon, lat in _geometry_positions(feature.get("geometry")):
                bounds = [min(bounds[0], lon), min(bounds[1], lat), max(bounds[2], lon), max(bounds[3], lat)]
    except RecursionError as exc:
        raise ArtifactError("GeoJSON 几何嵌套层级过深。") from exc
    return tuple(bounds)


def _check_properties(data: dict) -> None:
    """属性必须是对象且只含简单值：界面和提示会直接展示这些值，不做嵌套解析。"""
    for feature in data["features"]:
        properties = feature.get("properties")
        if properties is not None and not isinstance(properties, dict):
            raise ArtifactError("GeoJSON 的属性必须是对象。")
        for value in (properties or {}).values():
            if isinstance(value, (dict, list)):
                raise ArtifactError("GeoJSON 的属性值必须是简单值。")
            if isinstance(value, int) and not isinstance(value, bool):
                try:
                    float(value)
                except OverflowError:
                    raise ArtifactError("GeoJSON 的属性数值超出范围。") from None


def _parse_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ArtifactError("GeoJSON 不能包含 NaN 或 Infinity。")
    return number


def _reject_constant(value):
    raise ArtifactError("GeoJSON 不能包含 NaN 或 Infinity。")


def load_geojson(path: str) -> dict:
    """仅从受控产物目录读取大小受限、完整合法的 GeoJSON。"""
    candidate = _resolve_path(path)
    try:
        if candidate.stat().st_size > MAX_FILE_BYTES:
            raise ArtifactError("地图文件超过 20 MB，无法加载。")
        with candidate.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ArtifactError("地图文件超过 20 MB，无法加载。")
        data = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant, parse_float=_parse_float)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ArtifactError("地图文件无法读取或内容损坏，请重新生成图层。") from exc
    coordinate_bounds(data)
    _check_properties(data)
    return data


def validated_path(path: str) -> str:
    """返回经过完整内容校验的规范化绝对路径。"""
    load_geojson(path)
    return str(_resolve_path(path))


def extract_tool_path(output: str) -> str | None:
    """只用于可信工具返回值；助手回答不能作为地图产物来源。"""
    if not isinstance(output, str) or "GeoJSON 已保存：" not in output:
        return None
    suffix = output.rsplit("GeoJSON 已保存：", 1)[1]
    path = suffix.splitlines()[0].strip() if suffix else ""
    return path.strip("`\"'") or None
