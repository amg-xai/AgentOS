import path from 'node:path';

function localURL(value, origin) {
  try {
    const url = new URL(value);
    if (url.origin !== origin || url.username || url.password || /%|\\/.test(url.pathname))
      return null;
    return url;
  } catch {
    return null;
  }
}

export function artifactURL(value, origin) {
  const url = localURL(value, origin);
  return (
    !!url && !url.search && !url.hash && /^\/artifacts\/[0-9a-f]{32}\/content$/.test(url.pathname)
  );
}

export function navigationURL(value, origin) {
  const url = localURL(value, origin);
  return !!url && ((url.pathname === '/app/' && !url.search) || artifactURL(value, origin));
}

export function requestAllowed(value, origin, method = 'GET', resourceType = 'xhr') {
  const url = localURL(value, origin);
  if (!url || !['GET', 'POST'].includes(method)) return false;
  if (resourceType === 'subFrame') return false;
  if (resourceType === 'mainFrame') return method === 'GET' && navigationURL(value, origin);
  const id = '[0-9a-f-]{36}';
  const agent = '[a-z][a-z0-9_]*';
  const get = new RegExp(
    `^/(?:status|overview|memory|missions|roles|agents|(?:roles|agents)/${agent}|missions/${id}(?:/(?:events|run|approvals|artifacts))?|approvals/[0-9a-f]{32}|artifacts/[0-9a-f]{32}(?:/content)?)$`,
  );
  const post = new RegExp(
    `^/(?:memory|missions|workflows/(?:developer|creator|student)|missions/${id}/(?:run|cancel|recover|tasks/${agent}/actions)|approvals/[0-9a-f]{32}/decision)$`,
  );
  return method === 'GET'
    ? get.test(url.pathname) || /^\/app\/assets\/[A-Za-z0-9._-]+$/.test(url.pathname)
    : post.test(url.pathname);
}

export function windowOptions(session, demo) {
  return {
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 620,
    show: false,
    title: demo ? 'AgentOS — Offline demo' : 'AgentOS',
    webPreferences: {
      session,
      nodeIntegration: false,
      nodeIntegrationInWorker: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      webviewTag: false,
      spellcheck: false,
      devTools: false,
    },
  };
}

export function secureWindow(window, session, origin) {
  const contents = window.webContents;
  session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  session.setPermissionCheckHandler(() => false);
  session.setDevicePermissionHandler(() => false);
  session.webRequest.onBeforeRequest((details, callback) =>
    callback({
      cancel: !requestAllowed(details.url, origin, details.method, details.resourceType),
    }),
  );
  contents.setWindowOpenHandler(() => ({ action: 'deny' }));
  contents.on('will-attach-webview', (event) => event.preventDefault());
  contents.on('will-frame-navigate', (event) => {
    if (!event.isMainFrame || !navigationURL(event.url, origin)) event.preventDefault();
  });
  contents.on('will-redirect', (event, url) => {
    if (!navigationURL(event.url ?? url, origin)) event.preventDefault();
  });
  session.on('will-download', (event, item, source, frame) => {
    if (
      source !== contents ||
      frame !== contents.mainFrame ||
      !item.getURLChain().length ||
      !item.getURLChain().every((url) => artifactURL(url, origin))
    ) {
      event.preventDefault();
      return;
    }
    // No setSavePath: Electron must ask the user where to save every download.
    const filename = path
      .basename(item.getFilename().replaceAll('\\', '/'))
      .replace(/[^A-Za-z0-9._ -]/g, '_')
      .slice(0, 121);
    item.setSaveDialogOptions({
      title: 'Save verified AgentOS artifact',
      defaultPath: filename || 'artifact.txt',
    });
  });
}
