import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { MissionDetail } from './MissionDetail';

test.each([true, false])(
  'revision requires feedback and an explicit run (operator=%s)',
  async (canWrite) => {
    let reset = false;
    let reject = true;
    const respond = (value: unknown, status = 200) =>
      new Response(JSON.stringify(value), { status });
    const fetchMock = vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/missions/revise/patch-revision') {
        if (options?.method === 'POST') {
          expect(JSON.parse(options.body as string)).toEqual({
            expected_version: 12,
            approval_id: 'denied',
            payload_digest: 'digest',
            feedback: 'Correct addition',
          });
          if (reject) return respond({ detail: 'Stale denied result' }, 409);
          reset = true;
        }
        return respond({
          allowed: true,
          remaining: 2,
          approval_id: 'denied',
          payload_digest: 'digest',
        });
      }
      if (path === '/missions/revise')
        return respond({
          id: 'revise',
          goal: 'Fix addition',
          role_id: 'developer',
          version: reset ? 13 : 12,
          status: reset ? 'RUNNING' : 'FAILED',
          planning: {
            contract_version: 2,
            planner_id: 'planner',
            rationale: 'Preserve tests',
            constraints: [],
            objectives: {},
          },
          tasks: [
            {
              id: 'verify',
              title: 'Verify',
              agent_id: 'testing',
              attempts: 1,
              dependencies: [],
              status: reset ? 'PENDING' : 'FAILED',
              outputs: reset ? null : { passed: false },
              requires_passed_tests: true,
            },
          ],
          developer_revisions: reset ? [{ number: 1, feedback: 'Correct addition' }] : [],
        });
      if (path.endsWith('/run')) return respond(null);
      return respond([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<MissionDetail id="revise" canWrite={canWrite} onChange={async () => {}} />);
    const button = await screen.findByRole('button', { name: 'Revise patch' });
    expect(button).toBeDisabled();
    const feedback = screen.getByLabelText('Patch revision feedback');
    expect(feedback).toHaveAttribute('maxlength', '2000');
    if (!canWrite) {
      expect(feedback).toBeDisabled();
      expect(fetchMock.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
      return;
    }
    const user = userEvent.setup();
    await user.type(feedback, 'Correct addition');
    await user.click(button);
    expect(await screen.findByText('Stale denied result')).toBeVisible();
    expect(feedback).toHaveValue('Correct addition');
    reject = false;
    await user.click(button);
    expect(await screen.findByRole('button', { name: 'Run mission' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Revise patch' })).not.toBeInTheDocument();
    expect(screen.getByText('Inspect patch revision evidence')).toBeVisible();
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(
          ([path, options]) => path.endsWith('/run') && options?.method === 'POST',
        ),
      ).toHaveLength(0),
    );
  },
);
