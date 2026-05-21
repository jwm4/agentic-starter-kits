# How to Deploy Claude Code on OpenShift

A step-by-step guide to build, test, and deploy the Claude Code container image.

## Licensing Notice

**Do not redistribute built container images.** The Containerfile installs Claude Code at build time via Anthropic's native installer. The resulting image contains Anthropic's proprietary binary, which is subject to their [commercial terms](https://code.claude.com/docs/en/legal-and-compliance) ("All rights reserved"). Building the image yourself for internal use is permitted, but redistributing the built image (e.g., pushing to a public registry) is not authorized.

## Prerequisites

- `podman` installed locally (on macOS, you also need to run `podman machine init` and `podman machine start` before building)
- `oc` CLI installed and logged into your OpenShift cluster
- An Anthropic API key OR a GCP service account key for Vertex AI
- The Containerfile and entrypoint.sh files

---

## Option A: Deploy with Anthropic API Key

### 0. Get your Anthropic API key

1. Go to [https://console.anthropic.com/](https://console.anthropic.com/)
2. Sign in or create an account
3. Navigate to **API Keys** in the left sidebar
4. Click **Create Key** and give it a name
5. Copy the key (it starts with `sk-ant-api03-...`)

**Note**: You need a paid account with credits to use the API.

### 1. Build and test locally

```bash
# Build
podman build -t claude-code:latest -f Containerfile .

# Build with a specific Claude Code version
podman build --build-arg CLAUDE_CODE_VERSION=2.1.123 -t claude-code:2.1.123 -f Containerfile .

# Test (non-interactive)
podman run --rm \
  -e ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE" \
  claude-code:latest \
  claude -p "What is 2+2?"
```

### 2. Create OpenShift namespace

```bash
oc new-project my-claude-project
```

### 3. Create the API key secret

```bash
oc create secret generic claude-credentials \
  --from-literal=ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE"
```

### 4. Apply the deployment manifest

```bash
oc apply -f deployment.yaml
```

### 5. Build the image on OpenShift

```bash
oc start-build claude-code --from-dir=. --follow
```

### 6. Wait for deployment and test

```bash
# Wait for rollout
oc rollout status deployment/claude-code

# Test using the claude-run wrapper (includes all configured args)
oc exec deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2?"
'
```

**Note**: The `claude-run` wrapper automatically includes all container-configured arguments (permission bypass, MCP config, model selection, etc.). You can also source the environment directly:

```bash
oc exec deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS -p "What is 2+2?"
'
```

### 7. Interactive mode (optional)

For a full interactive Claude Code experience with multi-turn conversations:

```bash
# Local interactive mode
podman run -it --rm \
  -e ANTHROPIC_API_KEY="sk-ant-api03-YOUR_KEY_HERE" \
  -v $(pwd):/workspace:z \
  claude-code:latest \
  claude

# OpenShift interactive mode (uses claude-run for proper config)
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  ~/.claude/claude-run
'
```

**Note**: Interactive mode requires a TTY, so use `-it` flags with podman and `oc exec`.

### 8. Debug mode (optional)

To see detailed logging of Claude Code activity, use the `--debug` flag:

```bash
# Enable full debug logging
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  claude --debug api
'
```

Debug logs are written to a file. To monitor the logs in real-time, open a second terminal and run:

```bash
oc exec deployment/claude-code -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

---

## Option B: Deploy with Vertex AI

### 0. Get your GCP service account key

You need a GCP service account with Vertex AI access. Choose one of these methods:

**Option 1: Create a new service account in GCP Console**

1. Go to [GCP Console](https://console.cloud.google.com)
2. Select your project (must have Vertex AI API enabled)
3. Navigate to **IAM & Admin → Service Accounts**
4. Click **+ CREATE SERVICE ACCOUNT**
   - Name: `claude-code-user` (or your preferred name)
   - Grant role: **Vertex AI User** (`roles/aiplatform.user`)
5. Click on the service account → **Keys** tab
6. Click **Add Key → Create new key → JSON**
7. The key file downloads automatically - save it securely

**Option 2: Use gcloud CLI**

```bash
# Create service account
gcloud iam service-accounts create claude-code-user \
  --display-name="Claude Code User"

# Grant Vertex AI access
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:claude-code-user@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Create and download key
gcloud iam service-accounts keys create ~/claude-vertex-key.json \
  --iam-account=claude-code-user@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

**Note**: Creating service accounts requires **IAM Admin** or **Service Account Admin** permissions in the GCP project.

**Alternative: Application Default Credentials (ADC)**

If you already have credentials via `gcloud auth application-default login`, you can use your ADC file (typically at `~/.config/gcloud/application_default_credentials.json`) in place of a service account key. Substitute this path wherever the instructions reference your service account key file.

### 1. Build and test locally

```bash
# Build
podman build -t claude-code:latest -f Containerfile .

# Build with a specific Claude Code version
podman build --build-arg CLAUDE_CODE_VERSION=2.1.123 -t claude-code:2.1.123 -f Containerfile .

# Test (non-interactive)
podman run --rm \
  -e CLAUDE_CODE_USE_VERTEX=1 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id" \
  -e CLOUD_ML_REGION="global" \
  -e GOOGLE_APPLICATION_CREDENTIALS="/var/secrets/google/key.json" \
  -v /path/to/your-service-account-key.json:/var/secrets/google/key.json:ro,z \
  claude-code:latest \
  claude -p "What is 2+2?"
```

### 2. Create OpenShift namespace

```bash
oc new-project my-claude-project
```

### 3. Create the GCP credentials secret

```bash
oc create secret generic claude-vertex-credentials \
  --from-file=key.json=/path/to/your-service-account-key.json
```

### 4. Apply the Vertex AI deployment manifest and update the ConfigMap

Apply the manifest first to create all the resources, then immediately patch the ConfigMap with your actual project details before the pod starts using them:

```bash
oc apply -f deployment-vertex.yaml
```

```bash
oc patch configmap claude-vertex-config \
  -p '{"data":{"ANTHROPIC_VERTEX_PROJECT_ID":"your-gcp-project-id","CLOUD_ML_REGION":"global"}}'
```

### 5. Build the image on OpenShift

```bash
oc start-build claude-code --from-dir=. --follow
```

### 6. Wait for deployment and test

```bash
oc rollout status deployment/claude-code-vertex

# Test using the claude-run wrapper (includes all configured args)
oc exec deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  ~/.claude/claude-run -p "What is 2+2?"
'
```

**Note**: The `claude-run` wrapper automatically includes all container-configured arguments (permission bypass, MCP config, model selection, etc.). You can also source the environment directly:

```bash
oc exec deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS -p "What is 2+2?"
'
```

**Note on model selection:** On Vertex AI (and Bedrock/Foundry), the default `sonnet` model alias may resolve to an older model than on the direct Anthropic API. If you want a specific model version, set the `CLAUDE_MODEL` environment variable in your deployment manifest or patch it directly:

```bash
oc set env deployment/claude-code-vertex CLAUDE_MODEL=claude-sonnet-4-6
```

### 7. Interactive mode (optional)

For a full interactive Claude Code experience with multi-turn conversations:

```bash
# Local interactive mode
podman run -it --rm \
  -e CLAUDE_CODE_USE_VERTEX=1 \
  -e ANTHROPIC_VERTEX_PROJECT_ID="your-gcp-project-id" \
  -e CLOUD_ML_REGION="global" \
  -e GOOGLE_APPLICATION_CREDENTIALS="/var/secrets/google/key.json" \
  -v /path/to/your-service-account-key.json:/var/secrets/google/key.json:ro,z \
  -v $(pwd):/workspace:z \
  claude-code:latest \
  claude

# OpenShift interactive mode (uses claude-run for proper config)
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  ~/.claude/claude-run
'

# Alternative: source env.sh directly
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  source ~/.claude/env.sh
  claude $CLAUDE_EXTRA_ARGS
'
```

**Note**: Interactive mode requires a TTY, so use `-it` flags with podman and `oc exec`.

### 8. Debug mode (optional)

To see detailed logging of Claude Code activity, use the `--debug` flag:

```bash
# Enable full debug logging
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  claude --debug
'

# Enable debug logging for API calls only
oc exec -it deployment/claude-code-vertex -- bash -c '
  export HOME=/home/claude-agent
  cd /workspace
  claude --debug api
'
```

Debug logs are written to a file. To monitor the logs in real-time, open a second terminal and run:

```bash
oc exec deployment/claude-code-vertex -- bash -c 'tail -f /home/claude-agent/.claude/debug/*.txt'
```

---

## Security Considerations

### SKIP_PERMISSIONS

The deployment manifests set `SKIP_PERMISSIONS=true` by default, which passes `--dangerously-skip-permissions` to Claude Code. This disables all file-system write permission prompts.

**Why it's enabled by default:**

- The container runs as non-root with dropped capabilities and seccomp profiles
- Claude only has access to the isolated `/workspace` PVC, not host filesystems
- Permission prompts don't work well in non-interactive `oc exec` scenarios

**When to disable:**

- If you mount sensitive host directories into the container
- If you're running in a less isolated environment
- If you want Claude to prompt before file operations

To disable, set `SKIP_PERMISSIONS=false` in the deployment manifest or remove the environment variable entirely.

---

## Cleanup

### Option A: Anthropic API resources

```bash
oc delete deployment claude-code
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete secret claude-credentials
oc delete configmap claude-mcp-config
oc delete configmap claude-skills
oc delete pvc claude-workspace
oc delete project my-claude-project
```

### Option B: Vertex AI resources

```bash
oc delete deployment claude-code-vertex
oc delete buildconfig claude-code
oc delete imagestream claude-code
oc delete secret claude-vertex-credentials
oc delete configmap claude-vertex-config
oc delete configmap claude-vertex-mcp-config
oc delete configmap claude-vertex-skills
oc delete pvc claude-vertex-workspace
oc delete project my-claude-project
```
