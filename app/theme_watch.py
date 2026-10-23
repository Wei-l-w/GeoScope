"""读出浏览器里当前生效的明暗主题，供 deck.gl 图层等 CSS 管不到的配色使用。

主题只能在右上角菜单切换，st.context.theme 在切换瞬间会滞后。这里挂一个不显示内容的
v2 组件：数据或主题变化时 Streamlit 会重新执行组件脚本，脚本读取 .stApp 的
color-scheme，与 Python 已知值不同才上报（触发一次重跑）；busy 时不上报，避免打断分析。
"""

from __future__ import annotations

import streamlit as st
from streamlit.components import v2

STATE_KEY = "_ui_mode"
WATCH_KEY = "geoscope_theme_watch"
MODES = ("light", "dark")

_JS = """
const pendingFrames = new WeakMap();

export default function ({ data, parentElement, setStateValue }) {
  // Cancel this instance's idle frame even when the new invocation is busy.
  const previousFrame = pendingFrames.get(parentElement);
  if (previousFrame !== undefined) {
    cancelAnimationFrame(previousFrame);
    pendingFrames.delete(parentElement);
  }
  if (!data || data.busy) return;
  const frame = requestAnimationFrame(() => {
    pendingFrames.delete(parentElement);
    const app = document.querySelector('.stApp');
    const scheme = app ? getComputedStyle(app).colorScheme : '';
    if ((scheme === 'light' || scheme === 'dark') && scheme !== data.known) {
      setStateValue('mode', scheme);
    }
  });
  pendingFrames.set(parentElement, frame);
  return () => {
    if (pendingFrames.get(parentElement) === frame) {
      cancelAnimationFrame(frame);
      pendingFrames.delete(parentElement);
    }
  };
}
"""


def mode(busy: bool = False) -> str:
    """返回 "light" / "dark" 并记入会话状态；拿不到时依次回退到 st.context 与浅色。"""
    reported = (st.session_state.get(WATCH_KEY) or {}).get("mode")  # 组件上次上报、已生效的值
    context = st.context.theme.type
    current = reported if reported in MODES else (
        st.session_state.get(STATE_KEY) or (context if context in MODES else "light"))
    # known 必须是 Python 此刻实际采用的值。若传入上报前的旧值，浏览器切回原主题时
    # JS 会以为"没变化"而不上报（Light → Dark → Light 后仍按深色配色）。
    # 每次运行都注册：定义不变时 Streamlit 静默覆盖。只在导入时注册一次的话，同一进程里
    # 第二个 AppTest（各自独立的组件注册表）会报 "Component ... is not registered"
    component = v2.component(WATCH_KEY, js=_JS)
    component(key=WATCH_KEY, data={"known": current, "busy": busy}, on_mode_change=lambda: None)
    st.session_state[STATE_KEY] = current
    return current
