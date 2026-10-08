import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Mission } from './api';
import { App } from './App';

const demoGoal =
  'Fix incorrect addition in the bundled Calculator sample. Preserve all test assertions.';
function workflow(
  initialFailed = false,
  brokenArtifact = false,
  reviewOutsidePage = false,
  demo = false,
) {
  let mission: Mission = {
    id: 'mission-1',
    goal: demo ? demoGoal : 'Fix calculator addition',
    role_id: 'developer',
    status: initialFailed ? 'FAILED' : 'PENDING',
    version: 1,
    created_at: '2026-10-08T12:00:00Z',
    updated_at: '2026-10-08T12:00:00Z',
    tasks: [
      {
        id: 'verify',
        title: 'Run tests and review the result',
        agent_id: 'testing',
        status: initialFailed ? 'FAILED' : 'READY',
        attempts: initialFailed ? 1 : 0,
        dependencies: [],
        outputs: null,
        error: initialFailed ? 'ProviderFailure' : null,
      },
    ],
  };
  const decisions: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      const respond = (data: unknown, status = 200) =>
        new Response(JSON.stringify(data), { status });
      if (path === '/status')
        return respond({
          workflow_ready: true,
          workspace_configured: true,
          workspace_name: 'Calculator',
          provider_configured: !demo,
          model: demo ? null : 'TEST TRANSPORT',
          execution_mode: demo ? 'demo' : 'live',
          demo_goal: demo ? demoGoal : null,
          user_role: 'operator',
        });
      if (path.startsWith('/missions?')) return respond([mission]);
      if (path === '/workflows/developer') {
        if (demo) expect(JSON.parse(options?.body as string)).toEqual({ goal: demoGoal });
        return respond(mission, 201);
      }
      if (path.endsWith('/actions') && options?.method === 'POST') {
        mission = {
          ...mission,
          status: 'PENDING',
          version: mission.version + 1,
          tasks: [{ ...mission.tasks[0], status: 'READY', error: null }],
        };
        return respond(mission);
      }
      if (path === '/missions/mission-1/run') {
        if (options?.method === 'POST') {
          mission = {
            ...mission,
            status: 'WAITING_APPROVAL',
            version: mission.version + 2,
            tasks: [
              {
                ...mission.tasks[0],
                status: 'WAITING_APPROVAL',
                attempts: mission.tasks[0].attempts + 1,
                outputs: {
                  passed: true,
                  report: 'Real runner evidence is supplied by backend tests',
                },
              },
            ],
          };
          return respond(mission);
        }
        return respond(null);
      }
      if (path === '/approvals/review-1/decision') {
        const body = JSON.parse(options?.body as string);
        decisions.push(body);
        expect(body.expected_version).toBe(mission.version);
        expect(body.payload_digest).toBe('digest-bound-to-result');
        mission = {
          ...mission,
          status: body.decision === 'approve' ? 'COMPLETED' : 'FAILED',
          version: mission.version + 1,
          tasks: [
            { ...mission.tasks[0], status: body.decision === 'approve' ? 'COMPLETED' : 'FAILED' },
          ],
        };
        return respond(mission);
      }
      if (path === '/missions/mission-1') return respond(mission);
      if (path.endsWith('/approvals'))
        return respond(
          mission.status === 'WAITING_APPROVAL'
            ? [
                {
                  id: 'review-1',
                  task_id: 'verify',
                  payload_digest: 'digest-bound-to-result',
                  status: 'PENDING',
                  task_attempt: mission.tasks[0].attempts,
                  payload: { artifact_refs: ['diff-1'] },
                },
              ]
            : [],
        );
      if (path.includes('/artifacts?'))
        return respond(
          mission.tasks[0].outputs
            ? [
                {
                  id: 'upstream-1',
                  name: 'proposed.diff',
                  task_id: 'fix',
                  sha256: 'b'.repeat(64),
                  size: 42,
                },
                ...(!reviewOutsidePage
                  ? [
                      {
                        id: 'diff-1',
                        name: 'tested.diff',
                        task_id: 'verify',
                        sha256: 'a'.repeat(64),
                        size: 42,
                      },
                    ]
                  : []),
              ]
            : [],
        );
      if (path === '/artifacts/diff-1/content')
        return new Response('<script>untrusted artifact text</script>', {
          status: brokenArtifact ? 409 : 200,
        });
      if (path === '/artifacts/diff-1')
        return respond({
          id: 'diff-1',
          name: 'tested.diff',
          task_id: 'verify',
          sha256: 'a'.repeat(64),
          size: 42,
        });
      if (path === '/artifacts/upstream-1/content') return new Response('Earlier task proposal');
      if (path === '/memory') return respond({ id: 'saved-reference' }, 201);
      return respond([]);
    }),
  );
  return decisions;
}

test('create, execute, inspect artifact safely, save context, and accept the bound result', async () => {
  const decisions = workflow();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Local service connected');
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  await user.type(
    screen.getByLabelText('What should your agents investigate and fix?'),
    'Fix calculator addition',
  );
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  await user.click(await screen.findByRole('button', { name: 'Run mission' }));
  expect(await screen.findByText('Tests passed')).toBeInTheDocument();
  expect(screen.getByText('Review attempt 1: tested.diff')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
  expect(await screen.findByText('<script>untrusted artifact text</script>')).toBeInTheDocument();
  expect(screen.getByLabelText('Result artifact')).toHaveValue('diff-1');
  expect(document.querySelector('pre script')).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Save artifact reference to memory' }));
  expect(await screen.findByText('Saved to workspace memory.')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Accept result' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
  );
  expect(decisions).toHaveLength(1);
  expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
});

test('retry a failed task then deny the result explicitly', async () => {
  const decisions = workflow(true);
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Fix calculator addition/ }));
  await user.click(await screen.findByRole('button', { name: 'Retry task' }));
  await user.click(await screen.findByRole('button', { name: 'Run mission' }));
  await user.click(await screen.findByRole('button', { name: 'Deny result' }));
  expect(await screen.findByRole('button', { name: 'Retry task' })).toBeInTheDocument();
  expect(decisions).toEqual([expect.objectContaining({ decision: 'deny' })]);
});

test('artifact integrity failure is shown without rendering content', async () => {
  workflow(false, true);
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Fix calculator addition/ }));
  await user.click(await screen.findByRole('button', { name: 'Run mission' }));
  await user.click(await screen.findByRole('button', { name: 'Inspect artifacts →' }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Artifact could not be loaded or failed its integrity check',
  );
  expect(screen.queryByText('<script>untrusted artifact text</script>')).not.toBeInTheDocument();
});

test('review artifacts remain inspectable outside the first history page', async () => {
  workflow(false, false, true);
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Fix calculator addition/ }));
  await user.click(await screen.findByRole('button', { name: 'Run mission' }));
  expect(await screen.findByText('Review attempt 1: tested.diff')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Inspect artifacts →' }));
  expect(await screen.findByText('<script>untrusted artifact text</script>')).toBeInTheDocument();
  expect(screen.getByLabelText('Result artifact')).toHaveValue('diff-1');
  await user.click(screen.getByRole('button', { name: 'Accept result' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
  );
  expect(screen.getByLabelText('Result artifact')).toHaveValue('diff-1');
  expect(screen.getByRole('option', { name: /tested.diff/ })).toBeInTheDocument();
});

test('offline demo has a fixed goal and stays labelled through creation, review, and reload', async () => {
  workflow(false, false, false, true);
  const user = userEvent.setup();
  const view = render(<App />);
  await screen.findByText('Offline demo — scripted responses, no model calls');
  expect(
    screen.queryByText('Finish local setup to run your first mission'),
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: '+ New mission' }));
  const goal = screen.getByLabelText('What should your agents investigate and fix?');
  expect(goal).toHaveValue(demoGoal);
  expect(goal).toHaveAttribute('readonly');
  expect(screen.getByText(/No source files or notes are sent to a model/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Create demo mission' }));
  await user.click(await screen.findByRole('button', { name: 'Run mission' }));
  expect(await screen.findByText('OFFLINE DEMO MISSION')).toBeInTheDocument();
  await user.click(await screen.findByRole('button', { name: 'Accept result' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
  );
  view.unmount();
  render(<App />);
  await screen.findByText('Offline demo — scripted responses, no model calls');
  await user.click(await screen.findByRole('button', { name: /Fix incorrect addition/ }));
  expect(await screen.findByText('OFFLINE DEMO MISSION')).toBeInTheDocument();
  expect(screen.getAllByText('completed').length).toBeGreaterThan(0);
  await user.click(screen.getByRole('button', { name: /Workspace memory/ }));
  expect(
    await screen.findByText(/Demo notes stay in separate local demo history/),
  ).toBeInTheDocument();
  expect(screen.queryByText(/Relevant notes may be sent/)).not.toBeInTheDocument();
});
