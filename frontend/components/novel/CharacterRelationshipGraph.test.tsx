import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CharacterResponse, CharacterRelationshipResponse } from '@/lib/api/generated/model';
import CharacterRelationshipGraph from './CharacterRelationshipGraph';

const person = (id: number, name: string): CharacterResponse => ({
  id, novel_id: 1, name, created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00',
});
const bond = (id: number, aId: number, bId: number, type: string): CharacterRelationshipResponse => ({
  id, novel_id: 1,
  character_a_id: aId, character_a_name: aId === 5 ? '林昭' : '沈孤鸿',
  character_b_id: bId, character_b_name: bId === 5 ? '林昭' : '沈孤鸿',
  relationship_type: type, created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00',
});

afterEach(cleanup);

describe('手绘 SVG 关系图', () => {
  it('两人一连线：节点名与关系类型标注可见', () => {
    render(<CharacterRelationshipGraph
      characters={[person(5, '林昭'), person(6, '沈孤鸿')]}
      relationships={[bond(9, 5, 6, '师徒')]}
    />);
    const svg = screen.getByRole('img', { name: '人物关系图：2 个人物，1 段关系' });
    expect(svg.textContent).toContain('林昭');
    expect(svg.textContent).toContain('沈孤鸿');
    expect(svg.textContent).toContain('师徒');
    expect(svg.querySelectorAll('line')).toHaveLength(1);
  });

  it('自环（a=b）不连线，只保留人物节点', () => {
    render(<CharacterRelationshipGraph
      characters={[person(5, '林昭')]}
      relationships={[bond(9, 5, 5, '心魔')]}
    />);
    const svg = screen.getByRole('img', { name: '人物关系图：1 个人物，1 段关系' });
    expect(svg.querySelectorAll('line')).toHaveLength(0);
    expect(svg.textContent).toContain('林昭');
  });

  it('零人物不渲染图形', () => {
    const { container } = render(<CharacterRelationshipGraph characters={[]} relationships={[]} />);
    expect(container.querySelector('svg')).toBeNull();
  });
});
