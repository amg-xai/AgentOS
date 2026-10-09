import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { api, artifactText, date, errorMessage, label } from './api';
import type { Activity, Approval, Artifact, Mission, PatchRevisionStatus } from './api';
import { Badge, ErrorNotice } from './components';
import { TaskDependencies } from './TaskDependencies';
export function MissionDetail({
  id,
  canWrite,
  onChange,
  demo = false,
}: {
  id: string;
  canWrite: boolean;
  onChange: () => Promise<void>;
  demo?: boolean;
}) {
  const [mission, setMission] = useState<Mission | null>(null);
  const [events, setEvents] = useState<Activity[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [revision, setRevision] = useState<PatchRevisionStatus | null>(null);
  const [feedback, setFeedback] = useState('');
  const [claim, setClaim] = useState<unknown>(null);
  const [tab, setTab] = useState<'tasks' | 'artifacts' | 'activity'>('tasks');
  const tabs = ['tasks', 'artifacts', 'activity'] as const;
  const tabId = useId();
  const taskDetails = useRef(new Map<string, HTMLElement>());
  const tabButtons = useRef<Partial<Record<(typeof tabs)[number], HTMLButtonElement | null>>>({});
  const [artifact, setArtifact] = useState<string>('');
  const [text, setText] = useState('');
  const [artifactError, setArtifactError] = useState('');
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [refreshError, setRefreshError] = useState('');
  const [busy, setBusy] = useState(false);
  const [artifactPages, setArtifactPages] = useState(1);
  const [moreArtifacts, setMoreArtifacts] = useState(false);
  const [moreEvents, setMoreEvents] = useState(false);
  const eventCursor = useRef(0);
  const refreshNumber = useRef(0);
  const refresh = useCallback(async () => {
    const requestNumber = ++refreshNumber.current;
    try {
      const base = `/missions/${encodeURIComponent(id)}`;
      const [m, e, pages, p, c] = await Promise.all([
        api<Mission>(base),
        api<Activity[]>(`${base}/events?limit=1000&after=${eventCursor.current}`),
        Promise.all(
          Array.from({ length: artifactPages }, (_, page) =>
            api<Artifact[]>(`${base}/artifacts?limit=100&offset=${page * 100}`),
          ),
        ),
        api<Approval[]>(`${base}/approvals`),
        api<unknown>(`${base}/run`),
      ]);
      const a = pages.flat();
      // Current review artifacts must remain inspectable beyond the history page.
      const missing = [...new Set(p.flatMap((item) => item.payload?.artifact_refs ?? []))].filter(
        (ref) => !a.some((item) => item.id === ref),
      );
      const reviewArtifacts = await Promise.all(
        missing.map((ref) => api<Artifact>(`/artifacts/${encodeURIComponent(ref)}`)),
      );
      const revisionStatus =
        !demo &&
        m.role_id === 'developer' &&
        m.planning?.contract_version === 2 &&
        m.status === 'FAILED' &&
        m.tasks.some((task) => task.requires_passed_tests && task.outputs?.passed === false)
          ? await api<PatchRevisionStatus>(`${base}/patch-revision`)
          : null;
      if (requestNumber !== refreshNumber.current) return;
      setRevision(revisionStatus);
      setMission(m);
      setEvents((current) =>
        [...new Map([...current, ...e].map((item) => [item.sequence, item])).values()].sort(
          (left, right) => left.sequence - right.sequence,
        ),
      );
      if (e.length) eventCursor.current = e[e.length - 1].sequence;
      setMoreEvents(e.length === 1000);
      setMoreArtifacts(pages[pages.length - 1].length === 100);
      setArtifacts((current) => [
        ...new Map([...current, ...a, ...reviewArtifacts].map((item) => [item.id, item])).values(),
      ]);
      setApprovals(p);
      setClaim(c);
      setRefreshError('');
      setArtifact(
        (current) =>
          current || a.find((item) => item.name === 'proposed.diff')?.id || a[0]?.id || '',
      );
    } catch (e) {
      if (requestNumber === refreshNumber.current) setRefreshError(errorMessage(e));
    }
  }, [id, artifactPages, demo]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => {
      window.clearInterval(timer);
      refreshNumber.current += 1;
    };
  }, [refresh]);
  useEffect(() => {
    if (!artifact) return;
    const controller = new AbortController();
    setArtifactLoading(true);
    setText('');
    setArtifactError('');
    setSaved(false);
    artifactText(artifact, controller.signal)
      .then((content) => {
        if (!controller.signal.aborted) setText(content);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setArtifactError(errorMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setArtifactLoading(false);
      });
    return () => controller.abort();
  }, [artifact]);
  async function action(path: string, body: Record<string, unknown> = {}) {
    if (!mission) return false;
    setBusy(true);
    setError('');
    try {
      await api(path, { expected_version: mission.version, ...body });
      return true;
    } catch (e) {
      setError(errorMessage(e));
      return false;
    } finally {
      await refresh();
      await onChange();
      setBusy(false);
    }
  }
  async function saveReference() {
    if (!mission) return;
    setSaving(true);
    setSaved(false);
    setError('');
    try {
      await api('/memory', {
        title: `Reviewed artifact: ${artifacts.find((a) => a.id === artifact)?.name}`,
        content: `Mission ${id}: ${mission.goal}`.slice(0, 8000),
        artifact_refs: [artifact],
      });
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  if (!mission)
    return (
      <section className="panel detail">
        <ErrorNotice message={refreshError || error} />
        <p role="status">Loading mission…</p>
      </section>
    );
  const test = mission.tasks.find((t) => typeof t.outputs?.passed === 'boolean');
  const baseline = mission.tasks.find((t) => typeof t.outputs?.baseline_passed === 'boolean');
  const canRun = ['PENDING', 'RUNNING'].includes(mission.status) && !claim;
  const creator = mission.role_id === 'creator';
  const student = mission.role_id === 'student';
  const roleName = creator ? 'CREATOR' : mission.role_id.toUpperCase();
  const selectedArtifact = artifacts.find((a) => a.id === artifact);
  const testsBlockReview = (taskId: string) => {
    const task = mission.tasks.find((item) => item.id === taskId);
    return task?.requires_passed_tests === true && task.outputs?.passed !== true;
  };
  return (
    <section className="panel detail">
      <div className="section-heading">
        <span className="eyebrow">
          {demo
            ? `OFFLINE DEMO ${creator || student ? `${roleName} ` : ''}MISSION`
            : `${roleName} MISSION`}
        </span>
        <Badge state={mission.status} />
      </div>
      <h2 className="mission-goal">{mission.goal}</h2>
      <p className="muted mono">
        {id.slice(0, 8)} · revision {mission.version}
      </p>
      <ErrorNotice message={refreshError || error} />
      {mission.planning && (
        <details className="mission-plan">
          <summary>Inspect validated Developer plan</summary>
          <p>{mission.planning.rationale}</p>
          <p>
            Planner: <code>{mission.planning.planner_id}</code>
          </p>
          <h3>Constraints extracted from your goal</h3>
          {mission.planning.constraints.length ? (
            <ul>
              {mission.planning.constraints.map((constraint, index) => (
                <li key={index}>{constraint}</li>
              ))}
            </ul>
          ) : (
            <p>No additional constraints were extracted. Review the original goal above.</p>
          )}
          <p>
            Inspect each task's objective, assigned agent, and dependency inputs in the Tasks tab.
          </p>
          <details>
            <summary>Inspect planning data</summary>
            <pre>{JSON.stringify(mission.planning, null, 2)}</pre>
          </details>
        </details>
      )}
      {claim && !busy ? (
        <div className="info">
          This mission has an execution claim. If its worker was interrupted, stop that worker and
          use the documented admin recovery procedure.
        </div>
      ) : null}
      <div className="mission-actions">
        {canRun && (
          <button
            className="primary"
            disabled={busy || !canWrite}
            onClick={() => void action(`/missions/${id}/run`)}
          >
            {busy ? 'Agents are working…' : 'Run mission'}
          </button>
        )}
        {busy && (
          <span role="status" className="muted">
            Working… history updates as tasks progress.
          </span>
        )}
        {!['COMPLETED', 'CANCELLED'].includes(mission.status) && !claim && (
          <button
            disabled={busy || !canWrite}
            onClick={() => void action(`/missions/${id}/cancel`)}
          >
            Cancel mission
          </button>
        )}
      </div>
      {baseline && mission.role_id === 'developer' && (
        <div className={`test-result ${baseline.outputs?.baseline_passed ? 'pass' : 'fail'}`}>
          <strong>
            {baseline.outputs?.baseline_passed ? 'Baseline tests passed' : 'Baseline tests failed'}
          </strong>
          <p>
            Actual tests on the immutable source before the proposed patch. See the baseline report
            for evidence.
          </p>
        </div>
      )}
      {test && mission.role_id === 'developer' && (
        <div className={`test-result ${test.outputs?.passed ? 'pass' : 'fail'}`}>
          <strong>{test.outputs?.passed ? 'Tests passed' : 'Tests failed'}</strong>
          <span>Actual configured test execution. Inspect the report before accepting.</span>
        </div>
      )}
      {approvals.map((p) => (
        <div className="approval" key={p.id}>
          <div className="eyebrow">HUMAN REVIEW REQUIRED</div>
          <h3>The result is ready for your review</h3>
          <p>
            {student
              ? mission.tasks.some((task) => task.agent_id === 'student_focus')
                ? 'Inspect the study plan, original time settings, quiz, answer key, and reviewed notes. Durations are suggested effort. Acceptance records content review; it does not verify correctness, completed study, or exam readiness.'
                : 'Inspect the quiz, answer key, and reviewed notes. Acceptance records review of this material; it does not verify correctness or exam readiness.'
              : creator
                ? mission.tasks.some((task) => task.agent_id === 'creator_research')
                  ? 'Inspect the script, reviewed outline, research, and supplied sources. Quotes establish provenance; source truth and interpretations require your review. Acceptance records this content; it does not publish or send it.'
                  : 'Inspect the script and its reviewed outline. Acceptance records this content; it does not publish or send it.'
                : 'Inspect the diff and test report. Acceptance records this result; it does not change the source project or publish anything.'}
          </p>
          {p.payload?.artifact_refs && (
            <p>
              Review attempt {p.task_attempt}:{' '}
              {p.payload.artifact_refs
                .map((ref) => artifacts.find((a) => a.id === ref)?.name ?? ref)
                .join(', ')}
            </p>
          )}
          <button
            className="text-button"
            onClick={() => {
              const review = artifacts.filter((a) => p.payload?.artifact_refs?.includes(a.id));
              const preferred =
                review.find(
                  (a) =>
                    a.name ===
                    (student
                      ? mission.tasks.some((task) => task.agent_id === 'student_focus')
                        ? 'study-plan.md'
                        : 'quiz.md'
                      : creator
                        ? 'script.md'
                        : 'tested.diff'),
                ) ?? review[0];
              if (preferred) setArtifact(preferred.id);
              setTab('artifacts');
            }}
          >
            Inspect artifacts →
          </button>
          <div className="approval-actions">
            <button
              className="primary"
              disabled={busy || !canWrite || testsBlockReview(p.task_id)}
              onClick={() =>
                void action(`/approvals/${p.id}/decision`, {
                  decision: 'approve',
                  payload_digest: p.payload_digest,
                })
              }
            >
              Accept result
            </button>
            <button
              disabled={busy || !canWrite}
              onClick={() =>
                void action(`/approvals/${p.id}/decision`, {
                  decision: 'deny',
                  payload_digest: p.payload_digest,
                })
              }
            >
              Deny result
            </button>
          </div>
          {testsBlockReview(p.task_id) && (
            <p role="status">
              Tests must explicitly pass before this result can be accepted. Inspect the report,
              then deny and retry if needed.
            </p>
          )}
        </div>
      ))}
      {revision && (
        <div className="approval">
          <h3>Correct the failed patch</h3>
          <p>
            {revision.remaining} revision cycles remaining. A revision preserves the original goal,
            source, and tests. It needs a separate run and fresh human review.
          </p>
          {revision.allowed ? (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!canWrite || busy || !feedback.trim()) return;
                void action(`/missions/${id}/patch-revision`, {
                  approval_id: revision.approval_id,
                  payload_digest: revision.payload_digest,
                  feedback: feedback.trim(),
                }).then((success) => {
                  if (success) setFeedback('');
                });
              }}
            >
              <label htmlFor={`${tabId}-feedback`}>Patch revision feedback</label>
              <textarea
                id={`${tabId}-feedback`}
                required
                maxLength={2000}
                value={feedback}
                disabled={!canWrite || busy}
                onChange={(event) => setFeedback(event.target.value)}
              />
              <p>
                Describe the failure you observed. This feedback and the previous diff will go to
                the patch agent; test logs remain local.
              </p>
              <button disabled={!canWrite || busy || !feedback.trim()}>Revise patch</button>
            </form>
          ) : (
            <p role="status">{revision.reason}</p>
          )}
        </div>
      )}
      {!!mission.developer_revisions?.length && (
        <details>
          <summary>Inspect patch revision evidence</summary>
          <pre>{JSON.stringify(mission.developer_revisions, null, 2)}</pre>
        </details>
      )}
      <div className="tabs" role="tablist" aria-label="Mission details">
        {tabs.map((t, index) => (
          <button
            key={t}
            ref={(element) => {
              tabButtons.current[t] = element;
            }}
            id={`${tabId}-${t}-tab`}
            role="tab"
            aria-selected={tab === t}
            aria-controls={`${tabId}-${t}-panel`}
            tabIndex={tab === t ? 0 : -1}
            onClick={() => setTab(t)}
            onKeyDown={(event) => {
              const next =
                event.key === 'ArrowRight'
                  ? (index + 1) % tabs.length
                  : event.key === 'ArrowLeft'
                    ? (index + tabs.length - 1) % tabs.length
                    : event.key === 'Home'
                      ? 0
                      : event.key === 'End'
                        ? tabs.length - 1
                        : null;
              if (next === null) return;
              event.preventDefault();
              setTab(tabs[next]);
              tabButtons.current[tabs[next]]?.focus();
            }}
          >
            {t}{' '}
            <span>
              {t === 'tasks'
                ? mission.tasks.length
                : t === 'artifacts'
                  ? artifacts.length
                  : events.length}
            </span>
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${tabId}-tasks-panel`}
        aria-labelledby={`${tabId}-tasks-tab`}
        hidden={tab !== 'tasks'}
        tabIndex={0}
      >
        {tab === 'tasks' && (
          <>
            <TaskDependencies
              tasks={mission.tasks}
              onInspect={(taskId) => {
                const detail = taskDetails.current.get(taskId);
                detail?.focus();
                detail?.scrollIntoView?.({ block: 'nearest' });
              }}
            />
            <div className="task-list">
              {mission.tasks.map((t, index) => (
                <article
                  className="task"
                  key={t.id}
                  tabIndex={-1}
                  aria-label={`Task detail: ${t.title} (${t.id})`}
                  ref={(element) => {
                    if (element) taskDetails.current.set(t.id, element);
                    else taskDetails.current.delete(t.id);
                  }}
                >
                  <span className={`task-number ${t.status.toLowerCase()}`}>
                    {t.status === 'COMPLETED' ? '✓' : index + 1}
                  </span>
                  <div>
                    <div className="task-title">
                      <h3>{t.title}</h3>
                      <Badge state={t.status} />
                    </div>
                    <p>
                      {t.agent_id.replaceAll('_', ' ')} · attempt {t.attempts}
                      {Array.isArray(t.dependencies)
                        ? t.dependencies.length > 0 && ` · after ${t.dependencies.join(', ')}`
                        : ' · prerequisites unavailable'}
                    </p>
                    {mission.planning && (
                      <div className="task-plan-evidence">
                        <p>
                          <strong>Objective:</strong>{' '}
                          {mission.planning.objectives[t.id] ?? 'Objective unavailable'}
                        </p>
                        <p>
                          Assigned agent: <code>{t.agent_id}</code>
                        </p>
                        {t.requires_passed_tests && (
                          <p>Human review requires an explicit passing test outcome.</p>
                        )}
                        <details>
                          <summary>Inspect dependency inputs</summary>
                          {t.input_bindings === undefined ? (
                            <p>Input bindings unavailable.</p>
                          ) : Object.keys(t.input_bindings).length === 0 ? (
                            <p>No dependency-bound inputs.</p>
                          ) : (
                            <ul>
                              {Object.entries(t.input_bindings).map(([key, binding]) => {
                                const source = mission.tasks.find(
                                  (task) => task.id === binding.task_id,
                                );
                                return (
                                  <li key={key}>
                                    <code>{key}</code> receives <code>{binding.output_key}</code>{' '}
                                    from{' '}
                                    {source ? (
                                      <button
                                        className="text-button"
                                        onClick={() => {
                                          const detail = taskDetails.current.get(source.id);
                                          detail?.focus();
                                          detail?.scrollIntoView?.({ block: 'nearest' });
                                        }}
                                      >
                                        {source.title} ({source.id})
                                      </button>
                                    ) : (
                                      <span>Unavailable task ({binding.task_id})</span>
                                    )}
                                  </li>
                                );
                              })}
                            </ul>
                          )}
                        </details>
                      </div>
                    )}
                    {t.error && <div className="task-error">{t.error}</div>}
                    {t.outputs && (
                      <details>
                        <summary>Inspect task outputs</summary>
                        <pre>{JSON.stringify(t.outputs, null, 2)}</pre>
                      </details>
                    )}
                    {t.status === 'FAILED' && (
                      <button
                        disabled={busy || !canWrite || !!claim}
                        onClick={() =>
                          void action(`/missions/${id}/tasks/${t.id}/actions`, { action: 'retry' })
                        }
                      >
                        Retry task
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </>
        )}
      </div>
      <div
        role="tabpanel"
        id={`${tabId}-artifacts-panel`}
        aria-labelledby={`${tabId}-artifacts-tab`}
        hidden={tab !== 'artifacts'}
        tabIndex={0}
      >
        {tab === 'artifacts' && (
          <div className="artifact-panel">
            {!artifacts.length ? (
              <div className="empty">Artifacts will appear as agents finish their work.</div>
            ) : (
              <>
                <label htmlFor="artifact">Result artifact</label>
                <select
                  id="artifact"
                  value={artifact}
                  onChange={(e) => setArtifact(e.target.value)}
                >
                  {artifacts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {approvals.some((p) => p.payload?.artifact_refs?.includes(a.id))
                        ? 'Review: '
                        : ''}
                      {a.name} · {a.task_id} · {a.size} bytes ·{' '}
                      {a.created_at ? date(a.created_at) : a.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
                {moreArtifacts && (
                  <button onClick={() => setArtifactPages((current) => current + 1)}>
                    Load more artifacts
                  </button>
                )}
                <ErrorNotice message={artifactError} />
                {artifactLoading ? (
                  <p role="status">Verifying and loading artifact…</p>
                ) : (
                  <pre className="artifact-content">{text}</pre>
                )}
                <p className="muted mono hash">SHA-256 {selectedArtifact?.sha256}</p>
                {selectedArtifact && !artifactLoading && !artifactError && (
                  <p>
                    <a
                      href={`/artifacts/${encodeURIComponent(selectedArtifact.id)}/content`}
                      download={selectedArtifact.name}
                    >
                      Download {selectedArtifact.name}
                    </a>
                  </p>
                )}
                <button onClick={() => void saveReference()} disabled={!canWrite || saving}>
                  {saving ? 'Saving reference…' : 'Save artifact reference to memory'}
                </button>
                {saved && <p role="status">Saved to workspace memory.</p>}
              </>
            )}
          </div>
        )}
      </div>
      <div
        role="tabpanel"
        id={`${tabId}-activity-panel`}
        aria-labelledby={`${tabId}-activity-tab`}
        hidden={tab !== 'activity'}
        tabIndex={0}
      >
        {tab === 'activity' && (
          <>
            {moreEvents && <button onClick={() => void refresh()}>Load more activity</button>}
            <ol className="activity">
              {[...events].reverse().map((e) => (
                <li key={e.sequence}>
                  <span className="activity-dot" />
                  <div>
                    <strong>{label(e.action)}</strong>
                    <p>
                      {e.task_id ?? 'Mission'} · {e.actor}
                    </p>
                    {Object.keys(e.details).length > 0 && (
                      <details>
                        <summary>Event details</summary>
                        <pre>{JSON.stringify(e.details, null, 2)}</pre>
                      </details>
                    )}
                    <small>{date(e.timestamp)}</small>
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}
      </div>
    </section>
  );
}
