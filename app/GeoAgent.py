"""GeoScope 入口：Logo、顶部导航与页面路由（设计文档第 3 节）。

工作台在 workspace.py；看板页在 dashboards/ 下，由这里显式注册。目录不能叫 pages/：
Streamlit 见到 pages/ 会先按旧版多页模式运行，直到某个会话打开首页、执行到 st.navigation，
在那之前直接打开看板页链接会绕过这里，导航退回旧版侧栏。
"""

import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
if str(APP.parent) not in sys.path:
    sys.path.insert(0, str(APP.parent))

st.set_page_config(page_title="GeoScope", page_icon=":material/radar:", layout="wide",
                   initial_sidebar_state="expanded")
st.logo(str(APP / "static" / "logo.svg"), size="large")

PAGES = [
    st.Page("workspace.py", title="工作台", icon=":material/explore:", default=True),
    st.Page("dashboards/1_总览.py", title="总览", icon=":material/dashboard:"),
    st.Page("dashboards/2_AIS船舶地图.py", title="AIS 船舶", icon=":material/directions_boat:"),
    st.Page("dashboards/3_ACLED事件.py", title="ACLED 事件", icon=":material/warning:"),
    st.Page("dashboards/4_时空叠加.py", title="时空叠加", icon=":material/layers:"),
    st.Page("dashboards/5_新闻检索.py", title="新闻检索", icon=":material/article:"),
    st.Page("dashboards/6_全球背景参考.py", title="GDELT 背景", icon=":material/public:"),
]
st.navigation(PAGES, position="top").run()
