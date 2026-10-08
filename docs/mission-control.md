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
