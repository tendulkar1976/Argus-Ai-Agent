# Verification and implementation status

| Phase | Implemented and verified | Scope still open |
|---|---|---|
| Repository and architecture | Official empty repository cloned locally. FastAPI, SQLAlchemy, Alembic and Next.js production build. All four migrations and the 17-test suite exercised on disposable PostgreSQL and SQLite databases. | Container runtime verification on a Docker host |
| Gateway | Model discovery, TLS execution, native usage, immutable user-supplied prices, access roles, SQL admission limits and trace persistence. Local models tested over real HTTPS. SSE and error paths tested with controlled provider responses. | Credentialed OpenAI/NVIDIA validation and provider-specific compatibility coverage |
| Token intelligence | Per-block composition, exact duplicates, heuristic relevance, linked workflow calls, repeated-failure findings, searchable trace history and source inspection. | Semantic contribution attribution beyond lexical evidence |
| Optimization | Duplicate merging, protected passages and instructions, lexical evidence selection, cheaper-model proposals, scoped response cache and opt-in policies. | Retrieval index, abstractive evidence summaries and autonomous multi-stage workflow redesign |
| Experiment Studio | Distinct held-out cases, alternating order, repeated trials, saved versions, quality gates, paired replay, export, local studies and full policy lifecycle. | Large-batch resumable workers, multi-provider ablations and broader out-of-sample workloads |
| Argus Intelligence | Bounded deterministic orchestration of measured tools. Structured objectives for tokens, latency, inference cost or projected rollout cost. Human approval controls deployment. | Free-text objective parsing and an independently evaluated escalation policy |
| Policy learning | Historical success counts rank candidates for the same baseline model. Policy versions, case-based monitoring and manual rollback. | Calibrated workload-specific predictor or contextual bandit, exploration and long-term drift evaluation |
| Product and research | Responsive, light/dark Studio, frontend production build, browser checks, CI workflow, five genuine local model studies and raw reports. | Identity-provider integration, production load testing, external security review and a statistically powered benchmark |

## Operational limits

- The role model uses workspace-scoped bearer keys. There is no individual user directory or SSO. Audit rows identify workspace, action and resource. Per-user attribution is a future requirement for shared enterprise use.
- Provider discovery depends on a compatible model-list endpoint. Multimodal content, provider-native batch APIs and the Responses API are outside this release. Model prices are supplied by the operator. Cached and unsupported billing categories can leave USD values unknown.
- The hosted service adapters were exercised through wire-compatible providers locally. Vendor accounts and paid credentials were not used. The Compose configuration and GitHub Actions workflow are supplied; this environment has no Docker daemon and no remote workflow was triggered.
- Experiments run synchronously, execute sequentially and checkpoint completed arms. An interrupted experiment may contain a partial pair. Start a fresh batch only after reviewing prior usage. Studio reuses the same approval key when a response is lost. API clients can send an Idempotency-Key header for the same protection during the study retention period. A new key or an unkeyed POST authorizes a new run. Unattended high-volume use still requires background workers and recovery for interrupted jobs.
- Historical ranking is a smoothed success fraction. Mixed benchmarks and tiny sample sizes can confound it. Calibration requires trustworthy labels. High-stakes semantic judgments need independent review.
- Conservative USD controls assume the operator supplied correct full-model bounds and complete rates. Exact invoice reconciliation, third-party tool charges, model snapshot drift, provider-side caching and all infrastructure overhead require deployment-specific integration.
- `projected_net_saving_micros` is an estimate for a supplied rollout volume, cost rates and study overhead. Negative values are possible. Local studies have no verified USD rate and leave realized net savings unknown.
- Access keys, encryption material and production database backup/rotation require owner administration. The default launcher is bound to loopback. Production deployment and public exposure require separate authorization and operational configuration.

## Next engineering priority

Run the same frozen held-out workloads on verified hosted model versions with an owner-approved call and dollar ceiling. Reconcile reported usage against billing, then extend the dataset before training a routing model. Benchmark reports should retain both rejected and eligible results.

## Packaged startup and retry verification

The packaged Studio was extracted into a clean directory on Linux with Python 3.12. The launcher installed a private environment, initialized storage, served the compiled UI and accepted its generated owner key in Chromium. A second launch accepted the same owner key without issuing another. The workspace started empty. The Windows launcher command is documented; native Windows execution is pending.

The browser workflow test simulated losing a completed experiment's HTTP response and resubmitting the approval. The provider fixture received three completions across discovery, baseline and candidate combined. The retried submission returned the existing result. Replay, policy approval, rollback and mobile navigation also passed.
