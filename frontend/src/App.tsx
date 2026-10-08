import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, date, errorMessage } from './api';
import type { Agent, Mission, Role, Status } from './api';

import { Badge, ErrorNotice } from './components';
import { MissionDetail } from './MissionDetail';
import { Memory } from './Memory';

export function App() {
  const [page, setPage] = useState<'missions' | 'memory' | 'agents'>('missions');
  const [status, setStatus] = useState<Status | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [roles, setRoles] = useState<Role[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [error, setError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [goal, setGoal] = useState('');
  const [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const executionMode = useRef<Status['execution_mode'] | undefined>(undefined);
  const refresh = useCallback(async () => {
    try {
      const [s, m, r, a] = await Promise.all([
        api<Status>('/status'),
        api<Mission[]>(`/missions?limit=100&offset=${offset}`),
        api<Role[]>('/roles'),
        api<Agent[]>('/agents'),
      ]);
      if (executionMode.current !== undefined && executionMode.current !== s.execution_mode) {
        setSelected(null);
        setCreating(false);
        setGoal('');
      }
      executionMode.current = s.execution_mode;
      setStatus(s);
      setMissions(m);
      setRoles(r);
      setAgents(a);
      setMore(m.length === 100);
      setConnectionError('');
    } catch (e) {
      setConnectionError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [offset]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  const canWrite = !!status && status.user_role !== 'viewer';
  const demo = status?.execution_mode === 'demo';
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const mission = await api<Mission>('/workflows/developer', { goal: goal.trim() });
      setOffset(0);
      setSelected(mission.id);
      setCreating(false);
      setGoal('');
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/app/">
          <span className="brand-mark">A</span> AgentOS<span className="version">LOCAL</span>
        </a>
        <div className="workspace-switch">
          <span className="workspace-symbol">W</span>
          <div>
            <small>WORKSPACE</small>
            <strong>{status?.workspace_name ?? 'No project selected'}</strong>
          </div>
        </div>
        <small className="nav-heading">WORKBENCH</small>
        <nav aria-label="Main navigation">
          <button
            className={page === 'missions' ? 'active' : ''}
            onClick={() => setPage('missions')}
          >
            <span>◈</span> Mission Control
          </button>
          <button className={page === 'memory' ? 'active' : ''} onClick={() => setPage('memory')}>
            <span>▤</span> Workspace memory
          </button>
          <button className={page === 'agents' ? 'active' : ''} onClick={() => setPage('agents')}>
            <span>⌘</span> Agents & roles
          </button>
        </nav>
        <div className="sidebar-bottom">
          <span className={`dot ${status && !connectionError ? 'online' : ''}`} />
          {connectionError
            ? 'Local service unavailable'
            : status
              ? 'Local service connected'
              : 'Connecting to service'}
          <small>One workspace. Your control.</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{' '}
            {page === 'missions'
              ? 'Mission Control'
              : page === 'memory'
                ? 'Memory'
                : 'Agents & roles'}
          </span>
          <span className="local-tag">{status?.user_role ?? 'local'} · loopback</span>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">YOUR LOCAL AGENT WORKSPACE</div>
              <h1>
                {page === 'missions'
                  ? 'Mission Control'
                  : page === 'memory'
                    ? 'Workspace memory'
                    : 'Agents & roles'}
              </h1>
              <p>
                {page === 'missions'
                  ? 'Give your agents a goal. Follow the evidence. Review the result.'
                  : page === 'memory'
                    ? 'Project context that stays with your workspace.'
                    : 'Specialized agents, connected by a shared workflow.'}
              </p>
            </div>
            {page === 'missions' && (
              <button
                className="primary"
                disabled={!status?.workflow_ready || !canWrite}
                onClick={() => {
                  setGoal(demo ? (status?.demo_goal ?? '') : '');
                  setCreating(true);
                }}
              >
                + New mission
              </button>
            )}
          </div>
          <ErrorNotice message={connectionError || error} />
          {demo && (
            <div className="setup-notice" role="note">
              <strong>Offline demo — scripted responses, no model calls</strong>
              <p>
                The Calculator findings and patch are scripted. Git checks and tests run locally.
                Demo history and memory are separate from your configured workspace.
              </p>
            </div>
          )}
          {loading ? (
            <div className="empty" role="status">
              Connecting to your local workspace…
            </div>
          ) : (
            <>
              {status && !status.workflow_ready && (
                <div className="setup-notice">
                  <strong>Finish local setup to run your first mission</strong>
                  <p>
                    {!status.workspace_configured &&
                      'Select source files and test commands in workspace configuration. '}
                    {!status.provider_configured &&
                      'Configure a model and provider credentials in the server environment. '}
                    Restart the service after changing configuration.
                  </p>
                  <a
                    href="https://github.com/amg-xai/AgentOS/blob/main/docs/getting-started.md"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open setup guide ↗
                  </a>
                </div>
              )}
              {page === 'missions' && (
                <>
                  <section className="metrics" aria-label="Mission overview">
                    <div>
                      <small>MISSIONS ON THIS PAGE</small>
                      <strong>{missions.length}</strong>
                    </div>
                    <div>
                      <small>AWAITING REVIEW</small>
                      <strong>
                        {missions.filter((m) => m.status === 'WAITING_APPROVAL').length}
                        <span className="metric-hint">Your decision matters</span>
                      </strong>
                    </div>
                    <div>
                      <small>{demo ? 'EXECUTION' : 'MODEL'}</small>
                      <strong className="model-name">
                        {demo ? 'Scripted Calculator' : (status?.model ?? 'Not configured')}
                      </strong>
                    </div>
                  </section>
                  <section className="role-strip">
                    <span className="role-icon">&lt;/&gt;</span>
                    <div>
                      <small>ACTIVE WORKFLOW</small>
                      <strong>Developer</strong>
                      <p>Investigate → propose a patch → run tests → human review</p>
                    </div>
                    <span className="scope-tag">Scratch checkout</span>
                  </section>
                  {creating && (
                    <section className="panel create-panel">
                      <div className="section-heading">
                        <h2>{demo ? 'Try the Calculator demo' : 'Create a Developer mission'}</h2>
                        <button
                          className="text-button"
                          onClick={() => setCreating(false)}
                          disabled={busy}
                        >
                          Close
                        </button>
                      </div>
                      <form onSubmit={create}>
                        <label htmlFor="mission-role">Role package</label>
                        <select id="mission-role" defaultValue="developer">
                          <option value="developer">
                            {roles.find((role) => role.id === 'developer')?.name ?? 'Developer'}
                          </option>
                        </select>
                        <label htmlFor="goal">What should your agents investigate and fix?</label>
                        <textarea
                          id="goal"
                          value={goal}
                          readOnly={demo}
                          onChange={(e) => setGoal(e.target.value)}
                          placeholder="Investigate and fix incorrect addition. Preserve the existing tests."
                          required
                          maxLength={8000}
                          rows={3}
                        />
                        <p className="muted">
                          {demo
                            ? 'Fixed sample scenario. No source files or notes are sent to a model.'
                            : `Selected project: ${status?.workspace_name}. Only configured source files will be sent to the model.`}
                        </p>
                        <button className="primary" disabled={busy || !goal.trim()}>
                          {busy ? 'Creating…' : demo ? 'Create demo mission' : 'Create mission'}
                        </button>
                      </form>
                    </section>
                  )}
                  <div className="mission-layout">
                    <section className="panel mission-list">
                      <div className="section-heading">
                        <h2>Missions</h2>
                        <span className="count">{missions.length}</span>
                      </div>
                      {!missions.length && (
                        <div className="empty">
                          <span className="empty-symbol">◈</span>
                          <h3>Your next idea starts here</h3>
                          <p>Create a mission to turn a project issue into a reviewed patch.</p>
                        </div>
                      )}
                      {missions.map((m) => (
                        <button
                          key={m.id}
                          className={`mission-item ${selected === m.id ? 'selected' : ''}`}
                          onClick={() => setSelected(m.id)}
                        >
                          <Badge state={m.status} />
                          <strong>{m.goal}</strong>
                          <small>{date(m.created_at)}</small>
                          <span className="task-progress">
                            {m.tasks.filter((t) => t.status === 'COMPLETED').length}/
                            {m.tasks.length} tasks complete
                          </span>
                        </button>
                      ))}
                      {(offset > 0 || more) && (
                        <div className="pagination">
                          <button
                            disabled={!offset}
                            onClick={() => setOffset((o) => Math.max(0, o - 100))}
                          >
                            Previous
                          </button>
                          <button disabled={!more} onClick={() => setOffset((o) => o + 100)}>
                            Next
                          </button>
                        </div>
                      )}
                    </section>
                    {selected ? (
                      <MissionDetail
                        key={selected}
                        id={selected}
                        canWrite={canWrite}
                        demo={demo}
                        onChange={refresh}
                      />
                    ) : (
                      <section className="panel empty detail-placeholder">
                        <span className="empty-symbol">↗</span>
                        <h3>A clear view of the work</h3>
                        <p>
                          Select a mission to inspect tasks, artifacts, activity, and approvals.
                        </p>
                      </section>
                    )}
                  </div>
                </>
              )}
              {page === 'memory' && (
                <Memory key={status?.execution_mode} canWrite={canWrite} demo={demo} />
              )}
              {page === 'agents' && (
                <>
                  <section className="panel package">
                    <div className="eyebrow">INSTALLED PACKAGE</div>
                    {roles.map((r) => (
                      <div key={r.id}>
                        <h2>{r.name}</h2>
                        <p>{r.description}</p>
                        <span className="scope-tag">{r.agents.length} registered agents</span>
                      </div>
                    ))}
                  </section>
                  <div className="agent-grid">
                    {agents.map((a) => (
                      <article className="panel agent-card" key={a.id}>
                        <span className="agent-symbol">{a.name.slice(0, 1)}</span>
                        <h2>{a.name}</h2>
                        <p>{a.description}</p>
                        <small>PERMISSIONS</small>
                        <div className="chips">
                          {a.permissions.map((p) => (
                            <span key={p}>{p.toLowerCase()}</span>
                          ))}
                        </div>
                        <small>REGISTERED TOOLS</small>
                        <p className="mono">{a.tools.join(' · ')}</p>
                      </article>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
          <footer>
            AgentOS <span>Local execution · Durable history · Human review</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
