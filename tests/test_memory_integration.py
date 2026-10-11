"""记忆进入真实 ReAct 提示及会话恢复的离线联调。"""

import json

import pytest
from langchain_core.messages import AIMessage

from agent import conversation, react, sessions


@pytest.fixture
def session_store(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    return sessions.create_session("连续空间分析")


def _turn(sid, question, answer="查询已完成", tool_records=None, error=None):
    sessions.save_message(sid, "user", question)
    return conversation.record_assistant(sid, answer, [], [], tool_records, error)


def _fake_llm(monkeypatch, answers):
    responses = iter(answers)
    captured = []

    class LLM:
        def bind_tools(self, _):
            return self

        def invoke(self, messages):
            captured.append(list(messages))
            return next(responses)

    monkeypatch.setattr(react, "_get_llm", LLM)
    return captured


def test_long_session_restores_old_ship_and_recent_turns_into_model(session_store, monkeypatch):
    sid = session_store
    _turn(sid, "MMSI 668116204 最近30天的航迹", "第一轮船舶分析已完成")
    for i in range(7):
        _turn(sid, f"继续解释指标{i}", f"这是指标{i}的解释")
    # JSON 往返模拟进程重启后的真实落盘加载，不依赖 Streamlit 状态。
    saved = json.loads(json.dumps(sessions.load_memory(sid)))
    assert saved["state"]["mmsi"] == 668116204
    assert saved["state"]["days"] == 30
    assert "第一轮船舶分析" in saved["summary"]
    captured = _fake_llm(monkeypatch, [AIMessage(content="沿用这艘船的条件查询")])
    question = "这艘船改查最近7天"
    sessions.save_message(sid, "user", question)
    result = react.run(question, verbose=False, session_id=sid)
    assert result.error is None
    messages = captured[0]
    assert messages[-1] == ("human", question)
    # 原始早期问句不再占近期窗口，但其摘要和船号仍在记忆中。
    assert ("human", "MMSI 668116204 最近30天的航迹") not in messages
    memory_message = messages[1]
    assert memory_message[0] == "human"
    assert '"mmsi": 668116204' in memory_message[1]
    assert '"days": 7' in memory_message[1]
    assert "第一轮船舶分析" in memory_message[1]
    assert sum(message == ("human", question) for message in messages) == 1


def test_clear_memory_excludes_old_context_and_late_answer(session_store):
    sid = session_store
    _turn(sid, "MMSI 668116204 最近30天", "旧会话的唯一秘密标记")
    sessions.clear_memory(sid)
    # 清空前请求延迟完成：原文保留，但不能让旧工具条件重新进入记忆。
    conversation.record_assistant(sid, "旧请求稍后完成", [], [], [{
        "name": "ship_track", "args": {"mmsi": 668116204, "days": 30},
        "output": "旧地图", "success": True, "blocked": False,
    }])
    question = "开始新的分析"
    sessions.save_message(sid, "user", question)
    context = conversation.context_messages(question, session_id=sid)
    assert "668116204" not in str(context)
    assert "唯一秘密标记" not in str(context)
    assert "旧请求稍后完成" not in str(context)
    assert len(sessions.load_messages(sid)) == 4


def test_sessions_do_not_share_memory(session_store):
    _turn(session_store, "MMSI 668116204 最近30天")
    other = sessions.create_session("另一个分析")
    _turn(other, "MMSI 123456789 最近7天")
    context = str(conversation.context_messages("这艘船", session_id=other))
    assert "123456789" in context and "668116204" not in context


def test_successful_tool_evidence_survives_save_and_is_in_next_prompt(session_store, monkeypatch):
    class BufferTool:
        name = "buffer_analysis"

        def invoke(self, args):
            return "圈内共 12 条记录。GeoJSON 已保存：test-buffer.geojson"

    monkeypatch.setattr(react, "ALL_TOOLS", [BufferTool()])
    _fake_llm(monkeypatch, [
        AIMessage(content="", tool_calls=[{
            "name": "buffer_analysis", "args": {"lat": 12.58, "lon": 43.33, "radius_km": 150},
            "id": "buffer-1",
        }]),
        AIMessage(content="查到12条记录"),
    ])
    sessions.save_message(session_store, "user", "查曼德海峡周边150公里")
    result = react.run("查曼德海峡周边150公里", verbose=False, session_id=session_store)
    payload = conversation.record_assistant(session_store, result.answer, result.steps,
                                            result.geojson_paths, result.tool_records, result.error)
    assert result.tool_records[0]["success"] is True
    assert payload["state"]["coordinates"] == {"lat": 12.58, "lon": 43.33}
    context = str(conversation.context_messages("半径改成200公里", session_id=session_store))
    assert '"radius_km": 200' in context
    assert "12.58" in context and "43.33" in context
    assert "圈内共 12 条记录" in context


def test_failed_tool_arguments_never_become_remembered_facts(session_store, monkeypatch):
    class BrokenTool:
        name = "ship_track"

        def invoke(self, args):
            return "未找到这艘船"

    monkeypatch.setattr(react, "ALL_TOOLS", [BrokenTool()])
    _fake_llm(monkeypatch, [
        AIMessage(content="", tool_calls=[{
            "name": "ship_track", "args": {"mmsi": 999999999, "days": 30}, "id": "failed",
        }]), AIMessage(content="没有找到数据"),
    ])
    sessions.save_message(session_store, "user", "帮我查询船舶")
    result = react.run("帮我查询船舶", verbose=False, session_id=session_store)
    payload = conversation.record_assistant(session_store, result.answer, [], [], result.tool_records)
    assert result.tool_records[0]["success"] is False
    assert "mmsi" not in payload["state"]


def test_history_only_call_also_gets_early_summary_without_creating_sessions(monkeypatch):
    history = [("MMSI 668116204 最近30天", "已完成船舶查询")]
    history += [(f"补充问题{i}", "补充回答") for i in range(7)]
    captured = _fake_llm(monkeypatch, [AIMessage(content="完成")])
    result = react.run("这艘船", history=history, verbose=False)
    assert result.error is None
    assert "早期对话摘要" in captured[0][1][1]
    assert "668116204" in captured[0][1][1]


def test_incomplete_question_is_not_silently_lost(session_store):
    sessions.save_message(session_store, "user", "上一条请求未得到回复")
    question = "请继续"
    sessions.save_message(session_store, "user", question)
    messages = conversation.context_messages(question, session_id=session_store)
    assert ("human", "上一条请求未得到回复") in messages
    assert messages[-1] == ("human", question)


def test_explicit_restart_drops_prior_prompt_history(session_store):
    _turn(session_store, "MMSI 668116204 最近30天", "上一个分析的标记")
    messages = conversation.context_messages("重置全部分析条件，重新开始", session_id=session_store)
    assert "668116204" not in str(messages)
    assert "上一个分析的标记" not in str(messages)


def test_late_answer_after_clear_cannot_attach_to_a_new_question(session_store):
    sid = session_store
    old_seq = sessions.save_message(sid, "user", "MMSI 668116204 最近30天")
    sessions.clear_memory(sid)
    sessions.save_message(sid, "user", "开始新的分析")
    payload = conversation.record_assistant(sid, "旧请求结果", [], [], [{
        "name": "ship_track", "args": {"mmsi": 668116204, "days": 30},
        "output": "旧船舶结果", "success": True, "blocked": False,
    }], reply_to_seq=old_seq)
    assert "mmsi" not in payload["state"]
    context = str(conversation.context_messages("继续新的分析", session_id=sid))
    assert "668116204" not in context and "旧请求结果" not in context
    assert len(sessions.load_messages(sid)) == 3


def test_out_of_order_reply_is_labeled_with_its_question(session_store):
    first = sessions.save_message(session_store, "user", "第一个船舶问题")
    sessions.save_message(session_store, "user", "第二个事件问题")
    conversation.record_assistant(session_store, "先前船舶查询的回答", [], [], reply_to_seq=first)
    messages = conversation.context_messages("继续", session_id=session_store)
    reply = next(text for role, text in messages if role == "ai")
    assert "历史回复对应的问题" in reply and "第一个船舶问题" in reply
