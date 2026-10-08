import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { Memory } from './Memory';

test('a canceled memory search cannot replace newer results', async () => {
  let finishOldSearch!: (response: Response) => void;
  let oldSignal: AbortSignal | undefined;
  const oldSearch = new Promise<Response>((resolve) => {
    finishOldSearch = resolve;
  });
  const note = (title: string) => ({
    id: title,
    title,
    content: 'Saved workspace context',
    artifact_refs: [],
    created_at: '2026-10-09T00:00:00Z',
  });
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path === '/memory?limit=100&query=a') {
        oldSignal = options?.signal as AbortSignal;
        return oldSearch;
      }
      return new Response(
        JSON.stringify(path.endsWith('query=ab') ? [note('Current matching note')] : []),
      );
    }),
  );
  render(<Memory canWrite={false} />);
  await screen.findByText('A fresh workspace');
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Search notes'), 'ab');
  await screen.findByText('Current matching note');
  expect(oldSignal?.aborted).toBe(true);
  // Simulate a response that completes despite transport cancellation.
  await act(async () =>
    finishOldSearch(new Response(JSON.stringify([note('Obsolete matching note')]))),
  );
  expect(screen.getByText('Current matching note')).toBeInTheDocument();
  expect(screen.queryByText('Obsolete matching note')).not.toBeInTheDocument();
});
