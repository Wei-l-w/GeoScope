"""GeoAgent 工作台：左侧对话、右侧地图（设计文档第 6 节）。

渲染顺序是"防打断"的关键：先取得输入框的提交，再画侧栏和图层开关——本轮有提交时，
其余可交互控件全部置灰，避免点击触发重跑、中止正在进行的分析。
"""

from __future__ import annotations

import json

import streamlit as st

from agent import conversation
from agent import sessions as sessions_mod
from app import chat_ui, map_view, sessions_ui, theme_watch, ui

ui.setup("工作台", watch=False)
ui.inject_css("workspace.css")

st.session_state.setdefault("agent_messages", [])
st.session_state.setdefault("current_session_id", None)

with st.container(key="workspace"):
    chat_col, map_col = st.columns([5, 7], gap="medium")
with chat_col, st.container(key="chat_panel"):
    header_slot = st.container()
    history = st.container(height=520, border=False, autoscroll=True, key="chat_history")
    composer = st.container(key="chat_composer")
with map_col, st.container(key="map_panel"):
    bar_slot = st.container(key="map_bar")
    alerts = st.container()
    canvas = st.container(height=600, border=False, key="map_canvas")  # 增强样式 #8 生效时拉伸填满面板
    footer_slot = st.container()

with composer:
    question = st.chat_input("输入地点、船号或分析问题…", key=sessions_ui.PROMPT_KEY, submit_mode="disable")
    st.caption("Enter 发送 · Shift+Enter 换行")
question = (question or "").strip()
busy = bool(question)
mode = theme_watch.mode(busy=busy)

titles = sessions_ui.render(busy)
messages = st.session_state.agent_messages
sid = st.session_state.current_session_id

first_question = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
title = (titles.get(sid) or first_question or question or "新会话")[:60]
subtitle = "分析中…" if busy else (f"{len(messages)} 条消息" if messages else "还没有消息")
with header_slot:
    chat_ui.header(title, subtitle, sid, busy)

# 先算出图层，回答末尾的结果标签才能照抄图层按钮的名字（含"第 N 轮"）；只读数据，不出界面。
turn_paths = map_view.turns(messages)
state = map_view.build(turn_paths, map_view.reset_count())
labels = {(layer.turn, layer.path, layer.kind): layer.label for layer in state.layers}

interrupted = chat_ui.unanswered(messages)
with history:
    if not messages and not busy:
        chat_ui.welcome(busy)
    turn = 0
    for message in messages:
        if message.get("role") == "assistant":  # 与 map_view.turns() 同口径：助手回答的序号
            turn += 1
        chat_ui.render_message(message, mode, interrupted=message.get("seq") in interrupted, busy=busy,
                               labels=labels, turn=turn)

with bar_slot:
    visible = map_view.render_bar(state, sid, busy)
last_error = next((m.get("error") for m in reversed(messages) if m.get("role") == "assistant"), None)
with alerts:
    map_view.render_alerts(state, last_error)
with canvas:
    live_slot = st.empty() if busy else None
    map_view.render_map(state, visible, mode, slot=live_slot,
                        key="workspace_map_live_0" if busy else "workspace_map")
with footer_slot:
    map_view.render_footer(state, visible, mode)


def run_analysis(question: str, sid: str) -> dict:
    """流式执行一轮分析：状态行显示当前步骤，工具一产出 GeoJSON 就上图。"""
    from agent import react

    next_turn = sum(m.get("role") == "assistant" for m in messages) + 1
    live_paths, shown, updates = [], set(visible), 0
    steps, records, paths = [], [], []
    answer, error, got_answer = "", None, False
    with st.chat_message("assistant", avatar=chat_ui.ASSISTANT_AVATAR):
        status = st.status("正在理解问题…", expanded=False)
        done = st.empty()
        finished = []
        try:
            for event in react.stream(question, session_id=sid):
                if event["type"] == "thinking":
                    status.update(label="正在整理分析…", state="running")
                elif event["type"] == "tool_start":
                    label = chat_ui.tool_label(event["name"])
                    args_text = ", ".join(f"{k}={v!r}" for k, v in event["args"].items())
                    steps.append(f"{event['name']}({args_text})")
                    status.update(label=f"正在{label}…", state="running")
                    with status:
                        st.caption(label + (" · 已阻止重复执行" if event.get("blocked") else ""))
                        st.code(json.dumps(event["args"], ensure_ascii=False, indent=2), language="json")
                    finished.append(chat_ui.step_detail(event["name"], event["args"]))
                elif event["type"] == "tool_end":
                    with status:
                        st.text(event["output"][:1200])
                    done.caption("\n\n".join(f"✓ {line}" for line in finished))
                    if event.get("geojson_path"):
                        live_paths.append(event["geojson_path"])
                elif event["type"] == "map_ready":
                    live_paths = list(event["paths"])
                elif event["type"] == "answer":
                    result = event["result"]
                    answer = result.answer or result.error or "本轮没有生成回答，请重新提问。"
                    error = result.error or (None if result.answer else "本轮未返回有效回答")
                    paths = result.geojson_paths
                    records = getattr(result, "tool_records", [])
                    got_answer = True
                if event["type"] in ("tool_end", "map_ready") and live_paths:
                    live = map_view.build(turn_paths + [(next_turn, list(dict.fromkeys(live_paths)))])
                    shown |= {layer.id for layer in live.layers if layer.turn == next_turn}
                    updates += 1
                    map_view.render_map(live, shown, mode, slot=live_slot, key=f"workspace_map_live_{updates}")
        except Exception as exc:
            error = f"分析中断：{type(exc).__name__}: {exc}"
            answer = "本轮分析未完成。请稍后重试，或缩小查询范围。"
        if not got_answer and not error:
            error = "分析结束但没有返回最终回答"
            answer = "本轮没有生成完整回答，请重新提问。"
        # 已经产出、并且刚刚画到地图上的文件仍然属于本轮：工具成功之后才失败时，
        # 不能让用户刚看到的图层随回答一起消失，也不能让下载列表里查无此文件。
        paths = paths or list(dict.fromkeys(live_paths))
        status.update(label="分析未完成" if error else "分析完成", state="error" if error else "complete")
        st.markdown(answer)
    return {"role": "assistant", "content": answer, "steps": steps, "geojson": paths,
            "tool_records": records, "error": error}


if busy:
    if sid and not sessions_mod.session_exists(sid):
        # 另一个标签页在本次提交前删掉了这个会话：换新会话继续，别整页报错，也别丢用户的问题
        messages = st.session_state.agent_messages = []
        st.session_state.current_session_id = sid = None
    if not sid:
        sid = sessions_mod.create_session(question)
        st.session_state.current_session_id = sid
    user_seq = sessions_mod.save_message(sid, "user", question)
    messages.append({"role": "user", "content": question, "seq": user_seq})
    with history:
        chat_ui.render_message(messages[-1], mode, busy=True)
        reply = run_analysis(question, sid)
    reply["reply_to_seq"] = user_seq
    messages.append(reply)
    try:
        conversation.record_assistant(sid, reply["content"], reply["steps"], reply["geojson"],
                                      tool_records=reply["tool_records"], error=reply["error"],
                                      reply_to_seq=user_seq)
    except ValueError:
        if sessions_mod.session_exists(sid):
            raise  # 会话还在：是别的数据问题，不能当成"被删了"吞掉
        # 分析期间另一个标签页删掉了这个会话：回答已经生成并显示，但没有地方可存。
        # 停在当前这一帧，让用户还能读到回答；下一次交互会回到空的新会话。
        st.session_state.agent_messages = []
        st.session_state.current_session_id = None
        st.warning("本会话已在另一个标签页中被删除，本轮回答未能保存。")
        st.stop()
    st.rerun()
