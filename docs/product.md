# Product scope

The MVP provides one local workspace, role selection, an agent registry,
mission creation, multi-agent execution, persisted state and memory, artifacts,
history, and human approvals. The first complete workflow investigates a bug,
proposes a fix, runs tests, presents a diff, and produces an approved artifact.

Developer is the first functional package. Creator now demonstrates reuse of the
same platform for a supplied brief, outline, and reviewed video script. Both have
explicit offline scenarios for interaction testing; normal execution requires a
configured model. Creator does not perform research, fact-checking, image/video
production, or publication. Student now provides supplied-material notes and a
multiple-choice quiz with a separate answer key, including a fixed offline demo.
Study review records acceptance of the bundle, without asserting correctness or
exam readiness. Interactive answering, scoring, research, and study scheduling are
deferred. Do not advertise placeholder packages as functional.

Normal Developer missions now use [bounded goal-driven planning](developer-planning.md).
Live calls remain disabled pending explicit acceptance authorization. Real AI
vertical-slice acceptance still requires a failing baseline, a live generated
patch, passing actual tests, and human review. These implemented subsets do not
replace the full Developer, Creator, and Student scope in original PLAN.md.

Mission Control includes workspace-wide totals, recent waiting reviews/artifacts,
and recorded task activity for installed agents. These are read-only projections
of durable history; claim and task state do not imply agent availability. See
[workspace overview](mission-control.md) for interpretation and refresh behavior.
Mission history supports goal search and role/state filters across persisted
records, independently of workflow creation and global dashboard totals.
Mission inspection groups task dependencies by depth with named prerequisite
states and keyboard navigation to existing task details. Recorded task state is
not a claim of live worker activity or parallel execution.
Workspace memory lets users follow saved artifact references to verified text,
downloads, and the owning mission without changing approvals or execution.

Acceptance for the vertical slice: a user creates a mission, sees tasks run,
inspects tool activity and test output, reviews a diff, approves an explicit
action, resumes execution, and can inspect the completed mission after restart.

Exclude production deployment, billing, multi-tenancy, broad marketplaces,
custom models, and extensive integrations from the initial scope.
