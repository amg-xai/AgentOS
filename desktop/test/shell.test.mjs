import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { installShell } from '../src/shell.mjs';
import { windowOptions } from '../src/security.mjs';

function fixture({
  primary = true,
  active = 0,
  answer = 0,
  startupError = false,
  loadError = false,
  stopError = false,
} = {}) {
  const app = new EventEmitter();
  const calls = [];
  app.requestSingleInstanceLock = () => primary;
  app.whenReady = async () => {};
  app.quit = () => calls.push('quit');
  class Window extends EventEmitter {
    constructor(options) {
      super();
      this.options = options;
      this.webContents = new EventEmitter();
      calls.push('window');
    }
    removeMenu() {
      calls.push('menu removed');
    }
    async loadURL(url) {
      calls.push(url);
      if (loadError) throw new Error('load failed');
    }
    show() {
      calls.push('show');
    }
    focus() {
      calls.push('focus');
    }
    isMinimized() {
      return true;
    }
    restore() {
      calls.push('restore');
    }
    isDestroyed() {
      return !!this.destroyed;
    }
    destroy() {
      this.destroyed = true;
      calls.push('destroy');
    }
  }
  const backend = {
    session: 'owned',
    origin: 'http://127.0.0.1:8767',
    ready: false,
    exited: false,
    async start() {
      calls.push('start');
      if (startupError) throw new Error('secret config detail');
      this.ready = true;
    },
    async status() {
      return { active_runs: active };
    },
    async stop() {
      calls.push('stop');
      if (stopError) throw new Error('cleanup failed');
      this.exited = true;
    },
  };
  const dialog = {
    async showMessageBox(_window, options) {
      calls.push(options);
      return { response: answer };
    },
    showErrorBox(title, text) {
      calls.push({ title, text });
    },
  };
  const session = {
    fromPartition(name, options) {
      calls.push({ name, options });
      return {};
    },
  };
  const shell = installShell({
    app,
    BrowserWindow: Window,
    session,
    dialog,
    backend,
    demo: true,
    windowOptions,
    secureWindow: () => calls.push('secured'),
  });
  return { shell, app, backend, calls };
}

test('singleton secondary instance never starts a backend or creates a window', async () => {
  const { shell, calls } = fixture({ primary: false });
  await shell.started;
  assert.deepEqual(calls, ['quit']);
  assert.ok(shell.secondary);
});

test('startup secures one ephemeral window before navigation; second instance focuses it', async () => {
  const { shell, app, calls } = fixture();
  await shell.started;
  assert.ok(calls.indexOf('secured') < calls.indexOf('http://127.0.0.1:8767/app/'));
  assert.deepEqual(
    calls.find((call) => call?.name),
    { name: 'agentos-owned', options: { cache: false } },
  );
  const options = shell.getWindow().options;
  assert.equal(options.webPreferences.nodeIntegration, false);
  assert.equal(options.webPreferences.sandbox, true);
  app.emit('second-instance');
  assert.equal(calls.at(-1), 'focus');
  assert.equal(calls.filter((call) => call === 'start').length, 1);
  await shell.close();
  assert.equal(calls.at(-1), 'quit');
});

test('active work can keep running; exit explicitly stops only owned backend', async () => {
  const keep = fixture({ active: 1 });
  await keep.shell.started;
  await keep.shell.close();
  assert.ok(!keep.calls.includes('stop'));
  assert.equal(keep.calls.find((call) => call?.buttons).defaultId, 0);
  const exit = fixture({ active: 1, answer: 1 });
  await exit.shell.started;
  await Promise.all([exit.shell.close(), exit.shell.close()]);
  assert.equal(exit.calls.filter((call) => call === 'stop').length, 1);
  assert.ok(exit.calls.includes('destroy'));
  assert.equal(exit.calls.at(-1), 'quit');
});

test('unknown run status requires explicit exit choice', async () => {
  const { shell, backend, calls } = fixture();
  await shell.started;
  backend.status = async () => {
    throw new Error('unavailable');
  };
  await shell.close();
  assert.ok(calls.some((call) => call?.buttons));
  assert.ok(!calls.includes('stop'));
});

for (const failure of ['startupError', 'loadError']) {
  test(`${failure} cleans up without exposing configuration or opening another service`, async () => {
    const { shell, calls } = fixture({ [failure]: true });
    await shell.started;
    assert.ok(calls.includes('stop'));
    assert.equal(calls.at(-1), 'quit');
    assert.ok(!JSON.stringify(calls).includes('secret config detail'));
    if (failure === 'startupError') assert.ok(!calls.includes('window'));
  });
}

test('cleanup failure leaves a visible error instead of claiming exit succeeded', async () => {
  const { shell, calls } = fixture({ stopError: true });
  await shell.started;
  await shell.close();
  assert.ok(!calls.includes('quit'));
  assert.ok(!calls.includes('destroy'));
  assert.ok(calls.some((call) => call?.title === 'AgentOS could not stop its backend'));
});

test('unexpected backend exit reports failure and does not auto-restart agents', async () => {
  const { shell, backend, calls } = fixture();
  await shell.started;
  backend.exited = true;
  backend.onCrash();
  assert.equal(calls.filter((call) => call === 'start').length, 1);
  assert.ok(calls.some((call) => call?.title === 'AgentOS backend stopped'));
  assert.equal(calls.at(-1), 'quit');
});

test('native close event defers exit to lifecycle cleanup', async () => {
  const { shell, calls } = fixture();
  await shell.started;
  let prevented = false;
  shell.getWindow().emit('close', {
    preventDefault() {
      prevented = true;
    },
  });
  await new Promise(setImmediate);
  assert.ok(prevented);
  assert.equal(calls.at(-1), 'quit');
});
