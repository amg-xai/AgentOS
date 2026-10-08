# Agents and role packages

An AgentDefinition includes a stable id, name, description, role/package,
instructions, allowed tools, permissions, input/output schemas, and provider
configuration. Secrets are resolved at runtime and never stored in manifests.

AgentRegistry validates unique identifiers and resolves definitions by id.
Execution is a separate interface so discovery does not initialize providers or
execute tools. Results contain structured outputs and artifact references.

Role manifests reference registered agents and declared tools. Validate missing
references, duplicate ids, malformed schemas, and invalid permission values at
load time. Activation selects capabilities; it never bypasses permission checks.

First milestone: Developer manifests for investigation, code changes, and testing.
These definitions are discovery metadata until execution is implemented.
