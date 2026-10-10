import { configure, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from '../src/App';
import type { Approval, Mission } from '../src/api';
import { createRoot, readSources, removeRoot, startServer } from './server.mjs';

configure({ asyncUtilTimeout: 10000 });

// Actual UI and isolated HTTP backend/tools/storage; only model and embeddings
// are injected. This verifies contracts, never real semantic/model quality.
test('shared semantic evidence across three approved profiles survives restart', async () => {
  const root = await createRoot();
  let server: Awaited<ReturnType<typeof startServer>> | undefined;
  let view: ReturnType<typeof render> | undefined;
  const user = userEvent.setup();
  const post = async <T,>(route: string, body: object): Promise<T> => {
    const response = await server!.request(route, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    expect(response.ok, `${route}: ${response.status}`).toBe(true);
    return response.json();
  };
  const get = async <T,>(route: string): Promise<T> => {
    const response = await server!.request(route);
    expect(response.ok).toBe(true);
    return response.json();
  };
  const openMemory = async () => {
    await user.click(await screen.findByRole('button', { name: /Workspace memory/ }));
    await user.click(await screen.findByRole('button', { name: 'Open semantic search' }));
    await screen.findByLabelText('Meaning to find');
  };
  const mount = () => {
    vi.stubGlobal('fetch', server!.fetch);
    view = render(<App />);
  };
  try {
    server = await startServer(root);
    const original = await readSources(root);
    const missions: Mission[] = [];
    for (const profile of ['developer', 'creator', 'student']) {
      const body = {
        goal: `addition ${profile} acceptance`,
        ...(profile !== 'developer'
          ? {
              sources: [
                {
                  id: 'source_1',
                  label: 'Study material',
                  body:
                    profile === 'creator'
                      ? 'AgentOS keeps local history.'
                      : 'Stacks use LIFO. Queues use FIFO. Push and pop act on stacks; enqueue and dequeue act on queues.',
                },
              ],
            }
          : {}),
        ...(profile === 'creator' ? { include_thumbnail: true } : {}),
      };
      let mission = await post<Mission>(`/workflows/${profile}`, body);
      const base = `/missions/${mission.id}`;
      await post(`${base}/run`, { expected_version: mission.version });
      await waitFor(
        async () => {
          mission = await get<Mission>(base);
          expect(mission.status, JSON.stringify(mission.tasks.filter((task) => task.error))).toBe(
            'WAITING_APPROVAL',
          );
        },
        { timeout: 45000 },
      );
      const [approval] = await get<Approval[]>(`${base}/approvals`);
      // Pending bundles are excluded before a real, explicit approval decision.
      await post('/memory/semantic/index', {});
      const pending = await post<{ hits: unknown[] }>('/memory/semantic/search', {
        query: 'sum',
        kind: 'artifact',
        mission_id: mission.id,
      });
      expect(pending.hits).toEqual([]);
      mission = await post<Mission>(`/approvals/${approval.id}/decision`, {
        decision: 'approve',
        expected_version: mission.version,
        payload_digest: approval.payload_digest,
      });
      expect(mission.status).toBe('COMPLETED');
      missions.push(mission);
    }
    await post('/memory', { title: 'addition memory', content: 'Preserve negative sums' });
    await post('/memory', { title: 'Photography', content: 'Unrelated image composition' });
    mount();
    await openMemory();
    await user.click(await screen.findByRole('button', { name: 'Rebuild semantic index' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Rebuild semantic index' })).toBeEnabled(),
    );
    await user.type(screen.getByLabelText('Meaning to find'), 'sum');
    await user.selectOptions(screen.getByLabelText('Memory source'), 'note');
    await user.click(screen.getByRole('button', { name: 'Search semantic memory' }));
    await within(screen.getByRole('region', { name: 'Semantic memory search' })).findByRole(
      'heading',
      { name: 'addition memory' },
    );
    expect(
      within(screen.getByRole('region', { name: 'Semantic memory search' })).queryByRole(
        'heading',
        { name: 'Photography' },
      ),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open source note' }));
    await screen.findByRole('region', { name: 'Source note' });
    expect(
      within(screen.getByRole('region', { name: 'Source note' })).getByText(
        'Preserve negative sums',
      ),
    ).toBeInTheDocument();
    const before = await get<{ generation: number }>('/memory/semantic/status');
    view!.unmount();
    view = undefined;
    await server.stop();
    server = undefined;
    server = await startServer(root);
    expect((await get<{ generation: number }>('/memory/semantic/status')).generation).toBe(
      before.generation,
    );
    expect(await readSources(root)).toEqual(original);
    mount();
    await openMemory();
    await user.type(screen.getByLabelText('Meaning to find'), 'evidence');
    await user.selectOptions(screen.getByLabelText('Memory source'), 'artifact');
    for (const profile of ['developer', 'creator', 'student']) {
      await user.selectOptions(screen.getByLabelText('Memory profile'), profile);
      await user.click(screen.getByRole('button', { name: 'Search semantic memory' }));
      await screen.findAllByText(/approved artifact · similarity/);
      await user.click(screen.getAllByRole('button', { name: 'Inspect source artifact' })[0]);
      await screen.findByRole('heading', { name: 'Linked artifact' });
      await screen.findByRole('link', { name: /^Download / });
      await user.click(screen.getByRole('button', { name: 'Close preview' }));
    }
    await user.clear(screen.getByLabelText('Meaning to find'));
    await user.type(screen.getByLabelText('Meaning to find'), 'sum');
    await user.selectOptions(screen.getByLabelText('Memory source'), 'mission');
    await user.selectOptions(screen.getByLabelText('Memory profile'), 'developer');
    await user.click(screen.getByRole('button', { name: 'Search semantic memory' }));
    await screen.findByText(/stored outcome · similarity/);
    await user.click(screen.getByRole('button', { name: 'Open source mission' }));
    await screen.findByRole('heading', { name: missions[0].goal });
    expect(await readSources(root)).toEqual(original);
  } finally {
    view?.unmount();
    await server?.stop();
    await removeRoot(root);
  }
}, 180000);
