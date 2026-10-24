"""对话记忆持久化回归：只使用 pytest 临时库，不访问真实会话库。"""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import duckdb
import pytest

from agent import sessions


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    return sessions


def test_migrate_old_database_without_changing_messages(store):
    with duckdb.connect(str(store.DB_PATH)) as con:
        con.execute("CREATE TABLE chat_sessions (session_id VARCHAR PRIMARY KEY, title VARCHAR, created_at TIMESTAMP)")
        con.execute("CREATE TABLE chat_messages (session_id VARCHAR, seq INTEGER, role VARCHAR, content VARCHAR, steps_json VARCHAR, geojson_json VARCHAR, created_at TIMESTAMP)")
        con.execute("INSERT INTO chat_sessions VALUES ('old', '旧会话', '2026-10-01 09:00:00')")
        con.execute("INSERT INTO chat_messages VALUES ('old', 1, 'assistant', '已有回答', '[\"查询\"]', '[\"a.geojson\"]', '2026-10-01 09:01:00')")
        before = con.execute("SELECT * FROM chat_messages").fetchall()

    message = store.load_messages("old")[0]
    assert message == {
        "seq": 1, "role": "assistant", "content": "已有回答", "steps": ["查询"],
        "geojson": ["a.geojson"], "tool_records": [], "error": None, "reply_to_seq": None,
    }
    assert store.load_memory("old") is None
    with duckdb.connect(str(store.DB_PATH)) as con:
        after = con.execute("SELECT session_id, seq, role, content, steps_json, geojson_json, created_at FROM chat_messages").fetchall()
        assert after == before
        assert {r[1] for r in con.execute("PRAGMA table_info('chat_messages')").fetchall()} >= {"tool_records_json", "error", "reply_to_seq"}
    assert store.save_message("old", "user", "接着查") == 2
    assert len(store.load_messages("old")) == 2


def test_memory_and_tool_records_survive_connection_reopen(store):
    sid = store.create_session("船舶分析")
    records = [{"tool": "ship_track", "args": {"mmsi": 413123456, "days": 7}, "output": "已上图"}]
    assert store.save_message(sid, "assistant", "航迹", ["查询"], ["track.geojson"], records) == 1
    store.save_memory(sid, {"version": 1, "summary": "调查船舶", "state": {"mmsi": 413123456}})
    # 每个公开操作都关闭连接；直接重开库验证 JSON 是落盘数据。
    with duckdb.connect(str(store.DB_PATH)) as con:
        persisted = json.loads(con.execute("SELECT memory_json FROM chat_memory WHERE session_id = ?", [sid]).fetchone()[0])
    assert persisted == store.load_memory(sid)
    assert store.load_messages(sid)[0]["tool_records"] == records
    assert store.memory_messages(sid) == store.load_messages(sid)


def test_sessions_keep_memory_and_messages_isolated(store):
    first, second = store.create_session("一"), store.create_session("二")
    store.save_message(first, "user", "第一艘船")
    store.save_memory(first, {"summary": "只属于第一会话"})
    assert store.load_memory(second) is None
    assert store.memory_messages(second) == []
    store.save_message(second, "user", "另一艘船")
    store.save_memory(second, {"summary": "只属于第二会话"})
    assert store.load_memory(first) == {"summary": "只属于第一会话"}
    assert [m["content"] for m in store.memory_messages(second)] == ["另一艘船"]


def test_clear_keeps_display_history_but_never_reinjects_old_messages(store):
    sid = store.create_session("清空记忆")
    store.save_message(sid, "user", "旧船号")
    store.save_message(sid, "assistant", "旧结论")
    store.save_memory(sid, {"summary": "旧结论"})
    store.clear_memory(sid)
    assert store.load_memory(sid) is None
    assert len(store.load_messages(sid)) == 2
    assert store.memory_messages(sid) == []
    assert store.save_message(sid, "user", "新船号") == 3
    store.save_memory(sid, {"summary": "新分析"})
    assert [m["seq"] for m in store.memory_messages(sid)] == [3]
    assert len(store.load_messages(sid)) == 3
    with duckdb.connect(str(store.DB_PATH)) as con:
        assert con.execute("SELECT cutoff_seq FROM chat_memory WHERE session_id = ?", [sid]).fetchone()[0] == 2
    store.clear_memory(sid)
    assert store.memory_messages(sid) == []
    assert store.save_message(sid, "assistant", "第三段对话", error="工具不可用") == 4
    assert store.memory_messages(sid)[0]["error"] == "工具不可用"


def test_clear_empty_session_does_not_block_future_messages(store):
    sid = store.create_session("空会话")
    store.clear_memory(sid)
    store.save_message(sid, "user", "第一条消息")
    assert len(store.memory_messages(sid)) == 1


def test_delete_session_removes_memory_and_messages_only_for_that_session(store):
    target, other = store.create_session("删除"), store.create_session("保留")
    for sid in (target, other):
        store.save_message(sid, "user", sid)
        store.save_memory(sid, {"summary": sid})
    store.delete_session(target)
    store.delete_session(target)  # 兼容幂等删除。
    assert store.load_messages(target) == []
    assert store.load_memory(target) is None
    assert [s[0] for s in store.list_sessions()] == [other]
    assert store.load_memory(other) == {"summary": other}
    with duckdb.connect(str(store.DB_PATH)) as con:
        assert con.execute("SELECT COUNT(*) FROM chat_memory WHERE session_id = ?", [target]).fetchone()[0] == 0


def test_session_exists_tracks_creation_and_deletion(store, tmp_path):
    # 前端在"点开 / 恢复当前会话"之前先问一句，避免另一个标签页删掉后整页抛 ValueError
    absent = tmp_path / "nothing.duckdb"
    original = store.DB_PATH
    try:
        store.DB_PATH = absent
        assert store.session_exists("anything") is False  # 会话库还没建
        store.DB_PATH = original
        sid = store.create_session("存在的会话")
        assert store.session_exists(sid) is True
        assert store.session_exists("") is False
        store.delete_session(sid)
        assert store.session_exists(sid) is False
    finally:
        store.DB_PATH = original


@pytest.mark.parametrize("operation", [
    lambda store: store.save_message("missing", "user", "孤儿"),
    lambda store: store.save_memory("missing", {"summary": "孤儿"}),
    lambda store: store.clear_memory("missing"),
])
def test_writes_reject_unknown_session_without_orphans(store, operation):
    store.create_session("真实会话")
    with pytest.raises(ValueError, match="会话不存在"):
        operation(store)
    assert store.load_memory("missing") is None
    assert store.memory_messages("missing") == []
    with duckdb.connect(str(store.DB_PATH)) as con:
        assert con.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM chat_memory").fetchone()[0] == 0


def test_concurrent_message_saves_have_unique_contiguous_sequences(store):
    sid = store.create_session("并发会话")
    with ThreadPoolExecutor(max_workers=8) as executor:
        seqs = list(executor.map(lambda i: store.save_message(sid, "user", str(i)), range(24)))
    assert sorted(seqs) == list(range(1, 25))
    messages = store.load_messages(sid)
    assert [m["seq"] for m in messages] == list(range(1, 25))
    assert {m["content"] for m in messages} == {str(i) for i in range(24)}


def test_invalid_payload_does_not_replace_existing_memory(store):
    sid = store.create_session("参数校验")
    store.save_memory(sid, {"summary": "原记忆"})
    with pytest.raises(TypeError, match="字典"):
        store.save_memory(sid, [])
    assert store.load_memory(sid) == {"summary": "原记忆"}


def test_clear_waits_for_entire_memory_rebuild_without_reviving_old_snapshot(store):
    sid = store.create_session("并发清空")
    store.save_message(sid, "user", "待遗忘船号")
    snapshot_read, allow_save = Event(), Event()
    clear_started, clear_done = Event(), Event()
    operations = []

    def rebuild():
        with store.memory_update_lock():
            snapshot = store.memory_messages(sid)
            snapshot_read.set()
            assert allow_save.wait(timeout=5)
            store.save_memory(sid, {"summary": snapshot[0]["content"]})
            operations.append("saved")

    def clear():
        clear_started.set()
        store.clear_memory(sid)
        operations.append("cleared")
        clear_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        rebuilding = executor.submit(rebuild)
        try:
            assert snapshot_read.wait(timeout=5)
            clearing = executor.submit(clear)
            assert clear_started.wait(timeout=5)
            assert not clear_done.wait(timeout=0.1)
        finally:
            allow_save.set()
        rebuilding.result(timeout=5)
        clearing.result(timeout=5)
    assert operations == ["saved", "cleared"]
    assert store.load_memory(sid) is None
    assert store.memory_messages(sid) == []
    assert len(store.load_messages(sid)) == 1


def test_late_answer_to_cleared_user_stays_in_history_but_out_of_memory(store):
    sid = store.create_session("迟到回复")
    old_user = store.save_message(sid, "user", "旧船号")
    store.clear_memory(sid)
    new_user = store.save_message(sid, "user", "新船号")
    late_answer = store.save_message(sid, "assistant", "旧请求晚到", reply_to_seq=old_user)
    new_answer = store.save_message(sid, "assistant", "新请求回复", reply_to_seq=new_user)
    history = store.load_messages(sid)
    assert len(history) == 4
    assert history[2]["seq"] == late_answer
    assert history[2]["reply_to_seq"] == old_user
    assert [message["seq"] for message in store.memory_messages(sid)] == [new_user, new_answer]


@pytest.mark.parametrize("reply_to_seq", [0, -1, 2, 3, 99, True, "1"])
def test_reply_reference_requires_earlier_user_in_same_session(store, reply_to_seq):
    sid, other = store.create_session("当前会话"), store.create_session("其他会话")
    store.save_message(sid, "user", "当前用户消息")
    store.save_message(sid, "assistant", "助手消息")
    store.save_message(other, "assistant", "占位")
    store.save_message(other, "user", "其他会话的用户序号 2 不得用于当前助手序号 2")
    store.save_message(other, "user", "仅存在其他会话的序号 3")
    with pytest.raises(ValueError, match="较早的用户消息"):
        store.save_message(sid, "assistant", "错误关联", reply_to_seq=reply_to_seq)
    assert len(store.load_messages(sid)) == 2
    assert store.save_message(sid, "assistant", "有效关联", reply_to_seq=1) == 3


def test_unlinked_legacy_assistant_remains_compatible_after_clear(store):
    sid = store.create_session("历史兼容")
    store.save_message(sid, "user", "清空前")
    store.clear_memory(sid)
    store.save_message(sid, "assistant", "旧调用方无关联回复")
    assert store.memory_messages(sid)[0]["reply_to_seq"] is None


def test_reply_reference_migration_from_intermediate_nine_column_schema(store):
    with duckdb.connect(str(store.DB_PATH)) as con:
        con.execute("CREATE TABLE chat_sessions (session_id VARCHAR PRIMARY KEY, title VARCHAR, created_at TIMESTAMP)")
        con.execute("CREATE TABLE chat_messages (session_id VARCHAR, seq INTEGER, role VARCHAR, content VARCHAR, steps_json VARCHAR, geojson_json VARCHAR, created_at TIMESTAMP, tool_records_json VARCHAR, error VARCHAR)")
        con.execute("INSERT INTO chat_sessions VALUES ('middle', '中间版本', CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO chat_messages VALUES ('middle', 1, 'user', '已有问题', '[]', '[]', CURRENT_TIMESTAMP, '[]', NULL)")
        before = con.execute("SELECT * FROM chat_messages").fetchall()
    assert store.load_messages("middle")[0]["reply_to_seq"] is None
    with duckdb.connect(str(store.DB_PATH)) as con:
        after = con.execute("SELECT session_id, seq, role, content, steps_json, geojson_json, created_at, tool_records_json, error FROM chat_messages").fetchall()
    assert after == before
    store.save_message("middle", "assistant", "新回复", reply_to_seq=1)
    assert store.load_messages("middle")[1]["reply_to_seq"] == 1
