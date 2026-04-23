# EvalHub Adapter

Integration layer that bridges the existing pytest-based eval harness to
[EvalHub](https://github.com/redhat-ai-services/evalhub)'s Kubernetes
orchestration on OpenShift. Designed to run **on-cluster** as an EvalHub job.

> **Spike**: RHAIENG-4604 — lean POC, not production-hardened yet.

## Who this is for

Platform engineers deploying EvalHub on OpenShift who want to run scored
behavioral evaluations against agentic-starter-kit agents.

## Architecture

Four files that do one thing: translate EvalHub's `JobSpec` into harness
calls and report results back.

| File | Role |
|------|------|
| `adapter.py` | `AgenticEvalAdapter` — implements EvalHub's `FrameworkAdapter`. Drives the pipeline: INITIALIZING → LOADING_DATA → RUNNING_EVALUATION → POST_PROCESSING → PERSISTING_ARTIFACTS → results. Entry point: `main()`. |
| `config.py` | Maps job parameters and per-query fields into `TaskConfig`. Defines `AgenticEvalParams` (known_tools, forbidden_actions, max_latency_seconds, timeout_seconds, verify_ssl, MLflow settings). |
| `benchmarks.py` | Registry mapping benchmark IDs to golden-query YAML files + scorer lists. Includes `agentic-tool-use` (5 queries). |
| `__init__.py` | Exports `AgenticEvalAdapter`. |

## Inner loop vs outer loop

| | Inner loop (CI) | Outer loop (EvalHub) |
|---|---|---|
| **What** | pytest — API contract, adversarial, unit tests | Scored behavioral evals, latency benchmarks |
| **Where** | Local / GitHub Actions | K8s jobs on OpenShift |
| **Speed** | Seconds to minutes | Minutes to tens of minutes |
| **Purpose** | Gate merges | Track quality over time, feed dashboards |

EvalHub does **not** replace CI tests. They cover different layers. The outer
loop is the target state; see **What works now** for current scope.

## Design decisions

- **One adapter, all agents.** The adapter is agent-agnostic. Benchmark query
  files contain agent-specific `expected_tools`; each agent with different tools
  needs its own query files.
- **Runtime config via `JobSpec.parameters`.** Agent-specific settings
  (known_tools for hallucination detection, thresholds, forbidden actions) are
  passed at job submission time, not baked into benchmarks.
- **No scoring logic here.** All scorers live in `harness/scorers/`. The adapter
  reuses them: tool_selection, tool_sequence, hallucinated_tools,
  tool_call_validity, plan_coherence, completeness, latency, pii_leakage,
  policy_adherence, injection_resistance.

## Running on-cluster

EvalHub invokes `main()` in `adapter.py`. JobSpec loading is handled by
EvalHub's `FrameworkAdapter` base class (reads from `/meta/job.json` or
`EVALHUB_JOB_SPEC_PATH`).

## JobSpec parameters

The adapter reads agent-specific settings from `JobSpec.parameters`:

```json
{
  "known_tools": ["search"],
  "forbidden_actions": ["shell execution"],
  "max_latency_seconds": 8.0,
  "timeout_seconds": 30.0,
  "verify_ssl": true,
  "mlflow_tracking_uri": "http://mlflow:5000",
  "mlflow_experiment_name": "agentic-evals"
}
```

All fields are optional with sensible defaults. Unknown keys are silently
ignored. `timeout_seconds` and `max_latency_seconds` must be positive
(validated at job start; `ValueError` on zero/negative values).

## MLflow integration

Two distinct features, both optional (require `mlflow_tracking_uri` and
`mlflow_experiment_name` in job parameters, plus `MLflowTraceClient`
importable for trace enrichment):

1. **Trace enrichment** (per-query) — `MLflowTraceClient` from
   `harness.mlflow_client` reads agent-side traces after each query to fill
   in tool_calls and token usage. Needed because the HTTP response doesn't
   always expose tool calls. Fault-tolerant: enrichment failures are logged
   but do not abort the query or affect scoring.
2. **Run logging** (per-job) — `_log_mlflow_run` writes aggregated scorer
   results (metrics, pass rates, overall score, duration) to MLflow as a run.

## What works now

- `agentic-tool-use` benchmark: 5 golden queries for search-tool agents
  (`tests/behavioral/fixtures/benchmarks/tool_use.yaml`)
- Scoring dispatch wired for 10 scorers; `agentic-tool-use` exercises 4
  (tool_selection, tool_sequence, hallucinated_tools, tool_call_validity)
- Config translation from EvalHub `JobSpec` → harness `TaskConfig`
- MLflow integration (trace enrichment + run logging)
- Unit tests for config, benchmarks, and adapter modules

## What's planned

- Concurrent query execution (`asyncio.gather` with semaphore — queries
  currently run sequentially)
- Additional benchmarks: coherence, safety, latency, full suite (previously
  spiked, query files not yet populated)
- Vanilla Python agent query files
- End-to-end validation on OpenShift
- GitHub Actions workflow for CI / EvalHub integration
- Regression dashboard

## Dependencies

| Package | Version | Install extra | Required |
|---------|---------|---------------|----------|
| `evalhub` | `>=0.1,<1.0` | `evalhub` | Yes |
| `httpx` | `>=0.27` | `evalhub` | Yes |
| `pyyaml` | `>=6.0` | `evalhub` | Yes |
| `mlflow` | `>=2.0` | `test-mlflow` | No (trace enrichment + run logging) |

For container builds or local development:

```bash
uv pip install .[evalhub]              # core adapter deps
uv pip install .[evalhub,test-mlflow]  # + MLflow support
```

## Running unit tests

Tests stub `evalhub` imports if the package isn't installed (bootstrap
lives in `conftest.py` so it runs before any test module, regardless of
which files are selected). `uv pip install .[test]` alone is sufficient.

```bash
pytest tests/behavioral/evalhub_adapter/tests/ -m unit -v
```
