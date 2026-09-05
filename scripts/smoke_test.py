"""用 Streamlit AppTest 对所有页面做冒烟测试。

用法: python scripts/smoke_test.py
"""
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PAGES = [ROOT / "app" / "Home.py"] + sorted((ROOT / "app" / "pages").glob("*.py"))

failed = False
for page in PAGES:
    at = AppTest.from_file(str(page), default_timeout=60)
    at.run()
    if at.exception:
        failed = True
        print(f"[FAIL] {page.name}")
        for e in at.exception:
            print(f"       {e.value}")
    else:
        print(f"[OK]   {page.name}")

sys.exit(1 if failed else 0)
