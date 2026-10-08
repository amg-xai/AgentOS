import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, test, expect } from 'vitest';
import { App } from './App';

const status = {
  execution_mode: 'live',
  workflow_ready: false,
  workspace_configured: true,
  workspace_name: 'Calculator',
  workspace_files: ['calculator.py'],
  test_commands: [['python', '-m', 'unittest']],
  provider_configured: false,
  model: null,
  user_role: 'operator',
  memory_retrieval: 'lexical',
};

test('offline demo keeps viewer controls read-only and its label visible across pages', async () => {
  mockFetch({
    '/status': {
      ...status,
      execution_mode: 'demo',
      workflow_ready: true,
      workspace_name: 'Offline demo · Calculator',
      user_role: 'viewer',
    },
  });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Offline demo — scripted responses, no model calls');
  expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: /Workspace memory/ }));
  expect(
    await screen.findByText(/Demo notes stay in separate local demo history/),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save note' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: /Agents & roles/ }));
  expect(screen.getByText('Offline demo — scripted responses, no model calls')).toBeInTheDocument();
});

test('switching server execution mode clears the previous mission selection', async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 5000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  const savedMission = {
    id: 'demo-mission',
    goal: 'Previously selected demo',
    role_id: 'developer',
    status: 'COMPLETED',
    version: 4,
    created_at: '2026-10-08T12:00:00Z',
    tasks: [],
  };
  const overrides: Record<string, unknown> = {
    '/status': { ...status, execution_mode: 'demo', workflow_ready: true },
    '/missions?limit=100&offset=0': [savedMission],
    '/missions/demo-mission': savedMission,
    '/missions/demo-mission/run': null,
  };
  mockFetch(overrides);
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole('button', { name: /Previously selected demo/ }));
  await screen.findByText('OFFLINE DEMO MISSION');
  overrides['/status'] = status;
  overrides['/missions?limit=100&offset=0'] = [];
  await act(async () => poll());
  await screen.findByText('A clear view of the work');
  expect(screen.queryByText('OFFLINE DEMO MISSION')).not.toBeInTheDocument();
  expect(screen.queryByText('Previously selected demo')).not.toBeInTheDocument();
  expect(
    screen.queryByText('Offline demo — scripted responses, no model calls'),
  ).not.toBeInTheDocument();
});
function mockFetch(overrides: Record<string, unknown> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/memory' && options?.method === 'POST')
        return new Response(JSON.stringify({ id: 'note', ...JSON.parse(options.body as string) }), {
          status: 201,
        });
      const defaults: Record<string, unknown> = {
        '/status': status,
        '/missions?limit=100&offset=0': [],
        '/roles': [],
        '/agents': [],
        '/memory?limit=100&query=': [],
      };
      return new Response(JSON.stringify(overrides[path] ?? defaults[path] ?? []), { status: 200 });
    }),
  );
}
test('shows missing configuration honestly and disables mission creation', async () => {
  mockFetch();
  render(<App />);
  expect(
    await screen.findByText('Finish local setup to run your first mission'),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
  expect(screen.getByText('Your next idea starts here')).toBeInTheDocument();
  expect(screen.getByText('Not configured')).toBeInTheDocument();
});
test('creates a mission and exposes API failures', async () => {
  mockFetch({
    '/status': { ...status, workflow_ready: true, provider_configured: true, model: 'configured' },
  });
  const original = globalThis.fetch;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) =>
      path === '/workflows/developer'
        ? new Response(JSON.stringify({ detail: 'Source configuration changed' }), { status: 409 })
        : original(path, options),
    ),
  );
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: '+ New mission' }));
  await user.type(
    screen.getByLabelText('What should your agents investigate and fix?'),
    'Fix the calculator',
  );
  await user.click(screen.getByRole('button', { name: 'Create mission' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Source configuration changed');
});
test('supports saving notes and explains retrieval limits', async () => {
  mockFetch();
  render(<App />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: /Workspace memory/ }));
  expect(await screen.findByText(/keyword overlap/)).toBeInTheDocument();
  await user.type(screen.getByLabelText('Title'), 'Arithmetic');
  await user.type(screen.getByLabelText('Context'), 'Keep negative sums exact');
  await user.click(screen.getByRole('button', { name: 'Save note' }));
  await waitFor(() => expect(screen.getByLabelText('Title')).toHaveValue(''));
  expect(globalThis.fetch).toHaveBeenCalledWith(
    '/memory',
    expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ title: 'Arithmetic', content: 'Keep negative sums exact' }),
    }),
  );
});
test('viewer cannot create missions or notes', async () => {
  mockFetch({ '/status': { ...status, user_role: 'viewer', workflow_ready: true } });
  render(<App />);
  await screen.findByText('Local service connected');
  expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: /Workspace memory/ }));
  expect(await screen.findByLabelText('Title')).toBeDisabled();
});
test('connection failure remains visible', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Local service unavailable')));
  render(<App />);
  expect(await screen.findByRole('alert')).toHaveTextContent('Local service unavailable');
});
