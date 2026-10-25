"""助手回答的加粗显示修正：中文"**标题：**正文"在 CommonMark 下收不了尾，星号会原样显示。"""

import pytest

from app import chat_ui

FIXED = [
    ("**船舶与说法：**银河领袖号", "**船舶与说法**：银河领袖号"),
    ("- **时间与地点：**2023年11月19日", "- **时间与地点**：2023年11月19日"),
    ("**甲：**一，**乙；**二", "**甲**：一，**乙**；二"),
    ("**甲**：一，**乙：**二", "**甲**：一，**乙**：二"),  # 前一段的收尾不能被当成下一段的开头
    ("**注：。**正文", "**注**：。正文"),
    ("| **战斗：**56 | 共计 |", "| **战斗**：56 | 共计 |"),
    ("**Note:**text", "**Note**:text"),
]
UNCHANGED = [
    "**战斗（Battles）**：56 起",  # 收尾前是括号、后面是标点：本来就能收尾
    "**150 公里**内",
    "**56**起，**战斗**为主",  # 前一段的收尾后面是"起，"，不是下一段加粗的开头
    "在**曼德海峡**附近，**胡塞武装**发动了袭击",
    "| **战斗** | 共56起，**最多** |",
    "**注意：** 下一句",  # 收尾后面是空格
    "**小结：**",  # 收尾在行末
    "**小结：**\n正文",
    "`f(**kw,**extra)` 与 `{**a,**b}`",  # 代码原样保留
    "```markdown\n**标题：**正文\n```",
    "没有加粗：照常显示",
]


@pytest.mark.parametrize("raw, shown", FIXED)
def test_trailing_punctuation_moves_outside_the_bold(raw, shown):
    assert chat_ui.fix_cjk_bold(raw) == shown


@pytest.mark.parametrize("text", UNCHANGED)
def test_bold_that_already_renders_is_left_alone(text):
    assert chat_ui.fix_cjk_bold(text) == text


def test_fixed_text_renders_more_bold_under_commonmark():
    markdown_it = pytest.importorskip("markdown_it")
    md = markdown_it.MarkdownIt("commonmark")
    for raw, shown in FIXED:
        assert md.render(shown).count("<strong>") > md.render(raw).count("<strong>"), raw
