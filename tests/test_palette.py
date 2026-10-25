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
