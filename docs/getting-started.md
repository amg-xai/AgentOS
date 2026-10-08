# Test the local Developer workflow

AgentOS runs as a loopback web app. Electron packaging and external ticket/PR
integrations are deferred. You need Python 3.11+, Node.js 22.12+ (24 recommended),
Git, and a model endpoint supporting the Responses API with strict structured
outputs. Without a configured provider you can inspect the client, agents,
history, and memory, but cannot start a real Developer mission.

## Install and start

In PowerShell at the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "./backend[dev]"
npm --prefix frontend ci
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m agentos setup-sample
Copy-Item .env.example .env
```

Edit the ignored `.env` file locally. Set `AGENTOS_MODEL` to your chosen model and
`AGENTOS_MODEL_KEY` to its API key. Never send the key in chat or commit it. See
[provider configuration](providers.md) for a local Responses-compatible endpoint.
No model is selected implicitly, and desktop sign-in does not supply an API key.
The launcher reads `.env` without overriding existing environment variables.

Check local prerequisites without contacting a provider or executing project code:

```powershell
.\.venv\Scripts\python.exe -m agentos doctor
# Use --json for a structured report; exit 0 means prerequisites pass, 1 means blocked.
```

The check validates manifests, selected source files, configured runner paths,
role permissions, provider configuration, and built client assets. It does not
create databases or snapshots and never prints credentials. Missing provider
configuration is reported as blocked for real execution; you can still start the
client and inspect agents, memory, and existing history. A passing local check
does not establish live model connectivity or complete browser acceptance.

```powershell
.\Start-AgentOS.ps1
# Or, on any supported OS:
python -m agentos serve
```

Open [Mission Control](http://127.0.0.1:8000/app/). Stop with Ctrl+C.
`Start-AgentOS.ps1 -Build` reinstalls locked frontend dependencies and rebuilds;
`-SetupSample` creates configuration only when it does not already exist.
The launcher prefers an existing `.venv-runtime` on machines that need it;
otherwise it uses `.venv`. It never overwrites workspace configuration.

For another trusted project, edit `.agentos/workspace.json` while the service is
stopped. Use an absolute `repository` directory, explicit relative `files`, and
`test_commands` as argv arrays. Example:

```json
{
  "name": "Calculator acceptance project",
  "repository": "D:/AgentOS/samples/calculator",
  "files": ["calculator.py", "test_calculator.py", "README.md"],
  "test_commands": [["python", "-m", "unittest", "discover", "-v"]],
  "test_timeout_seconds": 30
}
```

The `python` runner uses the server's interpreter; specify an absolute runner path
for another installed environment. Dependencies must already be installed. No
automatic dependency installation or model-selected command execution occurs.

## Acceptance walkthrough

1. Confirm the model and Calculator workspace appear in Mission Control with no
   missing-configuration notice. In Agents & roles, inspect Developer's three agents.
2. Optionally add a workspace note: “Preserve the existing addition test assertions.”
   Relevant notes and selected source files are sent to the configured model.
3. Create a mission: “Investigate and fix incorrect addition in calculator.py.
   Preserve all existing test assertions and explain the cause.”
4. Select **Run mission**. Follow task states and Activity. The two model-backed
   agents investigate and generate a patch; the testing agent runs the configured
   command in a fresh scratch checkout. The app does not silently substitute fixtures.
5. Inspect `findings.md`, `proposed.diff`, `change-summary.md`, `tested.diff`, and
   `test-report.txt`. The review gate identifies its attempt and bound artifacts.
   Confirm the diff fixes subtraction and the actual report shows all three tests
   passing. Failed tests are labelled failed; accepting a result does not alter that.
6. At the review gate, accept the result. The mission becomes completed without
   rerunning completed tasks. Alternatively deny it, then explicitly retry the
   failed review task and run again. This reruns tests, not patch generation.
7. Save an artifact reference to memory. Stop and restart the service; verify the
   same mission, artifacts, activity, decision, and notes remain available.
   For longer histories, use **Load more artifacts** to browse additional results.
   Activity polls from its last loaded event and offers **Load more activity**
   when another full page is available.
8. Confirm the original sample still contains `return left - right` and still fails
   two tests. The workflow changes only scratch files. Apply any accepted patch to
   a real source checkout yourself after review; there is no automatic publication.

## Failure and recovery

Authentication, rate limits, invalid structured output, or a nonapplicable patch
fail the current task with a sanitized failure category. Fix configuration, then
explicitly retry that task and run the mission. Retries use the original snapshot.
Create a new mission to capture changed source. Interrupted runs retain a claim;
stop the old worker before following the admin recovery procedure in
[workflows.md](workflows.md). No automatic recovery or background worker is claimed.

Only trusted projects should be executed: **scratch directories are not an OS
security sandbox**. Tests run under your user account. The API is local and
single-user; never expose it on the network. Patches are restricted to existing
selected UTF-8 text files. New files, renames, binary edits, and vector/semantic
memory are deferred. See [workflow limits](local-workflow.md).

For frontend development, run the backend on port 8000 and `npm --prefix frontend
run dev`; open the Vite loopback URL ending in `/app/`. The dev proxy preserves
Host/Origin and calls the same API. Production uses the built client served by
FastAPI, with no separate frontend service.
