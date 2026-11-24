# Research methods and benchmark results

**Can trace-aware optimization reduce total LLM execution cost and token use while preserving specified quality and latency constraints?**

The five studies below compare full source passages with exact duplicate merging. They used the same task, model, generation settings and quality check for each paired comparison. Every reported token count came from a real local inference provider. The operator left pricing unknown. These studies establish token behavior on the listed cases. They do not establish dollar savings.

| Model | Workload | Input tokens, baseline → candidate | Output tokens, baseline → candidate | Checks passed, baseline → candidate | Decision and raw replay |
|---|---|---:|---:|---|---|
| SmolLM2 135M | Mixed | 730 → 612 | 250 → 268 | 0/6 → 0/6 | [rejected](../benchmarks/local-smollm2-report.json) |
| SmolLM2 135M | Binary QA | 430 → 368 | 4 → 4 | 2/4 → 2/4 | [rejected](../benchmarks/local-binary-report.json) |
| Qwen2.5 0.5B | Mixed | 694 → 572 | 74 → 74 | 4/6 → 4/6 | [rejected](../benchmarks/local-qwen-starter-report.json) |
| Qwen2.5 0.5B | Binary QA | 408 → 342 | 4 → 4 | 2/4 → 2/4 | [rejected](../benchmarks/local-qwen-binary-report.json) |
| Qwen2.5 0.5B | Integer functions | 732 → 608 | 90 → 90 | 6/6 → 6/6 | [eligible](../benchmarks/local-qwen-functions-report.json) |

## Interpretation

The code-specific follow-up used three fresh tasks: square an integer, subtract two integers, and triple an integer. Each ran twice. The fixed quality gate required every answer to implement the named function, comply with the output format and pass the supplied vectors. Both arms passed six checks. Input fell from 732 to 608, total tokens from 822 to 698. The platform approved the candidate in a temporary workspace, executed one monitored request and verified that rollback rejected further use. The narrower workload was selected after the mixed study. The three follow-up tasks and their test vectors were new.

The mixed benchmark contains document QA, structured extraction and code generation. For example, the SmolLM2 baseline answered “The badge is green.” when the case required the exact answer “green”. The checker correctly rejected that output for this format-constrained contract. Exact matching can be inappropriate for free-form factual answers. The mixed and binary studies failed the predeclared 100% gate. All five reports remain in the repository.

## Design and accounting

- Three hand-authored datasets contain separate discovery and evaluation cases. Duplicate held-out cases and exact reuse of the source case are rejected within a study. Similar paraphrases and reuse across studies need researcher review.
- Run order alternates across case and repeat. Each paired arm gets a fresh gateway call. Both repetitions share underlying cases and model seed; six successful executions represent three distinct tasks. Independent generalization error was not estimated.
- The local provider ran llama-cpp-python 0.3.37 with three CPU threads, a 2048-token context window, seed 19 and temperature zero. The output limit was 64 in the mixed and function workloads and one token in binary QA. File export includes actual prompts, model IDs, usage and outputs. Native runtime prefix caching and machine load can influence latency.
- Reports include nearest-rank p50/p95, trial latency standard deviation, exact checks, input and output usage, and timed transformation/evaluation overhead. Small-sample latency results are descriptive. The experiments do not isolate causal speedup from cache effects or concurrent host activity.
- Candidate eligibility requires the minimum pass rate, preservation of every passing baseline case, sufficient evaluation evidence, provider usage, a positive objective improvement and the optional latency ceiling.
- A USD scenario can allocate host occupancy, overhead and a rollout volume. It includes the one-time discovery and paired experiment costs and any judge calls. Include externally performed calibration and other study costs in the operator-provided extra study cost. Measured inference reduction is separate from projected rollout savings. Realized infrastructure cost was unavailable in these local runs.

## Reproduce

The local runner uses a temporary workspace, generated provider secret and self-signed loopback TLS certificate, and requires a local copy of the model weights, OpenSSL and the optional llama-cpp-python package. The core application does not require local model weights. Run from the repository root. Choose a new output path to retain previous reports.

```sh
python -m pip install llama-cpp-python==0.3.37
python scripts/local_study.py --gguf /path/to/qwen2.5-0.5b-instruct-q4_k_m.gguf --dataset benchmarks/integer-functions.json --repeats 2 --max-tokens 64 --approve-calls 14 --verify-policy --output my-functions-report.json
```

The 14-call ceiling includes one discovery call, 12 paired executions and one monitored call if the candidate qualifies. For a running workspace, set ARGUS_WORKSPACE_KEY in your environment and use scripts/benchmark.py with a discovered workspace model ID and an exact approved call count.

The SmolLM2 quantized artifact was obtained from bartowski/SmolLM2-135M-Instruct-GGUF, revision 09816acd5d99df7be770d85ea30822623dab342c. The Qwen quantized artifact was obtained from Qwen/Qwen2.5-0.5B-Instruct-GGUF, revision 9217f5db79a29953eb74d5343926648285ec7e67. SHA-256 values are recorded in the reports. The release excludes model weights. [SmolLM2 weights](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF) · [Qwen weights](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)

## Reference implementations and reuse

| Reference | Design consideration |
|---|---|
| [LiteLLM](https://github.com/BerriAI/litellm) | Keep provider execution and usage accounting behind a provider boundary. |
| [RouteLLM](https://github.com/lm-sys/RouteLLM) | Compare cheaper/stronger routing against a reproducible fixed-model baseline. |
| [LLMLingua](https://github.com/microsoft/LLMLingua) | Evaluate compression outcomes on the downstream task. |
| [Langfuse](https://github.com/langfuse/langfuse) | Connect traces, observations and evaluations through stable identifiers. |
| [DeepEval](https://github.com/confident-ai/deepeval) | Choose a check appropriate to the task and retain evidence. |
| [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) | Use constrained tools, observable actions and explicit approval boundaries. |

The runtime uses FastAPI, SQLAlchemy, Alembic, HTTPX, cryptography, JSON Schema, Hugging Face tokenizers, Next.js, React and Lucide. The trace investigation, transformations, admission ledger, experiment protocol, scoped policies, bounded code evaluator and calibration checks are implemented in this repository. The six reference projects are design references; their implementations are not vendored. Their licensing and enterprise exceptions should be revisited if their code is adopted. The sole learned component exercised in these studies is model inference; the optimization controller uses deterministic tools and historical counts.

## Open research work

The measured ablation isolates exact deduplication. A complete comparison across fixed high/low models, static routing, adaptive routing, evidence selection and combined planning needs calibrated comparable model prices, larger held-out datasets and extra authorized runs. Train a routing predictor on a development partition and freeze it before introducing a separately reserved final test set.
