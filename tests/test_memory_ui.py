"""会话记忆的页面回归：临时数据库、模拟 Agent，不请求模型 API。"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import config, conversation, react, sessions


PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


@pytest.fixture
def memory_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def no_model(settings=None):
        raise AssertionError("页面回归不得调用模型 API")

    monkeypatch.setattr(react, "_get_llm", no_model)
    return sessions


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _session_buttons(app):
    return [button for button in app.sidebar.button if (button.key or "").startswith("session_")]


def _sidebar_text(app):
    return "\n".join(str(element.value) for collection in
                     (app.sidebar.markdown, app.sidebar.caption, app.sidebar.text)
                     for element in collection)


def _legacy_chat(db, mmsi="668116204", title="同名航迹分析"):
    sid = db.create_session(title)
    db.save_message(sid, "user", f"MMSI {mmsi} 最近30天走了什么路线？")
    db.save_message(sid, "assistant", "已完成航迹分析。")
    assert db.load_memory(sid) is None
    return sid


def test_legacy_chat_loads_memory_and_chat_without_api(memory_db):
    sid = _legacy_chat(memory_db)
    app = _open(AppTest.from_file(str(PAGE), default_timeout=20).run(), sid)

    assert len(app.chat_message) == 2
    assert "668116204" in _sidebar_text(app)
    assert "最近天数" in _sidebar_text(app)
    assert memory_db.load_memory(sid)["state"]


def test_same_title_sessions_switch_and_new_chat_is_isolated(memory_db):
    first = _legacy_chat(memory_db, "668116204")
    second = _legacy_chat(memory_db, "123456789")
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    assert len(_session_buttons(app)) == 2

    _open(app, first)
    assert "668116204" in _sidebar_text(app)
    _open(app, second)
    assert "123456789" in _sidebar_text(app)
    assert "668116204" not in _sidebar_text(app)

    app.button(key="new_analysis").click().run()
    assert not app.exception
    assert app.session_state["current_session_id"] is None
    assert len(app.chat_message) == 0
    assert "暂无已记录的分析条件" in _sidebar_text(app)
    assert "123456789" not in _sidebar_text(app)
    assert app.button(key="clear_analysis_memory").disabled

    _open(app, first)
    assert len(app.chat_message) == 2
    assert "668116204" in _sidebar_text(app)


def test_clear_memory_keeps_chat_and_stays_clear_after_reload(memory_db):
    sid = _legacy_chat(memory_db)
    app = _open(AppTest.from_file(str(PAGE), default_timeout=20).run(), sid)
    app.button(key="clear_analysis_memory").click().run()

    assert not app.exception
    assert len(app.chat_message) == 2
    assert len(memory_db.load_messages(sid)) == 2
    assert not any(conversation.get_memory(sid).get("state", {}).values())
    assert "668116204" not in _sidebar_text(app)
    assert "暂无已记录的分析条件" in _sidebar_text(app)

    restored = _open(AppTest.from_file(str(PAGE), default_timeout=20).run(), sid)
    assert len(restored.chat_message) == 2
    assert "668116204" not in _sidebar_text(restored)
    assert not any(conversation.get_memory(sid).get("state", {}).values())


def test_early_summary_is_visible_without_internal_memory_fields(memory_db):
    sid = _legacy_chat(memory_db)
    for i in range(config.HISTORY_TURNS + 1):
        memory_db.save_message(sid, "user", f"第{i + 1}次继续查看之前的分析")
        memory_db.save_message(sid, "assistant", "已查看。")
    app = _open(AppTest.from_file(str(PAGE), default_timeout=20).run(), sid)

    assert conversation.get_memory(sid)["summary"]
    assert [expander.label for expander in app.sidebar.expander] == ["早期对话摘要"]
    assert any("668116204" in str(element.value) for element in app.sidebar.text)
    assert "processed_seq" not in _sidebar_text(app)
    assert "sources" not in _sidebar_text(app)


def test_question_passes_session_and_persists_tool_records(memory_db, monkeypatch):
    calls = []
    records = [{"name": "ship_track", "args": {"mmsi": 668116204, "days": 30},
                "output": "已查询该船最近30天航迹。", "success": True, "blocked": False}]

    def fake_stream(question, history=None, session_id=None):
        calls.append((question, history, session_id))
        assert memory_db.load_messages(session_id)[-1]["content"] == question
        result = react.AgentResult(question=question, answer="已完成航迹分析。")
        result.tool_records = records
        yield {"type": "answer", "result": result}

    monkeypatch.setattr(react, "stream", fake_stream)
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    app.chat_input[0].set_value("MMSI 668116204 最近30天的航迹").run()

    assert not app.exception
    sid = app.session_state["current_session_id"]
    assert sid
    assert calls == [("MMSI 668116204 最近30天的航迹", None, sid)]
    stored = memory_db.load_messages(sid)
    assert len(stored) == 2
    assert stored[1]["tool_records"] == records
    assert "668116204" in _sidebar_text(app)
