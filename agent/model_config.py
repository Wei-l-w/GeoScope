"""模型参数的本地覆盖层：界面里保存的 Base URL / API Key / 模型名。

默认值来自 .env 与环境变量（agent.config）。本文件一旦存在且字段完整，就整体覆盖默认值：
只有 Key 或模型名缺失时才回落到 .env，避免"改了一半"的配置让应用连不上。
两层都只在本机，密钥不进 git（data/model_settings.json 在 .gitignore 中单独排除）。
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import config

SETTINGS_PATH = Path(config.ROOT) / "data" / "model_settings.json"
FIELDS = ("base_url", "api_key", "model")
MAX_FIELD_CHARS = 500
MAX_ERROR_CHARS = 400
MAX_FILE_BYTES = 8192   # 三个 500 字符字段的 JSON，留足余量；更大的文件不可能来自本程序
DEFAULT_BASE_URL = "https://api.openai.com/v1"
_WRITE_LOCK = threading.Lock()
# 一轮分析/评测内冻结的配置。用 ContextVar 而不是模块级变量：它是按执行上下文隔离的，
# 另一个标签页的请求（另一个线程）不会读到，用完 reset 也不会留到下一轮。
_RUN_SETTINGS: ContextVar["ModelSettings | None"] = ContextVar("model_config_run", default=None)


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    api_key: str
    model: str
    source: str  # "file"（界面里保存的）或 "env"（.env / 环境变量）


def _clean(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def load() -> dict | None:
    """本地配置内容；文件缺失、损坏或字段不全时返回 None，当作没有本地配置。

    手工改坏这个文件不该让整个工作台红屏：它只是覆盖层，读不出来就用默认值。
    类型不对时整份作废，而不是把坏字段洗成空串——否则 base_url 写坏会悄悄改用官方接口，
    请求带着别家的 Key 打过去，比直接回落 .env 更难排查。
    """
    try:
        if SETTINGS_PATH.stat().st_size > MAX_FILE_BYTES:
            return None
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError):
        # ValueError 含 JSONDecodeError；超长整数、极深嵌套分别是 ValueError 和 RecursionError
        return None
    if not isinstance(data, dict):
        return None
    # 只允许"缺少 base_url"，不允许写成 null：后者是显式的坏值，不该当成官方接口
    if any(field in data and not isinstance(data[field], str) for field in FIELDS):
        return None
    settings = {field: _clean(data.get(field)) for field in FIELDS}
    return settings if settings["api_key"] and settings["model"] else None


def current() -> ModelSettings:
    """当前生效的模型配置。每次调用都读一次文件：保存后下一轮分析立即生效，不必重启。"""
    local = load()
    if local:
        return ModelSettings(local["base_url"], local["api_key"], local["model"], "file")
    return ModelSettings(_clean(config.OPENAI_BASE_URL), _clean(config.OPENAI_API_KEY),
                         _clean(config.MODEL_NAME), "env")


def resolve_base_url(base_url: str) -> str:
    """真正发请求用的地址：留空就显式写成官方接口，绝不把空串/None 交给客户端。

    客户端在 base_url 为 None 时会回读 OPENAI_BASE_URL（LangChain 还会回读 OPENAI_API_BASE），
    而本项目 .env 里正好写着代理地址——于是"留空使用官方接口"会把新 Key 发到旧代理上。
    """
    return _clean(base_url) or DEFAULT_BASE_URL


def validate(base_url: str, api_key: str, model: str) -> str | None:
    """返回错误说明；None 表示可以保存。Base URL 允许为空（官方接口）。"""
    values = {"API Key": _clean(api_key), "模型名": _clean(model), "Base URL": _clean(base_url)}
    if not values["API Key"]:
        return "API Key 不能为空。"
    if not values["模型名"]:
        return "模型名不能为空。"
    for label, value in values.items():
        if len(value) > MAX_FIELD_CHARS:
            return f"{label} 过长（上限 {MAX_FIELD_CHARS} 字符）。"
    if values["Base URL"] and not _valid_url(values["Base URL"]):
        return "Base URL 需以 http:// 或 https:// 开头，并包含主机名。"
    return None


def _valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:  # 例如 IPv6 括号没写全
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.hostname)


def save(base_url: str, api_key: str, model: str) -> None:
    """原子写入：先写同目录临时文件再替换，中断时不会留下半截 JSON。

    只有试连成功之后才调用它——填错配置不该覆盖掉原来能用的那一套。
    加锁是因为多标签页会同时触发保存：临时文件名固定，两个线程并行写会互相截断。
    这里再校验一次：界面已经校验过，但它是公开函数，别让别的调用方（脚本、测试）绕过。
    """
    error = validate(base_url, api_key, model)
    if error:
        raise ValueError(error)
    payload = {"base_url": _clean(base_url), "api_key": _clean(api_key), "model": _clean(model)}
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_PATH.with_name(SETTINGS_PATH.name + ".tmp")
    with _WRITE_LOCK:
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # POSIX 上仅本人可读
            try:
                fchmod = getattr(os, "fchmod", None)
                if fchmod:  # 预存了一个宽权限的 .tmp 时，创建参数不会把它收紧
                    fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    descriptor = None  # 交给 stream 管，别重复关闭
                    json.dump(payload, stream, ensure_ascii=False, indent=2)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            os.replace(temporary, SETTINGS_PATH)
        except BaseException:
            # 写一半失败：清掉自己的临时文件，正式文件保持原样（敏感内容不留在盘上）
            try:
                temporary.unlink()
            except OSError:
                pass
            raise


def clear() -> bool:
    """删除本地配置，回到 .env / 环境变量。返回是否真的删掉了（文件本来就不存在也算成功）。

    删不掉（Windows 上被别的进程占用）不抛异常，交给界面提示——静默失败会让用户以为已经恢复。
    与 save 共用一把锁：否则"删掉"和"正在替换"可能交错，留下一个刚被写回的配置。
    """
    with _WRITE_LOCK:
        try:
            SETTINGS_PATH.unlink()
        except FileNotFoundError:
            return True
        except OSError:
            return False
    return True


@contextmanager
def frozen(settings: "ModelSettings | None" = None):
    """在一轮执行内冻结模型配置与密钥，产出 (settings, secrets)。

    为什么不能等出错时再读：一轮分析可能跑很久，中途别的标签页保存了新配置，
    此时 current() 拿到的是新 Key，而报错里回显的是这一轮真正用过的旧 Key。
    react/geosql 之外的地方（工作台的兜底、CLI 的兜底）同样要能拿到同一份。

    嵌套时复用外层已冻结的配置（active()），不会在轮中途重新读文件。
    用 ContextVar 而不是模块级变量：并发请求各自一个执行上下文，用完 reset 恢复。
    """
    settings = settings or active()
    secrets = key_snapshot(settings.api_key)
    token = _RUN_SETTINGS.set(settings)
    try:
        yield settings, secrets
    finally:
        _RUN_SETTINGS.reset(token)


def active() -> ModelSettings:
    """本轮冻结的配置；没有冻结时（CLI 直连、新一轮开始）照常读最新配置。"""
    return _RUN_SETTINGS.get() or current()


def key_snapshot(*extra: str) -> tuple[str, ...]:
    """此刻可能被用到的全部密钥，按长度降序去重。

    一次分析可能跑很久；等出错时再读配置，拿到的可能已经是另一个标签页刚保存的新 Key，
    而报错里回显的是这一轮真正用过的旧 Key。所以要在开跑时冻结一份。
    长 Key 先替换：短 Key 若是长 Key 的前缀，先换短的会把长 Key 截成"***"加一截尾巴。
    """
    local = load()
    keys = {_clean(config.OPENAI_API_KEY), local["api_key"] if local else ""}
    keys.update(_clean(item) for item in extra)
    return tuple(sorted((k for k in keys if k), key=len, reverse=True))


def redact(text: str, secrets: str | tuple[str, ...] | None = None) -> str:
    """把密钥原文换成 ***。

    试连之外的路径也要过这一道：生产调用的报错会显示在界面上，还会写进会话库——
    部分代理会把请求头原样回显在报错里，密钥就跟着一起落盘了。
    生产路径应传入开跑时冻结的 key_snapshot()；不传时退化为"此刻"的两层密钥。
    """
    if secrets is None:
        secrets = key_snapshot()
    elif isinstance(secrets, str):
        secrets = (secrets,)
    for value in sorted({_clean(item) for item in secrets if _clean(item)}, key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def test_connection(base_url: str, api_key: str, model: str, *, timeout: float = 20.0) -> tuple[bool, str]:
    """用与生产同一个客户端类、同一个地址解析规则发一条最小请求，确认三者匹配。

    错误摘要里的 API Key 会被替换成 ***：部分代理会把请求头原样回显在报错里。
    """
    key = _clean(api_key)
    try:
        from langchain_openai import ChatOpenAI  # 延迟导入：没配模型时也能跑离线测试

        llm = ChatOpenAI(model=_clean(model), api_key=key, base_url=resolve_base_url(base_url),
                         temperature=0, timeout=timeout, max_retries=0)
        llm.invoke("ping")
    except Exception as exc:  # 网络、鉴权、模型名不存在、依赖没装都归到这里，统一转成一句人话
        return False, redact(f"{type(exc).__name__}: {exc}", key)[:MAX_ERROR_CHARS]
    return True, "连接正常"
