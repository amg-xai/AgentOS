import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  artifactURL,
  navigationURL,
  requestAllowed,
  secureWindow,
  windowOptions,
} from '../src/security.mjs';

const origin = 'http://127.0.0.1:8767';
const artifact = `${origin}/artifacts/${'a'.repeat(32)}/content`;
test('exact local navigation and artifact downloads; no remote, encoded, or privileged schemes', () => {
  assert.ok(navigationURL(`${origin}/app/#section`, origin));
  assert.ok(artifactURL(artifact, origin));
  for (const url of [
    'https://example.com/app/',
    'file:///app/',
    `${origin}/docs`,
    `${origin}/app/?remote=1`,
    `${origin}/artifacts/${'a'.repeat(32)}/content?x=1`,
    'http://localhost:8767/app/',
    'http://user@127.0.0.1:8767/app/',
    `${origin}/app/%2e%2e/status`,
    'javascript:alert(1)',
  ])
    assert.equal(navigationURL(url, origin), false, url);
  assert.ok(requestAllowed(`${origin}/app/assets/index-A1.js`, origin, 'GET', 'script'));
  const mission = '12345678-1234-1234-1234-123456789abc';
  assert.ok(requestAllowed(`${origin}/missions/${mission}/tasks/quiz/actions`, origin, 'POST'));
  assert.ok(requestAllowed(`${origin}/missions?limit=100&offset=0`, origin));
  assert.ok(
    requestAllowed(
      `${origin}/missions?query=older&role_id=student&status=WAITING_APPROVAL`,
      origin,
    ),
  );
  assert.ok(requestAllowed(`${origin}/approvals/${'a'.repeat(32)}/decision`, origin, 'POST'));
  assert.ok(requestAllowed(`${origin}/workflows/student`, origin, 'POST'));
  assert.ok(requestAllowed(`${origin}/overview`, origin));
  assert.equal(requestAllowed(`${origin}/overview`, origin, 'POST'), false);
  assert.equal(requestAllowed(`${origin}/overview/extra`, origin), false);
  assert.equal(requestAllowed('https://example.com/overview', origin), false);
  for (const [url, method, type] of [
    [`${origin}/docs`, 'GET', 'mainFrame'],
    [`${origin}/status`, 'DELETE', 'xhr'],
    [`${origin}/app/`, 'GET', 'subFrame'],
    ['https://example.com/script.js', 'GET', 'script'],
    [`${origin}/workflows/unknown`, 'POST', 'xhr'],
  ])
    assert.equal(requestAllowed(url, origin, method, type), false);
});

test('window has no renderer privilege bridge and preserves sandbox/web security', () => {
  const options = windowOptions({}, true);
  assert.equal(options.webPreferences.nodeIntegration, false);
  assert.equal(options.webPreferences.contextIsolation, true);
  assert.equal(options.webPreferences.sandbox, true);
  assert.equal(options.webPreferences.webSecurity, true);
  assert.equal(options.webPreferences.webviewTag, false);
  assert.equal(options.webPreferences.preload, undefined);
  assert.equal(options.webPreferences.allowRunningInsecureContent, false);
  assert.match(options.title, /Offline demo/);
});

test('session refuses permissions, popups, subframes, remote requests, and unsafe downloads', () => {
  const session = new EventEmitter();
  const contents = new EventEmitter();
  contents.mainFrame = {};
  session.setPermissionRequestHandler = (fn) => (session.request = fn);
  session.setPermissionCheckHandler = (fn) => (session.check = fn);
  session.setDevicePermissionHandler = (fn) => (session.device = fn);
  session.webRequest = {
    onBeforeRequest(fn) {
      this.check = fn;
    },
  };
  contents.setWindowOpenHandler = (fn) => (contents.popup = fn);
  secureWindow({ webContents: contents }, session, origin);
  let permission;
  session.request(null, 'camera', (value) => (permission = value));
  assert.equal(permission, false);
  assert.equal(session.check(), false);
  assert.equal(session.device(), false);
  assert.deepEqual(contents.popup(), { action: 'deny' });
  let cancelled = false;
  const event = {
    preventDefault() {
      cancelled = true;
    },
    url: 'https://example.com',
    isMainFrame: true,
  };
  contents.emit('will-frame-navigate', event);
  assert.ok(cancelled);
  cancelled = false;
  contents.emit('will-redirect', event, 'https://example.com');
  assert.ok(cancelled);
  cancelled = false;
  contents.emit('will-attach-webview', event);
  assert.ok(cancelled);
  session.webRequest.check(
    { url: 'https://example.com', method: 'GET', resourceType: 'script' },
    (value) => assert.ok(value.cancel),
  );
  let dialogOptions;
  const item = {
    getURLChain: () => [artifact],
    getFilename: () => '../review.md',
    setSaveDialogOptions: (options) => (dialogOptions = options),
  };
  session.emit('will-download', event, item, contents, contents.mainFrame);
  assert.equal(dialogOptions.defaultPath, 'review.md');
  assert.equal(item.setSavePath, undefined); // Handler never silently chooses a full path.
  for (const [source, frame, chain] of [
    [{}, contents.mainFrame, [artifact]],
    [contents, {}, [artifact]],
    [contents, contents.mainFrame, ['https://example.com', artifact]],
  ]) {
    cancelled = false;
    dialogOptions = undefined;
    session.emit('will-download', event, { ...item, getURLChain: () => chain }, source, frame);
    assert.ok(cancelled);
    assert.equal(dialogOptions, undefined);
  }
});
