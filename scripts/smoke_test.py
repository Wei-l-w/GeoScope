"""用 Streamlit AppTest 对所有页面做冒烟测试。

用法: python scripts/smoke_test.py
"""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / "app" / "GeoAgent.py"] + sorted((ROOT / "app" / "dashboards").glob("*.py"))
if len(PAGES) != 7:  # 看板页若被改名或清空，这里必须报错，而不是打印一个更小的"N/N 通过"
    raise SystemExit(f"预期 1 个工作台 + 6 个看板页，实际找到 {len(PAGES)} 个页面")


def main() -> int:
    """初始化真实的七个页面；测试会话库独立于正在运行的应用。"""
    sys.path.insert(0, str(ROOT))
    failed = 0
    with TemporaryDirectory(prefix="geoagent-smoke-") as temp_dir:
        sessions_path = Path(temp_dir) / "sessions.duckdb"
        with patch.dict(os.environ, {"SESSIONS_DB_PATH": str(sessions_path)}):
            from agent import sessions

            # 也处理调用 main() 前 sessions 已被导入的情况。
            with patch.object(sessions, "DB_PATH", sessions_path):
                for page in PAGES:
                    try:
                        at = AppTest.from_file(str(page), default_timeout=60)
                        at.run()
                    except Exception as exc:
                        failed += 1
                        print(f"[FAIL] {page.name}: {type(exc).__name__}: {exc}")
                        continue
                    if at.exception:
                        failed += 1
                        print(f"[FAIL] {page.name}")
                        for exc in at.exception:
                            print(f"       {exc.value}")
                    else:
                        print(f"[OK]   {page.name}")
    print(f"页面初始化：{len(PAGES) - failed}/{len(PAGES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
