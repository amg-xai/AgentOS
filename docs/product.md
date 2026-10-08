# Product scope

The MVP provides one local workspace, role selection, an agent registry,
mission creation, multi-agent execution, persisted state and memory, artifacts,
history, and human approvals. The first complete workflow investigates a bug,
proposes a fix, runs tests, presents a diff, and produces an approved artifact.

Developer is the first functional package. Creator and Student later demonstrate
reuse of the same platform. Do not advertise placeholder packages as functional.

Acceptance for the vertical slice: a user creates a mission, sees tasks run,
inspects tool activity and test output, reviews a diff, approves an explicit
action, resumes execution, and can inspect the completed mission after restart.

Exclude production deployment, billing, multi-tenancy, broad marketplaces,
custom models, and extensive integrations from the initial scope.
