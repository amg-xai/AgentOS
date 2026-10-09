import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import { overviewFixture } from './overview-fixture';
import type { Mission } from './api';

const status = {
  execution_mode: 'live',
  provider_configured: true,
  model: 'mocked-only',
  user_role: 'operator',
  workflows: [
    { role_id: 'student', name: 'Student', ready: true, study_planning_ready: true },
    { role_id: 'creator', name: 'Creator', ready: true },
  ],
};
const goal = 'Prepare stacks and queues';
const mission: Mission = {
  id: 'study-1',
  goal,
  role_id: 'student',
  status: 'WAITING_APPROVAL',
  version: 7,
  created_at: '2026-10-09T00:00:00Z',
  updated_at: '2026-10-09T00:00:00Z',
  tasks: [
    {
      id: 'notes',
      title: 'Notes',
      agent_id: 'student_notes',
      status: 'COMPLETED',
      attempts: 1,
      dependencies: [],
      outputs: { notes: 'Notes' },
      error: null,
    },
    {
      id: 'quiz',
      title: 'Quiz',
      agent_id: 'student_quiz',
      status: 'COMPLETED',
      attempts: 1,
      dependencies: ['notes'],
      outputs: { questions: [] },
      error: null,
    },
    {
      id: 'study_plan',
      title: 'Study plan',
      agent_id: 'student_focus',
      status: 'WAITING_APPROVAL',
      attempts: 1,
      dependencies: ['notes', 'quiz'],
      outputs: { summary: 'Suggested study' },
      error: null,
    },
  ],
};
function setup(
  extra: (path: string, options?: RequestInit) => Response | Promise<Response> | undefined,
  currentStatus = status,
) {
  const respond = (data: unknown) => new Response(JSON.stringify(data));
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      const result = extra(path, options);
      if (result) return result;
      if (path === '/status') return respond(currentStatus);
      if (path === '/overview')
        return respond(overviewFixture(currentStatus.execution_mode === 'demo' ? 'demo' : 'live'));
      return respond([]);
    }),
  );
}

test('Student settings are sent only on opt-in and clear on role and new mission changes', async () => {
  setup((path) =>
    path === '/workflows/student'
      ? new Response(JSON.stringify({ detail: 'Mock submitted' }), { status: 409 })
      : undefined,
  );
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '+ New mission' }));
  await user.type(
    screen.getByLabelText('What material should your study notes and quiz cover?'),
    goal,
  );
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  await screen.findByText('Mock submitted');
  expect(globalThis.fetch).toHaveBeenCalledWith(
    '/workflows/student',
    expect.objectContaining({ body: JSON.stringify({ goal }) }),
  );
  await user.click(screen.getByLabelText('Include a study plan'));
  await user.clear(screen.getByLabelText('Available study minutes'));
  await user.type(screen.getByLabelText('Available study minutes'), '90');
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/workflows/student',
      expect.objectContaining({
        body: JSON.stringify({
          goal,
          study_settings: { total_minutes: 90, max_session_minutes: 25 },
        }),
      }),
    ),
  );
  await user.selectOptions(screen.getByLabelText('Role package'), 'creator');
  expect(screen.queryByLabelText('Include a study plan')).not.toBeInTheDocument();
  await user.selectOptions(screen.getByLabelText('Role package'), 'student');
  expect(screen.getByLabelText('Include a study plan')).not.toBeChecked();
  await user.click(screen.getByLabelText('Include a study plan'));
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  expect(screen.getByLabelText('Include a study plan')).not.toBeChecked();
});

test('obsolete creation from a different role cannot restore its mission or settings', async () => {
  let resolve!: (response: Response) => void;
  setup((path) =>
    path === '/workflows/student'
      ? new Promise<Response>((r) => {
          resolve = r;
        })
      : undefined,
  );
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '+ New mission' }));
  await user.type(
    screen.getByLabelText('What material should your study notes and quiz cover?'),
    goal,
  );
  await user.click(screen.getByLabelText('Include a study plan'));
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  await user.selectOptions(screen.getByLabelText('Workflow'), 'creator');
  await act(async () => resolve(new Response(JSON.stringify(mission))));
  expect(screen.queryByText('STUDENT MISSION')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Role package')).toHaveValue('creator');
  await user.selectOptions(screen.getByLabelText('Role package'), 'student');
  expect(screen.getByLabelText('Include a study plan')).not.toBeChecked();
});

test('server mode changes clear opted-in time settings', async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 5000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  const currentStatus = structuredClone(status);
  setup(() => undefined, currentStatus);
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: '+ New mission' }));
  await user.click(screen.getByLabelText('Include a study plan'));
  await user.clear(screen.getByLabelText('Available study minutes'));
  await user.type(screen.getByLabelText('Available study minutes'), '90');
  currentStatus.execution_mode = 'demo';
  await act(async () => poll());
  await screen.findByText('Offline demo — scripted responses, no model calls');
  expect(screen.queryByLabelText('Include a study plan')).not.toBeInTheDocument();
  currentStatus.execution_mode = 'live';
  await act(async () => poll());
  await waitFor(() =>
    expect(
      screen.queryByText('Offline demo — scripted responses, no model calls'),
    ).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  expect(screen.getByLabelText('Include a study plan')).not.toBeChecked();
});

test.each([false, true])(
  'current complete study bundle is inspected safely and reviewed (viewer=%s)',
  async (viewer) => {
    let saved = structuredClone(mission);
    const refs = ['plan', 'structured', 'settings', 'notes', 'quiz', 'key'];
    const names = [
      'study-plan.md',
      'study-plan.json',
      'reviewed-study-settings.json',
      'reviewed-notes.md',
      'quiz.md',
      'answer-key.md',
    ];
    const artifacts = [
      { id: 'old-quiz', name: 'quiz.md', task_id: 'quiz', size: 1, sha256: 'a'.repeat(64) },
      ...refs.map((id, i) => ({
        id,
        name: names[i],
        task_id: 'study_plan',
        size: 1,
        sha256: 'b'.repeat(64),
      })),
    ];
    setup(
      (path, options) => {
        if (path.startsWith('/missions?')) return new Response(JSON.stringify([saved]));
        if (path === '/missions/study-1') return new Response(JSON.stringify(saved));
        if (path.endsWith('/approvals'))
          return new Response(
            JSON.stringify(
              saved.status === 'WAITING_APPROVAL'
                ? [
                    {
                      id: 'study-review',
                      task_id: 'study_plan',
                      task_attempt: 1,
                      status: 'PENDING',
                      payload_digest: 'bound-study',
                      payload: { artifact_refs: refs },
                    },
                  ]
                : [],
            ),
          );
        if (path.includes('/artifacts?')) return new Response(JSON.stringify(artifacts));
        if (path === '/artifacts/plan/content')
          return new Response('# Suggested study\n<img src=x onerror=alert(1)>');
        if (path === '/approvals/study-review/decision') {
          expect(JSON.parse(options?.body as string)).toEqual({
            expected_version: 7,
            decision: 'approve',
            payload_digest: 'bound-study',
          });
          saved = {
            ...saved,
            status: 'COMPLETED',
            version: 8,
            tasks: saved.tasks.map((t) => ({ ...t, status: 'COMPLETED' })),
          };
          return new Response(JSON.stringify(saved));
        }
        return undefined;
      },
      { ...status, user_role: viewer ? 'viewer' : 'operator' },
    );
    const user = userEvent.setup();
    const view = render(<App />);
    await user.click(await screen.findByRole('button', { name: new RegExp(goal) }));
    await screen.findByText(/Inspect the study plan, original time settings/);
    expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
    expect(await screen.findByText(/<img src=x onerror=alert/)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Result artifact')).toHaveValue('plan');
    expect(screen.getByRole('link', { name: 'Download study-plan.md' })).toHaveAttribute(
      'download',
      'study-plan.md',
    );
    if (viewer) {
      expect(screen.getByRole('button', { name: 'Accept result' })).toBeDisabled();
      expect(screen.getByRole('button', { name: 'Deny result' })).toBeDisabled();
    } else {
      await user.click(screen.getByRole('button', { name: 'Accept result' }));
      await waitFor(() =>
        expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
      );
      view.unmount();
      render(<App />);
      await user.click(await screen.findByRole('button', { name: new RegExp(goal) }));
      await screen.findByText('STUDENT MISSION');
      expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    }
  },
);
