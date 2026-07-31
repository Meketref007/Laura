# Dashboard

Laura includes a real-time web dashboard for monitoring shop performance, managing configurations, and visualizing metrics.

## Quick Start

```bash
laura dashboard
```

Opens at `http://localhost:8888` by default.

## Screens

### Overview
- Real-time order count, revenue, and customer messages
- Shop health score and violation alerts
- Active skill execution status
- LLM health and queue depth

### Orders
- Recent orders with status, value, and customer info
- Filters by status, date range, and amount
- Quick actions: ship, cancel, view details

### Products
- Product catalog with pricing, stock, and margins
- Low-stock warnings and margin alerts
- Bulk price/stock update interface

### Analytics
- Revenue charts (daily, weekly, monthly)
- Top-selling products
- Category distribution
- Profit margin trends

### Skills
- Registered skills list with status
- Skill execution history
- GOAP plan visualization
- Manual skill trigger

### Settings
- Environment variable editor
- LLM configuration
- Telegram test message
- Webhook status

## API Endpoints

The dashboard serves a REST API:

| Method | Endpoint                    | Description                 |
|--------|-----------------------------|-----------------------------|
| GET    | `/api/health`               | Health check                |
| GET    | `/api/status`               | Full system status          |
| GET    | `/api/orders`               | Recent orders               |
| GET    | `/api/products`             | Product list                |
| GET    | `/api/skills`               | Skill status                |
| GET    | `/api/metrics`              | Performance metrics         |
| GET    | `/api/config`               | Get configuration           |
| PUT    | `/api/config`               | Update configuration        |
| POST   | `/api/skill-run`            | Trigger a skill             |
| GET    | `/api/logs`                 | Recent log entries          |

All API endpoints require the `X-API-Key` header matching `DASHBOARD_API_KEY`.

## WebSocket

The dashboard exposes a WebSocket endpoint at `/ws` for real-time updates:

```javascript
const ws = new WebSocket("ws://localhost:8888/ws?token=YOUR_API_KEY");
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Update:", data);
};
```

Events:
- `order:new` — new order received
- `order:status` — order status changed
- `alert:critical` — critical alert
- `skill:start` — skill execution started
- `skill:complete` — skill execution completed
- `metric:update` — metric value changed

## Authentication

The dashboard uses API key authentication:

1. Set `DASHBOARD_API_KEY` in `.env` (or auto-generated on first run)
2. Include it in requests:
   ```
   X-API-Key: your-api-key
   ```
3. For browser access, enter the key in the login page

## Configuration

| Environment Variable | Default       | Description                     |
|---------------------|---------------|---------------------------------|
| `DASHBOARD_HOST`    | `0.0.0.0`     | Bind address                    |
| `DASHBOARD_PORT`    | `8888`        | HTTP port                       |
| `DASHBOARD_API_KEY` | (auto-gen)    | API key for authentication      |

## Custom Frontend

The dashboard serves a built React frontend from `frontend/build/`. To rebuild:

```bash
laura dashboard --build-frontend
```

Or build manually:

```bash
cd frontend
npm install
npm run build
```
