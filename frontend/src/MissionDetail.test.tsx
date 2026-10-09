import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MissionDetail } from './MissionDetail';

test('a canceled artifact body cannot replace the currently selected preview', async () => {
  let finishOldBody!: (content: string) => void;
  let oldSignal: AbortSignal | undefined;
  const oldBody = new Promise<string>((resolve) => {
    finishOldBody = resolve;
  });
  const artifacts = ['old', 'current'].map((id) => ({
    id,
    name: `${id}.md`,
    task_id: 'write',
    sha256: (id === 'old' ? 'a' : 'b').repeat(64),
    size: 20,
  }));
  const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    if (path === '/missions/mission')
      return respond({
        id: 'mission',
        goal: 'Review the content',
        role_id: 'creator',
        status: 'COMPLETED',
        version: 3,
        tasks: [],
      });
    if (path.includes('/artifacts?')) return respond(artifacts);
    if (path.endsWith('/run')) return respond(null);
    if (path === '/artifacts/old/content') {
      oldSignal = options?.signal as AbortSignal;
      return { ok: true, text: () => oldBody } as Response;
    }
    if (path === '/artifacts/current/content') return new Response('Current reviewed text');
    return respond([]);
  });
  vi.stubGlobal('fetch', fetchMock);
  const user = userEvent.setup();
  render(<MissionDetail id="mission" canWrite={false} onChange={async () => {}} />);
  await user.click(await screen.findByRole('tab', { name: /artifacts/ }));
  await waitFor(() => expect(oldSignal).toBeDefined());
  await user.selectOptions(screen.getByLabelText('Result artifact'), 'current');
  expect(await screen.findByText('Current reviewed text')).toBeInTheDocument();
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => finishOldBody('Obsolete artifact text'));
  expect(screen.queryByText('Obsolete artifact text')).not.toBeInTheDocument();
  expect(screen.getByText('Current reviewed text')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Download current.md' })).toHaveAttribute(
    'href',
    '/artifacts/current/content',
  );
  expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
});

test.each([true, false, undefined])(
  'planned review requires explicit passing tests (%s) and keeps denial available',
  async (passed) => {
    const respond = (data: unknown) => new Response(JSON.stringify(data));
    const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/missions/planned' || options?.method === 'POST')
        return respond({
          id: 'planned',
          goal: 'Fix addition while preserving tests',
          role_id: 'developer',
          status: 'WAITING_APPROVAL',
          version: 7,
          tasks: [
            {
              id: 'verify',
              title: 'Verify fix',
              agent_id: 'registered_tester',
              status: 'WAITING_APPROVAL',
              attempts: 1,
              dependencies: [],
              outputs: passed === undefined ? {} : { passed },
              error: null,
              requires_passed_tests: true,
            },
          ],
          planning: {
            planner_id: 'registered_planner',
            rationale: 'Investigate the operator and verify the fix',
            constraints: ['Preserve tests'],
            objectives: { verify: 'Run configured tests' },
          },
        });
      if (path.endsWith('/approvals'))
        return respond([
          {
            id: 'review',
            task_id: 'verify',
            status: 'PENDING',
            payload_digest: 'digest',
          },
        ]);
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    render(<MissionDetail id="planned" canWrite onChange={async () => {}} />);
    await user.click(await screen.findByText('Inspect validated Developer plan'));
    expect(screen.getByText('Investigate the operator and verify the fix')).toBeVisible();
    const accept = screen.getByRole('button', { name: 'Accept result' });
    if (passed === true) expect(accept).toBeEnabled();
    else {
      expect(accept).toBeDisabled();
      expect(screen.getByText(/Tests must explicitly pass before/)).toBeVisible();
      expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
    }
    await user.click(screen.getByRole('button', { name: 'Deny result' }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/approvals/review/decision',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"decision":"deny"'),
        }),
      ),
    );
  },
);
