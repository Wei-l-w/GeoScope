"""主题监听组件的回归测试（AppTest）：回退顺序、上报值回传给前端、分析中延后上报。"""

import json

from streamlit.testing.v1 import AppTest

from app import theme_watch


def _page(busy):
    import streamlit as st

    from app import theme_watch

    current = theme_watch.mode(busy=busy)
    st.write(f"watch={current} stored={st.session_state[theme_watch.STATE_KEY]}")


def _app(busy=False):
    app = AppTest.from_function(_page, args=(busy,), default_timeout=20).run()
    assert not app.exception
    return app


def _sent(app):
    """组件收到的 data，也就是浏览器端 JS 用来比较的值。"""
    return json.loads(app.get("bidi_component")[0].proto.json)


def test_without_a_report_mode_falls_back_to_light():
    app = _app()
    assert app.markdown[0].value == "watch=light stored=light"
    assert _sent(app) == {"known": "light", "busy": False}


def test_reported_mode_is_used_and_sent_back_as_known():
    # 回归：上报后必须把"已生效的值"传回前端，否则切回原主题时 JS 以为没变化、不再上报
    app = _app()
    for reported in ("dark", "light", "dark"):
        app.session_state[theme_watch.WATCH_KEY] = {"mode": reported}
        app.run()
        assert app.markdown[0].value == f"watch={reported} stored={reported}"
        assert _sent(app)["known"] == reported


def test_busy_is_forwarded_so_reports_wait_until_the_analysis_ends():
    assert _sent(_app(busy=True)) == {"known": "light", "busy": True}


def test_each_apptest_can_mount_the_watcher():
    # 每个 AppTest 有独立的组件注册表；组件只在导入时注册的话，第二个会报未注册
    for _ in range(2):
        assert _sent(_app())["known"] == "light"
