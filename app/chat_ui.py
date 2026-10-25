"""对话面板：标题栏、消息、分析过程、结果标签、空状态示例与中断标注（设计文档 6.3）。"""

from __future__ import annotations

import html
import json
import re

import streamlit as st

from agent import artifacts
from agent.conversation import clean_assistant_text
from app import map_view, palette, sessions_ui

ASSISTANT_AVATAR = ":material/radar:"
RADAR_SVG = ('<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">'
             '<circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-opacity=".6" stroke-width="1.5"/>'
             '<path d="M12 12 17 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
             '<circle cx="12" cy="12" r="2.2" fill="currentColor"/></svg>')
TOOL_LABELS = {
    "geocode": "定位地点", "buffer_analysis": "分析周边事件", "ship_track": "查询船舶航迹",
    "query_database": "查询数据", "knowledge_search": "检索相关报道",
}
TABLE_LABELS = {"acled_events": "ACLED", "gdelt_events": "GDELT"}
EXAMPLES = [
    ("周边事件", ":material/warning:", "曼德海峡周边150公里内发生了多少起事件？按类型统计"),
    ("船舶航迹", ":material/directions_boat:", "MMSI 668116204 最近30天走了什么路线？"),
    ("事件背景", ":material/article:", "银河领袖号被劫持事件有什么背景？有哪些相关报道？"),
    ("冲突排名", ":material/public:", "Goldstein 冲突最激烈的5个国家是哪些？"),
]


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, "分析数据")


def step_detail(name: str, args: dict) -> str:
    """进行中列表里的一行摘要：只用调用参数，不解析工具输出。"""
    if name == "geocode":
        return f"定位地点：{args.get('place', '')}"
    if name == "buffer_analysis":
        table = args.get("table", "acled_events")
        return f"分析周边事件：{TABLE_LABELS.get(table, table)}，半径 {args.get('radius_km')} km"
    if name == "ship_track":
        return f"查询船舶航迹：MMSI {args.get('mmsi')}，最近 {args.get('days', 7)} 天"
    if name == "knowledge_search":
        return f"检索相关报道：{args.get('query', '')}"
    return tool_label(name)


def _tool_names(message: dict) -> list[str]:
    records = message.get("tool_records") or []
    if records:
        return [str(record.get("name", "")) for record in records]
    return [str(step).split("(", 1)[0] for step in message.get("steps") or []]


def steps_summary(message: dict) -> str:
    """"定位地点 → 分析周边事件"：连续重复只记一次，最多 3 个。"""
    labels = []
    for name in _tool_names(message):
        label = tool_label(name)
        if not labels or labels[-1] != label:
            labels.append(label)
    return " → ".join(labels[:3] + (["…"] if len(labels) > 3 else []))


def process_label(message: dict) -> str:
    summary = steps_summary(message)
    return f"分析过程 · {len(_tool_names(message))} 步" + (f" · {summary}" if summary else "")


def prefill(question: str) -> None:
    st.session_state[sessions_ui.PROMPT_KEY] = question


def unanswered(messages: list[dict]) -> set:
    """没有收到回答的提问 seq：既没有助手消息的 reply_to_seq 指向它，
    也不是"紧跟一条未关联的旧式助手回答"的情况。"""
    replied = {m.get("reply_to_seq") for m in messages if m.get("role") == "assistant"}
    result = set()
    for index, message in enumerate(messages):
        seq = message.get("seq")
        if message.get("role") != "user" or seq is None or seq in replied:
            continue
        following = messages[index + 1] if index + 1 < len(messages) else None
        if following and following.get("role") == "assistant" and following.get("reply_to_seq") is None:
            continue
        result.add(seq)
    return result


def header(title: str, subtitle: str, sid: str | None, busy: bool) -> None:
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="chat_header"):
        st.markdown(f'<div class="gs-chat-title"><b>{html.escape(title)}</b>'
                    f'<span>{html.escape(subtitle)}</span></div>', unsafe_allow_html=True)
        with st.popover("", icon=":material/more_horiz:", type="tertiary", disabled=busy or not sid,
                        key="chat_menu"):
            st.caption("删除会同时移除本会话的聊天记录与记忆。")
            # 菜单的 disabled 只禁用触发按钮：已展开的菜单体在前端保留，分析进行中照样能点进来，
            # 所以里面这颗按钮必须自己置灰，否则一点就会中止本轮分析并删掉会话。
            st.button("删除会话", key="delete_session", icon=":material/delete:", width="stretch",
                      disabled=busy or not sid, on_click=sessions_ui.delete_current, args=(sid,))


def welcome(busy: bool) -> None:
    st.markdown(
        '<div class="gs-welcome"><div class="gs-welcome-mark">' + RADAR_SVG + '</div>'
        '<h3>从一个问题开始</h3><p>查询周边事件、回看船舶航迹，或从新闻中了解事件背景。<br>'
        '结果会作为图层出现在右侧地图上。</p></div>', unsafe_allow_html=True,
    )
    columns = st.columns(2, gap="small")
    for index, (label, icon, question) in enumerate(EXAMPLES):
        with columns[index % 2]:
            st.button(label, key=f"geoagent_example_{index}", icon=icon, help=question, width="stretch",
                      disabled=busy, on_click=prefill, args=(question,))
    st.caption("点选示例只会填入输入框，可修改后再发送")


def render_process(message: dict) -> None:
    records = message.get("tool_records") or []
    steps = message.get("steps") or []
    if not records and not steps:
        return
    icon = ":material/error:" if message.get("error") else ":material/check_circle:"
    with st.expander(process_label(message), icon=icon, expanded=False):
        if records:
            for record in records:
                state = "已阻止重复执行" if record.get("blocked") else ("已完成" if record.get("success") else "未完成")
                st.caption(f"{tool_label(record.get('name', ''))} · {state}")
                st.code(json.dumps(record.get("args", {}), ensure_ascii=False, indent=2), language="json")
                st.text(str(record.get("output", ""))[:1800])
        else:
            for step in steps:
                st.code(str(step), language="text")


def _swatch(kind: str, features: list, mode: str) -> str:
    """色块要和地图上看到的那个颜色一致：事件点按首个事件类型取色，
    非 ACLED 的普通点是空心环，不能都画成"武装冲突"的粉色。"""
    colors = palette.MAP[mode]
    if kind == "buffer":
        return f'<i class="ring" style="border-color:{colors["buffer"]}"></i>'
    if kind == "track":
        return f'<i class="line" style="background:{colors["track"]}"></i>'
    if kind == "events":
        # 地图把非 ACLED 的取值画成空心环（map_view.layer.typed 也要求全部是 ACLED 类型）
        if not all((item.get("properties") or {}).get("event_type") in palette.ACLED_TYPES for item in features):
            return f'<i class="ring" style="border-color:{colors["ring"]}"></i>'
        event_type = (features[0].get("properties") or {}).get("event_type")
        return f'<i class="dot" style="background:{palette.event_color(event_type, mode)}"></i>'
    return f'<i class="ring" style="border-color:{colors["ring"]}"></i>'


def _layers(message: dict, labels: dict | None, turn: int | None) -> list[tuple[str, list, str]]:
    """本轮产生的图层 [(种类, 要素, 名称)]。labels 是图层栏实际用的名称（{(轮次, 路径, 种类): 名称}），
    按轮次查：同一条路径若被后面的回答原样复用，图层只属于最后一轮，前一轮没有自己的按钮可抄，
    就退回不带编号的基本名，不能把"第 2 轮"写到第 1 轮的回答下面。"""
    paths = list(dict.fromkeys(message.get("geojson") or []))
    groups = []
    for path in paths:
        try:
            data = map_view.load(path)
        except artifacts.ArtifactError:
            continue
        for kind, features in map_view.split(data):
            groups.append((kind, features, (labels or {}).get((turn, path, kind))
                           or map_view.layer_label(kind, features)))
    return groups


def result_chips(message: dict, mode: str, labels: dict | None = None, turn: int | None = None) -> None:
    """本轮产生的图层：名称与图层按钮一致，色块与地图同色。"""
    chips = [f'<span class="gs-result">{_swatch(kind, features, mode)}{html.escape(label)}</span>'
             for kind, features, label in _layers(message, labels, turn)]
    if chips:
        st.markdown(f'<div class="gs-results">{"".join(chips)}</div>', unsafe_allow_html=True)


# CommonMark：收尾的 ** 紧跟在标点后面、后面又直接接文字时不算收尾，星号会原样显示。
# 中文回答常写"**标题：**正文"，正好踩中；把加粗末尾的分隔标点挪到 ** 外面。
# 加粗从左到右成对匹配（加粗里不含 * 和换行），免得把前一段的收尾当成下一段的开头；反引号围起的代码原样保留。
# 以引号、书名号、括号收尾的加粗（如"**“银河领袖号”**是"）不处理：挪出去会拆散配对。
_CODE_OR_BOLD = re.compile(r"(```.*?```|`[^`\n]+`)|\*\*([^*\n]+?)([：:，,。；;！!？?、]*)\*\*", re.S)
_WORD = re.compile(r"\w")


def fix_cjk_bold(text: str) -> str:
    """只改显示，会话库里存的仍是模型原文。"""
    def move(match: re.Match) -> str:
        code, body, punct = match.groups()
        if code is None and punct and _WORD.match(text, match.end()):
            return f"**{body}**{punct}"
        return match.group(0)

    return _CODE_OR_BOLD.sub(move, text)


def render_message(message: dict, mode: str, *, interrupted: bool = False, busy: bool = False,
                   labels: dict | None = None, turn: int | None = None) -> None:
    is_user = message.get("role") == "user"
    with st.chat_message("user" if is_user else "assistant", avatar="user" if is_user else ASSISTANT_AVATAR):
        content = message.get("content") or "本轮没有生成回答。"
        if is_user:
            st.markdown(content)
            if interrupted:
                st.caption("分析被中断，没有生成回答")
                st.button("重新填入", key=f"refill_{message.get('seq')}", type="tertiary", icon=":material/edit:",
                          disabled=busy, on_click=prefill, args=(content,))
            return
        render_process(message)
        st.markdown(fix_cjk_bold(clean_assistant_text(content)))
        result_chips(message, mode, labels, turn)
        if message.get("error"):
            st.caption("本轮分析未完成，可调整问题后重试。")
