"""工作台图层的页面回归：多轮累积、开关不重置视野、隐藏状态按会话隔离（AppTest，不调用模型）。"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import artifacts, react, sessions

PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


def _feature(shape, coordinates, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": shape, "coordinates": coordinates}}


BUFFER = _feature("Polygon", [[[42.3, 11.6], [44.3, 11.6], [44.3, 13.6], [42.3, 13.6], [42.3, 11.6]]],
                  kind="buffer", radius_km=150)
EVENT = _feature("Point", [43.3, 12.6], event_type="Battles", date="2023-12-15", location="Bab el Mandeb")
TRACK = _feature("LineString", [[38.0, 20.0], [39.0, 19.0], [40.0, 18.0]], mmsi=668116204,
                 points_shown=3, points_total=120)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def no_model(*args, **kwargs):
        raise AssertionError("图层回归不得调用模型 API")

    monkeypatch.setattr(react, "_get_llm", no_model)
    return sessions


@pytest.fixture
def geojson():
    """在受控产物目录里写 GeoJSON（tests/conftest.py 已把该目录隔离到每个测试的临时目录）。"""
    def write(name, features):
        artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = artifacts.OUTPUT_DIR / f"{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        return str(path)

    return write


def _session(store, turns):
    """turns: 每轮回答保存的地图文件列表。"""
    sid = store.create_session("图层测试")
    for index, paths in enumerate(turns, 1):
        seq = store.save_message(sid, "user", f"第{index}轮问题")
        store.save_message(sid, "assistant", f"第{index}轮回答", geojson=paths, reply_to_seq=seq)
    return sid


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    return app


def _deck(app):
    charts = app.get("deck_gl_json_chart")
    assert len(charts) == 1
    return json.loads(charts[0].proto.json)


def _captions(app):
    return "\n".join(str(element.value) for element in app.caption)


def _markdown(app):
    return "\n".join(str(element.value) for element in app.markdown)


def test_two_turns_accumulate_and_view_follows_latest_turn(store, geojson):
    track = geojson("track", [TRACK])
    events = geojson("events", [BUFFER, EVENT])
    sid = _session(store, [[track], [events]])
    app = _open(_app(), sid)

    assert app.pills[0].value == [f"{track}#track", f"{events}#buffer", f"{events}#events"]
    assert "3 个图层 · 3 个要素 · 已定位到最新结果" in _captions(app)
    view = _deck(app)["initialViewState"]
    assert (view["latitude"], view["longitude"]) == pytest.approx((12.602, 43.3), abs=0.01)


def test_hiding_a_layer_drops_it_but_keeps_the_view(store, geojson):
    track = geojson("track", [TRACK])
    events = geojson("events", [BUFFER, EVENT])
    sid = _session(store, [[track], [events]])
    app = _open(_app(), sid)
    before = _deck(app)
    assert "武装冲突" in _markdown(app)  # 底栏图例

    app.pills[0].unselect(f"{events}#events").run()
    assert not app.exception
    after = _deck(app)
    assert len(after["layers"]) == len(before["layers"]) - 1
    assert after["initialViewState"] == before["initialViewState"]
    assert "3 个图层 · 3 个要素（1 个已隐藏）" in _captions(app)
    assert "武装冲突" not in _markdown(app)
    assert app.session_state["hidden_layers"][sid] == {f"{events}#events"}


def test_hidden_layers_are_kept_per_session(store, geojson):
    first_file, second_file = geojson("a", [BUFFER]), geojson("b", [BUFFER])
    first, second = _session(store, [[first_file]]), _session(store, [[second_file]])
    app = _open(_app(), first)
    app.pills[0].unselect(f"{first_file}#buffer").run()
    assert app.pills[0].value == []
    assert not _deck(app).get("layers")

    _open(app, second)
    assert app.pills[0].value == [f"{second_file}#buffer"]
    _open(app, first)
    assert app.pills[0].value == []


def test_new_layers_show_by_default_while_hidden_ones_stay_hidden(store, geojson):
    old = geojson("old", [BUFFER])
    sid = _session(store, [[old]])
    app = _open(_app(), sid)
    app.pills[0].unselect(f"{old}#buffer").run()

    new = geojson("new", [EVENT])
    seq = store.save_message(sid, "user", "第2轮问题")
    store.save_message(sid, "assistant", "第2轮回答", geojson=[new], reply_to_seq=seq)
    _open(app, sid)
    assert app.pills[0].value == [f"{new}#events"]
    assert "2 个图层 · 2 个要素（1 个已隐藏）" in _captions(app)
