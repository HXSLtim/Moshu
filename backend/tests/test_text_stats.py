"""章节字数统计规则的回归测试。"""

from app.core.text_stats import count_text_units


def test_chinese_text_counts_non_whitespace_characters():
    """中文按字符计数，空白不参与统计。"""
    assert count_text_units("你好，世界") == 5
    assert count_text_units("  你好\n世界  ") == 4


def test_combining_marks_are_not_counted_separately():
    """组合重音与声调标记不拆成独立字数。"""
    assert count_text_units("e\u0301") == 1


def test_zero_width_joiner_is_ignored():
    """ZWJ 是连接控制符，不计入字数。"""
    assert count_text_units("A\u200dB") == 2


def test_empty_and_whitespace_only_text_returns_zero():
    """空文本和纯空白都不产生字数。"""
    assert count_text_units("") == 0
    assert count_text_units(" \t\n\r") == 0


def test_latin_letters_and_punctuation_are_counted_without_spaces():
    """英文字符仍按字符数计，空格被排除。"""
    assert count_text_units("hello world") == 10
    assert count_text_units("hello, world!") == 12
