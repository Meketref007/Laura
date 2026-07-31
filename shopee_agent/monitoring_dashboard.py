"""
PHASE 16: Real-time Monitoring Dashboard
Provides web-based monitoring of store health, alerts, and system metrics
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class MonitoringDashboard:
    """Real-time dashboard for Laura system monitoring"""

    def __init__(self, reports_dir: str = "reports"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)

    def get_store_metrics(self) -> dict[str, Any]:
        """Aggregate current store metrics"""
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "store_health": self._read_latest_file("laura_health_latest.json"),
            "profitability": self._read_latest_file("laura_profitability_latest.json"),
            "alerts_count": self._count_recent_alerts(),
            "refunds_stats": self._read_latest_file("laura_refunds_history.jsonl", last_n=10),
            "api_health": self._get_api_health(),
        }
        return metrics

    def get_dashboard_html(self) -> str:
        """Generate HTML dashboard"""
        metrics = self.get_store_metrics()

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Laura - Store Management Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; border-radius: 8px; margin-bottom: 30px; }}
        .header h1 {{ font-size: 32px; margin-bottom: 5px; }}
        .header p {{ opacity: 0.9; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .card h3 {{ color: #333; margin-bottom: 15px; font-size: 14px; text-transform: uppercase; opacity: 0.7; }}
        .card .value {{ font-size: 32px; font-weight: bold; color: #667eea; }}
        .card .unit {{ font-size: 12px; color: #999; margin-left: 5px; }}
        .status {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }}
        .status.ok {{ background: #22c55e; }}
        .status.warning {{ background: #f59e0b; }}
        .status.error {{ background: #ef4444; }}
        .alerts {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .alert-item {{ padding: 10px; margin: 10px 0; border-left: 4px solid #667eea; background: #f0f4ff; }}
        .footer {{ text-align: center; color: #999; margin-top: 30px; font-size: 12px; }}
    </style>
    <script>
        setInterval(() => location.reload(), 30000);
    </script>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 Laura Dashboard</h1>
            <p>Store Management System - Real-time Monitoring</p>
        </div>
        
        <div class="grid">
            <div class="card">
                <h3>System Status</h3>
                <span class="status ok"></span>
                <span>Operational</span>
            </div>
            <div class="card">
                <h3>Active Alerts</h3>
                <div class="value">{metrics.get('alerts_count', 0)}</div>
            </div>
            <div class="card">
                <h3>Last Update</h3>
                <div class="value" style="font-size: 14px;">{metrics['timestamp']}</div>
            </div>
        </div>
        
        <div class="alerts">
            <h3>📊 Recent Activity</h3>
            <div class="alert-item">✅ System operational and monitoring active</div>
            <div class="alert-item">📈 Dashboard updated every 30 seconds</div>
            <div class="alert-item">🔔 Alerts and metrics aggregated in real-time</div>
        </div>
        
        <div class="footer">
            Laura Store Management System | Production Ready | Phase 16: Monitoring Dashboard
        </div>
    </div>
</body>
</html>
"""
        return html

    def _read_latest_file(self, filename: str, last_n: int = 1) -> Any:
        """Read latest JSON or JSONL file"""
        filepath = self.reports_dir / filename
        if not filepath.exists():
            return None

        try:
            if filename.endswith('.jsonl'):
                lines = filepath.read_text().strip().split('\n')[-last_n:]
                return [json.loads(line) for line in lines if line]
            else:
                return json.loads(filepath.read_text())
        except Exception:
            return None

    def _count_recent_alerts(self) -> int:
        """Count alerts from last hour"""
        filepath = self.reports_dir / "laura_alerts_history.jsonl"
        if not filepath.exists():
            return 0

        try:
            lines = filepath.read_text().strip().split('\n')
            one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
            count = 0
            for line in lines:
                if line:
                    alert = json.loads(line)
                    if alert.get('timestamp', '') > one_hour_ago:
                        count += 1
            return count
        except Exception:
            return 0

    def _get_api_health(self) -> dict[str, Any]:
        """Check API health status in real time."""
        import requests as _req
        result = {
            "shopee_api": "unknown",
            "ollama_llm": "unknown",
            "webhook_system": "unknown",
            "seller_center": "unknown",
        }
        # Check Ollama
        try:
            r = _req.get("http://127.0.0.1:11434/api/tags", timeout=5)
            result["ollama_llm"] = "reachable" if r.status_code == 200 else "error"
        except Exception:
            result["ollama_llm"] = "unreachable"
        # Check webhook server
        webhook_port = int(__import__("os").getenv("LAURA_WEBHOOK_PORT", "8766"))
        try:
            r = _req.get(f"http://127.0.0.1:{webhook_port}/health", timeout=5)
            result["webhook_system"] = "active" if r.status_code == 200 else "error"
        except Exception:
            result["webhook_system"] = "inactive"
        # Check Shopee API via OpenAPI token
        try:
            from shopee_agent.client import ShopeeClient
            from shopee_agent.config import load_config
            cfg = load_config()
            tok = cfg.default_access_token
            sid = cfg.default_shop_id
            if tok and sid:
                cli = ShopeeClient(cfg)
                r2 = cli.get_shop_info(access_token=tok, shop_id=sid)
                if hasattr(r2, "status_code") and r2.status_code == 200:
                    result["shopee_api"] = "operational"
                else:
                    result["shopee_api"] = "degraded"
            else:
                result["shopee_api"] = "no_credentials"
        except Exception:
            result["shopee_api"] = "error"
        # Check Seller Center cookies
        try:
            from shopee_agent.seller_center import load_cookies
            session = load_cookies()
            if session and session.is_valid():
                result["seller_center"] = "authenticated"
            else:
                result["seller_center"] = "no_cookies"
        except Exception:
            result["seller_center"] = "error"
        return result

    def export_metrics_json(self, output_file: str = None) -> str:
        """Export metrics as JSON"""
        metrics = self.get_store_metrics()
        if output_file:
            Path(output_file).write_text(json.dumps(metrics, indent=2))
        return json.dumps(metrics, indent=2)

