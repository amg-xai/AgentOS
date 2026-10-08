import { useCallback, useEffect, useState } from 'react';
import { api, artifactText, date, errorMessage, label } from './api';
import type { Activity, Approval, Artifact, Mission } from './api';
import { Badge, ErrorNotice } from './components';
export function MissionDetail({
  id,
  canWrite,
  onChange,
}: {
  id: string;
  canWrite: boolean;
  onChange: () => Promise<void>;
}) {
  const [mission, setMission] = useState<Mission | null>(null);
  const [events, setEvents] = useState<Activity[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [claim, setClaim] = useState<unknown>(null);
  const [tab, setTab] = useState<'tasks' | 'artifacts' | 'activity'>('tasks');
  const [artifact, setArtifact] = useState<string>('');
  const [text, setText] = useState('');
  const [artifactError, setArtifactError] = useState('');
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    try {
      const base = `/missions/${encodeURIComponent(id)}`;
      const [m, e, a, p, c] = await Promise.all([
        api<Mission>(base),
        api<Activity[]>(`${base}/events?limit=1000`),
        api<Artifact[]>(`${base}/artifacts`),
        api<Approval[]>(`${base}/approvals`),
        api<unknown>(`${base}/run`),
      ]);
      setMission(m);
      setEvents(e);
      setArtifacts(a);
      setApprovals(p);
      setClaim(c);
      setArtifact(
        (current) =>
          current || a.find((item) => item.name === 'proposed.diff')?.id || a[0]?.id || '',
      );
    } catch (e) {
      setError(errorMessage(e));
    }
  }, [id]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  useEffect(() => {
    if (!artifact) return;
    const controller = new AbortController();
    setArtifactLoading(true);
    setText('');
    setArtifactError('');
    setSaved(false);
    artifactText(artifact, controller.signal)
      .then(setText)
      .catch((e) => {
        if (!controller.signal.aborted) setArtifactError(errorMessage(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setArtifactLoading(false);
      });
    return () => controller.abort();
  }, [artifact]);
  async function action(path: string, body: Record<string, unknown> = {}) {
    if (!mission) return;
    setBusy(true);
    setError('');
    try {
      await api(path, { expected_version: mission.version, ...body });
    } catch (e) {
      setError(errorMessage(e));
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
        <ErrorNotice message={error} />
        <p role="status">Loading mission…</p>
      </section>
    );
  const test = mission.tasks.find((t) => typeof t.outputs?.passed === 'boolean');
  const canRun = ['PENDING', 'RUNNING'].includes(mission.status) && !claim;
  return (
    <section className="panel detail">
      <div className="section-heading">
        <span className="eyebrow">DEVELOPER MISSION</span>
        <Badge state={mission.status} />
      </div>
      <h2 className="mission-goal">{mission.goal}</h2>
      <p className="muted mono">
        {id.slice(0, 8)} · revision {mission.version}
      </p>
      <ErrorNotice message={error} />
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
      {test && (
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
            Inspect the diff and test report. Acceptance records this result; it does not change the
            source project or publish anything.
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
              const preferred = review.find((a) => a.name === 'tested.diff') ?? review[0];
              if (preferred) setArtifact(preferred.id);
              setTab('artifacts');
            }}
          >
            Inspect artifacts →
          </button>
          <div className="approval-actions">
            <button
              className="primary"
              disabled={busy || !canWrite}
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
        </div>
      ))}
      <div className="tabs" role="tablist" aria-label="Mission details">
        {(['tasks', 'artifacts', 'activity'] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
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
      {tab === 'tasks' && (
        <div className="task-list">
          {mission.tasks.map((t, index) => (
            <article className="task" key={t.id}>
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
                  {t.dependencies.length > 0 && ` · after ${t.dependencies.join(', ')}`}
                </p>
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
      )}
      {tab === 'artifacts' && (
        <div className="artifact-panel">
          {!artifacts.length ? (
            <div className="empty">Artifacts will appear as agents finish their work.</div>
          ) : (
            <>
              <label htmlFor="artifact">Result artifact</label>
              <select id="artifact" value={artifact} onChange={(e) => setArtifact(e.target.value)}>
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
              <ErrorNotice message={artifactError} />
              {artifactLoading ? (
                <p role="status">Verifying and loading artifact…</p>
              ) : (
                <pre className="artifact-content">{text}</pre>
              )}
              <p className="muted mono hash">
                SHA-256 {artifacts.find((a) => a.id === artifact)?.sha256}
              </p>
              <button onClick={() => void saveReference()} disabled={!canWrite || saving}>
                {saving ? 'Saving reference…' : 'Save artifact reference to memory'}
              </button>
              {saved && <p role="status">Saved to workspace memory.</p>}
            </>
          )}
        </div>
      )}
      {tab === 'activity' && (
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
      )}
    </section>
  );
}
