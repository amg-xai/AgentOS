import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { Writable } from 'node:stream';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { OwnedBackend, prerequisites, assertPortFree, killTree } from '../src/backend.mjs';

function fixture({ graceful = true, ...overrides } = {}) {
  const child = new EventEmitter();
  Object.assign(child, { pid: 12345, exitCode: null, signalCode: null });
  const exit = () => {
    child.exitCode = 0;
    child.emit('exit', 0);
  };
  child.stdin = new Writable({
    write(_chunk, _encoding, callback) {
      callback();
    },
    final(callback) {
      callback();
      if (graceful) queueMicrotask(exit);
    },
  });
  const calls = [];
  const backend = new OwnedBackend({
    root: 'D:/project with spaces',
    python: 'D:/python with spaces/python.exe',
    demo: true,
    shutdownTimeoutMs: 10,
    startupTimeoutMs: 20,
    checkPort: async () => {},
    spawnProcess: (...args) => {
      calls.push(args);
      return child;
    },
    request: async () => ({
      desktop_session: backend.session,
      execution_mode: 'demo',
      active_runs: 0,
    }),
    forceStop: async (owned) => {
      assert.equal(owned, child);
      calls.push('force');
      exit();
    },
    ...overrides,
  });
  return { backend, child, calls };
}

test('direct argv spawn preserves paths, mode, identity, and graceful ownership', async () => {
  const { backend, calls } = fixture();
  await backend.start();
  assert.match(backend.session, /^[0-9a-f]{32}$/);
  const [python, args, options] = calls[0];
  assert.equal(python, backend.python);
  assert.deepEqual(args, [
    '-m',
    'agentos',
    'serve',
    '--root',
    backend.root,
    '--port',
    '8000',
    '--desktop',
    '--demo',
  ]);
  assert.equal(options.shell, false);
  assert.equal(options.windowsHide, true);
  assert.equal(options.env.AGENTOS_DESKTOP_SESSION, backend.session);
  assert.deepEqual(options.stdio, ['pipe', 'ignore', 'ignore']);
  await Promise.all([backend.stop(), backend.stop()]);
  assert.ok(backend.exited);
  assert.equal(calls.length, 1);
});

test('normal mode remains normal; never silently chooses demo', async () => {
  const { backend, calls } = fixture({
    demo: false,
    request: async () => ({
      desktop_session: backend.session,
      execution_mode: 'live',
    }),
  });
  await backend.start();
  assert.ok(!calls[0][1].includes('--demo'));
  await backend.stop();
});

test('occupied ports do not spawn or stop unrelated services', async () => {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  try {
    await assert.rejects(assertPortFree(port), /unavailable/);
    const { backend, calls } = fixture({
      checkPort: () => assertPortFree(port),
    });
    await assert.rejects(backend.start(), /unavailable/);
    await backend.stop();
    assert.equal(calls.length, 0);
    assert.ok(server.listening);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

for (const status of [
  { desktop_session: 'wrong', execution_mode: 'demo' },
  { desktop_session: null, execution_mode: 'demo' },
  { execution_mode: 'live' },
]) {
  test(`readiness mismatch is rejected and owned child cleaned: ${JSON.stringify(status)}`, async () => {
    const { backend } = fixture({
      request: async () => ({ desktop_session: backend.session, ...status }),
    });
    await assert.rejects(backend.start(), /does not match/);
    assert.ok(backend.exited);
  });
}

test('startup timeout cleans its child; early spawn error is sanitized', async () => {
  const timed = fixture({
    request: async () => {
      throw new Error('not ready');
    },
  });
  await assert.rejects(timed.backend.start(), /timed out/);
  assert.ok(timed.backend.exited);
  const failed = fixture();
  failed.backend.spawnProcess = () => {
    queueMicrotask(() => failed.child.emit('error', new Error('sensitive stderr')));
    return failed.child;
  };
  failed.backend.request = async () => {
    throw new Error('not ready');
  };
  await assert.rejects(failed.backend.start(), /exited during startup/);
});

test('stop while port check is pending prevents a later spawn', async () => {
  let release;
  const { backend, calls } = fixture({
    checkPort: () =>
      new Promise((resolve) => {
        release = resolve;
      }),
  });
  const starting = backend.start();
  await backend.stop();
  release();
  await assert.rejects(starting, /cancelled/);
  assert.equal(calls.length, 0);
});

test('bounded shutdown forces only the owned child; an exit never triggers force cleanup', async () => {
  const { backend, calls } = fixture({ graceful: false });
  await backend.start();
  await backend.stop();
  assert.equal(calls[1], 'force');
  await killTree({ pid: 12345, exitCode: 0, signalCode: null });
});

test('backend crash is reported once and never respawned', async () => {
  const { backend, child, calls } = fixture();
  let crashes = 0;
  backend.onCrash = () => crashes++;
  await backend.start();
  child.exitCode = 1;
  child.emit('exit', 1);
  child.emit('exit', 1);
  assert.equal(crashes, 1);
  assert.equal(calls.length, 1);
  await assert.rejects(backend.status(), /unavailable/);
  await backend.stop();
});

test('prerequisites prefer runtime, preserve files, and explain missing install/build', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'agentos desktop '));
  try {
    await assert.rejects(prerequisites(root, 'win32'), /build/);
    await mkdir(path.join(root, 'frontend/dist'), { recursive: true });
    await mkdir(path.join(root, 'packages'));
    await writeFile(path.join(root, 'PLAN.md'), 'plan');
    await writeFile(path.join(root, 'frontend/dist/index.html'), 'client');
    await assert.rejects(prerequisites(root, 'win32'), /Install backend/);
    for (const env of ['.venv', '.venv-runtime']) {
      await mkdir(path.join(root, env, 'Scripts'), { recursive: true });
      await writeFile(path.join(root, env, 'Scripts/python.exe'), 'fixture');
    }
    assert.equal(
      await prerequisites(root, 'win32'),
      path.join(root, '.venv-runtime/Scripts/python.exe'),
    );
  } finally {
    assert.ok(
      path.resolve(root).startsWith(path.resolve(path.join(os.tmpdir(), 'agentos desktop '))),
    );
    await rm(root, { recursive: true, force: true });
  }
});

test('invalid ports fail before process creation', () => {
  for (const port of [0, 65536, 1.5, NaN]) assert.throws(() => fixture({ port }), /Port/);
});
