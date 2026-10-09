import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MissionDetail } from './MissionDetail';

test.each([
  { baselinePassed: false, patchedPassed: true, canWrite: true },
  { baselinePassed: true, patchedPassed: false, canWrite: true },
  { baselinePassed: true, patchedPassed: undefined, canWrite: true },
  { baselinePassed: false, patchedPassed: true, canWrite: false },
])(
  'baseline and patched outcomes remain separate (%j)',
  async ({ baselinePassed, patchedPassed, canWrite }) => {
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    const fetchMock = vi.fn(async (path: string, _options?: RequestInit) => {
      if (path === '/missions/baseline')
        return respond({
          id: 'baseline',
          goal: 'Fix addition',
          role_id: 'developer',
          status: 'WAITING_APPROVAL',
          version: 9,
          tasks: [
            {
              id: 'baseline',
              title: 'Record baseline',
              agent_id: 'baseline_testing',
              status: 'COMPLETED',
              attempts: 1,
              dependencies: [],
              outputs: { baseline_passed: baselinePassed },
              error: null,
            },
            {
              id: 'verify',
              title: 'Verify patch',
              agent_id: 'testing',
              status: 'WAITING_APPROVAL',
              attempts: 1,
              dependencies: ['baseline'],
              outputs: patchedPassed === undefined ? {} : { passed: patchedPassed },
              requires_passed_tests: true,
              error: null,
            },
          ],
          planning: {
            contract_version: 2,
            planner_id: 'developer_planner',
            rationale: 'Record baseline before patch',
            constraints: [],
            objectives: { baseline: 'Test unpatched source', verify: 'Review patched tests' },
          },
        });
      if (path.endsWith('/approvals'))
        return respond([
          { id: 'review', task_id: 'verify', status: 'PENDING', payload_digest: 'digest' },
        ]);
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MissionDetail id="baseline" canWrite={canWrite} onChange={async () => {}} />);
    expect(
      await screen.findByText(baselinePassed ? 'Baseline tests passed' : 'Baseline tests failed'),
    ).toBeVisible();
    if (patchedPassed === undefined) {
      expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
      expect(screen.queryByText('Tests failed')).not.toBeInTheDocument();
    } else expect(screen.getByText(patchedPassed ? 'Tests passed' : 'Tests failed')).toBeVisible();
    const accept = screen.getByRole('button', { name: 'Accept result' });
    if (canWrite && patchedPassed === true) expect(accept).toBeEnabled();
    else expect(accept).toBeDisabled();
    expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  },
);

test('a canceled artifact body cannot replace the currently selected preview', async () => {
  let finishOldBody!: (content: string) => void;
  let oldSignal: AbortSignal | undefined;
  const oldBody = new Promise<string>((resolve) => {
    finishOldBody = resolve;
  });
  const artifacts = ['old', 'current'].map((id) => ({
    id,
    name: `${id}.md`,
    task_id: 'write',
    sha256: (id === 'old' ? 'a' : 'b').repeat(64),
    size: 20,
  }));
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    if (path === '/missions/mission')
      return respond({
        id: 'mission',
        goal: 'Review the content',
        role_id: 'creator',
        status: 'COMPLETED',
        version: 3,
        tasks: [],
      });
    if (path.includes('/artifacts?')) return respond(artifacts);
    if (path.endsWith('/run')) return respond(null);
    if (path === '/artifacts/old/content') {
      oldSignal = options?.signal as AbortSignal;
      return { ok: true, text: () => oldBody } as Response;
    }
    if (path === '/artifacts/current/content') return new Response('Current reviewed text');
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<MissionDetail id="mission" canWrite={false} onChange={async () => {}} />);
  await user.click(await screen.findByRole('tab', { name: /artifacts/ }));
  await waitFor(() => expect(oldSignal).toBeDefined());
  await user.selectOptions(screen.getByLabelText('Result artifact'), 'current');
  expect(await screen.findByText('Current reviewed text')).toBeInTheDocument();
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => finishOldBody('Obsolete artifact text'));
  expect(screen.queryByText('Obsolete artifact text')).not.toBeInTheDocument();
  expect(screen.getByText('Current reviewed text')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Download current.md' })).toHaveAttribute(
    'href',
    '/artifacts/current/content',
  );
  expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
});

test.each([true, false, undefined])(
  'planned review requires explicit passing tests (%s) and keeps denial available',
  async (passed) => {
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/missions/planned' || options?.method === 'POST')
        return respond({
          id: 'planned',
          goal: 'Fix addition while preserving tests',
          role_id: 'developer',
          status: 'WAITING_APPROVAL',
          version: 7,
          tasks: [
            {
              id: 'verify',
              title: 'Verify fix',
              agent_id: 'registered_tester',
              status: 'WAITING_APPROVAL',
              attempts: 1,
              dependencies: [],
              outputs: passed === undefined ? {} : { passed },
              error: null,
              requires_passed_tests: true,
            },
          ],
          planning: {
            planner_id: 'registered_planner',
            rationale: 'Investigate the operator and verify the fix',
            constraints: ['Preserve tests'],
            objectives: { verify: 'Run configured tests' },
          },
        });
      if (path.endsWith('/approvals'))
        return respond([
          {
            id: 'review',
            task_id: 'verify',
            status: 'PENDING',
            payload_digest: 'digest',
          },
        ]);
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MissionDetail id="planned" canWrite onChange={async () => {}} />);
    await user.click(await screen.findByText('Inspect validated Developer plan'));
    expect(screen.getByText('Investigate the operator and verify the fix')).toBeVisible();
    const accept = screen.getByRole('button', { name: 'Accept result' });
    if (passed === true) expect(accept).toBeEnabled();
    else {
      expect(accept).toBeDisabled();
      expect(screen.getByText(/Tests must explicitly pass before/)).toBeVisible();
      expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    }
    await user.click(screen.getByRole('button', { name: 'Deny result' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/approvals/review/decision',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"decision":"deny"'),
        }),
      ),
    );
  },
);

test('Viewer can inspect goal constraints and task evidence without executing work', async () => {
  const constraint = 'Preserve <script>test assertions</script>';
  const objective = 'Fix <b>addition</b> without weakening tests';
  const tasks = [
    {
      id: 'inspect_source',
      title: 'Inspect source',
      agent_id: 'source_reader',
      dependencies: [],
      input_bindings: {},
    },
    {
      id: 'inspect_tests',
      title: 'Inspect tests',
      agent_id: 'test_reader',
      dependencies: [],
      input_bindings: {},
    },
    {
      id: 'fix',
      title: 'Generate patch',
      agent_id: 'scoped_patch_agent',
      dependencies: ['inspect_source', 'inspect_tests'],
      input_bindings: {
        findings: { task_id: 'inspect_source', output_key: 'findings' },
        context: { task_id: 'inspect_tests', output_key: 'findings' },
      },
    },
    {
      id: 'verify',
      title: 'Test patch',
      agent_id: 'configured_tester',
      dependencies: ['fix'],
      input_bindings: { diff: { task_id: 'fix', output_key: 'diff' } },
      requires_passed_tests: true,
    },
  ].map((task) => ({ ...task, status: 'PENDING', attempts: 0, outputs: null, error: null }));
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method && options.method !== 'GET')
      throw new Error('Inspection must be read-only');
    if (path === '/missions/planned')
      return new Response(
        JSON.stringify({
          id: 'planned',
          goal: 'Fix addition',
          role_id: 'developer',
          status: 'PENDING',
          version: 1,
          tasks,
          planning: {
            planner_id: 'registered_planner',
            rationale: 'Gather independent source and test evidence',
            constraints: [constraint],
            objectives: { fix: objective },
          },
        }),
      );
    return new Response(JSON.stringify(path.endsWith('/run') ? null : []));
  });
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<MissionDetail id="planned" canWrite={false} onChange={async () => {}} />);
  await user.click(await screen.findByText('Inspect validated Developer plan'));
  expect(screen.getByText(constraint)).toBeVisible();
  expect(screen.getByText('registered_planner')).toBeVisible();
  const patch = screen.getByRole('article', { name: 'Task detail: Generate patch (fix)' });
  expect(patch).toHaveTextContent(objective);
  expect(within(patch).getByText('scoped_patch_agent')).toBeVisible();
  await user.click(within(patch).getByText('Inspect dependency inputs'));
  expect(patch).toHaveTextContent(
    'findings receives findings from Inspect source (inspect_source)',
  );
  expect(patch).toHaveTextContent('context receives findings from Inspect tests (inspect_tests)');
  await user.click(within(patch).getByRole('button', { name: 'Inspect tests (inspect_tests)' }));
  expect(
    screen.getByRole('article', { name: 'Task detail: Inspect tests (inspect_tests)' }),
  ).toHaveFocus();
  expect(screen.getByText('Human review requires an explicit passing test outcome.')).toBeVisible();
  expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Run mission' })).toBeDisabled();
  expect(document.querySelector('.task-plan-evidence b')).toBeNull();
  expect(document.querySelector('.mission-plan script')).toBeNull();
  expect(
    fetchMock.mock.calls.every(([, options]) => !options?.method || options.method === 'GET'),
  ).toBe(true);
});

test('an older mission retains task inspection without invented planning evidence', async () => {
  const fetchMock = vi.fn(
    async (path: string) =>
      new Response(
        JSON.stringify(
          path === '/missions/legacy'
            ? {
                id: 'legacy',
                goal: 'Older mission',
                role_id: 'developer',
                status: 'COMPLETED',
                version: 3,
                tasks: [
                  {
                    id: 'fix',
                    title: 'Legacy patch',
                    agent_id: 'code_helper',
                    status: 'COMPLETED',
                    attempts: 1,
                    dependencies: [],
                    outputs: { summary: 'Saved patch' },
                    error: null,
                  },
                ],
              }
            : path.endsWith('/run')
              ? null
              : [],
        ),
      ),
  );
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<MissionDetail id="legacy" canWrite={false} onChange={async () => {}} />);
  await user.click(await screen.findByText('Inspect task outputs'));
  expect(screen.getByText(/Saved patch/)).toBeVisible();
  expect(screen.queryByText('Inspect validated Developer plan')).not.toBeInTheDocument();
  expect(screen.queryByText('Inspect dependency inputs')).not.toBeInTheDocument();
  expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
});
