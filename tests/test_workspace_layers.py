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


EXPLOSION = _feature("Point", [43.3, 12.6], event_type="Explosions/Remote violence")
# GDELT 的 event_type 是事件编码（buffer_analysis 把 event_code 起别名成 event_type），
# 仍然算事件点，但取不到 ACLED 的类型色 —— 地图画空心环。
GDELT_POINT = _feature("Point", [43.4, 12.7], event_type="190", date="2023-12-15", location="Yemen")


def _chips_page(message, mode, turn):
    from app import chat_ui

    chat_ui.render_message(message, mode, turn=turn)


def _chips(app):
    return next(str(item.value) for item in app.markdown if "gs-results" in str(item.value))


def test_result_chip_colour_follows_the_event_type_on_the_map(geojson):
    # 地图按事件类型上色；标签不能一律画成"武装冲突"的粉色
    message = {"role": "assistant", "content": "已统计。", "geojson": [geojson("explosions", [EXPLOSION])]}
    app = AppTest.from_function(_chips_page, args=(message, "light", 1), default_timeout=20).run()

    assert not app.exception
    assert "background:#EA580C" in _chips(app)


def test_result_chip_for_non_acled_events_is_an_outlined_ring(geojson):
    message = {"role": "assistant", "content": "已查询。", "geojson": [geojson("gdelt", [GDELT_POINT])]}
    app = AppTest.from_function(_chips_page, args=(message, "light", 1), default_timeout=20).run()

    assert not app.exception
    chips = _chips(app)
    assert 'class="ring"' in chips
    # fixture 一旦丢掉 event_type 就会被拆成 points（"查询结果 · 1 点"），那时这条断言会拦下来
    assert "查询结果" not in chips


def test_chips_with_the_same_name_in_one_answer_are_numbered(store, geojson):
    # 一次回答做两个缓冲区：图层按钮按"同轮重名"规则编号，结果标签照抄同样的名字
    first, second = geojson("north", [BUFFER]), geojson("south", [BUFFER])
    sid = _session(store, [[first, second]])
    app = _open(_app(), sid)

    options = app.pills[0].options
    assert len(set(options)) == 2  # 两个按钮不能重名
    chips = next(str(item.value) for item in app.chat_message[1].markdown if "gs-results" in str(item.value))
    assert all(option in chips for option in options)


def test_result_chips_use_the_same_names_as_the_layer_buttons(store, geojson):
    # 两轮都生成"缓冲区 150 km"：图层按钮会加"第 N 轮"，回答下的标签必须一字不差
    first, second = geojson("north", [BUFFER]), geojson("south", [BUFFER])
    sid = _session(store, [[first], [second]])
    app = _open(_app(), sid)

    assert app.pills[0].options == ["缓冲区 150 km · 第 1 轮", "缓冲区 150 km · 第 2 轮"]
    chips = [str(item.value) for item in app.chat_message[1].markdown if "gs-results" in str(item.value)]
    assert len(chips) == 1
    assert "缓冲区 150 km · 第 1 轮" in chips[0]


def test_a_reused_file_is_not_mislabelled_on_the_earlier_answer(store, geojson):
    # 追问"把刚才的图显示出来"会原样复用上一轮的文件：图层只属于最后一轮，
    # 第 1 轮回答下面不能写上"第 2 轮"的按钮名。
    shared = geojson("shared", [BUFFER])
    sid = _session(store, [[shared], [shared]])
    app = _open(_app(), sid)

    assert app.pills[0].options == ["缓冲区 150 km"]  # 同一个文件只出一个图层，没有重名可加编号
    chips = [str(item.value) for item in app.chat_message[1].markdown if "gs-results" in str(item.value)]
    assert len(chips) == 1
    assert "第" not in chips[0]


def test_a_crash_after_a_tool_produced_a_map_keeps_that_map(store, geojson, monkeypatch):
    # 工具成功、地图已经画出来之后流才断：本轮产物属于这一轮，不能让图层随异常一起消失
    produced = geojson("partial", [BUFFER])

    def crashing_stream(prompt, history=None, session_id=None):
        yield {"type": "thinking", "step": 1}
        yield {"type": "tool_start", "name": "buffer_analysis",
               "args": {"lat": 12.6, "lon": 43.3, "radius_km": 150}, "step": 1, "blocked": False}
        yield {"type": "tool_end", "name": "buffer_analysis", "output": "GeoJSON 已保存：" + produced,
               "blocked": False, "geojson_path": produced}
        raise RuntimeError("模拟连接中断")

    monkeypatch.setattr(react, "stream", crashing_stream)
    app = _app()
    app.chat_input(key="geoagent_prompt").set_value("曼德海峡周边150公里内的事件").run()
    app.run()
    assert not app.exception
    stored = store.load_messages(app.session_state["current_session_id"])
    assert stored[-1]["geojson"] == [produced]
    assert stored[-1]["error"].startswith("分析中断")
    assert app.pills[0].value == [f"{produced}#buffer"]
    assert "本轮未生成可用地图" not in _captions(app)
    assert "1 个图层 · 1 个要素" in _captions(app)
