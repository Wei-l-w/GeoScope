"""工作台地图图层的单元测试：拆分、命名、配色归并、视野与复位（设计文档第 7 节）。"""

import json
from pathlib import Path

import pytest

from agent import artifacts
from app import map_view, palette


def _feature(shape, coordinates, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": shape, "coordinates": coordinates}}


def _square(lon, lat, half):
    return [[[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half],
             [lon - half, lat + half], [lon - half, lat - half]]]


def _event(event_type, lon=43.3, lat=12.6):
    return _feature("Point", [lon, lat], event_type=event_type, date="2023-12-15",
                    location="Strait of Bab el Mandeb", dist_km=37)


BUFFER = _feature("Polygon", _square(43.3, 12.6, 1.0), kind="buffer", radius_km=150)
TRACK = _feature("LineString", [[38.0, 20.0], [39.0, 19.0], [40.0, 18.0]],
                 mmsi=668116204, points_shown=3, points_total=120)
QUERY_POINT = _feature("Point", [42.0, 15.0], name="Hodeidah", country="Yemen", port=True, berths=12)
ACLED_TYPES = ["Battles", "Explosions/Remote violence", "Strategic developments",
               "Protests", "Riots", "Violence against civilians"]


@pytest.fixture
def geojson():
    """在受控产物目录里写 GeoJSON（tests/conftest.py 已把该目录隔离到每个测试的临时目录）。"""
    def write(name, features):
        artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = artifacts.OUTPUT_DIR / f"{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        return str(path)

    return write


def _all(state):
    return {layer.id for layer in state.layers}


def test_turns_number_assistant_replies_and_skip_replies_without_maps():
    messages = [{"role": "user"}, {"role": "assistant", "geojson": []},
                {"role": "user"}, {"role": "assistant", "geojson": ["a.geojson", "a.geojson"]}]
    assert map_view.turns(messages) == [(2, ["a.geojson"])]


def test_one_file_splits_into_named_layers_in_drawing_order(geojson):
    path = geojson("mixed", [QUERY_POINT, _event("Battles"), _event("Protests"), TRACK, BUFFER])
    state = map_view.build([(1, [path])])

    assert [(layer.kind, layer.label) for layer in state.layers] == [
        ("buffer", "缓冲区 150 km"), ("track", "航迹 · 668116204"),
        ("events", "事件点 · 2"), ("points", "查询结果 · 1 点"),
    ]
    assert [layer.id for layer in state.layers] == [f"{path}#{kind}" for kind in ("buffer", "track", "events", "points")]
    assert state.files == [(1, path, "缓冲区 150 km、航迹 · 668116204、事件点 · 2、查询结果 · 1 点")]
    assert state.feature_count == 5


def test_point_rows_with_an_mmsi_column_are_query_results_not_tracks(geojson):
    # query_database 把 mmsi 列也写成属性，逐行一个 Point；只看 mmsi 会把它当成航迹，每点一个图层
    rows = [_feature("Point", [43.0 + 0.01 * index, 12.0], mmsi="600000000", speed="12.4")
            for index in range(3)]
    state = map_view.build([(1, [geojson("ais", rows)])])

    assert [(layer.kind, layer.label) for layer in state.layers] == [("points", "查询结果 · 3 点")]
    assert [layer.type for layer in map_view.deck_layers(state.layers, _all(state), "light")] == ["ScatterplotLayer"]


def test_point_rows_are_not_tracks_just_because_a_column_is_named_points_total(geojson):
    # SQL 别名同样会变成属性；ship_track 的单点输出同时带 points_total 与 points_shown
    rows = [_feature("Point", [43.0, 12.0], mmsi="600000000", points_total="500")]
    state = map_view.build([(1, [geojson("alias", rows)])])
    assert [layer.kind for layer in state.layers] == ["points"]


def test_polygons_with_an_mmsi_property_are_not_tracks(geojson):
    # 回归：查出带 mmsi 的船舶区域面时，曾按航迹渲染并 IndexError
    area = _feature("Polygon", _square(43.3, 12.6, 1.0), mmsi=668116204, points_total=3, points_shown=3)
    state = map_view.build([(1, [geojson("ship_area", [area])])])
    assert [layer.kind for layer in state.layers] == ["other"]
    assert [layer.type for layer in map_view.deck_layers(state.layers, _all(state), "light")] == ["GeoJsonLayer"]


def test_single_point_track_stays_a_track(geojson):
    one = _feature("Point", [40.0, 18.0], mmsi=1, points_total=1, points_shown=1)
    state = map_view.build([(1, [geojson("track_one", [one])])])
    assert [(layer.kind, layer.label) for layer in state.layers] == [("track", "航迹 · 1")]


def test_tooltips_are_prepared_in_chinese(geojson):
    path = geojson("tips", [BUFFER, TRACK, _event("Explosions/Remote violence"), QUERY_POINT])
    state = map_view.build([(1, [path])])
    buffer, glow, line, end, events, ring = map_view.deck_layers(state.layers, _all(state), "light")

    assert buffer.data["features"][0]["properties"]["tip"] == "缓冲区 · 半径 150 km"
    assert line.data[0]["tip"] == end.data[0]["tip"] == "MMSI 668116204 · 展示 3 / 共 120 点"
    assert events.data[0]["tip"] == "2023-12-15 · 爆炸/远程暴力 · Strait of Bab el Mandeb · 距中心 37 km"
    assert ring.data[0]["tip"] == "name: Hodeidah · country: Yemen · port: True"


def test_zero_event_buffer_has_only_the_circle_layer(geojson):
    state = map_view.build([(1, [geojson("empty_buffer", [BUFFER])])])
    assert [layer.kind for layer in state.layers] == ["buffer"]


def test_same_names_get_turn_suffix(geojson):
    first, second = geojson("buffer_a", [BUFFER]), geojson("buffer_b", [BUFFER])
    state = map_view.build([(1, [first]), (3, [second])])
    assert [layer.label for layer in state.layers] == ["缓冲区 150 km · 第 1 轮", "缓冲区 150 km · 第 3 轮"]


def test_same_turn_layers_with_the_same_name_are_numbered(geojson):
    first, second = geojson("buffer_a", [BUFFER]), geojson("buffer_b", [BUFFER])
    state = map_view.build([(1, [first, second])])
    assert [layer.label for layer in state.layers] == ["缓冲区 150 km · 第 1 轮 · 1", "缓冲区 150 km · 第 1 轮 · 2"]


def test_file_repeated_in_later_turn_belongs_to_that_turn(geojson):
    path = geojson("repeated", [BUFFER])
    state = map_view.build([(1, [path]), (2, [path])])
    assert [(layer.turn, layer.label) for layer in state.layers] == [(2, "缓冲区 150 km")]
    assert [turn for turn, _, _ in state.files] == [2]


@pytest.mark.parametrize("mode", palette.MODES)
def test_acled_events_use_three_colors_plus_smaller_gray_other(geojson, mode):
    path = geojson("acled", [_event(event_type) for event_type in ACLED_TYPES])
    state = map_view.build([(1, [path])])
    assert state.layers[0].typed

    other, typed = map_view.deck_layers(state.layers, _all(state), mode)
    assert [row["color"] for row in typed.data] == [palette.rgb(color) for color in palette.EVENT_COLORS.values()]
    assert [row["color"] for row in other.data] == [palette.rgb(palette.OTHER_GRAY[mode])] * 3
    assert other.radius_min_pixels < typed.radius_min_pixels
    assert typed.get_line_color == palette.rgb(palette.MAP[mode]["stroke"])
    assert map_view.legend_groups(state, _all(state)) == [*palette.EVENT_COLORS, palette.OTHER]
    assert map_view.legend_groups(state, set()) == []


@pytest.mark.parametrize("mode", palette.MODES)
def test_gdelt_events_and_query_points_use_neutral_rings(geojson, mode):
    path = geojson("gdelt", [_event("190"), _event("Battles"), QUERY_POINT])
    state = map_view.build([(1, [path])])
    assert [(layer.kind, layer.typed) for layer in state.layers] == [("events", False), ("points", False)]

    rings = map_view.deck_layers(state.layers, _all(state), mode)
    assert len(rings) == 2
    for ring in rings:
        assert ring.type == "ScatterplotLayer" and ring.filled is False and ring.stroked is True
        assert ring.get_line_color == palette.rgb(palette.MAP[mode]["ring"])
    assert map_view.legend_groups(state, _all(state)) == []


def test_hidden_layers_are_not_drawn(geojson):
    path = geojson("hide", [BUFFER, _event("Battles")])
    state = map_view.build([(1, [path])])
    assert [layer.type for layer in map_view.deck_layers(state.layers, {f"{path}#buffer"}, "light")] == ["GeoJsonLayer"]


def test_view_fits_latest_turn_in_web_mercator(geojson):
    far = geojson("far", [_feature("Point", [-149.4, -17.7], name="Tahiti")])
    near = geojson("near", [_feature("Polygon", _square(40.0, 20.0, 10.0), kind="buffer", radius_km=1000)])
    state = map_view.build([(1, [far]), (2, [near])])
    # 10°N–30°N 在墨卡托下比按度数算更"高"：缩放 3.80，按度数线性算会得到 3.90
    # 中心取墨卡托中点（任务 4 的质量复查修正）：算术中点 20.0 会让上下边距不等
    assert state.view == (20.322, 40.0, 3.8)


def test_view_follows_the_shortest_arc_across_the_antimeridian(geojson):
    # -179° 与 179.5° 相距 1.5°；简单取最小/最大会得到覆盖 358.5° 的"全球"视野
    path = geojson("dateline", [_feature("Point", [-179.0, -17.0]), _feature("Point", [179.5, -17.0])])
    assert map_view.build([(1, [path])]).view == (-17.0, -179.75, 8.0)


def test_worldwide_points_still_fit_the_whole_map(geojson):
    path = geojson("world", [_feature("Point", [-170.0, 0.0]), _feature("Point", [0.0, 0.0]),
                             _feature("Point", [170.0, 0.0])])
    assert map_view.build([(1, [path])]).view == (0.0, 0.0, 2.0)


def test_without_layers_the_map_shows_the_red_sea():
    state = map_view.build([])
    assert state.view == map_view.DEFAULT_VIEW == (15.0, 43.0, 4.5)
    assert map_view.view_state(state).latitude == 15.0


def test_reset_nudges_every_view_field(geojson):
    path = geojson("reset", [BUFFER])
    base = map_view.view_state(map_view.build([(1, [path])]))
    moved = map_view.view_state(map_view.build([(1, [path])], reset=2))

    assert (base.pitch, base.bearing) == (0, 0)
    for name in ("latitude", "longitude", "zoom", "pitch", "bearing"):
        assert getattr(moved, name) == pytest.approx(getattr(base, name) + 2e-7, abs=1e-12)


def test_download_list_skips_files_that_have_since_been_deleted(geojson, tmp_path):
    from streamlit.testing.v1 import AppTest

    gone = geojson("gone", [BUFFER])
    page = tmp_path / "page.py"
    page.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
        "from pathlib import Path\n"
        "import streamlit as st\n"
        "from app import map_view\n"
        f"state = map_view.build([(1, [{gone!r}])])\n"
        "Path(" + f"{gone!r}" + ").unlink()\n"
        "map_view.render_bar(state, 'sid', False)\n",
        encoding="utf-8",
    )
    app = AppTest.from_file(str(page), default_timeout=20).run()
    assert not app.exception
    assert not app.get("download_button")
    assert "文件已不可用" in " ".join(caption.value for caption in app.caption)
