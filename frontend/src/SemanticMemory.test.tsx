import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { SemanticMemory } from './SemanticMemory';

const status = { configured: true, generation: 1, indexed_chunks: 2, omitted_sources: 0 };
const hit = {
  kind: 'mission',
  id: 'mission-1',
  title: 'Stored addition outcome',
  profile: 'developer',
  mission_id: 'mission-1',
  digest: 'a'.repeat(64),
  evidence: 'stored_outcome',
  start: 0,
  end: 20,
  excerpt: 'Tests explicitly passed',
  similarity: 0.9,
};
const results = {
  generation: 1,
  indexed_chunks: 2,
  omitted_sources: 0,
  stale_sources: 1,
  invalid_sources: 0,
  hits: [hit],
};

test('semantic search submits explicitly with filters and opens source mission', async () => {
  const requests: { path: string; body?: unknown }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      requests.push({ path, body: options?.body ? JSON.parse(String(options.body)) : undefined });
      return new Response(JSON.stringify(path.endsWith('/status') ? status : results));
    }),
  );
  const open = vi.fn();
  render(<SemanticMemory canWrite={false} onOpenMission={open} />);
  await screen.findByText(/Index generation 1/);
  expect(screen.getByRole('button', { name: 'Rebuild semantic index' })).toBeDisabled();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Meaning to find'), 'sum');
  await user.selectOptions(screen.getByLabelText('Memory profile'), 'developer');
  expect(requests).toHaveLength(1);
  await user.click(screen.getByRole('button', { name: 'Search semantic memory' }));
  await screen.findByText('Stored addition outcome');
  expect(requests[1]).toEqual({
    path: '/memory/semantic/search',
    body: { query: 'sum', profile: 'developer', mission_id: null, kind: null },
  });
  await user.click(screen.getByRole('button', { name: 'Open source mission' }));
  expect(open).toHaveBeenCalledWith('mission-1');
  expect(screen.getByText(/similarity 0.900/)).toBeInTheDocument();
});

test('disabled embeddings and empty index remain distinct from failures', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async (path: string) =>
        new Response(
          JSON.stringify(
            path.endsWith('/status')
              ? { ...status, configured: false, indexed_chunks: 0 }
              : { ...results, indexed_chunks: 0, hits: [] },
          ),
        ),
    ),
  );
  render(<SemanticMemory canWrite />);
  await screen.findByText(/Local embeddings are disabled/);
  expect(screen.getByRole('button', { name: 'Rebuild semantic index' })).toBeDisabled();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Meaning to find'), 'sum');
  await user.click(screen.getByRole('button', { name: 'Search semantic memory' }));
  await screen.findByText(/The semantic index is empty/);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('rebuild failure reports an error and preserves visible index generation', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) =>
      path.endsWith('/status')
        ? new Response(JSON.stringify(status))
        : new Response(JSON.stringify({ detail: 'Local embedding request failed' }), {
            status: 502,
          }),
    ),
  );
  render(<SemanticMemory canWrite />);
  await screen.findByText(/Index generation 1/);
  await userEvent.setup().click(screen.getByRole('button', { name: 'Rebuild semantic index' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Local embedding request failed');
  expect(screen.getByText(/Index generation 1/)).toBeInTheDocument();
});

test('changing filters cancels obsolete semantic results', async () => {
  let finish!: (response: Response) => void;
  let signal: AbortSignal | undefined;
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path.endsWith('/status')) return new Response(JSON.stringify(status));
      signal = options?.signal as AbortSignal;
      return new Promise<Response>((resolve) => {
        finish = resolve;
      });
    }),
  );
  render(<SemanticMemory canWrite />);
  await screen.findByText(/Index generation 1/);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Meaning to find'), 'sum');
  await user.click(screen.getByRole('button', { name: 'Search semantic memory' }));
  await user.selectOptions(screen.getByLabelText('Memory source'), 'note');
  expect(signal?.aborted).toBe(true);
  await act(async () => finish(new Response(JSON.stringify(results))));
  expect(screen.queryByText('Stored addition outcome')).not.toBeInTheDocument();
});
