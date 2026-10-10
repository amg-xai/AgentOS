# Shared semantic memory

Original PLAN.md Phase 6 semantic retrieval is implemented as an explicit shared
Memory search service. It does not change agent inputs, role plans, test recipes or
human review. Real embedding-model relevance is **not validated**. Completion and
embedding inference remain disabled; no model or runner is included or downloaded.

## Sources and evidence

The bounded corpus considers the newest 1,000 local notes and 200 missions:

- Notes retain their original ID and digest and are labelled `user_note`, not
  approved facts. Linked artifact IDs do not authorize indexing their contents.
- Completed mission outcomes contain the stored goal/profile/state, explicit
  test outcomes and review statuses. Completion does not imply passing tests.
- Approved text artifacts must belong to a current completed task attempt and
  match its exact approved payload. The existing approval service revalidates the
  role-specific evidence and test boundary; file hashes and ownership are checked.
  PNGs are verified with their bundle but are not embedded.

Sources outside the local workspace, pending/denied/stale review bundles and
damaged evidence are excluded. Product profiles are filters, not access roles:
Viewer/Operator/Admin retain existing shared local visibility. A profile filter
excludes unowned shared notes; select all profiles to include them. Demo state
stays separate and does not configure or inject semantic inference.

Text artifacts over 64 KB and review bundles over 20 files or 4 MB are ineligible.
The UI reports invalid/ineligible and stale sources separately from omitted
sources. Omission counts cover chunk-budget exclusions within the bounded corpus,
not all older history outside its window.

## Index and ranking

Workspace SQLite schema 3 adds a derived index table without changing mission
schema 2, notes, snapshots or frozen test recipes. Sources have model-independent
hashes; chunks retain exact character ranges and model digest/dimensions. Rebuild
publishes atomically against an expected generation. Failure or a competing rebuild
cannot publish a partial index. A corrupt existing index fails closed, without
automatic repair. Empty rebuild clears an existing index without inference.

Indexing uses up to 768 chunks of 1,000 characters with 128-character overlap,
in batches of at most 32. This bounds a rebuild to 24 inference reservations under
the unchanged 26-request policy ceiling. Rebuild has a 300-second whole-operation
deadline. Allowance must also cover subsequent
searches; failed requests consume reservations. The serialized cache is capped at
32 MB. A model whose vectors exceed response/cache limits fails explicitly.

Search filters eligible sources before ranking, embeds the submitted query, checks
the index's model identity and dimensions, and rechecks sources after awaiting
inference. Cosine similarity is ranked with stable ties and one best excerpt per
source. Default minimum similarity is 0.25; it is not a calibrated confidence score.
Default result limit is five, maximum twenty; responses are capped at 64 KB.
No relevant hit, empty index, unavailable inference and corrupt state are distinct.

## Mission Control and API

Open **Workspace memory → Open semantic search**. Search requires an explicit
submission, not typing. Operator/Admin may rebuild; Viewer may search and inspect.
Results link to their source notes, artifacts and missions. Cancellation prevents
obsolete results from replacing current filters; server/provider work is bounded
by deadlines and durable request allowances, not a guarantee of process abortion.
Keyword note search remains a separate compatible option.

| Endpoint                       | Behavior                                                                           |
| ------------------------------ | ---------------------------------------------------------------------------------- |
| `GET /memory/semantic/status`  | Read stored index/configuration status; no model request                           |
| `POST /memory/semantic/index`  | Explicit Operator/Admin rebuild; send JSON `{}`                                    |
| `POST /memory/semantic/search` | Query with optional `profile`, `mission_id`, `kind`, `limit`, `minimum_similarity` |
| `GET /memory/notes/{id}`       | Read a source note in the bounded local corpus                                     |

Existing `/memory` and `/status.memory_retrieval: lexical` retain their contracts.

## Local adapter and authorization

The native Ollama `/api/embed` adapter requires literal loopback HTTP, verifiably
disabled cloud, an installed local embedding-capable model and a pinned digest.
No redirects, proxies, credentials, cloud embedding adapter, automatic downloads,
completion requests or scripted/lexical semantic fallback are supported. Strict
vector validation rejects inconsistent dimensions/counts, nonnumeric/nonfinite or
zero vectors. Requests have byte/batch/text/response limits and a whole deadline.

Configuration reference only; nothing is activated by installation:

- `AGENTOS_ALLOW_LOCAL_EMBEDDINGS`: separate explicit opt-in, disabled by default.
- `AGENTOS_EMBEDDING_MODEL`, `AGENTOS_EMBEDDING_DIGEST`: explicit tag and SHA-256.
- `AGENTOS_EMBEDDING_URL`: defaults to `http://127.0.0.1:11434`; local only.
- `AGENTOS_EMBEDDING_POLICY`, `AGENTOS_EMBEDDING_LEDGER`: explicit matching,
  unexpired policy and pre-provisioned durable ledger with `memory_requests`.

`memory_requests` defaults to zero. Zero preserves existing policy fingerprints
and ledger compatibility. Memory reservations cannot ready or authorize completion
generation; total and profile allowances remain unchanged. Files are never
automatically provisioned, reset or refunded. Existing generation settings remain
independent. Do not activate inference or provision a ledger without authorization.

Only selected source chunks and search queries go to the local embedding endpoint.
No original project files, arbitrary linked files or entire conversation history
are automatically sent. Runner/model installation requires separate approval after
exact download sizes and disk requirements are reported. No real model has run.

## Automated validation

Backend tests use injected vectors/HTTP to validate migration, ranking, filters,
source integrity, failed-test exclusion, stale reviews, atomic rebuilds, restart,
provider failures, limits and legacy policy compatibility. The continuous React
journey creates/runs/approves real isolated Developer, Creator and Student missions,
then indexes/searches their evidence, inspects source artifacts and verifies restart
and unchanged original files. Only model and embedding transports are injected.
These establish contracts and integration, not real AI or semantic quality.
