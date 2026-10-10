import { transferableAbortController } from 'node:util';
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
export const createRoot = () => mkdtemp(join(tmpdir(), 'agentos-ui-acceptance-'));
export const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
export const inspectPng = (bytes) => {
  const python = process.env.AGENTOS_TEST_PYTHON;
  if (!python) throw new Error('Set AGENTOS_TEST_PYTHON for actual PNG decoding.');
  const decoded = spawnSync(
    python,
    [
      '-c',
      'import sys,json; from io import BytesIO; from PIL import Image; im=Image.open(BytesIO(sys.stdin.buffer.read())); im.load(); print(json.dumps([im.size,im.mode,len(im.getcolors(1000000))]))',
    ],
    { input: bytes, timeout: 10000 },
  );
  if (decoded.error || decoded.status !== 0)
    throw new Error('PNG decoding failed', { cause: decoded.error });
  const [size, mode, colors] = JSON.parse(decoded.stdout.toString());
  return { size, mode, colors };
};
export const removeRoot = (root) => {
  const target = resolve(root);
  if (
    dirname(target) !== resolve(tmpdir()) ||
    !basename(target).startsWith('agentos-ui-acceptance-')
  )
    throw new Error('Refusing cleanup outside the owned acceptance directory');
  return rm(target, { recursive: true, force: true });
};
export const readSources = (root) =>
  Promise.all(
    ['calculator.py', 'test_calculator.py', 'README.md'].map((file) =>
      readFile(join(root, 'source', file)),
    ),
  );
const nativeFetch = globalThis.fetch;
const fixture = resolve('../backend/tests/mission_control_server.py');
export async function startServer(root) {
  const python = process.env.AGENTOS_TEST_PYTHON;
  if (!python)
    throw new Error('Set AGENTOS_TEST_PYTHON; continuous acceptance must not silently skip.');
  const env = Object.fromEntries(
    Object.entries(process.env).filter(
      ([key]) => !key.startsWith('AGENTOS_') && !/^(OPENAI|ANTHROPIC|AZURE|GOOGLE|AWS)_/.test(key),
    ),
  );
  const child = spawn(python, [fixture, root], {
    env: { ...env, AGENTOS_ALLOW_LIVE_MODELS: '0', AGENTOS_USER_ROLE: 'operator' },
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  let diagnostics = '';
  let origin = '';
  let startup = '';
  let spawnError;
  child.on('error', (error) => {
    spawnError = error;
  });
  const exited = new Promise((resolve) => child.once('close', () => resolve()));
  child.stderr.on('data', (chunk) => {
    diagnostics = (diagnostics + chunk).slice(-8000);
  });
  child.stdout.on('data', (chunk) => {
    startup += chunk;
    if (!origin && startup.includes('\n')) origin = JSON.parse(startup.split('\n')[0]).origin;
  });
  const request = async (route, options) => {
    const target = new URL(route, origin);
    if (target.origin !== origin)
      throw new Error('Acceptance requests must stay on the owned backend');
    // JSDOM and Node have different AbortSignal realms. Forward cancellation
    // without fabricating responses or replacing the application's HTTP API.
    const controller = transferableAbortController();
    const signal = options?.signal;
    const abort = () => controller.abort();
    if (signal?.aborted) abort();
    signal?.addEventListener('abort', abort, { once: true });
    const timer = setTimeout(abort, 30000);
    // Model the browser's same-origin request; Host remains set by real HTTP.
    const headers = new Headers(options?.headers);
    headers.set('Origin', origin);
    try {
      return await nativeFetch(target.href, {
        ...options,
        headers,
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  };
  const stop = async () => {
    child.stdin.end();
    let timer;
    try {
      await Promise.race([
        exited,
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            child.kill();
            reject(new Error('Backend shutdown deadline'));
          }, 10000);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  };
  try {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      if (spawnError || child.exitCode !== null) throw spawnError ?? new Error(diagnostics);
      if (origin) {
        try {
          if ((await request('/status', { signal: AbortSignal.timeout(1000) })).ok) break;
        } catch {
          /* Server has announced its listener but startup may still be in progress. */
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    if (!origin || !(await request('/status')).ok) throw new Error('Backend startup deadline');
  } catch (error) {
    await stop();
    throw new Error(`Acceptance backend failed: ${diagnostics}`, { cause: error });
  }
  return {
    request,
    stop,
    fetch: (input, options) => {
      if (typeof input !== 'string' || !input.startsWith('/'))
        throw new Error('Only relative local API routes are expected');
      return request(input, options);
    },
    observations: async () =>
      (await readFile(`${root}/model-inputs.jsonl`, 'utf8'))
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line)),
  };
}
