# Model provider

The Responses adapter uses a configurable model and endpoint, strict JSON Schema
outputs, local output validation, bounded HTTP requests, and no automatic retries
or fixture fallback. Requests disable provider-side storage with `store: false`.
The wire format follows the [official structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).

Set `AGENTOS_MODEL` to a model that supports strict structured outputs. Set
`AGENTOS_MODEL_KEY` (or `OPENAI_API_KEY`) in the server environment. The default
endpoint is `https://api.openai.com/v1`; `AGENTOS_MODEL_URL` may select another
Responses-compatible server. Plain HTTP is allowed only on loopback. A local
server must support `/responses` and strict structured outputs; compatibility
with Chat Completions alone is insufficient. Model names are explicit to avoid
silently changing cost or behavior. Desktop sign-in and Git credentials are not
API credentials. Never put keys in manifests, source control, or review notes.

Provider tests use mocked transport. They verify the wire contract and rejection
paths; they do not establish model quality or live endpoint compatibility.

Live model calls default to disabled, even with provider credentials present.
After explicit authorization for live acceptance, set `AGENTOS_ALLOW_LIVE_MODELS=1`
in the ignored local `.env` and restart. With the default `0`, normal workflow
creation is blocked and the adapter rejects live transport before HTTP dispatch.
Read-only doctor checks never contact a provider. Tests use injected transports.

Live dispatch also requires an unexpired acceptance policy and an existing durable
request ledger with matching endpoint/model and remaining role allowance. Neither
is provisioned automatically. Read-only diagnostics report this separately from
provider settings. See [live acceptance controls](live-acceptance-limits.md) for
enforced request limits, provider spending prerequisites, transmitted data and the
separate authorization required before configuration or live execution.
