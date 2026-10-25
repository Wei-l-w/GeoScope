"""主题监听组件的回归测试（AppTest / JS）：回退顺序、主题回传与分析中取消上报。"""

import json
import shutil
import subprocess

import pytest
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


def test_busy_cancels_queued_theme_report_without_affecting_other_instances():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the JavaScript behavior regression")

    # 执行原始 ES 模块，保留模块级状态；可控 RAF 队列让 idle → busy 的竞态确定性重现。
    script = """
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(0, 'utf8');
const { default: component } = await import(
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64')
);
const frames = new Map();
let nextFrame = 0;
globalThis.requestAnimationFrame = callback => {
  const id = nextFrame++;
  frames.set(id, callback);
  return id;
};
globalThis.cancelAnimationFrame = id => frames.delete(id);
globalThis.document = { querySelector: selector => selector === '.stApp' ? {} : null };
globalThis.getComputedStyle = () => ({ colorScheme: 'dark' });
function flush() {
  const callbacks = [...frames.values()];
  frames.clear();
  for (const callback of callbacks) callback();
}
const reports = [[], []];
const parents = [{}, {}];
function mount(instance, busy = false) {
  return component({
    data: { known: 'light', busy },
    parentElement: parents[instance],
    setStateValue: (key, value) => reports[instance].push([key, value]),
  });
}
mount(0);
mount(0, true);
flush();
assert.deepEqual(reports[0], [], 'busy transition must cancel the queued theme report');
mount(0);
flush();
assert.deepEqual(reports[0], [['mode', 'dark']], 'idle must resume theme reporting');
reports[0].length = 0;
mount(0);
mount(1);
mount(0, true);
flush();
assert.deepEqual(reports[0], [], 'the busy instance must not report');
assert.deepEqual(reports[1], [['mode', 'dark']], 'instances must not cancel each other');
const cleanup = mount(1);
cleanup();
flush();
assert.deepEqual(reports[1], [['mode', 'dark']], 'unmount must cancel the pending report');
const cleanupA = mount(0);
mount(0);
cleanupA();
mount(0, true);
flush();
assert.deepEqual(reports[0], [], 'stale cleanup must preserve the newer frame for busy cancellation');
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script],
        input=theme_watch._JS,
        capture_output=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
