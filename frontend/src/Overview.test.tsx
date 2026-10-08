import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Mission, Overview } from './api';
import { App } from './App';
import { overviewFixture } from './overview-fixture';

const time = '2026-10-09T00:00:00Z';
const oldMission: Mission = {
  id: 'older',
  goal: 'Older reviewed work',
  role_id: 'developer',
  status: 'COMPLETED',
  version: 4,
  created_at: time,
  updated_at: time,
  tasks: [],
};
function overview(): Overview {
  return {
    ...overviewFixture(),
    total_missions: 125,
    pending_approvals: 42,
    total_artifacts: 301,
    durable_claims: 1,
    mission_counts: { COMPLETED: 83, WAITING_APPROVAL: 42 },
    recent_reviews: [
      {
        id: oldMission.id,
        goal: '<script>Older review</script>',
        role_id: 'developer',
        status: 'WAITING_APPROVAL',
        updated_at: time,
        has_claim: false,
      },
    ],
    recent_artifacts: [
      {
        id: 'file',
        mission_id: oldMission.id,
        task_id: 'work',
        name: 'older-result.md',
        size: 20,
        sha256: 'a'.repeat(64),
        created_at: time,
      },
    ],
    agent_activity: [
      {
        agent_id: 'testing',
        task_counts: { RUNNING: 1, COMPLETED: 25 },
        recent_tasks: [
          {
            mission_id: oldMission.id,
            mission_goal: oldMission.goal,
            task_id: 'work',
            title: 'Recorded test task',
            status: 'RUNNING',
            has_claim: true,
            mission_updated_at: time,
          },
        ],
      },
    ],
  };
}

function stub(
  handler: (path: string) => Response | Promise<Response> | undefined = () => undefined,
) {
  let poll = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 5000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const custom = handler(path);
      if (custom) return custom;
      if (path === '/status')
        return respond({
          execution_mode: 'live',
          user_role: 'viewer',
          workflow_ready: false,
          provider_configured: false,
          workspace_configured: false,
        });
      if (path === '/overview') return respond(overview());
      if (path === '/agents')
        return respond([
          {
            id: 'testing',
            name: 'Testing Agent',
            description: 'Inspects work',
            permissions: ['READ'],
            tools: [],
          },
          {
            id: 'idle',
            name: 'Unused Agent',
            description: 'Installed',
            permissions: [],
            tools: [],
          },
        ]);
      if (path === '/missions/older') return respond(oldMission);
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    }),
  );
  return { poll: () => poll() };
}
const respond = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}

test('workspace totals include older pages; Viewer opens old review and artifact missions safely', async () => {
  stub();
  const user = userEvent.setup();
  render(<App />);
  const totals = await screen.findByRole('region', { name: 'Workspace totals' });
  expect(within(totals).getByText('125')).toBeInTheDocument();
  expect(within(totals).getByText('42')).toBeInTheDocument();
  expect(within(totals).getByText('301')).toBeInTheDocument();
  expect(screen.getByText('Your next idea starts here')).toBeInTheDocument();
  expect(document.querySelector('script')).toBeNull();
  await user.click(
    screen.getByRole('button', { name: 'Open mission: <script>Older review</script>' }),
  );
  await screen.findByRole('heading', { name: oldMission.goal });
  expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
  await user.click(
    screen.getByRole('button', { name: 'Open mission for artifact: older-result.md' }),
  );
  expect(screen.getByRole('heading', { name: oldMission.goal })).toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
});

test('agent activity labels persisted running states and opens the existing mission detail', async () => {
  stub();
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('125');
  await user.click(screen.getByRole('button', { name: /Agents & roles/ }));
  expect(screen.getByText('26 recorded tasks · 1 recorded as running')).toBeInTheDocument();
  expect(screen.getByText('No recorded tasks for this installed agent.')).toBeInTheDocument();
  expect(screen.getByText(/Mission updated .*execution claim retained/)).toBeInTheDocument();
  expect(screen.getAllByText(/task states do not establish agent availability/)).toHaveLength(2);
  await user.click(screen.getByRole('button', { name: `Open mission: ${oldMission.goal}` }));
  await screen.findByRole('heading', { name: oldMission.goal });
});

test('initial overview failure remains unavailable instead of claiming zero totals', async () => {
  stub((path) =>
    path === '/overview' ? respond({ detail: 'Overview could not be read' }, 503) : undefined,
  );
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Overview could not be read');
  expect(screen.getByText(/Workspace overview unavailable/)).toBeInTheDocument();
  expect(screen.queryByRole('region', { name: 'Workspace totals' })).not.toBeInTheDocument();
});

test('failed polling retains explicitly stale counts and agent history', async () => {
  let failed = false;
  const { poll } = stub((path) =>
    path === '/overview' && failed ? respond({ detail: 'Refresh failed' }, 503) : undefined,
  );
  render(<App />);
  await screen.findByText('125');
  failed = true;
  await act(async () => poll());
  expect(await screen.findByRole('alert')).toHaveTextContent('Refresh failed');
  expect(screen.getByText(/Last successful snapshot/)).toBeInTheDocument();
  expect(screen.getByText('125')).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /Agents & roles/ }));
  expect(screen.getAllByText(/Showing the last successful snapshot/)).toHaveLength(2);
});

test('new mode clears old data immediately and an obsolete refresh cannot restore it', async () => {
  let mode: 'live' | 'demo' = 'live';
  let request = 0;
  const oldRefresh = deferred();
  const newRefresh = deferred();
  const { poll } = stub((path) => {
    if (path === '/status')
      return respond({ execution_mode: mode, user_role: 'viewer', workflow_ready: false });
    if (path === '/overview') {
      request++;
      return request === 1
        ? respond(overview())
        : request === 2
          ? oldRefresh.promise
          : newRefresh.promise;
    }
  });
  render(<App />);
  await screen.findByText('125');
  await act(async () => poll());
  mode = 'demo';
  await act(async () => poll());
  expect(screen.queryByText('125')).not.toBeInTheDocument();
  expect(screen.getByText(/Workspace overview unavailable/)).toBeInTheDocument();
  await act(async () =>
    newRefresh.resolve(respond({ ...overviewFixture('demo'), total_missions: 7 })),
  );
  expect(await screen.findByText('7')).toBeInTheDocument();
  await act(async () => oldRefresh.resolve(respond(overview())));
  expect(screen.queryByText('125')).not.toBeInTheDocument();
  expect(screen.queryByText('<script>Older review</script>')).not.toBeInTheDocument();
  expect(screen.getByText('7')).toBeInTheDocument();
});

test('pagination rejects an obsolete polling response and keeps workspace-wide totals', async () => {
  let request = 0;
  const held = deferred();
  const { poll } = stub((path) => {
    if (path === '/overview') {
      request++;
      if (request === 2) return held.promise;
      return respond({ ...overview(), total_missions: request === 1 ? 125 : 300 });
    }
    if (path === '/missions?limit=100&offset=0')
      return respond(
        Array.from({ length: 100 }, (_, index) => ({
          ...oldMission,
          id: `page-${index}`,
          goal: `First page ${index}`,
        })),
      );
    if (path === '/missions?limit=100&offset=100')
      return respond([{ ...oldMission, goal: 'Second page only' }]);
  });
  render(<App />);
  await screen.findByText('125');
  await act(async () => poll());
  await userEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByRole('button', { name: /Second page only/ });
  expect(screen.getByText('300')).toBeInTheDocument();
  await act(async () => held.resolve(respond({ ...overview(), total_missions: 200 })));
  expect(screen.queryByText('200')).not.toBeInTheDocument();
  expect(screen.getByText('300')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /First page 0/ })).not.toBeInTheDocument();
});

test('a mode mismatch within one refresh clears data rather than mixing histories', async () => {
  let mismatch = false;
  const { poll } = stub((path) =>
    path === '/overview' && mismatch ? respond(overviewFixture('demo')) : undefined,
  );
  render(<App />);
  await screen.findByText('125');
  mismatch = true;
  await act(async () => poll());
  expect(await screen.findByRole('alert')).toHaveTextContent('Server execution mode changed');
  expect(screen.queryByText('125')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
});

test('overview mission links are keyboard operable', async () => {
  stub();
  render(<App />);
  const button = await screen.findByRole('button', {
    name: 'Open mission for artifact: older-result.md',
  });
  button.focus();
  await userEvent.keyboard('{Enter}');
  await waitFor(() =>
    expect(screen.getByRole('heading', { name: oldMission.goal })).toBeInTheDocument(),
  );
});

test('mode switch on an older page resets pagination before fetching the new history', async () => {
  let mode: 'live' | 'demo' = 'live';
  const { poll } = stub((path) => {
    if (path === '/status') return respond({ execution_mode: mode, user_role: 'viewer' });
    if (path === '/overview')
      return respond(mode === 'live' ? overview() : overviewFixture('demo'));
    if (path === '/missions?limit=100&offset=0')
      return respond(
        mode === 'demo'
          ? []
          : Array.from({ length: 100 }, (_, index) => ({ ...oldMission, id: `first-${index}` })),
      );
    if (path === '/missions?limit=100&offset=100')
      return respond([{ ...oldMission, goal: 'Old second page' }]);
  });
  render(<App />);
  await screen.findByText('125');
  await userEvent.click(screen.getByRole('button', { name: 'Next' }));
  await screen.findByRole('button', { name: /Old second page/ });
  mode = 'demo';
  await act(async () => poll());
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Previous' })).not.toBeInTheDocument(),
  );
  expect(screen.queryByRole('button', { name: /Old second page/ })).not.toBeInTheDocument();
  expect(screen.getByText('Your next idea starts here')).toBeInTheDocument();
  expect(screen.queryByText('125')).not.toBeInTheDocument();
});

test('a creation response from the old mode cannot restore its mission selection', async () => {
  let mode: 'live' | 'demo' = 'live';
  const creation = deferred();
  const { poll } = stub((path) => {
    if (path === '/status')
      return respond({ execution_mode: mode, user_role: 'operator', workflow_ready: true });
    if (path === '/overview') return respond(overviewFixture(mode));
    if (path === '/workflows/developer') return creation.promise;
  });
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '+ New mission' }));
  await user.type(
    screen.getByLabelText('What should your agents investigate and fix?'),
    'Old-mode creation',
  );
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  mode = 'demo';
  await act(async () => poll());
  await act(async () => creation.resolve(respond(oldMission)));
  expect(screen.queryByRole('heading', { name: oldMission.goal })).not.toBeInTheDocument();
  expect(screen.getByText('A clear view of the work')).toBeInTheDocument();
});
