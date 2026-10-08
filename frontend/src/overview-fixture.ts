import type { Overview } from './api';

export function overviewFixture(execution_mode: 'live' | 'demo' = 'live'): Overview {
  return {
    observed_at: '2026-10-09T00:00:00Z',
    execution_mode,
    local_active_runs: 0,
    total_missions: 0,
    mission_counts: {
      PENDING: 0,
      RUNNING: 0,
      WAITING_APPROVAL: 0,
      BLOCKED: 0,
      FAILED: 0,
      COMPLETED: 0,
      CANCELLED: 0,
    },
    pending_approvals: 0,
    durable_claims: 0,
    total_artifacts: 0,
    recent_reviews: [],
    recent_artifacts: [],
    agent_activity: [],
  };
}
