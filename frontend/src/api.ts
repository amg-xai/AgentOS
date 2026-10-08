export interface Status {
  execution_mode: 'live' | 'demo';
  execution_label: string;
  demo_goal: string | null;
  provider_configured: boolean;
  model: string | null;
  workspace_configured: boolean;
  workspace_name: string | null;
  workspace_files: string[];
  test_commands: string[][];
  workflow_ready: boolean;
  user_role: 'viewer' | 'operator' | 'admin';
  memory_retrieval: string;
}
export type State =
  | 'PENDING'
  | 'READY'
  | 'RUNNING'
  | 'WAITING_APPROVAL'
  | 'BLOCKED'
  | 'FAILED'
  | 'COMPLETED'
  | 'CANCELLED';
export interface Task {
  id: string;
  title: string;
  agent_id: string;
  status: State;
  attempts: number;
  dependencies: string[];
  outputs: Record<string, unknown> | null;
  error: string | null;
}
export interface Mission {
  id: string;
  goal: string;
  role_id: string;
  status: State;
  version: number;
  created_at: string;
  updated_at: string;
  tasks: Task[];
}
export interface Artifact {
  id: string;
  name: string;
  task_id: string;
  sha256: string;
  size: number;
  created_at?: string;
}
export interface Approval {
  id: string;
  task_id: string;
  payload_digest: string;
  status: string;
  task_attempt?: number;
  payload?: { artifact_refs?: string[] };
}
export interface Activity {
  sequence: number;
  timestamp: string;
  actor: string;
  action: string;
  task_id: string | null;
  details: Record<string, unknown>;
}
export interface Note {
  id: string;
  title: string;
  content: string;
  created_at: string;
  artifact_refs: string[];
}
export interface Agent {
  id: string;
  name: string;
  description: string;
  permissions: string[];
  tools: string[];
}
export interface Role {
  id: string;
  name: string;
  description: string;
  agents: string[];
}

export async function api<T>(path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    ...(payload !== undefined
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }
      : {}),
    signal,
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      /* HTTP failure has no JSON body. */
    }
    throw new Error(
      typeof detail === 'string'
        ? detail
        : `Request failed (${response.status}). Refresh and try again.`,
    );
  }
  return response.json() as Promise<T>;
}
export async function artifactText(id: string, signal?: AbortSignal): Promise<string> {
  const response = await fetch(`/artifacts/${encodeURIComponent(id)}/content`, { signal });
  if (!response.ok) throw new Error('Artifact could not be loaded or failed its integrity check.');
  return response.text();
}
export const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : 'Something went wrong. Try again.';
export const label = (state: string) => state.toLowerCase().replaceAll('_', ' ');
export const date = (value: string) =>
  new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
