import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import { MissionDetail } from './MissionDetail';
import { overviewFixture } from './overview-fixture';

const mission = {
  id: 'planned-study',
  goal: 'Study supplied stacks and queues',
  role_id: 'student',
  status: 'PENDING',
  version: 1,
  planning: {
    contract_version: 1,
    planner_id: 'registered_student_planner',
    rationale: 'Refine notes to match the learning goal',
    constraints: ['Use supplied material only'],
    objectives: { draft: 'Compare removal order', final: 'Practice supplied concepts' },
  },
  tasks: [
    {
      id: 'draft',
      title: 'Refine learning notes',
      agent_id: 'alternate_notes',
      status: 'READY',
      attempts: 0,
      dependencies: [],
      input_bindings: {},
      outputs: null,
      error: null,
    },
    {
      id: 'final',
      title: 'Study quiz',
      agent_id: 'alternate_quiz',
      status: 'PENDING',
      attempts: 0,
      dependencies: ['draft'],
      input_bindings: { notes: { task_id: 'draft', output_key: 'notes' } },
      outputs: null,
      error: null,
    },
  ],
};

test('Student planning errors retain the goal; successful creation opens the plan without running it', async () => {
  let reject = true;
  let created = false;
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const respond = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
    if (path === '/status')
      return respond({
        execution_mode: 'live',
        user_role: 'operator',
        workflows: [
          {
            role_id: 'student',
            name: 'Student',
            ready: true,
            reason: '',
            steps: 'Plan → notes → quiz → review',
            context_notice: 'Injected UI fixture',
            demo_goal: null,
          },
        ],
      });
    if (path === '/overview') return respond(overviewFixture());
    if (path.startsWith('/missions?')) return respond(created ? [mission] : []);
    if (path === '/workflows/student') {
      expect(JSON.parse(options?.body as string)).toEqual({ goal: mission.goal });
      if (reject) return respond({ detail: 'Student plan rejected: invalid graph' }, 422);
      created = true;
      return respond(mission, 201);
    }
    if (path === '/missions/planned-study') return respond(mission);
    if (path.endsWith('/run')) return respond(null);
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<App />);
  await screen.findByLabelText('Workflow');
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  const goal = screen.getByLabelText('What material should your study notes and quiz cover?');
  await user.type(goal, mission.goal);
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  expect(await screen.findByText('Student plan rejected: invalid graph')).toBeVisible();
  expect(goal).toHaveValue(mission.goal);
  reject = false;
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  await user.click(await screen.findByText('Inspect validated Student plan'));
  expect(screen.getByText('Use supplied material only')).toBeVisible();
  expect(screen.getByRole('button', { name: 'Run mission' })).toBeEnabled();
  expect(
    fetchMock.mock.calls.every(
      ([path, options]) => !(path.endsWith('/run') && options?.method === 'POST'),
    ),
  ).toBe(true);
});

test.each([true, false])(
  'Student plan and alternate Focus review remain inspectable (writer=%s)',
  async (canWrite) => {
    const fetchMock = vi.fn(async (path: string) => {
      const respond = (data: unknown) => new Response(JSON.stringify(data));
      if (path === '/missions/planned-study')
        return respond({
          ...mission,
          status: 'WAITING_APPROVAL',
          version: 9,
          tasks: [
            { ...mission.tasks[0], status: 'COMPLETED', outputs: { notes: 'Notes' } },
            { ...mission.tasks[1], id: 'quiz', status: 'COMPLETED' },
            {
              id: 'final',
              title: 'Bounded Focus effort',
              agent_id: 'alternate_focus',
              status: 'WAITING_APPROVAL',
              attempts: 1,
              dependencies: ['draft', 'quiz'],
              input_bindings: {
                notes: { task_id: 'draft', output_key: 'notes' },
                questions: { task_id: 'quiz', output_key: 'questions' },
              },
              outputs: { summary: 'Review and practice' },
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
            payload: { artifact_refs: ['study-artifact'] },
          },
        ]);
      if (path.includes('/artifacts?'))
        return respond([
          {
            id: 'study-artifact',
            name: 'study-plan.md',
            task_id: 'final',
            size: 30,
            sha256: 'a'.repeat(64),
          },
        ]);
      if (path.endsWith('/content'))
        return new Response('<script>untrusted study content</script>');
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MissionDetail id="planned-study" canWrite={canWrite} onChange={async () => {}} />);
    await userEvent.click(await screen.findByText('Inspect validated Student plan'));
    expect(screen.getByText('Use supplied material only')).toBeVisible();
    expect(screen.getByText('registered_student_planner')).toBeVisible();
    expect(
      screen.getByText(
        /Inspect the study plan, original time settings, quiz, answer key, and reviewed notes/,
      ),
    ).toBeVisible();
    expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    const accept = screen.getByRole('button', { name: 'Accept result' });
    if (canWrite) expect(accept).toBeEnabled();
    else expect(accept).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
    expect(await screen.findByText('<script>untrusted study content</script>')).toBeVisible();
    expect(screen.getByRole('link', { name: 'Download study-plan.md' })).toHaveAttribute(
      'href',
      '/artifacts/study-artifact/content',
    );
  },
);
