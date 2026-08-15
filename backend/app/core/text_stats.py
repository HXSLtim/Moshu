"""统一文本字数统计规则。

前后端必须共用同一语义：按 Unicode 码点计非空白字符，忽略组合标记
（重音、声调等）与零宽连接符，保证章节列表、正文编辑器和总字数一致。
"""

import unicodedata

ZWJ = "\u200d"


def count_text_units(text: str) -> int:
    """返回非空白 Unicode 字符数，不把组合标记与 ZWJ 计为独立字。"""
    if not text:
        return 0

    count = 0
    for char in text:
        if char == ZWJ or char.isspace():
            continue
        if unicodedata.category(char).startswith("M"):
            continue
        count += 1
    return count
