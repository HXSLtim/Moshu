'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { generationJobsApi, isGenerationPending, type GenerationJob, type GenerationKind } from '@/lib/generationJobs';

interface Scope { novelId: number; novelLifecycleId?: string; chapterId: number | null; chapterLifecycleId?: string; kind: GenerationKind }
/** 请求中断只停止本页等待；任务继续保存在服务器，作者明确停止才发送取消命令。 */
export function useGenerationTask<T>({ novelId, novelLifecycleId, chapterId, chapterLifecycleId, kind }: Scope) {
  const [job, setJob] = useState<GenerationJob<T> | null>(null);
  const [jobs, setJobs] = useState<GenerationJob<T>[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const scope = `${novelId}:${novelLifecycleId}:${chapterId}:${chapterLifecycleId}:${kind}`;
  const latestScope = useRef(scope); latestScope.current = scope;
  const operations = useRef(new Set<AbortController>());
  const epoch = useRef(0);
  const busy = useRef(false);
  const apply = useCallback((next: GenerationJob<T>) => {
    setJob((previous) => previous?.id === next.id && !isGenerationPending(previous) && isGenerationPending(next) ? previous : next);
    setJobs((previous) => {
      const existing = previous.find((item) => item.id === next.id);
      if (existing && !isGenerationPending(existing) && isGenerationPending(next)) return previous;
      return [next, ...previous.filter((item) => item.id !== next.id)].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 30);
    });
  }, []);
  useEffect(() => {
    const requests = operations.current;
    const sequence = ++epoch.current;
    busy.current = false;
    setJob(null); setJobs([]); setLoading(true); setSubmitting(false); setStopping(false); setError('');
    const controller = new AbortController(); requests.add(controller);
    if (novelLifecycleId) void generationJobsApi.list<T>(novelId, kind, controller.signal, chapterId).then((items) => {
      if (controller.signal.aborted || sequence !== epoch.current) return;
      const history = items.filter((item) => item.novel_lifecycle_id === novelLifecycleId && item.chapter_id === chapterId && (!chapterLifecycleId || item.chapter_lifecycle_id === chapterLifecycleId))
        .sort((a, b) => b.created_at.localeCompare(a.created_at));
      setJobs(history);
      const latest = history.find(isGenerationPending) ?? history[0];
      if (latest) apply(latest);
    }).catch((failure) => { if (!controller.signal.aborted && sequence === epoch.current) setError(failure instanceof Error ? failure.message : '恢复生成任务失败'); })
      .finally(() => { requests.delete(controller); if (!controller.signal.aborted && sequence === epoch.current) setLoading(false); });
    else setLoading(false);
    return () => { epoch.current += 1; requests.forEach((request) => request.abort()); requests.clear(); };
  }, [novelId, novelLifecycleId, chapterId, chapterLifecycleId, kind, apply, refresh]);
  const jobId = job?.id;
  const jobPending = Boolean(job && isGenerationPending(job));
  useEffect(() => {
    if (!jobId || !jobPending) return;
    const requests = operations.current;
    const controller = new AbortController(); requests.add(controller);
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await generationJobsApi.get<T>(novelId, jobId, controller.signal);
        if (controller.signal.aborted || latestScope.current !== scope) return;
        apply(next); setError('');
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '读取生成进度失败，任务仍保存在服务器');
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 2000);
    };
    timer = setTimeout(() => void poll(), 1000);
    return () => { controller.abort(); requests.delete(controller); clearTimeout(timer); };
  }, [jobId, jobPending, novelId, scope, apply]);
  const run = async (payload: object, requestId = crypto.randomUUID()) => {
    if (loading || busy.current || !novelLifecycleId || jobs.some(isGenerationPending)) return;
    busy.current = true; epoch.current += 1;
    const controller = new AbortController(); operations.current.add(controller);
    setSubmitting(true); setError('');
    try {
      const next = await generationJobsApi.create<T>({ request_id: requestId, kind, novel_id: novelId, expected_novel_lifecycle_id: novelLifecycleId, payload }, controller.signal);
      if (!controller.signal.aborted && latestScope.current === scope) apply(next);
    } catch (failure) { if (!controller.signal.aborted && latestScope.current === scope) setError(failure instanceof Error ? failure.message : '提交失败，请刷新任务核对是否已送达'); }
    finally { operations.current.delete(controller); if (!controller.signal.aborted && latestScope.current === scope) { busy.current = false; setSubmitting(false); setLoading(false); } }
  };
  const stop = async () => {
    if (!job || busy.current || !isGenerationPending(job)) return;
    busy.current = true;
    const controller = new AbortController(); operations.current.add(controller); setStopping(true); setError('');
    try {
      const next = await generationJobsApi.stop<T>(novelId, job.id, controller.signal);
      if (!controller.signal.aborted && latestScope.current === scope) apply(next);
    } catch (failure) { if (!controller.signal.aborted && latestScope.current === scope) setError(failure instanceof Error ? failure.message : '取消失败，请刷新后重试'); }
    finally { operations.current.delete(controller); if (!controller.signal.aborted && latestScope.current === scope) { busy.current = false; setStopping(false); } }
  };
  return { job, jobs, select: (id: string) => { const item = jobs.find((entry) => entry.id === id); if (item && !busy.current && !loading && !jobPending) { setJob(item); setError(''); } }, loading, submitting, stopping, error, run, stop, refresh: () => setRefresh((value) => value + 1), pending: submitting || jobPending };
}
