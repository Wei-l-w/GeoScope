"""入口路由：工作台为默认页，看板页显式注册；入口旁不能有 pages/ 目录（设计文档第 3 节）。"""

import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from agent import sessions

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "app" / "GeoAgent.py"


def test_router_opens_the_workspace_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    app = AppTest.from_file(str(ROUTER), default_timeout=20).run()
    assert not app.exception
    assert app.chat_input(key="geoagent_prompt").placeholder == "输入地点、船号或分析问题…"


def test_router_registers_the_workspace_first_and_six_dashboards():
    pages = re.findall(r'^\s*st\.Page\("([^"]+)"', ROUTER.read_text(encoding="utf-8"), re.MULTILINE)
    assert pages[0] == "workspace.py"
    assert [Path(page).parent.name for page in pages[1:]] == ["dashboards"] * 6
    assert all((ROOT / "app" / page).is_file() for page in pages)


def test_every_nav_page_renders_through_the_router(tmp_path, monkeypatch):
    # 只看源码文本会漏掉被注释掉的注册项：switch_page 不检查注册表，照样能打开页面，
    # 所以这里逐个页面走路由执行，确认注册项与文件一对一。
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")
    pages = re.findall(r'^\s*st\.Page\("([^"]+)"', ROUTER.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(pages) == 7, pages  # 少一个注册项时，循环会静默跳过它
    app = AppTest.from_file(str(ROUTER), default_timeout=30).run()
    assert not app.exception
    for page in pages:
        app.switch_page(page).run()
        assert not app.exception, page
        if page == "workspace.py":
            assert app.chat_input(key="geoagent_prompt"), page
        else:
            assert "gs-header" in " ".join(item.value for item in app.markdown), page


def test_no_pages_directory_next_to_the_router():
    # Streamlit 见到入口旁的 pages/ 会先按旧版多页模式运行，直接打开看板链接会绕过路由
    assert not (ROOT / "app" / "pages").exists()
