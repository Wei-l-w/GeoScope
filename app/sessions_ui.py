"""工作台侧栏：新建分析、最近会话（点一下即打开）、本会话记忆卡片。"""

from __future__ import annotations

import html

import streamlit as st

from agent import conversation
from agent import sessions as sessions_mod
from app import model_ui

PROMPT_KEY = "geoagent_prompt"
MEMORY_FIELDS = [
    ("mmsi", "船号 MMSI"), ("place", "地点"), ("coordinates", "坐标"), ("days", "最近天数"),
    ("time_range", "时间窗"), ("radius_km", "半径（公里）"), ("table", "数据表"), ("filters", "筛选条件"),
]
VALUE_LABELS = {
    "lat": "纬度", "lon": "经度", "start": "开始", "end": "结束", "risk_level_min": "最低风险等级",
    "domain": "领域", "target_class": "目标类别", "ship_type": "船型", "country": "国家", "event_type": "事件类型",
}


def memory_value(value) -> str:
    """把结构化条件转成可读文本，避免把存储元数据直接暴露出来。"""
    if isinstance(value, dict):
        return "；".join(f"{VALUE_LABELS.get(k, k)}：{memory_value(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "、".join(memory_value(item) for item in value)
    return str(value)


def clear_draft() -> None:
    st.session_state[PROMPT_KEY] = ""
    st.session_state.pop("_pending_question", None)


def start_new() -> None:
    st.session_state.agent_messages = []
    st.session_state.current_session_id = None
    clear_draft()


def session_exists(sid: str | None) -> bool:
    """另一个标签页可能刚把它删掉：打开、清空记忆、提问之前先问一句。
    list_sessions 默认只取最近 50 个，要传 limit=None 才查得到最早的会话：DuckDB 的 LIMIT NULL 即不限，
    1.0–1.5 都如此；不能用 sys.maxsize，DuckDB 1.1 的 LIMIT 上限是 2**62，会直接报错。
    会话库还没建时它返回空列表，这里即为 False。"""
    return bool(sid) and any(row[0] == sid for row in sessions_mod.list_sessions(limit=None))


def open_session(sid: str) -> None:
    if not session_exists(sid):  # 另一个标签页刚删掉它：当作新会话，别让页面红屏
        start_new()
        return
    st.session_state.agent_messages = sessions_mod.load_messages(sid)
    st.session_state.current_session_id = sid
    clear_draft()


def delete_current(sid: str) -> None:
    sessions_mod.delete_session(sid)
    start_new()


def _clear_memory(sid: str) -> None:
    if session_exists(sid):
        sessions_mod.clear_memory(sid)


def render(busy: bool) -> dict:
    """渲染侧栏并返回 {会话 id: 标题}，供对话标题栏使用。"""
    current = st.session_state.get("current_session_id")
    titles = {}
    with st.sidebar:
        st.button("新建分析", key="new_analysis", type="primary", icon=":material/add:", width="stretch",
                  disabled=busy, on_click=start_new)
        st.caption("最近会话")
        with st.container(height=320, border=False, key="session_list"):
            past = sessions_mod.list_sessions()
            if not past:
                st.caption("还没有历史会话")
            for sid, title, created, count in past:
                titles[sid] = title or "未命名会话"
                when = created.strftime("%Y-%m-%d %H:%M") if created else ""
                st.button(titles[sid], key=f"session_{sid}", type="secondary" if sid == current else "tertiary",
                          width="stretch", disabled=busy, help=f"{count} 条消息 · 创建于 {when}",
                          on_click=open_session, args=(sid,))
        render_memory(current, busy)
        model_ui.render(busy)
    return titles


def render_memory(sid: str | None, busy: bool) -> None:
    """会话记忆始终按会话 ID 读取，切换会话时不会沿用其他会话的状态。"""
    try:
        memory = conversation.get_memory(sid) if sid else {}
    except ValueError as exc:
        if sid and not session_exists(sid):
            # 另一个标签页刚删掉当前会话：退回空的新会话，别让整页红屏。草稿留在输入框里。
            st.session_state.agent_messages = []
            st.session_state.current_session_id = None
            sid, memory = None, {}
        else:
            # 记忆内容损坏（旧版本数据、手工改库）不等于会话消失：聊天记录还在，不能静默踢回空会话
            st.error(f"本会话的记忆无法读取，暂时按空记忆继续：{exc}")
            memory = {}
    state = memory.get("state") or {}
    summary = memory.get("summary") or ""
    with st.container(border=True, key="memory_card"):
        st.markdown('<div class="gs-card-t">本会话记忆</div>', unsafe_allow_html=True)
        visible = [(label, state[key]) for key, label in MEMORY_FIELDS
                   if key in state and state[key] not in (None, "", {}, [])]
        if visible:
            chips = "".join(f'<span class="gs-chip"><em>{html.escape(label)}</em>{html.escape(memory_value(value))}</span>'
                            for label, value in visible)
            st.markdown(f'<div class="gs-chips">{chips}</div>', unsafe_allow_html=True)
        else:
            st.caption("暂无已记录的分析条件。新会话独立记忆。")
        if summary:
            with st.expander("早期对话摘要"):
                st.text(summary)
        else:
            st.caption("早期对话摘要：暂无")
        st.button("清空分析记忆", key="clear_analysis_memory", type="tertiary", icon=":material/delete_sweep:",
                  disabled=busy or not sid, on_click=_clear_memory, args=(sid,),
                  help="清空后不再将此前对话用于分析；聊天记录和已有地图仍保留。")
