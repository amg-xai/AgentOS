# Agents and role packages

An AgentDefinition includes a stable id, name, description, role/package,
instructions, optional capability, allowed tools, permissions, input/output schemas,
and provider configuration. Secrets are resolved at runtime and never stored in manifests.

AgentRegistry validates unique identifiers and resolves definitions by id.
Execution is a separate interface so discovery does not initialize providers or
execute tools. Results contain structured outputs and artifact references.

Role manifests reference registered agents and declared tools. Validate missing
references, duplicate ids, malformed schemas, and invalid permission values at
load time. Activation selects capabilities; it never bypasses permission checks.

Developer provides investigation, code changes, testing, deterministic baseline
testing, and a tool-free planning agent. Normal routing uses declared capabilities,
rather than canonical agent IDs;
the offline preset remains explicit. See [Developer planning](developer-planning.md).
Its executor composes the structured generator with registered local tools and scoped project
context. Creator provides tool-free `creator_research`, `creator_outline`, and
`creator_script`. Optional supplied sources add verified research outputs to
the outline/script inputs; brief-only requests retain their existing inputs.
Both packages share the execution registry, mission engine, artifacts,
and approval services; manifest discovery itself never runs an agent.

Creator bounds briefs to 8,000 characters and each generated outline/script to
24,000 characters. Schemas reject missing fields, extra properties, and non-text
outputs. The script task owns `script.md` and `reviewed-outline.md`, so approval
integrity checks cover both the result and the exact outline it used. Denial and
retry regenerate the script without rerunning the completed outline.

Student provides tool-free `student_notes` and `student_quiz` agents. The notes
agent receives an 8,000-character study brief; its notes are bounded to 24,000
characters. Quiz receives the brief and bound notes without workspace enrichment.
Its structured output has 3–8 questions, each with a bounded prompt, exactly four
choices, an answer index from 0 to 3, and an explanation. Unknown properties and
invalid output fail before artifact creation. Questions and answers render into
separate files; the quiz task also owns its input notes copy for review integrity.
Retrying a failed or denied quiz preserves the completed notes and old artifacts.

Creator supplied-source schema limits, provenance checks, owned review copies, and
capability preflight are documented in [Creator workflow](creator-workflow.md).

Student also registers tool-free `student_focus` for optional bounded study effort.
It receives the original goal/time settings and bound notes/questions. Strict
outputs enforce session/total budgets and valid complete quiz references. The
planner attempt owns the six-file final review bundle. Legacy notes/quiz contracts
are preserved. See [Student workflow](student-workflow.md).
