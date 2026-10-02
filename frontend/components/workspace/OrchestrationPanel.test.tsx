import { describe, expect, it, vi, beforeEach } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach } from 'vitest';
import OrchestrationPanel from '@/components/workspace/OrchestrationPanel';

const { createMock } = vi.hoisted(() => ({ createMock: vi.fn() }));

vi.mock('@/lib/generationJobs', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/generationJobs')>();
  return {
    ...actual,
    generationJobsApi: {
      ...actual.generationJobsApi,
      list: vi.fn(async () => []),
      get: vi.fn(async () => ({ id: 'job-1', status: 'completed' })),
      create: createMock,
    },
  };
});

vi.mock('@/components/workspace/WritingProposalActions', () => ({
  default: (props: { proposalId: string }) => (
    <div data-testid="proposal-actions">proposal:{props.proposalId}</div>
  ),
}));

const RESULT = {
  proposal_id: 'prop-1',
  content: '夜风掠过檐角。',
  length: 7,
  plan: {
    steps: [
      { id: 1, kind: 'retrieve', instruction: '林夏 武器', depends_on: [] },
      { id: 2, kind: 'generate', instruction: '写夜战段落', depends_on: [1] },
    ],
  },
  uncertainties: ['林夏的剑术来源未在账本中确认'],
  consistency: { has_conflict: false, violations: [] },
  context_manifest: {},
  execution: null,
};

function renderPanel() {
  return render(
    <OrchestrationPanel
      novelId={1}
      novelLifecycleId={'a'.repeat(32)}
      chapterId={3}
      chapterLifecycleId={'c'.repeat(32)}
      chapterVersion={2}
      currentContent="第一章结尾。"
    />,
  );
}

describe('OrchestrationPanel', () => {
  afterEach(cleanup);

  beforeEach(() => {
    createMock.mockReset();
    createMock.mockResolvedValue({ id: 'job-1', status: 'completed', result: RESULT });
  });

  it('提交编排任务并渲染计划、不确定点与候选提案', async () => {
    renderPanel();
    const submitButton = await screen.findByRole('button', { name: /提交编排/ });
    fireEvent.change(screen.getByLabelText(/复合创作指令/), {
      target: { value: '先查旧怨再写夜战' },
    });
    await waitFor(() => expect(submitButton.hasAttribute('disabled')).toBe(false));
    fireEvent.click(submitButton);

    await waitFor(() => expect(createMock).toHaveBeenCalledTimes(1));
    const submitted = createMock.mock.calls[0][0];
    expect(submitted.kind).toBe('orchestrate');
    expect(submitted.payload.instruction).toBe('先查旧怨再写夜战');
    expect(submitted.payload.expected_novel_lifecycle_id).toBe('a'.repeat(32));

    expect(await screen.findByText(/执行计划/)).toBeTruthy();
    expect(screen.getByText('检索 1')).toBeTruthy();
    expect(screen.getByText(/林夏的剑术来源未在账本中确认/)).toBeTruthy();
    expect(screen.getByText(/未发现与既有设定的冲突/)).toBeTruthy();
    expect(screen.getByTestId('proposal-actions').textContent).toBe('proposal:prop-1');
  });

  it('无指令或无生命周期时不能提交', () => {
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /提交编排/ }));
    expect(createMock).not.toHaveBeenCalled();
  });
});
