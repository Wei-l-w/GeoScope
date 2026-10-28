"""侧栏底部的模型设置：填写 Base URL / API Key / 模型名，保存前先发一次最小请求。

保存的配置存在 data/model_settings.json（不进 git），优先级高于 .env；
失败、校验不过都不落盘，原来能用的配置不会被一次手滑覆盖。
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


def trigger_label(settings) -> str:
    """侧栏触发器上的文案：当前模型名 + 配置来源。"""
    return f"模型 · {settings.model}（{SOURCE_LABELS[settings.source]}）"


def render(busy: bool) -> None:
    if st.session_state.pop("_model_saved", False):
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
                values[field] = st.text_input(
                    title, value=getattr(settings, field), type=kind, placeholder=placeholder or None,
                    max_chars=model_config.MAX_FIELD_CHARS, key=f"model_{field}")
            # popover 的 disabled 只禁用触发按钮：已展开的菜单体在前端保留，分析进行中照样能点进来
            # （header 的删除按钮同理），所以里面的按钮必须自己置灰。
            submitted = st.form_submit_button("保存并测试", type="primary", width="stretch", disabled=busy)
        st.button("恢复默认", key="reset_model", type="tertiary", width="stretch",
                  disabled=busy or settings.source != "file", on_click=_reset,
                  help="删除本地配置，回到 .env 里的设置")
        if submitted:
            _save_and_test(values["base_url"], values["api_key"], values["model"])


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
