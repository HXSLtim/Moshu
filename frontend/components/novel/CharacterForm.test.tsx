import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { charactersApi } from '@/lib/characters';
import type { CharacterResponse } from '@/lib/api/generated/model';
import CharacterForm from './CharacterForm';

const person: CharacterResponse = {
  id: 5, novel_id: 1, name: '林昭', occupation: '游侠', importance_level: 'main',
  created_at: '2026-10-02T00:00:00', updated_at: '2026-10-02T00:00:00',
};

const makeProps = () => ({ novelId: 1, open: true, onClose: vi.fn(), onSaved: vi.fn() });
afterEach(cleanup);

describe('人物表单弹窗', () => {
  it('新增：填名字、身份与重要程度后按创建载荷提交并关窗', async () => {
    const create = vi.spyOn(charactersApi, 'create').mockResolvedValue(person);
    const props = makeProps();
    render(<CharacterForm {...props} />);
    fireEvent.change(screen.getByLabelText(/^名字/), { target: { value: '沈孤鸿' } });
    fireEvent.change(screen.getByLabelText('身份'), { target: { value: '国师' } });
    fireEvent.mouseDown(screen.getByLabelText('重要程度'));
    fireEvent.click(await screen.findByRole('option', { name: '主力' }));
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({
      novel_id: 1, name: '沈孤鸿', occupation: '国师', importance_level: 'main',
    }));
    await waitFor(() => expect(props.onClose).toHaveBeenCalled());
    await waitFor(() => expect(props.onSaved).toHaveBeenCalled());
  });

  it('名字为空时创建按钮禁用', () => {
    render(<CharacterForm {...makeProps()} />);
    expect((screen.getByRole('button', { name: '创建' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('编辑：回显当前值，重要程度选「未设定」时显式传 null 清除', async () => {
    const update = vi.spyOn(charactersApi, 'update').mockResolvedValue(person);
    render(<CharacterForm {...makeProps()} character={person} />);
    expect(screen.getByDisplayValue('林昭')).toBeTruthy();
    expect(screen.getByDisplayValue('游侠')).toBeTruthy();
    fireEvent.mouseDown(screen.getByLabelText('重要程度'));
    fireEvent.click(await screen.findByRole('option', { name: '未设定' }));
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    await waitFor(() => expect(update).toHaveBeenCalledWith(5, {
      name: '林昭', occupation: '游侠', importance_level: null,
    }));
  });

  it('保存失败诚实展示原因，不关窗不假装成功', async () => {
    vi.spyOn(charactersApi, 'create').mockRejectedValue(new Error('角色名称 "沈孤鸿" 已存在'));
    const props = makeProps();
    render(<CharacterForm {...props} />);
    fireEvent.change(screen.getByLabelText(/^名字/), { target: { value: '沈孤鸿' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    expect(await screen.findByText('角色名称 "沈孤鸿" 已存在')).toBeTruthy();
    expect(props.onClose).not.toHaveBeenCalled();
  });
});
