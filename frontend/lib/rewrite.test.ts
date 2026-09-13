import { describe, expect, it } from 'vitest';
import { applyRewrite, type RewriteSnapshot } from './rewrite';

const content = '开头🌙同一句。中间同一句。结尾';
const start = content.lastIndexOf('同一句');
const snapshot: RewriteSnapshot = { novelId: 1, chapterId: 2, content, start, end: start + 3, originalText: '同一句' };

describe('改写采纳边界', () => {
  it('重复文本与表情存在时只替换发起时的那一处', () => {
    expect(applyRewrite(content, 1, 2, snapshot, '新句子')).toBe('开头🌙同一句。中间新句子。结尾');
  });
  it('生成期间正文被编辑时拒绝用旧偏移覆盖', () => {
    expect(() => applyRewrite(`前置${content}`, 1, 2, snapshot, '新句子')).toThrow('正文已发生变化');
  });
  it('切换章节或小说后拒绝应用旧候选', () => {
    expect(() => applyRewrite(content, 1, 3, snapshot, '新句子')).toThrow('章节已切换');
    expect(() => applyRewrite(content, 9, 2, snapshot, '新句子')).toThrow('章节已切换');
  });
});
