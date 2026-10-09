import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from './App';
import { Memory } from './Memory';
import { overviewFixture } from './overview-fixture';

const first = 'a'.repeat(32);
const second = 'b'.repeat(32);
const note = (id: string, refs: string[]) => ({
  id,
  title: `Note ${id}`,
  content: 'Retained context',
  artifact_refs: refs,
  created_at: '2026-10-09T00:00:00Z',
});
const metadata = (id: string) => ({
  id,
  name: `${id === first ? 'reviewed' : 'other'}.md`,
  mission_id: 'owner',
  task_id: 'review',
  sha256: 'c'.repeat(64),
  size: 44,
});
const respond = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
function stub(
  handler: (path: string, options?: RequestInit) => Response | Promise<Response> | undefined = () =>
    undefined,
) {
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const custom = handler(path, options);
    if (custom) return custom;
    if (path.startsWith('/memory?'))
      return respond([note('linked', [first, second]), note('plain', [])]);
    if (path === `/artifacts/${first}`) return respond(metadata(first));
    if (path === `/artifacts/${second}`) return respond(metadata(second));
    if (path === `/artifacts/${first}/content`)
      return new Response('<script>unsafe()</script>\n[link](https://example.com)');
    if (path === `/artifacts/${second}/content`) return new Response('Current artifact text');
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
const refButton = (index = 1) =>
  screen.getByRole('button', {
    name: new RegExp(`Inspect linked artifact ${index} for note Note linked`),
  });

test('Viewer inspects references on demand, renders inert text, downloads, and returns keyboard focus', async () => {
  const fetchMock = stub();
  const open = vi.fn();
  const user = userEvent.setup();
  render(<Memory canWrite={false} onOpenMission={open} />);
  await screen.findByText('Note linked');
  expect(fetchMock.mock.calls.every(([path]) => !path.startsWith('/artifacts/'))).toBe(true);
  expect(screen.getAllByRole('button', { name: /Inspect linked artifact/ })).toHaveLength(2);
  const origin = refButton();
  origin.focus();
  await user.keyboard('{Enter}');
  const panel = await screen.findByRole('region', { name: 'Linked artifact' });
  expect(panel).toHaveFocus();
  const download = await screen.findByRole('link', { name: 'Download reviewed.md' });
  expect(download).toHaveAttribute('href', `/artifacts/${first}/content`);
  expect(download).toHaveAttribute('download', 'reviewed.md');
  expect(panel.querySelector('pre')?.textContent).toContain('<script>unsafe()</script>');
  expect(panel.querySelector('pre script, pre a')).toBeNull();
  expect(within(panel).getByText('Task review · 44 bytes')).toBeInTheDocument();
  expect(within(panel).getByText(`SHA-256 ${'c'.repeat(64)}`)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Open owning mission' }));
  expect(open).toHaveBeenCalledExactlyOnceWith('owner');
  await user.click(screen.getByRole('button', { name: 'Close preview' }));
  expect(origin).toHaveFocus();
  expect(screen.queryByRole('region', { name: 'Linked artifact' })).not.toBeInTheDocument();
  expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  expect(screen.getByRole('button', { name: 'Save note' })).toBeDisabled();
});

test.each([
  { endpoint: '', status: 404 },
  { endpoint: '/content', status: 404 },
  { endpoint: '/content', status: 409 },
  { endpoint: '/content', status: 500 },
  { endpoint: '/content', status: 0 },
])(
  'unavailable reference ($endpoint $status) suppresses content and downloads, then can retry',
  async ({ endpoint, status }) => {
    let failing = true;
    stub((path) => {
      if (!failing || path !== `/artifacts/${first}${endpoint}`) return undefined;
      return status === 0
        ? Promise.reject(new Error('Network unavailable'))
        : respond({ detail: 'Missing linked artifact' }, status);
    });
    const user = userEvent.setup();
    render(<Memory canWrite={false} />);
    await screen.findByText('Note linked');
    await user.click(refButton());
    await screen.findByText('Artifact unavailable. Close the preview and try the reference again.');
    expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/unsafe\(\)/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Open owning mission' })).not.toBeInTheDocument();
    failing = false;
    await user.click(screen.getByRole('button', { name: 'Close preview' }));
    await user.click(refButton());
    expect(await screen.findByRole('link', { name: 'Download reviewed.md' })).toBeInTheDocument();
  },
);

test('a delayed canceled body cannot replace another selected reference', async () => {
  let finishBody!: (text: string) => void;
  let signal: AbortSignal | undefined;
  const body = new Promise<string>((resolve) => {
    finishBody = resolve;
  });
  stub((path, options) => {
    if (path !== `/artifacts/${first}/content`) return undefined;
    signal = options?.signal as AbortSignal;
    return { ok: true, text: () => body } as Response;
  });
  const user = userEvent.setup();
  render(<Memory canWrite={false} />);
  await screen.findByText('Note linked');
  await user.click(refButton());
  await screen.findByText('Verifying and loading linked artifact…');
  expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument();
  await user.click(refButton(2));
  await screen.findByText('Current artifact text');
  expect(signal?.aborted).toBe(true);
  await act(async () => finishBody('Obsolete content'));
  expect(screen.queryByText('Obsolete content')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Download other.md' })).toHaveAttribute(
    'href',
    `/artifacts/${second}/content`,
  );
});

test.each(['close', 'search', 'unmount'])(
  '%s cancels inspection and ignores late failures',
  async (action) => {
    let reject!: (error: Error) => void;
    let signal: AbortSignal | undefined;
    const pending = new Promise<Response>((_, fail) => {
      reject = fail;
    });
    stub((path, options) => {
      if (path !== `/artifacts/${first}`) return undefined;
      signal = options?.signal as AbortSignal;
      return pending;
    });
    const user = userEvent.setup();
    const view = render(<Memory canWrite={false} />);
    await screen.findByText('Note linked');
    await user.click(refButton());
    if (action === 'close') await user.click(screen.getByRole('button', { name: 'Close preview' }));
    if (action === 'search') await user.type(screen.getByLabelText('Search notes'), 'x');
    if (action === 'unmount') view.unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => reject(new Error('Obsolete read failure')));
    expect(screen.queryByRole('region', { name: 'Linked artifact' })).not.toBeInTheDocument();
    expect(screen.queryByText('Obsolete read failure')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument();
  },
);

test('saving a note reloads results and cancels the pending artifact preview', async () => {
  let finish!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const fetchMock = stub((path, options) => {
    if (path === `/artifacts/${first}/content`) {
      signal = options?.signal as AbortSignal;
      return pending;
    }
    if (path === '/memory' && options?.method === 'POST') return respond(note('saved', []), 201);
    return undefined;
  });
  const user = userEvent.setup();
  render(<Memory canWrite />);
  await screen.findByText('Note linked');
  await user.click(refButton());
  await user.type(screen.getByLabelText('Title'), 'New note');
  await user.type(screen.getByLabelText('Context'), 'New context');
  await user.click(screen.getByRole('button', { name: 'Save note' }));
  await waitFor(() => expect(signal?.aborted).toBe(true));
  await act(async () => finish(new Response('Old body after note reload')));
  expect(screen.queryByRole('region', { name: 'Linked artifact' })).not.toBeInTheDocument();
  expect(screen.queryByText('Old body after note reload')).not.toBeInTheDocument();
  expect(screen.getByLabelText('Title')).toHaveValue('');
  const writes = fetchMock.mock.calls.filter(([, options]) => options?.method === 'POST');
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe('/memory');
  expect(JSON.parse(writes[0][1]?.body as string)).toEqual({
    title: 'New note',
    content: 'New context',
  });
});

function appStub(
  handler: (path: string, options?: RequestInit) => Response | Promise<Response> | undefined = () =>
    undefined,
) {
  let poll = () => {};
  const original = window.setInterval.bind(window);
  vi.spyOn(window, 'setInterval').mockImplementation((callback, delay) => {
    if (delay !== 5000) return original(callback, delay);
    poll = callback as () => void;
    return 1;
  });
  const fetchMock = stub((path, options) => {
    const custom = handler(path, options);
    if (custom) return custom;
    if (path === '/status')
      return respond({ execution_mode: 'live', user_role: 'viewer', workflow_ready: true });
    if (path === '/overview') return respond(overviewFixture());
    if (path === '/missions/owner')
      return respond({
        id: 'owner',
        goal: 'Older owning mission',
        role_id: 'creator',
        status: 'COMPLETED',
        version: 4,
        tasks: [],
        created_at: '2026-10-09T00:00:00Z',
        updated_at: '2026-10-09T00:00:00Z',
      });
    if (path.endsWith('/run')) return respond(null);
    return undefined;
  });
  return { fetchMock, poll: () => poll() };
}

test('opening an owning mission outside current history preserves applied filters and never writes', async () => {
  const { fetchMock } = appStub();
  const user = userEvent.setup();
  render(<App />);
  await user.type(await screen.findByLabelText('Search mission goals'), 'unrelated');
  await user.click(screen.getByRole('button', { name: 'Apply filters' }));
  await screen.findByText(/Applied: goal “unrelated”/);
  await user.click(screen.getByRole('button', { name: /Workspace memory/ }));
  await screen.findByText('Note linked');
  await user.click(refButton());
  await user.click(await screen.findByRole('button', { name: 'Open owning mission' }));
  expect(await screen.findByRole('heading', { name: 'Older owning mission' })).toBeInTheDocument();
  expect(screen.getByText(/Applied: goal “unrelated”/)).toBeInTheDocument();
  expect(screen.getByLabelText('Search mission goals')).toHaveValue('unrelated');
  expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
});

test('normal/demo switch clears a pending preview and cannot restore old-mode content', async () => {
  let demo = false;
  let finish!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  const pending = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const mock = appStub((path, options) => {
    if (path === '/status')
      return respond({
        execution_mode: demo ? 'demo' : 'live',
        user_role: 'viewer',
        workflow_ready: true,
      });
    if (path === '/overview') return respond(overviewFixture(demo ? 'demo' : 'live'));
    if (path.startsWith('/memory?') && demo) return respond([note('demo', [])]);
    if (path === `/artifacts/${first}/content`) {
      signal = options?.signal as AbortSignal;
      return pending;
    }
    return undefined;
  });
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Local service connected');
  await user.click(screen.getByRole('button', { name: /Workspace memory/ }));
  await screen.findByText('Note linked');
  await user.click(refButton());
  demo = true;
  await act(async () => mock.poll());
  await screen.findByText('Note demo');
  await waitFor(() => expect(signal?.aborted).toBe(true));
  await act(async () => finish(new Response('Old normal-mode text')));
  expect(screen.queryByRole('region', { name: 'Linked artifact' })).not.toBeInTheDocument();
  expect(screen.queryByText('Old normal-mode text')).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: /Download/ })).not.toBeInTheDocument();
});
