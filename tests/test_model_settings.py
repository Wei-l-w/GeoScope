"""界面里的模型配置：本地覆盖层的读写、校验、试连与侧栏表单。全程不访问网络、不碰真实密钥。"""

import json
import os
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import config, model_config

PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


@pytest.fixture
def settings_file():
    """指向临时路径的本地配置文件；conftest 已把全局 SETTINGS_PATH 隔离到 tmp。"""
    return model_config.SETTINGS_PATH


@pytest.fixture
def env_defaults(monkeypatch):
    """固定 .env 层的取值：真实环境变量会让断言随开发机变化。"""
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-env")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "https://env.example/v1")
    monkeypatch.setattr(config, "MODEL_NAME", "env-model")


def write(path: Path, payload) -> None:
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------- 读写
def test_saved_settings_take_precedence_over_env(settings_file, env_defaults):
    model_config.save("https://relay.example/v1", "sk-file", "file-model")
    current = model_config.current()
    assert (current.base_url, current.api_key, current.model, current.source) == (
        "https://relay.example/v1", "sk-file", "file-model", "file")


def test_missing_file_falls_back_to_env(settings_file, env_defaults):
    current = model_config.current()
    assert (current.base_url, current.api_key, current.model, current.source) == (
        "https://env.example/v1", "sk-env", "env-model", "env")


def test_save_leaves_no_temporary_file(settings_file, env_defaults):
    model_config.save("", "sk-file", "file-model")
    assert settings_file.is_file()
    assert not settings_file.with_name(settings_file.name + ".tmp").exists()
    # Base URL 可以留空：官方接口的情形
    assert model_config.current().base_url == ""


def test_save_strips_surrounding_whitespace(settings_file, env_defaults):
    model_config.save("  https://relay.example/v1 \n", " sk-file ", " file-model ")
    assert settings_file.read_text(encoding="utf-8")
    current = model_config.current()
    assert (current.base_url, current.api_key, current.model) == (
        "https://relay.example/v1", "sk-file", "file-model")


@pytest.mark.parametrize("payload", [
    "{ 不是 JSON",
    "[]",
    '"字符串"',
    json.dumps({"base_url": "https://x/v1", "model": "m"}),              # 缺 Key
    json.dumps({"base_url": "https://x/v1", "api_key": "sk", "model": ""}),  # 模型名为空
    json.dumps({"base_url": "https://x/v1", "api_key": 42, "model": "m"}),   # Key 类型不对
    # 只有 base_url 类型不对：整份作废。否则它会洗成空串，请求改打官方接口
    json.dumps({"base_url": 42, "api_key": "sk", "model": "m"}),
    json.dumps({"base_url": "https://x/v1", "api_key": "sk", "model": None}),
    # 显式 null 与"键不存在"不同：前者是被写坏的显式值，不能当成官方接口
    json.dumps({"base_url": None, "api_key": "sk", "model": "m"}),
])
def test_broken_file_falls_back_to_env_instead_of_raising(settings_file, env_defaults, payload):
    write(settings_file, payload)
    assert model_config.load() is None
    assert model_config.current().source == "env"


def test_non_utf8_file_falls_back_to_env(settings_file, env_defaults):
    settings_file.write_bytes(b'{"api_key": "\xff\xfe", "model": "m"}')
    assert model_config.load() is None
    assert model_config.current().source == "env"


def test_huge_integer_in_json_falls_back_instead_of_crashing(settings_file, env_defaults):
    """超长整数让 json.loads 抛 ValueError（int 位数上限），同样当坏文件。"""
    write(settings_file, '{"api_key": ' + "9" * 5000 + ', "model": "m"}')
    assert model_config.load() is None
    assert model_config.current().source == "env"


def test_absurdly_deep_json_falls_back_instead_of_crashing(settings_file, env_defaults):
    """极深嵌套让 json.loads 抛 RecursionError（实测不是 JSONDecodeError）：同样当坏文件。"""
    write(settings_file, '{"api_key":' + "[" * 4000 + "]" * 4000 + ',"model":"m"}')
    assert model_config.load() is None
    assert model_config.current().source == "env"


def test_oversized_file_is_ignored_without_parsing(settings_file, env_defaults):
    """超过上限的文件不可能来自本程序：连解析都不做，直接回落 .env。"""
    payload = json.dumps({"base_url": "", "api_key": "sk-file", "model": "file-model",
                          "pad": "x" * (model_config.MAX_FILE_BYTES + 100)})
    write(settings_file, payload)
    assert model_config.load() is None
    assert model_config.current().source == "env"


def test_missing_base_url_key_is_still_accepted(settings_file, env_defaults):
    # 旧版本或手写的文件可能没有 base_url：视为"官方接口"，其余字段仍生效
    write(settings_file, {"api_key": "sk-file", "model": "file-model"})
    current = model_config.current()
    assert (current.source, current.base_url, current.model) == ("file", "", "file-model")


def test_clear_removes_file_and_is_idempotent(settings_file, env_defaults):
    model_config.save("", "sk-file", "file-model")
    model_config.clear()
    assert not settings_file.exists()
    model_config.clear()  # 再删一次不该抛异常
    assert model_config.current().source == "env"


def test_save_rejects_invalid_settings_itself(settings_file):
    """界面已经校验过，但 save 是公开函数：绕过界面直接调用也不该写进非法配置。"""
    with pytest.raises(ValueError, match="Base URL"):
        model_config.save("relay.example/v1", "sk-file", "file-model")
    assert not settings_file.exists()


def test_concurrent_saves_never_leave_a_broken_file(settings_file):
    """多个标签页同时点保存：临时文件名是固定的，不加锁会互相截断。

    future.result() 会把线程里的异常重新抛出来——只 join 的话，八个里七个失败、剩一个成功
    也能满足"文件是合法 JSON"的断言，等于什么都没测到。
    """
    from concurrent.futures import ThreadPoolExecutor

    def save(index):
        model_config.save("", f"sk-{index}", f"model-{index}")
        return index

    with ThreadPoolExecutor(max_workers=8) as pool:
        done = [future.result() for future in [pool.submit(save, i) for i in range(8)]]
    assert sorted(done) == list(range(8))  # 每一次保存都真的成功了
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    index = data["model"].removeprefix("model-")  # 最终是完整一致的某一套，不是拼起来的
    assert (data["api_key"], data["model"]) == (f"sk-{index}", f"model-{index}")
    assert not settings_file.with_name(settings_file.name + ".tmp").exists()


def test_write_failure_keeps_the_previous_file_and_cleans_up(settings_file, env_defaults, monkeypatch):
    """替换那一步失败（磁盘满、被占用）：原来那套必须原样还在，临时文件也不许留下。"""
    model_config.save("https://old.example/v1", "sk-old", "old-model")
    before = settings_file.read_text(encoding="utf-8")

    def boom(source, target):
        raise OSError("磁盘已满")

    monkeypatch.setattr(os, "replace", boom)  # model_config.os 就是这个模块
    with pytest.raises(OSError, match="磁盘已满"):
        model_config.save("https://new.example/v1", "sk-new", "new-model")
    assert settings_file.read_text(encoding="utf-8") == before
    assert not settings_file.with_name(settings_file.name + ".tmp").exists()


def test_save_narrows_permissions_of_a_pre_existing_tmp(settings_file, monkeypatch):
    """预存一个别人写得进去的 .tmp：创建参数不会把它收紧，必须再 chmod 一次。

    os.fchmod 在 Windows 上不存在，所以这里显式注入一个记录器——兼容分支本身也要被测到。
    """
    calls = []
    monkeypatch.setattr(os, "fchmod", lambda fd, mode: calls.append(mode), raising=False)
    temporary = settings_file.with_name(settings_file.name + ".tmp")
    temporary.write_text("旧的宽权限临时文件", encoding="utf-8")
    model_config.save("", "sk-file", "file-model")
    assert calls and calls[0] == 0o600
    assert not temporary.exists()


def test_write_stream_failure_leaves_no_file_and_no_tmp(settings_file, monkeypatch):
    """写流本身失败（磁盘满）：异常照抛，正式文件与临时文件都不该留下半成品。"""
    def boom(payload, stream, **kwargs):
        stream.write('{"api_key": "sk-hal')
        raise OSError("磁盘已满")

    monkeypatch.setattr(model_config.json, "dump", boom)
    with pytest.raises(OSError, match="磁盘已满"):
        model_config.save("", "sk-file", "file-model")
    assert not settings_file.exists()
    assert not settings_file.with_name(settings_file.name + ".tmp").exists()


def test_clear_waits_for_an_in_progress_save(settings_file, monkeypatch):
    """删除与替换共用一把锁：否则删掉之后那次 replace 又会把配置写回来。

    两个任务都通过 future.result() 收结果：线程里的异常会重新抛到主测试里。
    release 放在 finally：断言失败也不会把保存线程永远卡在临界区里。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    model_config.save("", "sk-old", "old-model")
    inside, release = threading.Event(), threading.Event()
    real_replace = os.replace

    def blocked_replace(source, target):
        inside.set()
        release.wait(5)  # 最多等 5 秒，卡死也不会挂住整个测试
        real_replace(source, target)

    monkeypatch.setattr(model_config.os, "replace", blocked_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            saver = pool.submit(model_config.save, "", "sk-new", "new-model")
            assert inside.wait(5), "保存没有进入替换阶段"
            clearer = pool.submit(model_config.clear)
            time.sleep(0.3)  # 给 clear 一点时间：它应该卡在锁上而不是删掉文件
            assert not clearer.done(), "clear 没有等保存退出临界区"
        finally:
            release.set()
        saver.result(10)
        assert clearer.result(10) is True
    assert not settings_file.exists()  # 后发生的 clear 生效，顺序确定


# ---------------------------------------------------------------- 校验
@pytest.mark.parametrize("base_url, api_key, model, expect_ok", [
    ("", "sk-1", "m", True),
    ("https://relay.example/v1", "sk-1", "m", True),
    ("http://127.0.0.1:8080/v1", "sk-1", "m", True),
    ("", "", "m", False),
    ("", "sk-1", "  ", False),
    ("ftp://relay.example", "sk-1", "m", False),
    ("relay.example/v1", "sk-1", "m", False),
    ("https://", "sk-1", "m", False),
    ("https://x/v1", "k" * 501, "m", False),
    ("https://x/v1", "sk-1", "m" * 501, False),
    # Base URL 本身超长：地址合法，只靠长度上限拦下（漏掉这条会允许误粘贴整段内容）
    ("https://x/" + "a" * 500, "sk-1", "m", False),
])
def test_validate(base_url, api_key, model, expect_ok):
    error = model_config.validate(base_url, api_key, model)
    assert (error is None) is expect_ok, error


# ---------------------------------------------------------------- 试连
class FakeChatOpenAI:
    """替身：记录构造参数，invoke 时按预设结果返回或抛错。"""

    calls = []
    error = None

    def __init__(self, **kwargs):
        FakeChatOpenAI.calls.append(kwargs)

    def invoke(self, messages):
        if FakeChatOpenAI.error:
            raise FakeChatOpenAI.error
        return "pong"


@pytest.fixture
def fake_llm(monkeypatch):
    import langchain_openai

    FakeChatOpenAI.calls, FakeChatOpenAI.error = [], None
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", FakeChatOpenAI)
    return FakeChatOpenAI


def test_connection_uses_the_same_client_and_reports_success(fake_llm):
    ok, detail = model_config.test_connection("https://relay.example/v1", "sk-1", "m")
    assert ok and detail == "连接正常"
    assert fake_llm.calls[0] == {  # 地址、密钥、模型名三者都传给了客户端
        "model": "m", "api_key": "sk-1", "base_url": "https://relay.example/v1",
        "temperature": 0, "timeout": 20.0, "max_retries": 0,
    }


def test_connection_uses_the_official_url_for_empty_base_url(fake_llm):
    """留空 = 官方接口。传 None 会让客户端回读 OPENAI_BASE_URL，把新 Key 发到旧代理。"""
    model_config.test_connection("", "sk-1", "m")
    assert fake_llm.calls[0]["base_url"] == "https://api.openai.com/v1"


# ---------------------------------------------------------------- 真实目的地址
@pytest.fixture
def captured_requests(monkeypatch):
    """用真实客户端 + 无网络 MockTransport：看请求实际发到哪个地址。

    同时把环境里的代理地址和官方地址都设成"陷阱"：只有显式解析出的地址才该被命中。
    """
    import httpx
    import langchain_openai

    monkeypatch.setenv("OPENAI_BASE_URL", "https://env-leak.example/v1")
    monkeypatch.setenv("OPENAI_API_BASE", "https://env-leak2.example/v1")
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={
            "id": "1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"},
                         "finish_reason": "stop"}]})

    real = langchain_openai.ChatOpenAI

    def factory(**kwargs):
        kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(handler))
        return real(**kwargs)

    monkeypatch.setattr(langchain_openai, "ChatOpenAI", factory)
    return seen


def test_connection_really_targets_the_official_url(captured_requests):
    ok, _ = model_config.test_connection("", "sk-new", "m")
    assert ok
    assert captured_requests == ["https://api.openai.com/v1/chat/completions"]


def test_connection_really_targets_the_configured_relay(captured_requests):
    ok, _ = model_config.test_connection("https://relay.example/v1", "sk-new", "m")
    assert ok
    assert captured_requests == ["https://relay.example/v1/chat/completions"]


def test_production_client_really_targets_the_official_url(captured_requests):
    """_get_llm 与试连共用同一条地址解析：生产路径同样不能落回环境里的代理。"""
    from agent import geosql

    settings = model_config.ModelSettings("", "sk-new", "m", "file")
    geosql._get_llm(settings).invoke("ping")
    assert captured_requests == ["https://api.openai.com/v1/chat/completions"]


def test_connection_hides_the_api_key_in_the_error(fake_llm):
    fake_llm.error = RuntimeError("401 Unauthorized: Bearer sk-secret-value 无效")
    ok, detail = model_config.test_connection("https://relay.example/v1", "sk-secret-value", "m")
    assert not ok
    assert "sk-secret-value" not in detail
    assert "***" in detail and "401" in detail


def test_redact_covers_both_layers_without_a_secret_argument(settings_file, env_defaults):
    """生产路径用 redact(text) 兜底：本地配置和 .env 里的 Key 都不能漏出去。"""
    model_config.save("", "sk-from-file", "file-model")
    text = "headers={Authorization: Bearer sk-from-file} env={sk-env}"
    cleaned = model_config.redact(text)
    assert "sk-from-file" not in cleaned and "sk-env" not in cleaned
    assert cleaned.count("***") == 2


def test_redact_keeps_text_without_the_key_intact():
    assert model_config.redact("普通报错", "sk-1") == "普通报错"


def test_redact_replaces_longer_keys_first():
    """同一份快照里有短 Key 和"以短 Key 开头"的长 Key 时，必须先换长的。

    反过来先换短的，长 Key 会被截成 "***" 加一截没抹掉的尾巴（"-long"）——那截尾巴
    本身已经是半个密钥了。
    """
    secrets = ("sk-short", "sk-short-long")  # 故意按"短的在前"传进去
    assert model_config.redact("Bearer sk-short-long", secrets) == "Bearer ***"


def test_key_snapshot_dedupes_and_orders_longest_first(settings_file, env_defaults):
    model_config.save("", "sk-file-long", "file-model")
    snapshot = model_config.key_snapshot("sk-env", "sk-file-long", "")
    assert snapshot == ("sk-file-long", "sk-env")  # 去重、丢掉空串、长的在前


# ---------------------------------------------------------------- 生产路径脱敏
class _TwoTurnLLM:
    """第一轮点名调用一个工具，第二轮给最终回答；记录每轮看到的完整消息列表。"""

    def __init__(self, tool_name):
        self.tool_name = tool_name
        self.seen = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage

        self.seen.append(list(messages))
        if len(self.seen) == 1:
            return AIMessage(content="", tool_calls=[
                {"name": self.tool_name, "args": {}, "id": "call-1"}])
        return AIMessage(content="已根据工具结果作答。")


def test_tool_exception_output_is_redacted_everywhere(env_defaults, monkeypatch):
    """工具抛异常：事件、会话记录、喂回模型的内容三个出口都不能带密钥。"""
    from langchain_core.messages import ToolMessage

    from agent import react

    monkeypatch.setattr(config, "OPENAI_API_KEY", "synthetic-old-key")

    class BadTool:
        name = "query_database"

        def invoke(self, args):
            raise RuntimeError("502 Bad Gateway, headers={'Authorization': 'Bearer synthetic-old-key'}")

    llm = _TwoTurnLLM("query_database")
    monkeypatch.setattr(react, "ALL_TOOLS", [BadTool()])
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: llm)
    events = list(react.stream("有多少起事件？"))

    output = next(event["output"] for event in events if event["type"] == "tool_end")
    assert "synthetic-old-key" not in output and "502" in output  # 报错本身保留，只抹密钥
    records = events[-1]["result"].tool_records
    assert "synthetic-old-key" not in records[0]["output"]
    fed_back = [m for m in llm.seen[1] if isinstance(m, ToolMessage)]
    assert "synthetic-old-key" not in fed_back[0].content


def test_tool_reported_failure_text_is_redacted_everywhere(env_defaults, monkeypatch):
    """工具自己捕获异常后返回的"查询失败：…"同样会展示、入库、再喂给模型。

    agent/tools.py 的 query_database / knowledge_search 正是这样做的：不抛异常，
    而是把底层报错拼成字符串返回。只脱敏抛异常支路会漏掉这条。
    """
    from langchain_core.messages import ToolMessage

    from agent import react

    monkeypatch.setattr(config, "OPENAI_API_KEY", "synthetic-old-key")

    class FailingTool:
        name = "query_database"

        def invoke(self, args):
            return "查询失败：Authorization: Bearer synthetic-old-key"

    llm = _TwoTurnLLM("query_database")
    monkeypatch.setattr(react, "ALL_TOOLS", [FailingTool()])
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: llm)
    events = list(react.stream("有多少起事件？"))

    end = next(event for event in events if event["type"] == "tool_end")
    assert "synthetic-old-key" not in end["output"] and "查询失败" in end["output"]
    result = events[-1]["result"]
    assert result.tool_records[0]["output"] == end["output"]
    fed_back = [m for m in llm.seen[1] if isinstance(m, ToolMessage)]
    assert "synthetic-old-key" not in fed_back[0].content


def test_artifact_error_is_redacted_too(env_defaults, monkeypatch):
    """产物校验失败的错误串也是一个出口（事件里单独一项 artifact_error）。"""
    from agent import artifacts, react

    monkeypatch.setattr(config, "OPENAI_API_KEY", "synthetic-old-key")

    class MapTool:
        name = "buffer_analysis"

        def invoke(self, args):
            return "缓冲区完成。GeoJSON 已保存：/tmp/x.geojson"

    def fail(path):
        raise artifacts.ArtifactError("地图文件不可用：synthetic-old-key")

    monkeypatch.setattr(react, "ALL_TOOLS", [MapTool()])
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("buffer_analysis"))
    monkeypatch.setattr(artifacts, "validated_path", fail)
    events = list(react.stream("曼德海峡周边 50 公里内的缓冲区分析"))
    end = next(event for event in events if event["type"] == "tool_end")
    assert "synthetic-old-key" not in end["output"]
    assert "synthetic-old-key" not in end["artifact_error"]
    assert "地图产物校验失败" in end["output"]


# ---------------------------------------------------------------- 本轮冻结
def test_frozen_settings_are_used_instead_of_a_newly_saved_one(settings_file, env_defaults, monkeypatch):
    """开跑后别的标签页换了 Key：本轮仍用冻结的那一份，报错按旧 Key 脱敏。"""
    from agent import db, geosql

    model_config.save("", "sk-old", "old-model")
    captured = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            raise AssertionError("模型调用失败时不该执行 SQL")

    def fake_llm(settings=None):
        captured.append(settings)

        class LLM:
            def invoke(self, messages):
                raise RuntimeError("401 Unauthorized: Bearer sk-old")

        return LLM()

    monkeypatch.setattr(geosql, "_get_llm", fake_llm)
    monkeypatch.setattr(db, "connect", lambda: FakeConnection())
    monkeypatch.setattr(db, "has_spatial", lambda _: False)
    monkeypatch.setattr(db, "describe_schema", lambda _: "表 t")

    with model_config.frozen() as (frozen_settings, _):
        model_config.save("", "sk-new", "new-model")  # 另一个标签页保存了新配置
        result = geosql.ask("有多少起事件？", verbose=False)

    assert frozen_settings.model == "old-model"
    assert captured[0].model == "old-model"  # 没有被新配置替换
    assert "sk-old" not in result.error  # 旧 Key 也必须被抹掉
    assert "401" in result.error


def test_query_database_tool_inherits_the_frozen_settings(settings_file, env_defaults, monkeypatch):
    """query_database 内部调用 geosql.ask 时不传 settings：必须继承本轮冻结的配置。"""
    from agent import db, geosql
    from agent.tools import query_database

    captured = []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            raise AssertionError("模型调用失败时不该执行 SQL")

    def fake_llm(settings=None):
        captured.append(settings)

        class LLM:
            def invoke(self, messages):
                raise RuntimeError("boom")

        return LLM()

    monkeypatch.setattr(geosql, "_get_llm", fake_llm)
    monkeypatch.setattr(db, "connect", lambda: FakeConnection())
    monkeypatch.setattr(db, "has_spatial", lambda _: False)
    monkeypatch.setattr(db, "describe_schema", lambda _: "表 t")

    with model_config.frozen():
        model_config.save("", "sk-new", "new-model")
        output = query_database.invoke({"question": "有多少起事件？"})

    assert captured[0].model == "env-model"  # 仍是开跑时 .env 那一套
    assert output.startswith("查询失败：")


def test_paused_stream_does_not_leak_its_frozen_settings_to_the_caller(
        settings_file, env_defaults, monkeypatch):
    """next() 之后调用方仍处在自己的上下文里：不能因为生成器暂停就被"冻结"住。

    旧实现把 with frozen() 直接写在生成器体里。ContextVar 按执行上下文隔离、不按生成器隔离，
    所以 yield 出去时调用方的 active() 看到的是这一轮的旧配置，另一轮也读不到新保存的配置。
    """
    from agent import react

    model_config.save("", "sk-a", "model-a")
    stream = react.stream("第一轮")
    first = next(stream)  # 拿到 thinking，生成器停在 with frozen() 里面
    assert first["type"] == "thinking"
    try:
        model_config.save("", "sk-b", "model-b")  # 另一个标签页保存
        assert model_config.active().model == "model-b"  # 调用方没有被冻住
        seen = []
        monkeypatch.setattr(react, "_get_llm", lambda settings=None: seen.append(settings.model) or _TwoTurnLLM("query_database"))
        list(react.stream("第二轮"))
        assert seen == ["model-b"]  # 另一轮读到的是最新配置
    finally:
        stream.close()


def test_two_interleaved_streams_keep_their_own_settings(settings_file, env_defaults, monkeypatch):
    """同一线程交替推进两轮：各自保持开跑时那一份，谁也不会覆盖谁。"""
    from agent import react

    seen = []

    class RecordingTool:
        name = "query_database"

        def invoke(self, args):
            seen.append(model_config.active().model)
            return "查询失败：boom"

    monkeypatch.setattr(react, "ALL_TOOLS", [RecordingTool()])
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))

    model_config.save("", "sk-a", "model-a")
    first = react.stream("第一轮")
    next(first)  # 冻结在 model-a
    model_config.save("", "sk-b", "model-b")
    second = react.stream("第二轮")
    next(second)  # 冻结在 model-b
    try:
        assert model_config.active().model == "model-b"  # 调用方始终读最新
        for _ in range(4):  # 交替推进：每轮走完工具调用并收尾
            for index, stream in enumerate((first, second)):
                try:
                    next(stream)
                except StopIteration:
                    pass
        assert seen == ["model-a", "model-b"]  # 工具各看各的，没有串
    finally:
        first.close()
        second.close()


def test_closing_a_stream_never_restores_stale_settings(settings_file, env_defaults, monkeypatch):
    """外层 frozen 先退出、内层 stream 后 close：不能把旧配置重新放回去。

    旧实现里 token.reset 发生在调用方上下文——close 晚于外层退出时，它会把已经过期的
    model-a 盖回去。渲染异常的 traceback 会一直持有生成器，这种事会真的发生。
    """
    from agent import react

    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))
    model_config.save("", "sk-a", "model-a")
    with model_config.frozen() as (outer, _):
        inner = react.stream("一轮")
        next(inner)
        assert outer.model == "model-a"
    model_config.save("", "sk-b", "model-b")
    inner.close()  # 在调用方上下文里关掉
    assert model_config.active().model == "model-b"  # 没有被 old reset 改回去


def test_abandoned_stream_leaves_no_residue(settings_file, env_defaults, monkeypatch):
    """消费者提前停止（异常/中断）：close 之后调用方上下文必须干净。"""
    from agent import react

    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))
    model_config.save("", "sk-a", "model-a")
    stream = react.stream("一轮")
    next(stream)
    stream.close()
    model_config.save("", "sk-b", "model-b")
    assert model_config.active().model == "model-b"


def test_closing_from_a_different_context_does_not_raise(settings_file, env_defaults, monkeypatch):
    """close 发生在另一个上下文里也不能抛"token created in a different Context"。

    渲染异常时生成器可能被持有到别处（另一个 with frozen 块里、或线程池）才关闭；
    token 的 reset 必须始终发生在设置它的那份上下文里。
    """
    from agent import react

    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))
    model_config.save("", "sk-a", "model-a")
    stream = react.stream("一轮")
    next(stream)
    with model_config.frozen(model_config.ModelSettings("", "sk-z", "model-z", "file")):
        stream.close()  # 另一层上下文里关：不能报错，也不能把 model-a 留在这里
        assert model_config.active().model == "model-z"
    assert model_config.active().model == "model-a"  # 外层 frozen 仍按自己的 token 恢复


def test_consumer_exception_mid_stream_closes_cleanly(settings_file, env_defaults, monkeypatch):
    """调用方在处理事件时自己抛了（渲染失败）：生成器随异常展开，上下文不留残留。"""
    from agent import react

    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))
    model_config.save("", "sk-a", "model-a")
    with pytest.raises(RuntimeError, match="渲染失败"):
        for _event in react.stream("一轮"):
            raise RuntimeError("渲染失败")
    model_config.save("", "sk-b", "model-b")
    assert model_config.active().model == "model-b"


def test_internal_failure_still_releases_the_frozen_context(settings_file, env_defaults, monkeypatch):
    """流内部抛异常（不是正常 return）：事件照常给出，上下文也要按时退出。"""
    from agent import react

    class ExplodingTool:
        name = "query_database"

        def invoke(self, args):
            raise RuntimeError("工具炸了")

    monkeypatch.setattr(react, "ALL_TOOLS", [ExplodingTool()])
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))
    model_config.save("", "sk-a", "model-a")
    events = list(react.stream("一轮"))
    assert events[-1]["type"] == "answer"
    model_config.save("", "sk-b", "model-b")
    assert model_config.active().model == "model-b"


def test_react_stream_freezes_settings_for_nested_tools(settings_file, env_defaults, monkeypatch):
    """react.stream 开跑后换配置：这一轮里工具看到的仍是开跑时那一份。

    query_database 内部调 geosql.ask 不传 settings，靠的就是这个冻结。
    """
    from agent import react

    model_config.save("", "sk-old", "old-model")
    seen = []

    class RecordingTool:
        name = "query_database"

        def invoke(self, args):
            model_config.save("", "sk-new", "new-model")  # 模拟另一个标签页在此期间保存
            seen.append(model_config.active().model)
            return "查询失败：boom"

    monkeypatch.setattr(react, "ALL_TOOLS", [RecordingTool()])
    monkeypatch.setattr(react, "_get_llm", lambda settings=None: _TwoTurnLLM("query_database"))
    list(react.stream("有多少起事件？"))
    assert seen == ["old-model"]
    assert model_config.active().model == "new-model"  # 出了这一轮照常读最新配置


def test_freezing_ends_with_the_run(settings_file, env_defaults):
    """frozen() 退出后恢复：下一轮分析照常读最新配置。"""
    model_config.save("", "sk-file", "file-model")
    with model_config.frozen() as (frozen_settings, _):
        model_config.save("", "sk-new", "new-model")
    assert frozen_settings.model == "file-model"
    assert model_config.active().model == "new-model"


def test_workspace_fallback_redacts_with_the_frozen_key(settings_file, env_defaults, tmp_path, monkeypatch):
    """工作台的兜底出口：stream 抛异常前另一个标签页换了 Key，报错里回显的是旧 Key。

    旧实现里 run_analysis 在 except 里才读配置，读到的是新 Key，旧 Key 原样写进会话库。
    """
    from agent import sessions

    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    model_config.save("", "synthetic-old-key", "old-model")

    def switching_stream(prompt, history=None, session_id=None):
        model_config.save("", "sk-new-key", "new-model")  # 另一个标签页在此期间保存
        if False:
            yield  # 让它成为生成器（实际在首次 next 时就抛错）
        raise RuntimeError("stream 中断：Authorization: Bearer synthetic-old-key")

    monkeypatch.setattr("agent.react.stream", switching_stream)
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    app.chat_input(key="geoagent_prompt").set_value("曼德海峡周边有哪些事件？").run()
    assert not app.exception
    app.run()  # 提交后会同次 rerun；重新读取稳定页面
    sid = app.session_state["current_session_id"]
    stored = sessions.load_messages(sid)
    assistant = next(message for message in stored if message["role"] == "assistant")
    assert "synthetic-old-key" not in assistant["error"]
    assert "***" in assistant["error"] and "stream 中断" in assistant["error"]
    assert "synthetic-old-key" not in app.session_state["agent_messages"][-1]["error"]


def test_frozen_settings_are_isolated_between_threads(env_defaults):
    """并发请求各用各的：一个线程冻结的配置不能被另一个线程读到。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    seen, barrier = {}, threading.Barrier(2, timeout=5)

    def run(name, settings):
        with model_config.frozen(settings):
            barrier.wait()
            seen[name] = model_config.active().model

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, "a", model_config.ModelSettings("", "sk-a", "model-a", "file"))
        second = pool.submit(run, "b", model_config.ModelSettings("", "sk-b", "model-b", "file"))
        first.result(10)
        second.result(10)
    assert seen == {"a": "model-a", "b": "model-b"}


# ---------------------------------------------------------------- 就绪检查
def test_check_llm_ready_accepts_a_prefetched_settings_object(monkeypatch):
    """_get_llm 已经取过 settings 了：传进来就不该再读一次文件。"""
    def boom(*args, **kwargs):
        raise AssertionError("不该再读一次配置")

    monkeypatch.setattr(model_config, "current", boom)
    config.check_llm_ready(model_config.ModelSettings("", "sk-file", "file-model", "file"))


def test_check_llm_ready_rejects_an_empty_key():
    with pytest.raises(RuntimeError, match="未配置 OPENAI_API_KEY"):
        config.check_llm_ready(model_config.ModelSettings("", "", "m", "env"))


def test_check_llm_ready_reads_the_merged_settings_when_not_given(settings_file, env_defaults):
    """不传参时以本地配置为准：文件里配了 Key，就不该再报"未配置"。"""
    model_config.save("", "sk-file", "file-model")
    config.check_llm_ready()  # 不抛异常即为通过


# ---------------------------------------------------------------- CLI 兜底出口
def test_cli_agent_fallback_redacts_with_the_frozen_key(settings_file, env_defaults, monkeypatch, capsys):
    """CLI 兜底：react.run 抛出的未预料异常，用本轮冻结的旧 Key 脱敏。

    旧实现只调 redact(text)，那会读"此刻"的配置——期间换了 Key 就漏掉旧 Key。
    """
    from agent import chat as chat_cli

    model_config.save("", "synthetic-old-key", "old-model")

    def switching_run(question, **kwargs):
        model_config.save("", "sk-new-key", "new-model")
        raise ValueError("boom: Authorization: Bearer synthetic-old-key")

    monkeypatch.setattr("agent.react.run", switching_run)
    code = chat_cli._run_agent("有多少起事件？")
    stderr = capsys.readouterr().err
    assert code == 2
    assert "synthetic-old-key" not in stderr
    assert "***" in stderr and "boom" in stderr


def test_geosql_initialization_failure_hides_the_key(settings_file, env_defaults, monkeypatch):
    """客户端初始化就失败时，异常里可能带着请求头：result.error 不能原样带出去。"""
    from agent import geosql

    model_config.save("", "synthetic-old-key", "old-model")

    def failing_get_llm(settings=None):
        raise ValueError("invalid api_key=synthetic-old-key")

    monkeypatch.setattr(geosql, "_get_llm", failing_get_llm)
    result = geosql.ask("有多少起事件？", verbose=False)
    assert not result.ok
    assert "synthetic-old-key" not in result.error
    assert "LLM 初始化失败" in result.error


def test_eval_keeps_one_settings_for_the_whole_batch(settings_file, env_defaults, monkeypatch, tmp_path, capsys):
    """一条评测跑很久，中途别的标签页换了模型：整批仍按开跑时那一套，报告也记那一套。"""
    from agent import db, eval as eval_mod

    model_config.save("", "sk-old", "old-model")
    seen = []

    def fake_ask(question, verbose=False, settings=None):
        seen.append(settings.model)
        if len(seen) == 1:
            model_config.save("", "sk-new", "new-model")  # 第一条用例跑完之后换了配置
        return eval_mod.geosql.GeoSQLResult(question=question, error="boom bearer=sk-old")

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            return type("Result", (), {"fetchall": lambda self: []})()

    monkeypatch.setattr(eval_mod.geosql, "ask", fake_ask)
    monkeypatch.setattr(db, "connect", lambda: FakeConnection())
    cases = [{"id": "q1", "tags": [], "question": "问题一", "gold_sql": "SELECT 1"},
             {"id": "q2", "tags": [], "question": "问题二", "gold_sql": "SELECT 1"}]
    details, summary = eval_mod.run_eval(cases)
    assert seen == ["old-model", "old-model"]  # 第二条没有被新配置换掉
    assert summary["model"] == "old-model"
    assert all("sk-old" not in case["error"] for case in details)
    out = tmp_path / "report.md"
    eval_mod.write_report(details, summary, out)
    assert "sk-old" not in out.read_text(encoding="utf-8")
    assert "old-model" in out.read_text(encoding="utf-8")


def test_cli_direct_fallback_redacts_with_the_frozen_key(settings_file, env_defaults, monkeypatch, capsys):
    from agent import chat as chat_cli

    model_config.save("", "synthetic-old-key", "old-model")

    def switching_ask(question, **kwargs):
        model_config.save("", "sk-new-key", "new-model")
        raise ValueError("boom: Authorization: Bearer synthetic-old-key")

    monkeypatch.setattr("agent.geosql.ask", switching_ask)
    args = type("Args", (), {"question": "有多少起事件？", "sql_only": False,
                             "csv": None, "max_rows": 20})()
    code = chat_cli._run_direct(args)
    stderr = capsys.readouterr().err
    assert code == 2
    assert "synthetic-old-key" not in stderr
    assert "***" in stderr


# ---------------------------------------------------------------- 触发器文案
def test_trigger_label_shows_model_and_file_source():
    from app.model_ui import trigger_label

    settings = model_config.ModelSettings("https://relay.example/v1", "sk-file", "gpt-6-luna", "file")
    assert trigger_label(settings) == "模型 · gpt-6-luna（本地配置）"


def test_trigger_label_shows_model_and_env_source():
    from app.model_ui import trigger_label

    settings = model_config.ModelSettings("", "sk-env", "deepseek-chat", "env")
    assert trigger_label(settings) == "模型 · deepseek-chat（.env）"


# ---------------------------------------------------------------- 界面
def _popovers(app):
    """侧栏的 popover 原型列表。

    AppTest 的公开访问器里没有 popover（本机 Streamlit 1.59 实测：AppTest 只有 button /
    text_input / markdown 等 30 余个 accessor），只能退到元素原型。全文件只此一处碰内部结构；
    文案本身由 test_trigger_label_* 直接测，这里只确认它确实渲染到了侧栏上。
    升级 Streamlit 时如果 proto 改字段，只需要改这一行。
    """
    return [element.proto.popover for element in app.get("popover")]


def _model_page(busy):
    """给 AppTest 用：只画侧栏这一块，才能在"分析中"状态下看控件是否都置灰。"""
    from app import model_ui

    model_ui.render(busy)


def test_all_controls_are_disabled_while_an_analysis_runs(env_defaults):
    """分析进行中三个控件都要置灰。

    popover 的 disabled 只灰触发器，已经展开的菜单体在前端保留，所以里面两个按钮各自也要置灰。
    只查目标按钮，不断言整页的按钮数量与顺序——那会因无关的界面改动而碎。
    """
    app = AppTest.from_function(_model_page, args=(True,), default_timeout=30).run()
    assert not app.exception
    (popover,) = _popovers(app)
    assert popover.disabled
    submit = next(button for button in app.button if "保存并测试" in button.label)
    reset = next(button for button in app.button if button.key == "reset_model")
    assert submit.disabled and reset.disabled


def _workspace(tmp_path, monkeypatch):
    from agent import sessions

    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    app = AppTest.from_file(str(PAGE), default_timeout=30).run()
    assert not app.exception
    return app


def _fill(app, base_url, api_key, model):
    app.text_input(key="model_base_url").set_value(base_url)
    app.text_input(key="model_api_key").set_value(api_key)
    app.text_input(key="model_model").set_value(model)
    return app


def _submit(app):
    return next(button for button in app.button if "保存并测试" in button.label).click().run()


def _trigger_labels(app):
    """侧栏触发器的文案；取值走 _popovers，同样是全文件唯一那处原型访问。"""
    return [popover.label for popover in _popovers(app)]


def test_sidebar_shows_current_model_and_prefills_the_form(settings_file, env_defaults, tmp_path, monkeypatch):
    app = _workspace(tmp_path, monkeypatch)
    assert app.text_input(key="model_api_key").value == "sk-env"
    assert app.text_input(key="model_model").value == "env-model"
    assert app.text_input(key="model_base_url").value == "https://env.example/v1"
    assert [label for label in _trigger_labels(app) if "模型 ·" in label] == ["模型 · env-model（.env）"]
    assert next(button for button in app.button if button.key == "reset_model").disabled  # 没有本地配置


def test_successful_save_writes_the_file(settings_file, env_defaults, tmp_path, monkeypatch, fake_llm):
    app = _workspace(tmp_path, monkeypatch)
    _fill(app, "https://relay.example/v1", "sk-file", "file-model")
    _submit(app)
    assert not app.exception
    assert model_config.current().model == "file-model"
    assert settings_file.is_file()
    # 来源标签要跟着变，否则看不出配置从哪来
    assert [label for label in _trigger_labels(app) if "模型 ·" in label] == ["模型 · file-model（本地配置）"]


def test_failed_connection_does_not_overwrite_the_working_settings(
        settings_file, env_defaults, tmp_path, monkeypatch, fake_llm):
    model_config.save("https://old.example/v1", "sk-old", "old-model")
    fake_llm.error = RuntimeError("连接超时")
    app = _workspace(tmp_path, monkeypatch)
    _fill(app, "https://relay.example/v1", "sk-new", "new-model")
    _submit(app)
    assert not app.exception
    assert any("连接失败" in error.value for error in app.error)
    assert model_config.current().model == "old-model"  # 原来那套还在


def test_failed_connection_does_not_create_a_first_config(
        settings_file, env_defaults, tmp_path, monkeypatch, fake_llm):
    """从没保存过、第一次就试连失败：不能凭空多出一个配置文件。"""
    fake_llm.error = RuntimeError("401 Unauthorized")
    app = _workspace(tmp_path, monkeypatch)
    _fill(app, "https://relay.example/v1", "sk-bad", "bad-model")
    _submit(app)
    assert not app.exception
    assert any("连接失败" in error.value for error in app.error)
    assert not settings_file.exists()


def test_disk_write_failure_is_reported_and_keeps_the_previous_file(
        settings_file, env_defaults, tmp_path, monkeypatch, fake_llm):
    """试连成功但写盘失败：界面要如实报错，且原来那套不能被写坏。"""
    model_config.save("https://old.example/v1", "sk-old", "old-model")
    before = settings_file.read_text(encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("磁盘已满")

    monkeypatch.setattr(model_config, "save", boom)  # 只换写盘这一步，试连照常成功
    app = _workspace(tmp_path, monkeypatch)
    _fill(app, "https://relay.example/v1", "sk-new", "new-model")
    _submit(app)
    assert not app.exception
    assert any("写不进去" in error.value for error in app.error)
    assert settings_file.read_text(encoding="utf-8") == before


def test_invalid_input_is_rejected_before_any_request(settings_file, env_defaults, tmp_path, monkeypatch, fake_llm):
    app = _workspace(tmp_path, monkeypatch)
    _fill(app, "relay.example/v1", "sk-file", "file-model")
    _submit(app)
    assert not app.exception
    assert any("Base URL" in error.value for error in app.error)
    assert fake_llm.calls == []  # 校验不过就不发请求
    assert not settings_file.exists()


def test_reset_button_restores_env_settings(settings_file, env_defaults, tmp_path, monkeypatch):
    model_config.save("https://relay.example/v1", "sk-file", "file-model")
    app = _workspace(tmp_path, monkeypatch)
    next(button for button in app.button if button.key == "reset_model").click().run()
    assert not app.exception
    assert not settings_file.exists()
    assert app.text_input(key="model_model").value == "env-model"


def test_reset_failure_is_reported_instead_of_silently_ignored(
        settings_file, env_defaults, tmp_path, monkeypatch):
    model_config.save("https://relay.example/v1", "sk-file", "file-model")
    monkeypatch.setattr(model_config, "clear", lambda: False)  # 模拟文件被别的程序占用
    app = _workspace(tmp_path, monkeypatch)
    next(button for button in app.button if button.key == "reset_model").click().run()
    assert not app.exception
    assert any("没能删掉" in error.value for error in app.error)
    assert app.text_input(key="model_model").value == "file-model"  # 输入框没被清空，还能再试
