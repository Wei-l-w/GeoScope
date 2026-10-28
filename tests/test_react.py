"""ReAct 回归：使用假的模型和工具，不发起 API 请求。"""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent import react


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return f"{self.name} result {len(self.calls)}"


class FakeLLM:
    def __init__(self, answers):
        self.answers = iter(answers)
        self.messages = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        # 模拟 API 的 tool_call 协议校验：下一条消息必须逐一补齐工具回复。
        pending = set()
        for message in messages:
            if isinstance(message, ToolMessage):
                assert message.tool_call_id in pending
                pending.remove(message.tool_call_id)
            else:
                assert not pending, "尚有工具调用未回复，不能插入其他消息"
                if isinstance(message, AIMessage):
                    pending = {call["id"] for call in message.tool_calls}
        assert not pending
        self.messages.append(list(messages))
        return next(self.answers)


def tool_turn(*names, prefix="call"):
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": {"query": str(i)}, "id": f"{prefix}-{i}"}
        for i, name in enumerate(names)
    ])


def setup_agent(monkeypatch, answers):
    tools = {name: FakeTool(name) for name in ("knowledge_search", "query_database")}
    llm = FakeLLM(answers)
    monkeypatch.setattr(react, "ALL_TOOLS", list(tools.values()))
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: llm)
    return llm, tools


def test_repeated_tool_is_blocked_across_llm_turns(monkeypatch):
    llm, tools = setup_agent(monkeypatch, [
        *(tool_turn("knowledge_search", prefix=str(i)) for i in range(4)),
        AIMessage(content="整合已有报道"),
    ])
    events = list(react.stream("背景是什么？"))
    assert len(tools["knowledge_search"].calls) == 2
    ends = [event for event in events if event["type"] == "tool_end"]
    assert [event["blocked"] for event in ends] == [False, False, True, True]
    replies = [m for m in llm.messages[-1] if isinstance(m, ToolMessage)]
    assert len(replies) == 4
    assert all("本次未执行" in m.content for m in replies[2:])
    assert events[-1]["result"].answer == "整合已有报道"


def test_same_turn_repeated_tools_receive_all_replies(monkeypatch):
    llm, tools = setup_agent(monkeypatch, [
        tool_turn(*(["knowledge_search"] * 4)),
        AIMessage(content="完成"),
    ])
    result = react.run("背景", verbose=False)
    assert len(tools["knowledge_search"].calls) == 2
    replies = [m for m in llm.messages[-1] if isinstance(m, ToolMessage)]
    assert [m.tool_call_id for m in replies] == [f"call-{i}" for i in range(4)]
    assert len(result.steps) == 4
    assert "已阻断" in result.steps[-1]


def test_switching_tools_resets_consecutive_limit(monkeypatch):
    _, tools = setup_agent(monkeypatch, [
        tool_turn("knowledge_search", "knowledge_search", "knowledge_search"),
        tool_turn("query_database", "knowledge_search", "knowledge_search", prefix="next"),
        AIMessage(content="完成"),
    ])
    result = react.run("背景和数量", verbose=False)
    assert len(tools["knowledge_search"].calls) == 4
    assert len(tools["query_database"].calls) == 1
    assert result.error is None


@pytest.mark.parametrize("verbose", [False, True])
def test_run_returns_final_result_with_or_without_logging(monkeypatch, capsys, verbose):
    setup_agent(monkeypatch, [
        tool_turn("query_database"), AIMessage(content="共有 12 起事件"),
    ])
    result = react.run("有多少事件？", verbose=verbose)
    assert isinstance(result, react.AgentResult)
    assert result.answer == "共有 12 起事件"
    assert bool(capsys.readouterr().out) == verbose


def test_global_step_budget_remains_bounded(monkeypatch):
    llm, tools = setup_agent(monkeypatch, [
        tool_turn("knowledge_search", prefix=str(i)) for i in range(react.MAX_STEPS)
    ])
    result = react.run("背景", verbose=False)
    assert len(llm.messages) == react.MAX_STEPS
    assert len(tools["knowledge_search"].calls) == 2
    assert result.error == f"达到最大步数 {react.MAX_STEPS} 仍未收敛"


def test_missing_final_event_returns_explicit_failure(monkeypatch):
    monkeypatch.setattr(react, "stream", lambda *args, **kwargs: iter([]))
    result = react.run("问题", verbose=False)
    assert isinstance(result, react.AgentResult)
    assert result.error and "未返回最终结果" in result.error
    assert result.answer == result.error


def test_empty_model_answer_returns_explicit_failure(monkeypatch):
    setup_agent(monkeypatch, [AIMessage(content="   ")])
    result = react.run("问题", verbose=False)
    assert result.error == "LLM 未返回有效回答"


def test_llm_initialization_failure_returns_result(monkeypatch):
    def fail(settings=None):
        raise RuntimeError("未配置模型")

    monkeypatch.setattr(react, "_get_llm", fail)
    result = react.run("问题", verbose=False)
    assert result.error and "LLM 初始化失败" in result.error
