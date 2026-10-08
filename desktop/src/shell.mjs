export function installShell({
  app,
  BrowserWindow,
  session,
  dialog,
  backend,
  demo = false,
  windowOptions,
  secureWindow,
  lockAcquired = false,
}) {
  let window;
  let quitting = false;
  let closing = false;
  let startup;
  const focus = () => {
    if (window && !window.isDestroyed()) {
      if (window.isMinimized()) window.restore();
      window.show();
      window.focus();
    }
  };
  if (!lockAcquired && !app.requestSingleInstanceLock()) {
    app.quit();
    return { started: Promise.resolve(), secondary: true };
  }
  app.on('second-instance', focus);
  app.on('activate', focus);

  async function close() {
    if (quitting || closing) return;
    closing = true;
    try {
      let active = true;
      if (backend.ready && !backend.exited) {
        try {
          active = (await backend.status()).active_runs !== 0;
        } catch {
          /* Unknown status requires the same explicit choice. */
        }
      } else if (backend.exited) active = false;
      if (active) {
        const { response } = await dialog.showMessageBox(window, {
          type: 'warning',
          title: 'Close AgentOS?',
          buttons: ['Keep working', 'Exit and stop backend'],
          defaultId: 0,
          cancelId: 0,
          message: 'Work may still be running.',
          detail:
            'Exiting stops this desktop backend. Interrupted work may retain a claim requiring manual recovery. No result is approved or retried.',
        });
        if (response !== 1) return;
      }
      await backend.stop();
      quitting = true;
      if (window && !window.isDestroyed()) window.destroy();
      app.quit();
    } catch {
      dialog.showErrorBox(
        'AgentOS could not stop its backend',
        'Check the owned backend process before restarting. Your mission history is preserved.',
      );
    } finally {
      closing = false;
    }
  }

  app.on('before-quit', (event) => {
    if (!quitting) {
      event.preventDefault();
      void close();
    }
  });
  app.on('window-all-closed', () => {
    if (!quitting) void close();
  });
  startup = app.whenReady().then(async () => {
    if (closing || quitting) return;
    backend.onCrash = () => {
      quitting = true;
      dialog.showErrorBox(
        'AgentOS backend stopped',
        'The owned backend exited unexpectedly. Close and reopen AgentOS. Interrupted missions may need manual recovery; no work was automatically retried.',
      );
      if (window && !window.isDestroyed()) window.destroy();
      app.quit();
    };
    try {
      await backend.start();
      if (closing || quitting) {
        await backend.stop();
        return;
      }
      const isolated = session.fromPartition(`agentos-${backend.session}`, {
        cache: false,
      });
      window = new BrowserWindow(windowOptions(isolated, demo));
      window.removeMenu();
      secureWindow(window, isolated, backend.origin);
      window.on('close', (event) => {
        if (!quitting) {
          event.preventDefault();
          void close();
        }
      });
      window.webContents.on('render-process-gone', () => {
        void close();
      });
      await window.loadURL(`${backend.origin}/app/`);
      if (!quitting) window.show();
    } catch {
      try {
        await backend.stop();
      } catch {
        /* Report cleanup ambiguity rather than claiming success. */
      }
      dialog.showErrorBox(
        'AgentOS could not start',
        'Check the Python environment, backend dependencies, built frontend assets, port, and local configuration. No existing service was adopted. If cleanup failed, inspect the owned process before restarting.',
      );
      quitting = true;
      if (window && !window.isDestroyed()) window.destroy();
      app.quit();
    }
  });
  return { started: startup, close, focus, getWindow: () => window };
}
