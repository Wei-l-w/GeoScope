"""GeoAgent 对话式空间分析页（M4）。

左栏对话：自然语言提问 -> ReAct Agent 调用工具 -> 回答 + 工具轨迹；
右栏地图：Agent 产出的 GeoJSON（缓冲区/事件点/航迹线）自动上图。
"""

import json
import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import ui  # noqa: E402

ui.setup("GeoAgent")
ui.page_header(
    "GeoAgent 空间智能体",
    "自然语言驱动的空间分析：意图识别 → 工具调用 → GeoSQL → 地图渲染",
    chips=[("ReAct", ""), ("Text-to-GeoSQL", ""), ("RAG 知识库", ""), ("deck.gl", "")],
)

EXAMPLE_QUESTIONS = [
    "曼德海峡周边150公里内发生了多少起事件？按类型统计",
    "MMSI 668116204 最近30天走了什么路线？",
    "银河领袖号被劫持事件有什么背景？有哪些相关报道？",
    "Goldstein 冲突最激烈的5个国家是哪些？",
]

if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []  # [{role, content, steps, geojson}]
if "current_session_id" not in st.session_state:
    st.session_state.current_session_id = None

# ---- 侧栏：历史会话（持久化于 data/sessions.duckdb）----
from agent import sessions as sessions_mod  # noqa: E402

with st.sidebar:
    st.markdown("---")
    st.subheader("历史会话")
    col_new, col_del = st.columns(2)
    if col_new.button("新会话", use_container_width=True):
        st.session_state.agent_messages = []
        st.session_state.current_session_id = None
        st.rerun()
    past = sessions_mod.list_sessions()
    past_map = {f"{title}（{cnt}条）": sid for sid, title, _, cnt in past}
    if past_map:
        chosen = st.selectbox("加载会话", [""] + list(past_map.keys()), key="session_picker")
        if chosen and st.button("打开", use_container_width=True):
            sid = past_map[chosen]
            st.session_state.agent_messages = sessions_mod.load_messages(sid)
            st.session_state.current_session_id = sid
            st.rerun()
        if col_del.button("删除当前会话", use_container_width=True) and st.session_state.current_session_id:
            sessions_mod.delete_session(st.session_state.current_session_id)
            st.session_state.agent_messages = []
            st.session_state.current_session_id = None
            st.rerun()


def _geojson_layers(paths: list[str]) -> tuple[list, tuple[float, float, float]]:
    """GeoJSON 文件 -> pydeck 图层；返回 (layers, 视野中心/缩放)。"""
    layers, all_lats, all_lons = [], [], []
    colors = [[34, 211, 238], [248, 113, 113], [251, 191, 36], [167, 139, 250]]
    for i, path in enumerate(paths):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        color = colors[i % len(colors)]
        for feat in data.get("features", []):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            flat = str(coords)
            import re
            nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", flat)]
            all_lons += nums[0::2]
            all_lats += nums[1::2]
        layers.append(
            pdk.Layer(
                "GeoJsonLayer",
                data=data,
                stroked=True,
                filled=True,
                get_fill_color=color + [40],
                get_line_color=color + [220],
                get_line_width=3,
                line_width_min_pixels=3,   # 关键：线宽按像素计，否则默认按米换算细到看不见
                point_radius_min_pixels=4,
                pickable=True,
            )
        )
    if all_lats:
        import math
        lat, lon = sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)
        span = max(max(all_lats) - min(all_lats), max(all_lons) - min(all_lons), 0.01)
        # 对数缩放：跨度从 0.01°（定点停泊）到 20°（跨海域）都有合适视野
        zoom = max(2.0, min(9.5, math.log2(180.0 / span)))
        return layers, (lat, lon, zoom)
    return layers, (15.0, 43.0, 4.5)


chat_col, map_col = st.columns([5, 6], gap="large")

latest_geojson = next(
    (m["geojson"] for m in reversed(st.session_state.agent_messages) if m.get("geojson")),
    [],
)


def _render_map(slot, paths: list[str], show_files: bool = False) -> None:
    """向指定容器渲染地图；paths 为空时显示默认视野与提示。"""
    slot.empty()
    with slot.container():
        if paths:
            layers, (lat, lon, zoom) = _geojson_layers(paths)
            ui.deck(layers, lat, lon, zoom,
                    tooltip="{date}{event_type}{location}", height=620)
            if show_files:
                with st.expander(f"GeoJSON 文件（{len(paths)} 个）"):
                    for p in paths:
                        st.code(p, language=None)
        else:
            ui.deck([], 15.0, 43.0, 4.5, height=620)
            st.caption("提问后，Agent 产出的缓冲区 / 航迹 / 事件点会自动渲染在这里")


with map_col:
    ui.panel("分析结果地图")
    map_slot = st.empty()
    _render_map(map_slot, latest_geojson, show_files=bool(latest_geojson))

with chat_col:
    ui.panel("对话")
    if not st.session_state.agent_messages:
        st.caption("试试这些问题：")
        for q in EXAMPLE_QUESTIONS:
            if st.button(q, key=f"ex_{q[:12]}", use_container_width=True):
                st.session_state["_pending_question"] = q
                st.rerun()

    for msg in st.session_state.agent_messages:
        with st.chat_message(msg["role"]):
            if msg.get("steps"):
                with st.expander(f"工具调用轨迹（{len(msg['steps'])} 步）", expanded=False):
                    for s in msg["steps"]:
                        st.code(s, language=None)
            st.markdown(msg["content"])

    question = st.chat_input("问一个空间分析问题，如：霍尔木兹海峡100公里内有哪些高风险事件？")
    pending = st.session_state.pop("_pending_question", None)
    question = question or pending

    if question:
        # 多轮记忆：从已有消息中提取 (问, 答) 对注入上下文
        history = []
        msgs = st.session_state.agent_messages
        for i in range(len(msgs) - 1):
            if msgs[i]["role"] == "user" and msgs[i + 1]["role"] == "assistant":
                history.append((msgs[i]["content"], msgs[i + 1]["content"]))

        st.session_state.agent_messages.append({"role": "user", "content": question})
        # 先持久化用户问题：即使运行中断线，历史里也能找回上下文
        sid = st.session_state.current_session_id
        if not sid:
            sid = sessions_mod.create_session(question)
            st.session_state.current_session_id = sid
        sessions_mod.save_message(sid, "user", question)

        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            from agent import react

            thinking = st.empty()          # “思考中”占位
            tool_views = {}                # 进行中的工具卡片 {name: [st.status]}
            steps, geojson_paths = [], []
            live_paths = list(latest_geojson)  # 本轮已上图的 GeoJSON（累加）
            answer, error = "", None

            for ev in react.stream(question, history=history):
                if ev["type"] == "thinking":
                    thinking.info(f"🤔 Agent 思考中（第 {ev['step']} 步）...")
                elif ev["type"] == "tool_start":
                    thinking.empty()
                    args_text = ", ".join(f"{k}={v!r}" for k, v in ev["args"].items())
                    steps.append(f"{ev['name']}({args_text})")
                    view = st.status(f"正在调用 {ev['name']} ...", expanded=True)
                    view.code(f"{ev['name']}({args_text})", language=None)
                    tool_views.setdefault(ev["name"], []).append(view)
                elif ev["type"] == "tool_end":
                    views = tool_views.get(ev["name"]) or []
                    view = views.pop(0) if views else None
                    if view:
                        view.code(ev["output"][:800], language=None)
                        view.update(label=f"{ev['name']} · 调用完成", state="complete", expanded=False)
                    # 即时上图：几何结果一产出就渲染到右侧地图，不等整轮结束
                    if ev.get("geojson_path"):
                        live_paths.append(ev["geojson_path"])
                        _render_map(map_slot, live_paths)
                elif ev["type"] == "answer":
                    thinking.empty()
                    result = ev["result"]
                    answer = result.answer or result.error or "（无回答）"
                    error = result.error
                    geojson_paths = result.geojson_paths
            st.markdown(answer)
            if error:
                st.caption(f"⚠️ {error}")
        st.session_state.agent_messages.append({
            "role": "assistant",
            "content": answer,
            "steps": steps,
            "geojson": geojson_paths,
        })
        sessions_mod.save_message(sid, "assistant", answer, steps, geojson_paths)
        st.rerun()
