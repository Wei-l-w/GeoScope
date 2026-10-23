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
