"""原生主题与设计令牌的静态检查：config.toml、令牌一致性、文字对比度（设计文档第 4 节）。"""

import re
import tomllib
from pathlib import Path

import pytest

from app import palette

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
STYLES = ROOT / "app" / "styles"
# base.css 里纯色的令牌：{名称: {"light": 色值, "dark": 色值}}
TOKENS = {name: dict(zip(palette.MODES, pair)) for name, *pair in re.findall(
    r"--gs-([\w-]+): light-dark\((#[0-9A-Fa-f]{6}), (#[0-9A-Fa-f]{6})\)",
    (STYLES / "base.css").read_text(encoding="utf-8"))}


def _luminance(hex_color: str) -> float:
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(value) for value in palette.rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(foreground: str, background: str) -> float:
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_formula_matches_wcag_reference():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)


@pytest.mark.parametrize("mode", palette.MODES)
def test_config_defines_complete_light_and_dark_themes(mode):
    assert "base" not in CONFIG  # 不再用 base = "dark" 再拿 CSS 硬改浅色
    theme = CONFIG[mode]
    for key in ("primaryColor", "backgroundColor", "secondaryBackgroundColor", "textColor", "borderColor"):
        assert re.fullmatch(r"#[0-9A-F]{6}", theme[key]), key
    assert {"backgroundColor", "secondaryBackgroundColor"} <= set(theme["sidebar"])
    assert "chartCategoricalColors" not in theme  # 写在子表里会被 Streamlit 静默忽略


def test_categorical_colors_are_the_palette_padded_to_ten():
    # Streamlit 的 Plotly 模板有 10 个占位色，少配的会变成 "undefined"、整套色板失效
    assert CONFIG["chartCategoricalColors"] == list(palette.PALETTE) + list(palette.PALETTE[:2])


@pytest.mark.parametrize("mode", palette.MODES)
def test_map_colors_follow_the_native_theme(mode):
    assert palette.MAP[mode]["buffer"] == CONFIG[mode]["primaryColor"]
    assert palette.MAP[mode]["ring"] == CONFIG[mode]["textColor"]


@pytest.mark.parametrize("mode", palette.MODES)
def test_tokens_agree_with_native_theme(mode):
    assert TOKENS["text"][mode] == CONFIG[mode]["textColor"]
    assert TOKENS["accent"][mode] == CONFIG[mode]["primaryColor"]
    assert TOKENS["line"][mode] == CONFIG[mode]["borderColor"]
    assert TOKENS["panel"][mode] == CONFIG[mode]["secondaryBackgroundColor"]


@pytest.mark.parametrize("mode", palette.MODES)
@pytest.mark.parametrize("token", ["text", "muted", "accent"])
def test_text_tokens_meet_wcag_aa_on_page_and_panel(mode, token):
    for background in (CONFIG[mode]["backgroundColor"], CONFIG[mode]["secondaryBackgroundColor"]):
        assert contrast(TOKENS[token][mode], background) >= 4.5, (token, mode, background)


@pytest.mark.parametrize("mode", palette.MODES)
def test_text_on_primary_buttons_meets_wcag_aa(mode):
    assert contrast(TOKENS["accent-ink"][mode], TOKENS["accent"][mode]) >= 4.5
