"""工作台会话交互回归：一键打开、当前会话样式、中断标注与重新填入、删除、分析中禁用控件。"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import artifacts, react, sessions

PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def forbidden(*args, **kwargs):
        raise AssertionError("会话交互回归不得调用模型或运行分析")

    monkeypatch.setattr(react, "_get_llm", forbidden)
    monkeypatch.setattr(react, "stream", forbidden)
    return sessions


def _chat(store, title):
    sid = store.create_session(title)
    seq = store.save_message(sid, "user", f"{title}的问题")
    store.save_message(sid, "assistant", f"{title}的回答", reply_to_seq=seq)
    return sid


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    return app


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _session_buttons(app):
    return [button for button in app.sidebar.button if (button.key or "").startswith("session_")]


def _captions(app):
    return "\n".join(str(element.value) for element in app.caption)


def test_one_click_opens_a_session_and_marks_it_current(store):
    first, second = _chat(store, "第一个会话"), _chat(store, "第二个会话")
    app = _app()
    assert app.session_state["current_session_id"] is None
    assert {button.proto.type for button in _session_buttons(app)} == {"tertiary"}

    _open(app, second)
    assert app.session_state["current_session_id"] == second
    assert len(app.chat_message) == 2
    assert app.button(key=f"session_{second}").proto.type == "secondary"
    assert app.button(key=f"session_{first}").proto.type == "tertiary"
    assert app.button(key=f"session_{second}").label == "第二个会话"


def test_interrupted_question_is_marked_and_refill_only_fills_the_input(store):
    sid = _chat(store, "中断会话")
    lost = store.save_message(sid, "user", "曼德海峡周边80公里有哪些事件？")
    app = _open(_app(), sid)
    assert _captions(app).count("分析被中断，没有生成回答") == 1

    app.button(key=f"refill_{lost}").click().run()
    assert not app.exception
    assert app.chat_input(key="geoagent_prompt").value == "曼德海峡周边80公里有哪些事件？"
    assert len(store.load_messages(sid)) == 3  # 只填入，不发送


def test_legacy_reply_without_link_is_not_marked_interrupted(store):
    sid = store.create_session("旧会话")
    store.save_message(sid, "user", "旧问题")
    store.save_message(sid, "assistant", "旧回答")  # 改版前的数据没有 reply_to_seq
    app = _open(_app(), sid)
    assert "分析被中断" not in _captions(app)


def test_delete_from_header_menu_removes_only_the_current_session(store):
    keep, drop = _chat(store, "保留"), _chat(store, "删除")
    app = _open(_app(), drop)
    app.button(key="delete_session").click().run()

    assert not app.exception
    assert [row[0] for row in store.list_sessions()] == [keep]
    assert app.session_state["current_session_id"] is None
    assert not app.chat_message
    assert [button.key for button in _session_buttons(app)] == [f"session_{keep}"]


def test_header_menu_is_disabled_without_a_session(store):
    app = _app()
    menu = next(block for block in app.get("popover") if block.proto.popover.icon == ":material/more_horiz:")
    assert menu.proto.popover.disabled


def _busy_page(sid, path):
    import streamlit as st

    from app import chat_ui, map_view, sessions_ui

    st.session_state.current_session_id = sid
    sessions_ui.render(busy=True)
    chat_ui.header("标题", "分析中…", sid, busy=True)
    chat_ui.welcome(busy=True)
    chat_ui.render_message({"role": "user", "content": "旧问题", "seq": 7}, "light", interrupted=True, busy=True)
    map_view.render_bar(map_view.build([(1, [path])]), sid, busy=True)


def test_every_control_is_disabled_while_an_analysis_runs(store):
    sid = _chat(store, "进行中")
    artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifacts.OUTPUT_DIR / "busy.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"kind": "buffer", "radius_km": 50},
        "geometry": {"type": "Polygon", "coordinates": [[[43, 12], [44, 12], [44, 13], [43, 13], [43, 12]]]},
    }]}), encoding="utf-8")
    app = AppTest.from_function(_busy_page, args=(sid, str(path)), default_timeout=20).run()

    assert not app.exception
    menu_buttons = {"delete_session"}  # 在 ··· 菜单里，菜单本身已禁用
    assert all(button.disabled for button in app.button if button.key not in menu_buttons)
    assert {button.key for button in app.button} >= {"new_analysis", f"session_{sid}", "clear_analysis_memory",
                                                    "geoagent_example_0", "refill_7", "map_reset"}
    assert app.pills[0].disabled
    assert all(block.proto.popover.disabled for block in app.get("popover"))
