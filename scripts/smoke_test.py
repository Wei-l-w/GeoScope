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
