# AgentOS

A local work environment for role-specific AI agents, persistent missions,
shared memory, tools, artifacts, and human approvals.

## Current status

Repository foundation only. The supplied PLAN.md is the product roadmap;
there is no runnable application yet. No model credentials are required for
the first proposed registry milestone.

## Development

- Read [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
- Review [the first implementation proposal](docs/implementation-plan.md).
- Build and review one milestone at a time, with tested, coherent commits.
- Store local credentials in ignored environment files, never in Git.

The proposed stack is Python/FastAPI with SQLite and React/TypeScript.
Desktop packaging follows a working local web application.
