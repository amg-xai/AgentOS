import { app, BrowserWindow, session, dialog } from 'electron';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { OwnedBackend, prerequisites } from './backend.mjs';
import { secureWindow, windowOptions } from './security.mjs';
import { installShell } from './shell.mjs';

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  try {
    const { values } = parseArgs({
      args: process.argv.slice(2),
      options: {
        root: {
          type: 'string',
          default: fileURLToPath(new URL('../../', import.meta.url)),
        },
        port: { type: 'string', default: '8000' },
        demo: { type: 'boolean', default: false },
      },
      strict: true,
    });
    const python = await prerequisites(values.root);
    const backend = new OwnedBackend({
      root: values.root,
      python,
      port: Number(values.port),
      demo: values.demo,
    });
    installShell({
      app,
      BrowserWindow,
      session,
      dialog,
      backend,
      demo: values.demo,
      secureWindow,
      windowOptions,
      lockAcquired: true,
    });
  } catch {
    await app.whenReady();
    dialog.showErrorBox(
      'AgentOS desktop prerequisites',
      'Run from the AgentOS checkout. Install backend and desktop dependencies, build the frontend, and use a valid port. See docs/desktop.md.',
    );
    app.quit();
  }
}
