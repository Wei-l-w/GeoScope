"""会话持久化：对话记录存独立的 sessions.duckdb（M6）。

为什么不用主仓库 warehouse.duckdb：前端各页面用只读连接访问主仓库，
DuckDB 同进程内读写连接与只读连接指向同一文件会报配置冲突；
独立会话库彻底规避，且可按需单独备份/清理。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import duckdb

from . import config

DB_PATH = Path(os.environ.get("SESSIONS_DB_PATH", str(config.ROOT / "data" / "sessions.duckdb")))
# MAX(seq) + INSERT 必须在同一临界区和事务中，防止 Streamlit 多线程写出重复序号。
_DB_LOCK = threading.RLock()

_DDL = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id VARCHAR PRIMARY KEY,
    title      VARCHAR,
    created_at TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chat_messages (
    session_id   VARCHAR,
    seq          INTEGER,
    role         VARCHAR,      -- user / assistant
    content      VARCHAR,
    steps_json   VARCHAR,      -- JSON 数组：工具调用轨迹
    geojson_json VARCHAR,      -- JSON 数组：GeoJSON 文件路径
    created_at   TIMESTAMP,
    tool_records_json VARCHAR,
    error        VARCHAR,
    reply_to_seq INTEGER
);
CREATE TABLE IF NOT EXISTS chat_memory (
    session_id  VARCHAR PRIMARY KEY,
    memory_json VARCHAR,
    cutoff_seq  INTEGER DEFAULT 0
);
"""


@contextmanager
def memory_update_lock():
    """将记忆的读取、重建与保存作为一个同进程临界区。

    与所有持久化操作共用可重入锁，避免另一标签页清空记忆后，
    尚未完成的旧快照又被保存回来。锁内只做本地构建，不等待模型调用。
    """
    with _DB_LOCK:
        yield


@contextmanager
def _connect():
    """串行连接并原子提交；旧库只增列、增表，不改写已有聊天。"""
    with _DB_LOCK:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(str(DB_PATH))
        try:
            con.execute("BEGIN TRANSACTION")
            con.execute(_DDL)
            columns = {row[1] for row in con.execute("PRAGMA table_info('chat_messages')").fetchall()}
            if "tool_records_json" not in columns:
                con.execute("ALTER TABLE chat_messages ADD COLUMN tool_records_json VARCHAR")
            if "error" not in columns:
                con.execute("ALTER TABLE chat_messages ADD COLUMN error VARCHAR")
            if "reply_to_seq" not in columns:
                con.execute("ALTER TABLE chat_messages ADD COLUMN reply_to_seq INTEGER")
            yield con
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        finally:
            con.close()


def _require_session(con: duckdb.DuckDBPyConnection, session_id: str) -> None:
    if not con.execute(
        "SELECT 1 FROM chat_sessions WHERE session_id = ?", [session_id]
    ).fetchone():
        raise ValueError(f"会话不存在：{session_id}")


def create_session(title: str) -> str:
    sid = uuid.uuid4().hex[:12]
    with _connect() as con:
        con.execute(
            "INSERT INTO chat_sessions (session_id, title, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            [sid, title.strip()[:60] or "未命名会话"],
        )
    return sid


def save_message(session_id: str, role: str, content: str,
                 steps: list | None = None, geojson: list | None = None,
                 tool_records: list | None = None, error: str | None = None,
                 reply_to_seq: int | None = None) -> int:
    """保存消息并返回序号；旧调用方可继续忽略返回值。"""
    with _connect() as con:
        _require_session(con, session_id)
        seq = con.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM chat_messages WHERE session_id = ?",
            [session_id],
        ).fetchone()[0]
        if reply_to_seq is not None:
            if (role != "assistant" or not isinstance(reply_to_seq, int)
                    or isinstance(reply_to_seq, bool) or not 0 < reply_to_seq < seq):
                raise ValueError("回复关联必须指向本会话中较早的用户消息")
            if not con.execute(
                "SELECT 1 FROM chat_messages WHERE session_id = ? AND seq = ? AND role = 'user'",
                [session_id, reply_to_seq],
            ).fetchone():
                raise ValueError("回复关联必须指向本会话中较早的用户消息")
        con.execute(
            "INSERT INTO chat_messages "
            "(session_id, seq, role, content, steps_json, geojson_json, created_at, tool_records_json, error, reply_to_seq) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)",
            [session_id, seq, role, content,
             json.dumps(steps or [], ensure_ascii=False),
             json.dumps(geojson or [], ensure_ascii=False),
             json.dumps(tool_records or [], ensure_ascii=False), error, reply_to_seq],
        )
    return seq


def list_sessions(limit: int = 50) -> list[tuple]:
    """[(session_id, title, created_at, msg_count)]，按最新消息排序。"""
    if not DB_PATH.exists():
        return []
    with _connect() as con:
        return con.execute(
            """
            SELECT s.session_id, s.title, s.created_at, COUNT(m.seq) AS msg_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m USING (session_id)
            GROUP BY s.session_id, s.title, s.created_at
            ORDER BY MAX(m.created_at) DESC NULLS LAST
            LIMIT ?
            """,
            [limit],
        ).fetchall()


def load_messages(session_id: str) -> list[dict]:
    """按 seq 还原某会话的全部消息（结构与页面 session_state 一致）。"""
    with _connect() as con:
        return _load_messages(con, session_id)


def _load_messages(con: duckdb.DuckDBPyConnection, session_id: str, cutoff: int = 0) -> list[dict]:
    rows = con.execute(
        "SELECT seq, role, content, steps_json, geojson_json, tool_records_json, error, reply_to_seq "
        "FROM chat_messages WHERE session_id = ? AND seq > ? ORDER BY seq",
        [session_id, cutoff],
    ).fetchall()
    return [
        {
            "seq": seq,
            "role": role,
            "content": content,
            "steps": json.loads(steps or "[]"),
            "geojson": json.loads(geo or "[]"),
            "tool_records": json.loads(records or "[]"),
            "error": error,
            "reply_to_seq": reply_to_seq,
        }
        for seq, role, content, steps, geo, records, error, reply_to_seq in rows
    ]


def load_memory(session_id: str) -> dict | None:
    """读取本会话记忆；新建、清空或不存在的会话返回 None。"""
    with _connect() as con:
        row = con.execute(
            "SELECT memory_json FROM chat_memory WHERE session_id = ?", [session_id]
        ).fetchone()
    return json.loads(row[0]) if row and row[0] is not None else None


def save_memory(session_id: str, payload: dict) -> None:
    """保存记忆快照，保留用户此前清空记忆时设定的边界。"""
    if not isinstance(payload, dict):
        raise TypeError("记忆内容必须为字典")
    memory_json = json.dumps(payload, ensure_ascii=False)
    with _connect() as con:
        _require_session(con, session_id)
        con.execute(
            "INSERT INTO chat_memory (session_id, memory_json, cutoff_seq) VALUES (?, ?, 0) "
            "ON CONFLICT (session_id) DO UPDATE SET memory_json = excluded.memory_json",
            [session_id, memory_json],
        )


def clear_memory(session_id: str) -> None:
    """清空记忆但保留可见聊天；旧消息永远不再进入该会话的记忆上下文。"""
    with _connect() as con:
        _require_session(con, session_id)
        cutoff = con.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM chat_messages WHERE session_id = ?", [session_id]
        ).fetchone()[0]
        con.execute(
            "INSERT INTO chat_memory (session_id, memory_json, cutoff_seq) VALUES (?, NULL, ?) "
            "ON CONFLICT (session_id) DO UPDATE SET memory_json = NULL, cutoff_seq = excluded.cutoff_seq",
            [session_id, cutoff],
        )


def memory_messages(session_id: str) -> list[dict]:
    """只读取最近一次清空之后的消息，供近期历史、摘要与状态构建使用。"""
    with _connect() as con:
        row = con.execute(
            "SELECT cutoff_seq FROM chat_memory WHERE session_id = ?", [session_id]
        ).fetchone()
        cutoff = int(row[0] or 0) if row else 0
        return [
            message for message in _load_messages(con, session_id, cutoff)
            if not (
                message["role"] == "assistant"
                and message["reply_to_seq"] is not None
                and message["reply_to_seq"] <= cutoff
            )
        ]


def delete_session(session_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM chat_memory WHERE session_id = ?", [session_id])
        con.execute("DELETE FROM chat_messages WHERE session_id = ?", [session_id])
        con.execute("DELETE FROM chat_sessions WHERE session_id = ?", [session_id])
