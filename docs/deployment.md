# Deployment

## Production Setup

### Systemd Service (Linux)

Create `/etc/systemd/system/laura.service`:

```ini
[Unit]
Description=Laura Autonomous Shopee Agent
After=network.target ollama.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/laura
EnvironmentFile=/opt/laura/.env
ExecStart=/opt/laura/.venv/bin/laura daemon
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable laura
sudo systemctl start laura
sudo systemctl status laura
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name laura.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

Add SSL with Certbot:

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d laura.yourdomain.com
```

### Docker Compose

```yaml
version: "3.8"

services:
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    restart: unless-stopped

  laura:
    build: .
    depends_on:
      - ollama
    env_file: .env
    environment:
      - OLLAMA_HOST=http://ollama:11434
    ports:
      - "8888:8888"
    volumes:
      - laura_data:/app/data
      - laura_reports:/app/reports
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    restart: unless-stopped

volumes:
  ollama_data:
  laura_data:
  laura_reports:
```

Run:

```bash
docker compose up -d
docker compose logs -f laura
```

## Monitoring

### Health Check

```bash
laura health
```

Or via API:

```bash
curl -H "X-API-Key: your-key" http://localhost:8888/api/health
```

### Prometheus Metrics

```bash
laura metrics-export
```

Configure Prometheus scrape target (`prometheus.yml`):

```yaml
scrape_configs:
  - job_name: "laura"
    static_configs:
      - targets: ["localhost:8888"]
```

### Logging

Laura writes structured JSON logs to `logs/laura.jsonl`. View recent logs:

```bash
laura dashboard  # Logs tab in dashboard
# Or tail the file
tail -f logs/laura.jsonl | jq .
```

### Alerts

Configure Telegram alerts in `.env`:

```ini
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234
TELEGRAM_CHAT_ID=987654321
```

Alert types:
- Critical errors (LLM failures, API outages)
- Low stock warnings
- Margin violations
- Unusual order patterns
- Daily performance summaries

## Backup

### Automated Backup

```bash
laura backup create
```

Backs up:
- `.env` configuration
- SQLite databases (`data/*.db`)
- Vector indexes (`data/annoy/`, `data/faiss/`)
- Reports (`reports/`)
- Logs (`logs/`)

### Schedule with Cron

```bash
# Daily backup at 2 AM
0 2 * * * cd /opt/laura && .venv/bin/laura backup create

# Weekly full backup
0 3 * * 0 cd /opt/laura && .venv/bin/laura backup create --full
```

### Restore

```bash
laura backup list
laura backup restore <backup_id>
```

## Security

### File Permissions

```bash
chmod 600 .env                    # Secure credentials
chmod 700 data/                   # Secure data directory
chmod 700 secrets/                # Secure secrets directory
```

### Network Security

- Bind dashboard to `127.0.0.1` in production unless using nginx
- Use strong `DASHBOARD_API_KEY` (auto-generated keys are 32-char hex)
- Enable HTTPS via nginx reverse proxy
- Restrict API access by IP if possible

### Secret Rotation

```bash
laura secrets-rotate
laura token-refresh
```

## Performance Tuning

### Redis

For production deployments, Redis significantly improves performance:

```ini
REDIS_URL=redis://localhost:6379/0
```

### Vector Store

Laura supports multiple vector backends:

```ini
# Annoy (default, good for most use cases)
VECTOR_BACKEND=annoy

# FAISS (faster for large datasets)
VECTOR_BACKEND=faiss

# In-memory (fastest, no persistence)
VECTOR_BACKEND=memory
```

### Worker Configuration

```bash
laura workers config --max-workers 4
laura workers config --queue-size 1000
```

## Upgrading

```bash
# Pull latest code
git pull origin main

# Update dependencies
pip install -e . --upgrade

# Run migrations
laura db migrate

# Restart daemon
laura daemon --stop
laura daemon
```
