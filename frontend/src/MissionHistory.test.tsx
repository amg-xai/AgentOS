import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Activity, Artifact, Mission } from './api';
import { MissionDetail } from './MissionDetail';

const mission: Mission = {
  id: 'history',
  goal: 'Inspect persisted history',
  role_id: 'developer',
  status: 'COMPLETED',
  version: 4,
  created_at: '2026-10-08T12:00:00Z',
  updated_at: '2026-10-08T12:00:00Z',
  tasks: [],
};
const respond = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
const activity = (sequence: number): Activity => ({
  sequence,
  timestamp: mission.created_at,
  actor: 'operator',
  action: `event_${sequence}`,
  task_id: null,
  details: {},
});
const artifact = (index: number): Artifact => ({
  id: `artifact-${index}`,
  name: `result-${index}.txt`,
  task_id: 'verify',
  sha256: 'a'.repeat(64),
  size: 20,
});

function mockHistory(handler: (path: string) => Response | Promise<Response> | undefined) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const custom = handler(path);
      if (custom) return custom;
      if (path === '/missions/history') return respond(mission);
      if (path.endsWith('/run')) return respond(null);
      if (path.endsWith('/content')) return new Response('Persisted artifact content');
      return respond([]);
    }),
  );
}

function renderHistory() {
  render(<MissionDetail id="history" canWrite={false} onChange={async () => {}} />);
}

test('artifact pages stay available after refresh without duplicating review references', async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 2000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  mockHistory((path) => {
    if (path.endsWith('/artifacts?limit=100&offset=0'))
      return respond(Array.from({ length: 100 }, (_, index) => artifact(index)));
    if (path.endsWith('/artifacts?limit=100&offset=100')) return respond([artifact(100)]);
    if (path.endsWith('/approvals'))
      return respond([
        {
          id: 'review',
          task_id: 'verify',
          task_attempt: 1,
          payload_digest: 'bound',
          status: 'PENDING',
          payload: { artifact_refs: ['artifact-100'] },
        },
      ]);
    if (path === '/artifacts/artifact-100') return respond(artifact(100));
  });
  const user = userEvent.setup();
  renderHistory();
  await user.click(await screen.findByRole('tab', { name: /artifacts/ }));
  expect(screen.getAllByRole('option')).toHaveLength(101);
  await user.click(screen.getByRole('button', { name: 'Load more artifacts' }));
  await waitFor(() =>
    expect(screen.queryByRole('button', { name: 'Load more artifacts' })).not.toBeInTheDocument(),
  );
  await user.selectOptions(screen.getByLabelText('Result artifact'), 'artifact-100');
  await act(async () => poll());
  expect(screen.getAllByRole('option')).toHaveLength(101);
  expect(screen.getByLabelText('Result artifact')).toHaveValue('artifact-100');
  expect(await screen.findByText('Persisted artifact content')).toBeInTheDocument();
});

test('activity continues beyond 1,000 events and polling uses the last sequence', async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 2000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  mockHistory((path) => {
    if (path.endsWith('/events?limit=1000&after=0'))
      return respond(Array.from({ length: 1000 }, (_, index) => activity(index + 1)));
    if (path.endsWith('/events?limit=1000&after=1000')) return respond([activity(1001)]);
  });
  const user = userEvent.setup();
  renderHistory();
  await user.click(await screen.findByRole('tab', { name: /activity/ }));
  await user.click(screen.getByRole('button', { name: 'Load more activity' }));
  expect(await screen.findByText('event 1001')).toBeInTheDocument();
  expect(document.querySelectorAll('.activity li')).toHaveLength(1001);
  await act(async () => poll());
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      '/missions/history/events?limit=1000&after=1001',
      expect.anything(),
    ),
  );
  expect(document.querySelectorAll('.activity li')).toHaveLength(1001);
}, 15000);

test('an older refresh cannot replace a newer mission revision', async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 2000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  let release: (response: Response) => void = () => {};
  const delayed = new Promise<Response>((resolve) => {
    release = resolve;
  });
  let calls = 0;
  mockHistory((path) => {
    if (path === '/missions/history') {
      calls += 1;
      if (calls === 2) return delayed;
      return respond({ ...mission, version: calls === 1 ? 4 : 6 });
    }
  });
  renderHistory();
  await screen.findByText(/revision 4/);
  await act(async () => poll());
  await act(async () => poll());
  await screen.findByText(/revision 6/);
  await act(async () => release(respond({ ...mission, version: 5 })));
  expect(screen.getByText(/revision 6/)).toBeInTheDocument();
  expect(screen.queryByText(/revision 5/)).not.toBeInTheDocument();
});

test('a successful refresh clears a transient history connection error', async () => {
  let poll: () => void = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 2000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  let unavailable = true;
  mockHistory((path) => {
    if (path === '/missions/history' && unavailable)
      return respond({ detail: 'Service interrupted' }, 503);
  });
  renderHistory();
  expect(await screen.findByRole('alert')).toHaveTextContent('Service interrupted');
  unavailable = false;
  await act(async () => poll());
  await screen.findByText(/revision 4/);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('mission tabs support arrow navigation, wrapping, Home/End, and labelled panels', async () => {
  mockHistory(() => undefined);
  const user = userEvent.setup();
  renderHistory();
  const tasks = await screen.findByRole('tab', { name: /tasks/ });
  const artifacts = screen.getByRole('tab', { name: /artifacts/ });
  const activity = screen.getByRole('tab', { name: /activity/ });
  for (const item of [tasks, artifacts, activity]) {
    expect(document.getElementById(item.getAttribute('aria-controls')!)).not.toBeNull();
  }
  tasks.focus();
  await user.keyboard('{ArrowRight}');
  expect(artifacts).toHaveFocus();
  expect(artifacts).toHaveAttribute('aria-selected', 'true');
  expect(tasks).toHaveAttribute('tabindex', '-1');
  const panel = screen.getByRole('tabpanel', { name: /artifacts/ });
  expect(artifacts).toHaveAttribute('aria-controls', panel.id);
  expect(panel).toHaveAttribute('aria-labelledby', artifacts.id);
  await user.keyboard('{End}');
  expect(activity).toHaveFocus();
  await user.keyboard('{ArrowRight}');
  expect(tasks).toHaveFocus();
  await user.keyboard('{ArrowLeft}');
  expect(activity).toHaveFocus();
  await user.keyboard('{Home}');
  expect(tasks).toHaveFocus();
  await user.tab();
  expect(screen.getByRole('tabpanel', { name: /tasks/ })).toHaveFocus();
});

test('a viewer can download the selected verified artifact with its original filename', async () => {
  mockHistory((path) => {
    if (path.endsWith('/artifacts?limit=100&offset=0')) return respond([artifact(0), artifact(1)]);
  });
  const user = userEvent.setup();
  renderHistory();
  await user.click(await screen.findByRole('tab', { name: /artifacts/ }));
  const first = await screen.findByRole('link', { name: 'Download result-0.txt' });
  expect(first).toHaveAttribute('href', '/artifacts/artifact-0/content');
  expect(first).toHaveAttribute('download', 'result-0.txt');
  await user.selectOptions(screen.getByLabelText('Result artifact'), 'artifact-1');
  const second = await screen.findByRole('link', { name: 'Download result-1.txt' });
  expect(second).toHaveAttribute('href', '/artifacts/artifact-1/content');
  expect(second).toHaveAttribute('download', 'result-1.txt');
  expect(screen.queryByRole('link', { name: 'Download result-0.txt' })).not.toBeInTheDocument();
});
