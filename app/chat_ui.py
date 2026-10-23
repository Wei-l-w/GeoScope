"""对话工作区的展示组件；只在 GeoAgent 页面注入样式。"""

from __future__ import annotations

import html
import json
from pathlib import Path

import streamlit as st

from agent.conversation import clean_assistant_text
from app import ui

TOOL_LABELS = {
    "geocode": "定位地点", "buffer_analysis": "分析周边事件",
    "ship_track": "查询船舶航迹", "query_database": "查询数据",
    "knowledge_search": "检索相关报道",
}


def setup() -> None:
    light = ui.mode() == "light"  # 过渡：任务 7 重写本文件
    palette = (
        "--chat-bg:#f3f5f8;--chat-panel:#ffffff;--chat-soft:#f7f9fb;"
        "--chat-user:#eaf4f4;--chat-line:#dfe5eb;--chat-text:#172b3a;"
        "--chat-muted:#657687;--chat-accent:#087f8c;--chat-button:#e7f3f3;--chat-primary-ink:#ffffff;"
        if light else
        "--chat-bg:#161e2b;--chat-panel:#202b3b;--chat-soft:#253244;"
        "--chat-user:#203e4b;--chat-line:#364559;--chat-text:#e9f0f6;"
        "--chat-muted:#a5b5c7;--chat-accent:#76d6dc;--chat-button:#29414e;--chat-primary-ink:#14333c;"
    )
    styles = Path(__file__).with_name("chat.css").read_text(encoding="utf-8")
    st.markdown("<style>:root{" + palette + "}" + styles + "</style>", unsafe_allow_html=True)


def header() -> None:
    st.markdown(
        '<header class="chat-page-header"><div><div class="chat-eyebrow">GEOSCOPE / 红海专题</div>'
        '<h1>空间分析工作台</h1><p>从一个问题开始，让事件、船舶与地图关联起来。</p></div>'
        '<span class="chat-page-tag">历史数据分析</span></header>', unsafe_allow_html=True,
    )


def panel_header(title: str, subtitle: str, badge: str = "") -> None:
    st.markdown(
        '<div class="chat-panel-header"><div><h2>' + html.escape(title) + '</h2><p>'
        + html.escape(subtitle) + '</p></div><span>' + html.escape(badge) + '</span></div>',
        unsafe_allow_html=True,
    )


def welcome() -> None:
    st.markdown(
        '<div class="chat-welcome"><div class="chat-welcome-mark" aria-hidden="true">⌖</div>'
        '<h3>今天想探索什么？</h3><p>查询周边事件、回看船舶航迹，<br>或从新闻中了解事件背景。</p></div>',
        unsafe_allow_html=True,
    )


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, "分析数据")


def render_details(message: dict) -> None:
    records = message.get("tool_records") or []
    steps = message.get("steps") or []
    if not records and not steps:
        return
    with st.expander(f"分析过程 · {len(records) if records else len(steps)} 步", expanded=False):
        if records:
            for record in records:
                state = "已阻止重复执行" if record.get("blocked") else (
                    "已完成" if record.get("success") else "未完成")
                st.caption(f"{tool_label(record.get('name', ''))} · {state}")
                st.code(json.dumps(record.get("args", {}), ensure_ascii=False, indent=2), language="json")
                st.text(str(record.get("output", ""))[:1800])
        else:
            for step in steps:
                st.code(str(step), language="text")


def render_message(message: dict) -> None:
    is_user = message.get("role") == "user"
    with st.chat_message("user" if is_user else "assistant", avatar="user" if is_user else ":material/explore:"):
        st.caption("你" if is_user else "GeoScope")
        content = message.get("content") or "本轮没有生成回答。"
        st.markdown(content if is_user else clean_assistant_text(content))
        if not is_user:
            if message.get("error"):
                st.caption("本轮分析未完成，可调整问题后重试。")
            render_details(message)


def render_map_files(paths: list[str]) -> None:
    if not paths:
        return
    with st.expander(f"地图结果 · {len(paths)} 个文件", expanded=False):
        output_root = Path(__file__).resolve().parents[1] / "data" / "agent_output"
        for index, raw_path in enumerate(paths):
            path = Path(raw_path)
            if path.suffix.lower() == ".geojson" and path.resolve().is_relative_to(output_root) and path.is_file():
                st.download_button("下载 " + path.name, path.read_bytes(), file_name=path.name,
                                   mime="application/geo+json", key=f"geoagent_download_{index}",
                                   on_click="ignore", width="stretch")
            else:
                st.caption(f"{path.name} 暂不可用，可重新运行对应分析。")
