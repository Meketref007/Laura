from __future__ import annotations

import csv
import json
import os
import smtplib
import sys
import threading
from datetime import UTC, datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from shopee_agent.logger import info, warning

try:
    from openpyxl import Workbook
    from openpyxl.styles import Border, Font, PatternFill, Side
except Exception:
    Workbook = None

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except Exception:
    letter = None
    canvas = None

try:
    import anthropic
except Exception:
    anthropic = None


REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
REPORT_HISTORY_PATH = REPORTS_DIR / "report_history.jsonl"


def _load_inputs(path: str | None) -> dict[str, Any]:
    p = Path(path) if path else REPORTS_DIR / "laura_profitability_inputs_latest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def generate_daily_reports(*, inputs_path: str | None = None, out_xlsx: str | None = None, out_pdf: str | None = None, use_llm: bool = True) -> dict[str, Any]:
    data = _load_inputs(inputs_path)
    out_xlsx_path = Path(out_xlsx) if out_xlsx else REPORTS_DIR / "laura_daily_summary.xlsx"
    out_pdf_path = Path(out_pdf) if out_pdf else REPORTS_DIR / "laura_daily_summary.pdf"
    out_xlsx_path.parent.mkdir(parents=True, exist_ok=True)
    out_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at": data.get("generated_at"),
        "shop_id": data.get("shop_id"),
        "orders_count": data.get("orders_count", 0),
    }

    if Workbook is not None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Summary"
        ws.append(["Key", "Value"])
        for k, v in summary.items():
            ws.append([k, str(v)])
        try:
            wb.save(str(out_xlsx_path))
        except Exception:
            pass

    if canvas is not None and letter is not None:
        try:
            c = canvas.Canvas(str(out_pdf_path), pagesize=letter)
            text = c.beginText(40, 720)
            text.setFont("Helvetica", 10)
            text.textLine("Laura Daily Summary")
            text.textLine("")
            for k, v in summary.items():
                text.textLine(f"{k}: {v}")
            c.drawText(text)
            c.showPage()
            c.save()
        except Exception:
            pass

    llm_summary = None
    if use_llm:
        try:
            from .llm_local import create_analyzer as create_local_analyzer
            model_name = os.getenv("LAURA_LLM_MODEL", "tinyllama")
            analyzer = create_local_analyzer(model=model_name)
            metrics = {
                "revenue": data.get("revenue", 0) or 0,
                "cogs": data.get("cogs", 0) or 0,
                "ad_spend": data.get("ad_spend", 0) or 0,
                "shipping_subsidy": data.get("shipping_subsidy", 0) or 0,
                "refunds": data.get("refunds", 0) or 0,
                "orders": data.get("orders_count", 0) or 0,
            }
            try:
                res = analyzer.analyze(metrics=metrics, prompt_type="profitability_analyzer", max_tokens=128, fallback_on_error=True)
            except Exception:
                res = None

            if isinstance(res, dict):
                llm_summary = (
                    res.get("decision") or res.get("action") or None
                )
                if not llm_summary and res.get("reasoning"):
                    llm_summary = (res.get("reasoning")[:300] + "...")
            else:
                try:
                    llm_summary = getattr(res, "decision", None) or getattr(res, "action", None) or getattr(res, "reasoning", None)
                except Exception:
                    llm_summary = None
        except Exception:
            llm_summary = None

    result = {
        "xlsx": str(out_xlsx_path),
        "pdf": str(out_pdf_path),
        "llm_summary_present": bool(llm_summary),
    }
    if llm_summary:
        result["llm_summary"] = str(llm_summary)

    return result


class ReportingEngine:
    def __init__(self, client=None, data_dir: str = "reports"):
        self.client = client
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._last_report: dict | None = None

    # --- data collection helpers ---

    def _fetch_orders(self, days: int, order_status: str = "") -> tuple[list[dict], int, float]:
        if self.client is None:
            return [], 0, 0.0
        from .config import load_config
        cfg = load_config()
        access_token = cfg.default_access_token
        shop_id = cfg.default_shop_id
        if not access_token or not shop_id:
            return [], 0, 0.0
        now = datetime.now(UTC)
        time_to = int(now.timestamp())
        time_from = int((now - timedelta(days=days)).timestamp())
        all_orders: list[dict] = []
        cursor = ""
        while True:
            resp = self.client.get_order_list(
                access_token=access_token, shop_id=shop_id,
                time_from=time_from, time_to=time_to,
                time_range_field="create_time", page_size=50, cursor=cursor,
                order_status=order_status,
            )
            body = resp.data.get("response") if isinstance(resp.data, dict) else None
            if not body:
                break
            orders = body.get("order_list") or []
            all_orders.extend(orders)
            cursor = body.get("next_cursor", "") or ""
            if not cursor:
                break
        total_amount = sum(
            float(o.get("total_amount", 0) or 0) for o in all_orders
        )
        return all_orders, len(all_orders), total_amount

    def _fetch_items(self) -> list[dict]:
        if self.client is None:
            return []
        from .config import load_config
        cfg = load_config()
        access_token = cfg.default_access_token
        shop_id = cfg.default_shop_id
        if not access_token or not shop_id:
            return []
        all_items: list[dict] = []
        offset = 0
        while True:
            resp = self.client.get_item_list(
                access_token=access_token, shop_id=shop_id,
                offset=offset, page_size=50,
            )
            body = resp.data.get("response") if isinstance(resp.data, dict) else None
            if not body:
                break
            items = body.get("item") or []
            all_items.extend(items)
            if not body.get("has_next_page"):
                break
            offset += 50
        return all_items

    def _fetch_performance(self, days: int) -> dict:
        if self.client is None:
            return {}
        from .config import load_config
        cfg = load_config()
        access_token = cfg.default_access_token
        shop_id = cfg.default_shop_id
        if not access_token or not shop_id:
            return {}
        now = datetime.now(UTC)
        time_to = int(now.timestamp())
        time_from = int((now - timedelta(days=days)).timestamp())
        try:
            resp = self.client.get_shop_performance(
                access_token=access_token, shop_id=shop_id,
                time_from=time_from, time_to=time_to,
            )
            body = resp.data.get("response") if isinstance(resp.data, dict) else {}
            return body if isinstance(body, dict) else {}
        except Exception:
            return {}

    def _count_by_status(self, orders: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for o in orders:
            status = o.get("order_status", "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _compute_trend(self, current: float, previous: float) -> float | None:
        if previous == 0:
            return None
        return round(((current - previous) / previous) * 100, 2)

    # --- report generators ---

    def generate_daily_report(self) -> dict:
        orders, orders_count, revenue = self._fetch_orders(days=1)
        prev_orders, prev_count, prev_revenue = self._fetch_orders(days=2, order_status="COMPLETED")
        prev_count = prev_count or 1
        items = self._fetch_items()
        performance = self._fetch_performance(days=1)
        status_counts = self._count_by_status(orders)
        now = datetime.now(UTC)

        report = {
            "type": "daily",
            "generated_at": now.isoformat(),
            "period": {
                "from": (now - timedelta(days=1)).isoformat(),
                "to": now.isoformat(),
            },
            "orders_count": orders_count,
            "revenue": round(revenue, 2),
            "new_products": len(items) if items else 0,
            "cancellations": status_counts.get("CANCELLED", 0),
            "refunds": status_counts.get("RETURN_REFUND", 0),
            "orders_by_status": status_counts,
            "avg_order_value": round(revenue / orders_count, 2) if orders_count else 0.0,
            "trends": {
                "orders_dod_change": self._compute_trend(orders_count, prev_count),
                "revenue_dod_change": self._compute_trend(revenue, prev_revenue),
            },
            "shop_performance": performance,
            "products_count": len(items),
        }
        self._save_history(report)
        self._last_report = report
        return report

    def generate_weekly_report(self) -> dict:
        orders, orders_count, revenue = self._fetch_orders(days=7)
        prev_orders, prev_count, prev_revenue = self._fetch_orders(days=14, order_status="COMPLETED")
        prev_count = max(prev_count, 1)
        items = self._fetch_items()
        performance = self._fetch_performance(days=7)
        status_counts = self._count_by_status(orders)
        now = datetime.now(UTC)

        report = {
            "type": "weekly",
            "generated_at": now.isoformat(),
            "period": {
                "from": (now - timedelta(days=7)).isoformat(),
                "to": now.isoformat(),
            },
            "orders_count": orders_count,
            "revenue": round(revenue, 2),
            "new_products": len(items) if items else 0,
            "cancellations": status_counts.get("CANCELLED", 0),
            "refunds": status_counts.get("RETURN_REFUND", 0),
            "orders_by_status": status_counts,
            "avg_order_value": round(revenue / orders_count, 2) if orders_count else 0.0,
            "trends": {
                "orders_wow_change": self._compute_trend(orders_count, prev_count),
                "revenue_wow_change": self._compute_trend(revenue, prev_revenue),
            },
            "shop_performance": performance,
            "products_count": len(items),
        }
        self._save_history(report)
        self._last_report = report
        return report

    def generate_monthly_report(self) -> dict:
        orders, orders_count, revenue = self._fetch_orders(days=30)
        prev_orders, prev_count, prev_revenue = self._fetch_orders(days=60, order_status="COMPLETED")
        prev_count = max(prev_count, 1)
        items = self._fetch_items()
        performance = self._fetch_performance(days=30)
        status_counts = self._count_by_status(orders)
        now = datetime.now(UTC)

        report = {
            "type": "monthly",
            "generated_at": now.isoformat(),
            "period": {
                "from": (now - timedelta(days=30)).isoformat(),
                "to": now.isoformat(),
            },
            "orders_count": orders_count,
            "revenue": round(revenue, 2),
            "new_products": len(items) if items else 0,
            "cancellations": status_counts.get("CANCELLED", 0),
            "refunds": status_counts.get("RETURN_REFUND", 0),
            "orders_by_status": status_counts,
            "avg_order_value": round(revenue / orders_count, 2) if orders_count else 0.0,
            "trends": {
                "orders_mom_change": self._compute_trend(orders_count, prev_count),
                "revenue_mom_change": self._compute_trend(revenue, prev_revenue),
            },
            "shop_performance": performance,
            "products_count": len(items),
        }
        self._save_history(report)
        self._last_report = report
        return report

    # --- history ---

    def _save_history(self, report: dict) -> None:
        REPORT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": report["generated_at"],
            "type": report["type"],
            "orders_count": report["orders_count"],
            "revenue": report["revenue"],
            "file": str(self._last_export_path()) if hasattr(self, "_last_export_path") else "",
        }
        try:
            with REPORT_HISTORY_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_report_history(self, days: int = 30) -> list[dict]:
        if not REPORT_HISTORY_PATH.exists():
            return []
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        history: list[dict] = []
        try:
            for line in REPORT_HISTORY_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry.get("timestamp", "") >= cutoff:
                    history.append(entry)
        except Exception:
            pass
        return history

    # --- export ---

    def _last_export_path(self) -> Path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        return self.data_dir / f"report_{ts}"

    def export_to_excel(self, report: dict, filepath: str = "") -> str:
        if Workbook is None:
            raise RuntimeError("openpyxl is not installed")
        path = Path(filepath) if filepath else self._last_export_path().with_suffix(".xlsx")
        path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill("solid", fgColor="4F46E5")
        thin_border = Border(
            left=Side(style="thin"), right=Side(style="thin"),
            top=Side(style="thin"), bottom=Side(style="thin"),
        )

        # Summary sheet
        ws = wb.active
        ws.title = "Summary"
        summary_fields = [
            ("Generated At", report.get("generated_at")),
            ("Period From", report.get("period", {}).get("from", "")),
            ("Period To", report.get("period", {}).get("to", "")),
            ("Orders Count", report.get("orders_count", 0)),
            ("Revenue", report.get("revenue", 0)),
            ("Avg Order Value", report.get("avg_order_value", 0)),
            ("Cancellations", report.get("cancellations", 0)),
            ("Refunds", report.get("refunds", 0)),
            ("Products Count", report.get("products_count", 0)),
        ]
        for col, (label, value) in enumerate(summary_fields, 1):
            cell = ws.cell(row=1, column=col, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
            ws.cell(row=2, column=col, value=value).border = thin_border

        # Orders by status sheet
        ws2 = wb.create_sheet("Orders by Status")
        statuses = report.get("orders_by_status", {})
        ws2.cell(row=1, column=1, value="Status").font = header_font
        ws2.cell(row=1, column=1).fill = header_fill
        ws2.cell(row=1, column=2, value="Count").font = header_font
        ws2.cell(row=1, column=2).fill = header_fill
        for row, (status, count) in enumerate(sorted(statuses.items()), 2):
            ws2.cell(row=row, column=1, value=status).border = thin_border
            ws2.cell(row=row, column=2, value=count).border = thin_border

        # Trends sheet
        ws3 = wb.create_sheet("Trends")
        trends = report.get("trends", {})
        ws3.cell(row=1, column=1, value="Metric").font = header_font
        ws3.cell(row=1, column=1).fill = header_fill
        ws3.cell(row=1, column=2, value="Change (%)").font = header_font
        ws3.cell(row=1, column=2).fill = header_fill
        for row, (metric, change) in enumerate(sorted(trends.items()), 2):
            ws3.cell(row=row, column=1, value=metric).border = thin_border
            ws3.cell(row=row, column=2, value=change).border = thin_border

        wb.save(str(path))
        return str(path)

    def export_to_csv(self, report: dict, filepath: str = "") -> str:
        path = Path(filepath) if filepath else self._last_export_path().with_suffix(".csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["Metric", "Value"])
            writer.writerow(["Generated At", report.get("generated_at", "")])
            writer.writerow(["Type", report.get("type", "")])
            writer.writerow(["Orders Count", report.get("orders_count", 0)])
            writer.writerow(["Revenue", report.get("revenue", 0)])
            writer.writerow(["Avg Order Value", report.get("avg_order_value", 0)])
            writer.writerow(["Cancellations", report.get("cancellations", 0)])
            writer.writerow(["Refunds", report.get("refunds", 0)])
            writer.writerow(["Products Count", report.get("products_count", 0)])
            writer.writerow([])
            writer.writerow(["Orders by Status", "Count"])
            for status, count in sorted(report.get("orders_by_status", {}).items()):
                writer.writerow([status, count])
            writer.writerow([])
            writer.writerow(["Trend", "Change (%)"])
            for metric, change in sorted(report.get("trends", {}).items()):
                writer.writerow([metric, change])
        return str(path)

    def export_to_html(self, report: dict, filepath: str = "") -> str:
        path = Path(filepath) if filepath else self._last_export_path().with_suffix(".html")
        path.parent.mkdir(parents=True, exist_ok=True)
        trends_rows = "".join(
            f"<tr><td>{k}</td><td>{v}%</td></tr>" for k, v in sorted(report.get("trends", {}).items())
        )
        status_rows = "".join(
            f"<tr><td>{s}</td><td>{c}</td></tr>" for s, c in sorted(report.get("orders_by_status", {}).items())
        )
        html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>{report.get('type','report').title()} Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; color: #333; }}
h1 {{ color: #4F46E5; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4F46E5; color: #fff; }}
.card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 12px 0; }}
</style></head>
<body>
<h1>{report.get('type','report').title()} Report</h1>
<p>Generated: {report.get('generated_at','')}</p>
<p>Period: {report.get('period',{}).get('from','')} to {report.get('period',{}).get('to','')}</p>
<div class="card">
<h2>Key Metrics</h2>
<p>Orders: <strong>{report.get('orders_count',0)}</strong></p>
<p>Revenue: <strong>{report.get('revenue',0)}</strong></p>
<p>Avg Order Value: <strong>{report.get('avg_order_value',0)}</strong></p>
<p>Cancellations: {report.get('cancellations',0)} | Refunds: {report.get('refunds',0)}</p>
</div>
<div class="card">
<h2>Orders by Status</h2>
<table><tr><th>Status</th><th>Count</th></tr>{status_rows}</table>
</div>
<div class="card">
<h2>Trends</h2>
<table><tr><th>Metric</th><th>Change</th></tr>{trends_rows}</table>
</div>
</body></html>"""
        path.write_text(html, encoding="utf-8")
        return str(path)

    def send_email(self, report: dict, recipients: list[str], format: str = "html") -> bool:
        smtp_host = os.getenv("SMTP_HOST", "")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER", "")
        smtp_pass = os.getenv("SMTP_PASS", "")
        smtp_from = os.getenv("SMTP_FROM", smtp_user)
        if not smtp_host or not smtp_user or not smtp_pass:
            return False
        msg = MIMEMultipart("mixed")
        msg["From"] = smtp_from
        msg["To"] = ", ".join(recipients)
        report_type = report.get("type", "report").title()
        msg["Subject"] = f"Laura {report_type} Report - {report.get('generated_at', '')}"

        if format == "html":
            html_path = self.export_to_html(report)
            html_content = Path(html_path).read_text(encoding="utf-8")
            msg.attach(MIMEText(html_content, "html"))
        elif format == "csv":
            csv_path = self.export_to_csv(report)
            csv_content = Path(csv_path).read_bytes()
            part = MIMEBase("text", "csv")
            part.set_payload(csv_content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment; filename=report.csv")
            msg.attach(part)
            msg.attach(MIMEText("Please find the report attached.", "plain"))
        else:
            txt = f"Report Type: {report.get('type')}\nOrders: {report.get('orders_count')}\nRevenue: {report.get('revenue')}"
            msg.attach(MIMEText(txt, "plain"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            return True
        except Exception:
            return False

    # --- convenience ---

    def last_report(self) -> dict | None:
        return self._last_report


# ── ReportScheduler ──────────────────────────────────────────────────────────


class ReportScheduler:
    """Schedules periodic report generation using threading.Timer.
    Persists schedules to reports/report_schedules.json.
    """

    def __init__(self, client=None, reports_dir="reports"):
        self.client = client
        self.reports_dir = Path(reports_dir)
        self._schedules_file = self.reports_dir / "report_schedules.json"
        self._schedules: list[dict] = []
        self._timers: dict[str, threading.Timer] = {}
        self._engine = ReportingEngine(client=client, data_dir=str(self.reports_dir))
        self._load_schedules()

    def _load_schedules(self):
        try:
            if self._schedules_file.exists():
                data = json.loads(self._schedules_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._schedules = data
        except Exception:
            self._schedules = []

    def _save_schedules(self):
        try:
            self.reports_dir.mkdir(parents=True, exist_ok=True)
            self._schedules_file.write_text(
                json.dumps(self._schedules, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _parse_time(self, time_str: str) -> tuple[int, int]:
        parts = time_str.strip().split(":")
        return int(parts[0]), int(parts[1])

    def _seconds_until(self, hour: int, minute: int) -> float:
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        now = _dt.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += _td(days=1)
        return (target - now).total_seconds()

    def schedule_daily(self, time_str="08:00"):
        hour, minute = self._parse_time(time_str)
        schedule = {"type": "daily", "time": time_str, "hour": hour, "minute": minute, "enabled": True}
        self._schedules = [s for s in self._schedules if s.get("type") != "daily"]
        self._schedules.append(schedule)
        self._save_schedules()
        self._start_timer("daily", self._seconds_until(hour, minute), self._run_daily)
        return schedule

    def schedule_weekly(self, day="monday", time_str="09:00"):
        days_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
        target_day = days_map.get(day.lower(), 0)
        hour, minute = self._parse_time(time_str)
        schedule = {"type": "weekly", "day": day, "day_num": target_day, "time": time_str, "hour": hour, "minute": minute, "enabled": True}
        self._schedules = [s for s in self._schedules if s.get("type") != "weekly"]
        self._schedules.append(schedule)
        self._save_schedules()
        self._start_timer("weekly", self._seconds_until_weekday(target_day, hour, minute), self._run_weekly)
        return schedule

    def schedule_monthly(self, day=1, time_str="10:00"):
        hour, minute = self._parse_time(time_str)
        schedule = {"type": "monthly", "day": day, "time": time_str, "hour": hour, "minute": minute, "enabled": True}
        self._schedules = [s for s in self._schedules if s.get("type") != "monthly"]
        self._schedules.append(schedule)
        self._save_schedules()
        self._start_timer("monthly", self._seconds_until_monthly(day, hour, minute), self._run_monthly)
        return schedule

    def _seconds_until_weekday(self, target_day: int, hour: int, minute: int) -> float:
        from datetime import datetime as _dt
        from datetime import timedelta as _td
        now = _dt.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (target_day - now.weekday()) % 7
        if days_ahead == 0 and target <= now:
            days_ahead = 7
        target += _td(days=days_ahead)
        return (target - now).total_seconds()

    def _seconds_until_monthly(self, target_day: int, hour: int, minute: int) -> float:
        from datetime import datetime as _dt
        now = _dt.now()
        year = now.year
        month = now.month
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        actual_day = min(target_day, max_day)
        target = now.replace(day=actual_day, hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            if month == 12:
                year += 1
                month = 1
            else:
                month += 1
            max_day = calendar.monthrange(year, month)[1]
            actual_day = min(target_day, max_day)
            target = now.replace(year=year, month=month, day=actual_day, hour=hour, minute=minute, second=0, microsecond=0)
        return (target - now).total_seconds()

    def _start_timer(self, name: str, delay: float, callback):
        self.cancel(name)
        timer = threading.Timer(delay, self._timer_callback, args=[name, callback])
        timer.daemon = True
        self._timers[name] = timer
        timer.start()

    def _timer_callback(self, name: str, callback):
        try:
            callback()
        except Exception as exc:
            warning(f"Report scheduler timer {name} failed: {exc}")
        schedule = next((s for s in self._schedules if s.get("type") == name), None)
        if schedule and schedule.get("enabled"):
            if name == "daily":
                self._start_timer("daily", self._seconds_until(schedule["hour"], schedule["minute"]), self._run_daily)
            elif name == "weekly":
                self._start_timer("weekly", self._seconds_until_weekday(schedule["day_num"], schedule["hour"], schedule["minute"]), self._run_weekly)
            elif name == "monthly":
                self._start_timer("monthly", self._seconds_until_monthly(schedule["day"], schedule["hour"], schedule["minute"]), self._run_monthly)

    def _run_daily(self):
        info("ReportScheduler: generating daily report")
        report = self._engine.generate_daily_report()
        self._save_report_file(report, "daily")

    def _run_weekly(self):
        info("ReportScheduler: generating weekly report")
        report = self._engine.generate_weekly_report()
        self._save_report_file(report, "weekly")

    def _run_monthly(self):
        info("ReportScheduler: generating monthly report")
        report = self._engine.generate_monthly_report()
        self._save_report_file(report, "monthly")

    def _save_report_file(self, report: dict, report_type: str):
        try:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            path = self.reports_dir / f"scheduled_{report_type}_{ts}.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            info(f"ReportScheduler: saved {report_type} report to {path}")
        except Exception as exc:
            warning(f"ReportScheduler: failed to save report: {exc}")

    def cancel_all(self):
        for name, timer in list(self._timers.items()):
            try:
                timer.cancel()
            except Exception:
                pass
        self._timers.clear()
        self._schedules = []
        self._save_schedules()
        info("ReportScheduler: all schedules cancelled")

    def cancel(self, name: str):
        if name in self._timers:
            try:
                self._timers[name].cancel()
            except Exception:
                pass
            del self._timers[name]

    def list_schedules(self) -> list[dict]:
        return list(self._schedules)


def build_parser(subparsers) -> None:
    report_parser = subparsers.add_parser("report", help="Generate and manage reports")
    report_sub = report_parser.add_subparsers(dest="report_command", required=True)

    report_sub.add_parser("daily", help="Generate daily report")
    report_sub.add_parser("weekly", help="Generate weekly report")
    report_sub.add_parser("monthly", help="Generate monthly report")

    export_parser = report_sub.add_parser("export", help="Export last report")
    export_parser.add_argument("--format", choices=["excel", "csv", "html"], default="excel", help="Export format")
    export_parser.add_argument("--file", default="", help="Output file path")

    email_parser = report_sub.add_parser("email", help="Email last report")
    email_parser.add_argument("--to", required=True, help="Recipient email(s), comma-separated")
    email_parser.add_argument("--format", choices=["html", "csv", "plain"], default="html", help="Email format")

    send_parser = report_sub.add_parser("send", help="Generate and email in one step")
    send_parser.add_argument("--type", choices=["daily", "weekly", "monthly"], required=True, help="Report type")
    send_parser.add_argument("--to", required=True, help="Recipient email(s), comma-separated")
    send_parser.add_argument("--format", choices=["html", "csv", "plain"], default="html", help="Email format")

    report_sub.add_parser("history", help="List past reports")

    # ── Schedule subcommands ────────────────────────────────────────────────
    schedule_parser = report_sub.add_parser("schedule", help="Schedule periodic report generation")
    schedule_sub = schedule_parser.add_subparsers(dest="schedule_action", required=True)

    daily_sched = schedule_sub.add_parser("daily", help="Schedule daily report")
    daily_sched.add_argument("--time", default="08:00", help="Time HH:MM (default: 08:00)")

    weekly_sched = schedule_sub.add_parser("weekly", help="Schedule weekly report")
    weekly_sched.add_argument("--day", default="monday", choices=["monday","tuesday","wednesday","thursday","friday","saturday","sunday"], help="Day of week")
    weekly_sched.add_argument("--time", default="09:00", help="Time HH:MM (default: 09:00)")

    monthly_sched = schedule_sub.add_parser("monthly", help="Schedule monthly report")
    monthly_sched.add_argument("--day", type=int, default=1, help="Day of month (1-31, default: 1)")
    monthly_sched.add_argument("--time", default="10:00", help="Time HH:MM (default: 10:00)")

    schedule_sub.add_parser("list", help="List active schedules")
    schedule_sub.add_parser("cancel", help="Cancel all schedules")


def run(args, client=None, cfg=None) -> int:
    engine = ReportingEngine(client=client)
    cmd = args.report_command

    if cmd == "daily":
        report = engine.generate_daily_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    elif cmd == "weekly":
        report = engine.generate_weekly_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    elif cmd == "monthly":
        report = engine.generate_monthly_report()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    elif cmd == "export":
        report = engine.last_report()
        if not report:
            print("No report generated yet. Run 'laura report daily' first.", file=sys.stderr)
            return 1
        fmt = args.format
        if fmt == "excel":
            path = engine.export_to_excel(report, filepath=args.file)
        elif fmt == "csv":
            path = engine.export_to_csv(report, filepath=args.file)
        elif fmt == "html":
            path = engine.export_to_html(report, filepath=args.file)
        else:
            print(f"Unknown format: {fmt}", file=sys.stderr)
            return 1
        print(f"Report exported to: {path}")
        return 0
    elif cmd == "email":
        report = engine.last_report()
        if not report:
            print("No report generated yet. Run 'laura report daily' first.", file=sys.stderr)
            return 1
        recipients = [r.strip() for r in args.to.split(",") if r.strip()]
        ok = engine.send_email(report, recipients, format=args.format)
        if ok:
            print(f"Report emailed to {', '.join(recipients)}")
            return 0
        else:
            print("Failed to send email. Check SMTP config.", file=sys.stderr)
            return 1
    elif cmd == "send":
        if args.type == "daily":
            report = engine.generate_daily_report()
        elif args.type == "weekly":
            report = engine.generate_weekly_report()
        elif args.type == "monthly":
            report = engine.generate_monthly_report()
        else:
            print(f"Unknown type: {args.type}", file=sys.stderr)
            return 1
        recipients = [r.strip() for r in args.to.split(",") if r.strip()]
        ok = engine.send_email(report, recipients, format=args.format)
        if ok:
            print(f"{args.type.title()} report generated and emailed to {', '.join(recipients)}")
            return 0
        else:
            print("Report generated but failed to send email. Check SMTP config.", file=sys.stderr)
            return 1
    elif cmd == "schedule":
        scheduler = ReportScheduler(client=client)
        action = args.schedule_action
        if action == "daily":
            s = scheduler.schedule_daily(time_str=args.time)
            print(f"Daily report scheduled at {args.time}")
            print(json.dumps(s, ensure_ascii=False))
        elif action == "weekly":
            s = scheduler.schedule_weekly(day=args.day, time_str=args.time)
            print(f"Weekly report scheduled on {args.day} at {args.time}")
            print(json.dumps(s, ensure_ascii=False))
        elif action == "monthly":
            s = scheduler.schedule_monthly(day=args.day, time_str=args.time)
            print(f"Monthly report scheduled on day {args.day} at {args.time}")
            print(json.dumps(s, ensure_ascii=False))
        elif action == "list":
            schedules = scheduler.list_schedules()
            if schedules:
                print(json.dumps(schedules, ensure_ascii=False, indent=2))
            else:
                print("No active schedules.")
        elif action == "cancel":
            scheduler.cancel_all()
            print("All schedules cancelled.")
        return 0
    elif cmd == "history":
        history = engine.get_report_history()
        if not history:
            print("No report history found.")
        else:
            print(json.dumps(history, ensure_ascii=False, indent=2))
        return 0

    return 2
