# Local inference preparation

The current project budget is ₹0. Generation stays disabled: no API usage,
runner installation, model download, credential change or real-model acceptance
has been authorized. This adapter is preparation, not evidence that a real model
has executed an AgentOS mission. Offline scripted demo mode remains a separate,
explicit mode; normal mode never substitutes demo outputs after provider failure.

## Shared provider contract

The optional `ollama` selection implements the existing structured generator
interface and reuses common provider dispatch controls. Developer, Creator and
Student planners/executors receive their existing instructions, original inputs
and registered output schemas. No workflow engine, role manifest, saved plan,
permission, result approval or patch revision contract changes.

`AGENTOS_MODEL_PROVIDER` defaults to `responses` for compatibility. The optional
`ollama` value selects native `/api/chat`, with a default endpoint of
`http://127.0.0.1:11434`. It accepts only HTTP literal loopback roots (`127.0.0.1`
or `::1`), explicit lowercase `name:tag` identifiers without `cloud`, and no API
key. Inherited API-key environment variables are not read for Ollama. Unknown
selections and invalid local settings fail rather than choosing another provider.
No active configuration is changed by adding the adapter.

The existing disabled-generation gate applies before any provider HTTP request,
including availability checks. Production dispatch additionally requires the
existing unexpired endpoint/model-bound policy and durable request ledger; these
are never provisioned automatically. Reservations precede HTTP requests, count
failed attempts and are never refunded. Role/total allowances, input bytes,
output tokens, response bytes and the whole-request deadline remain enforced.
The existing spending-control attestation is preserved, not silently waived for
local inference. It does not independently verify billing or make a remote
service safe under a zero budget. See [dispatch limits](live-acceptance-limits.md).

## Local-only preflight and output validation

If execution is separately authorized in future, each bounded attempt must:

1. Read `/api/status` and receive literal boolean `cloud.disabled: true`.
2. Find the exact installed tag in `/api/tags`, with a positive integer size
   and valid digest. Missing models never trigger a pull/download.
3. Inspect `/api/show`, reject remote model/host references, and require local
   completion capability and model metadata.
4. Submit `/api/chat` with the registered JSON Schema, streaming and thinking
   disabled, no model tools, bounded `num_predict` and `num_ctx`, `truncate: false`,
   `shift: false`, and `keep_alive: 0` to request unloading after completion.
5. Accept only a completed, correctly named local assistant result with stop
   reason `stop`; parse JSON and validate the actual output schema locally.

The contract follows the [native chat API](https://docs.ollama.com/api/chat) and
[structured output interface](https://docs.ollama.com/capabilities/structured-outputs).
Cloud status uses the current [server implementation](https://github.com/ollama/ollama/blob/main/server/routes.go)
and [response types](https://github.com/ollama/ollama/blob/main/api/types.go).
Older runners without this interface fail closed. No installed runner version
has been validated. A runner must honor context-preservation options; successful
metadata checks alone cannot prove this or model quality.

Ollama must use its documented cloud-disable setting and be restarted before
future acceptance; see [local-only settings](https://docs.ollama.com/faq).
AgentOS refuses redirects, ignores proxy environment variables, and does not
call pull, sign-in, web-research or cloud endpoints. This trusts the local runner
and its reported state; a malicious loopback proxy or concurrent runner
reconfiguration is outside that trust boundary. Keep cloud disabled for the whole
run; independent outbound blocking provides additional assurance if required.
The current disabled gate means no prompts are transmitted. A future authorized
local run would transmit instructions, goals, constraints, bounded source/test/
evidence inputs and schemas to the local runner.

Unavailable runner/model, unverifiable cloud state, malformed metadata, timeout,
excessive response, unsupported result, incomplete generation and schema failure
produce errors. There are no automatic retries, downloads, provider switches or
scripted fallback. Existing task recovery and human review remain responsible.

## Hardware feasibility and unvalidated candidate

The read-only Windows audit on 2026-10-10 found an Intel Core i5-12450HX (8 cores,
12 threads), 15.71 GiB RAM, NVIDIA RTX 3050 Laptop GPU with 6 GiB VRAM, and about
150 GiB free on D:. Only 2.64 GiB RAM was available at inspection; close
unnecessary applications yourself before future local acceptance. `nvidia-smi`
supplied VRAM because Windows CIM under-reported it. Ollama was not found on PATH.

A small quantized open-weight model is a plausible starting point. The official
[Qwen3 4B listing](https://ollama.com/library/qwen3:4b) reports about 2.5 GB download
size. Reserve at least 6 GiB disk **plus the runner installation**, and additional
RAM/VRAM for runtime overhead and context. AgentOS requests 8,192 context tokens
by default (programmatic bounds 4,096–32,768); model weights alone do not establish
whether a complete request fits. No download, throughput, schema reliability,
context preservation or mission quality has been validated on this computer.
This is a feasibility recommendation, not a promise of successful patches or
comprehensive role performance.

Download/setup approval must identify runner version, model tag/digest, download
sizes, storage path, cloud-disabled settings and expected runtime memory.
Inference requires separate authorization; downloading is not execution approval.
No paid or supposedly free cloud tier is the fallback.

## Free verification and roadmap continuity

Provider tests use in-memory HTTP transports, including the production branch
with a temporary policy/ledger. They cover selection, disabled operation, all
three profiles' schemas, availability, cloud/remote rejection, deadlines, malformed
results and retained limits without sockets or downloads. Existing continuous
UI/backend tests use injected output and real tools/tests; neither set of checks
demonstrates real AI execution.

This addresses PLAN.md's abstract model/provider configuration and prepares the
real-workflow requirement without changing its definition of done. Real-model
acceptance remains incomplete. The next shared-core roadmap gap is Phase 6
semantic memory retrieval (current retrieval is bounded keyword matching), not
another provider setup feature. Broader role capabilities, optional integrations
and native desktop acceptance retain their original scope and approval rules;
no paid service is required to continue their local implementation.
