"""聊天工作区交互回归：临时会话库与模拟流，不访问模型 API。"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import react, sessions


PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


@pytest.fixture
def chat_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def forbidden_model():
        raise AssertionError("聊天工作区回归不得调用模型 API")

    monkeypatch.setattr(react, "_get_llm", forbidden_model)
    return sessions


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    return app


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _message_text(message):
    return "\n".join(
        str(element.value)
        for collection in (message.markdown, message.caption, message.error, message.warning)
        for element in collection
    )


def test_examples_only_fill_draft_without_creating_session(chat_db, monkeypatch):
    def forbidden_stream(*args, **kwargs):
        raise AssertionError("点击示例只能填入草稿，不能直接运行分析")

    monkeypatch.setattr(react, "stream", forbidden_stream)
    app = _app()
    examples = {
        "周边事件": "曼德海峡",
        "船舶航迹": "668116204",
        "事件背景": "银河领袖号",
        "冲突排名": "Goldstein",
    }
    for label, expected in examples.items():
        _button(app, label).click().run()
        assert not app.exception
        assert expected in app.chat_input(key="geoagent_prompt").value
        assert app.session_state["current_session_id"] is None
        assert not app.chat_message
        assert chat_db.list_sessions() == []


def test_submit_persists_reply_and_tool_evidence(chat_db, monkeypatch):
    calls = []
    question = "查看 MMSI 668116204 最近30天的航迹"
    records = [{
        "name": "ship_track", "args": {"mmsi": 668116204, "days": 30},
        "output": "已查询航迹。", "success": True, "blocked": False,
    }]

    def fake_stream(prompt, history=None, session_id=None):
        calls.append((prompt, session_id))
        assert chat_db.load_messages(session_id)[-1]["content"] == question
        yield {"type": "thinking", "step": 1}
        yield {"type": "tool_start", "name": "ship_track", "args": records[0]["args"],
               "step": 1, "blocked": False}
        yield {"type": "tool_end", "name": "ship_track", "output": "已查询航迹。",
               "blocked": False}
        yield {"type": "answer", "result": react.AgentResult(
            question=prompt, answer="已完成这艘船的航迹分析。", tool_records=records,
        )}

    monkeypatch.setattr(react, "stream", fake_stream)
    app = _app()
    app.chat_input(key="geoagent_prompt").set_value(question).run()
    assert not app.exception
    # AppTest 在同次工具流的 st.rerun 后会保留旧 status 子树；重新读取稳定页面。
    app.run()
    assert not app.exception
    sid = app.session_state["current_session_id"]
    assert calls == [(question, sid)]
    stored = chat_db.load_messages(sid)
    assert len(stored) == len(app.chat_message) == 2
    assert stored[1]["reply_to_seq"] == stored[0]["seq"]
    assert stored[1]["tool_records"] == records
    assert stored[1]["error"] is None
    assert app.session_state["agent_messages"][1]["tool_records"] == records
    assert "已完成这艘船的航迹分析。" in _message_text(app.chat_message[1])
    # 带图标的 st.expander 在 AppTest 里归为 Status（st.status 就是带图标的折叠区）
    process = app.chat_message[1].status[0]
    assert process.label == "分析过程 · 1 步 · 查询船舶航迹"
    assert not process.proto.expanded


@pytest.mark.parametrize("failure", ["error_result", "exception", "no_answer"])
def test_failed_turn_is_nonempty_and_restored_with_history(chat_db, monkeypatch, failure):
    sid = chat_db.create_session("航迹连续分析")
    previous = []
    # 八轮超出模型近期记忆范围；页面应完整保留，不能误用模型上下文窗口裁剪 UI。
    for index in range(8 if failure == "error_result" else 1):
        question = f"第{index + 1}轮历史问题"
        answer = f"第{index + 1}轮历史回答"
        user_seq = chat_db.save_message(sid, "user", question)
        chat_db.save_message(sid, "assistant", answer, reply_to_seq=user_seq)
        previous.extend([question, answer])

    def fake_stream(prompt, history=None, session_id=None):
        assert session_id == sid
        yield {"type": "thinking", "step": 1}
        if failure == "exception":
            raise RuntimeError("模拟连接中断")
        if failure == "no_answer":
            return
        yield {"type": "answer", "result": react.AgentResult(
            question=prompt, answer="", error="模拟查询失败，请稍后重试",
        )}

    monkeypatch.setattr(react, "stream", fake_stream)
    app = _open(_app(), sid)
    app.chat_input(key="geoagent_prompt").set_value("继续分析当前船舶").run()
    assert not app.exception
    stored = chat_db.load_messages(sid)
    assert [message["content"] for message in stored[:-2]] == previous
    assert len(app.chat_message) == len(previous) + 2
    reply = stored[-1]
    assert reply["role"] == "assistant"
    assert reply["content"].strip()
    assert reply["error"]
    assert reply["reply_to_seq"] == stored[-2]["seq"]
    assert app.session_state["agent_messages"][-1]["error"] == reply["error"]
    if failure == "error_result":
        assert "模拟查询失败" in _message_text(app.chat_message[-1])

    restored = _open(_app(), sid)
    assert len(restored.chat_message) == len(stored)
    assert restored.session_state["agent_messages"][-1]["error"] == reply["error"]
    for expected, message in zip(previous, restored.chat_message):
        assert expected in _message_text(message)
    assert reply["content"] in _message_text(restored.chat_message[-1])


def test_whitespace_submit_does_not_create_session(chat_db, monkeypatch):
    def forbidden_stream(*args, **kwargs):
        raise AssertionError("空白消息不得触发分析")

    monkeypatch.setattr(react, "stream", forbidden_stream)
    app = _app()
    app.chat_input(key="geoagent_prompt").set_value("  \n\t  ").run()
    assert not app.exception
    assert app.session_state["current_session_id"] is None
    assert not app.chat_message
    assert chat_db.list_sessions() == []


def test_new_chat_clears_draft_and_legacy_pending_question(chat_db, monkeypatch):
    def forbidden_stream(*args, **kwargs):
        raise AssertionError("新会话不得提交旧草稿或遗留示例")

    monkeypatch.setattr(react, "stream", forbidden_stream)
    sid = chat_db.create_session("原会话")
    chat_db.save_message(sid, "user", "旧问题")
    app = _open(_app(), sid)
    # 直接写入状态模拟尚未发送的输入，不触发 chat_input 的提交事件。
    app.session_state["geoagent_prompt"] = "未发送的航迹分析草稿"
    app.session_state["_pending_question"] = "旧实现遗留的示例问题"
    app.button(key="new_analysis").click().run()
    assert not app.exception
    assert app.session_state["current_session_id"] is None
    assert not app.chat_message
    assert not app.chat_input(key="geoagent_prompt").value
    assert not app.session_state.filtered_state.get("_pending_question")
    assert len(chat_db.list_sessions()) == 1
    assert chat_db.load_messages(sid)[0]["content"] == "旧问题"
