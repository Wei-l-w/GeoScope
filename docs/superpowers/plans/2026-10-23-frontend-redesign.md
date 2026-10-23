# GeoScope 前端改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 GeoScope 的 Streamlit 前端改为原生双主题 + 设计令牌：重做 GeoAgent 工作台（会话列表、对话、会话内累积且可开关的地图图层、分析中防打断），6 个看板页统一换皮并接入经过验证的数据配色。

**Architecture:** 主题交还 Streamlit 原生 `[theme.light]` / `[theme.dark]`；自己输出的 HTML 只用 `app/styles/base.css` 里 `light-dark()` 定义的令牌取色；deck.gl 图层由 `theme_watch.mode()` 判断深浅，从 `app/palette.py` 取色。`app/GeoAgent.py` 改为 `st.navigation` 路由；工作台拆成 `workspace.py`（编排与流式循环）、`sessions_ui.py`（侧栏）、`chat_ui.py`（消息）、`map_view.py`（图层）；看板页移到 `app/dashboards/`。

**Tech Stack:** Python 3.12、Streamlit 1.59（`st.navigation`、`st.pills`、`st.popover`、`st.components.v2`、AppTest）、pydeck / deck.gl、Plotly、DuckDB、pytest。

**设计文档：** `docs/superpowers/specs/2026-10-23-frontend-redesign-design.md`。第 13 节"需先验证"的各项已在临时样机里逐一验证，结论与由此产生的调整已写回设计文档；本计划中的代码就是样机里验证过的代码。

---

## 开始之前

- 分支 `feat/frontend-redesign`（已有 `26f1e11` 地图修复、`0855c24` 设计文档两个提交）。所有命令在仓库根目录用 Git Bash 执行。
- 基线：`python -m pytest tests/ -q` 为 **223 passed**，`python scripts/smoke_test.py` 输出"页面初始化：7/7 通过"。
- 测试全部离线：会话库由各测试的 fixture 换成临时文件，地图产物目录由 `tests/conftest.py` 隔离到每个测试的临时目录，模型 API 被替换为直接报错的函数。
- 手动在浏览器里看效果时注意：Streamlit 不会热重载被改动的 `app/` 下模块，改完 Python 要重启 `streamlit run`。
- 每个任务结束时全部测试都应通过。任务 4–6 中旧工作台页面还要继续运行，所以有两处**过渡代码**（`chat_ui.py` 一行、`map_view.py` 末尾一段旧接口），任务 7 重写工作台时删除。

## 文件结构

| 文件 | 动作 | 职责 |
| --- | --- | --- |
| `.streamlit/config.toml` | 重写 | 原生双主题、字体、圆角、全局分类色板 |
| `app/palette.py` | 新建 | 数据配色常量与色阶函数，不依赖 Streamlit |
| `app/theme_watch.py` | 新建 | v2 组件读取浏览器当前深浅主题，`mode()` |
| `app/styles/base.css` | 新建 | 设计令牌 + 看板组件样式 + 增强样式 #1–#3 |
| `app/styles/workspace.css` | 新建 | 工作台布局 + 增强样式 #4、#5、#7、#8 |
| `app/static/logo.svg` | 新建 | Logo，内置深浅两套颜色 |
| `app/ui.py` | 重写 | 看板公共组件：`setup` / `mode` / `fit_bounds` / 页头 / KPI / 图例 / 地图 / 图表 |
| `app/pages/*.py` → `app/dashboards/*.py` | 换皮后改名 | 6 个看板页；只改配色、导入、占位文案和少量参数 |
| `app/map_view.py` | 重写 | 图层拆分、累积、开关、视野、复位、图例、下载 |
| `app/GeoAgent.py` | 改名为 `workspace.py`，再新建为路由 | 入口：`set_page_config`、`st.logo`、`st.navigation` |
| `app/workspace.py` | 重写 | 工作台页面：布局、提交判定、防打断、流式分析 |
| `app/sessions_ui.py` | 新建 | 侧栏：新建分析、最近会话、本会话记忆 |
| `app/chat_ui.py` | 重写 | 标题栏与 ··· 菜单、消息、分析过程、结果标签、空状态、中断标注 |
| `app/chat.css` | 删除 | 由 `styles/workspace.css` 取代 |
| `scripts/smoke_test.py` | 修改 | 冒烟目录改为 `app/dashboards` |
| `scripts/capture_screens.py` | 新建 | 无头 Chrome 截图（视觉验收、README 配图） |
| `tests/test_palette.py` `test_theme.py` `test_theme_watch.py` `test_ui.py` `test_map_layers.py` `test_navigation.py` `test_workspace_sessions.py` `test_workspace_layers.py` | 新建 | 见各任务 |
| `tests/test_chat_workspace.py` `test_map_display.py` `test_memory_ui.py` | 修改 | 选择器与文案跟随新界面，行为断言不变 |
| `requirements.txt`、`README.md`、`.gitignore` | 修改 | 依赖、界面说明、截图 |

## 任务总览

数字按实际实施更新：每个任务的质量复查都会补充回归测试，所以"结束时测试数"逐次增加，实施时以实际数与"全部通过"为准，不要为了凑数字改测试。

| # | 任务 | 结束时测试数 |
| --- | --- | --- |
| 1 | 数据配色模块 | 230 |
| 2 | 原生双主题与设计令牌 | 246 |
| 3 | 主题监听组件 | 252 |
| 4 | 看板公共层与 6 个看板页换皮 | 265 |
| 5 | 地图图层模型 | 291 |
| 6 | 路由入口与顶部导航 | 294 |
| 7 | 工作台重做 | 305 |
| 8 | README 与依赖 | 305 |
| 9 | 真实分析验收（调用模型约 2 次） | — |
| 10 | 视觉验收与 README 截图 | — |

---

### Task 1: 数据配色模块 `app/palette.py`

所有色值来自设计文档第 5 节，已用 dataviz 技能的 `validate_palette.py` 验证过（色盲模拟、OKLab 色差、对比度）。模块不依赖 Streamlit，方便单测；改动任何色值都要重新跑验证器。

**Files:**
- Create: `app/palette.py`
- Test: `tests/test_palette.py`

- [ ] **Step 1: 写测试**

**写入 `tests/test_palette.py`：**

```python
"""数据配色常量与色阶函数（设计文档第 5 节）。改动色值前先重跑 dataviz 验证器。"""

import pytest

from app import palette


def _lightness(colors):
    return [palette.oklab(color)[0] for color in colors]


def _monotonic(values, rising):
    pairs = list(zip(values, values[1:]))
    return all(b > a for a, b in pairs) if rising else all(b < a for a, b in pairs)


def test_categorical_palette_and_role_colors_match_design():
    assert palette.PALETTE == ("#2563EB", "#C2410C", "#0D9488", "#B45309",
                               "#DB2777", "#8B5CF6", "#15803D", "#DC2626")
    assert palette.SOURCE == {"ais": "#2563EB", "acled": "#DC2626", "news": "#8B5CF6", "gdelt": "#B45309"}
    assert set(palette.SOURCE.values()) <= set(palette.PALETTE)
    assert palette.EVENT_COLORS == {"Battles": "#BE185D", "Explosions/Remote violence": "#EA580C",
                                    "Strategic developments": "#A855F7"}
    assert palette.OTHER_GRAY == {"light": "#4B5563", "dark": "#9CA3AF"}
    assert palette.MAP == {
        "light": {"buffer": "#0F766E", "track": "#2563EB", "ring": "#1B1D1F", "stroke": "#FFFFFF"},
        "dark": {"buffer": "#F5B83D", "track": "#38D5F5", "ring": "#E7ECF3", "stroke": "#0A0F1A"},
    }


def test_rgb_and_unknown_mode_falls_back_to_light():
    assert palette.rgb("#0F766E") == [15, 118, 110]
    assert palette.ordinal(3, "sepia") == palette.ordinal(3, "light")


@pytest.mark.parametrize("mode", palette.MODES)
def test_ordered_ramps_run_light_to_dark_in_light_mode_and_reverse_in_dark(mode):
    rising = mode == "dark"  # 浅色主题：低 → 高 由浅到深；深色主题反过来
    for n in (3, 4):
        assert _monotonic(_lightness(palette.ordinal(n, mode)), rising)
    for hue in ("red", "blue"):
        ramp = palette.sequential(hue, mode)
        assert [color[3] for color in ramp] == list(palette.SEQUENTIAL_ALPHA)
        assert _monotonic(_lightness(palette.SEQUENTIAL[hue][mode]), rising)


@pytest.mark.parametrize("mode", palette.MODES)
def test_diverging_scale_has_gray_midpoint_and_monotonic_arms(mode):
    negative, middle, positive = palette.DIVERGING[mode]
    assert palette.diverging(-10, mode) == palette.rgb(negative)
    assert palette.diverging(0, mode) == palette.rgb(middle)
    assert palette.diverging(10, mode) == palette.rgb(positive)
    assert palette.diverging(-25, mode) == palette.rgb(negative)  # 超出 ±10 取端点
    arms = [_lightness(["#%02X%02X%02X" % tuple(palette.diverging(v * sign, mode)) for v in range(0, 11, 2)])
            for sign in (-1, 1)]
    rising = mode == "dark"  # 从中点走向两极：浅色越走越深，深色越走越亮
    assert all(_monotonic(values, rising) for values in arms)


def test_event_types_fold_into_three_colors_plus_other():
    assert palette.event_group("Battles") == "Battles"
    for value in ("Protests", "Riots", "Violence against civilians", "190", None):
        assert palette.event_group(value) == palette.OTHER
    assert palette.group_label(palette.OTHER) == "其他"
    assert palette.type_label("Riots") == "骚乱"
    assert palette.type_label("190") == "190"
    assert palette.event_color("Riots", "dark") == palette.OTHER_GRAY["dark"]
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_palette.py -q
```

预期：失败——收集阶段报 `ImportError: cannot import name 'palette' from 'app'`。

- [ ] **Step 3: 实现**

要点：
- `PALETTE` 是全局分类色板（顺序固定，按槽位取色），`SOURCE` 是 KPI 色条与单系列图表用的数据源色。
- 有序 / 顺序色阶浅色版由浅到深，深色版锚点反转（由暗到亮）；`sequential()` 直接返回 HeatmapLayer 的 `color_range`。
- `diverging(value, mode)` 在 OKLab 中从灰色中点向一极插值，保证每条臂明度单调。
- 工作台 ACLED 事件只给 3 类着色，其余（含 GDELT 代码等非 ACLED 取值）归"其他"。

**写入 `app/palette.py`：**

```python
"""数据配色：设计文档第 5 节经 dataviz 验证器计算过的色值，不依赖 Streamlit。

改动任何色值都要重新跑验证器；分类色板还要同步 .streamlit/config.toml 的
chartCategoricalColors（Streamlit 只允许全局配一套）。
"""

from __future__ import annotations

MODES = ("light", "dark")

# 5.1 分类色板：顺序固定，按槽位依次取色（Tailwind v3：blue-600 orange-700 teal-600
# amber-700 pink-600 violet-500 green-700 red-600）
PALETTE = ("#2563EB", "#C2410C", "#0D9488", "#B45309", "#DB2777", "#8B5CF6", "#15803D", "#DC2626")

# 数据源色：KPI 色条与单系列图表
SOURCE = {"ais": "#2563EB", "acled": "#DC2626", "news": "#8B5CF6", "gdelt": "#B45309"}

# 5.2 有序色阶（红），低 → 高；深色版由暗到亮
ORDINAL = {
    3: {"light": ("#F87171", "#DC2626", "#991B1B"), "dark": ("#991B1B", "#DC2626", "#F87171")},
    4: {"light": ("#F87171", "#EF4444", "#B91C1C", "#7F1D1D"),
        "dark": ("#991B1B", "#B91C1C", "#EF4444", "#FCA5A5")},
}

# 5.3 发散色阶：负极、中点、正极
DIVERGING = {"light": ("#B91C1C", "#A3A3A3", "#1D4ED8"), "dark": ("#F87171", "#737373", "#60A5FA")}

# 5.4 顺序色阶（热力图）：单色相、明度单调，透明度从 0 渐增
SEQUENTIAL_ALPHA = (0, 90, 140, 190, 225, 255)
SEQUENTIAL = {
    "red": {"light": ("#FECACA", "#FCA5A5", "#F87171", "#DC2626", "#B91C1C", "#7F1D1D"),
            "dark": ("#7F1D1D", "#991B1B", "#B91C1C", "#EF4444", "#F87171", "#FECACA")},
    "blue": {"light": ("#BFDBFE", "#93C5FD", "#60A5FA", "#2563EB", "#1D4ED8", "#1E3A8A"),
             "dark": ("#1E3A8A", "#1E40AF", "#1D4ED8", "#3B82F6", "#60A5FA", "#BFDBFE")},
}

# 5.5 工作台地图：ACLED 事件只给三类着色，其余归"其他"
EVENT_COLORS = {"Battles": "#BE185D", "Explosions/Remote violence": "#EA580C",
                "Strategic developments": "#A855F7"}
EVENT_LABELS = {"Battles": "武装冲突", "Explosions/Remote violence": "爆炸/远程暴力",
                "Strategic developments": "战略动态", "Protests": "抗议", "Riots": "骚乱",
                "Violence against civilians": "针对平民的暴力"}
ACLED_TYPES = frozenset(EVENT_LABELS)
OTHER = "other"
OTHER_LABEL = "其他"
OTHER_GRAY = {"light": "#4B5563", "dark": "#9CA3AF"}
MAP = {
    "light": {"buffer": "#0F766E", "track": "#2563EB", "ring": "#1B1D1F", "stroke": "#FFFFFF"},
    "dark": {"buffer": "#F5B83D", "track": "#38D5F5", "ring": "#E7ECF3", "stroke": "#0A0F1A"},
}


def _mode(mode: str) -> str:
    return mode if mode in MODES else "light"


def rgb(hex_color: str) -> list[int]:
    value = hex_color.lstrip("#")
    return [int(value[i:i + 2], 16) for i in (0, 2, 4)]


def ordinal(n: int, mode: str) -> tuple[str, ...]:
    return ORDINAL[n][_mode(mode)]


def sequential(hue: str, mode: str) -> list[list[int]]:
    """HeatmapLayer 的 color_range。"""
    return [rgb(color) + [alpha] for color, alpha in zip(SEQUENTIAL[hue][_mode(mode)], SEQUENTIAL_ALPHA)]


def event_group(event_type: str) -> str:
    """三类之外的类型（含非 ACLED 取值）统一归 OTHER。"""
    return event_type if event_type in EVENT_COLORS else OTHER


def group_label(group: str) -> str:
    return EVENT_LABELS[group] if group in EVENT_COLORS else OTHER_LABEL


def type_label(event_type: str) -> str:
    """悬停提示用的具体类型名；未知取值原样返回。"""
    return EVENT_LABELS.get(event_type, str(event_type))


def event_color(event_type: str, mode: str) -> str:
    return EVENT_COLORS.get(event_type, OTHER_GRAY[_mode(mode)])


# ---- OKLab：发散色阶在感知均匀的空间里插值，保证每条臂明度单调 ----
def _linear(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def _encode(channel: float) -> int:
    channel = channel * 12.92 if channel <= 0.0031308 else 1.055 * channel ** (1 / 2.4) - 0.055
    return round(min(1.0, max(0.0, channel)) * 255)


def oklab(hex_color: str) -> tuple[float, float, float]:
    r, g, b = (_linear(c) for c in rgb(hex_color))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _from_oklab(lightness: float, a: float, b: float) -> list[int]:
    l = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return [_encode(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _encode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _encode(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)]


def diverging(value: float, mode: str, limit: float = 10.0) -> list[int]:
    """负极 → 灰色中点 → 正极；value 超出 ±limit 时取端点色。"""
    negative, middle, positive = (oklab(c) for c in DIVERGING[_mode(mode)])
    t = max(-1.0, min(1.0, float(value) / limit))
    end = negative if t < 0 else positive
    return _from_oklab(*(m + (e - m) * abs(t) for m, e in zip(middle, end)))
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_palette.py -q
```

预期：通过，7 passed。

- [ ] **Step 5: 提交**

```bash
git add app/palette.py tests/test_palette.py && \
  git commit -m "feat(ui): 数据配色模块 app/palette.py" -m "设计文档第 5 节的分类色板、数据源色、有序/发散/顺序色阶与工作台地图配色，按主题取值，不依赖 Streamlit。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 2: 原生双主题与设计令牌

`config.toml` 同时定义 `[theme.light]` 与 `[theme.dark]` 后，右上角 ⋮ 菜单出现 System / Light / Dark，默认跟随系统。两个容易踩的坑（样机实测）：

- `chartCategoricalColors` 只能写在 `[theme]`，写进子表会被静默忽略。
- 它必须**正好 10 个**：Streamlit 的 Plotly 模板有 10 个占位色，前端按下标替换，少配的会变成字符串 `"undefined"`，Plotly 判定整套 colorway 无效，图表退回 Plotly 默认色（样机里总览页饼图就因此是蓝/橙/绿默认色）。第 9、10 个循环使用第 1、2 个。

本任务结束时旧 `ui.py` 仍在注入自己的大段 CSS，页面外观处于新旧混合的过渡状态，属预期；任务 4 换掉 `ui.py` 后恢复正常。

**Files:**
- Modify: `.streamlit/config.toml`（整体重写）
- Create: `app/styles/base.css`
- Test: `tests/test_theme.py`

- [ ] **Step 1: 写测试**

测试内实现 WCAG 2 对比度公式，检查正文、次要文字、主色在页面底色与卡片底色上都 ≥ 4.5:1，主按钮上的字 ≥ 4.5:1；并检查令牌与原生主题色一致。

**写入 `tests/test_theme.py`：**

```python
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
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_theme.py -q
```

预期：失败——收集阶段报 `FileNotFoundError`（`app/styles/base.css` 不存在）。

- [ ] **Step 3: 重写原生主题配置**

**写入 `.streamlit/config.toml`：**

```toml
# 原生双主题：右上角 ⋮ → System / Light / Dark，默认跟随系统（设计文档 4.1）。
# 自定义 HTML 的颜色在 app/styles/base.css 的 light-dark() 令牌里，deck.gl 图层在 app/palette.py。

[theme]
font = "Segoe UI Variable Text, Segoe UI, PingFang SC, Microsoft YaHei UI, Noto Sans SC, sans-serif"
codeFont = "Cascadia Mono, JetBrains Mono, Consolas, monospace"
baseRadius = "0.6rem"
showWidgetBorder = true
headingFontSizes = ["1.75rem", "1.375rem", "1.125rem", "1rem", "0.9rem", "0.8rem"]
# 只能全局配一套（写在 light/dark 子表里会被忽略）；前 8 个与 app/palette.py 的 PALETTE 一致。
# 必须正好 10 个：Streamlit 的 Plotly 模板有 10 个占位色，少配的会被替换成 "undefined"，
# 整套 colorway 失效、图表退回 Plotly 默认色。第 9、10 个循环使用第 1、2 个。
chartCategoricalColors = ["#2563EB", "#C2410C", "#0D9488", "#B45309", "#DB2777", "#8B5CF6", "#15803D", "#DC2626", "#2563EB", "#C2410C"]

[theme.light]
primaryColor = "#0F766E"
backgroundColor = "#F5F5F2"
secondaryBackgroundColor = "#FFFFFF"
textColor = "#1B1D1F"
borderColor = "#E4E3DE"
linkColor = "#0F766E"
codeBackgroundColor = "#F0F0EC"
dataframeHeaderBackgroundColor = "#F7F7F4"

[theme.light.sidebar]
backgroundColor = "#EEEEEA"
secondaryBackgroundColor = "#FFFFFF"

[theme.dark]
primaryColor = "#F5B83D"
backgroundColor = "#0A0F1A"
secondaryBackgroundColor = "#111827"
textColor = "#E7ECF3"
borderColor = "#243044"
linkColor = "#F5B83D"
codeBackgroundColor = "#0D1420"
dataframeHeaderBackgroundColor = "#0D1420"

[theme.dark.sidebar]
backgroundColor = "#0C121E"
secondaryBackgroundColor = "#111827"

[client]
toolbarMode = "viewer"

[server]
headless = true
```

- [ ] **Step 4: 写设计令牌与看板组件样式**

令牌用 `light-dark()` 定义：Streamlit 把 `color-scheme` 写在 `.stApp` 上，浏览器据此取色，切换主题不需要重跑脚本。`[data-testid]` 只出现在文件末尾登记过的增强样式 #1–#3 里，失效时只退回原生外观。

**写入 `app/styles/base.css`：**

```css
/* GeoScope 设计令牌：light-dark() 跟随 Streamlit 写在 .stApp 上的 color-scheme，
   切换主题不需要重跑脚本。自己输出的 HTML 只用这些令牌取色（设计文档 4.2）。 */
.stApp {
  --gs-panel: light-dark(#FFFFFF, #111827);
  --gs-soft: light-dark(#F7F7F4, #0D1420);
  --gs-line: light-dark(#E4E3DE, #243044);
  --gs-text: light-dark(#1B1D1F, #E7ECF3);
  --gs-muted: light-dark(#6A6F73, #8B97A8);
  --gs-accent: light-dark(#0F766E, #F5B83D);
  --gs-accent-soft: light-dark(#E3F1EE, rgba(245, 184, 61, .14));
  --gs-accent-ink: light-dark(#FFFFFF, #1A1203);
  --gs-user: light-dark(#EEF0EC, rgba(56, 213, 245, .10));
  --gs-user-line: light-dark(transparent, rgba(56, 213, 245, .28));
  --gs-ok: light-dark(#15803D, #34D399);
}

/* 主题监听组件不显示内容 */
.st-key-geoscope_theme_watch { display: none; }

/* 页头 */
.gs-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding-bottom: 14px; margin-bottom: 4px; border-bottom: 1px solid var(--gs-line); }
.gs-header h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -.01em; margin: 0; padding: 0; color: var(--gs-text); }
.gs-header p { margin: .35rem 0 0; color: var(--gs-muted); font-size: .875rem; }
.gs-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.gs-tag { font-size: .75rem; color: var(--gs-muted); border: 1px solid var(--gs-line); border-radius: 999px;
  padding: 3px 10px; background: var(--gs-panel); }
.gs-tag.live::before { content: ""; display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: var(--gs-ok); margin-right: 6px; vertical-align: 1px; }

/* KPI 卡片：左侧色条用数据源色 */
.gs-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: .8rem 0 1rem; }
.gs-kpi { background: var(--gs-panel); border: 1px solid var(--gs-line); border-radius: 12px;
  padding: 14px 16px 12px 18px; position: relative; }
.gs-kpi::before { content: ""; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
  border-radius: 0 3px 3px 0; background: var(--kc, var(--gs-accent)); }
.gs-kpi .l { font-size: .8rem; color: var(--gs-muted); }
.gs-kpi .v { font-size: 1.6rem; font-weight: 700; margin-top: 2px; color: var(--gs-text); letter-spacing: -.01em; }
.gs-kpi .c { font-size: .75rem; color: var(--gs-muted); margin-top: 2px; }

/* 区块标题 */
.gs-panel-t { font-size: 1rem; font-weight: 650; color: var(--gs-text); margin: 1rem 0 .5rem;
  display: flex; align-items: center; gap: 8px; }
.gs-panel-t::before { content: ""; width: 6px; height: 6px; border-radius: 2px; background: var(--gs-accent); }

/* 图例 */
.gs-legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: .55rem 0 .2rem; font-size: .8rem; color: var(--gs-muted); }
.gs-legend i { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }

/* 新闻条目 */
.gs-news { border-left: 2px solid var(--gs-line); padding: 2px 0 2px 12px; margin-bottom: 11px; }
.gs-news:hover { border-left-color: var(--gs-accent); }
.gs-news .m { font-size: .75rem; color: var(--gs-muted); }
.gs-news .h { font-size: .875rem; color: var(--gs-text); line-height: 1.5; }

/* ---- 增强样式（设计文档 4.3 登记表）：失效时只退回原生外观 ---- */
/* #1 深色主题下主按钮用深色字（琥珀底白字对比度只有 1.78） */
.stApp [data-testid="stBaseButton-primary"],
.stApp [data-testid="stBaseButton-primary"] p { color: var(--gs-accent-ink); }
/* #2 主区域留白收紧 */
.stApp [data-testid="stMainBlockContainer"] { padding: 4rem 1.5rem 1.5rem; }
/* #3 地图圆角描边 */
.stApp [data-testid="stDeckGlJsonChart"] { border: 1px solid var(--gs-line); border-radius: 12px; overflow: hidden; }
```

- [ ] **Step 5: 运行，确认通过**

```bash
python -m pytest tests/test_theme.py -q
```

预期：通过，16 passed。

- [ ] **Step 6: 全量回归**

```bash
python -m pytest tests/ -q
```

预期：通过，246 passed。

- [ ] **Step 7: 提交**

```bash
git add .streamlit/config.toml app/styles/base.css tests/test_theme.py && \
  git commit -m "feat(ui): 原生双主题配置与设计令牌" -m "config.toml 改为 [theme.light]/[theme.dark] + 侧栏子表，分类色板配满 10 个；app/styles/base.css 用 light-dark() 定义令牌。测试检查令牌与原生主题一致、文字对比度 ≥ 4.5:1。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 3: 主题监听组件 `app/theme_watch.py`

deck.gl 图层在 WebGL 里绘制，CSS 管不到，Python 需要知道当前是深色还是浅色。这里挂一个不显示内容的 `st.components.v2` 组件：Streamlit 在组件的 `data` 或主题变化时重新执行组件 JS，JS 读取 `.stApp` 的 `color-scheme`，与 `data.known` 不同才上报（触发一次重跑）；`busy` 时不上报，避免打断分析。

两处样机里踩过的坑，代码注释里也写了：

1. **`known` 必须是 Python 此刻实际采用的值**（优先取组件上次上报、已生效的值）。如果传"上报前的旧值"，Light → Dark → Light 切回原主题时 JS 会以为没变化而不上报，地图继续用深色配色。
2. **每次运行都调用 `v2.component(...)` 注册**。定义不变时 Streamlit 静默覆盖；只在模块导入时注册一次的话，同一进程里第二个 AppTest（每个都有独立的组件注册表）会报 `Component 'geoscope_theme_watch' is not registered`。

**Files:**
- Create: `app/theme_watch.py`
- Test: `tests/test_theme_watch.py`

- [ ] **Step 1: 写测试**

AppTest 不执行组件 JS，但可以往会话状态里写入组件的上报值，再检查组件收到的 `data`（也就是浏览器端比较用的值）。

**写入 `tests/test_theme_watch.py`：**

```python
"""主题监听组件的回归测试（AppTest）：回退顺序、上报值回传给前端、分析中延后上报。"""

import json

from streamlit.testing.v1 import AppTest

from app import theme_watch


def _page(busy):
    import streamlit as st

    from app import theme_watch

    current = theme_watch.mode(busy=busy)
    st.write(f"watch={current} stored={st.session_state[theme_watch.STATE_KEY]}")


def _app(busy=False):
    app = AppTest.from_function(_page, args=(busy,), default_timeout=20).run()
    assert not app.exception
    return app


def _sent(app):
    """组件收到的 data，也就是浏览器端 JS 用来比较的值。"""
    return json.loads(app.get("bidi_component")[0].proto.json)


def test_without_a_report_mode_falls_back_to_light():
    app = _app()
    assert app.markdown[0].value == "watch=light stored=light"
    assert _sent(app) == {"known": "light", "busy": False}


def test_reported_mode_is_used_and_sent_back_as_known():
    # 回归：上报后必须把"已生效的值"传回前端，否则切回原主题时 JS 以为没变化、不再上报
    app = _app()
    for reported in ("dark", "light", "dark"):
        app.session_state[theme_watch.WATCH_KEY] = {"mode": reported}
        app.run()
        assert app.markdown[0].value == f"watch={reported} stored={reported}"
        assert _sent(app)["known"] == reported


def test_busy_is_forwarded_so_reports_wait_until_the_analysis_ends():
    assert _sent(_app(busy=True)) == {"known": "light", "busy": True}


def test_each_apptest_can_mount_the_watcher():
    # 每个 AppTest 有独立的组件注册表；组件只在导入时注册的话，第二个会报未注册
    for _ in range(2):
        assert _sent(_app())["known"] == "light"
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_theme_watch.py -q
```

预期：失败——收集阶段报 `ImportError: cannot import name 'theme_watch' from 'app'`。

- [ ] **Step 3: 实现**

**写入 `app/theme_watch.py`：**

```python
"""读出浏览器里当前生效的明暗主题，供 deck.gl 图层等 CSS 管不到的配色使用。

主题只能在右上角菜单切换，st.context.theme 在切换瞬间会滞后。这里挂一个不显示内容的
v2 组件：数据或主题变化时 Streamlit 会重新执行组件脚本，脚本读取 .stApp 的
color-scheme，与 Python 已知值不同才上报（触发一次重跑）；busy 时不上报，避免打断分析。
"""

from __future__ import annotations

import streamlit as st
from streamlit.components import v2

STATE_KEY = "_ui_mode"
WATCH_KEY = "geoscope_theme_watch"
MODES = ("light", "dark")

_JS = """
export default function ({ data, setStateValue }) {
  if (!data || data.busy) return;
  requestAnimationFrame(() => {
    const app = document.querySelector('.stApp');
    const scheme = app ? getComputedStyle(app).colorScheme : '';
    if ((scheme === 'light' || scheme === 'dark') && scheme !== data.known) {
      setStateValue('mode', scheme);
    }
  });
}
"""


def mode(busy: bool = False) -> str:
    """返回 "light" / "dark" 并记入会话状态；拿不到时依次回退到 st.context 与浅色。"""
    reported = (st.session_state.get(WATCH_KEY) or {}).get("mode")  # 组件上次上报、已生效的值
    context = st.context.theme.type
    current = reported if reported in MODES else (
        st.session_state.get(STATE_KEY) or (context if context in MODES else "light"))
    # known 必须是 Python 此刻实际采用的值。若传入上报前的旧值，浏览器切回原主题时
    # JS 会以为"没变化"而不上报（Light → Dark → Light 后仍按深色配色）。
    # 每次运行都注册：定义不变时 Streamlit 静默覆盖。只在导入时注册一次的话，同一进程里
    # 第二个 AppTest（各自独立的组件注册表）会报 "Component ... is not registered"
    component = v2.component(WATCH_KEY, js=_JS)
    component(key=WATCH_KEY, data={"known": current, "busy": busy}, on_mode_change=lambda: None)
    st.session_state[STATE_KEY] = current
    return current
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_theme_watch.py -q
```

预期：通过，4 passed。

- [ ] **Step 5: 提交**

```bash
git add app/theme_watch.py tests/test_theme_watch.py && \
  git commit -m "feat(ui): 主题监听组件 theme_watch" -m "v2 组件读取 .stApp 的 color-scheme，与 Python 当前采用的主题不同才上报，分析进行中延后上报；每次运行注册组件以兼容多个 AppTest。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 4: 看板公共层与 6 个看板页换皮

`ui.py` 删掉三套 THEMES、主题下拉框和约 400 行内嵌 CSS，只保留看板组件，并新增 `mode()`、`fit_bounds()`、`inject_css()`、`tooltip_style()`。`fit_bounds` 按名义视口在 Web 墨卡托投影下分别算经、纬两向需要的缩放并取较小值（纬度跨度大时与按度数线性计算差别明显），限制在 2–9 级，单点用 7 级。

6 个看板页仍在 `app/pages/` 下（任务 6 改名），只改导入方式、配色调用、占位文案和少量参数。导入统一为 `from app import palette, ui`，避免同一模块以 `ui` 与 `app.ui` 两个名字各加载一份。

旧工作台页面（此时仍是 `app/GeoAgent.py`）的 `chat_ui.setup()` 调用了被删除的 `ui._is_light()`，用一行过渡代码保持它可用，任务 7 重写 `chat_ui.py` 时消失。

**Files:**
- Modify: `app/ui.py`（整体重写）
- Modify: `app/pages/1_总览.py` … `app/pages/6_全球背景参考.py`（整体重写）
- Modify: `app/chat_ui.py:22`（过渡）
- Test: `tests/test_ui.py`、`scripts/smoke_test.py`

- [ ] **Step 1: 写测试**

`test_dashboards_use_the_design_system` 防止页面里残留换皮前的霓虹色、`accent=` 参数、旧导入和旧文案。

**写入 `tests/test_ui.py`：**

```python
"""看板公共层：视野计算，以及 6 个看板页都已接入设计系统（设计文档 7.4、第 8 节）。"""

from pathlib import Path

from app import ui

DASHBOARDS = Path(__file__).resolve().parents[1] / "app" / "pages"
# 换皮前写死在页面里的霓虹色、旧接口和旧文案
LEGACY = ("#22d3ee", "#fbbf24", "#f87171", "#a78bfa", "#34d399", "#60a5fa", "#f472b6", "#fb923c",
          "accent=", "use_container_width", "\nimport ui\n", "from db import", "（默认全部）", "GeoAgent")


def test_fit_bounds_uses_web_mercator():
    # 10°N–30°N 在墨卡托下比按度数算更"高"：缩放 3.80，按度数线性算会得到 3.90
    assert ui.fit_bounds(30.0, 10.0, 50.0, 30.0) == (20.322, 40.0, 3.8)


def test_fit_bounds_limits():
    assert ui.fit_bounds(43.3, 12.6, 43.3, 12.6) == (12.6, 43.3, 7.0)  # 单点
    assert ui.fit_bounds(-180, -60, 180, 70)[2] == 2.0  # 全球范围不低于 2 级
    assert ui.fit_bounds(43.30, 12.60, 43.35, 12.65)[2] == 9.0  # 小范围不高于 9 级


def test_dashboards_use_the_design_system():
    pages = sorted(DASHBOARDS.glob("*.py"))
    assert len(pages) == 6
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert "from app import palette, ui" in text or "from app import ui" in text, page.name
        assert not [token for token in LEGACY if token.lower() in text.lower()], page.name
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_ui.py -q
```

预期：失败，3 failed（`ui` 没有 `fit_bounds`；看板页仍含 `#22d3ee`、`accent=` 等）。

- [ ] **Step 3: 重写 `app/ui.py`**

**写入 `app/ui.py`：**

```python
"""看板页共用组件：页面初始化、页头、KPI、图例、区块标题、地图与图表封装。

颜色分三路：控件 / 图表 / 底图走 .streamlit/config.toml 的原生主题；自己输出的 HTML
走 styles/base.css 里用 light-dark() 定义的令牌；deck.gl 图层在 WebGL 里绘制，
CSS 管不到，按 mode() 从 app.palette 取色。
"""

from __future__ import annotations

import html
import math
from pathlib import Path

import pydeck as pdk
import streamlit as st

from app import palette, theme_watch

STYLES = Path(__file__).with_name("styles")

# 数据源色（RGB），pydeck 图层直接使用
C_AIS = palette.rgb(palette.SOURCE["ais"])
C_ACLED = palette.rgb(palette.SOURCE["acled"])
C_GDELT = palette.rgb(palette.SOURCE["gdelt"])
C_NEWS = palette.rgb(palette.SOURCE["news"])

_TOOLTIP = {
    "light": {"backgroundColor": "#FFFFFF", "color": "#1B1D1F", "border": "1px solid #E4E3DE"},
    "dark": {"backgroundColor": "#111827", "color": "#E7ECF3", "border": "1px solid #243044"},
}
_TOOLTIP_BASE = {"fontSize": "12px", "borderRadius": "8px", "padding": "8px 10px",
                 "boxShadow": "0 8px 24px rgba(0, 0, 0, .18)"}


def inject_css(*names: str) -> None:
    css = "\n".join((STYLES / name).read_text(encoding="utf-8") for name in names)
    st.html(f"<style>{css}</style>")


def setup(title: str, *, watch: bool = True) -> None:
    """每个页面第一个调用。watch=False 时由页面在合适的时机自行调用 theme_watch.mode。"""
    st.set_page_config(page_title=f"{title} · GeoScope", layout="wide", initial_sidebar_state="expanded")
    inject_css("base.css")
    if watch:
        theme_watch.mode()


def mode() -> str:
    """本次运行中已确定的主题（由 setup 或 theme_watch.mode 写入会话状态）。"""
    current = st.session_state.get(theme_watch.STATE_KEY)
    return current if current in palette.MODES else "light"


def tooltip_style() -> dict:
    return {**_TOOLTIP_BASE, **_TOOLTIP[mode()]}


def _mercator(lat: float) -> float:
    lat = max(-85.0, min(85.0, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def fit_bounds(left: float, bottom: float, right: float, top: float,
               viewport: tuple[int, int] = (720, 560), padding: float = 0.12) -> tuple[float, float, float]:
    """(纬度, 经度, 缩放)：按名义视口在 Web 墨卡托投影下分别算出经纬两向需要的缩放，
    取较小值并留边距，限制在 2–9 级；极小范围用 7 级。中心取墨卡托中点（算术中点会让
    高纬度范围的上下边距明显不等）。"""
    width, height = viewport
    if max(right - left, top - bottom) < 0.01:
        zoom = 7.0
    else:
        zoom_x = math.log2(width * (1 - 2 * padding) * 360 / (512 * max(right - left, 1e-9)))
        zoom_y = math.log2(height * (1 - 2 * padding) * 2 * math.pi
                           / (512 * max(_mercator(top) - _mercator(bottom), 1e-9)))
        zoom = min(zoom_x, zoom_y)
    return ((bottom + top) / 2, (left + right) / 2, round(max(2.0, min(9.0, zoom)), 2))


def page_header(title: str, subtitle: str = "", chips: list | None = None) -> None:
    """chips: [文本] 或 [(文本, "live")]，live 带绿色状态点。"""
    tags = []
    for chip in chips or []:
        text, kind = chip if isinstance(chip, tuple) else (chip, "")
        tags.append(f'<span class="gs-tag {kind}">{html.escape(str(text))}</span>')
    st.markdown(
        f'<div class="gs-header"><div><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>'
        f'<div class="gs-tags">{"".join(tags)}</div></div>', unsafe_allow_html=True,
    )


def kpi_row(items: list) -> None:
    """items: [(标签, 数值, 说明)] 或 [(标签, 数值, 说明, "#色值")]；不给颜色时用主色。"""
    cards = []
    for item in items:
        label, value, caption = item[0], item[1], item[2]
        style = f' style="--kc:{item[3]}"' if len(item) > 3 else ""
        cards.append(f'<div class="gs-kpi"{style}><div class="l">{label}</div>'
                     f'<div class="v">{value}</div><div class="c">{caption}</div></div>')
    st.markdown(f'<div class="gs-kpis">{"".join(cards)}</div>', unsafe_allow_html=True)


def legend(items: list) -> None:
    """items: [(名称, [r, g, b])] 或 [(名称, "#色值")]。"""
    chips = []
    for name, color in items:
        css = color if isinstance(color, str) else f"rgb({color[0]},{color[1]},{color[2]})"
        chips.append(f'<span><i style="background:{css}"></i>{html.escape(name)}</span>')
    st.markdown(f'<div class="gs-legend">{"".join(chips)}</div>', unsafe_allow_html=True)


def panel(title: str) -> None:
    st.markdown(f'<div class="gs-panel-t">{html.escape(title)}</div>', unsafe_allow_html=True)


def deck(layers, lat: float, lon: float, zoom: float, tooltip=None, height: int = 560) -> None:
    """不传 map_style：Streamlit 前端按主题选 Positron / Dark Matter 底图。"""
    tip = {"text": tooltip, "style": tooltip_style()} if isinstance(tooltip, str) else tooltip
    st.pydeck_chart(
        pdk.Deck(map_style=None, layers=layers, tooltip=tip,
                 initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom, pitch=0)),
        height=height,
    )


def chart(fig, height: int = 320) -> None:
    """theme="streamlit"：坐标轴、网格、悬浮框与分类色板都跟随当前主题。"""
    st.plotly_chart(style_fig(fig, height), width="stretch", theme="streamlit")


def style_fig(fig, height: int = 320):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=14, b=0), bargap=0.25,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, title_text=""))
    return fig
```

- [ ] **Step 4: 让旧工作台继续可用（过渡）**

**修改 `app/chat_ui.py`，把：**

```python
    light = ui._is_light()
```

**替换为：**

```python
    light = ui.mode() == "light"  # 过渡：任务 7 重写本文件
```

- [ ] **Step 5: 总览页换皮**

改动：导入与 `ui.setup("总览")` + `mode = ui.mode()`；导航表换成新导航名（工作台、AIS 船舶、ACLED 事件、GDELT 背景）；KPI 色条用数据源色；事件热度图用 ACLED 红顺序色阶、按全部事件范围定位（原来偏南，以色列 / 黎巴嫩落在画面外）、热力参数 `radius_pixels=34`、`intensity=4`、`threshold=0.02`，图例按色阶；危机演化用阶段有序色阶并固定顺序；AIS Top 10 用 AIS 蓝；国家分布用红顺序色阶；新闻条目用 `.gs-news`；删除未使用的 `pandas` 导入。

**写入 `app/pages/1_总览.py`：**

```python
import sys
from pathlib import Path

import plotly.express as px
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("总览")
mode = ui.mode()
ui.page_header(
    "GeoScope · 红海危机时空态势",
    "2023 下半年红海危机专题 —— AIS 船舶动态 · ACLED 危机事件（LLM 筛选增强）· 新闻原文 · GDELT 全球背景",
    chips=[("DATA ONLINE", "live"), "专题窗口 2023-07 ~ 2023-12"],
)

with st.expander("页面导航：我该用哪一页？", expanded=False):
    st.markdown(
        """
| 页面 | 什么时候用 |
| --- | --- |
| **工作台**（推荐入口） | 直接用大白话提问：查数、缓冲区分析、航迹查询、事件背景问答，结果自动上图 |
| **AIS 船舶** | 看具体船舶的航行轨迹与密度分布，按时间窗筛选 |
| **ACLED 事件** | 浏览红海危机事件清单：风险等级 / 咽喉要道 / 伤亡等多维筛选 |
| **时空叠加** | 把船舶轨迹和危机事件叠在一张图上，观察袭击与航运的时空关联 |
| **新闻检索** | 按英文关键词全文检索报道原文（对话式问背景请直接用工作台） |
| **GDELT 背景** | 全球媒体舆情背景（非红海专题数据），用于对比全球冲突基调 |
"""
    )

# ---- KPI ----
stats = {
    "AIS 位置点": ("ais_positions", "ts", palette.SOURCE["ais"], "红海海域 88 天"),
    "ACLED 危机事件": ("acled_events", "event_date", palette.SOURCE["acled"], "LLM 筛选增强版"),
    "新闻原文": ("news_articles", "published_at", palette.SOURCE["news"], "关联 ACLED 事件"),
    "GDELT 背景事件": ("gdelt_events", "event_date", palette.SOURCE["gdelt"], "全球背景参考"),
}
kpis = []
for name, (table, tcol, color, note) in stats.items():
    df = query(f"SELECT COUNT(*) n, MIN({tcol}) a, MAX({tcol}) b FROM {table}")
    n = int(df["n"][0])
    cap = f"{str(df['a'][0])[:10]} ~ {str(df['b'][0])[:10]} · {note}" if n else "暂无数据"
    kpis.append((name, f"{n:,}", cap, color))
ui.kpi_row(kpis)

left, right = st.columns([3, 2], gap="medium")

with left:
    ui.panel("红海危机事件热度（ACLED）")
    pts = query("SELECT lat, lon FROM acled_events WHERE lat IS NOT NULL")
    if pts.empty:
        st.info("暂无事件数据")
    else:
        lat, lon, zoom = ui.fit_bounds(pts["lon"].min(), pts["lat"].min(), pts["lon"].max(), pts["lat"].max(),
                                       viewport=(760, 480))
        ramp = palette.sequential("red", mode)
        ui.deck(
            [
                pdk.Layer(
                    "HeatmapLayer",
                    data=pts,
                    get_position="[lon, lat]",
                    radius_pixels=34,
                    intensity=4,
                    threshold=0.02,
                    color_range=ramp,
                )
            ],
            lat=lat, lon=lon, zoom=zoom, height=480,
        )
        ui.legend([("低", ramp[1][:3]), ("中", ramp[2][:3]), ("较高", ramp[3][:3]), ("高", ramp[5][:3])])

with right:
    ui.panel("危机演化（每周事件 · 按阶段）")
    trend = query(
        """
        SELECT date_trunc('week', event_date) AS 周,
               CASE phase
                   WHEN 'precursor' THEN '前兆期'
                   WHEN 'trigger_chain' THEN '触发链'
                   WHEN 'maritime_crisis' THEN '海上危机期'
                   ELSE '其他' END AS 阶段,
               COUNT(*) AS 事件数
        FROM acled_events GROUP BY 1, 2 ORDER BY 1
        """
    )
    if trend.empty:
        st.info("暂无事件数据")
    else:
        fig = px.bar(trend, x="周", y="事件数", color="阶段", barmode="stack",
                     color_discrete_map=dict(zip(["前兆期", "触发链", "海上危机期"], palette.ordinal(3, mode))),
                     category_orders={"阶段": ["前兆期", "触发链", "海上危机期"]})
        ui.chart(fig, height=260)

    ui.panel("最新相关报道（ACLED 事件原文回填）")
    news = query(
        """
        SELECT published_at, source, title FROM news_articles
        WHERE published_at IS NOT NULL
        ORDER BY published_at DESC LIMIT 5
        """
    )
    if news.empty:
        st.info("暂无新闻数据")
    for _, r in news.iterrows():
        src = str(r["source"])[:36] + ("…" if len(str(r["source"])) > 36 else "")
        st.markdown(
            f'<div class="gs-news"><div class="m">{str(r["published_at"])[:10]} · {src}</div>'
            f'<div class="h">{r["title"]}</div></div>',
            unsafe_allow_html=True,
        )

st.divider()

b1, b2, b3 = st.columns(3, gap="medium")
with b1:
    ui.panel("AIS 活跃船舶 Top 10")
    ships = query(
        """
        SELECT COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS 船舶, COUNT(*) AS 位置点
        FROM ais_positions p LEFT JOIN ais_ships s USING (mmsi)
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """
    )
    if not ships.empty:
        fig = px.bar(ships, x="位置点", y="船舶", orientation="h")
        fig.update_traces(marker_color=palette.SOURCE["ais"])
        fig.update_yaxes(autorange="reversed")
        ui.chart(fig, height=300)
with b2:
    ui.panel("危机事件国家分布")
    by_c = query(
        """
        SELECT country AS 国家, COUNT(*) AS 事件数, SUM(fatalities) AS 死亡
        FROM acled_events GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """
    )
    if not by_c.empty:
        fig = px.bar(by_c, x="国家", y="事件数", color="死亡",
                     color_continuous_scale=list(palette.SEQUENTIAL["red"][mode][1:]))
        ui.chart(fig, height=300)
with b3:
    ui.panel("咽喉要道关联事件")
    choke = query(
        """
        SELECT chokepoint AS 咽喉要道, COUNT(*) AS 事件数
        FROM acled_events WHERE chokepoint IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    if not choke.empty:
        fig = px.pie(choke, names="咽喉要道", values="事件数", hole=0.55)
        ui.chart(fig, height=300)
```

- [ ] **Step 6: AIS 页换皮**

改动：导入与 `ui.setup("AIS 船舶")`；筛选标题改 `st.subheader`，多选框标签去掉"（默认全部）"、加 `placeholder`；船型配色由 8 色改为货船蓝 / 油轮橙 / 其他灰（实际数据货船 2480、油轮 907，客船 3、渔船 1，其余为 0 或未知）；最新位置点改为正文色实心点 + 背景色描边（原方案白点在图例里与页面底色几乎一样，看不出来）；密度热力图用 AIS 蓝顺序色阶；地图按数据范围定位（原来固定 5 级，红海南段被切掉）；`st.dataframe(width="stretch")`。

**写入 `app/pages/2_AIS船舶地图.py`：**

```python
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("AIS 船舶")
mode = ui.mode()
ui.page_header(
    "AIS 船舶时空轨迹",
    "红海海域船舶航行轨迹与密度分析 · 动态位置关联静态船舶档案",
    chips=["红海海域 88 天", "37.6M 位置点"],
)

meta = query("SELECT MIN(ts) a, MAX(ts) b FROM ais_positions")
if meta["a"][0] is None:
    st.info("暂无 AIS 数据，请先入库。")
    st.stop()

tmin, tmax = pd.Timestamp(meta["a"][0]), pd.Timestamp(meta["b"][0])
default_start = max(tmin, tmax - timedelta(hours=24))

with st.sidebar:
    st.subheader("筛选")
    date_range = st.slider(
        "时间窗口",
        min_value=tmin.to_pydatetime(),
        max_value=tmax.to_pydatetime(),
        value=(default_start.to_pydatetime(), tmax.to_pydatetime()),
        format="MM-DD HH:mm",
        help="数据量大，默认展示最后 24 小时",
    )
    ships = query(
        """
        SELECT mmsi, COALESCE(ship_name, CAST(mmsi AS VARCHAR)) AS name
        FROM ais_ships ORDER BY name
        """
    )
    sel_names = st.multiselect("船舶", ships["name"].tolist(), placeholder="全部（可搜索）")
    types = query("SELECT DISTINCT ship_type FROM ais_ships WHERE ship_type IS NOT NULL ORDER BY 1")
    sel_types = st.multiselect("船舶类型", types["ship_type"].tolist(), placeholder="全部")
    view_mode = st.radio("图层模式", ["轨迹线", "密度热力图"], horizontal=True)
    if view_mode == "轨迹线":
        max_ships = st.slider("最多显示船舶数（按活跃度取 Top N）", 20, 500, 120, step=20)

conds, params = ["p.ts BETWEEN ? AND ?"], [date_range[0], date_range[1]]
if sel_names:
    mmsis = ships[ships["name"].isin(sel_names)]["mmsi"].tolist()
    conds.append(f"p.mmsi IN ({','.join(str(m) for m in mmsis)})")
if sel_types:
    quoted = ",".join("'" + t.replace("'", "''") + "'" for t in sel_types)
    conds.append(f"s.ship_type IN ({quoted})")
where = " AND ".join(conds)

BASE = f"""
    FROM ais_positions p
    LEFT JOIN ais_ships s USING (mmsi)
    WHERE {where}
"""

stat = query(f"SELECT COUNT(*) n, COUNT(DISTINCT p.mmsi) ships, AVG(p.sog) sog {BASE}", tuple(params))
n_total, n_ships = int(stat["n"][0]), int(stat["ships"][0])
if n_total == 0:
    st.warning("筛选结果为空")
    st.stop()

hours = max((date_range[1] - date_range[0]).total_seconds() / 3600, 1)
ui.kpi_row([
    ("位置点", f"{n_total:,}", f"时间窗 {hours:.0f} 小时"),
    ("在航船舶", f"{n_ships:,}", "本时间窗内上报过位置"),
    ("平均航速", f"{stat['sog'][0]:.1f} kn", "对地航速"),
    ("船舶档案", f"{query('SELECT COUNT(*) n FROM ais_ships')['n'][0]:,}", "静态数据档案总数"),
])

if view_mode == "轨迹线":
    # 每船每 10 分钟抽稀一个点，并只取活跃度 Top N 船舶，保证渲染流畅
    df = query(
        f"""
        WITH active AS (
            SELECT p.mmsi {BASE}
            GROUP BY p.mmsi ORDER BY COUNT(*) DESC LIMIT {max_ships}
        ),
        thinned AS (
            SELECT DISTINCT ON (p.mmsi, time_bucket(INTERVAL 10 MINUTE, p.ts))
                   p.mmsi, p.ts, p.lat, p.lon,
                   COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS ship_name,
                   COALESCE(s.ship_type, '未知') AS ship_type
            {BASE} AND p.mmsi IN (SELECT mmsi FROM active)
        )
        SELECT * FROM thinned ORDER BY mmsi, ts
        """,
        tuple(params * 2),
    )
    paths = (
        df.groupby(["mmsi", "ship_name", "ship_type"])
        .apply(lambda g: g[["lon", "lat"]].values.tolist(), include_groups=False)
        .reset_index(name="path")
    )
    # 实际数据里货船、油轮占绝大多数，其余船型合计约 5%，归入"其他"（地图上最多 3 类颜色）
    TYPE_COLORS = {"货船": palette.PALETTE[0], "油轮": palette.PALETTE[1], "其他": palette.OTHER_GRAY[mode]}
    paths["color"] = paths["ship_type"].map(lambda t: palette.rgb(TYPE_COLORS.get(t, TYPE_COLORS["其他"])))
    marker = palette.MAP[mode]  # 最新位置：正文色实心点 + 背景色描边，两种主题下都醒目
    last_pos = df.sort_values("ts").groupby("mmsi").tail(1)
    layers = [
        pdk.Layer(
            "PathLayer",
            data=paths,
            get_path="path",
            get_color="color",
            width_min_pixels=2,
            opacity=0.75,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=last_pos,
            get_position="[lon, lat]",
            get_radius=2200,
            get_fill_color=palette.rgb(marker["ring"]),
            get_line_color=palette.rgb(marker["stroke"]),
            line_width_min_pixels=1,
            stroked=True,
            pickable=True,
        ),
    ]
    tooltip = "{ship_name} ({ship_type})"
    st.caption(f"轨迹已按活跃度取 Top {min(max_ships, paths.shape[0])} 艘、每 10 分钟抽稀")
else:
    # 热力图 12 万采样点在视觉上与 40 万几乎无差别，但浏览器渲染负担小得多
    df = query(
        f"SELECT p.lat, p.lon {BASE} USING SAMPLE reservoir(120000 ROWS) REPEATABLE (42)",
        tuple(params),
    )
    layers = [
        pdk.Layer(
            "HeatmapLayer",
            data=df[["lon", "lat"]],
            get_position="[lon, lat]",
            radius_pixels=28,
            color_range=palette.sequential("blue", mode),
        )
    ]
    tooltip = None

lat, lon, zoom = ui.fit_bounds(df["lon"].min(), df["lat"].min(), df["lon"].max(), df["lat"].max(),
                               viewport=(1100, 560))
ui.deck(layers, lat=lat, lon=lon, zoom=zoom, tooltip=tooltip, height=560)
if view_mode == "轨迹线":
    ui.legend(list(TYPE_COLORS.items()) + [("最新位置", marker["ring"])])

ui.panel("船舶概况（本时间窗 Top 200）")
summary = query(
    f"""
    SELECT COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS 船名, p.mmsi AS MMSI,
           COALESCE(s.ship_type, '未知') AS 类型, s.length_m AS 船长_米,
           s.destination AS 目的地, COUNT(*) AS 位置点数,
           ROUND(AVG(p.sog), 1) AS 平均航速_节, MAX(p.ts) AS 最后上报时间
    {BASE}
    GROUP BY 1, 2, 3, 4, 5 ORDER BY 位置点数 DESC LIMIT 200
    """,
    tuple(params),
)
st.dataframe(summary, width="stretch", hide_index=True)
```

- [ ] **Step 7: ACLED 页换皮**

改动：导入与 `ui.setup("ACLED 事件")`；危机阶段用 3 级有序色阶（未知阶段用"其他"灰）；筛选标题与多选框同上；地图按事件范围定位；每周时间线固定阶段顺序；因果角色、咽喉要道柱图用 ACLED 红；AIS 关联层级饼图用 4 级有序色阶并固定顺序；动能 / 非动能用 ACLED 红 / 蓝；`st.dataframe(width="stretch")`。

**写入 `app/pages/3_ACLED事件.py`：**

```python
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("ACLED 事件")
mode = ui.mode()
ui.page_header(
    "ACLED 红海危机事件",
    "LLM 筛选增强版 · 危机阶段 / 风险等级 / 因果角色 / AIS 关联层级 / 咽喉要道 全维度标注",
    chips=["LLM 筛选增强", "1,565 事件"],
)

meta = query("SELECT MIN(event_date) a, MAX(event_date) b FROM acled_events")
if meta["a"][0] is None:
    st.info("暂无 ACLED 数据，请先入库。")
    st.stop()

dmin, dmax = pd.Timestamp(meta["a"][0]).date(), pd.Timestamp(meta["b"][0]).date()

PHASE_LABELS = {
    "precursor": "前兆期",
    "trigger_chain": "触发链",
    "maritime_crisis": "海上危机期",
}
# 危机阶段是有序类别：单一红色由浅到深（深色主题由暗到亮）
PHASE_COLORS = dict(zip(PHASE_LABELS, (palette.rgb(c) for c in palette.ordinal(3, mode))))
CAUSAL_LABELS = {
    "direct_maritime_attack": "直接海上袭击",
    "coalition_response": "联军回应",
    "coastal_control": "沿岸控制",
    "regional_escalation": "地区升级",
    "geopolitical_context": "地缘背景",
}
TIER_LABELS = {
    "tier_A_direct": "A级·直接相关",
    "tier_A_enabling": "A级·支撑行动",
    "tier_B_signal": "B级·信号事件",
    "tier_C_context": "C级·背景事件",
}
DOMAIN_LABELS = {"maritime": "海上", "air": "空中", "land": "陆上"}

with st.sidebar:
    st.subheader("筛选")
    d1, d2 = st.date_input("日期范围", (dmin, dmax), min_value=dmin, max_value=dmax)
    sel_phase = st.multiselect(
        "危机阶段", list(PHASE_LABELS.keys()),
        format_func=lambda x: PHASE_LABELS.get(x, x), placeholder="全部",
    )
    risk_range = st.slider("风险等级", 1, 5, (1, 5))
    sel_causal = st.multiselect(
        "危机因果角色", list(CAUSAL_LABELS.keys()),
        format_func=lambda x: CAUSAL_LABELS.get(x, x), placeholder="全部",
    )
    sel_tier = st.multiselect(
        "AIS 关联层级", list(TIER_LABELS.keys()),
        format_func=lambda x: TIER_LABELS.get(x, x), placeholder="全部",
    )
    sel_domain = st.multiselect(
        "事件域", list(DOMAIN_LABELS.keys()),
        format_func=lambda x: DOMAIN_LABELS.get(x, x), placeholder="全部",
    )
    countries = query("SELECT DISTINCT country FROM acled_events ORDER BY 1")
    sel_countries = st.multiselect("国家", countries["country"].tolist(), placeholder="全部")
    only_kinetic = st.checkbox("仅动能事件")
    only_vessel = st.checkbox("仅船舶目标事件")


def _in(col, vals):
    return f"{col} IN (" + ",".join("'" + v.replace("'", "''") + "'" for v in vals) + ")"


conds, params = ["event_date BETWEEN ? AND ?", "risk_level BETWEEN ? AND ?"], [d1, d2, *risk_range]
if sel_phase:
    conds.append(_in("phase", sel_phase))
if sel_causal:
    conds.append(_in("causal_role", sel_causal))
if sel_tier:
    conds.append(_in("ais_tier", sel_tier))
if sel_domain:
    conds.append(_in("domain", sel_domain))
if sel_countries:
    conds.append(_in("country", sel_countries))
if only_kinetic:
    conds.append("is_kinetic")
if only_vessel:
    conds.append("target_class = 'vessel'")
where = " AND ".join(conds)

df = query(f"SELECT * FROM acled_events WHERE {where}", tuple(params))

if df.empty:
    st.warning("筛选结果为空")
    st.stop()

tier_a = int(df["ais_tier"].str.startswith("tier_A").sum())
ui.kpi_row([
    ("事件总数", f"{len(df):,}",
     f"{df['country'].nunique()} 个国家 · 平均风险 {df['risk_level'].mean():.1f}/5"),
    ("A级 AIS 关联", f"{tier_a}",
     f"直接影响航运 · 5级事件 {int((df['risk_level'] == 5).sum())} 起"),
    ("海上域事件", f"{int((df['domain'] == 'maritime').sum())}",
     f"船舶目标 {int((df['target_class'] == 'vessel').sum())} 起"),
    ("死亡总数", f"{int(df['fatalities'].sum()):,}",
     f"动能事件 {int(df['is_kinetic'].sum())} 起"),
])

df["color"] = df["phase"].map(lambda p: PHASE_COLORS.get(p, palette.rgb(palette.OTHER_GRAY[mode])))
df["phase_cn"] = df["phase"].map(PHASE_LABELS).fillna("未知")
df["causal_cn"] = df["causal_role"].map(CAUSAL_LABELS).fillna(df["causal_role"])

lat, lon, zoom = ui.fit_bounds(df["lon"].min(), df["lat"].min(), df["lon"].max(), df["lat"].max(),
                               viewport=(1100, 540))
ui.deck(
    [
        pdk.Layer(
            "ScatterplotLayer",
            data=df,
            get_position="[lon, lat]",
            get_radius="4000 + risk_level * 5000",
            get_fill_color="color",
            opacity=0.6,
            pickable=True,
        )
    ],
    lat=lat, lon=lon, zoom=zoom,
    tooltip="{phase_cn} · 风险{risk_level}级\n{event_type} / {sub_event_type}\n{location}, {country} · {event_date}\n因果角色: {causal_cn}\n咽喉要道: {chokepoint}",
    height=540,
)
ui.legend([(PHASE_LABELS[p], c) for p, c in PHASE_COLORS.items()])
st.caption("点径 = 风险等级 · 颜色 = 危机阶段")

left, right = st.columns(2, gap="medium")
with left:
    ui.panel("危机演化时间线（每周 · 按阶段）")
    weekly = (
        df.assign(week=pd.to_datetime(df["event_date"]).dt.to_period("W").dt.start_time)
        .groupby(["week", "phase_cn"]).size().reset_index(name="事件数")
    )
    fig = px.bar(weekly, x="week", y="事件数", color="phase_cn", barmode="stack",
                 color_discrete_map={PHASE_LABELS[p]: f"rgb({c[0]},{c[1]},{c[2]})"
                                     for p, c in PHASE_COLORS.items()},
                 category_orders={"phase_cn": list(PHASE_LABELS.values())},
                 labels={"week": "周", "phase_cn": "阶段"})
    ui.chart(fig, height=320)
with right:
    ui.panel("危机因果角色分布")
    causal = df["causal_cn"].value_counts().reset_index()
    causal.columns = ["因果角色", "事件数"]
    fig = px.bar(causal, x="事件数", y="因果角色", orientation="h")
    fig.update_traces(marker_color=palette.SOURCE["acled"])
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig, height=320)

c1, c2, c3 = st.columns(3, gap="medium")
with c1:
    ui.panel("咽喉要道关联")
    choke = (
        df.groupby("chokepoint")
        .agg(事件数=("event_id", "count"), 平均距离_km=("chokepoint_km", "mean"))
        .reset_index().dropna()
    )
    choke["平均距离_km"] = choke["平均距离_km"].round(0)
    fig = px.bar(choke, x="chokepoint", y="事件数", hover_data=["平均距离_km"])
    fig.update_traces(marker_color=palette.SOURCE["acled"])
    fig.update_layout(xaxis_title=None)
    ui.chart(fig, height=280)
with c2:
    ui.panel("AIS 关联层级")
    tier = df["ais_tier"].map(TIER_LABELS).value_counts().reset_index()
    tier.columns = ["层级", "事件数"]
    # 关联层级同样有序：C 背景 → B 信号 → A 支撑 → A 直接
    tier_order = [TIER_LABELS[t] for t in ("tier_C_context", "tier_B_signal", "tier_A_enabling", "tier_A_direct")]
    fig = px.pie(tier, names="层级", values="事件数", hole=0.55, color="层级",
                 color_discrete_map=dict(zip(tier_order, palette.ordinal(4, mode))),
                 category_orders={"层级": tier_order})
    ui.chart(fig, height=280)
with c3:
    ui.panel("事件域 × 动能")
    dom = (
        df.assign(域=df["domain"].map(DOMAIN_LABELS), 动能=df["is_kinetic"].map({True: "动能", False: "非动能"}))
        .groupby(["域", "动能"]).size().reset_index(name="事件数")
    )
    fig = px.bar(dom, x="域", y="事件数", color="动能", barmode="group",
                 color_discrete_map={"动能": palette.SOURCE["acled"], "非动能": palette.PALETTE[0]})
    fig.update_layout(xaxis_title=None)
    ui.chart(fig, height=280)

ui.panel("事件明细")
show_all = st.toggle("显示全部字段（25 个入库字段：专题标注、AIS 层级、港口/咽喉要道距离等）")
if show_all:
    full = df.drop(columns=["color", "phase_cn", "causal_cn"], errors="ignore").copy()
    full["event_date"] = pd.to_datetime(full["event_date"]).dt.date
    full = full.sort_values("event_date", ascending=False)
    st.dataframe(full, width="stretch", hide_index=True, height=420)
else:
    detail = df[["event_date", "phase_cn", "risk_level", "causal_cn", "event_type",
                 "sub_event_type", "country", "location", "target_class", "chokepoint",
                 "fatalities", "notes"]].copy()
    detail["event_date"] = pd.to_datetime(detail["event_date"]).dt.date
    detail = detail.sort_values("event_date", ascending=False)
    detail.columns = ["日期", "阶段", "风险", "因果角色", "事件类型", "子类型", "国家",
                      "地点", "目标类型", "咽喉要道", "死亡", "描述"]
    st.dataframe(detail, width="stretch", hide_index=True, height=360)
```

- [ ] **Step 8: 时空叠加页换皮**

改动：导入与 `ui.setup("时空叠加")`；ACLED 点按关联层级用 4 级有序色阶；筛选标题与多选框同上；KPI 色条用数据源色；所选区域按查询范围定位（原来所有区域都固定 5 级：红海全域显示不全、曼德海峡又显得过远），"全球"保持 1.8 级。

**写入 `app/pages/4_时空叠加.py`：**

```python
import sys
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("时空叠加")
mode = ui.mode()
ui.page_header(
    "红海危机 · 时空叠加分析",
    "AIS 船舶轨迹叠加 ACLED 危机事件（按 AIS 关联层级着色）· 观察袭击事件与航运动态的时空关联",
    chips=["AIS × ACLED 联动", "2023-10 ~ 2023-12"],
)

ais_meta = query("SELECT MIN(ts) a, MAX(ts) b FROM ais_positions")
if ais_meta["a"][0] is None:
    st.info("暂无数据，请先入库。")
    st.stop()

tmin = pd.Timestamp(ais_meta["a"][0]).date()
tmax = pd.Timestamp(ais_meta["b"][0]).date()

REGIONS = {
    "红海全域": (20.5, 38.5, 9.5),
    "曼德海峡": (12.8, 43.3, 2.5),
    "苏伊士湾": (28.5, 33.0, 2.5),
    "亚丁湾": (12.5, 46.5, 4.0),
    "全球": (20.0, 60.0, None),
}

# AIS 关联层级是有序类别：C → B → A 支撑 → A 直接，单一红色由浅到深（深色主题由暗到亮）
_TIER_RAMP = dict(zip(("tier_C_context", "tier_B_signal", "tier_A_enabling", "tier_A_direct"),
                      (palette.rgb(c) for c in palette.ordinal(4, mode))))
TIER_STYLE = {
    "tier_A_direct": ("A级·直接相关", _TIER_RAMP["tier_A_direct"]),
    "tier_A_enabling": ("A级·支撑行动", _TIER_RAMP["tier_A_enabling"]),
    "tier_B_signal": ("B级·信号事件", _TIER_RAMP["tier_B_signal"]),
    "tier_C_context": ("C级·背景事件", _TIER_RAMP["tier_C_context"]),
}

with st.sidebar:
    st.subheader("筛选")
    region = st.selectbox("关注区域", list(REGIONS.keys()))
    d1, d2 = st.date_input("日期范围", (tmin, tmax))
    show_ais = st.checkbox("AIS 船舶轨迹", True)
    show_acled = st.checkbox("ACLED 危机事件", True)
    sel_tiers = st.multiselect(
        "ACLED · AIS 关联层级",
        list(TIER_STYLE.keys()),
        default=["tier_A_direct", "tier_A_enabling", "tier_B_signal"],
        format_func=lambda t: TIER_STYLE[t][0], placeholder="全部",
        help="A级=直接影响航运的事件，默认隐藏纯背景类事件",
    )
    show_gdelt = st.checkbox("GDELT 背景事件", False)

lat0, lon0, radius = REGIONS[region]
geo_cond = "1=1" if radius is None else (
    f"lat BETWEEN {lat0 - radius} AND {lat0 + radius} "
    f"AND lon BETWEEN {lon0 - radius} AND {lon0 + radius}"
)

layers, kpis, legend_items = [], [], []

if show_ais:
    # 活跃度 Top 150 船舶、每 15 分钟抽稀，避免千万级点位压垮前端
    ais = query(
        f"""
        WITH active AS (
            SELECT mmsi FROM ais_positions
            WHERE {geo_cond} AND ts BETWEEN ? AND ?
            GROUP BY mmsi ORDER BY COUNT(*) DESC LIMIT 150
        )
        SELECT DISTINCT ON (p.mmsi, time_bucket(INTERVAL 15 MINUTE, p.ts))
               p.mmsi, COALESCE(s.ship_name, CAST(p.mmsi AS VARCHAR)) AS ship_name,
               s.ship_type, p.ts, p.lat, p.lon
        FROM ais_positions p
        LEFT JOIN ais_ships s USING (mmsi)
        WHERE {geo_cond.replace('lat', 'p.lat').replace('lon', 'p.lon')}
          AND p.ts BETWEEN ? AND ?
          AND p.mmsi IN (SELECT mmsi FROM active)
        ORDER BY p.mmsi, p.ts
        """,
        (str(d1), str(d2) + " 23:59:59", str(d1), str(d2) + " 23:59:59"),
    )
    kpis.append(("AIS 位置点（抽稀后）", f"{len(ais):,}",
                 f"{ais['mmsi'].nunique() if len(ais) else 0} 艘活跃船舶", palette.SOURCE["ais"]))
    if not ais.empty:
        paths = (
            ais.groupby(["mmsi", "ship_name"])
            .apply(lambda g: g[["lon", "lat"]].values.tolist(), include_groups=False)
            .reset_index(name="path")
        )
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=paths,
                get_path="path",
                get_color=ui.C_AIS + [150],
                width_min_pixels=2,
                pickable=True,
            )
        )
        legend_items.append(("AIS 船舶轨迹", ui.C_AIS))

if show_gdelt:
    gdelt = query(
        f"""
        SELECT event_date, actor1, actor2, event_code, goldstein, lat, lon
        FROM gdelt_events
        WHERE {geo_cond} AND event_date BETWEEN ? AND ? LIMIT 100000
        """,
        (str(d1), str(d2)),
    )
    kpis.append(("GDELT 事件", f"{len(gdelt):,}",
                 f"平均 Goldstein {gdelt['goldstein'].mean():+.1f}" if len(gdelt) else "无", palette.SOURCE["gdelt"]))
    if not gdelt.empty:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=gdelt,
                get_position="[lon, lat]",
                get_radius=6000,
                get_fill_color=ui.C_GDELT + [150],
                pickable=True,
            )
        )
        legend_items.append(("GDELT 事件", ui.C_GDELT))

if show_acled:
    tier_cond = "1=1"
    if sel_tiers:
        tier_cond = "ais_tier IN (" + ",".join(f"'{t}'" for t in sel_tiers) + ")"
    acled = query(
        f"""
        SELECT event_date, event_type, sub_event_type, location, country,
               fatalities, risk_level, phase, ais_tier, chokepoint, lat, lon
        FROM acled_events
        WHERE {geo_cond} AND event_date BETWEEN ? AND ? AND {tier_cond}
        LIMIT 100000
        """,
        (str(d1), str(d2)),
    )
    tier_a = int(acled["ais_tier"].str.startswith("tier_A").sum()) if len(acled) else 0
    kpis.append(("ACLED 危机事件", f"{len(acled):,}",
                 f"A级直接相关 {tier_a} 起", palette.SOURCE["acled"]))
    if not acled.empty:
        acled["color"] = acled["ais_tier"].map(lambda t: TIER_STYLE.get(t, ("", palette.rgb(palette.OTHER_GRAY[mode])))[1])
        acled["tier_cn"] = acled["ais_tier"].map(lambda t: TIER_STYLE.get(t, (t, None))[0])
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=acled,
                get_position="[lon, lat]",
                get_radius="3000 + risk_level * 4000",
                get_fill_color="color",
                opacity=0.75,
                pickable=True,
            )
        )
        for t in (sel_tiers or TIER_STYLE.keys()):
            legend_items.append(TIER_STYLE[t])

if kpis:
    ui.kpi_row(kpis)

if not layers:
    st.warning("当前筛选下没有可显示的数据")
    st.stop()

# 区域按查询范围定位；全球视图低于 fit_bounds 的最小缩放，单独处理
lat, lon, zoom = (lat0, lon0, 1.8) if radius is None else ui.fit_bounds(
    lon0 - radius, lat0 - radius, lon0 + radius, lat0 + radius, viewport=(1100, 620))
ui.deck(
    layers,
    lat=lat, lon=lon, zoom=zoom,
    tooltip="{ship_name}{event_type}{actor1}",
    height=620,
)
ui.legend(legend_items)
```

- [ ] **Step 9: 新闻检索页换皮**

改动：导入与 `ui.setup("新闻检索")`；标题里的"GeoAgent 页"改为"工作台"；报道趋势与来源柱图用新闻紫，面积填充 18%。

**写入 `app/pages/5_新闻检索.py`：**

```python
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("新闻检索")
ui.page_header(
    "新闻文本检索与趋势（问背景/要结论请用工作台，本页适合按关键词翻原文）",
    "全文关键词检索 · 报道热度时间线 · 来源结构分析",
    chips=["ACLED 原文回填", "568 篇"],
)

meta = query("SELECT COUNT(*) n FROM news_articles")
if int(meta["n"][0]) == 0:
    st.info("暂无新闻数据，请先入库。")
    st.stop()

kw = st.text_input("关键词检索（标题+正文，多个关键词空格分隔，AND 关系）", "",
                   placeholder="新闻正文为英文，例如：Houthi vessel / Red Sea attack")

conds, params = [], []
for w in kw.split():
    conds.append("(title ILIKE ? OR body ILIKE ?)")
    params += [f"%{w}%", f"%{w}%"]
where = " AND ".join(conds) if conds else "1=1"

df = query(
    f"""
    SELECT published_at, source, title, body, url, lang, related_event_id
    FROM news_articles WHERE {where}
    ORDER BY published_at DESC NULLS LAST LIMIT 5000
    """,
    tuple(params),
)

if df.empty:
    st.warning("没有匹配的文章")
    st.stop()

valid_dates = pd.to_datetime(df["published_at"]).dropna()
span_days = (valid_dates.max() - valid_dates.min()).days + 1 if len(valid_dates) else 0
ui.kpi_row([
    ("命中文章", f"{len(df):,}", f"检索词：{kw or '（全部）'}"),
    ("涉及来源", f"{df['source'].nunique()}", "按文章 URL 域名统计"),
    ("时间跨度", f"{span_days} 天",
     f"{str(valid_dates.min())[:10]} ~ {str(valid_dates.max())[:10]}" if len(valid_dates) else "无有效日期"),
])

left, right = st.columns([3, 2], gap="medium")
with left:
    ui.panel("报道量趋势（按天）")
    daily = (
        df.dropna(subset=["published_at"])
        .assign(day=lambda x: pd.to_datetime(x["published_at"]).dt.date)
        .groupby("day").size().reset_index(name="文章数")
    )
    fig = px.area(daily, x="day", y="文章数")
    fig.update_traces(line_color=palette.SOURCE["news"], fillcolor="rgba(139,92,246,.18)")
    fig.update_layout(xaxis_title=None)
    ui.chart(fig, height=300)
with right:
    ui.panel("来源分布（Top 15）")
    src = df["source"].value_counts().head(15).reset_index()
    src.columns = ["来源", "数量"]
    fig = px.bar(src, x="数量", y="来源", orientation="h")
    fig.update_traces(marker_color=palette.SOURCE["news"])
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig, height=300)

ui.panel("文章列表")
page_size = 20
total_pages = (len(df) - 1) // page_size + 1
page = st.number_input(f"页码（共 {total_pages} 页）", min_value=1, max_value=total_pages, value=1) - 1
for _, r in df.iloc[page * page_size:(page + 1) * page_size].iterrows():
    src = str(r["source"])[:40] + ("…" if len(str(r["source"])) > 40 else "")
    with st.expander(f"[{src}] {r['title']}  ·  {str(r['published_at'])[:10]}"):
        st.write(r["body"])
        cols = st.columns([1, 3])
        cols[0].caption(f"关联 ACLED 事件: {r['related_event_id'] or '无'}")
        cols[1].markdown(f"[原文链接]({r['url']})")
```

- [ ] **Step 10: GDELT 页换皮**

改动：导入与 `ui.setup("GDELT 背景")`；筛选标题与多选框同上；"冲突事件占比"色条用 ACLED 红；地图点按 Goldstein 用发散色阶（按 0.1 分档查表，避免逐行做 OKLab 换算），图例 3 项；每日事件数与 Top 行为方用 GDELT 琥珀；`st.dataframe(width="stretch")`。

**写入 `app/pages/6_全球背景参考.py`：**

```python
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import pydeck as pdk
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app import palette, ui  # noqa: E402
from app.db import query  # noqa: E402

ui.setup("GDELT 背景")
mode = ui.mode()
ui.page_header(
    "全球背景参考（GDELT 媒体事件流）",
    "航运相关国家的媒体事件流（估值任务筛选版，非红海专题数据）· 默认聚焦 2023 下半年危机窗口",
    chips=["全球背景参考", "1920 ~ 2025"],
)

meta = query("SELECT MIN(event_date) a, MAX(event_date) b FROM gdelt_events")
if meta["a"][0] is None:
    st.info("暂无 GDELT 数据，请先入库。")
    st.stop()

dmin, dmax = pd.Timestamp(meta["a"][0]).date(), pd.Timestamp(meta["b"][0]).date()
# 默认聚焦红海危机窗口（与 AIS / ACLED 时间对齐），可手动放宽
CRISIS_START, CRISIS_END = pd.Timestamp("2023-07-01").date(), pd.Timestamp("2023-12-31").date()
default_range = (max(dmin, CRISIS_START), min(dmax, CRISIS_END))
if default_range[0] > default_range[1]:
    default_range = (dmin, dmax)

with st.sidebar:
    st.subheader("筛选")
    d1, d2 = st.date_input("日期范围", default_range, min_value=dmin, max_value=dmax,
                           help="GDELT 为全球背景数据（1920~2025），默认只看危机窗口")
    countries = query("SELECT DISTINCT country FROM gdelt_events WHERE country IS NOT NULL ORDER BY 1")
    sel_countries = st.multiselect("国家/地区", countries["country"].tolist(), placeholder="全部")
    codes = query("SELECT DISTINCT event_code FROM gdelt_events ORDER BY 1")
    sel_codes = st.multiselect("事件类型", codes["event_code"].tolist(), placeholder="全部")
    tone_range = st.slider("Goldstein 分值（负=冲突 / 正=合作）", -10.0, 10.0, (-10.0, 10.0))

conds = ["event_date BETWEEN ? AND ?", "goldstein BETWEEN ? AND ?"]
params = [d1, d2, tone_range[0], tone_range[1]]
if sel_countries:
    conds.append("country IN (" + ",".join("'" + c + "'" for c in sel_countries) + ")")
if sel_codes:
    conds.append("event_code IN (" + ",".join("'" + c + "'" for c in sel_codes) + ")")
where = " AND ".join(conds)

df = query(
    f"""
    SELECT event_id, event_date, actor1, actor2, event_code, goldstein,
           avg_tone, lat, lon, country, num_mentions, source_url
    FROM gdelt_events WHERE {where} LIMIT 200000
    """,
    tuple(params),
)

if df.empty:
    st.warning("筛选结果为空")
    st.stop()

conflict_ratio = (df["goldstein"] < 0).mean() * 100
ui.kpi_row([
    ("事件总数", f"{len(df):,}", f"{df['country'].nunique()} 个国家/地区"),
    ("平均 Goldstein", f"{df['goldstein'].mean():+.2f}", "负值偏冲突，正值偏合作"),
    ("冲突事件占比", f"{conflict_ratio:.0f}%", "Goldstein < 0", palette.SOURCE["acled"]),
    ("媒体总提及", f"{int(df['num_mentions'].sum()):,}", f"平均语调 {df['avg_tone'].mean():+.2f}"),
])

# 发散色阶：冲突（红）← 灰色中点 → 合作（蓝）；按 0.1 分档查表，避免逐行做 OKLab 换算
_STEPS = {round(v / 10, 1): palette.diverging(v / 10, mode) + [150] for v in range(-100, 101)}
df["color"] = df["goldstein"].clip(-10, 10).round(1).map(_STEPS)

ui.deck(
    [
        pdk.Layer(
            "ScatterplotLayer",
            data=df,
            get_position="[lon, lat]",
            get_radius="1500 + num_mentions * 80",
            get_fill_color="color",
            pickable=True,
        )
    ],
    lat=df["lat"].mean(), lon=df["lon"].mean(), zoom=3,
    tooltip="{actor1} → {actor2}\n{event_code} | Goldstein {goldstein}\n{country} · {event_date}",
    height=520,
)
ui.legend([("冲突（Goldstein -10）", palette.diverging(-10, mode)),
           ("中性（0）", palette.diverging(0, mode)),
           ("合作（+10）", palette.diverging(10, mode))])

left, right = st.columns(2, gap="medium")
with left:
    ui.panel("每日事件数")
    daily = df.groupby("event_date").size().reset_index(name="事件数")
    fig = px.bar(daily, x="event_date", y="事件数")
    fig.update_traces(marker_color=palette.SOURCE["gdelt"])
    fig.update_layout(xaxis_title=None)
    ui.chart(fig)
with right:
    ui.panel("Top 行为方")
    top = df["actor1"].value_counts().head(10).reset_index()
    top.columns = ["行为方", "事件数"]
    fig = px.bar(top, x="事件数", y="行为方", orientation="h")
    fig.update_traces(marker_color=palette.SOURCE["gdelt"])
    fig.update_yaxes(autorange="reversed")
    ui.chart(fig)

ui.panel("事件明细")
show_all = st.toggle("显示全部字段（含事件 ID 与经纬度）")
cols = (["event_id", "event_date", "actor1", "actor2", "event_code", "goldstein",
         "avg_tone", "lat", "lon", "country", "num_mentions", "source_url"]
        if show_all else
        ["event_date", "actor1", "actor2", "event_code", "goldstein", "avg_tone",
         "country", "num_mentions", "source_url"])
detail = df[cols].copy()
detail["event_date"] = pd.to_datetime(detail["event_date"]).dt.date
st.dataframe(
    detail.sort_values("event_date", ascending=False),
    width="stretch",
    hide_index=True,
    height=340,
)
```

- [ ] **Step 11: 运行，确认通过**

```bash
python -m pytest tests/test_ui.py -q
```

预期：通过，3 passed。

- [ ] **Step 12: 全量回归与冒烟**

```bash
python -m pytest tests/ -q
```

预期：通过，265 passed（旧工作台的回归测试照常通过；实施时实测 265）。

```bash
python scripts/smoke_test.py
```

预期：通过，最后一行"页面初始化：7/7 通过"。

- [ ] **Step 13: 提交**

```bash
git add app/ui.py app/chat_ui.py app/pages tests/test_ui.py && \
  git commit -m "feat(ui): 看板公共层瘦身，6 个看板页统一换皮" -m "ui.py 删除三套主题与内嵌 CSS，新增 mode/fit_bounds/inject_css/tooltip_style；看板页改用 from app import palette, ui，配色按设计文档 8.2 换成角色色与色阶，地图按数据范围定位，多选框中文占位。chat_ui 一行过渡代码保持旧工作台可用。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 5: 地图图层模型 `app/map_view.py`

一个结果文件按要素拆成若干图层（缓冲区 / 航迹 / 事件点 / 查询结果 / 其他），图层在会话内按轮次累积，id 为 `"{path}#{kind}"`。要点：

- **视野**定位到最新一轮产出图层的范围，与图层是否隐藏无关，所以切换开关不会改变初始视野。
- **复位**把计数 × 1e-7 同时加到纬度、经度、缩放、俯仰、方位五个字段：Streamlit 只覆盖初始视野里"变了"的字段，只改纬度会留下用户拖动后的经度和缩放（样机实测）。
- **渲染**：平时直接画进当前容器、key 固定，重跑时地图组件保留用户拖动过的视野；不要先建 `st.empty()` 再填地图——空占位会先把旧地图换掉，视野随之丢失（样机里"切换图层重置视野"的真正原因）。流式分析时才传入 `st.empty()` 槽位和每次不同的 key。
- **配色**：ACLED 事件只有 3 类着色，"其他"先画、点更小；非 ACLED 点（GDELT 事件、查询结果）用正文色空心圆环。
- 解析与校验后的 GeoJSON 按（路径、修改时间、大小）缓存，切换开关不重复读盘。

旧工作台还在调用旧的 `prepare` / `render`，所以文件末尾暂时保留旧接口（标注为过渡代码），任务 7 删除。

**Files:**
- Modify: `app/map_view.py`（整体重写，末尾保留过渡代码）
- Modify: `agent/artifacts.py`（新增 `longitude_extent`、`_check_properties`，见下方"质量复查修正"）
- Test: `tests/test_map_layers.py`、`tests/test_map_artifacts.py`

**质量复查修正**（代码已按此实现，下方代码块未逐字回改，以本节为准）：

- 航迹只认 `LineString`，或同时带 `points_total` 与 `points_shown` 的 `Point`。`query_database` 把 SQL 列名原样写成属性，只看 `mmsi` 会把 AIS 点集当成航迹（每行一个 deck 图层）——实测 2000 行时图层数 2000、载荷 1.14 MB。多边形带 `mmsi` 时还会走进航迹分支并 `IndexError`。
- 同一轮里同名的图层在"· 第 N 轮"之后再加序号：一次回答做两个缓冲区时，两个按钮原本同名。
- 经度取跨日界线的最短弧（`artifacts.longitude_extent`），`fit_view` 再把中心折回 −180–180。原来一对 ±179° 的点会定位到全球、缩放 2 级。
- `load_geojson` 增加属性校验：`properties` 必须是对象、值必须是简单值、整数不能溢出 `float`。原来非对象的 `properties` 会让整个页面 `AttributeError`。
- 下载按钮的 `data` 改成闭包按需读取，文件已被删除时给一行"文件已不可用"，不留点了才报错的按钮。

- [ ] **Step 1: 写测试**

**写入 `tests/test_map_layers.py`：**

```python
"""工作台地图图层的单元测试：拆分、命名、配色归并、视野与复位（设计文档第 7 节）。"""

import json

import pytest

from agent import artifacts
from app import map_view, palette


def _feature(shape, coordinates, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": shape, "coordinates": coordinates}}


def _square(lon, lat, half):
    return [[[lon - half, lat - half], [lon + half, lat - half], [lon + half, lat + half],
             [lon - half, lat + half], [lon - half, lat - half]]]


def _event(event_type, lon=43.3, lat=12.6):
    return _feature("Point", [lon, lat], event_type=event_type, date="2023-12-15",
                    location="Strait of Bab el Mandeb", dist_km=37)


BUFFER = _feature("Polygon", _square(43.3, 12.6, 1.0), kind="buffer", radius_km=150)
TRACK = _feature("LineString", [[38.0, 20.0], [39.0, 19.0], [40.0, 18.0]],
                 mmsi=668116204, points_shown=3, points_total=120)
QUERY_POINT = _feature("Point", [42.0, 15.0], name="Hodeidah", country="Yemen", port=True, berths=12)
ACLED_TYPES = ["Battles", "Explosions/Remote violence", "Strategic developments",
               "Protests", "Riots", "Violence against civilians"]


@pytest.fixture
def geojson():
    """在受控产物目录里写 GeoJSON（tests/conftest.py 已把该目录隔离到每个测试的临时目录）。"""
    def write(name, features):
        artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = artifacts.OUTPUT_DIR / f"{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        return str(path)

    return write


def _all(state):
    return {layer.id for layer in state.layers}


def test_turns_number_assistant_replies_and_skip_replies_without_maps():
    messages = [{"role": "user"}, {"role": "assistant", "geojson": []},
                {"role": "user"}, {"role": "assistant", "geojson": ["a.geojson", "a.geojson"]}]
    assert map_view.turns(messages) == [(2, ["a.geojson"])]


def test_one_file_splits_into_named_layers_in_drawing_order(geojson):
    path = geojson("mixed", [QUERY_POINT, _event("Battles"), _event("Protests"), TRACK, BUFFER])
    state = map_view.build([(1, [path])])

    assert [(layer.kind, layer.label) for layer in state.layers] == [
        ("buffer", "缓冲区 150 km"), ("track", "航迹 · 668116204"),
        ("events", "事件点 · 2"), ("points", "查询结果 · 1 点"),
    ]
    assert [layer.id for layer in state.layers] == [f"{path}#{kind}" for kind in ("buffer", "track", "events", "points")]
    assert state.files == [(1, path, "缓冲区 150 km、航迹 · 668116204、事件点 · 2、查询结果 · 1 点")]
    assert state.feature_count == 5


def test_tooltips_are_prepared_in_chinese(geojson):
    path = geojson("tips", [BUFFER, TRACK, _event("Explosions/Remote violence"), QUERY_POINT])
    state = map_view.build([(1, [path])])
    buffer, glow, line, end, events, ring = map_view.deck_layers(state.layers, _all(state), "light")

    assert buffer.data["features"][0]["properties"]["tip"] == "缓冲区 · 半径 150 km"
    assert line.data[0]["tip"] == end.data[0]["tip"] == "MMSI 668116204 · 展示 3 / 共 120 点"
    assert events.data[0]["tip"] == "2023-12-15 · 爆炸/远程暴力 · Strait of Bab el Mandeb · 距中心 37 km"
    assert ring.data[0]["tip"] == "name: Hodeidah · country: Yemen · port: True"


def test_zero_event_buffer_has_only_the_circle_layer(geojson):
    state = map_view.build([(1, [geojson("empty_buffer", [BUFFER])])])
    assert [layer.kind for layer in state.layers] == ["buffer"]


def test_point_rows_with_an_mmsi_column_are_query_results_not_tracks(geojson):
    # query_database 把 mmsi 列也写成属性，逐行一个 Point；只看 mmsi 会把它当成航迹，每点一个图层
    rows = [_feature("Point", [43.0 + 0.01 * index, 12.0], mmsi="600000000", speed="12.4")
            for index in range(3)]
    state = map_view.build([(1, [geojson("ais", rows)])])

    assert [(layer.kind, layer.label) for layer in state.layers] == [("points", "查询结果 · 3 点")]
    assert [layer.type for layer in map_view.deck_layers(state.layers, _all(state), "light")] == ["ScatterplotLayer"]


def test_point_rows_are_not_tracks_just_because_a_column_is_named_points_total(geojson):
    # SQL 别名同样会变成属性；ship_track 的单点输出同时带 points_total 与 points_shown
    rows = [_feature("Point", [43.0, 12.0], mmsi="600000000", points_total="500")]
    state = map_view.build([(1, [geojson("alias", rows)])])
    assert [layer.kind for layer in state.layers] == ["points"]


def test_polygons_with_an_mmsi_property_are_not_tracks(geojson):
    # 回归：查出带 mmsi 的船舶区域面时，曾按航迹渲染并 IndexError
    area = _feature("Polygon", _square(43.3, 12.6, 1.0), mmsi=668116204, points_total=3, points_shown=3)
    state = map_view.build([(1, [geojson("ship_area", [area])])])
    assert [layer.kind for layer in state.layers] == ["other"]
    assert [layer.type for layer in map_view.deck_layers(state.layers, _all(state), "light")] == ["GeoJsonLayer"]


def test_single_point_track_stays_a_track(geojson):
    one = _feature("Point", [40.0, 18.0], mmsi=1, points_total=1, points_shown=1)
    state = map_view.build([(1, [geojson("track_one", [one])])])
    assert [(layer.kind, layer.label) for layer in state.layers] == [("track", "航迹 · 1")]


def test_same_names_get_turn_suffix(geojson):
    first, second = geojson("buffer_a", [BUFFER]), geojson("buffer_b", [BUFFER])
    state = map_view.build([(1, [first]), (3, [second])])
    assert [layer.label for layer in state.layers] == ["缓冲区 150 km · 第 1 轮", "缓冲区 150 km · 第 3 轮"]


def test_same_turn_layers_with_the_same_name_are_numbered(geojson):
    first, second = geojson("buffer_a", [BUFFER]), geojson("buffer_b", [BUFFER])
    state = map_view.build([(1, [first, second])])
    assert [layer.label for layer in state.layers] == ["缓冲区 150 km · 第 1 轮 · 1", "缓冲区 150 km · 第 1 轮 · 2"]


def test_file_repeated_in_later_turn_belongs_to_that_turn(geojson):
    path = geojson("repeated", [BUFFER])
    state = map_view.build([(1, [path]), (2, [path])])
    assert [(layer.turn, layer.label) for layer in state.layers] == [(2, "缓冲区 150 km")]
    assert [turn for turn, _, _ in state.files] == [2]


@pytest.mark.parametrize("mode", palette.MODES)
def test_acled_events_use_three_colors_plus_smaller_gray_other(geojson, mode):
    path = geojson("acled", [_event(event_type) for event_type in ACLED_TYPES])
    state = map_view.build([(1, [path])])
    assert state.layers[0].typed

    other, typed = map_view.deck_layers(state.layers, _all(state), mode)
    assert [row["color"] for row in typed.data] == [palette.rgb(color) for color in palette.EVENT_COLORS.values()]
    assert [row["color"] for row in other.data] == [palette.rgb(palette.OTHER_GRAY[mode])] * 3
    assert other.radius_min_pixels < typed.radius_min_pixels
    assert typed.get_line_color == palette.rgb(palette.MAP[mode]["stroke"])
    assert map_view.legend_groups(state, _all(state)) == [*palette.EVENT_COLORS, palette.OTHER]
    assert map_view.legend_groups(state, set()) == []


@pytest.mark.parametrize("mode", palette.MODES)
def test_gdelt_events_and_query_points_use_neutral_rings(geojson, mode):
    path = geojson("gdelt", [_event("190"), _event("Battles"), QUERY_POINT])
    state = map_view.build([(1, [path])])
    assert [(layer.kind, layer.typed) for layer in state.layers] == [("events", False), ("points", False)]

    rings = map_view.deck_layers(state.layers, _all(state), mode)
    assert len(rings) == 2
    for ring in rings:
        assert ring.type == "ScatterplotLayer" and ring.filled is False and ring.stroked is True
        assert ring.get_line_color == palette.rgb(palette.MAP[mode]["ring"])
    assert map_view.legend_groups(state, _all(state)) == []


def test_hidden_layers_are_not_drawn(geojson):
    path = geojson("hide", [BUFFER, _event("Battles")])
    state = map_view.build([(1, [path])])
    assert [layer.type for layer in map_view.deck_layers(state.layers, {f"{path}#buffer"}, "light")] == ["GeoJsonLayer"]


def test_view_fits_latest_turn_in_web_mercator(geojson):
    far = geojson("far", [_feature("Point", [-149.4, -17.7], name="Tahiti")])
    near = geojson("near", [_feature("Polygon", _square(40.0, 20.0, 10.0), kind="buffer", radius_km=1000)])
    state = map_view.build([(1, [far]), (2, [near])])
    # 10°N–30°N 在墨卡托下比按度数算更"高"：缩放 3.80，按度数线性算会得到 3.90
    assert state.view == (20.322, 40.0, 3.8)


def test_view_follows_the_shortest_arc_across_the_antimeridian(geojson):
    # -179° 与 179.5° 相距 1.5°；简单取最小/最大会得到覆盖 358.5° 的"全球"视野
    path = geojson("dateline", [_feature("Point", [-179.0, -17.0]), _feature("Point", [179.5, -17.0])])
    assert map_view.build([(1, [path])]).view == (-17.0, -179.75, 8.0)


def test_worldwide_points_still_fit_the_whole_map(geojson):
    path = geojson("world", [_feature("Point", [-170.0, 0.0]), _feature("Point", [0.0, 0.0]),
                             _feature("Point", [170.0, 0.0])])
    assert map_view.build([(1, [path])]).view == (0.0, 0.0, 2.0)


def test_without_layers_the_map_shows_the_red_sea():
    state = map_view.build([])
    assert state.view == map_view.DEFAULT_VIEW == (15.0, 43.0, 4.5)
    assert map_view.view_state(state).latitude == 15.0


def test_reset_nudges_every_view_field(geojson):
    path = geojson("reset", [BUFFER])
    base = map_view.view_state(map_view.build([(1, [path])]))
    moved = map_view.view_state(map_view.build([(1, [path])], reset=2))

    assert (base.pitch, base.bearing) == (0, 0)
    for name in ("latitude", "longitude", "zoom", "pitch", "bearing"):
        assert getattr(moved, name) == pytest.approx(getattr(base, name) + 2e-7, abs=1e-12)
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_map_layers.py -q
```

预期：失败，14 failed（`AttributeError: module 'app.map_view' has no attribute 'build'` 等）。

- [ ] **Step 3: 实现**

**写入 `app/map_view.py`：**

```python
"""工作台地图：把会话各轮的真实产物拆成可开关的图层，按主题配色上图（设计文档第 7 节）。

只读取通过 agent/artifacts.py 校验的本地 GeoJSON；回答正文里的路径永远不会变成图层。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pydeck as pdk
import streamlit as st

from agent import artifacts
from app import palette, ui

DEFAULT_VIEW = (15.0, 43.0, 4.5)
NOMINAL_VIEWPORT = (720, 560)  # 计算缩放用的名义视口（像素）
PADDING = 0.12
ORDER = ("buffer", "track", "events", "points", "other")  # 叠放顺序：缓冲区在最下
ICONS = {"buffer": ":material/radio_button_unchecked:", "events": ":material/scatter_plot:",
         "track": ":material/route:", "points": ":material/location_on:", "other": ":material/layers:"}
HIDDEN_KEY = "hidden_layers"
RESET_KEY = "map_reset_nonce"


@dataclass
class MapLayer:
    id: str
    path: str
    turn: int
    kind: str
    label: str
    features: list
    typed: bool = False  # ACLED 事件点：按类型着色


@dataclass
class MapState:
    layers: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    files: list = field(default_factory=list)  # [(轮次, 路径, 内容摘要)]，供下载
    view: tuple = DEFAULT_VIEW
    reset: int = 0  # "复位"计数

    @property
    def feature_count(self) -> int:
        return sum(len(layer.features) for layer in self.layers)


# ---------------------------------------------------------------- 数据
def turns(messages: list[dict]) -> list[tuple[int, list[str]]]:
    """[(轮次, 路径)]：轮次是助手回答的序号（从 1 开始），跳过没有产物的回答。"""
    result, turn = [], 0
    for message in messages:
        if message.get("role") != "assistant":
            continue
        turn += 1
        paths = list(dict.fromkeys(message.get("geojson") or []))
        if paths:
            result.append((turn, paths))
    return result


@st.cache_data(max_entries=256, show_spinner=False)
def _load_cached(path: str, mtime_ns: int, size: int) -> dict:
    return artifacts.load_geojson(path)


def load(path: str) -> dict:
    """按（路径，修改时间，大小）缓存校验结果；切换开关不重复读盘。"""
    try:
        stat = Path(path).stat()
    except (OSError, TypeError, ValueError):
        return artifacts.load_geojson(path)  # 交给校验函数给出统一的错误说明
    return _load_cached(str(path), stat.st_mtime_ns, stat.st_size)


def _kind(feature: dict) -> str:
    geometry = feature.get("geometry") or {}
    shape = geometry.get("type")
    props = feature.get("properties") or {}
    if shape in ("Polygon", "MultiPolygon") and props.get("kind") == "buffer":
        return "buffer"
    if shape == "Point" and "event_type" in props:
        return "events"
    # query_database 把 SQL 列名原样写成属性，只看 mmsi 会把 AIS 点集当成航迹。
    # ship_track 的单点输出同时带 points_total 与 points_shown，两个都在才算。
    if shape == "LineString" and "mmsi" in props:
        return "track"
    if shape == "Point" and "mmsi" in props and "points_total" in props and "points_shown" in props:
        return "track"  # ship_track 只有 1 个点时的输出
    if shape in ("Point", "MultiPoint"):
        return "points"
    return "other"


def split(data: dict) -> list[tuple[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    for feature in data["features"]:
        groups.setdefault(_kind(feature), []).append(feature)
    return [(kind, groups[kind]) for kind in ORDER if kind in groups]


def layer_label(kind: str, features: list[dict]) -> str:
    first = features[0].get("properties") or {}
    if kind == "buffer":
        radius = first.get("radius_km")
        return f"缓冲区 {radius:g} km" if isinstance(radius, (int, float)) else "缓冲区"
    if kind == "track":
        return f"航迹 · {first.get('mmsi')}"
    if kind == "events":
        return f"事件点 · {len(features)}"
    if kind == "points":
        return f"查询结果 · {len(features)} 点"
    return f"图层 · {len(features)} 个要素"


def build(turn_paths: list[tuple[int, list[str]]], reset: int = 0) -> MapState:
    state = MapState()
    latest = {path: turn for turn, paths in turn_paths for path in paths}  # 重复出现的文件归到最后一轮
    seen = set()
    for turn, paths in turn_paths:
        for path in paths:
            if latest[path] != turn or path in seen:
                continue
            seen.add(path)
            try:
                data = load(path)
            except artifacts.ArtifactError as exc:
                state.errors.append(str(exc))
                continue
            parts = split(data)
            state.files.append((turn, path, "、".join(layer_label(kind, items) for kind, items in parts)))
            for kind, items in parts:
                typed = kind == "events" and all(
                    (item.get("properties") or {}).get("event_type") in palette.ACLED_TYPES for item in items)
                state.layers.append(MapLayer(f"{path}#{kind}", path, turn, kind,
                                             layer_label(kind, items), items, typed))
    counts = Counter(layer.label for layer in state.layers)
    for layer in state.layers:
        if counts[layer.label] > 1:
            layer.label = f"{layer.label} · 第 {layer.turn} 轮"
    counts = Counter(layer.label for layer in state.layers)  # 一轮里仍同名：一次回答做了两个缓冲区
    index: Counter = Counter()
    for layer in state.layers:
        if counts[layer.label] > 1:
            index[layer.label] += 1
            layer.label = f"{layer.label} · {index[layer.label]}"
    state.errors = list(dict.fromkeys(state.errors))
    state.view = fit_view(state.layers)
    state.reset = reset
    return state


# ---------------------------------------------------------------- 视野
def fit_view(layers: list[MapLayer]) -> tuple[float, float, float]:
    """定位到最新一轮产出图层的范围；与图层是否隐藏无关，所以切换开关不会改变视野。
    经度取跨日界线的最短弧，再折回 -180–180，避免一对 ±179° 的点定位到全球。"""
    if not layers:
        return DEFAULT_VIEW
    latest = max(layer.turn for layer in layers)
    features = [item for layer in layers if layer.turn == latest for item in layer.features]
    _, bottom, _, top = artifacts.coordinate_bounds({"type": "FeatureCollection", "features": features})
    left, right = artifacts.longitude_extent(features)
    latitude, longitude, zoom = ui.fit_bounds(left, bottom, right, top, viewport=NOMINAL_VIEWPORT, padding=PADDING)
    if longitude > 180.0:
        longitude -= 360.0
    elif longitude < -180.0:
        longitude += 360.0
    return (latitude, longitude, zoom)


# ---------------------------------------------------------------- 图层样式
def _tip(kind: str, props: dict) -> str:
    if kind == "buffer":
        radius = props.get("radius_km")
        return f"缓冲区 · 半径 {radius:g} km" if isinstance(radius, (int, float)) else "缓冲区"
    if kind == "track":
        return f"MMSI {props.get('mmsi')} · 展示 {props.get('points_shown')} / 共 {props.get('points_total')} 点"
    if kind == "events":
        parts = [str(props.get("date") or ""), palette.type_label(props.get("event_type")), str(props.get("location") or "")]
        if props.get("dist_km") is not None:
            parts.append(f"距中心 {props['dist_km']} km")
        return " · ".join(part for part in parts if part)
    return " · ".join(f"{key}: {value}" for key, value in list(props.items())[:3])


def _positions(geometry: dict) -> list:
    """Point 与 MultiPoint 统一成位置列表。"""
    coordinates = geometry["coordinates"]
    return [coordinates] if geometry["type"] == "Point" else list(coordinates)


def _records(layer: MapLayer, mode: str) -> list[dict]:
    rows = []
    for feature in layer.features:
        props = feature.get("properties") or {}
        tip = _tip(layer.kind, props)
        group = palette.event_group(props.get("event_type"))
        color = palette.rgb(palette.event_color(props.get("event_type"), mode))
        for position in _positions(feature["geometry"]):
            rows.append({"lon": position[0], "lat": position[1], "tip": tip, "group": group, "color": color})
    return rows


def _collection(layer: MapLayer) -> dict:
    features = [{**item, "properties": {**(item.get("properties") or {}), "tip": _tip(layer.kind, item.get("properties") or {})}}
                for item in layer.features]
    return {"type": "FeatureCollection", "features": features}


def _ring(rows: list[dict], mode: str) -> pdk.Layer:
    return pdk.Layer("ScatterplotLayer", data=rows, get_position="[lon, lat]", get_radius=3000,
                     radius_min_pixels=4, radius_max_pixels=9, filled=False, stroked=True,
                     get_line_color=palette.rgb(palette.MAP[mode]["ring"]), line_width_min_pixels=1.5,
                     pickable=True)


def deck_layers(layers: list[MapLayer], visible: set, mode: str) -> list[pdk.Layer]:
    colors = palette.MAP[mode]
    result = []
    for layer in sorted(layers, key=lambda item: (ORDER.index(item.kind), item.turn)):
        if layer.id not in visible:
            continue
        if layer.kind == "buffer":
            color = palette.rgb(colors["buffer"])
            result.append(pdk.Layer("GeoJsonLayer", data=_collection(layer), stroked=True, filled=True,
                                    get_fill_color=color + [23], get_line_color=color + [235],
                                    line_width_min_pixels=2, pickable=True))
        elif layer.kind == "track":
            color = palette.rgb(colors["track"])
            for feature in layer.features:
                geometry = feature["geometry"]
                tip = _tip("track", feature.get("properties") or {})
                path = geometry["coordinates"] if geometry["type"] == "LineString" else [geometry["coordinates"]]
                if len(path) > 1:
                    result.append(pdk.Layer("PathLayer", data=[{"path": path, "tip": tip}], get_path="path",
                                            get_color=color + [70], width_min_pixels=8,
                                            cap_rounded=True, joint_rounded=True))
                    result.append(pdk.Layer("PathLayer", data=[{"path": path, "tip": tip}], get_path="path",
                                            get_color=color, width_min_pixels=2.5, cap_rounded=True,
                                            joint_rounded=True, pickable=True))
                end = path[-1]
                result.append(pdk.Layer("ScatterplotLayer", data=[{"lon": end[0], "lat": end[1], "tip": tip}],
                                        get_position="[lon, lat]", get_radius=5000, radius_min_pixels=6,
                                        get_fill_color=[255, 255, 255], get_line_color=color, stroked=True,
                                        line_width_min_pixels=3, pickable=True))
        elif layer.kind == "events" and layer.typed:
            rows = _records(layer, mode)
            other = [row for row in rows if row["group"] == palette.OTHER]
            typed = [row for row in rows if row["group"] != palette.OTHER]
            stroke = palette.rgb(colors["stroke"])
            for data, min_px in ((other, 2.5), (typed, 3.5)):  # "其他"先画、点更小
                if data:
                    result.append(pdk.Layer("ScatterplotLayer", data=data, get_position="[lon, lat]",
                                            get_radius=3000, radius_min_pixels=min_px, radius_max_pixels=8,
                                            get_fill_color="color", get_line_color=stroke, stroked=True,
                                            line_width_min_pixels=1, pickable=True))
        elif layer.kind in ("events", "points"):
            result.append(_ring(_records(layer, mode), mode))
        else:
            result.append(pdk.Layer("GeoJsonLayer", data=_collection(layer), stroked=True, filled=False,
                                    get_line_color=palette.rgb(colors["ring"]), line_width_min_pixels=1.5,
                                    point_radius_min_pixels=4, pickable=True))
    return result


# ---------------------------------------------------------------- 渲染
def hidden(sid: str | None) -> set:
    return set(st.session_state.get(HIDDEN_KEY, {}).get(sid or "", set()))


def _store_hidden(key: str, sid: str | None, ids: list[str]) -> None:
    selected = set(st.session_state.get(key) or [])
    st.session_state.setdefault(HIDDEN_KEY, {})[sid or ""] = {item for item in ids if item not in selected}


def _bump_reset() -> None:
    st.session_state[RESET_KEY] = st.session_state.get(RESET_KEY, 0) + 1


def reset_count() -> int:
    return st.session_state.get(RESET_KEY, 0)


def render_bar(state: MapState, sid: str | None, busy: bool) -> set:
    """图层开关 + 复位 + 下载；返回当前可见的图层 id。开关多时在左栏内换行，两个图标固定在右侧。"""
    ids = [layer.id for layer in state.layers]
    visible = [item for item in ids if item not in hidden(sid)]
    layers_col, reset_col, download_col = st.columns([12, 1, 1.5], gap="small", vertical_alignment="center")
    with layers_col:
        if ids:
            digest = hashlib.sha1("|".join(ids).encode("utf-8")).hexdigest()[:10]
            key = f"layers_{sid or 'new'}_{digest}"  # 图层集合变化时换一个控件，默认值由隐藏集合算出
            names = {layer.id: f"{ICONS[layer.kind]} {layer.label}" for layer in state.layers}
            visible = st.pills("图层", ids, selection_mode="multi", default=visible, key=key,
                               format_func=names.get, label_visibility="collapsed", disabled=busy,
                               on_change=_store_hidden, args=(key, sid, ids)) or []
        else:
            st.caption("还没有图层")
    with reset_col:
        st.button("", key="map_reset", icon=":material/center_focus_strong:", type="tertiary",
                  disabled=busy or not ids, on_click=_bump_reset, help="复位：回到最新结果的范围")
    with download_col:
        with st.popover("", icon=":material/download:", disabled=busy or not state.files, key="map_download",
                        help="下载 GeoJSON"):
            for index, (turn, path, summary) in enumerate(state.files):
                file = Path(path)
                st.download_button(f"{summary} · 第 {turn} 轮 · {file.name}", file.read_bytes(),
                                   file_name=file.name, mime="application/geo+json",
                                   key=f"geoagent_download_{index}", on_click="ignore", width="stretch")
    return set(visible)


def render_alerts(state: MapState, last_error: str | None) -> None:
    if state.errors:
        st.warning("地图加载失败：" + "；".join(state.errors))
    if last_error and not state.layers:
        st.warning("本轮未生成可用地图，请查看对话中的执行失败说明。")


def view_state(state: MapState) -> pdk.ViewState:
    """Streamlit 只覆盖初始视野里"变了"的字段；复位时五个字段都挪一个肉眼不可见的量，
    才能把用户拖动、缩放、旋转过的视野全部重置。"""
    lat, lon, zoom = state.view
    nudge = state.reset * 1e-7
    return pdk.ViewState(latitude=lat + nudge, longitude=lon + nudge, zoom=zoom + nudge,
                         pitch=nudge, bearing=nudge)


def render_map(state: MapState, visible: set, mode: str, *, key: str = "workspace_map", slot=None) -> None:
    """平时直接画进当前容器、key 固定，重跑时地图组件保留用户拖动过的视野；
    流式分析时传入 st.empty() 槽位与每次不同的 key，新结果到达时重新定位。

    不要在页面里先建 st.empty() 再填地图：空占位会先替换掉旧地图，视野随之丢失。"""
    deck = pdk.Deck(map_style=None, layers=deck_layers(state.layers, visible, mode),
                    initial_view_state=view_state(state),
                    tooltip={"text": "{tip}", "style": ui.tooltip_style()})
    (slot or st).pydeck_chart(deck, height="stretch", key=key)


def legend_groups(state: MapState, visible: set) -> list[str]:
    present = {palette.event_group((item.get("properties") or {}).get("event_type"))
               for layer in state.layers if layer.id in visible and layer.typed for item in layer.features}
    return [group for group in (*palette.EVENT_COLORS, palette.OTHER) if group in present]


def render_footer(state: MapState, visible: set, mode: str) -> None:
    with st.container(horizontal=True, vertical_alignment="center", key="map_footer"):
        if not state.layers:
            st.caption("提问后，分析结果会作为图层出现在这里")
            return
        hidden_count = sum(layer.id not in visible for layer in state.layers)
        text = f"{len(state.layers)} 个图层 · {state.feature_count} 个要素"
        if hidden_count:
            text += f"（{hidden_count} 个已隐藏）"
        st.caption(text + " · 已定位到最新结果")
        groups = legend_groups(state, visible)
        if groups:
            ui.legend([(palette.group_label(group), palette.event_color(group, mode)) for group in groups])


# ---------------------------------------------------------------- 过渡代码：旧工作台页面仍在调用，任务 7 删除
import math  # noqa: E402


@dataclass
class MapResult:
    layers: list = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    view: tuple = (15.0, 43.0, 4.5)
    points: int = 0
    features: int = 0


def prepare(paths: list[str]) -> MapResult:
    result = MapResult()
    bounds = []
    colors = [[34, 211, 238], [248, 113, 113], [251, 191, 36], [167, 139, 250]]
    for path in dict.fromkeys(paths):
        try:
            data = artifacts.load_geojson(path)
            bounds.append(artifacts.coordinate_bounds(data))
        except artifacts.ArtifactError as exc:
            result.errors.append(str(exc))
            continue
        result.paths.append(path)
        result.features += len(data["features"])
        result.points += sum(feature["geometry"]["type"] == "Point" for feature in data["features"])
        color = colors[len(result.layers) % len(colors)]
        result.layers.append(pdk.Layer(
            "GeoJsonLayer", data=data, stroked=True, filled=True, pickable=True,
            get_fill_color=color + [40], get_line_color=color + [220],
            get_line_width=3, line_width_min_pixels=3, point_radius_min_pixels=5,
        ))
    if bounds:
        left, bottom = min(b[0] for b in bounds), min(b[1] for b in bounds)
        right, top = max(b[2] for b in bounds), max(b[3] for b in bounds)
        span = max(right - left, top - bottom, .01)
        result.view = ((bottom + top) / 2, (left + right) / 2,
                       max(2., min(9., math.log2(180. / span))))
    return result


def render(slot, paths: list[str], *, last_error: str | None = None) -> MapResult:
    result = prepare(paths)
    slot.empty()
    with slot.container():
        if result.errors:
            st.warning("地图加载失败：" + "；".join(dict.fromkeys(result.errors)))
        if last_error and not result.paths:
            st.warning("本轮未生成可用地图，请查看对话中的执行失败说明。")
        lat, lon, zoom = result.view
        ui.deck(result.layers, lat, lon, zoom, tooltip="{date}{event_type}{location}", height=450)
        if result.paths:
            st.caption(f"已加载 {len(result.paths)} 个地图文件 · {result.features} 个要素 · {result.points} 个点要素")
        elif result.errors:
            st.caption("尚无可显示的分析图层；当前仅为默认底图。")
        else:
            st.caption("尚未生成分析图层；模型回答中的文件名不会自动作为地图结果。")
    return result
```

- [ ] **Step 4: 运行，确认通过**

```bash
python -m pytest tests/test_map_layers.py -q
```

预期：通过，14 passed（质量复查后本文件共 22 条）。

- [ ] **Step 5: 全量回归**

```bash
python -m pytest tests/ -q
```

预期：通过，291 passed（实施时实测；原计划的 267 写在质量复查补充回归测试之前）。

- [ ] **Step 6: 提交**

```bash
git add app/map_view.py agent/artifacts.py tests/test_map_layers.py tests/test_map_artifacts.py && \
  git commit -m "feat(map): 工作台地图图层模型" -m "按要素拆分图层并在会话内累积；视野按最新一轮结果在墨卡托投影下计算；复位同时微调视野五个字段；ACLED 事件 3 色 + 其他，非 ACLED 点用中性圆环；GeoJSON 按路径、修改时间、大小缓存。旧 prepare/render 暂留给旧工作台。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 6: 路由入口与顶部导航

`app/GeoAgent.py` 从"页面"变成"路由"：Docker CMD、README 启动命令、`AppTest.from_file("app/GeoAgent.py")` 都不用改。旧工作台页面原样改名为 `workspace.py`（任务 7 重写），作为默认页。

看板页目录必须改名：Streamlit 启动时只要入口旁有 `pages/`，就先按旧版多页模式运行，直到某个会话打开首页、执行到 `st.navigation`；在那之前直接打开看板页链接会绕过路由，导航退回旧版侧栏（样机实测：重启后先访问 `/总览` 就会出现）。改名后 URL 不变，仍由文件名推断（`/总览`、`/AIS船舶地图` 等）。

**Files:**
- Move: `app/GeoAgent.py` → `app/workspace.py`（内容不变）
- Create: `app/GeoAgent.py`（路由）、`app/static/logo.svg`
- Move: `app/pages/` → `app/dashboards/`
- Modify: `scripts/smoke_test.py:14`、`tests/test_ui.py:7`
- Test: `tests/test_navigation.py`

- [ ] **Step 1: 写测试**

**写入 `tests/test_navigation.py`：**

```python
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
    pages = re.findall(r'st\.Page\("([^"]+)"', ROUTER.read_text(encoding="utf-8"))
    assert pages[0] == "workspace.py"
    assert [Path(page).parent.name for page in pages[1:]] == ["dashboards"] * 6
    assert all((ROOT / "app" / page).is_file() for page in pages)


def test_no_pages_directory_next_to_the_router():
    # Streamlit 见到入口旁的 pages/ 会先按旧版多页模式运行，直接打开看板链接会绕过路由
    assert not (ROOT / "app" / "pages").exists()
```

- [ ] **Step 2: 运行，确认失败**

```bash
python -m pytest tests/test_navigation.py -q
```

预期：失败，2 failed, 1 passed（入口还不是路由、`app/pages/` 仍在；默认页显示工作台输入框的那条已经成立，留作回归）。

- [ ] **Step 3: 旧页面改名为工作台**

```bash
git mv app/GeoAgent.py app/workspace.py
```

预期：成功，无输出。

- [ ] **Step 4: 新建 Logo**

SVG 内用 `@media (prefers-color-scheme: dark)` 换色，系统深色与菜单手动切换 Dark 时都能变（样机实测）。

**写入 `app/static/logo.svg`：**

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 26"><style>.mk{fill:#0F766E}.ln{stroke:#FFFFFF}.dt{fill:#FFFFFF}.wm{fill:#1B1D1F}@media (prefers-color-scheme: dark){.mk{fill:#F5B83D}.ln{stroke:#1A1203}.dt{fill:#1A1203}.wm{fill:#E7ECF3}}</style><rect class="mk" x="0" y="1" width="24" height="24" rx="7"/><circle class="ln" cx="12" cy="13" r="6.6" fill="none" stroke-width="1.4" stroke-opacity=".6"/><path class="ln" d="M12 13 16.8 8.2" stroke-width="1.8" stroke-linecap="round" fill="none"/><circle class="dt" cx="12" cy="13" r="2.1"/><text class="wm" x="32" y="18.5" font-family="Segoe UI, PingFang SC, sans-serif" font-size="16" font-weight="700">GeoScope</text></svg>
```

- [ ] **Step 5: 新建路由入口**

**写入 `app/GeoAgent.py`：**

```python
"""GeoScope 入口：Logo、顶部导航与页面路由（设计文档第 3 节）。

工作台在 workspace.py；看板页在 dashboards/ 下，由这里显式注册。目录不能叫 pages/：
Streamlit 见到 pages/ 会先按旧版多页模式运行，直到某个会话打开首页、执行到 st.navigation，
在那之前直接打开看板页链接会绕过这里，导航退回旧版侧栏。
"""

import sys
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parent
if str(APP.parent) not in sys.path:
    sys.path.insert(0, str(APP.parent))

st.set_page_config(page_title="GeoScope", page_icon=":material/radar:", layout="wide",
                   initial_sidebar_state="expanded")
st.logo(str(APP / "static" / "logo.svg"), size="large")

PAGES = [
    st.Page("workspace.py", title="工作台", icon=":material/explore:", default=True),
    st.Page("dashboards/1_总览.py", title="总览", icon=":material/dashboard:"),
    st.Page("dashboards/2_AIS船舶地图.py", title="AIS 船舶", icon=":material/directions_boat:"),
    st.Page("dashboards/3_ACLED事件.py", title="ACLED 事件", icon=":material/warning:"),
    st.Page("dashboards/4_时空叠加.py", title="时空叠加", icon=":material/layers:"),
    st.Page("dashboards/5_新闻检索.py", title="新闻检索", icon=":material/article:"),
    st.Page("dashboards/6_全球背景参考.py", title="GDELT 背景", icon=":material/public:"),
]
st.navigation(PAGES, position="top").run()
```

- [ ] **Step 6: 看板页目录改名**

```bash
git mv app/pages app/dashboards
```

预期：成功，无输出。

**修改 `scripts/smoke_test.py`，把：**

```python
PAGES = [ROOT / "app" / "GeoAgent.py"] + sorted((ROOT / "app" / "pages").glob("*.py"))
```

**替换为：**

```python
PAGES = [ROOT / "app" / "GeoAgent.py"] + sorted((ROOT / "app" / "dashboards").glob("*.py"))
```

**修改 `tests/test_ui.py`，把：**

```python
DASHBOARDS = Path(__file__).resolve().parents[1] / "app" / "pages"
```

**替换为：**

```python
DASHBOARDS = Path(__file__).resolve().parents[1] / "app" / "dashboards"
```

- [ ] **Step 7: 运行，确认通过**

```bash
python -m pytest tests/test_navigation.py tests/test_ui.py -q
```

预期：通过，6 passed。

- [ ] **Step 8: 全量回归与冒烟**

```bash
python -m pytest tests/ -q
```

预期：通过，270 passed（旧工作台测试经路由照常通过）。

```bash
python scripts/smoke_test.py
```

预期：通过，"页面初始化：7/7 通过"。

- [ ] **Step 9: 提交**

```bash
git add app/GeoAgent.py app/workspace.py app/static app/dashboards scripts/smoke_test.py tests/test_ui.py tests/test_navigation.py && \
  git commit -m "feat(app): 入口改为 st.navigation 路由，看板页移到 dashboards/" -m "GeoAgent.py 只负责 Logo、顶部导航与路由，旧工作台页面改名 workspace.py 作为默认页；pages/ 改名 dashboards/，避免 Streamlit 启动后先进入旧版多页模式。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 7: 工作台重做

工作台按设计文档第 6 节重写：侧栏（新建分析、最近会话一键打开、本会话记忆卡片）、对话面板（标题栏与 ··· 菜单、消息、分析过程、结果标签、空状态、中断标注）、地图面板（图层开关、复位、下载、底栏统计与图例），高度填满视口。

**渲染顺序是"防打断"的关键**（`workspace.py` 顶部注释）：Streamlit 的任何点击都会中止正在运行的脚本。所以先在输入区容器里调用 `st.chat_input` 得到 `question`，`busy = bool(question)`，再以 `disabled=busy` 渲染侧栏、标题栏、示例、图层栏等全部控件；容器允许先占位后填内容，调用顺序不影响页面摆放。输入框 `submit_mode="disable"` 在提交后禁用到本轮结束。

两个与 AppTest 有关的细节：带图标的 `st.expander` 在 AppTest 里归为 `Status`（`st.status` 本身就是带图标的折叠区），所以"分析过程"用 `.status[0]` 读取；`st.pills` 用 `app.pills[0]` 读写。

**Files:**
- Create: `app/sessions_ui.py`、`app/styles/workspace.css`
- Modify: `app/chat_ui.py`、`app/workspace.py`（整体重写）
- Modify: `app/map_view.py`（删除过渡代码）
- Delete: `app/chat.css`
- Modify: `tests/test_chat_workspace.py`、`tests/test_map_display.py`、`tests/test_memory_ui.py`、`tests/test_theme.py`
- Test: `tests/test_workspace_sessions.py`、`tests/test_workspace_layers.py`

- [ ] **Step 1: 更新对话工作区回归测试**

打开会话改为点击侧栏的 `session_<sid>` 按钮；"新会话"按钮改为 key `new_analysis`（"新建分析"）；分析过程标签带上步骤摘要。

**修改 `tests/test_chat_workspace.py`，把：**

```python
def _open(app, sid):
    app.selectbox(key="session_picker").select(sid).run()
    _button(app, "打开").click().run()
    assert not app.exception
    return app
```

**替换为：**

```python
def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app
```

**修改 `tests/test_chat_workspace.py`，把：**

```python
    assert app.chat_message[1].expander[0].label == "分析过程 · 1 步"
    assert not app.chat_message[1].expander[0].proto.expanded
```

**替换为：**

```python
    # 带图标的 st.expander 在 AppTest 里归为 Status（st.status 就是带图标的折叠区）
    process = app.chat_message[1].status[0]
    assert process.label == "分析过程 · 1 步 · 查询船舶航迹"
    assert not process.proto.expanded
```

**修改 `tests/test_chat_workspace.py`，把：**

```python
    _button(app, "新会话").click().run()
```

**替换为：**

```python
    app.button(key="new_analysis").click().run()
```

- [ ] **Step 2: 更新会话记忆页面回归测试**

会话下拉的选项数（含"新会话"共 3 项）改为会话按钮数 2；"早期对话摘要"现在是侧栏折叠区的标签。

**修改 `tests/test_memory_ui.py`，把：**

```python
def _button(app, label):
    return next(button for button in app.button if button.label == label)


def _open(app, sid):
    app.selectbox(key="session_picker").select(sid).run()
    _button(app, "打开").click().run()
    assert not app.exception
    return app
```

**替换为：**

```python
def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _session_buttons(app):
    return [button for button in app.sidebar.button if (button.key or "").startswith("session_")]
```

**修改 `tests/test_memory_ui.py`，把：**

```python
    assert len(app.selectbox(key="session_picker").options) == 3
```

**替换为：**

```python
    assert len(_session_buttons(app)) == 2
```

**修改 `tests/test_memory_ui.py`，把：**

```python
    _button(app, "新会话").click().run()
```

**替换为：**

```python
    app.button(key="new_analysis").click().run()
```

**修改 `tests/test_memory_ui.py`，把：**

```python
    assert "早期对话摘要" in _sidebar_text(app)
```

**替换为：**

```python
    assert [expander.label for expander in app.sidebar.expander] == ["早期对话摘要"]
```

- [ ] **Step 3: 更新地图显示回归测试**

`map_view.prepare` 换成 `map_view.build([(轮次, [路径])])`；地图统计与空状态改用新文案（设计文档 6.4）；deck 的图层数与初始视野断言不变。

**修改 `tests/test_map_display.py`，把：**

```python
def _open(app, sid):
    app.selectbox(key="session_picker").select(sid).run()
    next(button for button in app.button if button.label == "打开").click().run()
    assert not app.exception
    return app
```

**替换为：**

```python
def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app
```

**修改 `tests/test_map_display.py`，把：**

```python
def test_prepare_zero_event_southern_buffer_has_layer_and_correct_view():
    path = _polygon_file()
    result = map_view.prepare([path, path])

    assert result.paths == [path]
    assert not result.errors
    assert len(result.layers) == result.features == 1
    assert result.points == 0
    assert result.view[:2] == pytest.approx((-17, -145))
    assert result.view != (15.0, 43.0, 4.5)
    assert result.layers[0].data["features"][0]["properties"]["radius_km"] == 100
```

**替换为：**

```python
def test_build_zero_event_southern_buffer_has_layer_and_correct_view():
    path = _polygon_file()
    state = map_view.build([(1, [path, path])])

    assert [file for _, file, _ in state.files] == [path]
    assert not state.errors
    assert len(state.layers) == state.feature_count == 1
    assert state.layers[0].kind == "buffer"
    assert state.view[:2] == pytest.approx((-17, -145))
    assert state.view != map_view.DEFAULT_VIEW
    assert state.layers[0].features[0]["properties"]["radius_km"] == 100
```

**修改 `tests/test_map_display.py`，把：**

```python
def test_prepare_missing_or_damaged_file_reports_failure(kind):
    artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifacts.OUTPUT_DIR / f"{kind}.geojson"
    if kind == "damaged":
        path.write_text("{broken geojson", encoding="utf-8")

    result = map_view.prepare([str(path)])

    assert result.errors
    assert not result.paths and not result.layers
    assert result.features == result.points == 0
```

**替换为：**

```python
def test_build_missing_or_damaged_file_reports_failure(kind):
    artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifacts.OUTPUT_DIR / f"{kind}.geojson"
    if kind == "damaged":
        path.write_text("{broken geojson", encoding="utf-8")

    state = map_view.build([(1, [str(path)])])

    assert state.errors
    assert not state.files and not state.layers
    assert state.feature_count == 0
    assert state.view == map_view.DEFAULT_VIEW
```

**修改 `tests/test_map_display.py`，把：**

```python
    assert "已加载 1 个地图文件 · 1 个要素 · 0 个点要素" in _captions(app)
    deck = _deck(app)
    assert len(deck["layers"]) == 1
    assert deck["initialViewState"]["latitude"] == pytest.approx(-17)
    assert deck["initialViewState"]["longitude"] == pytest.approx(-145)

    _open(app, empty)
    assert "已加载" not in _captions(app)
    assert "尚未生成分析图层" in _captions(app)
    assert not _deck(app).get("layers", [])
```

**替换为：**

```python
    assert "1 个图层 · 1 个要素 · 已定位到最新结果" in _captions(app)
    deck = _deck(app)
    assert len(deck["layers"]) == 1
    assert deck["initialViewState"]["latitude"] == pytest.approx(-17)
    assert deck["initialViewState"]["longitude"] == pytest.approx(-145)

    _open(app, empty)
    assert "个图层" not in _captions(app)
    assert "提问后，分析结果会作为图层出现在这里" in _captions(app)
    assert not _deck(app).get("layers", [])
```

**修改 `tests/test_map_display.py`，把：**

```python
    assert any("地图加载失败" in warning.value for warning in app.warning)
    assert "已加载" not in _captions(app)
    assert not _deck(app).get("layers", [])

    _open(app, fabricated)
    assert "尚未生成分析图层" in _captions(app)
    assert "已加载" not in _captions(app)
```

**替换为：**

```python
    assert any("地图加载失败" in warning.value for warning in app.warning)
    assert "个图层" not in _captions(app)
    assert not _deck(app).get("layers", [])

    _open(app, fabricated)
    assert "提问后，分析结果会作为图层出现在这里" in _captions(app)
    assert "个图层" not in _captions(app)
```

**修改 `tests/test_map_display.py`，把：**

```python
    result = map_view.prepare([path])
    assert result.features == 1 and result.points == 0
    assert not result.errors
```

**替换为：**

```python
    state = map_view.build([(1, [path])])
    assert state.feature_count == 1 and [layer.kind for layer in state.layers] == ["buffer"]
    assert not state.errors
```

**修改 `tests/test_map_display.py`，把：**

```python
    assert "已加载 1 个地图文件 · 1 个要素 · 0 个点要素" in _captions(app)
    deck = _deck(app)
    assert len(deck["layers"]) == 1
    assert deck["layers"][0]["data"]["features"][0]["geometry"]["type"] == "Polygon"
```

**替换为：**

```python
    assert "1 个图层 · 1 个要素 · 已定位到最新结果" in _captions(app)
    deck = _deck(app)
    assert len(deck["layers"]) == 1
    assert deck["layers"][0]["data"]["features"][0]["geometry"]["type"] == "Polygon"
```

- [ ] **Step 4: 新增会话交互测试**

覆盖：一键打开与当前会话样式、中断标注与"重新填入"只填不发、旧数据（无 `reply_to_seq`）不误标、··· 菜单删除、无会话时菜单禁用、分析进行中全部控件禁用。

**写入 `tests/test_workspace_sessions.py`：**

```python
"""工作台会话交互回归：一键打开、当前会话样式、中断标注与重新填入、删除、分析中禁用控件。"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import artifacts, react, sessions

PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def forbidden(*args, **kwargs):
        raise AssertionError("会话交互回归不得调用模型或运行分析")

    monkeypatch.setattr(react, "_get_llm", forbidden)
    monkeypatch.setattr(react, "stream", forbidden)
    return sessions


def _chat(store, title):
    sid = store.create_session(title)
    seq = store.save_message(sid, "user", f"{title}的问题")
    store.save_message(sid, "assistant", f"{title}的回答", reply_to_seq=seq)
    return sid


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    return app


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _session_buttons(app):
    return [button for button in app.sidebar.button if (button.key or "").startswith("session_")]


def _captions(app):
    return "\n".join(str(element.value) for element in app.caption)


def test_one_click_opens_a_session_and_marks_it_current(store):
    first, second = _chat(store, "第一个会话"), _chat(store, "第二个会话")
    app = _app()
    assert app.session_state["current_session_id"] is None
    assert {button.proto.type for button in _session_buttons(app)} == {"tertiary"}

    _open(app, second)
    assert app.session_state["current_session_id"] == second
    assert len(app.chat_message) == 2
    assert app.button(key=f"session_{second}").proto.type == "secondary"
    assert app.button(key=f"session_{first}").proto.type == "tertiary"
    assert app.button(key=f"session_{second}").label == "第二个会话"


def test_interrupted_question_is_marked_and_refill_only_fills_the_input(store):
    sid = _chat(store, "中断会话")
    lost = store.save_message(sid, "user", "曼德海峡周边80公里有哪些事件？")
    app = _open(_app(), sid)
    assert _captions(app).count("分析被中断，没有生成回答") == 1

    app.button(key=f"refill_{lost}").click().run()
    assert not app.exception
    assert app.chat_input(key="geoagent_prompt").value == "曼德海峡周边80公里有哪些事件？"
    assert len(store.load_messages(sid)) == 3  # 只填入，不发送


def test_legacy_reply_without_link_is_not_marked_interrupted(store):
    sid = store.create_session("旧会话")
    store.save_message(sid, "user", "旧问题")
    store.save_message(sid, "assistant", "旧回答")  # 改版前的数据没有 reply_to_seq
    app = _open(_app(), sid)
    assert "分析被中断" not in _captions(app)


def test_delete_from_header_menu_removes_only_the_current_session(store):
    keep, drop = _chat(store, "保留"), _chat(store, "删除")
    app = _open(_app(), drop)
    app.button(key="delete_session").click().run()

    assert not app.exception
    assert [row[0] for row in store.list_sessions()] == [keep]
    assert app.session_state["current_session_id"] is None
    assert not app.chat_message
    assert [button.key for button in _session_buttons(app)] == [f"session_{keep}"]


def test_header_menu_is_disabled_without_a_session(store):
    app = _app()
    menu = next(block for block in app.get("popover") if block.proto.popover.icon == ":material/more_horiz:")
    assert menu.proto.popover.disabled


def _busy_page(sid, path):
    import streamlit as st

    from app import chat_ui, map_view, sessions_ui

    st.session_state.current_session_id = sid
    sessions_ui.render(busy=True)
    chat_ui.header("标题", "分析中…", sid, busy=True)
    chat_ui.welcome(busy=True)
    chat_ui.render_message({"role": "user", "content": "旧问题", "seq": 7}, "light", interrupted=True, busy=True)
    map_view.render_bar(map_view.build([(1, [path])]), sid, busy=True)


def test_every_control_is_disabled_while_an_analysis_runs(store):
    sid = _chat(store, "进行中")
    artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = artifacts.OUTPUT_DIR / "busy.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"kind": "buffer", "radius_km": 50},
        "geometry": {"type": "Polygon", "coordinates": [[[43, 12], [44, 12], [44, 13], [43, 13], [43, 12]]]},
    }]}), encoding="utf-8")
    app = AppTest.from_function(_busy_page, args=(sid, str(path)), default_timeout=20).run()

    assert not app.exception
    menu_buttons = {"delete_session"}  # 在 ··· 菜单里，菜单本身已禁用
    assert all(button.disabled for button in app.button if button.key not in menu_buttons)
    assert {button.key for button in app.button} >= {"new_analysis", f"session_{sid}", "clear_analysis_memory",
                                                    "geoagent_example_0", "refill_7", "map_reset"}
    assert app.pills[0].disabled
    assert all(block.proto.popover.disabled for block in app.get("popover"))
```

- [ ] **Step 5: 新增图层交互测试**

覆盖：两轮结果累积且视野跟随最新一轮、隐藏图层后 deck 少一层但初始视野不变、隐藏状态按会话隔离、新图层默认显示而已隐藏的保持隐藏。

**写入 `tests/test_workspace_layers.py`：**

```python
"""工作台图层的页面回归：多轮累积、开关不重置视野、隐藏状态按会话隔离（AppTest，不调用模型）。"""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agent import artifacts, react, sessions

PAGE = Path(__file__).resolve().parents[1] / "app" / "GeoAgent.py"


def _feature(shape, coordinates, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": shape, "coordinates": coordinates}}


BUFFER = _feature("Polygon", [[[42.3, 11.6], [44.3, 11.6], [44.3, 13.6], [42.3, 13.6], [42.3, 11.6]]],
                  kind="buffer", radius_km=150)
EVENT = _feature("Point", [43.3, 12.6], event_type="Battles", date="2023-12-15", location="Bab el Mandeb")
TRACK = _feature("LineString", [[38.0, 20.0], [39.0, 19.0], [40.0, 18.0]], mmsi=668116204,
                 points_shown=3, points_total=120)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "DB_PATH", tmp_path / "sessions.duckdb")

    def no_model(*args, **kwargs):
        raise AssertionError("图层回归不得调用模型 API")

    monkeypatch.setattr(react, "_get_llm", no_model)
    return sessions


@pytest.fixture
def geojson():
    """在受控产物目录里写 GeoJSON（tests/conftest.py 已把该目录隔离到每个测试的临时目录）。"""
    def write(name, features):
        artifacts.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = artifacts.OUTPUT_DIR / f"{name}.geojson"
        path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
        return str(path)

    return write


def _session(store, turns):
    """turns: 每轮回答保存的地图文件列表。"""
    sid = store.create_session("图层测试")
    for index, paths in enumerate(turns, 1):
        seq = store.save_message(sid, "user", f"第{index}轮问题")
        store.save_message(sid, "assistant", f"第{index}轮回答", geojson=paths, reply_to_seq=seq)
    return sid


def _open(app, sid):
    app.button(key=f"session_{sid}").click().run()
    assert not app.exception
    return app


def _app():
    app = AppTest.from_file(str(PAGE), default_timeout=20).run()
    assert not app.exception
    return app


def _deck(app):
    charts = app.get("deck_gl_json_chart")
    assert len(charts) == 1
    return json.loads(charts[0].proto.json)


def _captions(app):
    return "\n".join(str(element.value) for element in app.caption)


def _markdown(app):
    return "\n".join(str(element.value) for element in app.markdown)


def test_two_turns_accumulate_and_view_follows_latest_turn(store, geojson):
    track = geojson("track", [TRACK])
    events = geojson("events", [BUFFER, EVENT])
    sid = _session(store, [[track], [events]])
    app = _open(_app(), sid)

    assert app.pills[0].value == [f"{track}#track", f"{events}#buffer", f"{events}#events"]
    assert "3 个图层 · 3 个要素 · 已定位到最新结果" in _captions(app)
    view = _deck(app)["initialViewState"]
    assert (view["latitude"], view["longitude"]) == pytest.approx((12.6, 43.3))


def test_hiding_a_layer_drops_it_but_keeps_the_view(store, geojson):
    track = geojson("track", [TRACK])
    events = geojson("events", [BUFFER, EVENT])
    sid = _session(store, [[track], [events]])
    app = _open(_app(), sid)
    before = _deck(app)
    assert "武装冲突" in _markdown(app)  # 底栏图例

    app.pills[0].unselect(f"{events}#events").run()
    assert not app.exception
    after = _deck(app)
    assert len(after["layers"]) == len(before["layers"]) - 1
    assert after["initialViewState"] == before["initialViewState"]
    assert "3 个图层 · 3 个要素（1 个已隐藏）" in _captions(app)
    assert "武装冲突" not in _markdown(app)
    assert app.session_state["hidden_layers"][sid] == {f"{events}#events"}


def test_hidden_layers_are_kept_per_session(store, geojson):
    first_file, second_file = geojson("a", [BUFFER]), geojson("b", [BUFFER])
    first, second = _session(store, [[first_file]]), _session(store, [[second_file]])
    app = _open(_app(), first)
    app.pills[0].unselect(f"{first_file}#buffer").run()
    assert app.pills[0].value == []
    assert not _deck(app).get("layers")

    _open(app, second)
    assert app.pills[0].value == [f"{second_file}#buffer"]
    _open(app, first)
    assert app.pills[0].value == []


def test_new_layers_show_by_default_while_hidden_ones_stay_hidden(store, geojson):
    old = geojson("old", [BUFFER])
    sid = _session(store, [[old]])
    app = _open(_app(), sid)
    app.pills[0].unselect(f"{old}#buffer").run()

    new = geojson("new", [EVENT])
    seq = store.save_message(sid, "user", "第2轮问题")
    store.save_message(sid, "assistant", "第2轮回答", geojson=[new], reply_to_seq=seq)
    _open(app, sid)
    assert app.pills[0].value == [f"{new}#events"]
    assert "2 个图层 · 2 个要素（1 个已隐藏）" in _captions(app)
```

- [ ] **Step 6: CSS 预算检查**

**追加到 `tests/test_theme.py` 末尾：**

```python
# 设计文档 4.3 登记表里的增强样式用到的 data-testid
REGISTERED_TESTIDS = {
    "stBaseButton-primary", "stMainBlockContainer", "stDeckGlJsonChart", "stChatMessage",
    "stChatMessageAvatarUser", "stHorizontalBlock", "stColumn", "stLayoutWrapper",
}


def test_custom_css_stays_within_budget_and_registered_selectors():
    sheets = sorted(STYLES.glob("*.css"))
    assert [sheet.name for sheet in sheets] == ["base.css", "workspace.css"]
    texts = [sheet.read_text(encoding="utf-8") for sheet in sheets]
    assert sum(len(text.splitlines()) for text in texts) <= 250
    testids = [found for text in texts for found in re.findall(r'\[data-testid="([^"]+)"\]', text)]
    assert len(testids) <= 20
    assert set(testids) <= REGISTERED_TESTIDS
    assert not (ROOT / "app" / "chat.css").exists()
    # CSS 只放在 app/styles/ 里，Python 文件不再内嵌 data-testid 选择器
    leaks = [path.name for path in (ROOT / "app").rglob("*.py") if "data-testid" in path.read_text(encoding="utf-8")]
    assert not leaks
```

- [ ] **Step 7: 运行，确认失败**

```bash
python -m pytest tests/test_chat_workspace.py tests/test_memory_ui.py tests/test_map_display.py tests/test_workspace_sessions.py tests/test_workspace_layers.py tests/test_theme.py -q
```

预期：失败（旧界面没有 `session_<sid>` 按钮、没有 `sessions_ui` 模块与 `workspace.css`，`app/chat.css` 仍在）。

- [ ] **Step 8: 侧栏 `app/sessions_ui.py`**

最近会话放在固定 320px 的滚动容器里，每条是一个按钮（当前会话 secondary，其余 tertiary），点击即打开；记忆卡片沿用原有字段标签，摘要放进"早期对话摘要"折叠区。

**写入 `app/sessions_ui.py`：**

```python
"""工作台侧栏：新建分析、最近会话（点一下即打开）、本会话记忆卡片。"""

from __future__ import annotations

import html

import streamlit as st

from agent import conversation
from agent import sessions as sessions_mod

PROMPT_KEY = "geoagent_prompt"
MEMORY_FIELDS = [
    ("mmsi", "船号 MMSI"), ("place", "地点"), ("coordinates", "坐标"), ("days", "最近天数"),
    ("time_range", "时间窗"), ("radius_km", "半径（公里）"), ("table", "数据表"), ("filters", "筛选条件"),
]
VALUE_LABELS = {
    "lat": "纬度", "lon": "经度", "start": "开始", "end": "结束", "risk_level_min": "最低风险等级",
    "domain": "领域", "target_class": "目标类别", "ship_type": "船型", "country": "国家", "event_type": "事件类型",
}


def memory_value(value) -> str:
    """把结构化条件转成可读文本，避免把存储元数据直接暴露出来。"""
    if isinstance(value, dict):
        return "；".join(f"{VALUE_LABELS.get(k, k)}：{memory_value(v)}" for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return "、".join(memory_value(item) for item in value)
    return str(value)


def clear_draft() -> None:
    st.session_state[PROMPT_KEY] = ""
    st.session_state.pop("_pending_question", None)


def start_new() -> None:
    st.session_state.agent_messages = []
    st.session_state.current_session_id = None
    clear_draft()


def open_session(sid: str) -> None:
    st.session_state.agent_messages = sessions_mod.load_messages(sid)
    st.session_state.current_session_id = sid
    clear_draft()


def delete_current(sid: str) -> None:
    sessions_mod.delete_session(sid)
    start_new()


def _clear_memory(sid: str) -> None:
    sessions_mod.clear_memory(sid)


def render(busy: bool) -> dict:
    """渲染侧栏并返回 {会话 id: 标题}，供对话标题栏使用。"""
    current = st.session_state.get("current_session_id")
    titles = {}
    with st.sidebar:
        st.button("新建分析", key="new_analysis", type="primary", icon=":material/add:", width="stretch",
                  disabled=busy, on_click=start_new)
        st.caption("最近会话")
        with st.container(height=320, border=False, key="session_list"):
            past = sessions_mod.list_sessions()
            if not past:
                st.caption("还没有历史会话")
            for sid, title, created, count in past:
                titles[sid] = title or "未命名会话"
                when = created.strftime("%Y-%m-%d %H:%M") if created else ""
                st.button(titles[sid], key=f"session_{sid}", type="secondary" if sid == current else "tertiary",
                          width="stretch", disabled=busy, help=f"{count} 条消息 · 创建于 {when}",
                          on_click=open_session, args=(sid,))
        render_memory(current, busy)
    return titles


def render_memory(sid: str | None, busy: bool) -> None:
    """会话记忆始终按会话 ID 读取，切换会话时不会沿用其他会话的状态。"""
    memory = conversation.get_memory(sid) if sid else {}
    state = memory.get("state") or {}
    summary = memory.get("summary") or ""
    with st.container(border=True, key="memory_card"):
        st.markdown('<div class="gs-card-t">本会话记忆</div>', unsafe_allow_html=True)
        visible = [(label, state[key]) for key, label in MEMORY_FIELDS
                   if key in state and state[key] not in (None, "", {}, [])]
        if visible:
            chips = "".join(f'<span class="gs-chip"><em>{html.escape(label)}</em>{html.escape(memory_value(value))}</span>'
                            for label, value in visible)
            st.markdown(f'<div class="gs-chips">{chips}</div>', unsafe_allow_html=True)
        else:
            st.caption("暂无已记录的分析条件。新会话独立记忆。")
        if summary:
            with st.expander("早期对话摘要"):
                st.text(summary)
        else:
            st.caption("早期对话摘要：暂无")
        st.button("清空分析记忆", key="clear_analysis_memory", type="tertiary", icon=":material/delete_sweep:",
                  disabled=busy or not sid, on_click=_clear_memory, args=(sid,),
                  help="清空后不再将此前对话用于分析；聊天记录和已有地图仍保留。")
```

- [ ] **Step 9: 消息与对话部件 `app/chat_ui.py`**

"分析过程 · N 步 · 定位地点 → 分析周边事件"：工具名转中文，连续重复只记一次，最多 3 个。中断判定：没有任何助手消息的 `reply_to_seq` 指向这条提问，且不是"紧跟一条未关联的旧式助手回答"。结果标签的名称与图层按钮一致、色块与地图同色。

**写入 `app/chat_ui.py`：**

```python
"""对话面板：标题栏、消息、分析过程、结果标签、空状态示例与中断标注（设计文档 6.3）。"""

from __future__ import annotations

import html
import json

import streamlit as st

from agent import artifacts
from agent.conversation import clean_assistant_text
from app import map_view, palette, sessions_ui

ASSISTANT_AVATAR = ":material/radar:"
RADAR_SVG = ('<svg viewBox="0 0 24 24" width="28" height="28" aria-hidden="true">'
             '<circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-opacity=".6" stroke-width="1.5"/>'
             '<path d="M12 12 17 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
             '<circle cx="12" cy="12" r="2.2" fill="currentColor"/></svg>')
TOOL_LABELS = {
    "geocode": "定位地点", "buffer_analysis": "分析周边事件", "ship_track": "查询船舶航迹",
    "query_database": "查询数据", "knowledge_search": "检索相关报道",
}
TABLE_LABELS = {"acled_events": "ACLED", "gdelt_events": "GDELT"}
EXAMPLES = [
    ("周边事件", ":material/warning:", "曼德海峡周边150公里内发生了多少起事件？按类型统计"),
    ("船舶航迹", ":material/directions_boat:", "MMSI 668116204 最近30天走了什么路线？"),
    ("事件背景", ":material/article:", "银河领袖号被劫持事件有什么背景？有哪些相关报道？"),
    ("冲突排名", ":material/public:", "Goldstein 冲突最激烈的5个国家是哪些？"),
]


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, "分析数据")


def step_detail(name: str, args: dict) -> str:
    """进行中列表里的一行摘要：只用调用参数，不解析工具输出。"""
    if name == "geocode":
        return f"定位地点：{args.get('place', '')}"
    if name == "buffer_analysis":
        table = args.get("table", "acled_events")
        return f"分析周边事件：{TABLE_LABELS.get(table, table)}，半径 {args.get('radius_km')} km"
    if name == "ship_track":
        return f"查询船舶航迹：MMSI {args.get('mmsi')}，最近 {args.get('days', 7)} 天"
    if name == "knowledge_search":
        return f"检索相关报道：{args.get('query', '')}"
    return tool_label(name)


def _tool_names(message: dict) -> list[str]:
    records = message.get("tool_records") or []
    if records:
        return [str(record.get("name", "")) for record in records]
    return [str(step).split("(", 1)[0] for step in message.get("steps") or []]


def steps_summary(message: dict) -> str:
    """"定位地点 → 分析周边事件"：连续重复只记一次，最多 3 个。"""
    labels = []
    for name in _tool_names(message):
        label = tool_label(name)
        if not labels or labels[-1] != label:
            labels.append(label)
    return " → ".join(labels[:3] + (["…"] if len(labels) > 3 else []))


def process_label(message: dict) -> str:
    summary = steps_summary(message)
    return f"分析过程 · {len(_tool_names(message))} 步" + (f" · {summary}" if summary else "")


def prefill(question: str) -> None:
    st.session_state[sessions_ui.PROMPT_KEY] = question


def unanswered(messages: list[dict]) -> set:
    """没有收到回答的提问 seq：既没有助手消息的 reply_to_seq 指向它，
    也不是"紧跟一条未关联的旧式助手回答"的情况。"""
    replied = {m.get("reply_to_seq") for m in messages if m.get("role") == "assistant"}
    result = set()
    for index, message in enumerate(messages):
        seq = message.get("seq")
        if message.get("role") != "user" or seq is None or seq in replied:
            continue
        following = messages[index + 1] if index + 1 < len(messages) else None
        if following and following.get("role") == "assistant" and following.get("reply_to_seq") is None:
            continue
        result.add(seq)
    return result


def header(title: str, subtitle: str, sid: str | None, busy: bool) -> None:
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="chat_header"):
        st.markdown(f'<div class="gs-chat-title"><b>{html.escape(title)}</b>'
                    f'<span>{html.escape(subtitle)}</span></div>', unsafe_allow_html=True)
        with st.popover("", icon=":material/more_horiz:", type="tertiary", disabled=busy or not sid,
                        key="chat_menu"):
            st.caption("删除会同时移除本会话的聊天记录与记忆。")
            st.button("删除会话", key="delete_session", icon=":material/delete:", width="stretch",
                      on_click=sessions_ui.delete_current, args=(sid,))


def welcome(busy: bool) -> None:
    st.markdown(
        '<div class="gs-welcome"><div class="gs-welcome-mark">' + RADAR_SVG + '</div>'
        '<h3>从一个问题开始</h3><p>查询周边事件、回看船舶航迹，或从新闻中了解事件背景。<br>'
        '结果会作为图层出现在右侧地图上。</p></div>', unsafe_allow_html=True,
    )
    columns = st.columns(2, gap="small")
    for index, (label, icon, question) in enumerate(EXAMPLES):
        with columns[index % 2]:
            st.button(label, key=f"geoagent_example_{index}", icon=icon, help=question, width="stretch",
                      disabled=busy, on_click=prefill, args=(question,))
    st.caption("点选示例只会填入输入框，可修改后再发送")


def render_process(message: dict) -> None:
    records = message.get("tool_records") or []
    steps = message.get("steps") or []
    if not records and not steps:
        return
    icon = ":material/error:" if message.get("error") else ":material/check_circle:"
    with st.expander(process_label(message), icon=icon, expanded=False):
        if records:
            for record in records:
                state = "已阻止重复执行" if record.get("blocked") else ("已完成" if record.get("success") else "未完成")
                st.caption(f"{tool_label(record.get('name', ''))} · {state}")
                st.code(json.dumps(record.get("args", {}), ensure_ascii=False, indent=2), language="json")
                st.text(str(record.get("output", ""))[:1800])
        else:
            for step in steps:
                st.code(str(step), language="text")


def _swatch(kind: str, mode: str) -> str:
    colors = palette.MAP[mode]
    if kind == "buffer":
        return f'<i class="ring" style="border-color:{colors["buffer"]}"></i>'
    if kind == "track":
        return f'<i class="line" style="background:{colors["track"]}"></i>'
    if kind == "events":
        return f'<i class="dot" style="background:{palette.EVENT_COLORS["Battles"]}"></i>'
    return f'<i class="ring" style="border-color:{colors["ring"]}"></i>'


def result_chips(message: dict, mode: str) -> None:
    """本轮产生的图层：名称与图层按钮一致，色块与地图同色。"""
    chips = []
    for path in message.get("geojson") or []:
        try:
            data = map_view.load(path)
        except artifacts.ArtifactError:
            continue
        for kind, features in map_view.split(data):
            chips.append(f'<span class="gs-result">{_swatch(kind, mode)}{html.escape(map_view.layer_label(kind, features))}</span>')
    if chips:
        st.markdown(f'<div class="gs-results">{"".join(chips)}</div>', unsafe_allow_html=True)


def render_message(message: dict, mode: str, *, interrupted: bool = False, busy: bool = False) -> None:
    is_user = message.get("role") == "user"
    with st.chat_message("user" if is_user else "assistant", avatar="user" if is_user else ASSISTANT_AVATAR):
        content = message.get("content") or "本轮没有生成回答。"
        if is_user:
            st.markdown(content)
            if interrupted:
                st.caption("分析被中断，没有生成回答")
                st.button("重新填入", key=f"refill_{message.get('seq')}", type="tertiary", icon=":material/edit:",
                          disabled=busy, on_click=prefill, args=(content,))
            return
        render_process(message)
        st.markdown(clean_assistant_text(content))
        result_chips(message, mode)
        if message.get("error"):
            st.caption("本轮分析未完成，可调整问题后重试。")
```

- [ ] **Step 10: 工作台布局样式**

增强样式 #4（用户气泡靠右）、#5（窄于 1000px 上下排列，只作用于最外层两栏）、#7（会话列表左对齐省略）、#8（填满视口）。#8 失效时退回 Python 里写的固定高度：对话历史 520px、地图画布 600px（样机实测）。

**写入 `app/styles/workspace.css`：**

```css
/* 工作台布局（设计文档 6.1）。.st-key-* 由 st.container(key=...) 生成，有文档保证；
   [data-testid] 只出现在登记过的增强样式里（设计文档 4.3 表 #4–#8）。 */

/* 面板 */
.st-key-chat_panel, .st-key-map_panel {
  background: var(--gs-panel); border: 1px solid var(--gs-line); border-radius: 12px; gap: 0; overflow: hidden;
}
.st-key-chat_header { padding: 10px 10px 10px 18px; border-bottom: 1px solid var(--gs-line); min-height: 56px; }
.gs-chat-title b { display: block; font-size: 14.5px; font-weight: 650; color: var(--gs-text); line-height: 1.4; }
.gs-chat-title span { font-size: 12px; color: var(--gs-muted); }
.st-key-chat_history { padding: 12px 16px; }
.st-key-chat_composer { padding: 10px 16px 12px; border-top: 1px solid var(--gs-line); gap: 6px; }
.st-key-map_bar { padding: 10px 12px; border-bottom: 1px solid var(--gs-line); min-height: 56px; }
.st-key-map_footer { padding: 8px 14px 10px; border-top: 1px solid var(--gs-line); gap: 16px; }

/* 空状态 */
.gs-welcome { text-align: center; padding: 28px 8px 8px; }
.gs-welcome-mark { width: 46px; height: 46px; border-radius: 13px; margin: 0 auto 14px; display: grid;
  place-items: center; background: var(--gs-accent-soft); color: var(--gs-accent); }
.gs-welcome h3 { font-size: 19px; margin: 0 0 8px; padding: 0; color: var(--gs-text); }
.gs-welcome p { color: var(--gs-muted); font-size: 13px; line-height: 1.7; }

/* 回答末尾的结果标签：色块与地图图层同色 */
.gs-results { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 2px; }
.gs-result { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--gs-muted);
  border: 1px solid var(--gs-line); border-radius: 999px; padding: 2px 9px; }
.gs-result i { display: inline-block; flex: none; }
.gs-result i.line { width: 14px; height: 3px; border-radius: 2px; }
.gs-result i.ring { width: 10px; height: 10px; border-radius: 50%; border: 2px solid; box-sizing: border-box; }
.gs-result i.dot { width: 8px; height: 8px; border-radius: 50%; }

/* 本会话记忆 */
.gs-card-t { font-size: 14px; font-weight: 650; color: var(--gs-text); }
.gs-chips { display: flex; flex-wrap: wrap; gap: 5px; }
.gs-chip { font-size: 12px; border: 1px solid var(--gs-line); background: var(--gs-soft); border-radius: 6px;
  padding: 2px 7px; color: var(--gs-text); }
.gs-chip em { font-style: normal; color: var(--gs-muted); margin-right: 4px; }

/* ---- 增强样式：失效时只退回原生外观 ---- */
/* #4 用户消息靠右气泡、隐藏用户头像 */
.st-key-chat_history [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  margin-left: auto; max-width: 86%; background: var(--gs-user); border: 1px solid var(--gs-user-line);
  border-radius: 14px 14px 4px 14px; padding: 8px 12px;
}
.st-key-chat_history [data-testid="stChatMessageAvatarUser"] { display: none; }
/* #5 窄于 1000px 时对话与地图上下排列；只作用于最外层两栏，标题栏、示例按钮等内部横排不受影响 */
@media (max-width: 1000px) {
  .st-key-workspace > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { flex-direction: column; }
  .st-key-workspace > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    width: 100% !important; flex: 1 1 100% !important; }
}
/* #7 会话列表左对齐、单行省略 */
.st-key-session_list button > div { justify-content: flex-start; min-width: 0; }
.st-key-session_list button p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* #8 两个面板填满视口：对话历史与地图画布吃掉其余高度（失效时退回 Python 里的 520px / 600px） */
[data-testid="stLayoutWrapper"]:has(> .st-key-chat_panel),
[data-testid="stLayoutWrapper"]:has(> .st-key-map_panel) { height: calc(100dvh - 5.5rem); }
.st-key-chat_panel, .st-key-map_panel { height: 100%; }
[data-testid="stLayoutWrapper"]:has(> .st-key-chat_history),
[data-testid="stLayoutWrapper"]:has(> .st-key-map_canvas) { flex: 1 1 0; height: auto !important; min-height: 0; }
```

- [ ] **Step 11: 工作台页面 `app/workspace.py`**

**写入 `app/workspace.py`：**

```python
"""GeoAgent 工作台：左侧对话、右侧地图（设计文档第 6 节）。

渲染顺序是"防打断"的关键：先取得输入框的提交，再画侧栏和图层开关——本轮有提交时，
其余可交互控件全部置灰，避免点击触发重跑、中止正在进行的分析。
"""

from __future__ import annotations

import json

import streamlit as st

from agent import conversation
from agent import sessions as sessions_mod
from app import chat_ui, map_view, sessions_ui, theme_watch, ui

ui.setup("工作台", watch=False)
ui.inject_css("workspace.css")

st.session_state.setdefault("agent_messages", [])
st.session_state.setdefault("current_session_id", None)

with st.container(key="workspace"):
    chat_col, map_col = st.columns([5, 7], gap="medium")
with chat_col, st.container(key="chat_panel"):
    header_slot = st.container()
    history = st.container(height=520, border=False, autoscroll=True, key="chat_history")
    composer = st.container(key="chat_composer")
with map_col, st.container(key="map_panel"):
    bar_slot = st.container(key="map_bar")
    alerts = st.container()
    canvas = st.container(height=600, border=False, key="map_canvas")  # 增强样式 #8 生效时拉伸填满面板
    footer_slot = st.container()

with composer:
    question = st.chat_input("输入地点、船号或分析问题…", key=sessions_ui.PROMPT_KEY, submit_mode="disable")
    st.caption("Enter 发送 · Shift+Enter 换行")
question = (question or "").strip()
busy = bool(question)
mode = theme_watch.mode(busy=busy)

titles = sessions_ui.render(busy)
messages = st.session_state.agent_messages
sid = st.session_state.current_session_id

first_question = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
title = (titles.get(sid) or first_question or question or "新会话")[:60]
subtitle = "分析中…" if busy else (f"{len(messages)} 条消息" if messages else "还没有消息")
with header_slot:
    chat_ui.header(title, subtitle, sid, busy)

interrupted = chat_ui.unanswered(messages)
with history:
    if not messages and not busy:
        chat_ui.welcome(busy)
    for message in messages:
        chat_ui.render_message(message, mode, interrupted=message.get("seq") in interrupted, busy=busy)

turn_paths = map_view.turns(messages)
state = map_view.build(turn_paths, map_view.reset_count())
with bar_slot:
    visible = map_view.render_bar(state, sid, busy)
last_error = next((m.get("error") for m in reversed(messages) if m.get("role") == "assistant"), None)
with alerts:
    map_view.render_alerts(state, last_error)
with canvas:
    live_slot = st.empty() if busy else None
    map_view.render_map(state, visible, mode, slot=live_slot,
                        key="workspace_map_live_0" if busy else "workspace_map")
with footer_slot:
    map_view.render_footer(state, visible, mode)


def run_analysis(question: str, sid: str) -> dict:
    """流式执行一轮分析：状态行显示当前步骤，工具一产出 GeoJSON 就上图。"""
    from agent import react

    next_turn = sum(m.get("role") == "assistant" for m in messages) + 1
    live_paths, shown, updates = [], set(visible), 0
    steps, records, paths = [], [], []
    answer, error, got_answer = "", None, False
    with st.chat_message("assistant", avatar=chat_ui.ASSISTANT_AVATAR):
        status = st.status("正在理解问题…", expanded=False)
        done = st.empty()
        finished = []
        try:
            for event in react.stream(question, session_id=sid):
                if event["type"] == "thinking":
                    status.update(label="正在整理分析…", state="running")
                elif event["type"] == "tool_start":
                    label = chat_ui.tool_label(event["name"])
                    args_text = ", ".join(f"{k}={v!r}" for k, v in event["args"].items())
                    steps.append(f"{event['name']}({args_text})")
                    status.update(label=f"正在{label}…", state="running")
                    with status:
                        st.caption(label + (" · 已阻止重复执行" if event.get("blocked") else ""))
                        st.code(json.dumps(event["args"], ensure_ascii=False, indent=2), language="json")
                    finished.append(chat_ui.step_detail(event["name"], event["args"]))
                elif event["type"] == "tool_end":
                    with status:
                        st.text(event["output"][:1200])
                    done.caption("\n\n".join(f"✓ {line}" for line in finished))
                    if event.get("geojson_path"):
                        live_paths.append(event["geojson_path"])
                elif event["type"] == "map_ready":
                    live_paths = list(event["paths"])
                elif event["type"] == "answer":
                    result = event["result"]
                    answer = result.answer or result.error or "本轮没有生成回答，请重新提问。"
                    error = result.error or (None if result.answer else "本轮未返回有效回答")
                    paths = result.geojson_paths
                    records = getattr(result, "tool_records", [])
                    got_answer = True
                if event["type"] in ("tool_end", "map_ready") and live_paths:
                    live = map_view.build(turn_paths + [(next_turn, list(dict.fromkeys(live_paths)))])
                    shown |= {layer.id for layer in live.layers if layer.turn == next_turn}
                    updates += 1
                    map_view.render_map(live, shown, mode, slot=live_slot, key=f"workspace_map_live_{updates}")
        except Exception as exc:
            error = f"分析中断：{type(exc).__name__}: {exc}"
            answer = "本轮分析未完成。请稍后重试，或缩小查询范围。"
        if not got_answer and not error:
            error = "分析结束但没有返回最终回答"
            answer = "本轮没有生成完整回答，请重新提问。"
        status.update(label="分析未完成" if error else "分析完成", state="error" if error else "complete")
        st.markdown(answer)
    return {"role": "assistant", "content": answer, "steps": steps, "geojson": paths,
            "tool_records": records, "error": error}


if busy:
    if not sid:
        sid = sessions_mod.create_session(question)
        st.session_state.current_session_id = sid
    user_seq = sessions_mod.save_message(sid, "user", question)
    messages.append({"role": "user", "content": question, "seq": user_seq})
    with history:
        chat_ui.render_message(messages[-1], mode, busy=True)
        reply = run_analysis(question, sid)
    reply["reply_to_seq"] = user_seq
    messages.append(reply)
    conversation.record_assistant(sid, reply["content"], reply["steps"], reply["geojson"],
                                  tool_records=reply["tool_records"], error=reply["error"], reply_to_seq=user_seq)
    st.rerun()
```

- [ ] **Step 12: 删除过渡代码与旧样式**

**删除 `app/map_view.py` 中的以下整段：**

```python
# ---------------------------------------------------------------- 过渡代码：旧工作台页面仍在调用，任务 7 删除
import math  # noqa: E402


@dataclass
class MapResult:
    layers: list = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    view: tuple = (15.0, 43.0, 4.5)
    points: int = 0
    features: int = 0


def prepare(paths: list[str]) -> MapResult:
    result = MapResult()
    bounds = []
    colors = [[34, 211, 238], [248, 113, 113], [251, 191, 36], [167, 139, 250]]
    for path in dict.fromkeys(paths):
        try:
            data = artifacts.load_geojson(path)
            bounds.append(artifacts.coordinate_bounds(data))
        except artifacts.ArtifactError as exc:
            result.errors.append(str(exc))
            continue
        result.paths.append(path)
        result.features += len(data["features"])
        result.points += sum(feature["geometry"]["type"] == "Point" for feature in data["features"])
        color = colors[len(result.layers) % len(colors)]
        result.layers.append(pdk.Layer(
            "GeoJsonLayer", data=data, stroked=True, filled=True, pickable=True,
            get_fill_color=color + [40], get_line_color=color + [220],
            get_line_width=3, line_width_min_pixels=3, point_radius_min_pixels=5,
        ))
    if bounds:
        left, bottom = min(b[0] for b in bounds), min(b[1] for b in bounds)
        right, top = max(b[2] for b in bounds), max(b[3] for b in bounds)
        span = max(right - left, top - bottom, .01)
        result.view = ((bottom + top) / 2, (left + right) / 2,
                       max(2., min(9., math.log2(180. / span))))
    return result


def render(slot, paths: list[str], *, last_error: str | None = None) -> MapResult:
    result = prepare(paths)
    slot.empty()
    with slot.container():
        if result.errors:
            st.warning("地图加载失败：" + "；".join(dict.fromkeys(result.errors)))
        if last_error and not result.paths:
            st.warning("本轮未生成可用地图，请查看对话中的执行失败说明。")
        lat, lon, zoom = result.view
        ui.deck(result.layers, lat, lon, zoom, tooltip="{date}{event_type}{location}", height=450)
        if result.paths:
            st.caption(f"已加载 {len(result.paths)} 个地图文件 · {result.features} 个要素 · {result.points} 个点要素")
        elif result.errors:
            st.caption("尚无可显示的分析图层；当前仅为默认底图。")
        else:
            st.caption("尚未生成分析图层；模型回答中的文件名不会自动作为地图结果。")
    return result
```

```bash
git rm -q app/chat.css
```

预期：成功，无输出。

- [ ] **Step 13: 运行，确认通过**

```bash
python -m pytest tests/test_chat_workspace.py tests/test_memory_ui.py tests/test_map_display.py tests/test_workspace_sessions.py tests/test_workspace_layers.py tests/test_theme.py -q
```

预期：通过，45 passed。

- [ ] **Step 14: 全量回归与冒烟**

```bash
python -m pytest tests/ -q
```

预期：通过，281 passed。

```bash
python scripts/smoke_test.py
```

预期：通过，"页面初始化：7/7 通过"。

- [ ] **Step 15: 提交**

```bash
git add -A app tests && \
  git commit -m "feat(app): 工作台重做" -m "侧栏最近会话一键打开、本会话记忆卡片；对话标题栏与 ··· 菜单、分析过程摘要、结果标签、空状态示例、中断标注与重新填入；地图图层累积可开关、复位、下载与图例；先取输入再以 disabled=busy 渲染其余控件，防止分析被点击打断；工作台高度填满视口。删除 chat.css 与 map_view 过渡代码。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 8: README 与依赖

**Files:**
- Modify: `requirements.txt:1`、`README.md`

- [ ] **Step 1: 依赖版本**

所有用到的能力（双主题子表、`st.navigation(position="top")`、`st.pills`、`st.components.v2`、`chat_input(submit_mode=...)`、`st.container(horizontal=...)`）都是在 1.59 上验证的。

**修改 `requirements.txt`，把：**

```text
streamlit>=1.52
```

**替换为：**

```text
streamlit>=1.59
```

- [ ] **Step 2: README 界面说明**

**修改 `README.md`，把：**

```markdown
对话工作台：左侧聊天独立滚动，输入区留在面板底部；用户消息与分析回答分层展示，工具明细默认收在“分析过程”中。右侧地图随几何结果即时更新，窄屏下改为上下布局。

示例问题先填入可编辑草稿，确认发送后才开始分析。侧栏保留会话恢复与记忆查看，错误回复会保存并明确标记为未完成。地图结果提供 GeoJSON 下载。界面支持深浅主题，要求 Streamlit 1.52 及以上。
```

**替换为：**

```markdown
工作台：侧栏列出最近会话，点一下即可打开；对话与地图左右两栏、高度随窗口填满，窄于 1000px 时改为上下排列。每轮分析产出的缓冲区、事件点、航迹各自成为一个图层，在会话内累积、可单独开关；新结果到达时地图自动定位，“复位”回到最新结果的范围。工具明细默认收在“分析过程”里；分析进行中其余控件暂时置灰，避免误触打断。

示例问题先填入可编辑草稿，确认发送后才开始分析。被中断、没有得到回答的提问会标注出来，可一键重新填入。侧栏“本会话记忆”可查看与清空，错误回复会保存并明确标记为未完成。地图结果提供 GeoJSON 下载。右上角 ⋮ 菜单可切换 System / Light / Dark（默认跟随系统），要求 Streamlit 1.59 及以上。
```

**修改 `README.md`，把：**

```markdown
| GeoJSON / deck.gl 可视化交互                   | 三类几何结果（圆/点/线）即时上图，流式工具调用可视化，多轮指代对话，会话持久化                                               | `app/GeoAgent.py`                 |
```

**替换为：**

```markdown
| GeoJSON / deck.gl 可视化交互                   | 缓冲区 / 事件点 / 航迹按会话累积为可开关的图层，流式工具调用可视化，多轮指代对话，会话持久化                                     | `app/workspace.py` `app/map_view.py` |
```

**修改 `README.md`，把：**

```text
# 3. 启动（GeoAgent 即首屏）
```

**替换为：**

```text
# 3. 启动（首屏为工作台，顶部导航进入各看板页）
```

**修改 `README.md`，把：**

```text
├── app/GeoAgent.py     # GeoAgent 首屏（对话 + 流式工具可视化 + 即时上图）
├── app/pages/          # 总览 / AIS / ACLED / 时空叠加 / 新闻检索 / 全球背景参考
```

**替换为：**

```text
├── app/GeoAgent.py     # 入口：Logo、顶部导航与页面路由
├── app/workspace.py    # 工作台（对话 + 流式工具可视化 + 图层地图）
├── app/sessions_ui.py  # 侧栏：新建分析、最近会话、本会话记忆
├── app/chat_ui.py      # 消息、分析过程、空状态示例、中断标注
├── app/map_view.py     # 图层拆分、累积、开关、视野、图例、下载
├── app/palette.py      # 数据配色：分类色板与有序/发散/顺序色阶
├── app/theme_watch.py  # 读取浏览器当前深浅主题，供地图图层取色
├── app/styles/         # 设计令牌与工作台布局 CSS
├── app/dashboards/     # 总览 / AIS / ACLED / 时空叠加 / 新闻检索 / 全球背景参考
```

- [ ] **Step 3: 全量回归**

```bash
python -m pytest tests/ -q
```

预期：通过，281 passed。

- [ ] **Step 4: 提交**

```bash
git add requirements.txt README.md && \
  git commit -m "docs: README 界面说明更新，依赖 streamlit>=1.59" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

---

### Task 9: 真实分析验收（调用模型约 2 次）

这一步会用 `.env` 里配置的服务调用模型约 2 次（用户已同意）。全程在浏览器里手动操作；这一轮建出的会话（航迹 + 缓冲区两轮）也是任务 10 截图用的展示会话。

- [ ] **Step 1: 启动应用**

```bash
# 手动：另开一个终端，保持运行
streamlit run app/GeoAgent.py --server.port=8501
```

预期：浏览器打开 http://localhost:8501，首屏为工作台。

- [ ] **Step 2: 第一轮：航迹**

点「新建分析」，输入"MMSI 668116204 最近30天走了什么路线？"并发送。逐项确认：

- 状态行显示转圈 +"正在查询船舶航迹…"，下方逐条出现"✓ 查询船舶航迹：MMSI 668116204，最近 30 天"；
- 分析进行中：侧栏会话按钮、「新建分析」、示例、··· 菜单、图层按钮、复位、下载都置灰，输入框禁用；
- 航迹一产出就画到地图上；
- 完成后：回答上方是收起的"分析过程 · N 步 · 查询船舶航迹…"，回答下方有"航迹 · 668116204"结果标签；图层栏出现同名按钮；地图定位到航迹；侧栏会话列表出现这条会话并高亮。

- [ ] **Step 3: 第二轮：缓冲区（同一会话）**

输入"曼德海峡周边150公里内发生了多少起事件？按类型统计"。确认：

- 新的"缓冲区 150 km""事件点 · N"按钮出现，航迹图层仍在（累积）；地图定位到缓冲区；
- 底栏统计"3 个图层 · M 个要素 · 已定位到最新结果"，图例只列出实际出现的事件类型；
- 拖动地图后点"事件点"按钮隐藏：图层消失、视野不跳回；统计出现"（1 个已隐藏）"；点「复位」回到最新结果的范围；
- 下载 popover 按文件列出两项，下载的文件能用文本编辑器打开。

- [ ] **Step 4: 主题与刷新**

- ⋮ → Dark：控件、图表、底图与地图图层（缓冲区琥珀、航迹青）一起变；再切 Light、System 都正确，无需刷新；
- 分析进行中切换主题不会中断本轮，本轮结束后地图配色才跟上（设计如此）；
- 刷新页面：从会话列表打开这条会话，消息与图层恢复，隐藏状态恢复为全部显示（设计如此）。

- [ ] **Step 5: 记录结果**

把结论（通过 / 发现的问题）写进 PR 描述或交接说明；发现问题时先用 superpowers:systematic-debugging 定位，再补测试与修复。

---

### Task 10: 视觉验收与 README 截图

**Files:**
- Create: `scripts/capture_screens.py`、`docs/ui-light-1440x900.png`、`docs/ui-dark-1440x900.png`
- Modify: `README.md`、`.gitignore`

- [ ] **Step 1: 截图脚本**

无头 Chrome + CDP，主题通过模拟系统深浅色切换（菜单默认 System）。需要本机 Chrome（找不到时用环境变量 `CHROME_PATH` 指定）和 `websocket-client`（`pip install websocket-client`，不进 `requirements.txt`）。

**写入 `scripts/capture_screens.py`：**

```python
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
```

**修改 `.gitignore`，把：**

```text
screenshot.png
```

**替换为：**

```text
screenshot.png
tmp/
```

- [ ] **Step 2: 截取验收图**

应用保持运行（任务 9 的终端）。

```bash
# 手动：每页等待约 20 秒，全套约 10 分钟
python scripts/capture_screens.py --out tmp/screens
python scripts/capture_screens.py --out tmp/screens --size 1366x768
python scripts/capture_screens.py --out tmp/screens --pages 工作台 --open-session 668116204 --name 工作台-会话 --size 1440x900 --size 1366x768
python scripts/capture_screens.py --out tmp/screens --pages 工作台 --size 1000x800
```

预期：`tmp/screens/` 下生成 7 页 × 浅/深 × 两种尺寸，加上打开会话的工作台和 1000px 宽的工作台。

- [ ] **Step 3: 逐张检查**

对照设计文档第 6、8 节的设计稿：

- 没有深底深字、浅底浅字；没有文字溢出或被遮挡；
- 工作台两栏填满视口，对话历史在面板内滚动；图层按钮名称与地图、结果标签、底栏图例一致；
- 1000px 宽：顶部导航折叠成"N more"，对话与地图上下排列，标题栏与 ··· 菜单仍在同一行，4 个示例按钮两两一行；
- 深色下热力图、ACLED 阶段色、GDELT 发散色清楚；总览饼图是蓝 / 橙 / 青（全局分类色板），不是 Plotly 默认色。

- [ ] **Step 4: README 截图**

```bash
# 手动：截任务 9 建的展示会话，浅色、深色各一张
python scripts/capture_screens.py --out docs --pages 工作台 --open-session 668116204 --name ui --size 1440x900
```

预期：生成 `docs/ui-light-1440x900.png` 与 `docs/ui-dark-1440x900.png`。

**修改 `README.md`，把：**

```markdown
| "曼德海峡周边 150km 内发生了多少起事件？" | "MMSI 668116204 最近 30 天走了什么路线？" | "银河领袖号事件有什么背景？" |
```

**替换为：**

```markdown
| "曼德海峡周边 150km 内发生了多少起事件？" | "MMSI 668116204 最近 30 天走了什么路线？" | "银河领袖号事件有什么背景？" |

| 浅色主题 | 深色主题 |
| --- | --- |
| ![工作台（浅色）](docs/ui-light-1440x900.png) | ![工作台（深色）](docs/ui-dark-1440x900.png) |
```

- [ ] **Step 5: 提交**

```bash
# 手动：截图生成后执行
git add scripts/capture_screens.py docs/ui-light-1440x900.png docs/ui-dark-1440x900.png README.md .gitignore && \
  git commit -m "docs: 界面截图与截图脚本" -m "scripts/capture_screens.py 用无头 Chrome 按主题、尺寸截取各页；README 换上浅色、深色工作台截图。" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

预期：提交成功。

- [ ] **Step 6: 收尾**

全部任务完成后，使用 superpowers:finishing-a-development-branch 决定合并到 `master` 还是提 PR。
