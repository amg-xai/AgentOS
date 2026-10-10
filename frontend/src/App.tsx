import { useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { api, date, errorMessage } from './api';
import type {
  Agent,
  Mission,
  Overview,
  Role,
  Status,
  SourceText,
  Workflow,
  StudySettings,
} from './api';
import { StudySettingsForm } from './StudySettingsForm';
import { CreatorSources } from './CreatorSources';

import { Badge, ErrorNotice } from './components';
import { MissionDetail } from './MissionDetail';
import { Memory } from './Memory';
import { RecordedActivity, WorkspaceOverview } from './Overview';
import { emptyHistoryQuery, HistoryFilters } from './HistoryFilters';
import type { HistoryQuery } from './HistoryFilters';

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
  const [includeThumbnail, setIncludeThumbnail] = useState(false);
  const [sources, setSources] = useState<SourceText[]>([]);
  const [studySettings, setStudySettings] = useState<StudySettings | null>(null);
  const [roleId, setRoleId] = useState('developer');
  const [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [filters, setFilters] = useState<HistoryQuery>(emptyHistoryQuery);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState('');
  const hasFilters = !!(filters.query || filters.role_id || filters.status);
  const [overview, setOverview] = useState<Overview | null>(null);
  const requestVersion = useRef(0);
  const refreshController = useRef<AbortController | null>(null);
  const executionMode = useRef<Status['execution_mode'] | undefined>(undefined);
  const modeGeneration = useRef(0);
  const refresh = useCallback(
    async (listOffset = offset) => {
      const version = ++requestVersion.current;
      refreshController.current?.abort();
      const controller = new AbortController();
      refreshController.current = controller;
      try {
        const s = await api<Status>('/status', undefined, controller.signal);
        if (version !== requestVersion.current) return;
        if (executionMode.current !== undefined && executionMode.current !== s.execution_mode) {
          modeGeneration.current++;
          setSelected(null);
          setCreating(false);
          setGoal('');
          setSources([]);
          setIncludeThumbnail(false);
          setStudySettings(null);
          setError('');
          setOverview(null);
          setMissions([]);
          setAgents([]);
          setRoles([]);
          setMore(false);
          setFilters(emptyHistoryQuery);
          setHistoryLoading(true);
          setHistoryError('');
          if (listOffset !== 0 || filters.query || filters.role_id || filters.status) {
            executionMode.current = s.execution_mode;
            setStatus(s);
            setOffset(0);
            return;
          }
        }
        executionMode.current = s.execution_mode;
        setStatus(s);
        const params = new URLSearchParams({ limit: '100', offset: String(listOffset) });
        if (filters.query) params.set('query', filters.query);
        if (filters.role_id) params.set('role_id', filters.role_id);
        if (filters.status) params.set('status', filters.status);
        const [m, r, a, o] = await Promise.all([
          api<Mission[]>(`/missions?${params}`, undefined, controller.signal),
          api<Role[]>('/roles', undefined, controller.signal),
          api<Agent[]>('/agents', undefined, controller.signal),
          api<Overview>('/overview', undefined, controller.signal),
        ]);
        if (version !== requestVersion.current) return;
        if (o.execution_mode !== s.execution_mode) {
          modeGeneration.current++;
          setSelected(null);
          setCreating(false);
          setGoal('');
          setSources([]);
          setIncludeThumbnail(false);
          setStudySettings(null);
          setError('');
          setOverview(null);
          setMissions([]);
          setAgents([]);
          setRoles([]);
          setStatus(null);
          setMore(false);
          setOffset(0);
          setFilters(emptyHistoryQuery);
          setHistoryLoading(true);
          setHistoryError('');
          throw new Error(
            'Server execution mode changed during refresh. Waiting for a consistent snapshot.',
          );
        }
        setMissions(m);
        setRoles(r);
        setAgents(a);
        setMore(m.length === 100);
        setOverview(o);
        setConnectionError('');
        setHistoryError('');
        setHistoryLoading(false);
      } catch (e) {
        if (version !== requestVersion.current) return;
        setConnectionError(errorMessage(e));
        setHistoryError(errorMessage(e));
        setHistoryLoading(false);
      } finally {
        if (version === requestVersion.current) setLoading(false);
      }
    },
    [offset, filters],
  );
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 5000);
    return () => {
      window.clearInterval(timer);
      requestVersion.current++;
      refreshController.current?.abort();
    };
  }, [refresh]);
  const canWrite = !!status && status.user_role !== 'viewer';
  const demo = status?.execution_mode === 'demo';
  const workflows: Workflow[] = status?.workflows ?? [
    {
      role_id: 'developer',
      name: 'Developer',
      ready: !!status?.workflow_ready,
      reason: '',
      steps: 'Investigate → propose a patch → run tests → human review',
      context_notice: `Selected project: ${status?.workspace_name}. Only configured source files will be sent to the model.`,
      demo_goal: status?.demo_goal ?? null,
    },
  ];
  const workflow = workflows.find((item) => item.role_id === roleId);
  useEffect(() => {
    if (status?.workflows && !status.workflows.some((item) => item.role_id === roleId)) {
      const first = status.workflows.find((item) => item.ready) ?? status.workflows[0];
      if (first) {
        modeGeneration.current++;
        setSources([]);
        setIncludeThumbnail(false);
        setStudySettings(null);
        setRoleId(first.role_id);
        setGoal(first.demo_goal ?? '');
      }
    }
  }, [status, roleId]);
  function selectRole(value: string) {
    modeGeneration.current++;
    setSources([]);
    setIncludeThumbnail(false);
    setStudySettings(null);
    setRoleId(value);
    setGoal(demo ? (workflows.find((item) => item.role_id === value)?.demo_goal ?? '') : '');
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const generation = modeGeneration.current;
    try {
      if (!workflow?.ready || !canWrite) return;
      const sourceContext =
        (roleId === 'creator' || roleId === 'student') &&
        !demo &&
        workflow.source_research_ready &&
        sources.length > 0;
      if (
        sourceContext &&
        (sources.some((source) => !source.label.trim() || !source.body.trim()) ||
          sources.reduce((sum, source) => sum + [...source.body].length, 0) > 48000)
      ) {
        throw new Error('Provide nonblank source labels and text within 48,000 total characters.');
      }
      if (
        roleId === 'student' &&
        studySettings &&
        (!Number.isInteger(studySettings.total_minutes) ||
          studySettings.total_minutes < 10 ||
          studySettings.total_minutes > 240 ||
          !Number.isInteger(studySettings.max_session_minutes) ||
          studySettings.max_session_minutes < 10 ||
          studySettings.max_session_minutes > 60)
      ) {
        throw new Error('Use whole minutes: 10–240 available and 10–60 per session.');
      }
      const mission = await api<Mission>(`/workflows/${encodeURIComponent(roleId)}`, {
        goal: goal.trim(),
        ...(sourceContext ? { sources } : {}),
        ...(roleId === 'creator' && !demo && workflow.thumbnail_ready && includeThumbnail
          ? { include_thumbnail: true }
          : {}),
        ...(roleId === 'student' && !demo && workflow.study_planning_ready && studySettings
          ? { study_settings: studySettings }
          : {}),
      });
      if (generation !== modeGeneration.current) return;
      setOffset(0);
      setSelected(mission.id);
      setCreating(false);
      setGoal('');
      setSources([]);
      setIncludeThumbnail(false);
      setStudySettings(null);
      await refresh(0);
    } catch (e) {
      if (generation === modeGeneration.current) setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  function openMission(id: string) {
    modeGeneration.current++;
    setSources([]);
    setIncludeThumbnail(false);
    setStudySettings(null);
    setSelected(id);
    setPage('missions');
    setCreating(false);
  }
  function applyFilters(next: HistoryQuery) {
    requestVersion.current++;
    refreshController.current?.abort();
    setFilters({ ...next });
    setOffset(0);
    setMissions([]);
    setMore(false);
    setHistoryLoading(true);
    setHistoryError('');
  }
  function changePage(next: number) {
    requestVersion.current++;
    refreshController.current?.abort();
    setOffset(next);
    setMissions([]);
    setMore(false);
    setHistoryLoading(true);
    setHistoryError('');
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
                disabled={!workflow?.ready || !canWrite}
                onClick={() => {
                  modeGeneration.current++;
                  setSources([]);
                  setIncludeThumbnail(false);
                  setStudySettings(null);
                  setGoal(demo ? (workflow?.demo_goal ?? '') : '');
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
                Demo responses are scripted. Developer runs actual Git checks and tests; Creator and
                Student produce content fixtures. Demo history and memory are separate from your
                configured workspace.
              </p>
            </div>
          )}
          {loading ? (
            <div className="empty" role="status">
              Connecting to your local workspace…
            </div>
          ) : (
            <>
              {status && !workflow?.ready && (
                <div className="setup-notice">
                  <strong>Finish local setup to run your first mission</strong>
                  <p>
                    {workflow?.reason && `${workflow.reason} `}
                    {roleId === 'developer' &&
                      !status.workspace_configured &&
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
                  <WorkspaceOverview
                    overview={overview}
                    stale={!!connectionError}
                    onOpen={openMission}
                  />
                  <p className="muted">
                    {demo ? (
                      'Scripted workflows'
                    ) : (
                      <>
                        Model: <strong>{status?.model ?? 'Not configured'}</strong>
                      </>
                    )}
                  </p>
                  <section className="role-strip">
                    <span className="role-icon">&lt;/&gt;</span>
                    <div>
                      <small>ACTIVE WORKFLOW</small>
                      <label htmlFor="workflow-role">Workflow</label>
                      <select
                        id="workflow-role"
                        value={roleId}
                        onChange={(e) => selectRole(e.target.value)}
                      >
                        {workflows.map((item) => (
                          <option key={item.role_id} value={item.role_id}>
                            {item.name}
                            {item.ready ? '' : ' · setup required'}
                          </option>
                        ))}
                      </select>
                      <p>{workflow?.steps ?? 'No executable workflow is installed.'}</p>
                    </div>
                    <span className="scope-tag">
                      {roleId === 'developer' ? 'Scratch checkout' : 'Content only'}
                    </span>
                  </section>
                  {creating && (
                    <section className="panel create-panel">
                      <div className="section-heading">
                        <h2>
                          {demo
                            ? `Try the ${workflow?.name} demo`
                            : `Create a ${workflow?.name} mission`}
                        </h2>
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
                        <select
                          id="mission-role"
                          value={roleId}
                          onChange={(e) => selectRole(e.target.value)}
                        >
                          {workflows.map((item) => (
                            <option key={item.role_id} value={item.role_id}>
                              {item.name}
                              {item.ready ? '' : ' · setup required'}
                            </option>
                          ))}
                        </select>
                        <label htmlFor="goal">
                          {roleId === 'student'
                            ? 'What material should your study notes and quiz cover?'
                            : roleId === 'creator'
                              ? 'What should your video script cover?'
                              : 'What should your agents investigate and fix?'}
                        </label>
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
                            : workflow?.context_notice}
                        </p>
                        {!demo && roleId === 'creator' && workflow?.thumbnail_ready && (
                          <label>
                            <input
                              type="checkbox"
                              checked={includeThumbnail}
                              disabled={busy || !canWrite}
                              onChange={(event) => setIncludeThumbnail(event.target.checked)}
                            />{' '}
                            Include a graphic thumbnail
                            <span className="muted">
                              {' '}
                              Local text and geometry PNG; printable ASCII text only. No
                              photographic synthesis or publication.
                            </span>
                          </label>
                        )}
                        {!demo &&
                          (roleId === 'creator' || roleId === 'student') &&
                          workflow?.source_research_ready && (
                            <CreatorSources
                              purpose={roleId === 'student' ? 'study summarization' : 'outlining'}
                              sources={sources}
                              onChange={setSources}
                              disabled={busy || !canWrite}
                            />
                          )}
                        {!demo && roleId === 'student' && workflow?.study_planning_ready && (
                          <StudySettingsForm
                            settings={studySettings}
                            onChange={setStudySettings}
                            disabled={busy || !canWrite}
                          />
                        )}
                        <button
                          className="primary"
                          disabled={busy || !goal.trim() || !workflow?.ready || !canWrite}
                        >
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
                      <HistoryFilters
                        key={status?.execution_mode}
                        filters={filters}
                        roles={roles}
                        onApply={applyFilters}
                      />
                      <p className="muted">
                        {hasFilters ? 'Matching missions' : 'Missions'} on this page:{' '}
                        {missions.length}
                      </p>
                      {historyLoading && <p role="status">Loading mission history…</p>}
                      {!!historyError && (
                        <p role="status">
                          Mission history refresh failed.{' '}
                          {missions.length
                            ? 'Showing the last successful results for these filters.'
                            : 'Results are unavailable; retry Apply filters.'}
                        </p>
                      )}
                      {!historyLoading && !historyError && !missions.length && (
                        <div className="empty">
                          <span className="empty-symbol">◈</span>
                          <h3>
                            {hasFilters ? 'No matching missions' : 'Your next idea starts here'}
                          </h3>
                          <p>
                            {hasFilters
                              ? 'Try another goal, role, or state, or clear the filters.'
                              : 'Create a mission to turn a goal into a reviewed result.'}
                          </p>
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
                            disabled={!offset || historyLoading}
                            onClick={() => changePage(Math.max(0, offset - 100))}
                          >
                            Previous
                          </button>
                          <button
                            disabled={!more || historyLoading}
                            onClick={() => changePage(offset + 100)}
                          >
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
                        onChange={() => refresh()}
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
                <Memory
                  key={status?.execution_mode}
                  canWrite={canWrite}
                  demo={demo}
                  onOpenMission={openMission}
                />
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
                        <RecordedActivity
                          activity={overview?.agent_activity.find((item) => item.agent_id === a.id)}
                          unavailable={!overview}
                          stale={!!connectionError}
                          onOpen={openMission}
                        />
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
