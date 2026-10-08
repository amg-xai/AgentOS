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

Developer provides investigation, code changes, and testing agents. Its executor
composes the structured generator with registered local tools and scoped project
context. Creator provides `creator_outline` and `creator_script`, with no tools.
The Creator executor sends only the brief and dependency-bound outline to the
generator. Both packages share the execution registry, mission engine, artifacts,
and approval services; manifest discovery itself never runs an agent.

Creator bounds briefs to 8,000 characters and each generated outline/script to
24,000 characters. Schemas reject missing fields, extra properties, and non-text
outputs. The script task owns `script.md` and `reviewed-outline.md`, so approval
integrity checks cover both the result and the exact outline it used. Denial and
retry regenerate the script without rerunning the completed outline.
