# Installation

## Requirements

| Requirement  | Minimum Version | Notes                              |
|-------------|-----------------|-------------------------------------|
| Python      | 3.10+           | 3.12+ recommended                   |
| Ollama      | 0.1.0+          | Optional if using remote LLM        |
| Disk Space  | 1 GB            | For models + vector indexes         |
| OS          | Linux / macOS / Windows | Windows requires PowerShell 5.1+ |

## Quick Install

```bash
# Clone the repository
git clone https://github.com/anomalyco/laura.git
cd laura

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows

# Install Laura
pip install -e .
```

## Docker

```bash
docker build -t laura .
docker run -d \
  --name laura \
  -p 8888:8888 \
  -v $(pwd)/.env:/app/.env \
  -v laura_data:/app/data \
  laura
```

See [deployment.md](deployment.md) for Docker Compose setups.

## Ollama Setup (Recommended)

```bash
# Install Ollama: https://ollama.ai
ollama pull tinyllama
ollama pull nomic-embed-text   # for vector embeddings
```

Verify Ollama is running:

```bash
laura ollama-status
```

## Post-Install Verification

```bash
laura setup --check
```

This checks Python version, Ollama availability, disk space, and internet connectivity.

## Troubleshooting

### `ModuleNotFoundError: No module named 'shopee_agent'`
Ensure you ran `pip install -e .` from the project root.

### Ollama not found
- Install Ollama from [ollama.ai](https://ollama.ai)
- Ensure `ollama serve` is running before starting Laura
- Windows: Ollama runs as a system service; check `ollama list`

### Permission denied on `.env`
Run `chmod 600 .env` on Linux/macOS to secure credentials.

### Port 8888 already in use
Change the dashboard port:
```bash
laura dashboard --port 8889
```
Or set `DASHBOARD_PORT=8889` in `.env`.

### SQLite locking errors
Laura uses WAL mode for concurrent access. If you see locking errors, ensure only one Laura process is running:
```bash
laura daemon --stop
laura daemon
```
