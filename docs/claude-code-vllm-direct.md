# Claude Code with vLLM Direct (No OGX)

Deploy Claude Code on OpenShift pointing directly at vLLM's `/v1/messages` endpoint, bypassing OGX entirely. This is the simplest architecture for running Claude Code against a self-hosted model.

Related Jira: RHAIENG-4747

## Architecture

```text
Claude Code pod  ──HTTP──▶  vLLM service (ClusterIP :8000)
                             └── /v1/messages (Anthropic Messages API)
```

No OGX, no translation layer. vLLM natively serves the Anthropic Messages API format.

## Prerequisites

| Requirement | Description |
|-------------|-------------|
| **OpenShift cluster** | With GPU nodes available (e.g., `g6e.12xlarge` for 4x L40S) |
| **GPU node pool** | Labeled for scheduling (e.g., `node-pool=gpu-g6e-12xl`) |
| **Model with 32K+ context** | Claude Code's system prompt is ~20K+ tokens. Models with 16K or less will fail. Recommended: 64K+ for multi-turn conversations. |
| **`oc` CLI** | Logged into the target OpenShift cluster |
| **Build files** | `Containerfile`, `entrypoint.sh`, `deployment.yaml` from the [claude-agent branch](https://github.com/red-hat-data-services/agentic-starter-kits/tree/claude-agent/agents/claude/claude_agent) |

## Configuration Reference

| Variable | Description | Example |
|----------|-------------|---------|
| `<NAMESPACE>` | Namespace for vLLM and Claude Code | `redhat-ods-applications` |
| `<MODEL_NAME>` | Model identifier from `/v1/models` | `openai/gpt-oss-120b` |
| `<NODE_POOL>` | GPU node pool label | `gpu-g6e-12xl` |
| `<TP_SIZE>` | Tensor parallel size (number of GPUs) | `4` |
| `<MAX_MODEL_LEN>` | Max context length | `131072` |

## Step 1: Deploy vLLM

Deploy vLLM as a standalone Deployment with the model served directly (no storage-initializer sidecar — vLLM downloads the model at startup):

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <MODEL_SHORT_NAME>
  namespace: <NAMESPACE>
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <MODEL_SHORT_NAME>
  template:
    metadata:
      labels:
        app: <MODEL_SHORT_NAME>
    spec:
      nodeSelector:
        node-pool: <NODE_POOL>
      tolerations:
      - key: nvidia.com/gpu
        operator: Exists
        effect: NoSchedule
      containers:
      - name: vllm
        image: registry.redhat.io/rhaiis/vllm-cuda-rhel9@sha256:2ebb2ffb49a2a270d4f634c22e81ee2b8da038063df4957ecbd3c9e66ee57491
        command:
          - python3
          - -m
          - vllm.entrypoints.openai.api_server
          - --model
          - <MODEL_NAME>
          - --host
          - "0.0.0.0"
          - --port
          - "8000"
          - --tensor-parallel-size
          - "<TP_SIZE>"
          - --max-model-len
          - "<MAX_MODEL_LEN>"
          - --tool-call-parser
          - openai
          - --enable-auto-tool-choice
        ports:
        - containerPort: 8000
          name: http
          protocol: TCP
        resources:
          requests:
            memory: "32Gi"
            cpu: "4"
            nvidia.com/gpu: "<TP_SIZE>"
          limits:
            memory: "128Gi"
            cpu: "16"
            nvidia.com/gpu: "<TP_SIZE>"
        env:
        - name: HF_HOME
          value: /tmp/huggingface
        - name: HOME
          value: /tmp
        - name: XDG_CACHE_HOME
          value: /tmp/.cache
        - name: FLASHINFER_WORKSPACE_DIR
          value: /tmp/flashinfer
        - name: HF_HUB_ENABLE_HF_TRANSFER
          value: "0"
        - name: TRANSFORMERS_OFFLINE
          value: "0"
        - name: HF_HUB_OFFLINE
          value: "0"
        - name: CURL_CA_BUNDLE
          value: /etc/pki/tls/certs/ca-bundle.crt
        - name: NCCL_DEBUG
          value: "INFO"
        - name: NCCL_IB_DISABLE
          value: "1"
        - name: NCCL_P2P_DISABLE
          value: "0"
        - name: VLLM_LOGGING_LEVEL
          value: "DEBUG"
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
          timeoutSeconds: 5
        volumeMounts:
        - name: shm
          mountPath: /dev/shm
      volumes:
      - name: shm
        emptyDir:
          medium: Memory
          sizeLimit: 16Gi
---
apiVersion: v1
kind: Service
metadata:
  name: <MODEL_SHORT_NAME>
  namespace: <NAMESPACE>
  labels:
    app: <MODEL_SHORT_NAME>
spec:
  selector:
    app: <MODEL_SHORT_NAME>
  ports:
  - name: http
    port: 8000
    targetPort: 8000
    protocol: TCP
  type: ClusterIP
```

**Key settings:**

- `HF_HUB_ENABLE_HF_TRANSFER=0` — use standard HTTP downloads. The HF Xet high-performance downloader can stall on large models (60GB+) in cluster environments.
- `NCCL_IB_DISABLE=1` — disables InfiniBand (not available on standard GPU instance types like g6e).
- `/dev/shm` at 16Gi — required for NCCL multi-GPU communication with tensor parallelism.
- `readinessProbe` on `/health` — required for OpenShift routes to forward traffic.

Apply:

```bash
oc apply -f vllm-deployment.yaml -n <NAMESPACE>
```

Wait for the model to download and load (10–30 minutes for large models):

```bash
oc rollout status deployment/<MODEL_SHORT_NAME> -n <NAMESPACE>
oc logs -f deployment/<MODEL_SHORT_NAME> -n <NAMESPACE>
```

## Step 2: Create External Route

Create a network policy (required in `redhat-ods-applications` namespace) and external route:

```bash
# Network policy — allow ingress to port 8000
cat <<EOF | oc apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-<MODEL_SHORT_NAME>-ingress
  namespace: <NAMESPACE>
spec:
  podSelector:
    matchLabels:
      app: <MODEL_SHORT_NAME>
  ingress:
  - ports:
    - port: 8000
      protocol: TCP
  policyTypes:
  - Ingress
EOF

# External route (TLS edge termination)
oc create route edge <MODEL_SHORT_NAME>-external \
  --service=<MODEL_SHORT_NAME> --port=http -n <NAMESPACE>
```

## Step 3: Verify vLLM Endpoints

```bash
VLLM_ROUTE=$(oc get route <MODEL_SHORT_NAME>-external -n <NAMESPACE> -o jsonpath='{.spec.host}')

# Health check
curl -sk "https://$VLLM_ROUTE/health"

# List models
curl -sk "https://$VLLM_ROUTE/v1/models"

# Non-streaming (Anthropic Messages API)
curl -sk "https://$VLLM_ROUTE/v1/messages" \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","max_tokens":50,"messages":[{"role":"user","content":"Hello"}]}'

# Streaming (SSE)
curl -sk "https://$VLLM_ROUTE/v1/messages" \
  -H "Content-Type: application/json" \
  -d '{"model":"<MODEL_NAME>","max_tokens":50,"stream":true,"messages":[{"role":"user","content":"Hello"}]}'
```

The streaming response should include all SSE event types: `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`.

## Step 4: Deploy Claude Code

### Prepare Build Context

```bash
mkdir -p claude-code-build && cd claude-code-build

for f in Containerfile entrypoint.sh deployment.yaml; do
  gh api "repos/red-hat-data-services/agentic-starter-kits/contents/agents/claude/claude_agent/$f" \
    -H "Accept: application/vnd.github+json" -f ref=claude-agent --jq '.content' | base64 -d > "$f"
done

chmod +x entrypoint.sh
```

### Configure deployment.yaml

Set the env vars to point at the vLLM service:

```yaml
env:
  - name: HOME
    value: "/home/claude-agent"
  - name: ANTHROPIC_API_KEY
    valueFrom:
      secretKeyRef:
        name: claude-credentials
        key: ANTHROPIC_API_KEY
  - name: ANTHROPIC_BASE_URL
    value: "http://<MODEL_SHORT_NAME>.<NAMESPACE>.svc.cluster.local:8000"
  - name: CLAUDE_MODEL
    value: "<MODEL_NAME>"
  - name: MCP_CONFIG_FILE
    value: "/etc/mcp/config.json"
  - name: SKIP_PERMISSIONS
    value: "true"
```

Since the standalone vLLM deployment serves plain HTTP (no TLS), `NODE_TLS_REJECT_UNAUTHORIZED` is not needed.

### Create Resources and Build

```bash
# Dummy API key (vLLM doesn't validate it, but Claude Code requires it)
oc create secret generic claude-credentials \
  --from-literal=ANTHROPIC_API_KEY=dummy-key-for-vllm \
  -n <NAMESPACE>

oc apply -f deployment.yaml -n <NAMESPACE>
oc start-build claude-code --from-dir=. --follow -n <NAMESPACE>
```

### Verify

```bash
oc rollout status deployment/claude-code -n <NAMESPACE>
oc logs deployment/claude-code -n <NAMESPACE>
```

Expected output:

```text
[entrypoint] INFO: Starting Claude Code container
[entrypoint] INFO: Using custom API endpoint: http://<MODEL_SHORT_NAME>.<NAMESPACE>.svc.cluster.local:8000
[entrypoint] INFO: Using model: <MODEL_NAME>
```

### Smoke Test

```bash
oc exec deployment/claude-code -n <NAMESPACE> -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2? Reply with just the number."
'
```

## Testing

Two test scripts are provided in `infrastructure/vllm/` to validate the full setup.

### vLLM Endpoint Validation

Tests vLLM's OpenAI and Anthropic API endpoints directly (no Claude Code). Requires only `curl` and `jq`.

```bash
bash infrastructure/vllm/test_vllm_endpoints.sh \
  --url https://<VLLM_EXTERNAL_ROUTE> \
  --model <MODEL_NAME>
```

Tests: health check, model listing, OpenAI chat (streaming + non-streaming), Anthropic messages (streaming + non-streaming), multi-turn conversation, tool use.

### Claude Code Test Matrix

Tests Claude Code CLI functionality via `oc exec`. Requires `oc` logged into the cluster.

```bash
bash infrastructure/vllm/test_claude_code_matrix.sh \
  --namespace <NAMESPACE> \
  --deployment claude-code
```

Tests: single-turn prompt, multi-step reasoning, bash tool use, file read tool use, streaming.

### Configuration

Both scripts accept CLI flags or environment variables:

| Env Var | CLI Flag | Default | Description |
|---------|----------|---------|-------------|
| `VLLM_URL` | `--url` | (required) | vLLM base URL |
| `VLLM_MODEL` | `--model` | (required) | Model name |
| `VLLM_API_KEY` | `--api-key` | `""` | API key (if auth enabled) |
| `VLLM_NAMESPACE` | `--namespace` | `redhat-ods-applications` | OpenShift namespace |
| `CLAUDE_DEPLOYMENT` | `--deployment` | `claude-code` | Claude Code deployment |
| `VLLM_TIMEOUT` | `--timeout` | `60` / `120` | Request timeout (seconds) |

### Latency Benchmark

Measures latency, TTFB, and throughput across request types. Results are saved to a timestamped JSON file.

```bash
bash infrastructure/vllm/test_vllm_latency.sh \
  --url https://<VLLM_EXTERNAL_ROUTE> \
  --model <MODEL_NAME> \
  --runs 3 \
  --output .
```

### Validated Results

Tested with `openai/gpt-oss-120b` on `g6e.12xlarge` (4x L40S, 131K context):

| Test | Result |
|------|--------|
| Health check | PASS |
| Model listing | PASS |
| OpenAI chat (non-streaming) | PASS |
| OpenAI chat (streaming) | PASS |
| Anthropic messages (non-streaming) | PASS |
| Anthropic messages (streaming, all SSE events) | PASS |
| Multi-turn conversation | PASS |
| Tool use (Anthropic API) | PASS |
| Claude Code single-turn | PASS |
| Claude Code multi-step reasoning | PASS |
| Claude Code bash tool use | PASS |
| Claude Code file read tool use | PASS |
| Claude Code streaming | PASS |

### Latency Results

Measured with `openai/gpt-oss-120b` on `g6e.12xlarge` (4x L40S), 3 runs averaged:

| Test | TTFB | Total | Tokens | Throughput |
|------|------|-------|--------|------------|
| Short prompt — OpenAI | — | 449ms | 48 | 108.5 tok/s |
| Short prompt — Anthropic | — | 394ms | 44 | 112.8 tok/s |
| Short prompt — OpenAI streaming | 353ms | 368ms | 31 | 83.9 chunk/s |
| Short prompt — Anthropic streaming | 353ms | 362ms | 6 | 16.9 chunk/s |
| Long prompt — OpenAI | — | 1347ms | 200 | 148.6 tok/s |
| Long prompt — Anthropic | — | 1310ms | 200 | 152.5 tok/s |
| Long prompt — OpenAI streaming | 511ms | 1305ms | 194 | 148.5 chunk/s |
| Long prompt — Anthropic streaming | 1303ms | 1340ms | 91 | 69.4 chunk/s |
| Multi-turn (3 messages) | — | 567ms | 70 | 123.1 tok/s |
| Tool use | — | 451ms | 49 | 109.2 tok/s |

**Key observations:**

- Non-streaming OpenAI and Anthropic APIs perform nearly identically (~110-150 tok/s).
- Anthropic streaming uses fewer, larger SSE chunks than OpenAI streaming.
- TTFB for short prompts is ~350ms; long prompts ~500-1300ms.
- Tool use adds no measurable overhead vs regular prompts.

### Model Aliasing

vLLM supports model aliasing via `--served-model-name`. This lets you serve a model under a custom name without OGX.

**How it works:**

Add `--served-model-name` to the vLLM command:

```yaml
command:
  - python3
  - -m
  - vllm.entrypoints.openai.api_server
  - --model
  - openai/gpt-oss-120b
  - --served-model-name
  - my-custom-model-name
  # ... other flags
```

Then set `CLAUDE_MODEL` on the Claude Code pod to match:

```bash
oc set env deployment/claude-code CLAUDE_MODEL=my-custom-model-name
```

**Validated results:**

| Test | Result |
|------|--------|
| Alias registered in `/v1/models` | PASS |
| API request with alias | PASS |
| Claude Code with aliased model name | PASS |

**Important behavior:**

- `--served-model-name` is a **replacement**, not an addition. The original HuggingFace model ID (`openai/gpt-oss-120b`) is no longer recognized after setting an alias.
- To keep both the original name and an alias, pass the flag twice: `--served-model-name openai/gpt-oss-120b --served-model-name my-alias`.
- No OGX is required for model aliasing — vLLM handles it natively.

## Acceptance Criteria (RHAIENG-4747)

| Criteria | Status | Notes |
|----------|--------|-------|
| ANTHROPIC_BASE_URL set directly to vLLM (no OGX) | Done | `http://gpt-oss-120b:8000` |
| vLLM `/v1/messages` accessible, accepts Anthropic Messages API | Done | Non-streaming + streaming verified |
| Single-turn test | Done | Passed via API and Claude Code CLI |
| Multi-turn test | Done | Context preserved across messages |
| Tool use test | Done | Bash, file read, and Anthropic API `tool_use` all passed |
| Streaming test | Done | All 6 SSE event types present |
| Model aliasing env vars tested | Done | `--served-model-name` works without OGX; replaces original name |
| Latency baseline documented | Done | ~110-150 tok/s, ~350-500ms TTFB |
| Latency comparison: direct vLLM vs OGX | Blocked | OGX not available yet (RHAIENG-4745) |
| Document gaps if `/v1/messages` incomplete | Done | No gaps — full Anthropic API support confirmed |

## Known Limitations

### Context Window Requirement

Claude Code sends a large internal system prompt (~20K+ tokens) with every request. Models with insufficient context will fail:

```text
API Error: 400 {"type":"error","error":{"type":"BadRequestError",
"message":"max_tokens must be at least 1, got -7214."}}
```

**Minimum:** 32K tokens. **Recommended:** 64K+ for multi-turn conversations with tool use.

### LLMInferenceService vs Standalone Deployment

The KServe `LLMInferenceService` CRD adds a `storage-initializer` init container that uses HF Xet for model downloads. This can stall on large models (60GB+) due to CDN timeouts, and the CRD does not expose init container env overrides. The standalone Deployment approach (shown above) lets vLLM download the model directly with standard HTTP, which is more reliable.

Use `LLMInferenceService` when you need the llm-d router/scheduler for multi-replica intelligent routing. Use standalone Deployment for single-replica setups or when the init container stalls.

## Cleanup

```bash
# vLLM
oc delete deployment <MODEL_SHORT_NAME> -n <NAMESPACE>
oc delete service <MODEL_SHORT_NAME> -n <NAMESPACE>
oc delete route <MODEL_SHORT_NAME>-external -n <NAMESPACE>
oc delete networkpolicy allow-<MODEL_SHORT_NAME>-ingress -n <NAMESPACE>

# Claude Code
oc delete deployment claude-code -n <NAMESPACE>
oc delete buildconfig claude-code -n <NAMESPACE>
oc delete imagestream claude-code -n <NAMESPACE>
oc delete secret claude-credentials -n <NAMESPACE>
oc delete configmap claude-mcp-config claude-skills -n <NAMESPACE>
oc delete pvc claude-workspace -n <NAMESPACE>
oc delete service claude-code -n <NAMESPACE>
```

## Next Steps

- Latency comparison: direct vLLM vs. OGX translation vs. OGX passthrough (pending OGX availability — RHAIENG-4745)
