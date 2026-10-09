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

test('failed initial memory load is unavailable rather than an empty workspace', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: 'Workspace history unavailable' }), { status: 500 }),
    ),
  );
  render(<Memory canWrite={false} />);
  expect(await screen.findByText('Notes unavailable')).toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('Workspace history unavailable');
  expect(screen.queryByText('A fresh workspace')).not.toBeInTheDocument();
  expect(screen.queryByText('No matching notes')).not.toBeInTheDocument();
});

test('failed searches do not present earlier notes as matching the new query and can recover', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      if (path.endsWith('query=x'))
        return new Response(JSON.stringify({ detail: 'Search unavailable' }), { status: 500 });
      return new Response(
        JSON.stringify([
          {
            id: 'note',
            title: 'Earlier query result',
            content: 'Saved context',
            artifact_refs: [],
            created_at: '2026-10-09T00:00:00Z',
          },
        ]),
      );
    }),
  );
  render(<Memory canWrite={false} />);
  await screen.findByText('Earlier query result');
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Search notes'), 'x');
  expect(await screen.findByText('Notes unavailable')).toBeInTheDocument();
  expect(screen.queryByText('Earlier query result')).not.toBeInTheDocument();
  expect(screen.queryByText('No matching notes')).not.toBeInTheDocument();
  await user.clear(screen.getByLabelText('Search notes'));
  expect(await screen.findByText('Earlier query result')).toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});
