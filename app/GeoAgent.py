"""GeoAgent 对话式空间分析页（M4）。

左栏对话：自然语言提问 -> ReAct Agent 调用工具 -> 回答 + 工具轨迹；
右栏地图：Agent 产出的 GeoJSON（缓冲区/事件点/航迹线）自动上图。
"""

import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ui, chat_ui, map_view  # noqa: E402

ui.setup("GeoAgent")
chat_ui.setup()
chat_ui.header()

EXAMPLE_QUESTIONS = [
    ("周边事件", "曼德海峡周边150公里内发生了多少起事件？按类型统计"),
    ("船舶航迹", "MMSI 668116204 最近30天走了什么路线？"),
    ("事件背景", "银河领袖号被劫持事件有什么背景？有哪些相关报道？"),
    ("冲突排名", "Goldstein 冲突最激烈的5个国家是哪些？"),
]

if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []  # [{role, content, steps, geojson}]
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# ---- 侧栏：历史会话（持久化于 data/sessions.duckdb）----
from agent import sessions as sessions_mod  # noqa: E402
from agent import conversation  # noqa: E402


def _clear_draft() -> None:
    st.session_state.geoagent_prompt = ""
    st.session_state.pop("_pending_question", None)


def _prefill_question(question: str) -> None:
    st.session_state.geoagent_prompt = question


def _memory_value(value) -> str:
    """将结构化条件转为侧栏可读文本，避免把存储元数据直接暴露出来。"""
    if isinstance(value, dict):
        labels = {
            "lat": "纬度", "lon": "经度", "start": "开始", "end": "结束",
            "risk_level_min": "最低风险等级", "domain": "领域",
            "target_class": "目标类别", "ship_type": "船型", "country": "国家",
            "event_type": "事件类型",
        }
        return "；".join(f"{labels.get(k, k)}：{_memory_value(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "、".join(_memory_value(item) for item in value)
    return str(value)


def _render_memory(session_id: str | None) -> None:
    """当前会话的记忆始终按会话 ID 读取，切换会话时不会沿用其他会话状态。"""
    memory = conversation.get_memory(session_id) if session_id else {}
    state = memory.get("state") or {}
    summary = memory.get("summary") or ""
    with st.expander("本会话记忆", expanded=False):
        st.caption("连续追问会参考近期对话、早期摘要和下列分析条件。新会话独立记忆。")
        fields = [
            ("mmsi", "船号 MMSI"), ("place", "地点"), ("coordinates", "坐标"),
            ("days", "最近天数"), ("time_range", "时间窗"),
            ("radius_km", "半径（公里）"), ("table", "数据表"), ("filters", "筛选条件"),
        ]
        visible = [(label, state[key]) for key, label in fields
                   if key in state and state[key] not in (None, "", {}, [])]
        if visible:
            for label, value in visible:
                st.markdown(f"**{label}**：{_memory_value(value)}")
        else:
            st.caption("暂无已记录的分析条件。")
        if summary:
            st.markdown("**早期对话摘要**")
            st.text(summary)
        else:
            st.caption("早期对话摘要：暂无；近期对话会直接用于连续追问。")
        st.caption("清空后不再将此前对话用于分析；聊天记录和已有地图仍保留。")
        if st.button("清空分析记忆", key="clear_analysis_memory", disabled=not session_id,
                     use_container_width=True):
            sessions_mod.clear_memory(session_id)
            st.rerun()

with st.sidebar:
    st.subheader("历史会话")
    if st.button("新会话", width="stretch", type="primary", icon=":material/add:"):
        st.session_state.agent_messages = []
        st.session_state.current_session_id = None
        st.session_state.session_picker = ""
        _clear_draft()
        st.rerun()
    past = sessions_mod.list_sessions()
    # 标题和消息数可能完全相同；用 ID 做选项值，避免字典覆盖导致会话丢失。
    past_map = {sid: f"{title}（{cnt}条 · {sid[-6:]}）" for sid, title, _, cnt in past}
    if past_map:
        chosen = st.selectbox("加载会话", [""] + list(past_map),
                              format_func=lambda sid: past_map.get(sid, "请选择会话"),
                              key="session_picker")
        if chosen and st.button("打开", use_container_width=True):
            sid = chosen
            st.session_state.agent_messages = sessions_mod.load_messages(sid)
            st.session_state.current_session_id = sid
            _clear_draft()
            st.rerun()
    _render_memory(st.session_state.current_session_id)
    if st.session_state.current_session_id:
        with st.expander("会话管理", expanded=False):
            st.caption("删除会同时移除本会话的聊天记录与记忆。")
            if st.button("删除当前会话", width="stretch", icon=":material/delete:"):
                sessions_mod.delete_session(st.session_state.current_session_id)
                st.session_state.agent_messages = []
                st.session_state.current_session_id = None
                _clear_draft()
                st.rerun()


latest_geojson = next(
    (m["geojson"] for m in reversed(st.session_state.agent_messages) if m.get("geojson")),
    [],
)


with st.container(key="geoagent_workspace"):
    chat_col, map_col = st.columns([1.1, 1], gap="medium")

    with map_col, st.container(key="geoagent_map"):
        chat_ui.panel_header("分析地图", "事件点、缓冲区与航迹会在这里更新", "空间视图")
        map_slot = st.empty()
        latest_error = next((m.get("error") for m in reversed(st.session_state.agent_messages) if m["role"] == "assistant"), None)
        rendered_map = map_view.render(map_slot, latest_geojson, last_error=latest_error)
        with st.container(key="geoagent_map_footer"):
            chat_ui.render_map_files(rendered_map.paths)

    with chat_col, st.container(key="geoagent_chat"):
        has_history = bool(st.session_state.agent_messages)
        chat_ui.panel_header("分析对话", "可以连续追问，或调整地点、时间和筛选条件",
                             f"{len(st.session_state.agent_messages)} 条消息" if has_history else "新会话")
        history_view = st.container(height=380, border=False, key="geoagent_history")
        with st.container(key="geoagent_composer"):
            question = st.chat_input("输入地点、船号或分析问题…", key="geoagent_prompt")
            st.caption("Enter 发送 · Shift+Enter 换行 · 示例问题可编辑后发送")

        with history_view:
            if not has_history and not (question and question.strip()):
                chat_ui.welcome()
                suggestions = st.columns(2, gap="small")
                for i, (label, question_text) in enumerate(EXAMPLE_QUESTIONS):
                    with suggestions[i % 2]:
                        st.button(label, key=f"geoagent_example_{i}", width="stretch",
                                  help=question_text, on_click=_prefill_question, args=(question_text,))
            for msg in st.session_state.agent_messages:
                chat_ui.render_message(msg)

        if question and question.strip():
            question = question.strip()
            st.session_state.agent_messages.append({"role": "user", "content": question})
            sid = st.session_state.current_session_id
            if not sid:
                sid = sessions_mod.create_session(question)
                st.session_state.current_session_id = sid
            user_seq = sessions_mod.save_message(sid, "user", question)

            with history_view:
                chat_ui.render_message({"role": "user", "content": question})
                with st.chat_message("assistant", avatar=":material/explore:"):
                    from agent import react

                    st.caption("GeoScope")
                    status = st.status("正在理解问题…", expanded=False)
                    steps, geojson_paths, tool_records = [], [], []
                    live_paths = list(latest_geojson)
                    answer, error, got_answer = "", None, False
                    try:
                        for ev in react.stream(question, session_id=sid):
                            if ev["type"] == "thinking":
                                status.update(label="正在整理分析…", state="running", expanded=False)
                            elif ev["type"] == "tool_start":
                                label = chat_ui.tool_label(ev["name"])
                                args_text = ", ".join(f"{k}={v!r}" for k, v in ev["args"].items())
                                steps.append(f"{ev['name']}({args_text})")
                                status.update(label=label + "…", state="running", expanded=False)
                                with status:
                                    st.caption(label + (" · 已阻止重复执行" if ev.get("blocked") else ""))
                                    st.code(json.dumps(ev["args"], ensure_ascii=False, indent=2), language="json")
                            elif ev["type"] == "tool_end":
                                with status:
                                    st.text(ev["output"][:1200])
                                if ev.get("geojson_path"):
                                    live_paths.append(ev["geojson_path"])
                                    map_view.render(map_slot, live_paths)
                            elif ev["type"] == "map_ready":
                                live_paths = list(ev["paths"])
                                map_view.render(map_slot, live_paths)
                            elif ev["type"] == "answer":
                                result = ev["result"]
                                answer = result.answer or result.error or "本轮没有生成回答，请重新提问。"
                                error = result.error or (None if result.answer else "本轮未返回有效回答")
                                geojson_paths = result.geojson_paths
                                tool_records = getattr(result, "tool_records", [])
                                got_answer = True
                    except Exception as exc:
                        error = f"分析中断：{type(exc).__name__}: {exc}"
                        answer = "本轮分析未完成。请稍后重试，或缩小查询范围。"
                    if not got_answer and not error:
                        error = "分析结束但没有返回最终回答"
                        answer = "本轮没有生成完整回答，请重新提问。"
                    status.update(label="分析未完成" if error else "分析完成",
                                  state="error" if error else "complete", expanded=False)
                    st.markdown(answer)
                    if error:
                        st.caption("本轮分析未完成，可调整问题后重试。")

            message = {"role": "assistant", "content": answer, "steps": steps,
                       "geojson": geojson_paths, "tool_records": tool_records, "error": error}
            st.session_state.agent_messages.append(message)
            conversation.record_assistant(sid, answer, steps, geojson_paths,
                                          tool_records=tool_records, error=error, reply_to_seq=user_seq)
            st.rerun()
