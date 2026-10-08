import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { stat } from 'node:fs/promises';
import net from 'node:net';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

export async function prerequisites(root, platform = process.platform) {
  for (const relative of ['PLAN.md', 'packages', 'frontend/dist/index.html']) {
    try {
      await stat(path.join(root, relative));
    } catch {
      throw new Error('Use the AgentOS checkout and build the frontend before desktop startup.');
    }
  }
  for (const environment of ['.venv-runtime', '.venv']) {
    const python = path.join(
      root,
      environment,
      ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']),
    );
    try {
      if ((await stat(python)).isFile()) return python;
    } catch {
      /* Try the next installed environment. */
    }
  }
  throw new Error('Install backend dependencies in .venv (or .venv-runtime) first.');
}

export function assertPortFree(port) {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', () =>
      reject(
        new Error('Desktop port is unavailable. Stop the other service or choose another port.'),
      ),
    );
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(resolve));
  });
}

export async function readStatus(origin) {
  const response = await fetch(`${origin}/status`, {
    signal: AbortSignal.timeout(1000),
    redirect: 'error',
  });
  if (!response.ok) throw new Error('Backend status is unavailable.');
  return response.json();
}

export async function killTree(child, platform = process.platform) {
  if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (platform === 'win32') {
    await new Promise((resolve, reject) => {
      const cleanup = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
        windowsHide: true,
        stdio: 'ignore',
        shell: false,
      });
      const deadline = setTimeout(() => {
        cleanup.kill();
        reject(new Error('Owned backend cleanup timed out.'));
      }, 2000);
      cleanup.once('close', () => clearTimeout(deadline));
      cleanup.once('error', reject);
      cleanup.once('exit', (code) =>
        code === 0 || child.exitCode !== null
          ? resolve()
          : reject(new Error('Owned backend cleanup failed.')),
      );
    });
  } else {
    try {
      process.kill(-child.pid, 'SIGKILL');
    } catch (error) {
      if (error.code !== 'ESRCH') throw error;
    }
  }
}

export class OwnedBackend {
  constructor({
    root,
    python,
    port = 8000,
    demo = false,
    startupTimeoutMs = 15000,
    shutdownTimeoutMs = 12000,
    spawnProcess = spawn,
    checkPort = assertPortFree,
    request = readStatus,
    forceStop = killTree,
  }) {
    if (!Number.isInteger(port) || port < 1 || port > 65535)
      throw new Error('Port must be between 1 and 65535.');
    Object.assign(this, {
      root,
      python,
      port,
      demo,
      startupTimeoutMs,
      shutdownTimeoutMs,
      spawnProcess,
      checkPort,
      request,
      forceStop,
    });
    this.session = randomUUID().replaceAll('-', '');
    this.origin = `http://127.0.0.1:${port}`;
    this.child = null;
    this.stopping = false;
    this.exited = false;
    this.onCrash = () => {};
  }

  async start() {
    if (this.stopping) throw new Error('Desktop startup was cancelled.');
    if (this.child) throw new Error('Backend is already owned by this shell.');
    await this.checkPort(this.port);
    if (this.stopping) throw new Error('Desktop startup was cancelled.');
    const args = [
      '-m',
      'agentos',
      'serve',
      '--root',
      this.root,
      '--port',
      String(this.port),
      '--desktop',
    ];
    if (this.demo) args.push('--demo');
    this.child = this.spawnProcess(this.python, args, {
      cwd: this.root,
      env: { ...process.env, AGENTOS_DESKTOP_SESSION: this.session },
      stdio: ['pipe', 'ignore', 'ignore'],
      windowsHide: true,
      shell: false,
      detached: process.platform !== 'win32',
    });
    this.child.stdin.on('error', () => {});
    this.exit = new Promise((resolve) => {
      const finish = () => {
        if (this.exited) return;
        this.exited = true;
        resolve();
        if (this.ready && !this.stopping) this.onCrash();
      };
      this.child.once('error', finish);
      this.child.once('exit', finish);
    });
    const deadline = Date.now() + this.startupTimeoutMs;
    try {
      while (Date.now() < deadline) {
        if (this.exited)
          throw new Error(
            'Backend exited during startup. Check backend installation and local configuration.',
          );
        let status;
        try {
          status = await this.request(this.origin);
        } catch {
          /* Server may still be starting. */
        }
        if (this.exited)
          throw new Error(
            'Backend exited during startup. Check backend installation and local configuration.',
          );
        if (status) {
          if (
            status.desktop_session !== this.session ||
            status.execution_mode !== (this.demo ? 'demo' : 'live')
          ) {
            throw new Error(
              'Backend readiness identity or execution mode does not match this launch.',
            );
          }
          if (this.exited) throw new Error('Backend exited during startup.');
          this.ready = true;
          return this;
        }
        await delay(Math.min(100, Math.max(1, deadline - Date.now())));
      }
      throw new Error('Backend startup timed out. Check installation and local configuration.');
    } catch (error) {
      await this.stop();
      throw error;
    }
  }

  async status() {
    const status = await this.request(this.origin);
    if (status.desktop_session !== this.session || this.exited)
      throw new Error('Owned backend is unavailable.');
    return status;
  }

  async stop() {
    if (this.stopPromise) return this.stopPromise;
    this.stopping = true;
    this.stopPromise = this.shutdown();
    return this.stopPromise;
  }

  async shutdown() {
    if (!this.child || this.exited) return;
    this.child.stdin.end();
    const graceful = await this.waitForExit(this.shutdownTimeoutMs);
    if (!graceful) {
      await this.forceStop(this.child);
      if (!(await this.waitForExit(2000)))
        throw new Error('Owned backend did not stop. Check the local process before restarting.');
    }
  }

  async waitForExit(ms) {
    let timer;
    try {
      return await Promise.race([
        this.exit.then(() => true),
        new Promise((resolve) => {
          timer = setTimeout(() => resolve(false), ms);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }
}
