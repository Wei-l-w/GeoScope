"""侧栏底部的模型设置：填写 Base URL / API Key / 模型名，保存前先发一次最小请求。

保存的配置存在 data/model_settings.json（不进 git），优先级高于 .env；
失败、校验不过都不落盘，原来能用的配置不会被一次手滑覆盖。

API Key 输入框从不预填：控件的值会原样发到浏览器（密码框只是掩码，还带"显示"按钮），
预填等于把服务器上的 Key 交给每个打开页面的人。留空表示沿用当前 Key，界面只显示末四位。
"""

from __future__ import annotations

import streamlit as st

from agent import model_config

SOURCE_LABELS = {"file": "本地配置", "env": ".env"}
# (字段名, 标签, text_input 的 type, 占位符)；字段名与 model_config.FIELDS 一一对应
INPUTS = (("base_url", "Base URL", "default", "留空使用官方接口"),
          ("api_key", "API Key", "password", ""),
          ("model", "模型名", "default", ""))


def _flag(key: str, value=True) -> None:
    """回调里不能直接出提示：回调之后紧跟着一次重跑，提示要等重跑时才画得出来。"""
    st.session_state[key] = value


def _reset() -> None:
    removed = model_config.clear()
    if removed:  # 没删掉就留着输入框里的值，用户还能再试一次
        for field, *_ in INPUTS:  # 输入框还记着被删掉的那一套：一并清掉，免得看着像是没恢复
            st.session_state.pop(f"model_{field}", None)
    _flag("_model_reset", removed)


def key_hint(api_key: str) -> str:
    """API Key 输入框的占位符：只露末四位，够认出是哪一把，不够拿去用。"""
    if not api_key:
        return ""
    tail = f"（…{api_key[-4:]}）" if len(api_key) >= 12 else ""
    return f"已配置{tail}，留空保持不变"


def resolve_key(base_url: str, api_key: str, settings) -> tuple[str | None, str | None]:
    """返回 (要使用的 Key, 错误)。输入框留空时沿用当前 Key，但地址变了必须重新填写：
    否则任何人都能把 Base URL 改成自己的服务器，让"保存并测试"把已保存的 Key 发过去。"""
    typed = api_key.strip()
    if typed:
        return typed, None
    if not settings.api_key:
        return None, "API Key 不能为空。"
    if model_config.resolve_base_url(base_url) != model_config.resolve_base_url(settings.base_url):
        return None, "更换 Base URL 时需要重新填写 API Key（已保存的 Key 不会发往新地址）。"
    return settings.api_key, None


def trigger_label(settings) -> str:
    """侧栏触发器上的文案：当前模型名 + 配置来源。"""
    return f"模型 · {settings.model}（{SOURCE_LABELS[settings.source]}）"


def render(busy: bool) -> None:
    if st.session_state.pop("_model_saved", False):
        st.session_state.pop("model_api_key", None)  # 刚填的 Key 已保存，别让它留在这个会话的输入框里
        st.toast("模型配置已保存，下一轮分析生效", icon=":material/check_circle:")
    reset = st.session_state.pop("_model_reset", None)
    if reset is True:
        st.toast("已恢复为 .env 里的配置", icon=":material/restart_alt:")
    elif reset is False:
        st.error("没能删掉本地配置：文件可能被其他程序占用，稍后重试。")
    settings = model_config.current()
    label = trigger_label(settings)
    with st.popover(label, icon=":material/tune:", width="stretch", disabled=busy, key="model_settings",
                    help="修改接口地址、密钥或模型名"):
        st.caption("保存前会先发一条最小请求确认三者匹配，成功才写入 data/model_settings.json。")
        with st.form("model_settings_form", border=False, enter_to_submit=False):
            values = {}
            for field, title, kind, placeholder in INPUTS:
                secret = field == "api_key"
                values[field] = st.text_input(
                    title, value="" if secret else getattr(settings, field), type=kind,
                    placeholder=(key_hint(settings.api_key) if secret else placeholder) or None,
                    max_chars=model_config.MAX_FIELD_CHARS, key=f"model_{field}")
            # popover 的 disabled 只禁用触发按钮：已展开的菜单体在前端保留，分析进行中照样能点进来
            # （header 的删除按钮同理），所以里面的按钮必须自己置灰。
            submitted = st.form_submit_button("保存并测试", type="primary", width="stretch", disabled=busy)
        st.button("恢复默认", key="reset_model", type="tertiary", width="stretch",
                  disabled=busy or settings.source != "file", on_click=_reset,
                  help="删除本地配置，回到 .env 里的设置")
        if submitted:
            api_key, error = resolve_key(values["base_url"], values["api_key"], settings)
            if error:
                st.error(error)
            else:
                _save_and_test(values["base_url"], api_key, values["model"])


def _save_and_test(base_url: str, api_key: str, model: str) -> None:
    error = model_config.validate(base_url, api_key, model)
    if error:
        st.error(error)
        return
    ok, detail = model_config.test_connection(base_url, api_key, model)
    if not ok:
        st.error(f"连接失败，配置未保存：{detail}")
        return
    try:
        model_config.save(base_url, api_key, model)
    except OSError as exc:  # 磁盘满、目录只读、文件被占用：写不进去就如实说，别整页红屏
        st.error(f"配置写不进去（{type(exc).__name__}）：{model_config.redact(str(exc), api_key)}")
        return
    _flag("_model_saved")
    st.rerun()
