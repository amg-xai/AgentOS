# AgentOS — Build Plan

## 0. Goal

Build a desktop/local Agent OS that gives users one place to activate and use role-specific AI agents and workflows.

Reference ideas to borrow:

- Senior AI-OS: desktop client, role-based agent packages, agent activation.
- Mission-control AgentOS tutorial: agents, workflows/pipelines, memory, background runs, artifacts, history, approvals, modularity.
- Builder-style Agent OS: persistent project context, standards, structured planning/specification.
- Our current AgentOS repo: multi-agent orchestration, shared state, memory, RBAC, human approval, audit logs, tracing, evaluation.

**Important:** Slack + Jira is a demonstration workflow, not the product boundary.

---

# 1. MVP Definition

Do NOT attempt to build every agent first.

The MVP is:

1. Desktop/web Mission Control.
2. Role/package selection.
3. Agent registry.
4. One workspace/project.
5. Task/Mission creation.
6. Multi-agent execution.
7. Shared task state.
8. Persistent memory.
9. Human approval for risky actions.
10. Activity/history/artifacts.
11. One complete real workflow.
12. Extensible tool/integration layer.

### First complete workflow

Use **Developer** as the first role because it gives the strongest demonstration.

Example:

```text
User creates mission:
"Investigate and fix this issue."

        ↓
Investigation Agent
        ↓
Issue/Ticket Agent
        ↓
Code/Fix Agent
        ↓
Testing Agent
        ↓
Human Review
        ↓
Result / PR / artifact
```

Slack → Jira → GitHub/GitLab can be one implementation of this workflow.

Do not make Slack/Jira hard-coded into the core architecture.

---

# 2. Target Architecture

```text
                         AGENT OS
                            |
          +-----------------+-----------------+
          |                 |                 |
       Roles             Workspaces        Agent Registry
          |                 |                 |
    +-----+-----+           |          +------+------+
    |     |     |            |          |      |     |
 Developer Creator Student  |        Code  Research Focus
    |     |     |            |        Agent  Agent   Agent
    +-----+-----+------------+----------+------+-----+
                            |
                       Mission Engine
                            |
                       Task / Work Graph
                            |
                  +---------+---------+
                  |                   |
             Orchestrator          State
                  |                   |
          +-------+-------+           |
          |       |       |           |
        Agent A Agent B Agent C       |
          |       |       |           |
          +-------+-------+-----------+
                            |
              +-------------+-------------+
              |             |             |
           Memory         Tools        Artifacts
              |             |             |
              |       Slack/Jira/Git/API  |
              +-------------+-------------+
                            |
                     Approval / RBAC
                            |
                         Audit Log
                            |
                         UI/Desktop
```

---

# 3. Core Concepts

## Role

A predefined bundle of agents and tools.

Example:

```yaml
developer:
  agents:
    - code_helper
    - architecture
    - debugger
    - testing
  tools:
    - filesystem
    - terminal
    - git
```

Creator and Student packages follow the same schema.

## Agent

A reusable capability.

Each agent should have:

- id
- name
- description
- role/package
- system instructions
- tools
- permissions
- input schema
- output schema
- model/provider configuration

## Mission

A user-level goal.

Example:

> "Fix the authentication bug."

A mission contains tasks, dependencies, status, outputs and history.

## Task

A single executable unit inside a mission.

```text
Mission
  ├── Investigate
  ├── Implement
  ├── Test
  └── Review
```

## Artifact

Anything produced during work:

- code diff
- file
- report
- Jira ticket
- PR
- image
- generated document
- test result

## Workspace

Persistent context for a project/user.

Contains:

- files/context
- memory
- missions
- agents
- configuration
- artifacts
- history

---

# 4. Build Order

## Phase 0 — Stabilize the existing repo

Before adding features:

- Run the current application.
- Identify frontend/backend entry points.
- Run existing tests.
- Record current failures.
- Document architecture.
- Remove dead/demo code only when it blocks development.
- Create a clean development branch.

### Deliverables

- Application runs locally.
- Current functionality is understood.
- Baseline screenshots.
- Baseline test result.

---

# Phase 1 — Repository Contract

Create these files before major coding:

```text
AGENTS.md
PLAN.md
ARCHITECTURE.md
docs/
  product.md
  agents.md
  workflows.md
  integrations.md
  decisions.md
```

`AGENTS.md` should stay short. It should point Codex to the deeper documentation rather than becoming a giant instruction file.

`PLAN.md` is this implementation plan.

### Codex rule

For every major feature:

1. Ask Codex to inspect the repo.
2. Ask for an implementation plan.
3. Review the plan.
4. Only then ask it to implement.
5. Run tests/build.
6. Ask Codex to review its own changes.
7. Commit.

---

# Phase 2 — Agent Registry

Build the core agent abstraction first.

Example:

```python
AgentDefinition(
    id="code_helper",
    name="Code Helper",
    description="Helps understand and modify code",
    tools=["filesystem", "terminal", "git"],
    permissions=["read_project", "write_workspace"]
)
```

Build:

- AgentDefinition
- AgentRegistry
- Agent configuration
- Agent loading
- Agent execution interface

The UI should be able to show:

```text
Developer
  ✓ Code Helper
  ✓ Architecture Agent
  ✓ Debug Agent
  ○ Testing Agent
```

Do NOT implement 20 agents yet.

Implement 2-3 real agents and prove the abstraction works.

---

# Phase 3 — Role Packages

Create package manifests instead of hard-coding roles.

Example:

```yaml
name: Developer
agents:
  - code_helper
  - architecture
  - debugger

tools:
  - filesystem
  - terminal
  - git
```

Then add:

### Developer

- Code Helper
- Architecture Agent
- Debugger
- Testing Agent

### Creator

- Research Agent
- Script Agent
- Content Agent
- Image Agent

### Student

- Research Agent
- Study Agent
- Summarizer
- Quiz Agent
- Focus Agent

Initially, only Developer agents need to be fully functional.

Creator/Student can begin with 1-2 working agents each.

---

# Phase 4 — Mission / Task Engine

This is the most important backend layer.

Implement:

```text
Mission
  |
  +-- Task
  |     +-- status
  |     +-- assigned_agent
  |     +-- inputs
  |     +-- outputs
  |     +-- dependencies
  |
  +-- artifacts
  +-- approvals
  +-- events
  +-- memory references
```

Task states:

```text
PENDING
READY
RUNNING
WAITING_APPROVAL
BLOCKED
FAILED
COMPLETED
CANCELLED
```

Support:

- task creation
- task assignment
- dependencies
- state transitions
- retry
- cancellation
- resume

---

# Phase 5 — Orchestration

Use the existing LangGraph foundation where it is already useful.

The orchestrator should:

1. Understand the mission.
2. Decompose it.
3. Select appropriate agents.
4. Execute ready tasks.
5. Pass outputs to dependent tasks.
6. Persist state after every meaningful step.
7. Handle failures.
8. Request approval when required.
9. Resume after approval.
10. Produce final mission status.

Do not make one giant supervisor prompt.

Keep agents modular.

---

# Phase 6 — Memory

Use layered memory.

```text
User Memory
    |
Workspace Memory
    |
Mission Memory
    |
Agent Context
    |
Artifacts
```

Minimum implementation:

- workspace/project memory
- mission history
- semantic retrieval for relevant previous information
- artifact references

Do not dump the entire history into every prompt.

Retrieve only relevant context.

---

# Phase 7 — Tools / Integrations

Create a generic tool interface.

```text
Tool
 ├── id
 ├── description
 ├── input schema
 ├── permissions
 └── execute()
```

Then integrations become plugins/tools:

```text
Filesystem
Git
GitHub
GitLab
Slack
Jira
Browser
Email
Calendar
```

The core AgentOS must not depend directly on Slack/Jira.

---

# Phase 8 — Developer Workflow

This is the first complete showcase.

### Scenario

A bug is reported.

```text
Slack / user input
       ↓
Investigation Agent
       ↓
Jira/Issue Agent
       ↓
Fix Agent
       ↓
Testing Agent
       ↓
Human Review
       ↓
PR / Artifact
       ↓
Optional Deployment
```

Important:

- Human approval before destructive/high-impact actions.
- Never automatically deploy in the first MVP.
- Show code diff before approval.
- Log every action.

If GitHub/GitLab integration takes too long, first implement the same flow using a local repository.

---

# Phase 9 — Creator Workflow

After Developer works:

```text
Mission:
"Create a YouTube video about AgentOS."

Research Agent
      ↓
Outline Agent
      ↓
Script Agent
      ↓
Image/Thumbnail Agent
      ↓
Review
      ↓
Artifacts
```

This proves the architecture is not Slack/Jira-specific.

---

# Phase 10 — Student Workflow

```text
Mission:
"Prepare me for my DSA exam."

Research/Study Agent
      ↓
Summarizer
      ↓
Notes Agent
      ↓
Quiz Agent
      ↓
Focus/Study Planner
```

Again, all agents use the same Mission/Task/Memory/Artifact infrastructure.

---

# Phase 11 — Mission Control UI

Build only the screens that expose the actual system.

### Dashboard

```text
Active Missions
Running Agents
Waiting Approvals
Recent Artifacts
```

### Agent Store

```text
Developer
Creator
Student
```

### Mission View

```text
Mission
  ├── Tasks
  ├── Agent activity
  ├── Logs
  ├── Artifacts
  └── Approvals
```

### Agent View

```text
Agent
  ├── status
  ├── current task
  ├── tools
  ├── permissions
  └── history
```

### Memory

Show relevant workspace/mission memory.

### History

Show completed missions and artifacts.

Do not spend days polishing animations before the backend workflow works.

---

# 5. Desktop App

Only after the web/local system works:

```text
React
   ↓
Electron
   ↓
AgentOS local client
```

First milestone:

- start backend
- open desktop shell
- connect to backend
- show Mission Control

Do not let Electron development block the AgentOS backend.

---

# 6. Safety / Governance

Keep these from the current implementation:

### RBAC

```text
Viewer
Operator
Admin
```

### Permission levels

```text
READ
WRITE
EXECUTE
DESTRUCTIVE
```

### Approval

Require human approval for:

- deployment
- deleting files
- sending external messages
- publishing
- modifying production systems
- destructive database actions

### Audit

Record:

```text
timestamp
user
mission
task
agent
tool
action
input/reference
result
approval
```

---

# 7. Testing Strategy

Do not only test individual functions.

Test complete missions.

## Unit tests

- agent registry
- task state
- dependency resolution
- permissions
- memory retrieval
- tool validation

## Integration tests

- agent → tool
- mission → agent
- agent → artifact
- approval → resume
- failure → retry

## End-to-end tests

At least:

### Test 1

```text
Developer mission
→ investigate
→ fix
→ test
→ approval
→ complete
```

### Test 2

```text
Creator mission
→ research
→ script
→ artifact
```

### Test 3

```text
Student mission
→ study
→ quiz
→ result
```

---

# 8. Demo-First Development

Your final demo should tell one continuous story.

## Demo A — Developer

```text
Open AgentOS
      ↓
Select Developer
      ↓
Create mission
"Fix authentication bug"
      ↓
Agent decomposes mission
      ↓
Agents work
      ↓
Code changes
      ↓
Tests
      ↓
Human approval
      ↓
PR/artifact
```

## Demo B — Creator

```text
Select Creator
      ↓
"Create video content about AI agents"
      ↓
Research
      ↓
Script
      ↓
Thumbnail
      ↓
Artifacts
```

## Demo C — Student

```text
Select Student
      ↓
"Prepare me for tomorrow's exam"
      ↓
Study
      ↓
Notes
      ↓
Quiz
```

This demonstrates that the same OS infrastructure works across roles.

---

# 9. What NOT to Build Yet

Do NOT start with:

- 20+ agents
- every MCP integration
- custom LLM
- custom vector database
- voice assistant
- complex marketplace
- autonomous production deployment
- elaborate animations
- mobile app
- billing
- multi-tenant enterprise infrastructure
- perfect memory system

These are scope killers.

Build the vertical slice first.

---

# 10. Recommended Tech Direction

Reuse your existing stack wherever possible.

### Frontend

- React
- TypeScript
- Tailwind if already present
- Electron later

### Backend

- Python
- FastAPI
- LangGraph where your existing orchestration already uses it

### Storage

Start simple:

- SQLite/PostgreSQL for structured state
- Chroma/vector store only where semantic retrieval is useful
- Filesystem/object storage for artifacts

### Integrations

Use adapters/tools:

```text
Tool Interface
   ├── Git
   ├── GitHub
   ├── Slack
   ├── Jira
   ├── Browser
   └── Local Files
```

### AI

Keep model/provider configuration abstract.

Do not hard-code the entire OS around one model.

---

# 11. How to Use ChatGPT + Codex

## ChatGPT = Architect / Reviewer / Debugger

Use ChatGPT for:

- architecture decisions
- breaking large features into tasks
- comparing approaches
- debugging explanations
- API/interface design
- writing specs
- reviewing Codex output
- test strategy
- documentation
- demo planning

Keep one ChatGPT Project/conversation dedicated to AgentOS context.

Keep:

```text
Architecture
Decisions
Roadmap
Known bugs
```

in repository docs as the source of truth.

## Codex = Primary Builder

Use Codex for:

- repository inspection
- implementation
- refactoring
- tests
- migrations
- integration code
- UI implementation
- bug fixing
- code review

OpenAI recommends starting large changes in Ask/planning mode and then switching to Code mode, and using well-scoped tasks rather than asking for an enormous implementation in one prompt. citeturn0search0turn0search1

---

# 12. Your Codex Workflow

For EVERY feature:

```text
CHATGPT
  ↓
Define feature
  ↓
Write acceptance criteria
  ↓
CODEx — ASK MODE
  ↓
Inspect repo
  ↓
Implementation plan
  ↓
YOU REVIEW
  ↓
CODEX — CODE MODE
  ↓
Implement
  ↓
Tests
  ↓
CODEX REVIEW
  ↓
YOU TEST
  ↓
Commit
```

Do not prompt:

> "Build my entire AgentOS."

Instead:

> "Implement AgentRegistry and role package loading. First inspect the existing architecture. Do not modify files yet. Give me an implementation plan, affected files, interfaces, tests, and risks."

Then:

> "Implement the approved plan. Keep existing APIs compatible. Add tests. Run the relevant test suite."

This is much more reliable.

---

# 13. Create AGENTS.md

Your repo should have a short `AGENTS.md`.

It should contain:

```text
# AgentOS Development Instructions

## Project
AgentOS is a modular multi-agent work environment.

## Architecture
Frontend: ...
Backend: ...
Orchestration: ...
Storage: ...

## Rules
- Do not hard-code integrations into the core.
- Agents must be registered through AgentRegistry.
- Work must be represented as Missions and Tasks.
- Persist task state.
- Do not bypass permission checks.
- Destructive/high-impact actions require approval.
- Add tests for new core behavior.
- Do not rewrite working modules without reason.

## Before coding
- Inspect existing architecture.
- Identify affected modules.
- Propose a plan for non-trivial changes.

## After coding
- Run tests.
- Run type/build checks.
- Summarize changed files.
- Report remaining issues.
```

Codex supports `AGENTS.md` as persistent repository context, and OpenAI recommends keeping it useful and focused rather than turning it into a giant manual. citeturn0search0turn0search9

---

# 14. Resource Order

Do NOT watch/read everything.

Use resources in this order:

### A. Your existing repositories

Study only for:

- UI patterns
- workspace/mission ideas
- agent configuration
- memory
- integrations
- desktop client

### B. Your current AgentOS repo

This is your starting codebase.

Understand before rewriting.

### C. OpenAI Codex documentation

Use the official Codex guidance for:

- AGENTS.md
- Ask → Code workflow
- code review
- task sizing
- repository context

urlCodex best practiceshttps://openai.com/business/guides-and-resources/how-openai-uses-codex/

urlUsing Codex with your ChatGPT planhttps://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan

### D. OpenAI Agents documentation

Read only if you decide to use OpenAI's agent runtime/API instead of keeping your current LangGraph runtime.

urlOpenAI Agents documentationhttps://developers.openai.com/api/docs/guides/agents

### E. MCP documentation

Only when implementing integrations.

Don't spend the first week learning MCP theory.

---

# 15. 10-Day Fast Track

## Day 1

- Stabilize current repo
- Understand architecture
- Create AGENTS.md
- Create PLAN.md
- Run baseline

## Day 2

- Agent Registry
- AgentDefinition
- Role package schema
- Developer package

## Day 3

- Mission model
- Task model
- State machine
- Persistence

## Day 4

- Orchestrator
- Agent assignment
- Dependencies
- Resume/retry

## Day 5

- Memory
- Artifacts
- Activity/history
- Approval system

## Day 6

- Developer workflow
- Local Git repository
- Code agent
- Testing agent

## Day 7

- GitHub/GitLab adapter
- Slack/Jira adapter
- Complete incident workflow

## Day 8

- Mission Control UI
- Agent/package UI
- Mission/task UI
- Approval UI

## Day 9

- Creator + Student packages
- 1-2 working agents each

## Day 10

- Electron shell
- End-to-end testing
- Demo polish
- Screenshots/video
- Documentation

If something slips, **cut features, not the core vertical slice.**

---

# 16. Definition of Done

The MVP is DONE when a user can:

```text
Install/open AgentOS
       ↓
Choose Developer
       ↓
Create a mission
       ↓
AgentOS creates tasks
       ↓
Agents execute tasks
       ↓
Tools are used
       ↓
State is persisted
       ↓
Human approval is requested
       ↓
Agent resumes
       ↓
Artifacts are produced
       ↓
Mission becomes COMPLETE
       ↓
User can inspect what happened
```

Then the exact same engine can support:

```text
Developer
Creator
Student
```

without creating three separate applications.

---

# 17. The Rule for the Whole Project

### Build the PLATFORM once.

### Build WORKFLOWS on top of it.

### Build AGENTS as plugins.

Do NOT build:

```text
Slack AgentOS
Jira AgentOS
Creator AgentOS
Student AgentOS
Developer AgentOS
```

Build:

```text
                 AgentOS Core
                      |
             Mission / Task Engine
                      |
             Agent / Tool Registry
                      |
        +-------------+-------------+
        |             |             |
    Developer       Creator       Student
     Package        Package       Package
        |             |             |
     Agents         Agents        Agents
        |             |             |
        +-------------+-------------+
                      |
               Shared OS Services
       Memory / State / Artifacts / RBAC
       Approvals / History / Integrations
```

That is the architecture you should code toward.
