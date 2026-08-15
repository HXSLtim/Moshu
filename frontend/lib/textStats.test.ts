import { describe, expect, it } from 'vitest';
import { countTextUnits } from './textStats';

describe('countTextUnits', () => {
  it('按非空白 Unicode 字符统计中文正文', () => {
    expect(countTextUnits('你好，世界')).toBe(5);
    expect(countTextUnits('  你好\n世界  ')).toBe(4);
  });

  it('忽略组合标记，重音字母只计一个基础字符', () => {
    expect(countTextUnits('e\u0301')).toBe(1);
  });

  it('忽略零宽连接符，不把连接序列拆成额外字', () => {
    expect(countTextUnits('A\u200dB')).toBe(2);
  });

  it('空文本与纯空白返回 0', () => {
    expect(countTextUnits('')).toBe(0);
    expect(countTextUnits(' \t\n\r')).toBe(0);
  });

  it('英文空格不计入，字母与标点正常计数', () => {
    expect(countTextUnits('hello world')).toBe(10);
    expect(countTextUnits('hello, world!')).toBe(12);
  });
});
