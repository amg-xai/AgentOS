import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test, vi } from 'vitest';
import { App } from '../src/App';
import type { Activity, Approval, Artifact, Mission, Status } from '../src/api';
import { createRoot, readSources, removeRoot, startServer } from './server.mjs';

const reviewNames = [
  'tested.diff',
  'test-report.txt',
  'reviewed-baseline-report.txt',
  'reviewed-issue.json',
  'reviewed-issue.md',
];

// Only model transport is injected. UI fetches real HTTP responses, and Git/tests,
// persistence, artifact integrity, approvals and revisions use production services.
test.each(['passing', 'two revisions', 'exhaust revisions'] as const)(
  'continuous normal Developer v3: %s',
  async (scenario) => {
    const root = await createRoot();
    let server: Awaited<ReturnType<typeof startServer>> | undefined;
    let view: ReturnType<typeof render> | undefined;
    const user = userEvent.setup();
    const goal = `Fix calculator addition (${scenario}). Preserve existing test assertions.`;
    const json = async <T,>(route: string): Promise<T> => {
      const response = await server!.request(route);
      expect(response.ok).toBe(true);
      return response.json();
    };
    const mount = () => {
      vi.stubGlobal('fetch', server!.fetch);
      view = render(<App />);
    };
    const reopen = async (id: string) => {
      view!.unmount();
      await server!.stop();
      server = await startServer(root);
      mount();
      const history = (
        await screen.findByRole('heading', { name: 'Missions' }, { timeout: 10000 })
      ).closest('section')!;
      await user.click(
        await within(history).findByRole(
          'button',
          { name: /Fix calculator addition/ },
          { timeout: 10000 },
        ),
      );
      await screen.findByText('Inspect validated Developer plan');
      expect((await json<Mission>(`/missions/${id}`)).goal).toBe(goal);
    };
    try {
      server = await startServer(root);
      const status = await json<Status>('/status');
      expect(status.execution_mode).toBe('live'); // Existing normal-mode enum, not live transport.
      expect(status.model).toBe('INJECTED ACCEPTANCE TRANSPORT');
      expect(status.workflows?.map((workflow) => workflow.role_id).sort()).toEqual([
        'creator',
        'developer',
        'student',
      ]);
      const originals = await readSources(root);
      mount();
      await user.selectOptions(await screen.findByLabelText('Workflow'), 'developer');
      await user.click(await screen.findByRole('button', { name: '+ New mission' }));
      await user.click(screen.getByLabelText('What should your agents investigate and fix?'));
      await user.paste(goal);
      await user.click(screen.getByRole('button', { name: 'Create mission' }));
      await user.click(await screen.findByText('Inspect validated Developer plan'));
      expect(screen.getByText('Preserve existing test assertions')).toBeVisible();
      const [created] = await json<Mission[]>('/missions');
      const base = `/missions/${created.id}`;
      expect(created.planning?.contract_version).toBe(3);
      expect(created.goal).toBe(goal);
      for (const task of created.tasks) {
        const article = screen.getByRole('article', {
          name: `Task detail: ${task.title} (${task.id})`,
        });
        expect(within(article).getByText(task.agent_id)).toBeVisible();
        expect(article).toHaveTextContent(created.planning!.objectives[task.id]);
        await user.click(within(article).getByText('Inspect dependency inputs'));
        for (const [input, binding] of Object.entries(task.input_bindings ?? {})) {
          expect(article).toHaveTextContent(`${input} receives ${binding.output_key}`);
          expect(task.dependencies).toContain(binding.task_id);
        }
      }
      const run = async (passes: boolean) => {
        const button = await screen.findByRole('button', { name: 'Run mission' });
        await waitFor(() => expect(button).toBeEnabled());
        await user.click(button);
        await screen.findByText(passes ? 'Tests passed' : 'Tests failed', {}, { timeout: 20000 });
        expect(screen.getByText('Baseline tests failed')).toBeVisible();
        const mission = await json<Mission>(base);
        expect(mission.status).toBe('WAITING_APPROVAL');
        const baseline = mission.tasks.find((task) => task.id === 'baseline')!;
        expect(baseline.status).toBe('COMPLETED');
        expect(baseline.outputs?.baseline_passed).toBe(false);
        expect(baseline.outputs?.baseline_report).toContain('Ran 3 tests');
        expect(baseline.outputs?.baseline_report).toContain('FAILED (failures=2)');
        expect(mission.tasks.find((task) => task.id === 'verify')?.outputs?.passed).toBe(passes);
        return mission;
      };
      let mission = await run(scenario === 'passing');
      const initialEvidence = mission.tasks.filter((task) => !['fix', 'verify'].includes(task.id));
      let lastDenied: Approval | undefined;
      if (scenario !== 'passing') {
        for (let cycle = 0; cycle < 3; cycle++) {
          expect(screen.getByRole('button', { name: 'Accept result' })).toBeDisabled();
          const [approval] = await json<Approval[]>(`${base}/approvals`);
          const rejected = await server.request(`/approvals/${approval.id}/decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              expected_version: mission.version,
              decision: 'approve',
              payload_digest: approval.payload_digest,
            }),
          });
          expect(rejected.status).toBe(409);
          expect((await json<Mission>(base)).status).toBe('WAITING_APPROVAL');
          await user.click(screen.getByRole('button', { name: 'Deny result' }));
          lastDenied = approval;
          await screen.findByText(
            `${2 - cycle} revision cycles remaining. A revision preserves the original goal, source, and tests. It needs a separate run and fresh human review.`,
          );
          if (cycle === 2) break;
          const button = await screen.findByRole('button', { name: 'Revise patch' });
          expect(button).toBeDisabled();
          await waitFor(() =>
            expect(screen.getByLabelText('Patch revision feedback')).toBeEnabled(),
          );
          await user.type(
            screen.getByLabelText('Patch revision feedback'),
            'Use addition; preserve all test assertions.',
          );
          await waitFor(() => expect(button).toBeEnabled());
          await user.click(button);
          await screen.findByRole('button', { name: 'Run mission' }, { timeout: 10000 });
          const revised = await json<Mission>(base);
          expect(revised.tasks.filter((task) => !['fix', 'verify'].includes(task.id))).toEqual(
            initialEvidence,
          );
          expect(revised.tasks.find((task) => task.id === 'fix')?.outputs).toBeNull();
          mission = await run(scenario === 'two revisions' && cycle === 1);
          if (scenario === 'two revisions' && cycle === 1) break;
        }
      }
      const artifacts = await json<Artifact[]>(`${base}/artifacts`);
      const verify = mission.tasks.find((task) => task.id === 'verify')!;
      const reviews = artifacts.filter((artifact) => artifact.task_id === verify.id).slice(-5);
      expect(reviews.map((artifact) => artifact.name).sort()).toEqual([...reviewNames].sort());
      const content = new Map<string, string>();
      await user.click(screen.getByRole('tab', { name: /artifacts/ }));
      for (const artifact of reviews) {
        const text = await (await server.request(`/artifacts/${artifact.id}/content`)).text();
        content.set(artifact.name, text);
        await user.selectOptions(screen.getByLabelText('Result artifact'), artifact.id);
        await waitFor(() =>
          expect(
            screen.getByText(
              (_, element) => element?.tagName === 'PRE' && element.textContent === text,
            ),
          ).toBeVisible(),
        );
      }
      expect(content.get('reviewed-baseline-report.txt')).toBe(
        mission.tasks.find((task) => task.id === 'baseline')?.outputs?.baseline_report,
      );
      expect(content.get('test-report.txt')).toContain('Ran 3 tests');
      expect(content.get('tested.diff')).toContain(
        scenario === 'exhaust revisions' ? '+    return left * right' : '+    return left + right',
      );
      expect(content.get('tested.diff')).not.toContain('b/test_calculator.py');
      expect(verify.attempts).toBe(scenario === 'passing' ? 1 : 3);
      expect(mission.developer_revisions ?? []).toHaveLength(scenario === 'passing' ? 0 : 2);
      expect(content.get('test-report.txt')).toContain(
        scenario === 'exhaust revisions' ? 'FAILED' : 'OK',
      );
      for (const prefix of ['Source SHA-256:', 'Recipe SHA-256:']) {
        const digest = content
          .get('reviewed-baseline-report.txt')!
          .split('\n')
          .find((line) => line.startsWith(prefix));
        expect(digest).toBeTruthy();
        expect(content.get('test-report.txt')).toContain(digest);
      }
      const sourceIssue = artifacts.filter((artifact) => artifact.name === 'issue.json')[0];
      expect(content.get('reviewed-issue.json')).toBe(
        await (await server.request(`/artifacts/${sourceIssue.id}/content`)).text(),
      );
      const sourceIssueText = artifacts.find((artifact) => artifact.name === 'issue.md')!;
      expect(content.get('reviewed-issue.md')).toBe(
        await (await server.request(`/artifacts/${sourceIssueText.id}/content`)).text(),
      );
      const events = await json<Activity[]>(`${base}/events`);
      expect(
        events.filter((event) => event.action === 'tool_completed').length,
      ).toBeGreaterThanOrEqual(5);
      await user.click(screen.getByRole('tab', { name: /activity/ }));
      expect((await screen.findAllByText('tool completed')).length).toBeGreaterThanOrEqual(5);
      if (scenario === 'exhaust revisions') {
        expect(screen.queryByRole('button', { name: 'Revise patch' })).not.toBeInTheDocument();
        const exhausted = await json<Mission>(base);
        expect(exhausted.status).toBe('FAILED');
        const rejected = await server.request(`${base}/patch-revision`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            expected_version: exhausted.version,
            approval_id: lastDenied!.id,
            payload_digest: lastDenied!.payload_digest,
            feedback: 'A forbidden third revision',
          }),
        });
        expect(rejected.status).toBe(409);
        mission = exhausted;
      } else {
        const [pending] = await json<Approval[]>(`${base}/approvals`);
        expect(pending.payload?.artifact_refs).toEqual(reviews.map((artifact) => artifact.id));
        await reopen(created.id); // Real process restart while waiting for a human decision.
        expect(await json<Mission>(base)).toEqual(mission);
        expect(await json<Artifact[]>(`${base}/artifacts`)).toEqual(artifacts);
        await user.click(await screen.findByRole('button', { name: 'Accept result' }));
        await waitFor(() =>
          expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument(),
        );
        mission = await json<Mission>(base);
        expect(mission.status).toBe('COMPLETED');
      }
      const finalEvents = await json<Activity[]>(`${base}/events`);
      await reopen(created.id);
      expect(await json<Mission>(base)).toEqual(mission);
      expect(await json<Artifact[]>(`${base}/artifacts`)).toEqual(artifacts);
      expect(await json<Activity[]>(`${base}/events`)).toEqual(finalEvents);
      expect(
        screen.getByText(scenario === 'exhaust revisions' ? 'Tests failed' : 'Tests passed'),
      ).toBeVisible();
      expect(screen.queryByRole('button', { name: 'Accept result' })).not.toBeInTheDocument();
      await user.click(screen.getByRole('tab', { name: /artifacts/ }));
      await user.selectOptions(screen.getByLabelText('Result artifact'), reviews[4].id);
      await waitFor(() =>
        expect(
          screen.getByText(
            (_, element) =>
              element?.tagName === 'PRE' && element.textContent === content.get(reviews[4].name),
          ),
        ).toBeVisible(),
      );
      expect(mission.tasks.filter((task) => !['fix', 'verify'].includes(task.id))).toEqual(
        initialEvidence,
      );
      for (const artifact of reviews)
        expect(await (await server.request(`/artifacts/${artifact.id}/content`)).text()).toBe(
          content.get(artifact.name),
        );
      const observations = await server.observations();
      expect(observations.filter((item) => item.agent === 'developer_planner')).toHaveLength(1);
      expect(observations.filter((item) => item.agent === 'issue_specification')).toHaveLength(1);
      const patches = observations.filter((item) => item.agent === 'code_helper');
      expect(patches).toHaveLength(scenario === 'passing' ? 1 : 3);
      for (const observation of observations) expect(observation.inputs.goal).toBe(goal);
      for (const patch of patches) {
        expect(patch.inputs.constraints).toEqual(created.planning!.constraints);
        expect(patch.inputs.issue).toEqual(
          initialEvidence.find((task) => task.id === 'specify')?.outputs?.issue,
        );
      }
      expect(await readSources(root)).toEqual(originals);
    } finally {
      view?.unmount();
      try {
        await server?.stop();
      } finally {
        vi.unstubAllGlobals();
        await removeRoot(root);
      }
    }
  },
);
