# Product scope

The MVP provides one local workspace, role selection, an agent registry,
mission creation, multi-agent execution, persisted state and memory, artifacts,
history, and human approvals. The first complete workflow investigates a bug,
specifies a local issue, proposes a fix, runs tests, presents exact evidence,
and produces an approved artifact.

Developer is the first functional package. Creator now demonstrates reuse of the
same platform for a supplied brief, outline, and reviewed video script. Both have
explicit offline scenarios for interaction testing; normal execution requires a
configured model. Creator optionally researches pasted source text with exact-quote
provenance checks and reviewed evidence copies. It does not fetch sources, fact-check,
produce photographic imagery/video, or publish. Optional Creator thumbnails render
bounded text and geometry into real PNGs, with frozen layout and upstream content
review evidence. Student now provides supplied-material notes and a
multiple-choice quiz with a separate answer key, including a fixed offline demo.
Optional Student planning adds suggested study blocks within explicit time and
session budgets, with the full notes/quiz/plan bundle reviewed together. Study review
records acceptance without asserting correctness or exam readiness. Interactive
answering, scoring, independent research, and calendar scheduling remain deferred.
Do not advertise placeholder packages as functional.

Normal Developer missions now use [bounded goal-driven planning](developer-planning.md).
Live calls remain disabled pending explicit acceptance authorization. Real AI
vertical-slice acceptance still requires a failing baseline, a live generated
patch, passing actual tests, and human review. These implemented subsets do not
replace the full Developer, Creator, and Student scope in original PLAN.md.

Normal Creator creation now uses bounded goal-driven planning and registered
capability selection on the same engine. Inspect its plan, original goal,
constraints and dependency-linked content tasks before running. Outline refinements
and supplied-source research feed one exact script review. This completes the
planning/selection portion of that content slice and bounded graphic thumbnails;
broader imagery and genuine live acceptance remain pending.

Normal Student creation also uses bounded goal-driven decomposition and registered
notes/quiz/Focus selection. Inspect the plan, run content work explicitly and review
the exact final bundle. Notes refinements preserve the original goal/constraints;
only explicit time settings request Focus. This completes planning/selection for
the supplied-material subset. Sourced Student v2 adds registered Research/Study
and Summarizer stages, frozen source/research/summary evidence and per-question
provenance before exact quiz/Focus review. Independent source acquisition and
live quality acceptance remain unfinished original-roadmap work.

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
Continuous React-to-real-backend tests now exercise the bounded Developer,
Creator and Student journeys using injected model transport. Creator includes
source research, script and actual graphic-thumbnail artifacts with human review.
This verifies offline integration and persistence; live AI quality and native
visual acceptance remain outstanding.

Exclude production deployment, billing, multi-tenancy, broad marketplaces,
custom models, and extensive integrations from the initial scope.
