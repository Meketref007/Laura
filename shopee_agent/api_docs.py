"""OpenAPI/Swagger documentation for the Laura Dashboard API."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse


def _discover_routes(app: FastAPI) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for route in app.routes:
        if hasattr(route, "methods") and route.path.startswith("/api/"):
            methods = sorted(route.methods - {"HEAD", "OPTIONS"}) if route.methods else ["GET"]
            doc = (getattr(route, "description", None) or getattr(route, "summary", "") or "").strip()
            path = route.path
            is_old = not path.startswith(("/api/v1/", "/api/v2/")) and not path == "/api/version"
            routes.append({
                "path": path,
                "methods": methods,
                "summary": doc or route.endpoint.__doc__ or "",
                "operation_id": route.name or route.endpoint.__name__,
                "deprecated": is_old,
            })
    return routes


def _build_spec(app: FastAPI) -> dict[str, Any]:
    title = getattr(app, "title", "Laura Dashboard API")
    version = getattr(app, "version", "1.0.0")
    description = getattr(app, "description", "Laura Dashboard REST API")

    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": version,
            "description": description + "\n\n## API Versioning\n\nThis API supports versioning:\n- **v1** (stable) — available at `/api/v1/*`\n- **v2** (latest) — available at `/api/v2/*`\n\nLegacy endpoints at `/api/*` are deprecated and will redirect to `/api/v1/*`. New clients should use versioned paths.\n\nDeprecation headers:\n- `X-API-Version`: which version served the request\n- `X-API-Deprecated`: `true` if the version is deprecated (v1 after v2 is available)",
        },
        "servers": [
            {"url": "/", "description": "Laura Dashboard API"},
        ],
        "paths": {},
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "API Key",
                    "description": "Use DASHBOARD_API_KEY as Bearer token",
                },
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                },
                "Status": {
                    "type": "object",
                    "properties": {
                        "running": {"type": "boolean"},
                        "health": {"type": "object"},
                        "pending_ratings": {"type": "integer"},
                        "pending_chats": {"type": "integer"},
                        "updated": {"type": "string", "format": "date-time"},
                    },
                },
                "HealthResponse": {
                    "type": "object",
                    "properties": {
                        "health_score": {"type": "number"},
                        "status": {"type": "string"},
                    },
                },
                "ProfitabilityResponse": {
                    "type": "object",
                    "properties": {
                        "metrics": {"type": "object"},
                        "action_key": {"type": "string"},
                    },
                },
                "SkillsResponse": {
                    "type": "object",
                    "properties": {
                        "registered_skills": {"type": "array", "items": {"type": "string"}},
                        "total_executions": {"type": "integer"},
                        "success_rate_pct": {"type": "number"},
                    },
                },
                "SkillHealthResponse": {
                    "type": "object",
                    "properties": {
                        "skills": {"type": "object"},
                        "total_skills": {"type": "integer"},
                    },
                },
                "GoapGraphResponse": {
                    "type": "object",
                    "properties": {
                        "nodes": {"type": "array", "items": {"type": "object"}},
                        "edges": {"type": "array", "items": {"type": "object"}},
                    },
                },
                "GoapTimelineResponse": {
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "items": {"type": "object"}},
                    },
                },
                "GoapCostHistoryResponse": {
                    "type": "object",
                    "properties": {
                        "cost_history": {"type": "array", "items": {"type": "object"}},
                    },
                },
                "GoalSynthesizeResponse": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "object"},
                        "description": {"type": "string"},
                    },
                },
                "WsTokenResponse": {
                    "type": "object",
                    "properties": {
                        "token": {"type": "string"},
                    },
                },
                "ABTestStatsResponse": {
                    "type": "object",
                    "properties": {
                        "total_tests": {"type": "integer"},
                        "active": {"type": "integer"},
                        "promoted": {"type": "integer"},
                        "avg_confidence": {"type": "number"},
                    },
                },
                "ABTestDetailResponse": {
                    "type": "object",
                    "properties": {
                        "test_id": {"type": "string"},
                        "is_promoted": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "control_rate": {"type": "number"},
                        "variant_rate": {"type": "number"},
                    },
                },
                "DashboardMetricsResponse": {
                    "type": "object",
                    "properties": {
                        "skills": {"type": "object"},
                        "plans": {"type": "object"},
                        "health": {"type": "object"},
                        "events_last_minute": {"type": "integer"},
                        "uptime_seconds": {"type": "integer"},
                    },
                },
                "RecentEventsResponse": {
                    "type": "object",
                    "properties": {
                        "events": {"type": "array", "items": {"type": "object"}},
                    },
                },
                "PromoteResponse": {
                    "type": "object",
                    "properties": {
                        "test_id": {"type": "string"},
                        "promoted": {"type": "boolean"},
                        "winner": {"type": "string"},
                        "reason": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                },
                "PushSubscribeRequest": {
                    "type": "object",
                    "properties": {
                        "endpoint": {"type": "string"},
                        "keys": {"type": "object"},
                    },
                },
                "PushSendRequest": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "message": {"type": "string"},
                    },
                },
                "PushSendResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "sent": {"type": "integer"},
                    },
                },
                "ApproveRejectResponse": {
                    "type": "object",
                    "properties": {
                        "ok": {"type": "boolean"},
                        "error": {"type": "string"},
                        "result": {"type": "object"},
                    },
                },
            },
        },
        "security": [{"BearerAuth": []}],
    }

    routes = _discover_routes(app)
    for r in routes:
        path = r["path"]
        if path not in spec["paths"]:
            spec["paths"][path] = {}
        for method in r["methods"]:
            method_lower = method.lower()
            responses: dict[str, Any] = {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                        },
                    },
                },
                "401": {
                    "description": "Unauthorized",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"},
                        },
                    },
                },
            }

            security = [{"BearerAuth": []}]
            push_paths = {"/api/push/subscribe", "/api/push/send", "/api/v1/push/subscribe", "/api/v1/push/send"}
            if path in push_paths:
                security = []

            entry: dict[str, Any] = {
                "operationId": r["operation_id"],
                "summary": r["summary"].split("\n")[0] if r["summary"] else "",
                "description": r["summary"] or "",
                "security": security,
                "responses": responses,
            }
            if r.get("deprecated"):
                entry["deprecated"] = True
            if path.startswith("/api/v2/"):
                if "summary" not in entry or not entry["summary"]:
                    entry["summary"] = f"[v2] {r['operation_id']}"

            spec["paths"][path][method_lower] = entry

    return spec


_SWAGGER_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Laura API — Swagger UI</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
  <style>html{box-sizing:border-box}*,*:before,*:after{box-sizing:inherit}body{margin:0;background:#0f172a}</style>
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script>
    SwaggerUIBundle({
      url: '/openapi.json',
      dom_id: '#swagger-ui',
      presets: [SwaggerUIBundle.presets.apis],
      layout: 'BaseLayout',
    });
  </script>
</body>
</html>"""

_REDOC_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Laura API — ReDoc</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>body{margin:0;padding:0}</style>
</head>
<body>
  <div id="redoc-container"></div>
  <script src="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js"></script>
  <script>
    Redoc.init('/openapi.json', {scrollYOffset: 0}, document.getElementById('redoc-container'));
  </script>
</body>
</html>"""


def register_swagger(app: FastAPI) -> None:
    spec: dict[str, Any] | None = None

    @app.get("/openapi.json", include_in_schema=False)
    async def openapi_json():
        nonlocal spec
        if spec is None:
            spec = _build_spec(app)
        return JSONResponse(content=spec)

    @app.get("/docs", include_in_schema=False)
    async def swagger_ui():
        return HTMLResponse(_SWAGGER_UI_HTML)

    @app.get("/redoc", include_in_schema=False)
    async def redoc_ui():
        return HTMLResponse(_REDOC_HTML)


def build_openapi_spec(app: FastAPI | None = None) -> dict[str, Any]:
    if app is None:
        from shopee_agent.dashboard import app as dashboard_app
        app = dashboard_app
    return _build_spec(app)
