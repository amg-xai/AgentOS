import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, mkdtemp, mkdir, writeFile, readFile, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { OwnedBackend } from '../src/backend.mjs';
import { spawn } from 'node:child_process';

const project = fileURLToPath(new URL('../../', import.meta.url));
const python = process.env.AGENTOS_TEST_PYTHON;
async function port() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const selected = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return selected;
}

test(
  'real owned Python server: three workflows, review restart, EOF shutdown, and preserved normal data',
  { skip: !python, timeout: 60000 },
  async () => {
    const prefix = path.join(os.tmpdir(), 'agentos-desktop-process-');
    const root = await mkdtemp(prefix);
    let backend;
    try {
      await cp(path.join(project, 'packages'), path.join(root, 'packages'), { recursive: true });
      await cp(path.join(project, 'samples'), path.join(root, 'samples'), { recursive: true });
      await mkdir(path.join(root, 'frontend/dist'), { recursive: true });
      await writeFile(path.join(root, 'PLAN.md'), 'temporary process smoke checkout');
      await writeFile(
        path.join(root, 'frontend/dist/index.html'),
        '<!doctype html><title>HTTP fixture only</title>',
      );
      await mkdir(path.join(root, '.agentos'));
      const normal = path.join(root, '.agentos/agentos.sqlite3');
      await writeFile(normal, 'existing normal history must remain unchanged');
      const original = await readFile(normal);
      const sample = path.join(root, 'samples/calculator/calculator.py');
      const sampleHash = createHash('sha256')
        .update(await readFile(sample))
        .digest('hex');
      const makeBackend = async () =>
        new OwnedBackend({
          root,
          python,
          port: await port(),
          demo: true,
          spawnProcess: (command, args, options) =>
            spawn(command, args, {
              ...options,
              env: {
                ...options.env,
                AGENTOS_USER_ROLE: 'operator',
                AGENTOS_MODEL: 'not-a-live-call',
                AGENTOS_MODEL_URL: 'malformed-live-settings',
                AGENTOS_DATABASE: normal,
              },
            }),
          forceStop: async () => {
            throw new Error('Expected graceful private-pipe shutdown, not force.');
          },
        });
      backend = await makeBackend();
      await backend.start();
      const api = async (route, payload) => {
        const response = await fetch(backend.origin + route, {
          method: payload === undefined ? 'GET' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
          signal: AbortSignal.timeout(30000),
        }).catch((error) => {
          throw new Error(`Owned process HTTP request failed: ${route}`, { cause: error });
        });
        assert.ok(response.ok, `${route}: ${response.status}`);
        return response.json();
      };
      const status = await backend.status();
      assert.equal(status.provider_configured, false);
      assert.equal(status.active_runs, 0);
      const missions = [];
      let student;
      for (const workflow of status.workflows) {
        const created = await api(`/workflows/${workflow.role_id}`, { goal: workflow.demo_goal });
        const mission = await api(`/missions/${created.id}/run`, {
          expected_version: created.version,
        });
        assert.equal(mission.status, 'WAITING_APPROVAL');
        missions.push(mission.id);
        if (workflow.role_id === 'developer') assert.equal(mission.tasks[2].outputs.passed, true);
        else assert.ok(mission.tasks.every((task) => !('passed' in (task.outputs ?? {}))));
        if (workflow.role_id === 'student') student = mission;
      }
      assert.equal(missions.length, 3);
      const artifacts = await api(`/missions/${student.id}/artifacts`);
      assert.equal(artifacts.length, 6);
      const approval = (await api(`/missions/${student.id}/approvals`))[0];
      const note = await api('/memory', {
        title: 'Desktop process smoke',
        content: 'HTTP fixture study bundle',
        artifact_refs: [artifacts[0].id],
      });
      const originalIdentity = backend.session;
      const beforeOverview = await api('/overview');
      assert.equal(beforeOverview.execution_mode, 'demo');
      assert.equal(beforeOverview.total_missions, 3);
      assert.equal(beforeOverview.pending_approvals, 3);
      assert.equal(beforeOverview.local_active_runs, 0);
      assert.equal(beforeOverview.durable_claims, 0);
      assert.equal(beforeOverview.recent_reviews.length, 3);
      await backend.stop();
      assert.ok(backend.exited);
      backend = await makeBackend();
      await backend.start();
      assert.notEqual(backend.session, originalIdentity);
      assert.deepEqual(await api(`/missions/${student.id}`), student);
      assert.deepEqual(await api(`/missions/${student.id}/artifacts`), artifacts);
      const afterOverview = await api('/overview');
      const { observed_at: _beforeTime, ...beforeState } = beforeOverview;
      const { observed_at: _afterTime, ...afterState } = afterOverview;
      assert.deepEqual(afterState, beforeState);
      assert.ok((await api('/memory')).some((saved) => saved.id === note.id));
      assert.ok((await api('/missions')).every((mission) => missions.includes(mission.id)));
      assert.equal(
        (
          await api(`/approvals/${approval.id}/decision`, {
            expected_version: student.version,
            decision: 'approve',
            payload_digest: approval.payload_digest,
          })
        ).status,
        'COMPLETED',
      );
      assert.deepEqual(await readFile(normal), original);
      assert.equal(
        createHash('sha256')
          .update(await readFile(sample))
          .digest('hex'),
        sampleHash,
      );
      await backend.stop();
      assert.ok(backend.exited);
    } finally {
      if (backend) await backend.stop();
      assert.ok(path.resolve(root).startsWith(path.resolve(prefix)));
      await rm(root, { recursive: true, force: true });
    }
  },
);
