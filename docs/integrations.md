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
