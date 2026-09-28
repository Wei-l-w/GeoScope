"""集中配置：全部走环境变量，不落任何密钥在代码里。

必填：
    OPENAI_API_KEY   LLM API Key（任意 OpenAI 兼容服务：DeepSeek / 通义 / 月之暗面等）
可选：
    OPENAI_BASE_URL  接口地址，默认官方；DeepSeek 填 https://api.deepseek.com
    MODEL_NAME       模型名，默认 gpt-4o-mini；DeepSeek 填 deepseek-chat
    WAREHOUSE_PATH   DuckDB 仓库路径，默认 <项目根>/data/warehouse.duckdb
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """极简 .env 加载（不依赖 python-dotenv）：环境变量优先，文件仅作兜底。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

DB_PATH = os.environ.get("WAREHOUSE_PATH", str(ROOT / "data" / "warehouse.duckdb"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL") or None  # None = 官方默认
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-4o-mini")

# 自纠正循环最大重试次数（pandas-ai 式：报错回传 LLM 重写）
MAX_RETRIES = int(os.environ.get("GEOSQL_MAX_RETRIES", "3"))

# LLM 请求超时与重试（代理服务延迟高，默认 60s 容易误杀）
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "300"))
LLM_RETRIES = int(os.environ.get("LLM_RETRIES", "2"))

# 多轮记忆：注入最近 N 轮问答（每轮答案截断，控制 token 与延迟）
HISTORY_TURNS = int(os.environ.get("AGENT_HISTORY_TURNS", "5"))
HISTORY_ANSWER_CHARS = int(os.environ.get("AGENT_HISTORY_ANSWER_CHARS", "800"))


def check_llm_ready() -> None:
    """调用 LLM 前检查配置，缺 Key 时给出可操作的报错。"""
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "未配置 OPENAI_API_KEY。请先设置环境变量，例如：\n"
            '  $env:OPENAI_API_KEY="sk-..."\n'
            '  $env:OPENAI_BASE_URL="https://api.deepseek.com"  # 非官方服务时\n'
            '  $env:MODEL_NAME="deepseek-chat"'
        )
