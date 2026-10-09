# Workspace overview and recorded activity

Mission Control shows totals across the entire selected local history, independent
of the current 100-mission list page. Normal and explicit offline demo histories
remain separate. The same overview is available in the web and desktop clients.

## Find work across history

- **Total missions** includes every persisted mission. State counts follow the
  existing task-derived mission status rules.
- **Pending result reviews** counts undecided result approval records. Legacy
  manual waiting states may have no result approval, so this number can differ
  from the count of missions in WAITING_APPROVAL.
- **Total artifacts** counts recorded artifact metadata. It does not certify
  that every file still passes its integrity check.
- **Recent waiting reviews** lists up to ten waiting missions ordered by mission
  update time, with mission ids breaking ties. **Recent artifacts** lists the ten
  most recently recorded files in database insertion order.

Choose **Open mission** to inspect a review or an artifact's owning mission even
when it is outside the currently displayed list page. The existing mission detail
provides tasks, activity, reviews, and integrity-checked artifact inspection and
downloads. Opening a mission does not run agents or accept its result. Viewer
access remains read-only.

## Search mission history

Use **Search mission goals**, **History role id**, and **Mission state** beside
the mission list, then choose **Apply filters** or press Enter. Goal matching is
a literal, case-insensitive substring search with Unicode case folding. Spaces
around the query are ignored; `%`, `_`, and regex characters are ordinary text.
Search covers persisted goal text across the whole selected history, not task
inputs/outputs, memory, or artifact contents.

Leave the role blank for all roles. Suggestions show installed role ids; you can
also enter a historic id whose package has since been removed. Role matching is
exact. Goal, role, and state filters combine with AND. Filters do not change the
selected workflow for creating missions, and overview totals remain global.

Applying or clearing filters returns to the first page. Existing selected mission
detail stays available even when that mission is outside the matches. Failed
queries report unavailable, while failed refreshes label retained results as stale.
Normal/demo mode switches clear filters, page, and selection. Old responses cannot
restore the previous results. **Clear filters** returns to unfiltered history.

Pages contain up to 100 results in creation-time descending/id ascending order.
The existing list API does not return a filtered total or a next-page token. When
the last page has exactly 100 results, **Next** can open an empty page; **Previous**
returns to the earlier results.

`GET /missions` accepts optional `query` (up to 200 characters), `role_id` (a
lowercase identifier of up to 80 characters), and `status` (a mission state).
Invalid parameters return 422; a valid unknown role returns its matches or an
empty list. Existing `limit` (1–100), nonnegative `offset`, defaults, and the array
response remain compatible. For example:

```text
/missions?limit=100&offset=0&query=calculator&role_id=developer&status=FAILED
```

Filters run before pagination. Filtered reads stream snapshots and reuse the
domain mission-status calculation, stopping after the requested matching page.
Cost grows with the history searched. No schema migration, search index, provider
call, audit event, execution, or permission change is introduced.

## Inspect task dependencies

Open a mission's **Tasks** tab to see **Task dependencies** above the detailed
task list. Stages represent dependency depth: roots have no prerequisites, and
each later stage follows its deepest prerequisite. Tasks at the same depth keep
their original snapshot order. Stage grouping does not promise simultaneous
execution; the current orchestrator executes ready tasks sequentially.

Each card shows the task title/id, assigned agent, recorded status, and named
direct prerequisites with their statuses. The incomplete count includes every
prerequisite whose recorded state is not COMPLETED. The view does not recalculate
readiness or override the task's recorded state. A recorded RUNNING state does
not establish worker liveness. Existing polling updates the overview and details
from the same mission snapshot, including after explicit retries and reviews.

Activate a task title, by click or keyboard, to move focus to its detailed task
entry below. Identifiers distinguish tasks with the same title. Viewer access is
read-only; inspecting dependencies never runs or retries work, cancels a mission,
or accepts an approval. Existing controls remain in their original locations.

Empty missions have explicit copy. If ids/prerequisites are invalid or a cycle is
present, the dependency layout reports unavailable and preserves task detail
inspection. Backend validation remains the authority for executable graphs. The
view introduces no API or storage changes and uses no external graph library.

## Follow saved artifact references

In **Workspace memory**, choose **Inspect linked artifact** on a note. Each
reference shows its id; inspection loads only the selected reference. The
**Linked artifact** panel displays the note title, recorded artifact name/id,
task, owner mission, size/hash, and integrity-checked text. HTML, Markdown links,
and scripts display as ordinary text.

Use **Download** after verification succeeds to save that artifact with its
recorded filename. The backend checks integrity again for the download request.
**Open owning mission** opens existing task/activity/artifact inspection even
when its mission is outside current history results. Applied history filters
remain unchanged. Neither action runs agents or accepts a result.

Keyboard activation moves focus to the preview. **Close preview** returns focus
to its reference button when that button is still present. Selecting another
reference, changing the search, reloading notes after saving, leaving Memory,
or changing normal/demo mode cancels earlier reads and removes obsolete previews.
Missing files/metadata, failed integrity checks, and transport errors show an
unavailable panel with no content or download link. Close and reopen to retry.
Viewer inspection is read-only; note saving still requires Operator/Admin.

Memory retrieval remains bounded and lexical: the client requests up to 100
notes, and the backend considers the newest 1,000 stored notes. Searching uses
keyword overlap rather than semantic or full-history retrieval. Failed reads
report **Notes unavailable** instead of empty-history/no-match copy, and earlier
query results are cleared while a new query loads.

## Interpret activity correctly

**Active runs on this server** is a current in-memory observation from this API
process. **Durable execution claims** are persisted ownership records, including
records retained after an interrupted worker. A claim is not proof of a live
process. Follow the [manual recovery procedure](workflows.md#interrupted-run-recovery)
after confirming the original worker stopped; the overview never recovers work.

Agents & roles shows recorded task counts and up to five recent task references
for each installed agent. Recency uses the owning mission's update time; a task
does not have a separate activity timestamp in the current schema. A recorded
RUNNING task can survive a restart. A RUNNING mission can also have completed
upstream work with downstream tasks ready to resume. Neither establishes that an
agent is currently executing or that its provider is configured. Existing workflow
readiness remains the source for whether a new mission can be created.

## Refresh and read contract

The client refreshes every five seconds. Failed refreshes display an error and
label retained counts/activity as the last successful snapshot. Before any
successful overview load, it reports unavailable rather than inventing zero counts.
Mode changes clear the previous history and selection. Obsolete requests cannot
replace a newer refresh, and a creation response from the previous mode cannot
restore its selection. Restart the service after configuration changes.

`GET /overview` is available to Viewer, Operator, and Admin. It returns bounded
summaries and metadata, never claim tokens, task inputs/outputs, provider settings,
or artifact content. Persisted counts and recent lists share one SQLite read
transaction; `observed_at` marks that read. The local active-run observation is
separate and can change during the request. Reads do not create audit events,
release claims, approve results, or run tools.

The initial implementation streams all mission snapshots to reuse the domain
status calculation, retaining bounded recent lists in memory. Read cost grows
with stored history, and a read transaction can briefly delay SQLite writers.
There is no new cache, background scheduler, schema migration, or distributed
worker liveness guarantee.

Automated API and React/JSDOM checks cover counts beyond one page, navigation,
permissions, stale refreshes, and mode changes. Browser/native visual, responsive,
and screen-reader acceptance remain manual; live model quality remains deferred.
