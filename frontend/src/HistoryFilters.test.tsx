import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import type { Mission } from './api';
import { overviewFixture } from './overview-fixture';

const mission: Mission = {
  id: 'found',
  goal: 'Archived calculator issue',
  role_id: 'historic_role',
  status: 'FAILED',
  version: 3,
  created_at: '2026-10-09T00:00:00Z',
  updated_at: '2026-10-09T00:00:00Z',
  tasks: [],
};
const respond = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((finish) => {
    resolve = finish;
  });
  return { promise, resolve };
}
function stub(handler: (path: string) => Response | Promise<Response> | undefined) {
  let poll = () => {};
  const original = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 5000) return original(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const custom = handler(path);
      if (custom) return custom;
      if (path === '/status')
        return respond({ execution_mode: 'live', user_role: 'viewer', workflow_ready: true });
      if (path === '/overview') return respond({ ...overviewFixture(), total_missions: 125 });
      if (path === '/roles')
        return respond([
          { id: 'developer', name: 'Developer', description: 'Code workflow', agents: [] },
        ]);
      if (path === '/missions/found') return respond(mission);
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    }),
  );
  return { poll: () => poll() };
}
async function loaded() {
  render(<App />);
  await screen.findByRole('form', { name: 'Search mission history' });
}

test('Viewer applies all filters explicitly, opens old work, and keeps overview totals global', async () => {
  stub((path) =>
    path === '/missions?limit=100&offset=0&query=calculator&role_id=historic_role&status=FAILED'
      ? respond([mission])
      : undefined,
  );
  const user = userEvent.setup();
  await loaded();
  const form = screen.getByRole('form', { name: 'Search mission history' });
  await user.type(within(form).getByLabelText('Search mission goals'), ' calculator ');
  await user.type(within(form).getByLabelText('History role id'), 'historic_role');
  await user.selectOptions(within(form).getByLabelText('Mission state'), 'FAILED');
  expect(
    vi.mocked(fetch).mock.calls.filter(([path]) => String(path).includes('query=')),
  ).toHaveLength(0);
  await user.click(within(form).getByRole('button', { name: 'Apply filters' }));
  await user.click(await screen.findByRole('button', { name: /Archived calculator issue/ }));
  await screen.findByRole('heading', { name: mission.goal });
  expect(screen.getByText('Matching missions on this page: 1')).toBeInTheDocument();
  expect(screen.getByText('125')).toBeInTheDocument();
  expect(
    screen.getByText(/Applied: goal “calculator” · role historic_role · state failed/),
  ).toBeInTheDocument();
  expect(screen.getByLabelText('Workflow')).toHaveValue('developer');
  expect(screen.getByRole('button', { name: '+ New mission' })).toBeDisabled();
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
});

test('no matches differ from empty history; clearing keeps selected mission inspection available', async () => {
  stub((path) =>
    path.startsWith('/missions?') && !path.includes('query=missing')
      ? respond([mission])
      : undefined,
  );
  const user = userEvent.setup();
  await loaded();
  await user.click(screen.getByRole('button', { name: /Archived calculator issue/ }));
  await screen.findByRole('heading', { name: mission.goal });
  await user.type(screen.getByLabelText('Search mission goals'), 'missing');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await screen.findByText('No matching missions');
  expect(screen.getByRole('heading', { name: mission.goal })).toBeInTheDocument();
  expect(screen.queryByText('Your next idea starts here')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Clear filters' }));
  await screen.findByRole('button', { name: /Archived calculator issue/ });
  expect(screen.getByLabelText('Search mission goals')).toHaveValue('');
  expect(screen.getByLabelText('History role id')).toHaveValue('');
  expect(screen.getByLabelText('Mission state')).toHaveValue('');
});

test('new filters reset pagination and obsolete results cannot overwrite current matches', async () => {
  const stale = deferred();
  let hold = false;
  const { poll } = stub((path) => {
    if (!path.startsWith('/missions?')) return;
    if (path.includes('query=needle')) return respond([mission]);
    if (hold) return stale.promise;
    if (path.includes('offset=100')) return respond([{ ...mission, goal: 'Old second page' }]);
    return respond(
      Array.from({ length: 100 }, (_, index) => ({
        ...mission,
        id: `page-${index}`,
        goal: `Old page ${index}`,
      })),
    );
  });
  const user = userEvent.setup();
  await loaded();
  await user.click(screen.getByRole('button', { name: 'Next' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled());
  hold = true;
  await act(async () => poll());
  await user.type(screen.getByLabelText('Search mission goals'), 'needle');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await screen.findByRole('button', { name: /Archived calculator issue/ });
  expect(screen.queryByRole('button', { name: 'Previous' })).not.toBeInTheDocument();
  await act(async () => stale.resolve(respond([{ ...mission, goal: 'Obsolete old page' }])));
  expect(screen.queryByRole('button', { name: /Obsolete old page/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Archived calculator issue/ })).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    '/missions?limit=100&offset=0&query=needle',
    expect.anything(),
  );
});

test('failed search reports unavailable; a failed poll labels retained matches as stale', async () => {
  let fail = false;
  const { poll } = stub((path) =>
    path.startsWith('/missions?')
      ? fail
        ? respond({ detail: 'History unavailable' }, 503)
        : respond([mission])
      : undefined,
  );
  const user = userEvent.setup();
  await loaded();
  fail = true;
  await user.type(screen.getByLabelText('Search mission goals'), 'broken');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('History unavailable');
  expect(screen.getByText(/Results are unavailable; retry Apply filters/)).toBeInTheDocument();
  expect(screen.queryByText('No matching missions')).not.toBeInTheDocument();
  fail = false;
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await screen.findByRole('button', { name: /Archived calculator issue/ });
  fail = true;
  await act(async () => poll());
  expect(
    screen.getByText(/Showing the last successful results for these filters/),
  ).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Archived calculator issue/ })).toBeInTheDocument();
});

test('mode switch clears filters and a pending old search cannot restore matches', async () => {
  let mode: 'live' | 'demo' = 'live';
  let pending = false;
  const old = deferred();
  const { poll } = stub((path) => {
    if (path === '/status') return respond({ execution_mode: mode, user_role: 'viewer' });
    if (path === '/overview') return respond(overviewFixture(mode));
    if (path.startsWith('/missions?') && path.includes('query=old'))
      return pending ? old.promise : respond([mission]);
  });
  const user = userEvent.setup();
  await loaded();
  await user.type(screen.getByLabelText('Search mission goals'), 'old');
  await user.type(screen.getByLabelText('History role id'), 'historic_role');
  await user.selectOptions(screen.getByLabelText('Mission state'), 'FAILED');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await screen.findByRole('button', { name: /Archived calculator issue/ });
  pending = true;
  await act(async () => poll());
  mode = 'demo';
  await act(async () => poll());
  await screen.findByText('Your next idea starts here');
  expect(screen.getByLabelText('Search mission goals')).toHaveValue('');
  expect(screen.getByLabelText('History role id')).toHaveValue('');
  expect(screen.getByLabelText('Mission state')).toHaveValue('');
  await act(async () => old.resolve(respond([mission])));
  expect(
    screen.queryByRole('button', { name: /Archived calculator issue/ }),
  ).not.toBeInTheDocument();
});

test('literal query encoding and keyboard form submission preserve search text', async () => {
  stub(() => undefined);
  const user = userEvent.setup();
  await loaded();
  await user.type(screen.getByLabelText('Search mission goals'), '100%_ Straße');
  await user.keyboard('{Enter}');
  await screen.findByText('No matching missions');
  expect(screen.getByLabelText('Search mission goals')).toHaveFocus();
  expect(fetch).toHaveBeenCalledWith(
    '/missions?limit=100&offset=0&query=100%25_+Stra%C3%9Fe',
    expect.anything(),
  );
  expect(screen.getByLabelText('Search mission goals')).toHaveAttribute('maxlength', '200');
  expect(screen.getByLabelText('History role id')).toHaveAttribute('pattern', '[a-z][a-z0-9_]*');
});
