# API Reference

Laura exposes a REST API for integration with external tools and dashboards.

## Base URL

```
http://localhost:8888/api
```

## Authentication

All API requests require the `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key" http://localhost:8888/api/health
```

## Endpoints

### Health

```http
GET /api/health
```

Response:
```json
{
  "status": "ok",
  "timestamp": "2024-01-15T10:30:00Z",
  "version": "3.0.0",
  "uptime_seconds": 3600
}
```

### System Status

```http
GET /api/status
```

Response:
```json
{
  "daemon": "running",
  "ollama": "connected",
  "shopee": "authenticated",
  "skills": 24,
  "queue_depth": 3,
  "memory_usage_mb": 245,
  "last_order_check": "2024-01-15T10:29:00Z"
}
```

### Orders

```http
GET /api/orders?status=READY_TO_SHIP&limit=10&offset=0
```

Parameters:
| Parameter | Type   | Default | Description              |
|-----------|--------|---------|--------------------------|
| `status`  | string | `all`   | Filter by order status   |
| `limit`   | int    | `20`    | Max results              |
| `offset`  | int    | `0`     | Pagination offset        |

Response:
```json
{
  "orders": [
    {
      "order_sn": "240115ABC123",
      "status": "READY_TO_SHIP",
      "total_amount": 149.90,
      "currency": "BRL",
      "created_at": "2024-01-15T08:00:00Z",
      "buyer": "John Doe",
      "items": [
        {"item_id": 123456, "name": "Product A", "quantity": 2}
      ]
    }
  ],
  "total": 42,
  "limit": 10,
  "offset": 0
}
```

### Products

```http
GET /api/products?page=1&page_size=50
```

Response:
```json
{
  "products": [
    {
      "item_id": 123456,
      "name": "Product A",
      "price": 49.90,
      "stock": 100,
      "sold_30d": 25,
      "rating": 4.5,
      "cost": 25.00,
      "margin": 49.9,
      "status": "NORMAL"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 50
}
```

### Skills

```http
GET /api/skills
```

Response:
```json
{
  "skills": [
    {
      "name": "pricing_skill",
      "cost": 3.5,
      "priority": 80,
      "status": "idle",
      "last_run": "2024-01-15T09:00:00Z",
      "last_success": true
    }
  ]
}
```

### Trigger Skill

```http
POST /api/skill-run
Content-Type: application/json

{
  "skill": "pricing_skill",
  "params": {
    "min_margin": 30,
    "max_adjustment_pct": 10
  }
}
```

Response:
```json
{
  "status": "accepted",
  "execution_id": "exec_a1b2c3d4",
  "estimated_duration_seconds": 15
}
```

### Configuration

```http
GET /api/config
```

Response:
```json
{
  "LAURA_LLM_MODEL": "tinyllama",
  "DASHBOARD_PORT": "8888",
  "SHOPEE_COUNTRY": "br",
  "LAURA_ALLOW_PAID_LLM": "0"
}
```

```http
PUT /api/config
Content-Type: application/json

{
  "LAURA_LLM_MODEL": "llama3.2",
  "LAURA_ALLOW_PAID_LLM": "1"
}
```

Note: Keys shown here are masked in responses. Sensitive values (tokens, keys) return `"****"`.

### Metrics

```http
GET /api/metrics
```

Response:
```json
{
  "orders_today": 12,
  "revenue_today": 1845.50,
  "orders_7d": 89,
  "revenue_7d": 12450.00,
  "avg_order_value": 139.89,
  "top_product": {"id": 123456, "name": "Product A", "sold": 45},
  "low_stock_items": 3,
  "margin_violations": 1,
  "skills_executed_today": 28,
  "llm_requests_today": 156,
  "llm_avg_latency_ms": 450
}
```

### Logs

```http
GET /api/logs?level=error&limit=50
```

Parameters:
| Parameter | Type   | Default   | Description              |
|-----------|--------|-----------|--------------------------|
| `level`   | string | `all`     | Filter: debug, info, warning, error |
| `limit`   | int    | `50`      | Max entries              |
| `since`   | string | (unset)   | ISO 8601 timestamp       |

Response:
```json
{
  "logs": [
    {
      "timestamp": "2024-01-15T10:28:00Z",
      "level": "error",
      "module": "shopee_agent.client",
      "message": "API request failed",
      "details": {"endpoint": "order/list", "status_code": 500}
    }
  ]
}
```

### Webhook

Laura can receive Shopee webhook notifications:

```http
POST /webhook/shopee
Content-Type: application/json

{
  "request_id": "req_abc123",
  "data": {
    "shop_id": 123456789,
    "orders": ["240115ABC123"]
  }
}
```

Configure the webhook URL in your Shopee Partner settings as:
```
https://your-domain.com/webhook/shopee
```

## Error Responses

```json
{
  "error": "unauthorized",
  "message": "Invalid or missing API key",
  "status_code": 401
}
```

Common status codes:
| Code | Description            |
|------|------------------------|
| 200  | Success                |
| 400  | Bad request            |
| 401  | Unauthorized           |
| 404  | Not found              |
| 429  | Rate limited           |
| 500  | Internal server error  |

## Rate Limiting

API rate limits:
- 100 requests per minute per API key
- 1000 requests per hour per API key

Rate limit headers are included in responses:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705310400
```
