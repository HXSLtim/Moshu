import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './api';
import { generationJobsApi } from './generationJobs';

const queued = { id: 'job-1', request_id: 'request-1', novel_id: 1, novel_lifecycle_id: 'n1', chapter_id: 2, kind: 'chat', status: 'queued', result: null, message: '已排队的问题', mode: 'discuss', chapter_title: '第一章', error: null, created_at: '2026-09-08', finished_at: null };
const turn = { id: 7, request_id: 'request-1', novel_id: 1, chapter_id: 2, chapter_title: '第一章', mode: 'discuss', user_text: queued.message, assistant_text: '已完成的回答', base_content_hash: '', status: 'completed', error: null, created_at: queued.created_at };
const data = { request_id: 'request-1', chapter_id: 2, mode: 'discuss' as const, message: queued.message, current_content: '当前未保存正文', expected_novel_lifecycle_id: 'n1', expected_chapter_lifecycle_id: 'c1' };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); localStorage.clear(); });

describe('持久生成 API 契约', () => {
  it('提交任务后通过查询获得对话结果，身份与同一request_id贯穿请求', async () => {
    vi.useFakeTimers(); localStorage.setItem('token', 'author-token');
    const fetcher = vi.fn().mockResolvedValueOnce(response(queued, 202)).mockResolvedValueOnce(response({ ...queued, status: 'completed', result: turn }));
    vi.stubGlobal('fetch', fetcher);
    const pending = api.sendWritingTurn(1, data);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await pending).toMatchObject({ ...turn, job_id: 'job-1', job_status: 'completed' });
    expect(fetcher.mock.calls[0][0]).toContain('/generation/jobs');
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ request_id: 'request-1', kind: 'chat', novel_id: 1, expected_novel_lifecycle_id: 'n1', payload: data });
    expect(fetcher.mock.calls[0][1].headers.Authorization).toBe('Bearer author-token');
    expect(fetcher.mock.calls[1][0]).toContain('/generation/jobs/job-1?novel_id=1');
  });
  it('尚未建立对话轮次的真实排队任务在刷新后仍保留问题与任务身份', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response([])).mockResolvedValueOnce(response([queued])));
    const history = await api.listWritingTurns(1);
    expect(history).toEqual([expect.objectContaining({ id: 0, job_id: 'job-1', user_text: queued.message, chapter_title: '第一章', mode: 'discuss', status: 'pending' })]);
  });
  it('同一任务与对话轮次合并不重复，较早对话分页只读取历史接口', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response([turn])).mockResolvedValueOnce(response([{ ...queued, status: 'completed', result: turn }])).mockResolvedValueOnce(response([]));
    vi.stubGlobal('fetch', fetcher);
    expect(await api.listWritingTurns(1)).toHaveLength(1);
    await api.listWritingTurns(1, 7);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(fetcher.mock.calls[2][0]).toContain('turns?limit=30&before=7');
  });
  it('作者停止排队任务调用服务端取消，保留未建轮次的问题', async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(response([queued])).mockResolvedValueOnce(response({ ...queued, status: 'cancelled', error: '作者已停止' }));
    vi.stubGlobal('fetch', fetcher);
    expect(await api.stopWritingTurn(1, 'request-1')).toMatchObject({ id: 0, job_id: 'job-1', status: 'cancelled', user_text: queued.message, error: '作者已停止' });
    expect(fetcher.mock.calls[1][0]).toContain('/jobs/job-1/stop?novel_id=1');
    expect(fetcher.mock.calls[1][1].method).toBe('POST');
  });
  it('切页面中断等待不会隐式取消持久任务', async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValue(response(queued, 202));
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    const result = api.sendWritingTurn(1, data, { signal: controller.signal });
    const assertion = expect(result).rejects.toMatchObject({ name: 'AbortError' });
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await assertion;
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('按作品、章节和能力恢复记录，不扫描其他章任务', async () => {
    const fetcher = vi.fn().mockResolvedValue(response([])); vi.stubGlobal('fetch', fetcher);
    await generationJobsApi.list(1, 'rewrite', undefined, 2);
    expect(fetcher.mock.calls[0][0]).toContain('/jobs?novel_id=1&limit=30&kind=rewrite&chapter_id=2');
  });
});
