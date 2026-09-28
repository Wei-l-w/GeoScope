"""会话持久化：对话记录存独立的 sessions.duckdb（M6）。

为什么不用主仓库 warehouse.duckdb：前端各页面用只读连接访问主仓库，
DuckDB 同进程内读写连接与只读连接指向同一文件会报配置冲突；
独立会话库彻底规避，且可按需单独备份/清理。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import duckdb

from . import config

DB_PATH = Path(os.environ.get("SESSIONS_DB_PATH", str(config.ROOT / "data" / "sessions.duckdb")))

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
    created_at   TIMESTAMP
);
"""


def _connect() -> duckdb.DuckDBPyConnection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(_DDL)
    return con


def create_session(title: str) -> str:
    sid = uuid.uuid4().hex[:12]
    with _connect() as con:
        con.execute(
            "INSERT INTO chat_sessions VALUES (?, ?, CURRENT_TIMESTAMP)",
            [sid, title.strip()[:60] or "未命名会话"],
        )
    return sid


def save_message(session_id: str, role: str, content: str,
                 steps: list | None = None, geojson: list | None = None) -> None:
    with _connect() as con:
        seq = con.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM chat_messages WHERE session_id = ?",
            [session_id],
        ).fetchone()[0]
        con.execute(
            "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            [session_id, seq, role, content,
             json.dumps(steps or [], ensure_ascii=False),
             json.dumps(geojson or [], ensure_ascii=False)],
        )


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
        rows = con.execute(
            "SELECT role, content, steps_json, geojson_json FROM chat_messages "
            "WHERE session_id = ? ORDER BY seq",
            [session_id],
        ).fetchall()
    return [
        {
            "role": role,
            "content": content,
            "steps": json.loads(steps or "[]"),
            "geojson": json.loads(geo or "[]"),
        }
        for role, content, steps, geo in rows
    ]


def delete_session(session_id: str) -> None:
    with _connect() as con:
        con.execute("DELETE FROM chat_messages WHERE session_id = ?", [session_id])
        con.execute("DELETE FROM chat_sessions WHERE session_id = ?", [session_id])
