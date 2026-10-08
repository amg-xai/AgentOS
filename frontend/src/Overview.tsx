import type { AgentActivity, Overview } from './api';
import { date, label } from './api';
import { Badge } from './components';

export function WorkspaceOverview({
  overview,
  stale,
  onOpen,
}: {
  overview: Overview | null;
  stale: boolean;
  onOpen: (id: string) => void;
}) {
  if (!overview)
    return <p role="status">Workspace overview unavailable. Waiting for a successful refresh.</p>;
  return (
    <section aria-label="Workspace overview" className="workspace-overview">
      <p className="muted">
        {stale ? 'Last successful snapshot' : 'Workspace snapshot'} · {date(overview.observed_at)}
      </p>
      <section className="metrics" aria-label="Workspace totals">
        <div>
          <small>TOTAL MISSIONS</small>
          <strong>{overview.total_missions}</strong>
        </div>
        <div>
          <small>PENDING RESULT REVIEWS</small>
          <strong>{overview.pending_approvals}</strong>
        </div>
        <div>
          <small>TOTAL ARTIFACTS</small>
          <strong>{overview.total_artifacts}</strong>
        </div>
      </section>
      <p className="muted">
        {overview.local_active_runs} active runs on this server · {overview.durable_claims} durable
        execution claims. Claims and recorded task states do not confirm live execution.
      </p>
      <dl className="state-totals" aria-label="Mission states">
        {Object.entries(overview.mission_counts).map(([state, count]) => (
          <div key={state}>
            <dt>{label(state)}</dt>
            <dd>{count}</dd>
          </div>
        ))}
      </dl>
      <div className="overview-lists">
        <section className="panel" aria-label="Recent waiting reviews">
          <h2>Recent waiting reviews</h2>
          <p className="muted">Up to 10 missions, most recently updated first.</p>
          {!overview.recent_reviews.length && <p>No missions waiting for review.</p>}
          <ul className="activity-list">
            {overview.recent_reviews.map((mission) => (
              <li key={mission.id}>
                <strong>{mission.goal}</strong>
                <small>
                  {mission.role_id} · {date(mission.updated_at)}
                  {mission.has_claim ? ' · execution claim retained' : ''}
                </small>
                <button
                  className="text-button"
                  onClick={() => onOpen(mission.id)}
                  aria-label={`Open mission: ${mission.goal}`}
                >
                  Open mission
                </button>
              </li>
            ))}
          </ul>
        </section>
        <section className="panel" aria-label="Recent artifacts">
          <h2>Recent artifacts</h2>
          <p className="muted">
            Up to 10 most recently recorded files. Open their mission to inspect and download
            verified content.
          </p>
          {!overview.recent_artifacts.length && <p>No artifacts recorded.</p>}
          <ul className="activity-list">
            {overview.recent_artifacts.map((artifact) => (
              <li key={artifact.id}>
                <strong>{artifact.name}</strong>
                <small>
                  {artifact.size} bytes
                  {artifact.created_at ? ` · ${date(artifact.created_at)}` : ''}
                </small>
                <button
                  className="text-button"
                  onClick={() => onOpen(artifact.mission_id)}
                  aria-label={`Open mission for artifact: ${artifact.name}`}
                >
                  Open mission
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </section>
  );
}

export function RecordedActivity({
  activity,
  unavailable,
  stale,
  onOpen,
}: {
  activity?: AgentActivity;
  unavailable: boolean;
  stale: boolean;
  onOpen: (id: string) => void;
}) {
  return (
    <section aria-label="Recorded task activity">
      <h3>Recorded task activity</h3>
      <p className="muted">
        Persisted history; task states do not establish agent availability.
        {stale ? ' Showing the last successful snapshot.' : ''}
      </p>
      {unavailable ? (
        <p>Activity unavailable. Waiting for a successful refresh.</p>
      ) : (
        <>
          <p>
            {Object.values(activity?.task_counts ?? {}).reduce(
              (sum, count) => sum + (count ?? 0),
              0,
            )}{' '}
            recorded tasks · {activity?.task_counts.RUNNING ?? 0} recorded as running
          </p>
          {!activity?.recent_tasks.length && <p>No recorded tasks for this installed agent.</p>}
          <ul className="activity-list">
            {activity?.recent_tasks.map((task) => (
              <li key={`${task.mission_id}/${task.task_id}`}>
                <strong>{task.title}</strong>
                <Badge state={task.status} />
                <small>
                  Mission updated {date(task.mission_updated_at)}
                  {task.has_claim ? ' · execution claim retained' : ''}
                </small>
                <button
                  className="text-button"
                  onClick={() => onOpen(task.mission_id)}
                  aria-label={`Open mission: ${task.mission_goal}`}
                >
                  {task.mission_goal}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
