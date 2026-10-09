import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MissionDetail } from './MissionDetail';
import { App } from './App';
import { overviewFixture } from './overview-fixture';

test('Creator creation shows planning errors and then opens the validated plan', async () => {
  const goal = 'Explain local history for new students';
  let reject = true;
  let created = false;
  const mission = {
    id: 'created-content',
    goal,
    role_id: 'creator',
    status: 'PENDING',
    version: 1,
    created_at: '2026-10-09T00:00:00Z',
    updated_at: '2026-10-09T00:00:00Z',
    planning: {
      contract_version: 1,
      planner_id: 'registered_planner',
      rationale: 'Use a student-friendly outline',
      constraints: ['Use only supplied facts'],
      objectives: { draft: 'Explain local history' },
    },
    tasks: [
      {
        id: 'draft',
        title: 'Student-friendly outline',
        agent_id: 'alternate_outline',
        status: 'READY',
        attempts: 0,
        dependencies: [],
        input_bindings: {},
        outputs: null,
        error: null,
      },
    ],
  };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const respond = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
    if (path === '/status')
      return respond({
        execution_mode: 'live',
        user_role: 'operator',
        workflows: [
          {
            role_id: 'creator',
            name: 'Creator',
            ready: true,
            reason: '',
            steps: 'Plan → outline → script → review',
            context_notice: 'Injected UI fixture',
            demo_goal: null,
          },
        ],
      });
    if (path === '/overview') return respond(overviewFixture());
    if (path.startsWith('/missions?')) return respond(created ? [mission] : []);
    if (path === '/workflows/creator') {
      expect(JSON.parse(options?.body as string)).toEqual({ goal });
      if (reject) return respond({ detail: 'Creator plan rejected: invalid graph' }, 422);
      created = true;
      return respond(mission, 201);
    }
    if (path === '/missions/created-content') return respond(mission);
    if (path.endsWith('/run')) return respond(null);
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByLabelText('Workflow');
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  await user.type(screen.getByLabelText('What should your video script cover?'), goal);
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  expect(await screen.findByText('Creator plan rejected: invalid graph')).toBeVisible();
  expect(screen.getByLabelText('What should your video script cover?')).toHaveValue(goal);
  reject = false;
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  const summary = await screen.findByText('Inspect validated Creator plan');
  await user.click(summary);
  expect(screen.getByText('Use only supplied facts')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Run mission' })).toBeEnabled();
  expect(
    fetchMock.mock.calls.every(
      ([path, options]) => !(path.endsWith('/run') && options?.method === 'POST'),
    ),
  ).toBe(true);
});

test.each([true, false])(
  'Creator plan and current evidence retain content review (writer=%s)',
  async (canWrite) => {
    const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
      const respond = (data: unknown) => new Response(JSON.stringify(data));
      if (path === '/missions/planned-content')
        return respond({
          id: 'planned-content',
          goal: 'Explain supplied research for students',
          role_id: 'creator',
          status: 'WAITING_APPROVAL',
          version: 9,
          planning: {
            contract_version: 1,
            planner_id: 'registered_planner',
            rationale: 'Refine the audience-specific outline before script',
            constraints: ['Preserve evidence limitations'],
            objectives: { draft: 'Explain for students', final: 'Review the complete script' },
          },
          tasks: [
            {
              id: 'draft',
              title: 'Refined outline',
              agent_id: 'alternate_outline',
              status: 'COMPLETED',
              attempts: 1,
              dependencies: [],
              outputs: { outline: 'Outline' },
              error: null,
            },
            {
              id: 'final',
              title: 'Final script',
              agent_id: 'alternate_script',
              status: 'WAITING_APPROVAL',
              attempts: 1,
              dependencies: ['draft'],
              input_bindings: {
                outline: { task_id: 'draft', output_key: 'outline' },
                evidence: { task_id: 'source', output_key: 'evidence' },
              },
              outputs: { script: 'Script' },
              error: null,
            },
          ],
        });
      if (path.endsWith('/approvals'))
        return respond([
          {
            id: 'review',
            task_id: 'final',
            status: 'PENDING',
            payload_digest: 'bound',
            payload: { artifact_refs: ['script'] },
          },
        ]);
      if (path.includes('/artifacts?'))
        return respond([
          { id: 'script', name: 'script.md', task_id: 'final', size: 20, sha256: 'a'.repeat(64) },
        ]);
      if (path.endsWith('/content')) return new Response('<script>untrusted content</script>');
      if (path.endsWith('/run')) return respond(null);
      if (options?.method === 'POST') return respond({});
      return respond([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MissionDetail id="planned-content" canWrite={canWrite} onChange={async () => {}} />);
    const summary = await screen.findByText('Inspect validated Creator plan');
    await userEvent.click(summary);
    expect(screen.getByText('Preserve evidence limitations')).toBeVisible();
    expect(screen.getByText('Refine the audience-specific outline before script')).toBeVisible();
    expect(screen.getByText('registered_planner')).toBeVisible();
    expect(
      screen.getByText(/Inspect the script, reviewed outline, research, and supplied sources/),
    ).toBeVisible();
    expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    const accept = screen.getByRole('button', { name: 'Accept result' });
    if (canWrite) expect(accept).toBeEnabled();
    else expect(accept).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
    expect(await screen.findByText('<script>untrusted content</script>')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Download script.md' })).toHaveAttribute(
      'href',
      '/artifacts/script/content',
    );
    expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  },
);
