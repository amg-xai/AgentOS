# AgentOS development instructions

AgentOS is a local, modular multi-agent work environment. Read PLAN.md and
ARCHITECTURE.md before changing core behavior; supporting contracts live in docs/.

- Work in this repository. Preserve the user's files and configuration.
- Inspect affected code and propose a plan for each major feature. Obtain the
  user's review before implementation, as required by PLAN.md.
- Register agents and tools through interfaces; load roles from manifests.
- Represent work as missions and dependency-linked tasks. Persist meaningful
  state transitions, artifacts, approvals, and audit events.
- Enforce permissions at tool execution. High-impact actions require approval.
- Keep external integrations out of the core. Never deploy autonomously.
- Add meaningful tests for core behavior. Run relevant tests and build/type
  checks, review the diff, and report limitations before committing.
- Make small, coherent commits using the user's configured Git identity.
  Never add Codex signatures, attribution, or co-author trailers.
- Keep proposals and review notes Git-ignored (docs/reviews/). Check staged
  files before every commit. Publish coherent, tested milestones suitable for
  mentor review; keep essential project documentation tracked.

See docs/product.md for scope, docs/agents.md for agent contracts,
docs/workflows.md for execution, docs/integrations.md for tools, and
docs/decisions.md for decisions and baseline evidence.
