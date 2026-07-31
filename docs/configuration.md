# Configuration

Laura is configured via a `.env` file in the project root. Use `laura setup` to generate one interactively, or copy `.env.example` and edit manually.

## Environment Variables

### Shopee API (Required)

| Variable                     | Description                                  | Example                        |
|------------------------------|----------------------------------------------|--------------------------------|
| `SHOPEE_PARTNER_ID`          | Your Shopee Partner ID (numeric)             | `123456`                       |
| `SHOPEE_PARTNER_KEY_SHA256`  | SHA-256 hash of your Partner Key             | `a1b2c3d4e5f6...`              |
| `SHOPEE_DEFAULT_ACCESS_TOKEN`| OAuth access token from Shopee               | `eyJhbGciOiJ...`               |
| `SHOPEE_DEFAULT_SHOP_ID`     | Your Shop ID (numeric)                       | `123456789`                    |
| `SHOPEE_COUNTRY`             | Country code                                 | `br`, `id`, `th`, `sg`, `my`  |

### LLM Provider

| Variable              | Description                              | Default     |
|----------------------|------------------------------------------|-------------|
| `LAURA_LLM_MODEL`    | Ollama model name                        | `tinyllama` |
| `LAURA_ALLOW_PAID_LLM`| Set to `1` to enable remote LLMs         | (unset)     |
| `OPENAI_API_KEY`     | OpenAI API key (if using GPT)            |             |
| `ANTHROPIC_API_KEY`  | Anthropic API key (if using Claude)      |             |

### Telegram (Optional)

| Variable              | Description                              |
|----------------------|------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather                |
| `TELEGRAM_CHAT_ID`   | Chat ID for push notifications           |

### Dashboard

| Variable           | Description                        | Default       |
|-------------------|------------------------------------|---------------|
| `DASHBOARD_HOST`  | Dashboard bind address             | `0.0.0.0`     |
| `DASHBOARD_PORT`  | Dashboard HTTP port                | `8888`        |
| `DASHBOARD_API_KEY`| API key for dashboard auth        | (auto-generated) |

### Webhook

| Variable              | Description                              | Default |
|----------------------|------------------------------------------|---------|
| `WEBHOOK_SECRET`     | Secret for verifying Shopee webhooks     |         |
| `CHAT_AUTO_RESPOND`  | Auto-respond to customer messages (`0`/`1`)| `0`   |

### Redis (Optional — for production)

| Variable    | Description                    | Default                       |
|------------|--------------------------------|-------------------------------|
| `REDIS_URL` | Redis connection string        | `redis://localhost:6379/0`    |

### SMTP / Email (Optional)

| Variable     | Description                    |
|-------------|--------------------------------|
| `SMTP_HOST` | SMTP server host               |
| `SMTP_PORT` | SMTP server port               |
| `SMTP_USER` | SMTP username                  |
| `SMTP_PASS` | SMTP password                  |
| `SMTP_FROM` | Sender email address           |
| `ALERT_EMAIL`| Alert recipient email          |

### Paths (Optional)

| Variable           | Description             | Default    |
|-------------------|-------------------------|------------|
| `LAURA_REPORTS_DIR`| Reports directory       | `reports/` |
| `LAURA_LOGS_DIR`  | Logs directory           | `logs/`    |
| `LAURA_DATA_DIR`  | Data directory           | `data/`    |

### Locale

| Variable       | Description          | Default  |
|---------------|----------------------|----------|
| `LAURA_LOCALE` | Language locale      | `pt_BR`  |

Supported locales: `pt_BR`, `en_US`.

## Example `.env`

```ini
# Shopee
SHOPEE_PARTNER_ID=123456
SHOPEE_PARTNER_KEY_SHA256=a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890
SHOPEE_DEFAULT_ACCESS_TOKEN=eyJhbGciOiJSUzI1NiIs...
SHOPEE_DEFAULT_SHOP_ID=123456789
SHOPEE_COUNTRY=br

# LLM
LAURA_LLM_MODEL=tinyllama

# Dashboard
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8888

# Telegram (optional)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=987654321

# Locale
LAURA_LOCALE=pt_BR
```

## Secret Management

- `.env` file permissions should be `600` (owner read/write only)
- Never commit `.env` to version control
- Use `laura setup --quick` for CI/CD environments
- Partner Keys are stored as SHA-256 hashes for security
- Access tokens can be rotated with `laura token-refresh`
