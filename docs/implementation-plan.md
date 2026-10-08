# First implementation proposal: agent registry and Developer package

Status: awaiting user review, as required by PLAN.md sections 1 and 12.

## Scope

Implement Phase 2 and the minimum Developer manifest support from Phase 3.
This milestone delivers validated agent discovery with a local API; execution,
missions, memory, UI, and external integrations remain subsequent milestones.

## Files and interfaces

- backend/pyproject.toml: installable Python package, development dependencies,
  test and lint configuration.
- backend/src/agentos/domain/agents.py: AgentDefinition and execution Protocol;
  typed inputs/results and provider configuration without embedded credentials.
- backend/src/agentos/domain/roles.py: RolePackage manifest contract.
- backend/src/agentos/services/registry.py: registration, lookup, listing, and
  role-to-agent resolution with explicit validation errors.
- backend/src/agentos/adapters/manifests.py: load versioned JSON manifests;
  validate definitions, schemas, ids, and cross-references before activation.
- backend/src/agentos/api/app.py: FastAPI app factory, health endpoint,
  GET /agents, GET /agents/{id}, GET /roles, and GET /roles/{id}.
- packages/developer/: three agent definitions and a role manifest.
- backend/tests/: registry, manifest, execution-contract, and API tests.
- README.md and architecture docs: installation and local run instructions.

Use Pydantic for data validation and JSON Schema validation for declared agent
inputs/outputs. Registry construction is atomic: invalid manifests cannot leave
a partially loaded registry. Provider execution is injectable; a deterministic
test executor proves the contract without pretending to perform real AI work.

## Acceptance and validation

1. Load the Developer role and discover investigation, code, and testing agents.
2. Reject duplicate ids, unknown tools/agents, invalid permissions, malformed
   schemas, and unsupported manifest versions with actionable errors.
3. Unknown API ids return 404; initialization failures do not silently disappear.
4. Execute a test agent through the interface and validate its inputs/outputs.
5. Run pytest, lint/type checks, and a local API smoke check; review the diff.
6. Commit the tested milestone using the user's configured identity.

## Risks and next milestones

Dependency installation requires network access. API endpoints initially serve
local discovery metadata and must not imply execution or secure remote access.
Provider credentials and selection will be resolved when real execution starts.

Next: persisted mission/task state machine with dependency tests; orchestration
and approval/resume; a local Developer workflow; API-backed Mission Control.
