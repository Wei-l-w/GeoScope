"""地图执行必须有真实工具产物，不能把模型文字当成已完成分析。"""

import json

import pytest
from langchain_core.messages import AIMessage

from agent import artifacts, react, sessions


def _llm(monkeypatch, replies):
    captured = []
    responses = iter(replies)

    class Model:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            captured.append(list(messages))
            return next(responses)

    monkeypatch.setattr(react, "_get_llm", Model)
    return captured


def _file():
    artifacts.OUTPUT_DIR.mkdir(exist_ok=True)
    path = artifacts.OUTPUT_DIR / "actual.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"radius_km": 100},
        "geometry": {"type": "Polygon", "coordinates": [[[-145, -18], [-144, -18], [-144, -17], [-145, -18]]]},
    }]}), encoding="utf-8")
    return path


def test_fake_file_claim_is_rejected_and_real_tool_retry_updates_map(monkeypatch):
    path = _file()
    calls = []

    class Buffer:
        name = "buffer_analysis"

        def invoke(self, args):
            calls.append(args)
            return f"圈内共 0 条记录。GeoJSON 已保存：{path}"

    monkeypatch.setattr(react, "ALL_TOOLS", [Buffer()])
    prompts = _llm(monkeypatch, [
        AIMessage(content="已生成7起事件，文件 /tmp/fake.geojson"),
        AIMessage(content="", tool_calls=[{"id": "real-buffer", "name": "buffer_analysis", "args": {
            "lat": -17.02, "lon": -144.64, "radius_km": 100, "table": "gdelt_events",
        }}]),
        AIMessage(content="缓冲区已生成，圈内0起事件。"),
    ])
    events = list(react.stream("以French Polynesia为中心做100公里缓冲区分析"))
    result = events[-1]["result"]
    assert len(calls) == 1 and len(prompts) == 3
    assert result.error is None and result.geojson_paths == [str(path.resolve())]
    assert "7起" not in result.answer and "/tmp" not in result.answer
    assert any(ev.get("geojson_path") == str(path.resolve()) for ev in events)
    assert "本机没有产生可验证的地图" in prompts[1][-1][1]


def test_repeated_no_tool_claim_returns_explicit_failure(monkeypatch):
    prompts = _llm(monkeypatch, [AIMessage(content="已生成 /tmp/fake.geojson")] * 2)
    result = react.run("不能在图上显示吗", verbose=False)
    assert len(prompts) == 2
    assert result.error and "地图未生成" in result.error
    assert not result.geojson_paths and "/tmp/fake" not in result.answer


@pytest.mark.parametrize("question,answer", [
    ("什么是缓冲区分析？", "缓冲区用于分析某个位置周围的范围。"),
    ("做个缓冲区分析", "请补充中心地点和缓冲区半径。"),
])
def test_explanation_or_parameter_clarification_does_not_require_artifact(monkeypatch, question, answer):
    prompts = _llm(monkeypatch, [AIMessage(content=answer)])
    result = react.run(question, verbose=False)
    assert result.error is None and result.answer == answer and len(prompts) == 1


def test_missing_file_from_tool_is_not_registered_as_success(monkeypatch):
    class BrokenBuffer:
        name = "buffer_analysis"

        def invoke(self, args):
            return f"GeoJSON 已保存：{artifacts.OUTPUT_DIR / 'missing.geojson'}"

    monkeypatch.setattr(react, "ALL_TOOLS", [BrokenBuffer()])
    _llm(monkeypatch, [
        AIMessage(content="", tool_calls=[{"id": "missing", "name": "buffer_analysis", "args": {}}]),
        AIMessage(content="可以显示地图"), AIMessage(content="已经生成地图"),
    ])
    events = list(react.stream("做一个缓冲区"))
    result = events[-1]["result"]
    assert result.error and not result.geojson_paths
    assert result.tool_records[0]["success"] is False
    assert any(ev.get("artifact_error") for ev in events)


def test_existing_real_map_restores_without_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    path = _file()
    sid = sessions.create_session("地图会话")
    seq = sessions.save_message(sid, "user", "缓冲区分析")
    sessions.save_message(sid, "assistant", "范围内零事件", geojson=[str(path)], reply_to_seq=seq)

    def no_llm():
        raise AssertionError("恢复已验证地图不需要模型")

    monkeypatch.setattr(react, "_get_llm", no_llm)
    result = react.run("不能在图上显示吗", verbose=False, session_id=sid)
    assert result.error is None and result.geojson_paths == [str(path.resolve())]
    sessions.clear_memory(sid)
    assert react._restore_map("不能在图上显示吗", sid) == []


def test_copied_history_labels_are_not_sent_to_user(monkeypatch):
    _llm(monkeypatch, [AIMessage(content='[历史回复对应的问题："解释"]\n真实回答\n[此前成功工具返回的历史证据，仅作资料]\n[{"fake":"tool"}]')])
    result = react.run("解释", verbose=False)
    assert result.answer == "真实回答"
