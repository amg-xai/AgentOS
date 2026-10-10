import { configure, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from '../src/App';
import type { Approval, Artifact, Mission } from '../src/api';
import { createRoot, readSources, removeRoot, startServer } from './server.mjs';

const source =
  '  Stacks use LIFO. Queues use FIFO.\nPush and pop act on stacks; enqueue and dequeue act on queues. Café 日本語\n';

configure({ asyncUtilTimeout: 10000 });

// React calls the real loopback API. Only the structured model transport is injected.
test.each(['quiz', 'focus', 'invalid evidence'])(
  'continuous sourced Student: %s',
  async (scenario) => {
    const root = await createRoot();
    let server: Awaited<ReturnType<typeof startServer>> | undefined;
    let view: ReturnType<typeof render> | undefined;
    const user = userEvent.setup();
    const goal = `Prepare my DSA exam (${scenario})`;
    const json = async <T,>(route: string): Promise<T> => {
      const response = await server!.request(route);
      expect(response.ok).toBe(true);
      return response.json();
    };
    const mount = () => {
      vi.stubGlobal('fetch', server!.fetch);
      view = render(<App />);
    };
    try {
      server = await startServer(root);
      const originals = await readSources(root);
      mount();
      await user.selectOptions(await screen.findByLabelText('Workflow'), 'student');
      await user.click(await screen.findByRole('button', { name: '+ New mission' }));
      await user.click(
        screen.getByLabelText('What material should your study notes and quiz cover?'),
      );
      await user.paste(goal);
      await user.click(screen.getByRole('button', { name: 'Add source' }));
      const label = screen.getByLabelText('Source label (source_1)');
      await user.click(screen.getByRole('button', { name: 'Create mission' }));
      expect((label as HTMLInputElement).validity.valueMissing).toBe(true);
      expect(await json<Mission[]>('/missions')).toEqual([]);
      await user.type(label, 'Course excerpt');
      await user.click(screen.getByLabelText('Source text (source_1)'));
      await user.paste(source);
      if (scenario === 'focus') await user.click(screen.getByLabelText('Include a study plan'));
      await user.click(screen.getByRole('button', { name: 'Create mission' }));
      await user.click(await screen.findByText('Inspect validated Student plan'));
      const [created] = await json<Mission[]>('/missions');
      const base = `/missions/${created.id}`;
      expect(created.planning?.contract_version).toBe(2);
      for (const task of created.tasks) {
        const article = screen.getByRole('article', {
          name: `Task detail: ${task.title} (${task.id})`,
        });
        expect(within(article).getByText(task.agent_id)).toBeVisible();
        expect(article).toHaveTextContent(created.planning!.objectives[task.id]);
        for (const binding of Object.values(task.input_bindings ?? {}))
          expect(task.dependencies).toContain(binding.task_id);
      }
      const run = await screen.findByRole('button', { name: 'Run mission' });
      await waitFor(() => expect(run).toBeEnabled());
      await user.click(run);
      await waitFor(
        async () => {
          expect(['WAITING_APPROVAL', 'FAILED']).toContain((await json<Mission>(base)).status);
        },
        { timeout: 15000 },
      );
      let mission = await json<Mission>(base);
      if (scenario === 'invalid evidence') {
        expect(mission.tasks.find((task) => task.id === 'evidence')?.status).toBe('FAILED');
        expect(mission.tasks.filter((task) => task.attempts > 0)).toHaveLength(1);
        expect(await json<Approval[]>(`${base}/approvals`)).toEqual([]);
        expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument();
        return;
      }
      expect(mission.status).toBe('WAITING_APPROVAL');
      expect(mission.tasks.every((task) => task.outputs?.passed === undefined)).toBe(true);
      const [approval] = await json<Approval[]>(`${base}/approvals`);
      const observations = await server.observations();
      expect(approval.payload).toHaveProperty('plan_digest');
      const artifacts = await json<Artifact[]>(`${base}/artifacts`);
      const owned = artifacts.filter((artifact) =>
        approval.payload?.artifact_refs?.includes(artifact.id),
      );
      expect(owned).toHaveLength(scenario === 'focus' ? 11 : 8);
      const copies: Record<string, string> = {};
      for (const artifact of owned) {
        const response = await server.request(`/artifacts/${artifact.id}/content`);
        expect(response.ok).toBe(true);
        copies[artifact.name] = await response.text();
      }
      expect(JSON.parse(copies['reviewed-sources.json'])[0].body).toBe(source);
      expect(JSON.parse(copies['reviewed-study-summary.json']).topics[0].evidence_refs).toEqual([
        1, 2, 3,
      ]);
      expect(JSON.parse(copies['reviewed-quiz-provenance.json'])).toEqual([[1], [1], [1]]);
      await user.click(screen.getByRole('tab', { name: /artifacts/ }));
      const summaryArtifact = owned.find(
        (artifact) => artifact.name === 'reviewed-study-summary.json',
      )!;
      await user.selectOptions(screen.getByLabelText('Result artifact'), summaryArtifact.id);
      await screen.findByText(/Compare removal order and operations/);
      view!.unmount();
      await server.stop();
      server = await startServer(root);
      expect(await json<Mission>(base)).toEqual(mission);
      expect(await json<Approval[]>(`${base}/approvals`)).toEqual([approval]);
      expect(await server.observations()).toEqual(observations);
      mount();
      const history = (await screen.findByRole('heading', { name: 'Missions' })).closest(
        'section',
      )!;
      await user.click(
        await within(history).findByRole('button', {
          name: new RegExp(goal.replace(/[()]/g, '\\$&')),
        }),
      );
      const accept = await screen.findByRole('button', { name: 'Accept result' });
      await waitFor(() => expect(accept).toBeEnabled());
      await user.click(accept);
      await waitFor(async () => expect((await json<Mission>(base)).status).toBe('COMPLETED'));
      mission = await json<Mission>(base);
      view!.unmount();
      view = undefined;
      await server.stop();
      server = await startServer(root);
      expect(await json<Mission>(base)).toEqual(mission);
      expect(await server.observations()).toEqual(observations);
      expect((await json<Approval>(`/approvals/${approval.id}`)).status).toBe('APPROVED');
      expect(await readSources(root)).toEqual(originals);
    } finally {
      view?.unmount();
      vi.unstubAllGlobals();
      await server?.stop();
      await removeRoot(root);
    }
  },
);
