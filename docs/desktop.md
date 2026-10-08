# Local desktop shell

The checkout-based Electron shell starts its own loopback backend and displays the
existing Mission Control. Developer, Creator, Student, artifact review, and memory
use the same API and databases as the web app. This is a development launcher,
not a standalone installer with bundled Python.

## Install and open

Install the backend and build the frontend using [getting-started.md](getting-started.md).
Then, from the repository root in PowerShell:

```powershell
npm --prefix desktop ci
npm --prefix desktop run install:runtime
.\Start-AgentOSDesktop.ps1 -Demo
```

Runtime installation downloads the pinned Electron binary; it does not open the
app. The launcher never installs dependencies automatically. It prefers an
existing `.venv-runtime`, then `.venv`. Backend dependencies must be installed in
that environment. Node.js 24 is used for desktop development/checks.

The default port is 8000. If another service uses it, choose a free port:

```powershell
.\Start-AgentOSDesktop.ps1 -Demo -Port 8768
```

The shell refuses occupied ports and verifies its child's per-launch identity
before opening Mission Control. It never adopts an existing web server. Starting
another desktop instance focuses the first instance; it does not switch its mode
or start another backend. Close it before switching between normal and demo mode.

`-Demo` is explicit: responses are scripted, Developer executes actual scratch
tests, and Creator/Student produce labelled content fixtures. No model calls
occur. The same `.agentos/demo/` history and memory remain available. Follow the
[Developer walkthrough](getting-started.md), [Creator guide](creator-workflow.md),
or [Student guide](student-workflow.md).

For configured model execution, omit `-Demo`:

```powershell
.\Start-AgentOSDesktop.ps1
```

Provider and workspace configuration follow the existing web setup. The backend
loads `.env`; the renderer receives no model credentials or native-process APIs.
The PowerShell launcher temporarily removes `ELECTRON_RUN_AS_NODE` while starting
Electron and restores the caller's value afterward.

## Downloads and closing

Use **Download** on a verified artifact. The desktop session allows only current
same-origin artifact endpoints and asks where to save each file. Downloads do not
apply patches, approve results, publish anything, or open the saved file.

Closing an idle window stops its owned backend through private stdin EOF. If work
is active or its status is unavailable, choose **Keep working** or **Exit and stop
backend**. Graceful shutdown has a bounded wait; a stuck owned process tree may
require forced cleanup. Work interrupted before a durable result may retain an
execution claim. Follow [manual recovery](workflows.md#interrupted-run-recovery)
after confirming the old worker stopped. Closing does not approve, cancel, retry,
or recover missions automatically. A backend crash reports failure and does not
automatically restart agents. Existing mission history is retained.

The server remains a trusted, local, single-user service. A launch identity proves
which process answered startup; it is not authentication or a permission grant.
The backend's Viewer/Operator/Admin enforcement remains in effect. Keep the app
on a trusted local machine; remote operation is unsupported.

## Test the desktop manually

Automated checks exercise process ownership, real HTTP workflows/restart, renderer
policy helpers, and lifecycle using injected window/dialog adapters. They do not
establish actual Electron rendering or native dialog behavior. Under the existing
browser access restriction, no alternative renderer was opened for automated
inspection. The installed runtime is available for your manual test:

1. Start `-Demo` and verify Mission Control and the offline label are visible.
2. Run and inspect a mission in each role. Confirm role-specific review copy,
   keyboard navigation, and separate Student quiz/answer-key downloads.
3. Download an artifact through the native save prompt; cancel another download.
   Confirm content and filename match the inspected artifact.
4. Start the launcher again and confirm it focuses the existing window.
5. Close while idle, reopen, and verify history and notes persisted. While work
   is running, test **Keep working** before testing an explicit exit separately.
6. Check layout at supported window sizes, keyboard focus, and screen-reader
   behavior. Report failures before treating desktop acceptance as complete.

Browser/native rendering, dialogs, downloads, accessibility, and live AI quality
remain unverified. Installers, bundled Python, signing, updates, background/tray
operation, remote authentication, and deployment remain deferred.

## Development checks

```powershell
$env:AGENTOS_TEST_PYTHON = (Resolve-Path .\.venv-runtime\Scripts\python.exe).Path
# Use your installed .venv interpreter when .venv-runtime is absent.
npm --prefix desktop test
npm --prefix desktop run check
npm --prefix desktop run format:check
```

Without `AGENTOS_TEST_PYTHON`, the real-process test is explicitly skipped. Hosted
Linux/Windows checks set it and run real Python/HTTP workflows without launching
Electron. Existing backend and frontend checks remain required.

Renderer policy is based on [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security),
with sandbox/context isolation enabled, Node integration disabled, restrictive
navigation/requests, denied permissions/popups, and no privileged preload bridge.
