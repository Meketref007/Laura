"""Relatorio semanal automatico em PDF."""
import os
import smtplib
from datetime import UTC, datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
PDF_DIR = REPORTS_DIR / "weekly_pdfs"


def _get_weekly_range() -> tuple[str, str]:
    now = datetime.now(UTC)
    last_monday = now - timedelta(days=now.weekday(), weeks=1)
    this_monday = last_monday + timedelta(days=7)
    return last_monday.strftime("%Y-%m-%d"), this_monday.strftime("%Y-%m-%d")


def generate_html_report(
    summary: dict,
    orders: list[dict],
    ratings: dict,
    pricing: list[dict],
    stock: list[dict],
    sentiment: dict,
) -> str:
    """Gera HTML do relatorio semanal."""
    from_ts, to_ts = _get_weekly_range()
    revenue = summary.get("revenue", 0)
    orders_count = summary.get("orders_seen", 0)
    avg_ticket = round(revenue / orders_count, 2) if orders_count else 0

    ratings_html = ""
    if ratings:
        ratings_html = f"""
        <div class="card">
            <h2>Avaliacoes</h2>
            <p>Media: <strong>{ratings.get('avg_stars', 'N/A')}</strong></p>
            <p>Total: {ratings.get('total_ratings', 0)}</p>
        </div>"""

    pricing_html = ""
    for p in pricing[:5]:
        direction = chr(8593) if p.get("direction") == "subir" else chr(8595) if p.get("direction") == "descer" else chr(8594)
        pricing_html += f"<tr><td>{p.get('name', '?')[:40]}</td><td>R$ {p.get('current_price', 0)}</td><td>R$ {p.get('suggested_price', 0)}</td><td>{direction} {p.get('direction', '')}</td></tr>"

    stock_html = ""
    for s in stock[:5]:
        stock_html += f"<tr><td>{s.get('name', '?')[:40]}</td><td>{s.get('current_stock', 0)}</td><td>{s.get('days_until_empty', 0)} dias</td><td>{s.get('priority', '')}</td></tr>"

    sent_html = ""
    if sentiment:
        for sug in sentiment.get("suggestions", []):
            sent_html += f"<li>{sug}</li>"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><title>Relatorio Semanal - ViluShop</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; color: #333; }}
h1 {{ color: #8B5CF6; }} h2 {{ color: #6366F1; }}
.card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 12px 0; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f4f4f4; }}
</style></head>
<body>
<h1>Relatorio Semanal ViluShop</h1>
<p><strong>Periodo:</strong> {from_ts} a {to_ts}</p>
<p><strong>Gerado em:</strong> {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}</p>

<div class="card">
    <h2>Resumo Financeiro</h2>
    <p>Faturamento: <strong>R$ {revenue:.2f}</strong></p>
    <p>Pedidos: <strong>{orders_count}</strong></p>
    <p>Ticket Medio: <strong>R$ {avg_ticket}</strong></p>
</div>

{ratings_html}

<div class="card">
    <h2>Sugestoes de Precificacao</h2>
    <table>
        <tr><th>Produto</th><th>Atual</th><th>Sugerido</th><th>Direcao</th></tr>
        {pricing_html or '<tr><td colspan="4">Sem dados</td></tr>'}
    </table>
</div>

<div class="card">
    <h2>Previsao de Estoque</h2>
    <table>
        <tr><th>Produto</th><th>Estoque</th><th>Previsao</th><th>Prioridade</th></tr>
        {stock_html or '<tr><td colspan="4">Sem dados</td></tr>'}
    </table>
</div>

<div class="card">
    <h2>Insights de Avaliacoes</h2>
    <ul>{sent_html or '<li>Sem dados</li>'}</ul>
</div>

<p style="color: #888; font-size: 12px;">Gerado automaticamente por Laura - ViluShop Bot</p>
</body></html>"""


def generate_pdf(seller_client, summary: dict, orders: list, ratings_data: dict) -> dict:
    """Gera relatorio semanal em PDF."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    from_ts, to_ts = _get_weekly_range()
    filename = f"relatorio_semanal_{from_ts}_a_{to_ts}.html"
    filepath = PDF_DIR / filename

    try:
        from shopee_agent.pricing_automation import generate_pricing_report
        pricing = generate_pricing_report(seller_client) or []
    except Exception:
        pricing = []

    try:
        from shopee_agent.stock_predictor import predict_restock
        stock = predict_restock(seller_client) or []
    except Exception:
        stock = []

    try:
        from shopee_agent.sentiment_analyzer import analyze_ratings
        sentiment = analyze_ratings(seller_client) or {}
    except Exception:
        sentiment = {}

    html = generate_html_report(summary, orders, ratings_data, pricing, stock, sentiment)
    filepath.write_text(html, encoding="utf-8")

    pdf_path = filepath.with_suffix(".pdf")
    pdf_ok = False
    try:
        from weasyprint import HTML
        HTML(string=html).write_pdf(str(pdf_path))
        pdf_ok = True
    except ImportError:
        try:
            import subprocess
            subprocess.run(
                ["wkhtmltopdf", str(filepath), str(pdf_path)],
                capture_output=True, timeout=30,
            )
            pdf_ok = True
        except Exception:
            pass
    except Exception:
        pass

    result_file = pdf_path if pdf_ok else filepath

    return {
        "file": str(result_file),
        "period": f"{from_ts} a {to_ts}",
        "revenue": summary.get("revenue", 0),
        "orders": summary.get("orders_seen", 0),
    }


def generate_report_pdf(report: dict, filepath: str = "") -> str:
    """Generate a styled PDF report from a report dict using reportlab."""
    try:
        from reportlab.lib.colors import HexColor, white
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError:
        raise RuntimeError("reportlab is required for PDF generation")

    path = Path(filepath) if filepath else PDF_DIR / f"report_{report.get('type', 'report')}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(str(path), pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("Title2", parent=styles["Title"],
                                  fontSize=22, textColor=HexColor("#4F46E5"),
                                  spaceAfter=6, alignment=TA_CENTER)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"],
                                     fontSize=11, textColor=HexColor("#6B7280"),
                                     alignment=TA_CENTER, spaceAfter=20)
    heading_style = ParagraphStyle("SectionHead", parent=styles["Heading2"],
                                    fontSize=14, textColor=HexColor("#4F46E5"),
                                    spaceBefore=16, spaceAfter=8)
    ParagraphStyle("Cell", parent=styles["Normal"], fontSize=9, leading=12)

    elements: list = []

    # Title page
    elements.append(Spacer(1, 4*cm))
    elements.append(Paragraph(f"Laura {report.get('type', 'report').title()} Report", title_style))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(
        f"Period: {report.get('period', {}).get('from', 'N/A')} to {report.get('period', {}).get('to', 'N/A')}",
        subtitle_style,
    ))
    elements.append(Paragraph(f"Generated: {report.get('generated_at', '')}", subtitle_style))
    elements.append(Spacer(1, 1*cm))

    # Key metrics
    elements.append(Paragraph("Key Metrics", heading_style))
    metrics_data = [
        ["Metric", "Value"],
        ["Orders", str(report.get("orders_count", 0))],
        ["Revenue", str(report.get("revenue", 0))],
        ["Avg Order Value", str(report.get("avg_order_value", 0))],
        ["Cancellations", str(report.get("cancellations", 0))],
        ["Refunds", str(report.get("refunds", 0))],
        ["Products Count", str(report.get("products_count", 0))],
    ]
    metrics_table = Table(metrics_data, colWidths=[5*cm, 8*cm])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#4F46E5")),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#D1D5DB")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#F9FAFB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 0.5*cm))

    # Orders by status
    statuses = report.get("orders_by_status", {})
    if statuses:
        elements.append(Paragraph("Orders by Status", heading_style))
        status_data = [["Status", "Count"]]
        for s, c in sorted(statuses.items()):
            status_data.append([s, str(c)])
        status_table = Table(status_data, colWidths=[8*cm, 5*cm])
        status_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#4F46E5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#D1D5DB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#F9FAFB")]),
        ]))
        elements.append(status_table)
        elements.append(Spacer(1, 0.5*cm))

    # Trends
    trends = report.get("trends", {})
    if trends:
        elements.append(Paragraph("Trends", heading_style))
        trend_data = [["Metric", "Change (%)"]]
        for k, v in sorted(trends.items()):
            trend_data.append([k, f"{v}%" if v is not None else "N/A"])
        trend_table = Table(trend_data, colWidths=[8*cm, 5*cm])
        trend_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HexColor("#4F46E5")),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#D1D5DB")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#F9FAFB")]),
        ]))
        elements.append(trend_table)

    doc.build(elements)
    return str(path)


def email_report_pdf(pdf_path: str, recipients: list[str]) -> bool:
    """Send a PDF report as email attachment via SMTP."""
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    smtp_from = os.getenv("SMTP_FROM", smtp_user)
    if not smtp_host or not smtp_user or not smtp_pass:
        return False

    pdf = Path(pdf_path)
    if not pdf.exists():
        return False

    msg = MIMEMultipart("mixed")
    msg["From"] = smtp_from
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"Weekly Report - {pdf.stem}"

    msg.attach(MIMEText("Please find attached the weekly report PDF.", "plain"))

    with pdf.open("rb") as fh:
        part = MIMEBase("application", "pdf")
        part.set_payload(fh.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={pdf.name}")
    msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception:
        return False
