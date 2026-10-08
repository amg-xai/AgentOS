# Tools and integrations

Tools declare an id, description, input/output schemas, required permissions,
and an execution interface. Tool dispatch checks the acting user's RBAC role,
agent capabilities, workspace boundaries, and any required action approval.

Viewer, Operator, and Admin are authorization roles, distinct from product role
packages such as Developer. READ, WRITE, EXECUTE, and DESTRUCTIVE describe tool
permissions. Admin status does not waive high-impact approval requirements.

Start with scoped local filesystem and Git adapters. Add GitHub, GitLab, Slack,
and Jira behind the tool interface when needed. Keep secrets out of persisted
inputs, logs, artifacts, and manifests. Do not send external messages, publish,
delete files, modify production, or deploy without action-specific approval.

Audit records include timestamp, actor, mission/task, agent/tool, action,
redacted input reference, result, and approval reference.

## Implemented tool boundary

ToolRegistry accepts validated definitions and executors plus a mandatory audit
recorder. A call must satisfy both the user's role and the agent's registered
tool/permission capabilities. Validate input before dispatch and output afterward.
Record started/completed/denied/failed events without logging raw inputs or
provider error strings. If the audit recorder fails before dispatch, do not call
the executor.

Viewer permits READ; Operator permits READ/WRITE/EXECUTE; Admin additionally has
DESTRUCTIVE capability metadata. High-impact and DESTRUCTIVE dispatch is disabled
for every role until a dedicated tool-action approval mechanism is implemented.
The current `review_result` approval is limited to accepting an agent's staged
output; it cannot authorize tool side effects.

SQLite's tool audit recorder checks the current execution claim, workspace, and
RUNNING task scope. Claim tokens are internal execution context and are not
persisted in audit details. No production tool executors or arbitrary HTTP tool
dispatch endpoint are shipped yet. Tests use explicitly labelled toy executors.
