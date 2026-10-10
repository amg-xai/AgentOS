import { configure, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from '../src/App';
import type { Activity, Approval, Artifact, Mission } from '../src/api';
import { createRoot, inspectPng, readSources, removeRoot, sha256, startServer } from './server.mjs';

configure({ asyncUtilTimeout: 10000 });
const source = '  AgentOS keeps local history.\nCafé 日本語\n';

// Actual React and HTTP services; only model responses are injected by the server.
test.each(['script', 'thumbnail', 'invalid evidence', 'invalid layout'])(
  'continuous sourced Creator: %s',
  async (scenario) => {
    const root = await createRoot();
    let server: Awaited<ReturnType<typeof startServer>> | undefined;
    let view: ReturnType<typeof render> | undefined;
    const user = userEvent.setup();
    const thumbnail = scenario !== 'script';
    const goal = `Explain local AgentOS history (${scenario})`;
    const json = async <T,>(route: string): Promise<T> => {
      const response = await server!.request(route);
      expect(response.ok).toBe(true);
      return response.json();
    };
    const mount = () => {
      vi.stubGlobal('fetch', server!.fetch);
      view = render(<App />);
    };
    const openHistory = async () => {
      const history = (await screen.findByRole('heading', { name: 'Missions' })).closest(
        'section',
      )!;
      await user.click(
        await within(history).findByRole('button', {
          name: new RegExp(goal.replace(/[()]/g, '\\$&')),
        }),
      );
    };
    try {
      server = await startServer(root);
      const originals = await readSources(root);
      mount();
      await user.selectOptions(await screen.findByLabelText('Workflow'), 'creator');
      await user.click(screen.getByRole('button', { name: '+ New mission' }));
      await user.click(screen.getByLabelText('What should your video script cover?'));
      await user.paste(goal);
      await user.click(screen.getByRole('button', { name: 'Add source' }));
      const label = screen.getByLabelText('Source label (source_1)');
      await user.click(screen.getByRole('button', { name: 'Create mission' }));
      expect((label as HTMLInputElement).validity.valueMissing).toBe(true);
      expect(await json<Mission[]>('/missions')).toEqual([]);
      await user.type(label, 'Local history note');
      await user.click(screen.getByLabelText('Source text (source_1)'));
      await user.paste(source);
      const checkbox = screen.getByRole('checkbox', { name: /Include a graphic thumbnail/ });
      expect(checkbox).not.toBeChecked();
      if (thumbnail) await user.click(checkbox);
      await user.click(screen.getByRole('button', { name: 'Create mission' }));
      await user.click(await screen.findByText('Inspect validated Creator plan'));
      const [created] = await json<Mission[]>('/missions');
      const base = `/missions/${created.id}`;
      expect(created.goal).toBe(goal);
      expect(created.planning?.contract_version).toBe(thumbnail ? 2 : 1);
      expect(created.planning?.constraints).toEqual(['Use only supplied facts']);
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
      if (scenario.startsWith('invalid')) {
        expect(mission.status).toBe('FAILED');
        const failed = scenario === 'invalid evidence' ? 'evidence' : 'image';
        expect(mission.tasks.find((task) => task.id === failed)?.status).toBe('FAILED');
        expect(mission.tasks.filter((task) => task.attempts > 0)).toHaveLength(
          scenario === 'invalid evidence' ? 1 : 5,
        );
        expect(await json<Approval[]>(`${base}/approvals`)).toEqual([]);
        expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument();
        expect(
          (await json<Artifact[]>(`${base}/artifacts`)).some((a) => a.name === 'thumbnail.png'),
        ).toBe(false);
        expect(await readSources(root)).toEqual(originals);
        return;
      }
      expect(mission.status).toBe('WAITING_APPROVAL');
      expect(mission.tasks.every((task) => task.outputs?.passed === undefined)).toBe(true);
      const observations = await server.observations();
      expect(observations[0].inputs.sources).toEqual([
        { id: 'source_1', label: 'Local history note' },
      ]);
      for (const observation of observations.slice(1)) {
        expect(observation.inputs.goal).toBe(goal);
        expect(observation.inputs.constraints).toEqual(created.planning!.constraints);
        expect(observation.inputs.sources).toEqual([
          { id: 'source_1', label: 'Local history note', body: source },
        ]);
      }
      let [approval] = await json<Approval[]>(`${base}/approvals`);
      const oldApproval = approval;
      const artifacts = await json<Artifact[]>(`${base}/artifacts`);
      let owned = artifacts.filter((a) => approval.payload?.artifact_refs?.includes(a.id));
      expect(owned.map((a) => a.name).sort()).toEqual(
        (thumbnail
          ? [
              'thumbnail.png',
              'thumbnail-layout.json',
              'reviewed-script.md',
              'reviewed-outline.md',
              'reviewed-research.json',
              'reviewed-sources.json',
            ]
          : ['script.md', 'reviewed-outline.md', 'reviewed-research.json', 'reviewed-sources.json']
        ).sort(),
      );
      const contents = new Map<string, Uint8Array>();
      const text = (name: string) => new TextDecoder().decode(contents.get(name)!);
      for (const artifact of owned) {
        const response = await server.request(`/artifacts/${artifact.id}/content`);
        expect(response.ok).toBe(true);
        const bytes = new Uint8Array(await response.arrayBuffer());
        expect(sha256(bytes)).toBe(artifact.sha256);
        contents.set(artifact.name, bytes);
      }
      expect(JSON.parse(text('reviewed-sources.json'))[0].body).toBe(source);
      const research = mission.tasks.find((t) => t.id === 'evidence')!.outputs;
      expect(JSON.parse(text('reviewed-research.json'))).toEqual(research);
      expect(text('reviewed-outline.md')).toBe(
        mission.tasks.find((t) => t.id === 'polish')!.outputs!.outline,
      );
      expect(text(thumbnail ? 'reviewed-script.md' : 'script.md')).toBe(
        mission.tasks.find((t) => t.id === 'deliver')!.outputs!.script,
      );
      await user.click(await screen.findByRole('button', { name: 'Inspect artifacts →' }));
      const primary = owned.find((a) => a.name === (thumbnail ? 'thumbnail.png' : 'script.md'))!;
      expect(await screen.findByRole('link', { name: `Download ${primary.name}` })).toHaveAttribute(
        'download',
        primary.name,
      );
      if (thumbnail) {
        const upstream = mission.tasks.filter((t) => t.id !== 'image');
        const image = await screen.findByRole('img', {
          name: 'Creator graphic thumbnail for human review',
        });
        expect(image).toHaveAttribute('src', `/artifacts/${primary.id}/content`);
        // Independently decode real bytes with the existing backend Pillow dependency.
        const { size, mode, colors } = inspectPng(contents.get('thumbnail.png')!);
        expect(size).toEqual([1280, 720]);
        expect(mode).toBe('RGB');
        expect(colors).toBeGreaterThan(3);
        const receipt = JSON.parse(text('thumbnail-layout.json'));
        expect(receipt.receipt.png_sha256).toBe(primary.sha256);
        await user.selectOptions(
          screen.getByLabelText('Result artifact'),
          owned.find((a) => a.name === 'reviewed-script.md')!.id,
        );
        await screen.findByText(/A goal becomes a mission/);
        const deny = screen.getByRole('button', { name: 'Deny result' });
        await waitFor(() => expect(deny).toBeEnabled());
        await user.click(deny);
        await waitFor(async () => expect((await json<Mission>(base)).status).toBe('FAILED'));
        await user.click(screen.getByRole('tab', { name: /tasks/ }));
        const retry = await screen.findByRole('button', { name: 'Retry task' });
        await waitFor(() => expect(retry).toBeEnabled());
        await user.click(retry);
        const rerun = await screen.findByRole('button', { name: 'Run mission' });
        await waitFor(() => expect(rerun).toBeEnabled());
        await user.click(rerun);
        await waitFor(async () =>
          expect((await json<Mission>(base)).status).toBe('WAITING_APPROVAL'),
        );
        mission = await json<Mission>(base);
        expect(mission.tasks.filter((t) => t.id !== 'image')).toEqual(upstream);
        expect(mission.tasks.filter((t) => t.id !== 'image').every((t) => t.attempts === 1)).toBe(
          true,
        );
        expect(mission.tasks.find((t) => t.id === 'image')?.attempts).toBe(2);
        expect(
          (await server.observations()).slice(observations.length).map((o) => o.agent),
        ).toEqual(['creator_thumbnail']);
        [approval] = await json<Approval[]>(`${base}/approvals`);
        expect(approval.id).not.toBe(oldApproval.id);
        const previous = owned;
        owned = (await json<Artifact[]>(`${base}/artifacts`)).filter((a) =>
          approval.payload?.artifact_refs?.includes(a.id),
        );
        expect(owned.map((a) => a.name).sort()).toEqual(previous.map((a) => a.name).sort());
        expect(owned.every((a) => !previous.some((old) => old.id === a.id))).toBe(true);
        for (const artifact of [...previous, ...owned]) {
          const response = await server.request(`/artifacts/${artifact.id}/content`);
          expect(response.ok).toBe(true);
          const bytes = new Uint8Array(await response.arrayBuffer());
          expect(bytes).toEqual(contents.get(artifact.name));
          expect(sha256(bytes)).toBe(artifact.sha256);
        }
        const stale = await server.request(`/approvals/${oldApproval.id}/decision`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            decision: 'approve',
            expected_version: mission.version,
            payload_digest: oldApproval.payload_digest,
          }),
        });
        expect(stale.status).toBe(409);
      }
      expect(screen.queryByText('Tests passed')).not.toBeInTheDocument();
      const finalObservations = await server.observations();
      const activity = await json<Activity[]>(`${base}/events`);
      view!.unmount();
      view = undefined;
      await server.stop();
      server = await startServer(root);
      expect(await json<Mission>(base)).toEqual(mission);
      expect(await json<Activity[]>(`${base}/events`)).toEqual(activity);
      expect(await json<Approval[]>(`${base}/approvals`)).toEqual([approval]);
      expect(await server.observations()).toEqual(finalObservations);
      for (const artifact of owned) {
        const response = await server.request(`/artifacts/${artifact.id}/content`);
        expect(new Uint8Array(await response.arrayBuffer())).toEqual(contents.get(artifact.name));
      }
      mount();
      await openHistory();
      const accept = await screen.findByRole('button', { name: 'Accept result' });
      await waitFor(() => expect(accept).toBeEnabled());
      await user.click(accept);
      await waitFor(async () => expect((await json<Mission>(base)).status).toBe('COMPLETED'));
      mission = await json<Mission>(base);
      const replay = await server.request(`/approvals/${approval.id}/decision`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          decision: 'approve',
          expected_version: mission.version,
          payload_digest: approval.payload_digest,
        }),
      });
      expect(replay.status).toBe(409);
      view!.unmount();
      view = undefined;
      await server.stop();
      server = await startServer(root);
      expect(await json<Mission>(base)).toEqual(mission);
      expect((await json<Approval>(`/approvals/${approval.id}`)).status).toBe('APPROVED');
      expect(await server.observations()).toEqual(finalObservations);
      expect(await readSources(root)).toEqual(originals);
    } finally {
      view?.unmount();
      vi.unstubAllGlobals();
      await server?.stop();
      await removeRoot(root);
    }
  },
);
