import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { charactersApi } from '@/lib/characters';
import type {
  CharacterNetworkResponse,
  CharacterResponse,
  CharacterRelationshipResponse,
  MCPCharacterResponse,
} from '@/lib/api/generated/model';
import CharacterRelationshipEditor from './CharacterRelationshipEditor';

const roster: CharacterResponse[] = [
  { id: 5, novel_id: 1, name: '林昭', created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00' },
  { id: 6, novel_id: 1, name: '沈孤鸿', created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00' },
];
const bond: CharacterRelationshipResponse = {
  id: 9, novel_id: 1,
  character_a_id: 5, character_a_name: '林昭',
  character_b_id: 6, character_b_name: '沈孤鸿',
  relationship_type: '师徒', strength: 7, description: '林昭少年时拜入沈孤鸿门下。',
  established_in_chapter: 3, development_stage: '初识',
  created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00',
};
const network: CharacterNetworkResponse = { novel_id: 1, characters: roster, relationships: [bond] };

beforeEach(() => { vi.spyOn(charactersApi, 'network').mockResolvedValue(network); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('人物关系区', () => {
  it('渲染关系图与关系卡：卡有编辑、无删除（无删除端点，诚实处理）', async () => {
    render(<CharacterRelationshipEditor novelId={1} />);
    await screen.findByText('林昭 —— 师徒 —— 沈孤鸿');
    expect(screen.getByRole('img', { name: '人物关系图：2 个人物，1 段关系' })).toBeTruthy();
    expect(screen.getByText('强度 7/10 · 第 3 章确立')).toBeTruthy();
    expect(screen.getByRole('button', { name: '编辑林昭与沈孤鸿的关系' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /删除/ })).toBeNull();
  });

  it('零人物诚实空态，不渲染建关系表单', async () => {
    vi.mocked(charactersApi.network).mockResolvedValue({ novel_id: 1, characters: [], relationships: [] });
    render(<CharacterRelationshipEditor novelId={1} />);
    await screen.findByText('还没有人物关系。');
    expect(screen.queryByLabelText('人物一')).toBeNull();
  });

  it('三步建关系：人物一 → 人物二 → 关系类型，保存后刷新网络', async () => {
    const createRelationship = vi.spyOn(charactersApi, 'createRelationship').mockResolvedValue(bond);
    render(<CharacterRelationshipEditor novelId={1} />);
    await screen.findByText('林昭 —— 师徒 —— 沈孤鸿');
    fireEvent.mouseDown(screen.getByLabelText('人物一'));
    fireEvent.click(await screen.findByRole('option', { name: '林昭' }));
    fireEvent.mouseDown(screen.getByLabelText('人物二'));
    fireEvent.click(await screen.findByRole('option', { name: '沈孤鸿' }));
    fireEvent.change(screen.getByLabelText(/^关系类型/), { target: { value: '宿敌' } });
    fireEvent.click(screen.getByRole('button', { name: '建立关系' }));
    await waitFor(() => expect(createRelationship).toHaveBeenCalledWith({
      novel_id: 1, character_a_id: 5, character_b_id: 6, relationship_type: '宿敌',
      strength: 5, description: null, established_in_chapter: null,
    }));
    await waitFor(() => expect(charactersApi.network).toHaveBeenCalledTimes(2));
  });

  it('人物一与人物二相同禁用建立', async () => {
    render(<CharacterRelationshipEditor novelId={1} />);
    await screen.findByText('林昭 —— 师徒 —— 沈孤鸿');
    fireEvent.mouseDown(screen.getByLabelText('人物一'));
    fireEvent.click(await screen.findByRole('option', { name: '林昭' }));
    fireEvent.mouseDown(screen.getByLabelText('人物二'));
    fireEvent.click(await screen.findByRole('option', { name: '林昭' }));
    expect((screen.getByRole('button', { name: '建立关系' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('编辑关系经 MCP 全量提交四字段，development_stage 原样透传防清空', async () => {
    const response: MCPCharacterResponse = {
      action: 'update_relationship', message: '角色关系更新成功', success: true, timestamp: '2026-10-02T00:00:00',
    };
    const execute = vi.spyOn(charactersApi, 'executeMcpAction').mockResolvedValue(response);
    render(<CharacterRelationshipEditor novelId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: '编辑林昭与沈孤鸿的关系' }));
    await screen.findByRole('dialog');
    expect(screen.getByDisplayValue('师徒')).toBeTruthy();
    expect(screen.getByDisplayValue('林昭少年时拜入沈孤鸿门下。')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(execute).toHaveBeenCalledWith({
      action: 'update_relationship',
      parameters: {
        relationship_id: 9, relationship_type: '师徒', strength: 7,
        description: '林昭少年时拜入沈孤鸿门下。', development_stage: '初识',
      },
    }));
    await waitFor(() => expect(charactersApi.network).toHaveBeenCalledTimes(2));
  });

  it('MCP 返回 success=false 诚实展示原因，不关窗', async () => {
    const response: MCPCharacterResponse = {
      action: 'update_relationship', message: '角色关系不存在', success: false, timestamp: '2026-10-02T00:00:00',
    };
    vi.spyOn(charactersApi, 'executeMcpAction').mockResolvedValue(response);
    render(<CharacterRelationshipEditor novelId={1} />);
    fireEvent.click(await screen.findByRole('button', { name: '编辑林昭与沈孤鸿的关系' }));
    fireEvent.click(await screen.findByRole('button', { name: '保存' }));
    expect(await screen.findByText('角色关系不存在')).toBeTruthy();
    expect(screen.getByRole('dialog')).toBeTruthy();
  });
});
