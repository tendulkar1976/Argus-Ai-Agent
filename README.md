# Argus-AI Studio

**Autonomous LLM Execution Intelligence & Optimization Platform**

Argus records LLM calls, identifies redundant context, runs paired experiments and lets a workspace owner approve or roll back a measured change. Its research question is whether trace-aware optimization can reduce execution cost and token use while preserving a workload's required quality.

**Research title** — Intelligent Token Optimization for Cost-Effective and High-Performance LLM Applications  
**Tagline** — Observe. Optimize. Validate. Evolve.

## Run locally

Extract the release ZIP, open a terminal in the folder containing `start.py`, and run the command below using Python 3.12. The release includes the built Studio. A source checkout also needs Node.js 24 and npm for the first frontend build.

```sh
python start.py
```

Open **http://127.0.0.1:8000**. On first start the terminal prints one private workspace key. Save it and enter it in Studio. The launcher installs dependencies into the project's virtual environment and starts a loopback server. The first installation needs internet access. For the Windows Python launcher, use `py -3.12 start.py`. Press Ctrl+C in the terminal to stop.

1. Choose **Configure provider**, select a catalog entry and enter a provider key. **Test connection** discovers the models available to that credential.
2. Select a discovered model. Enter its verified input/output limits and any known rates in USD per million tokens. Save the model version. Changes to prices create separately identifiable versions.
3. On **Overview**, choose **Run first request**. Enter a task and add individually named source passages. Add a repeated passage to investigate exact duplication.
4. Inspect the recorded trace, context composition and output. Choose **Investigate trace** to see the evidence and candidate strategies.
5. Enter distinct held-out tasks, source passages, expected answers and quality checks. Review and approve the displayed number of provider calls.
6. Inspect both outputs in **Replay pair**. An eligible result can become a policy. Select that policy on later requests and inspect its monitoring record. **Roll back** disables that version.

Studio starts empty. The benchmark reports in this repository are offline artifacts. They are never inserted into a new workspace.

## What has run

The first five recorded local studies used two real quantized language models, an HTTPS provider adapter, the authenticated gateway, encrypted persisted traces and deterministic output checks. Four candidates failed the required threshold. On a separate Qwen integer-function study, both arms passed all six checks and the candidate used 608 input tokens against 732. The owner approval, monitored call and rollback completed against real inference. Replay records include model output and provider usage. See [benchmark results](docs/research.md).

## Developer entry points

| Component | Location |
|---|---|
| Next.js / TypeScript Studio | `studio/app/` |
| HTTP contracts and OpenAPI documentation | `argus/contracts.py`, `/docs`, `/openapi.json` |
| Provider communication, budgets, accounting | `argus/gateway.py` |
| Trace analysis, context transformations, checks | `argus/intelligence.py`, `argus/evaluators.py` |
| Experiments, investigations and policies | `argus/research.py` |
| Calibrated rubric judging | `argus/judges.py` |
| Source datasets, raw results and replay | `benchmarks/` |
| Tests and browser acceptance test | `tests/` |

Read [API and architecture](docs/architecture.md), [verification and limitations](docs/status.md), and [research methods](docs/research.md).

## Development and verification

```sh
python -m venv .venv
# Activate the virtual environment for your shell before continuing.
python -m pip install -r requirements.txt pytest playwright
python -m argus.cli init
python -m pytest -q
cd studio
npm ci
npm run build
cd ..
python -m playwright install chromium
python tests/browser_workflow.py
```

The browser test starts isolated storage and a labeled test provider. Set `CHROMIUM_PATH` to use an installed headless Chromium binary. To rebuild after frontend edits, use `python start.py --rebuild-studio`.

## Docker Compose

Copy `.env.example` to `.env`. Set `POSTGRES_PASSWORD` to a random URL-safe password and provide a Fernet `ARGUS_ENCRYPTION_KEY`. A private key can be generated locally with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

```sh
docker compose up --build -d
docker compose exec engine python -m argus.cli workspace "My workspace"
```

The Compose stack uses PostgreSQL, a persistent database volume and a loopback-bound application port. Local Python startup defaults to SQLite. The two database modes use the same SQLAlchemy schema and Alembic migrations.

Official repository: [tendulkar1976/Argus-Ai-Agent](https://github.com/tendulkar1976/Argus-Ai-Agent).
