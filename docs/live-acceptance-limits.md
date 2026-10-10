# Bounded live acceptance prerequisites

Current policy: ₹0 budget, no paid/cloud API calls and generation disabled.
Responses compatibility and spending-control information below is retained as
historical preparation, not authorization to configure or use a billing account.
The optional [local-only path](local-inference.md) retains this policy/ledger;
no runner/model download or real inference has been authorized or validated.

Generation remains disabled until the user separately authorizes a specific
isolated acceptance session. Preparing these controls grants no authorization.
Developer is the first target; Creator and Student follow only within the approved
allowance. All role contracts, source/test recipes, permissions and result approvals
continue through the existing engine. Model-call authorization is distinct from
accepting a result.

## Endpoint and schema requirements

The adapter POSTs to `<AGENTOS_MODEL_URL>/responses` (default base:
`https://api.openai.com/v1`). Remote endpoints require HTTPS, without embedded
credentials, query or fragment; loopback HTTP is supported. Select an explicit
model with Responses API access and strict `text.format` JSON Schema support.
Chat Completions compatibility alone is insufficient. The endpoint must accept
`store: false`, `instructions`, a string `input`, and `max_output_tokens`, and return
a completed Responses envelope with exactly one structured `output_text`.
Responses are validated again locally against the actual registered output schema.

The existing 22 registered schemas can be inspected without generation. Local
schema validation, contract tests and injected transport tests establish local
shape and wire behavior; they cannot certify a particular account/model/endpoint.
The offline audit found no inspected subset violations: maximum resolved object/
array depth 5, maximum 13 property definitions and 5 enum values per schema. All 22
use bounds excluded by the currently documented fine-tuned subset. Select a model
supporting the complete schema, rather than stripping those bounds.
No documented non-billable schema-only Responses dry-run was found in the official
[Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create).
Do not probe generation expecting an invalid request to be free. Endpoint/model
compatibility remains unverified until separately authorized acceptance.

The selected model must support the actual nested, closed objects, required fields,
arrays, enums and string/numeric bounds in the manifests. Check the provider's
[strict schema subset](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)
for that model, particularly fine-tuned-model restrictions. No schema is weakened
to make a provider accept it. Refusals, incomplete responses and incompatible
outputs fail instead of becoming successful missions.

## Enforced dispatch limits

Production transport requires all three gates: existing explicit live enablement,
an acceptance policy, and a pre-provisioned SQLite reservation ledger. No policy or
ledger is created automatically by startup, diagnostics or generation. Injected
test transports remain independent and never establish live readiness.

After authorization only, provision the approved policy and its matching ledger
under ignored local session storage, separately from ordinary mission history.
`LiveRequestPolicy` validates the policy; `LiveRequestLedger.initialize(path, policy)`
creates the ledger exclusively and refuses to overwrite an existing file. Point
`AGENTOS_LIVE_REQUEST_POLICY` and `AGENTOS_LIVE_REQUEST_LEDGER` at these paths in
the isolated server environment. Do not configure or enable them during preparation.

The policy must contain:

- An identifier `session_id`, exact normalized base `endpoint`, explicit `model`,
  and timezone-aware `expires_at`.
- `max_requests` (1–26), `developer_requests` (0–9), `creator_requests` (0–8),
  and `student_requests` (0–9). A zero allowance excludes that role. These are
  implementation ceilings; approved session allowances should be smaller.
- `max_output_tokens` (256–8192) and `max_request_bytes` (1–1,000,000). Dispatch
  uses the lower of the existing model output bound and the approved policy bound.
  Byte accounting includes the entire UTF-8 JSON request, schemas and instructions.
- `provider_spend_control_confirmed: true` and a nonempty, nonsecret
  `spend_control_reference` identifying the control the user has verified.

An immutable policy fingerprint ties the ledger to all settings. Missing, corrupt,
changed, expired or exhausted state blocks dispatch. A SQLite write transaction
atomically reserves a slot before HTTP construction. Concurrent requests and
restarts cannot reset the count. Authentication errors, invalid outputs, timeouts,
cancellation and other failed attempts retain their reservation; there are no
refunds or automatic retries. Unknown or exhausted roles cannot borrow allowance
from another role. Smaller request limits can reject a payload before reservation.

Existing defaults remain a 120-second request deadline (programmatic maximum 300),
2,000,000 response bytes, no redirects, no environment proxies, and no implicit
transport retries. Cancellation cannot prove the provider stopped processing or
billing a request. Read-only diagnostics never contact the provider or consume slots;
startup readiness is a snapshot and later dispatch always rechecks the policy.

## Monetary ceiling and provider-side controls

This is a request reservation ledger, not a billing subsystem. The spending-control
field is a required local attestation, not remote verification of a monetary cap.
AgentOS does not independently meter money, verify prices or reconcile provider
usage. Output token and request bounds do not bound dollars without a selected
model, input pricing and billing rules. Trusted local operators can deliberately
replace files or controls; the ledger is not an adversarial security boundary.

For OpenAI, use a dedicated acceptance project/key with no unrelated traffic. In
project Settings → Limits → Spend, set the agreed monthly spend limit and enable
**Enforce a hard limit**; check applicable organization limits as well. Account
for spend already incurred. Spend alerts or warning budgets alone are insufficient.
Verify key project membership and supported model access in the provider console
without generation. Keep keys in ignored local configuration, never chat or notes.
For another endpoint, require documented blocking controls covering the selected
model/key and all chargeable requests; a UI warning is not such a control.

OpenAI's [spend-limit documentation](https://developers.openai.com/api/docs/guides/spend-limits)
warns enforcement can be delayed with some overshoot. This therefore cannot promise
a strict zero-overshoot ceiling. Keep a margin below the approved currency ceiling
and explicitly agree that residual risk before acceptance. If zero overshoot is
required, do not run: require a provider guarantee or a separately reviewed gateway
that reserves conservative maximum monetary liability before forwarding requests.
Adding that gateway is outside this milestone.

## Transmitted data and estimation

Every call sends the selected model identifier, registered agent instructions,
actual output schema, and JSON-serialized inputs. Planning includes the natural-
language goal, constraints, settings and bounded registered-capability catalog.
Developer investigation/patch calls include the three selected isolated Calculator
files, dependency evidence (including baseline/Issue findings), and patch rules;
investigation can include up to five matching workspace notes. Use a fresh isolated
workspace memory store so no personal or unrelated notes are sent. Revisions also
send the previous diff, failure evidence and explicit human feedback.

Creator and Student send the prepared pasted excerpts, source IDs/labels, goal,
constraints/settings and generated dependency context (research, outlines, summary,
notes, quiz or graphic layout as appropriate). Local test execution and PNG rendering
do not contact a model. No arbitrary repository, independent web research, external
tickets, publication or deployment is authorized. The key is an authorization
header; it is not prompt text. `store: false` is not a guarantee of zero provider
retention: review the selected provider's data handling before authorizing transmission.

Prepared graph maxima are Developer 7 calls initially, up to 9 with two explicitly
authorized patch revisions; sourced Creator with thumbnail 8; sourced Student with
Focus 9. All three initially need at most 24, or 26 with Developer revisions.
Unplanned retries or new missions require separate approval and allowance.

Once endpoint/model and currency are chosen, estimate each request's input tokens
offline with the model's supported tokenizer, including schemas, instructions and
bounded dependency context. Use current uncached input pricing and the full approved
output token cap for every allowed call; include chargeable reasoning tokens and
endpoint-specific fees according to that provider's rules. Do not assume caching,
short outputs or failed-call refunds. Sum these conservative amounts, add a margin
and compare with the dedicated provider limit and approved budget. Later dependent
inputs are not yet known, so distinguish estimates from enforceable byte/request
ceilings and stop rather than guessing a monetary guarantee. No cost estimate or
live compatibility claim is valid until the model and billing rules are identified.
With rates quoted per million tokens, estimate
`sum(input_tokens_estimate * uncached_input_rate + output_token_cap * output_rate) / 1_000_000`,
then add endpoint fees and the agreed margin. This is an estimate, not a local
monetary lock. A Developer-only allowance of seven calls bounds requested generated
tokens at 57,344 with the 8192 cap; nine calls with revisions bounds them at 73,728.
For OpenAI, `max_output_tokens` includes reasoning as well as visible output;
an incomplete response may incur charges without producing usable output. See
[reasoning cost controls](https://developers.openai.com/api/docs/guides/reasoning).

## Remaining release gate

Obtain a separate explicit user authorization identifying endpoint/model, allowed
prepared data, Developer-first session expiry, per-role/aggregate allowances, token/
byte limits, revision allowance, currency budget and verified provider spending
control with accepted overshoot risk. Then provision only the isolated session's
credentials, policy and ledger, and enable that session temporarily. Keep normal
settings/history intact. Disable it afterward. Do not infer authorization from
approval of offline preparation or the implementation of these guards.
