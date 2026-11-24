# Engine and API

Studio is a static Next.js export served by FastAPI on the same origin. The gateway, investigation tools, experiment runner and policy store share one database. A workspace-scoped transactional lock serializes admission before each provider call. Experiments and streaming responses release the database transaction while waiting for the provider. Both SQLite and PostgreSQL support the application.

## Workspace and provider configuration

The local operator creates a workspace using `python -m argus.cli workspace "Name"`. The returned owner bearer key is shown once. The owner may issue and revoke runner and reader keys. Readers inspect workspace data, runners execute studies, and owners manage credentials, model versions, budgets and policies. Studio holds its workspace key in memory for the current page lifetime. A refresh closes the session.

Provider credentials, prompts, outputs, calibration examples, checks and experiment reports are encrypted with Fernet. Only hashes of workspace keys are persisted. For local single-host use the encryption key is created under the private state directory. Multi-instance deployments need a common externally supplied key and backup policy. Possession of the key and database grants access to encrypted records.

The server's `ARGUS_PROVIDERS` JSON object maps names to approved HTTPS base URLs. Studio selects a catalog entry. HTTP redirects are disabled. `ARGUS_PROVIDER_CA` optionally selects a certificate authority for private endpoints. A connection is saved after a successful model listing. The owner selects a returned model ID, output parameter and limits. Configure verified cached-input rates, tool support and streaming-usage support where applicable. Catalog discovery proves list access. An actual completion verifies inference access.

## Gateway contract

All application routes require `Authorization: Bearer <workspace key>`. Health and API documentation are public. `GET /v1/models` returns immutable workspace model version IDs. Use an ID as the `model` value. `POST /v1/chat/completions` accepts text chat and returns upstream completion JSON or SSE. The `X-Argus-Trace` response header identifies the stored record. The supported surface is the Chat Completions subset documented in OpenAPI.

```python
import os
import httpx

url = "http://127.0.0.1:8000"
headers = {"Authorization": "Bearer " + os.environ["ARGUS_WORKSPACE_KEY"]}
models = httpx.get(url + "/v1/models", headers=headers).raise_for_status().json()["data"]
response = httpx.post(url + "/v1/chat/completions", headers=headers, timeout=90, json={
    "model": models[0]["id"],
    "messages": [{"role": "user", "content": "What quantity appears on the invoice?"}],
    "evidence": [{"source": "invoice-12", "text": "The quantity is 14.", "critical": True}],
    "max_tokens": 48,
})
response.raise_for_status()
print(response.headers["X-Argus-Trace"], response.json()["choices"][0]["message"])
```

- Supply `parent_trace_id` on subsequent calls to link a multi-step workflow. The trace detail returns the call timeline. Cross-workspace parents are rejected before provider dispatch.
- Text messages, tool definitions, tool call transcripts and tool responses are forwarded on configured tool-capable models. The caller owns tool execution. Agent tools never dispatch arbitrary commands.
- For optional response reuse, set `temperature=0` and `cache_ttl_seconds` from 1 to 3600. Cache reuse is workspace/model-version/request scoped. A hit records a new trace, the origin ID and zero new provider tokens. Experiments run fresh calls. A TTL bounds reuse of a previous answer and provider-side model aliases may change.
- To use a policy, include the approved `policy_id` with its original model version. An inactive policy returns HTTP 409. Requests without a policy use the original strategy.
- The maximum body is 512 KB. The workspace begins with 20 daily inference calls, 30 requests per minute and seven days of retention. The daily call ceiling and retention are editable. Automatic inference retries are disabled to avoid duplicate charges after uncertain failures.
- Daily USD admission uses a conservative reservation at the configured model input maximum and requested output limit. Accurate prices, true provider limits and supported billing categories are prerequisites for meaningful currency controls. Ambiguous calls retain reservations. The provider's own spending limit remains authoritative for the account.
- Provider-reported counts and nested usage are preserved. Optional Hugging Face tokenizer JSON files can be registered with `python -m argus.cli tokenizer path/to/tokenizer.json`; select their immutable hash per model version. Per-block tokenization omits chat-template framing. The fallback is labeled as a UTF-8 byte-length estimate. Prices use USD microdollars internally with conservative rounding per call.

## Investigation, quality and policy lifecycle

| Operation | Method and path |
|---|---|
| Workspace, models and verified connections | GET /api/workspace |
| Verify provider and register model version | POST /api/connections, POST /api/models |
| Issue, enumerate and revoke delegated keys | POST /api/keys, GET /api/keys, DELETE /api/keys/{id} |
| Usage totals and recent traces | GET /api/overview, GET /api/traces |
| Trace, attribution, sent messages and output | GET /api/traces/{id} |
| Analyze a discovery trace and rank hypotheses | POST /api/investigations/{id} |
| Pre-calibrate a rubric judge | POST /api/judges |
| Read judge results and model configuration | GET /api/judges/{id} |
| Approve a bounded experiment batch | POST /api/experiments |
| Replay, export and review the paired report | GET /api/experiments/{id} |
| Create policy version after quality gate | POST /api/experiments/{id}/approve |
| List versions and disable a version | GET /api/policies, POST /api/policies/{id}/rollback |
| Inspect operator actions and rollback signals | GET /api/audit |

For retryable study submissions, send a stable `Idempotency-Key` header with `POST /api/experiments`. Parallel submissions with the same workspace, key and configuration return the same study ID. A retry during execution returns its current checkpoint. Changing the configuration under that key returns HTTP 409. This protection lasts until the study expires. Studio keeps a pending key in the browser tab across a failed response and reload.

Exact match, numeric tolerance, expected JSON fields, bounded JSON Schema, source-ID citations, integer-function test vectors and calibrated judge verdicts are available. The integer-function evaluator interprets a small expression grammar with a bounded syntax tree, argument count and integer size. A citation check verifies cited source IDs. Semantic support requires an independently specified check or rubric.

For a rubric judge, submit the model version, rubric, distinct expert-labeled calibration examples, minimum agreement and explicit call count. Both passing and failing groups must meet agreement independently. The saved judge ID becomes the expected value of a `rubric_judge` check. A judge call consumes one additional approved call per arm. Each verdict, justification and usage links to its trace. Uncertain or malformed verdicts prevent approval. Only deterministic checks are automatically repeated in policy monitoring. Arbitrary live requests without reference answers are marked unscored.

Retention runs at startup and hourly; `python -m argus.cli prune` runs it immediately. Calibration data, studies and their active policies expire with the retention window. Failed or interrupted calls remain visible while retained. Client-side credentials and inference data are not logged by application code.
