import { describe, expect, it, vi } from 'vitest';
import { runAfterSave } from './workspaceNavigation';

describe('runAfterSave', () => {
  it('脏稿保存成功后才执行导航', async () => {
    const order: string[] = [];
    const save = vi.fn(async () => {
      order.push('save');
    });
    const action = vi.fn(() => {
      order.push('navigate');
      return 42;
    });

    await expect(runAfterSave({ isDirty: true, save, action })).resolves.toBe(42);
    expect(order).toEqual(['save', 'navigate']);
  });

  it('保存失败时不执行导航', async () => {
    const error = new Error('版本冲突');
    const action = vi.fn();

    await expect(
      runAfterSave({
        isDirty: true,
        save: async () => {
          throw error;
        },
        action,
      }),
    ).rejects.toBe(error);
    expect(action).not.toHaveBeenCalled();
  });

  it('无脏稿时直接执行动作', async () => {
    const save = vi.fn();
    const action = vi.fn(() => 'ok');

    await expect(runAfterSave({ isDirty: false, save, action })).resolves.toBe('ok');
    expect(save).not.toHaveBeenCalled();
  });
});
