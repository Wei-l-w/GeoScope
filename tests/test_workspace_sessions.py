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


def test_session_deleted_in_another_tab_falls_back_to_a_new_one(store):
    # 两个标签页开着同一个会话库：A 页删掉当前会话，B 页下一次重跑不能整页红屏
    sid = _chat(store, "会被删掉")
    app = _open(_app(), sid)
    store.delete_session(sid)

    app.run()
    assert not app.exception
    assert app.session_state["current_session_id"] is None
    assert not app.chat_message
    assert "还没有历史会话" in _captions(app)


def _corrupt_memory(store, sid):
    import duckdb

    with duckdb.connect(str(store.DB_PATH)) as con:
        con.execute("INSERT INTO chat_memory (session_id, memory_json, cutoff_seq) VALUES (?, ?, 0) "
                    "ON CONFLICT (session_id) DO UPDATE SET memory_json = excluded.memory_json",
                    [sid, "{not json"])


def test_corrupted_memory_does_not_hide_the_chat_or_block_new_questions(store, monkeypatch):
    # 记忆行损坏（旧版本数据、手工改库）不是"会话被删"：聊天记录要留着，
    # 而且这个会话此后每一次提问都得能正常完成——坏快照按空记忆重建，下一次保存覆盖它。
    sid = _chat(store, "记忆损坏")
    app = _open(_app(), sid)
    _corrupt_memory(store, sid)

    def fake_stream(prompt, history=None, session_id=None):
        yield {"type": "thinking", "step": 1}
        yield {"type": "answer", "result": react.AgentResult(question=prompt, answer="这是本轮的回答。")}

    monkeypatch.setattr(react, "stream", fake_stream)
    app.chat_input(key="geoagent_prompt").set_value("损坏之后还能提问吗？").run()

    assert not app.exception
    assert app.session_state["current_session_id"] == sid
    stored = store.load_messages(sid)
    assert stored[-1]["content"] == "这是本轮的回答。"
    assert store.load_memory(sid) is not None  # 坏快照已被重建的记忆覆盖


def test_corrupted_message_json_is_reported_without_hiding_the_chat(store):
    # 消息行里的 steps_json/geojson_json 损坏：会话还在，只是记忆读不出来。
    # 不能当成"会话被删"把整段聊天清掉，也不能整页红屏。
    import duckdb

    sid = _chat(store, "消息损坏")
    app = _open(_app(), sid)
    with duckdb.connect(str(store.DB_PATH)) as con:
        con.execute("UPDATE chat_messages SET steps_json = ? WHERE session_id = ?", ["{not json", sid])

    app.run()
    assert not app.exception
    assert app.session_state["current_session_id"] == sid
    assert len(app.chat_message) == 2
    assert any("记忆无法读取" in str(item.value) for item in app.error)


def _ghost_page(sid):
    import streamlit as st

    from app import sessions_ui

    sessions_ui.open_session(sid)
    st.write("sid=" + str(st.session_state.current_session_id))


def test_opening_a_vanished_session_does_not_raise(store):
    # 列表是上一次重跑画的，点下去时另一个标签页可能已经删了：回调不能抛 ValueError
    app = AppTest.from_function(_ghost_page, args=("not-a-real-session",), default_timeout=20).run()
    assert not app.exception
    assert app.session_state["current_session_id"] is None
    assert "sid=None" in str(app.markdown[0].value)


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
    # 菜单体在前端展开后会跨重跑保留，里面的按钮必须自己置灰，不能靠 popover 的 disabled
    assert all(button.disabled for button in app.button)
    assert {button.key for button in app.button} >= {"new_analysis", f"session_{sid}", "clear_analysis_memory",
                                                    "geoagent_example_0", "refill_7", "map_reset", "delete_session"}
    assert app.pills[0].disabled
    assert all(block.proto.popover.disabled for block in app.get("popover"))


def test_a_run_disables_every_interactive_block_end_to_end(store, monkeypatch):
    # _busy_page 直接以 busy=True 调各区块，接线断了也不会红；这里提交一次真实问题，
    # 检查工作台在同一次运行里确实把 busy=True 传给了每个会画可交互控件的地方——
    # 少传一处，那个按钮就会在分析进行中活着，点一下就会中止本轮。
    from app import chat_ui, map_view, sessions_ui

    seen = []
    real_render, real_bar = sessions_ui.render, map_view.render_bar
    real_header, real_message = chat_ui.header, chat_ui.render_message

    def spy_render(busy):
        seen.append(("sidebar", busy))
        return real_render(busy)

    def spy_bar(state, sid, busy):
        seen.append(("bar", busy))
        return real_bar(state, sid, busy)

    def spy_header(title, subtitle, sid, busy):
        seen.append(("header", busy))
        return real_header(title, subtitle, sid, busy)

    def spy_message(message, mode, **kwargs):
        # 历史循环会传 interrupted（并带上"重新填入"按钮），本轮实时渲染不传：
        # 分开记，否则实时渲染的 busy=True 会替历史循环的接线打掩护。
        seen.append(("history", bool(kwargs.get("interrupted")), kwargs.get("busy", False))
                    if "interrupted" in kwargs else ("live", kwargs.get("busy", False)))
        return real_message(message, mode, **kwargs)

    def fake_stream(prompt, history=None, session_id=None):
        yield {"type": "thinking", "step": 1}
        yield {"type": "answer", "result": react.AgentResult(question=prompt, answer="分析完成。")}

    monkeypatch.setattr(sessions_ui, "render", spy_render)
    monkeypatch.setattr(map_view, "render_bar", spy_bar)
    monkeypatch.setattr(chat_ui, "header", spy_header)
    monkeypatch.setattr(chat_ui, "render_message", spy_message)
    monkeypatch.setattr(react, "stream", fake_stream)

    sid = _chat(store, "已有会话")
    store.save_message(sid, "user", "上一轮没收到回答的提问")  # 历史里会画出"重新填入"
    app = _open(_app(), sid)
    seen.clear()
    app.chat_input(key="geoagent_prompt").set_value("曼德海峡周边有哪些事件？").run()
    assert not app.exception
    for block in ("sidebar", "bar", "header"):
        assert (block, True) in seen, (block, seen)
    assert ("live", True) in seen, seen
    assert ("history", True, True) in seen, seen  # 历史里中断提问的"重新填入"也必须置灰


def test_clearing_memory_of_a_deleted_session_does_not_raise(store):
    # 列表是上一次重跑画的，点"清空分析记忆"时另一个标签页可能已经删了它
    app = AppTest.from_function(_clear_memory_page, args=("not-a-real-session",), default_timeout=20).run()
    assert not app.exception
    assert "ok" in str(app.markdown[0].value)


def _clear_memory_page(sid):
    import streamlit as st

    from app import sessions_ui

    sessions_ui._clear_memory(sid)
    st.write("ok")


def test_a_run_keeps_the_answer_when_the_session_is_deleted_midway(store, monkeypatch):
    # 分析几十秒里，另一个标签页把这个会话删了：写回会抛 ValueError。
    # 用户必须还能读到刚生成的回答，而不是整页 traceback。
    def deleting_stream(prompt, history=None, session_id=None):
        store.delete_session(session_id)  # 模拟另一个标签页在分析期间删除
        yield {"type": "thinking", "step": 1}
        yield {"type": "answer", "result": react.AgentResult(question=prompt, answer="这是本轮的回答。")}

    monkeypatch.setattr(react, "stream", deleting_stream)
    app = _app()
    app.chat_input(key="geoagent_prompt").set_value("曼德海峡周边有哪些事件？").run()

    assert not app.exception
    assert app.session_state["current_session_id"] is None  # 已退回空会话，不再指向死数据
    text = "\n".join(str(item.value) for item in app.markdown) + "\n".join(str(item.value) for item in app.warning)
    assert "这是本轮的回答。" in text
    assert "另一个标签页" in text


def test_composer_keeps_the_submit_locked_until_the_turn_ends(store):
    from streamlit.proto.ChatInput_pb2 import ChatInput

    app = _app()
    assert app.chat_input(key="geoagent_prompt").proto.submit_mode == ChatInput.SUBMIT_MODE_DISABLE
