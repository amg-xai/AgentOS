import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import type { Mission, State, Task } from './api';
import { label } from './api';
import { MissionDetail } from './MissionDetail';
import { dependencyStages, TaskDependencies } from './TaskDependencies';

const task = (id: string, dependencies: string[] = [], status: State = 'PENDING'): Task => ({
  id,
  title: `Work ${id}`,
  agent_id: 'code_helper',
  dependencies,
  status,
  attempts: 0,
  error: null,
  outputs: null,
});

test('unsorted branch/merge and isolated tasks use stable dependency depth', () => {
  const tasks = [
    task('merge', ['right', 'left']),
    task('right', ['root']),
    task('isolated'),
    task('root'),
    task('left', ['root']),
  ];
  render(<TaskDependencies tasks={tasks} onInspect={vi.fn()} />);
  const stages = within(screen.getByRole('list', { name: 'Dependency stages' })).getAllByRole(
    'heading',
  );
  expect(stages.map((heading) => heading.textContent)).toEqual(['Stage 1', 'Stage 2', 'Stage 3']);
  expect(
    stages.map((heading) =>
      within(heading.parentElement!)
        .getAllByRole('button')
        .map((button) => button.textContent),
    ),
  ).toEqual([
    ['Work isolated (isolated)', 'Work root (root)'],
    ['Work right (right)', 'Work left (left)'],
    ['Work merge (merge)'],
  ]);
  expect(screen.getByText('2 of 2 prerequisites incomplete.')).toBeInTheDocument();
  expect(screen.getAllByText('1 of 1 prerequisites incomplete.')).toHaveLength(2);
});

test.each<State>([
  'PENDING',
  'READY',
  'RUNNING',
  'WAITING_APPROVAL',
  'BLOCKED',
  'FAILED',
  'COMPLETED',
  'CANCELLED',
])('prerequisites show recorded %s state without overriding the dependant', (status) => {
  render(
    <TaskDependencies
      tasks={[task('upstream', [], status), task('downstream', ['upstream'], 'PENDING')]}
      onInspect={vi.fn()}
    />,
  );
  const downstream = screen
    .getByRole('button', { name: 'Inspect task Work downstream (downstream)' })
    .closest('li')!;
  const prerequisites = within(downstream).getByRole('list');
  expect(within(prerequisites).getByText(label(status))).toBeInTheDocument();
  expect(
    within(downstream.querySelector('.dependency-title')!).getByText('pending'),
  ).toBeInTheDocument();
  expect(
    within(downstream).getByText(
      status === 'COMPLETED' ? 'All prerequisites completed.' : '1 of 1 prerequisites incomplete.',
    ),
  ).toBeInTheDocument();
});

test('duplicate titles retain distinct ids and keyboard inspection targets', async () => {
  const inspect = vi.fn();
  const user = userEvent.setup();
  render(
    <TaskDependencies
      tasks={[
        { ...task('first'), title: 'Same title' },
        { ...task('second'), title: 'Same title' },
      ]}
      onInspect={inspect}
    />,
  );
  screen.getByRole('button', { name: 'Inspect task Same title (second)' }).focus();
  await user.keyboard('{Enter}');
  expect(inspect).toHaveBeenCalledExactlyOnceWith('second');
});

test.each([
  [task('missing', ['absent'])],
  [task('self', ['self'])],
  [task('a', ['b']), task('b', ['a']), task('isolated')],
  [task('duplicate'), task('duplicate')],
  [task('root'), task('next', ['root', 'root'])],
  [{ ...task('invalid'), dependencies: null } as unknown as Task],
])('invalid graph reports unavailable rather than a partial dependency order: %#', (...tasks) => {
  render(<TaskDependencies tasks={tasks} onInspect={vi.fn()} />);
  expect(screen.getByText(/Dependency layout unavailable/)).toBeInTheDocument();
  expect(screen.queryByRole('list', { name: 'Dependency stages' })).not.toBeInTheDocument();
});

test('empty graphs have explicit copy and deep graphs do not recurse', () => {
  render(<TaskDependencies tasks={[]} onInspect={vi.fn()} />);
  expect(screen.getByText('This mission has no tasks.')).toBeInTheDocument();
  const tasks = Array.from({ length: 10000 }, (_, index) =>
    task(`${index}`, index ? [`${index - 1}`] : []),
  );
  const stages = dependencyStages(tasks)!;
  expect(stages).toHaveLength(10000);
  expect(stages[9999][0].id).toBe('9999');
});

function mockMission(tasks: Task[], canWrite = false) {
  let mission: Mission = {
    id: 'dependencies',
    goal: 'Inspect the task graph',
    role_id: 'developer',
    status: 'FAILED',
    version: 1,
    created_at: '2026-10-09T00:00:00Z',
    updated_at: '2026-10-09T00:00:00Z',
    tasks,
  };
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    if (path.endsWith('/actions') && options?.method === 'POST') {
      expect(JSON.parse(options.body as string)).toEqual({ expected_version: 1, action: 'retry' });
      mission = {
        ...mission,
        version: 2,
        status: 'PENDING',
        tasks: [task('upstream', [], 'READY'), task('downstream', ['upstream'])],
      };
    }
    if (path === '/approvals/review/decision') {
      expect(JSON.parse(options?.body as string)).toEqual({
        expected_version: 3,
        decision: 'approve',
        payload_digest: 'bound',
      });
      mission = {
        ...mission,
        version: 4,
        status: 'RUNNING',
        tasks: [task('upstream', [], 'COMPLETED'), task('downstream', ['upstream'], 'READY')],
      };
    }
    if (path === '/missions/dependencies') return respond(mission);
    if (path.endsWith('/run')) return respond(null);
    if (path.endsWith('/approvals') && mission.status === 'WAITING_APPROVAL')
      return respond([
        { id: 'review', task_id: 'upstream', payload_digest: 'bound', status: 'PENDING' },
      ]);
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<MissionDetail id="dependencies" canWrite={canWrite} onChange={async () => {}} />);
  return {
    fetchMock,
    setMission: (next: Mission) => {
      mission = next;
    },
    getMission: () => mission,
  };
}

test('Viewer keyboard navigation focuses existing detail and inspection never writes', async () => {
  const { fetchMock } = mockMission([task('downstream', ['upstream']), task('upstream')]);
  const user = userEvent.setup();
  const button = await screen.findByRole('button', {
    name: 'Inspect task Work downstream (downstream)',
  });
  button.focus();
  await user.keyboard('{Enter}');
  expect(
    screen.getByRole('article', { name: 'Task detail: Work downstream (downstream)' }),
  ).toHaveFocus();
  expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  expect(screen.getByRole('button', { name: 'Cancel mission' })).toBeDisabled();
});

test.each([{ dependencies: ['missing'] }, { dependencies: null }])(
  'invalid dependency layout preserves task details: %#',
  async ({ dependencies }) => {
    mockMission([
      {
        ...task('broken', [], 'FAILED'),
        dependencies,
        error: 'Preserved failure evidence',
      } as Task,
    ]);
    expect(await screen.findByText(/Dependency layout unavailable/)).toBeInTheDocument();
    expect(
      screen.getByRole('article', { name: 'Task detail: Work broken (broken)' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Preserved failure evidence')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry task' })).toBeDisabled();
  },
);

test('retry and approval refresh the same dependency snapshot without implicit execution', async () => {
  let poll = () => {};
  const originalInterval = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 2000) return originalInterval(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  const user = userEvent.setup();
  const mock = mockMission(
    [task('upstream', [], 'FAILED'), task('downstream', ['upstream'], 'BLOCKED')],
    true,
  );
  await user.click(await screen.findByRole('button', { name: 'Retry task' }));
  const upstreamCard = () =>
    screen.getByRole('button', { name: 'Inspect task Work upstream (upstream)' }).closest('li')!;
  expect(within(upstreamCard()).getByText('ready')).toBeInTheDocument();
  mock.setMission({
    ...mock.getMission(),
    version: 3,
    status: 'WAITING_APPROVAL',
    tasks: [task('upstream', [], 'WAITING_APPROVAL'), task('downstream', ['upstream'])],
  });
  await act(async () => poll());
  await user.click(await screen.findByRole('button', { name: 'Accept result' }));
  await waitFor(() => expect(screen.getByText('All prerequisites completed.')).toBeInTheDocument());
  expect(within(upstreamCard()).getByText('completed')).toBeInTheDocument();
  const writes = mock.fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST');
  expect(writes.map(([path]) => path)).toEqual([
    '/missions/dependencies/tasks/upstream/actions',
    '/approvals/review/decision',
  ]);
});
