export interface RunAfterSaveOptions<T> {
  isDirty: boolean;
  save: () => Promise<void>;
  action: () => Promise<T> | T;
}

/**
 * 所有离开当前章节的动作都从这里串行执行，保存失败时不会触发后续导航。
 */
export async function runAfterSave<T>({
  isDirty,
  save,
  action,
}: RunAfterSaveOptions<T>): Promise<T> {
  if (isDirty) await save();
  return action();
}
