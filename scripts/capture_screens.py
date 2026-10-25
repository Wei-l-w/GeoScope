"""用无头 Chrome 给运行中的 GeoScope 截图，供视觉验收与 README 配图。

需要本机 Chrome（找不到时用环境变量 CHROME_PATH 指定）和 websocket-client：
    pip install websocket-client

用法（先在另一个终端启动应用：streamlit run app/GeoAgent.py）：
    python scripts/capture_screens.py --out tmp/screens
    python scripts/capture_screens.py --out tmp/screens --size 1366x768 --size 1000x800
    python scripts/capture_screens.py --out docs --pages 工作台 --open-session 曼德海峡 --name ui
文件名为 <名称>-<light|dark>-<宽>x<高>.png。主题通过模拟系统深浅色切换（菜单默认 System）。
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import websocket
except ImportError:
    sys.exit("缺少 websocket-client：pip install websocket-client")

PAGES = {"工作台": "", "总览": "总览", "AIS": "AIS船舶地图", "ACLED": "ACLED事件",
         "时空叠加": "时空叠加", "新闻检索": "新闻检索", "GDELT": "全球背景参考"}
CLICK = """(() => {{ const b = [...document.querySelectorAll('[data-testid=stSidebar] button')]
  .find(x => x.textContent.includes({text})); if (b) b.click(); return !!b; }})()"""


def chrome_path() -> str:
    candidates = [os.environ.get("CHROME_PATH"), shutil.which("chrome"), shutil.which("google-chrome"),
                  shutil.which("chromium"), r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                  r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    for path in candidates:
        if path and Path(path).exists():
            return path
    sys.exit("找不到 Chrome，请用环境变量 CHROME_PATH 指定可执行文件。")


class Browser:
    def __init__(self, port: int = 9333):
        self.proc = subprocess.Popen(
            [chrome_path(), "--headless=new", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tempfile.mkdtemp(prefix='gs-shots-')}", f"--remote-debugging-port={port}",
             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                page = next(t for t in targets if t.get("type") == "page")
                break
            except Exception:
                time.sleep(0.2)
        else:
            self.close()
            sys.exit("Chrome 调试端口没有响应。")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=60, suppress_origin=True)
        self.counter = 0

    def call(self, method: str, **params):
        self.counter += 1
        self.ws.send(json.dumps({"id": self.counter, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == self.counter:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def close(self):
        self.proc.terminate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8501")
    parser.add_argument("--out", default="tmp/screens")
    parser.add_argument("--pages", nargs="+", choices=list(PAGES), default=list(PAGES))
    parser.add_argument("--theme", action="append", choices=["light", "dark"])
    parser.add_argument("--size", action="append", help="宽x高，如 1440x900，可重复")
    parser.add_argument("--open-session", help="工作台截图前，点击侧栏里标题包含该文字的会话")
    parser.add_argument("--name", help="文件名前缀，默认用页面名")
    parser.add_argument("--wait", type=float, default=20, help="每页等待渲染与底图加载的秒数")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    browser = Browser()
    try:
        browser.call("Page.enable")
        for theme in args.theme or ["light", "dark"]:
            browser.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": theme}])
            for size in args.size or ["1440x900"]:
                width, height = (int(value) for value in size.lower().split("x"))
                browser.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                             deviceScaleFactor=1, mobile=False)
                for page in args.pages:
                    browser.call("Page.navigate", url=f"{args.base}/{urllib.parse.quote(PAGES[page])}")
                    time.sleep(args.wait)
                    if page == "工作台" and args.open_session:
                        expression = CLICK.format(text=json.dumps(args.open_session))
                        found = browser.call("Runtime.evaluate", expression=expression, returnByValue=True)
                        if not found.get("result", {}).get("value"):
                            print(f"没有找到会话：{args.open_session}")
                        time.sleep(args.wait / 2)
                    data = browser.call("Page.captureScreenshot", format="png")["data"]
                    path = out / f"{args.name or page}-{theme}-{width}x{height}.png"
                    path.write_bytes(base64.b64decode(data))
                    print(path)
    finally:
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
