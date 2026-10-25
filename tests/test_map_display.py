"""地图显示回归：真实临时产物与会话库，不调用模型或外部地理编码。"""

import json
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

from agent import artifacts, geosql, react, sessions, tools
from app import map_view


PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


@pytest.fixture
def map_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def no_model(*args, **kwargs):
        raise AssertionError("地图显示回归不得调用模型 API")

    monkeypatch.setattr(react, "_get_llm", no_model)
    monkeypatch.setattr(geosql, "_get_llm", no_model)
    return sessions


def _polygon_file():
    artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifacts.OUTPUT_DIR / "southern_buffer.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"kind": "buffer", "radius_km": 100},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-146, -18], [-144, -18], [-144, -16], [-146, -16], [-146, -18],
            ]]},
        }],
    }), encoding="utf-8")
    return str(path)


def _session(store, title, answer, paths=None):
    sid = store.create_session(title)
    seq = store.save_message(sid, "user", title)
    store.save_message(sid, "assistant", answer, geojson=paths or [], reply_to_seq=seq)
    return sid


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    return app


def _captions(app):
    return "\n".join(str(element.value) for element in app.caption)


def _deck(app):
    charts = app.get("deck_gl_json_chart")
    assert len(charts) == 1
    return json.loads(charts[0].proto.json)


def test_build_zero_event_southern_buffer_has_layer_and_correct_view():
    path = _polygon_file()
    state = map_view.build([(1, [path, path])])

    assert [file for _, file, _ in state.files] == [path]
    assert not state.errors
    assert len(state.layers) == state.feature_count == 1
    assert state.layers[0].kind == "buffer"
    assert state.view[:2] == pytest.approx((-17.003, -145.0), abs=0.01)
    assert state.view != map_view.DEFAULT_VIEW
    assert state.layers[0].features[0]["properties"]["radius_km"] == 100


@pytest.mark.parametrize("kind", ["missing", "damaged"])
def test_build_missing_or_damaged_file_reports_failure(kind):
    artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifacts.OUTPUT_DIR / f"{kind}.geojson"
    if kind == "damaged":
        path.write_text("{broken geojson", encoding="utf-8")

    state = map_view.build([(1, [str(path)])])

    assert state.errors
    assert not state.files and not state.layers
    assert state.feature_count == 0
    assert state.view == map_view.DEFAULT_VIEW


def test_page_restores_real_map_and_does_not_load_empty_reply(map_sessions):
    path = _polygon_file()
    real = _session(map_sessions, "南半球100公里缓冲区", "圈内没有事件，范围已生成。", [path])
    empty = _session(map_sessions, "尚无结果的会话", "")
    app = _open(_app(), real)

    assert "1 个图层 · 1 个要素 · 已定位到最新结果" in _captions(app)
    deck = _deck(app)
    assert len(deck["layers"]) == 1
    assert deck["initialViewState"]["latitude"] == pytest.approx(-17.003, abs=0.01)
    assert deck["initialViewState"]["longitude"] == pytest.approx(-145.0, abs=0.01)

    _open(app, empty)
    assert "个图层" not in _captions(app)
    assert "提问后，分析结果会作为图层出现在这里" in _captions(app)
    assert not _deck(app).get("layers", [])


def test_page_warns_about_missing_map_and_ignores_path_in_answer(map_sessions):
    missing_path = str(artifacts.OUTPUT_DIR / "removed.geojson")
    missing = _session(map_sessions, "打开原来的图", "已生成地图。", [missing_path])
    fabricated = _session(map_sessions, "能在图上显示吗", "可以显示。GeoJSON 已保存：/tmp/xx.geojson")
    app = _open(_app(), missing)

    assert any("地图加载失败" in warning.value for warning in app.warning)
    assert "个图层" not in _captions(app)
    assert not _deck(app).get("layers", [])

    _open(app, fabricated)
    assert "提问后，分析结果会作为图层出现在这里" in _captions(app)
    assert "个图层" not in _captions(app)
    assert not _deck(app).get("layers", [])
    assert map_sessions.load_messages(fabricated)[-1]["geojson"] == []


def test_zero_event_buffer_tool_artifact_renders_on_page(tmp_path, monkeypatch, map_sessions):
    database = tmp_path / "empty_gdelt.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE gdelt_events "
                    "(event_date DATE, event_code VARCHAR, country VARCHAR, lat DOUBLE, lon DOUBLE)")
    monkeypatch.setattr(tools.db, "connect", lambda: duckdb.connect(str(database), read_only=True))

    output = tools.buffer_analysis.invoke({
        "lat": -17.6797, "lon": -149.4068, "radius_km": 100, "table": "gdelt_events",
    })
    assert "圈内共 0 条记录" in output
    path = artifacts.validated_path(artifacts.extract_tool_path(output))
    state = map_view.build([(1, [path])])
    assert state.feature_count == 1 and [layer.kind for layer in state.layers] == ["buffer"]
    assert not state.errors
    sid = _session(map_sessions, "显示100公里内的 GDELT 事件", output, [path])
    app = _open(_app(), sid)

    assert "1 个图层 · 1 个要素 · 已定位到最新结果" in _captions(app)
    deck = _deck(app)
    assert len(deck["layers"]) == 1
    assert deck["layers"][0]["data"]["features"][0]["geometry"]["type"] == "Polygon"
    assert deck["initialViewState"]["latitude"] == pytest.approx(-17.682, abs=0.01)
    assert deck["initialViewState"]["longitude"] == pytest.approx(-149.4068, abs=0.01)
