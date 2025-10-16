# Kubernetes AI Assistant

An AI-powered Kubernetes SRE assistant that helps diagnose and troubleshoot cluster issues using local tools and LLM integration.

## Features

- 🤖 AI-powered cluster analysis
- 🔍 Read-only Kubernetes operations
- 📊 Pod metrics and logs inspection
- 🎯 Smart recommendations with kubectl commands
- 🔐 Automatic log sanitization (IPs, emails, tokens)

## Prerequisites

- Python 3.8+
- kubectl configured with cluster access
- (Optional) OpenAI API key for GPT-4o-mini
- (Optional) metrics-server for pod metrics

## Quick Start

### 1. Clone and Setup

```bash
# Ensure your kubectl is configured
kubectl cluster-info

# Run the setup script
chmod +x run.sh
./run.sh
```

### 2. Choose Your LLM Adapter

#### Option A: Local Mode (No API Key Required)
```bash
# Default - uses simple local adapter for testing
python cli/chat.py
```

#### Option B: OpenAI Mode
```bash
# Set your API key
export OPENAI_API_KEY="sk-..."
export LLM_ADAPTER="openai"

python cli/chat.py
```

### 3. Start Chatting

```
🤖 Kubernetes AI Assistant
Type 'exit' to quit

You: Show me all pods in default namespace
```

## Project Structure

```
.
├── mcp/
│   ├── __init__.py       # MCP module exports
│   ├── server.py         # Tool registry and local MCP server
│   └── tools.py          # Kubernetes tool implementations
├── ai/
│   ├── __init__.py
│   ├── adapters.py       # LLM adapters (OpenAI, Local)
│   └── agent.py          # AI agent orchestration
├── cli/
│   └── chat.py           # Terminal chat interface
├── requirements.txt      # Python dependencies
├── run.sh               # Setup and run script
└── README.md            # This file
```

## Available Tools

The assistant has access to these read-only Kubernetes tools:

- `get_pods` - List pods with status
- `get_pod_logs` - Fetch pod logs (sanitized)
- `get_pod_metrics` - CPU/memory usage (requires metrics-server)
- `get_cluster_events` - Recent cluster events
- `get_deployments` - List deployments
- `get_services` - List services

## Example Queries

```
- "Are there any crashing pods?"
- "Show me logs for pod nginx-abc123"
- "What's using the most memory?"
- "Check the cluster events"
- "Why is my deployment not ready?"
```

## Configuration

### Environment Variables

- `LLM_ADAPTER` - Set to "openai" or "local" (default: "local")
- `OPENAI_API_KEY` - Your OpenAI API key (required for openai adapter)

### Kubernetes Access

The tool uses your kubectl configuration:
- `~/.kube/config` (default)
- Or in-cluster config if running inside Kubernetes

## Security Features

- ✅ Read-only operations only
- ✅ Automatic log sanitization
- ✅ No cluster mutations allowed
- ✅ Token/IP/email redaction in logs

## Troubleshooting

### "Could not load Kubernetes config"
```bash
# Check your kubectl access
kubectl cluster-info
kubectl get nodes
```

### "metrics API not available"
```bash
# Install metrics-server (optional)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### "OPENAI_API_KEY not set"
```bash
# Set your API key
export OPENAI_API_KEY="sk-your-key-here"
export LLM_ADAPTER="openai"
```

## Development

### Running Tests
```bash
source .venv/bin/activate
python -m pytest tests/
```

### Adding New Tools

1. Add function to `mcp/tools.py`:
```python
@tool()
async def my_new_tool(arg1: str):
    """Tool description"""
    # Implementation
    return {"result": "data"}
```

2. Tool is automatically registered and available to the AI

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Please open an issue or PR.