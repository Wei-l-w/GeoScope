"""地图产物边界与几何回归，不依赖模型、真实数据库或会话。"""

import json

import pytest

from agent import artifacts


@pytest.fixture
def artifact_dir(tmp_path, monkeypatch):
    directory = tmp_path / "outputs"
    directory.mkdir()
    monkeypatch.setattr(artifacts, "OUTPUT_DIR", directory)
    return directory


def collection(geometry, properties=None):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": geometry, "properties": properties or {}}
    ]}


def save(directory, data, name="result.geojson"):
    path = directory / name
    path.write_text(json.dumps(data), encoding="utf-8-sig")
    return str(path)


RING = [[-150, -20], [-149, -20], [-149, -19], [-150, -20]]


@pytest.mark.parametrize("geometry,expected", [
    ({"type": "Point", "coordinates": [-149.4068, -17.6797, 123]}, (-149.4068, -17.6797, -149.4068, -17.6797)),
    ({"type": "MultiPoint", "coordinates": [[-180, -90], [180, 90]]}, (-180, -90, 180, 90)),
    ({"type": "LineString", "coordinates": [[-0.001, -2e-5], [0.002, 3e-5]]}, (-0.001, -2e-5, 0.002, 3e-5)),
    ({"type": "Polygon", "coordinates": [RING]}, (-150, -20, -149, -19)),
    ({"type": "MultiLineString", "coordinates": [[[1, 2], [3, 4]], [[-5, -6], [-7, -8]]]}, (-7, -8, 3, 4)),
    ({"type": "MultiPolygon", "coordinates": [[RING]]}, (-150, -20, -149, -19)),
    ({"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [10, 20]}, {"type": "Polygon", "coordinates": [RING]}]}, (-150, -20, 10, 20)),
])
def test_supported_geometries_and_real_bounds(artifact_dir, geometry, expected):
    data = collection(geometry, {"irrelevant_text": "coordinates: [180, 90]"})
    path = save(artifact_dir, data)
    assert artifacts.load_geojson(path) == data
    assert artifacts.coordinate_bounds(data) == expected
    assert artifacts.validated_path(path) == str((artifact_dir / "result.geojson").resolve())


def test_zero_events_with_buffer_is_displayable(artifact_dir):
    data = collection({"type": "Polygon", "coordinates": [RING]}, {"event_count": 0, "kind": "buffer"})
    assert artifacts.load_geojson(save(artifact_dir, data)) == data


@pytest.mark.parametrize("data", [
    {}, {"type": "Point", "coordinates": [1, 2]},
    {"type": "FeatureCollection", "features": []},
    {"type": "FeatureCollection", "features": "invalid"},
    {"type": "FeatureCollection", "features": [None]},
    collection(None),
    collection({"type": "Point", "coordinates": [181, 20]}),
    collection({"type": "Point", "coordinates": [20, -91]}),
    collection({"type": "Point", "coordinates": [True, 20]}),
    collection({"type": "Point", "coordinates": ["1", 20]}),
    collection({"type": "Point", "coordinates": [1]}),
    collection({"type": "Point", "coordinates": [1, 2, 3, 4]}),
    collection({"type": "LineString", "coordinates": [[1, 2]]}),
    collection({"type": "Polygon", "coordinates": [[[1, 2], [3, 4], [5, 6], [7, 8]]]}),
    collection({"type": "Polygon", "coordinates": [[[1, 2], [3, 4], [1, 2]]]}),
    collection({"type": "GeometryCollection", "geometries": []}),
    collection({"type": "Unsupported", "coordinates": [1, 2]}),
])
def test_invalid_geometry_rejects_entire_file(artifact_dir, data):
    with pytest.raises(artifacts.ArtifactError):
        artifacts.load_geojson(save(artifact_dir, data))


def test_one_invalid_feature_does_not_silently_disappear(artifact_dir):
    data = collection({"type": "Point", "coordinates": [1, 2]})
    data["features"].extend(collection({"type": "Point", "coordinates": [200, 20]})["features"])
    with pytest.raises(artifacts.ArtifactError, match="超出"):
        artifacts.load_geojson(save(artifact_dir, data))


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_json_even_in_properties_is_rejected(artifact_dir, literal):
    path = artifact_dir / "nonfinite.geojson"
    path.write_text('{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[1,2]},"properties":{"value":' + literal + '}}]}', encoding="utf-8")
    with pytest.raises(artifacts.ArtifactError, match="NaN|Infinity"):
        artifacts.load_geojson(str(path))


@pytest.mark.parametrize("properties", [[1], "x", {"event_type": ["Battles"]}, {"radius_km": 10 ** 400}])
def test_properties_must_be_an_object_of_simple_values(artifact_dir, properties):
    with pytest.raises(artifacts.ArtifactError, match="属性"):
        artifacts.load_geojson(save(artifact_dir, collection({"type": "Point", "coordinates": [1, 2]}, properties)))


@pytest.mark.parametrize("position", [[float("nan"), 0], [0, float("inf")], [1, 2, float("-inf")]])
def test_bounds_also_reject_nonfinite_coordinates(position):
    with pytest.raises(artifacts.ArtifactError, match="有限数值"):
        artifacts.coordinate_bounds(collection({"type": "Point", "coordinates": position}))


def test_outside_missing_wrong_extension_and_damage(artifact_dir):
    valid = collection({"type": "Point", "coordinates": [1, 2]})
    outside = save(artifact_dir.parent, valid)
    with pytest.raises(artifacts.ArtifactError, match="目录内"):
        artifacts.load_geojson(outside)
    with pytest.raises(artifacts.ArtifactError, match="不存在"):
        artifacts.load_geojson(str(artifact_dir / "missing.geojson"))
    with pytest.raises(artifacts.ArtifactError, match="扩展名"):
        artifacts.load_geojson(save(artifact_dir, valid, "bad.json"))
    path = artifact_dir / "corrupt.geojson"
    for payload in [b"{broken", b"\xff\xfe"]:
        path.write_bytes(payload)
        with pytest.raises(artifacts.ArtifactError, match="损坏"):
            artifacts.load_geojson(str(path))


def test_path_traversal_is_rejected(artifact_dir):
    save(artifact_dir.parent, collection({"type": "Point", "coordinates": [1, 2]}))
    with pytest.raises(artifacts.ArtifactError, match="目录内"):
        artifacts.load_geojson(str(artifact_dir / ".." / "result.geojson"))


def test_oversized_file_is_rejected(artifact_dir, monkeypatch):
    monkeypatch.setattr(artifacts, "MAX_FILE_BYTES", 10)
    path = save(artifact_dir, collection({"type": "Point", "coordinates": [1, 2]}))
    with pytest.raises(artifacts.ArtifactError, match="20 MB"):
        artifacts.load_geojson(path)


def test_extract_requires_tool_marker_and_keeps_spaces():
    assert artifacts.extract_tool_path("范围内 7 起事件。GeoJSON 已保存：G:/project name/out.geojson\n结束") == "G:/project name/out.geojson"
    assert artifacts.extract_tool_path("GeoJSON 已保存：`G:/project/out.geojson`") == "G:/project/out.geojson"
    assert artifacts.extract_tool_path("GeoJSON 已保存：") is None
    assert artifacts.extract_tool_path("/tmp/fabricated.geojson") is None
    assert artifacts.extract_tool_path("GeoJSON 文件路径：/tmp/fabricated.geojson") is None
