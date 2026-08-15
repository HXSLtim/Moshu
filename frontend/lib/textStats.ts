/**
 * 与后端 `app/core/text_stats.py` 保持一致的章节字数统计。
 *
 * 规则：按 Unicode 码点计非空白字符，忽略组合标记（category M）
 * 与零宽连接符（ZWJ）。
 */

const MARK_PATTERN = /\p{M}/u;
const ZWJ = '\u200d';

export function countTextUnits(text: string): number {
  let count = 0;
  for (const char of text) {
    if (char === ZWJ || /\s/u.test(char)) continue;
    if (MARK_PATTERN.test(char)) continue;
    count += 1;
  }
  return count;
}
