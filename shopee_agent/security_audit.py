"""Security audit for Laura installation — checks secrets, permissions, dependencies."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shopee_agent.logger import info


class SecurityAudit:
    """Runs security checks on Laura installation and generates reports."""

    SECRET_PATTERNS: list[str] = [
        r"(?i)(?:api[_-]?key|apikey|secret|token|password|passwd|credential)[^=]*=\s*['\"]?(your_|changeme|placeholder|<|sk-|pk-)",
        r"(?i)(?:api[_-]?key|apikey|secret|token|password|passwd|credential)[^=]*=\s*['\"]?\w{0,5}['\"]?\s*$",
    ]

    def __init__(self, base_dir: str = "."):
        self._base = Path(base_dir).resolve()
        self._findings: list[dict[str, Any]] = []

    def run_all(self) -> list[dict[str, Any]]:
        self._findings = []
        self.check_env_secrets()
        self.check_file_permissions()
        self.check_dependencies()
        self.check_api_keys_in_code()
        self.check_https()
        return self._findings

    def _add(self, severity: str, title: str, detail: str, recommendation: str, category: str = "general") -> dict[str, Any]:
        finding: dict[str, Any] = {
            "severity": severity,
            "title": title,
            "detail": detail,
            "recommendation": recommendation,
            "category": category,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._findings.append(finding)
        return finding

    def check_env_secrets(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        env_path = self._base / ".env"
        if not env_path.exists():
            results.append(self._add("HIGH", ".env file missing", ".env not found in project root", "Create a .env file with your secrets", category="secrets"))
            return results

        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
        placeholder_count = 0
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            for pattern in self.SECRET_PATTERNS:
                if re.search(pattern, line):
                    placeholder_count += 1
                    key = line.split("=", 1)[0].strip()
                    results.append(self._add("CRITICAL", f"Placeholder secret in .env:{i}", f"Key '{key}' appears to be a placeholder or empty", "Set a real value for this key", category="secrets"))
                    break

        if placeholder_count == 0:
            results.append(self._add("LOW", ".env secrets check passed", "No placeholder values detected in .env", "Keep rotating secrets periodically", category="secrets"))

        return results

    def check_file_permissions(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        sensitive_paths = [
            self._base / ".env",
            self._base / "secrets",
            self._base / "secrets" / "gmail_token.json",
            self._base / "secrets" / "seller_center_cookies.json",
            self._base / "secrets" / "seller_center_credentials.json",
        ]

        for path in sensitive_paths:
            if not path.exists():
                continue
            try:
                st = path.stat()
                mode = stat.S_IMODE(st.st_mode)
                readable_by_others = bool(mode & 0o0044)
                if readable_by_others and sys.platform != "win32":
                    results.append(self._add("HIGH", f"World-readable file: {path.name}", f"Mode {oct(mode)} allows others to read", f"Run: chmod 600 {path}", category="permissions"))
                if path.is_file() and path.stat().st_mode & stat.S_IRWXO:
                    results.append(self._add("MEDIUM", f"Excessive permissions: {path.name}", f"Mode {oct(mode)} has group/other access", "Restrict permissions to owner-only", category="permissions"))
            except Exception as exc:
                results.append(self._add("MEDIUM", f"Cannot check permissions: {path.name}", str(exc), "Manually verify file permissions", category="permissions"))

        if not results:
            results.append(self._add("LOW", "File permissions check passed", "No permission issues detected", "Periodically re-check", category="permissions"))

        return results

    def check_dependencies(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        pyproject = self._base / "pyproject.toml"
        if not pyproject.exists():
            results.append(self._add("MEDIUM", "pyproject.toml not found", "Cannot verify dependency versions", "Ensure pyproject.toml exists in project root", category="dependencies"))
            return results

        try:
            import tomllib
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            try:
                import tomli
                data = tomli.loads(pyproject.read_text(encoding="utf-8"))
            except Exception:
                results.append(self._add("MEDIUM", "Cannot parse pyproject.toml", "tomllib/tomli not available", "Install Python 3.11+ or tomli", category="dependencies"))
                return results

        deps = data.get("project", {}).get("dependencies", [])
        if isinstance(deps, list):
            for dep in deps:
                dep = dep.strip()
                if not dep:
                    continue
                pkg_name = re.split(r"[>=<~!]", dep)[0].strip()
                try:
                    import importlib.metadata
                    installed = importlib.metadata.version(pkg_name)
                    info(f"Dependency {pkg_name}=={installed} (required: {dep})")
                except importlib.metadata.PackageNotFoundError:
                    results.append(self._add("MEDIUM", f"Missing dependency: {pkg_name}", f"Required by pyproject.toml: {dep}", f"Run: pip install {pkg_name}", category="dependencies"))
                except Exception as exc:
                    results.append(self._add("LOW", f"Cannot check dependency: {pkg_name}", str(exc), "Verify manually", category="dependencies"))

        if not results:
            results.append(self._add("LOW", "Dependency check passed", "All required packages are installed", "Keep dependencies up-to-date", category="dependencies"))

        return results

    def check_api_keys_in_code(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        key_patterns: list[tuple[str, str]] = [
            (r"(?i)(?:api[_-]?key|apikey)\s*=\s*['\"][A-Za-z0-9_\-]{20,}['\"]", "Hardcoded API key"),
            (r"(?i)(?:secret|password|token)\s*=\s*['\"][A-Za-z0-9_\-]{16,}['\"]", "Hardcoded secret/token"),
            (r"sk-[A-Za-z0-9]{20,}", "Stripe/OpenAI-style secret key"),
            (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
        ]

        py_files = list(self._base.rglob("*.py"))
        py_files = [f for f in py_files if "__pycache__" not in f.parts and ".venv" not in f.parts and "node_modules" not in f.parts]

        for py_file in py_files:
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern, label in key_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    results.append(self._add("HIGH", f"Possible {label} in {py_file.relative_to(self._base)}", f"Pattern matched {len(matches)} time(s)", "Move keys to .env and use os.getenv()", category="secrets"))

        if not results:
            results.append(self._add("LOW", "API key scan passed", "No hardcoded keys found in .py files", "Keep scanning as codebase grows", category="secrets"))

        return results

    def check_https(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        env_path = self._base / ".env"
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"(https?://[^\s\"']+)", content):
                url = match.group(1)
                if url.startswith("http://"):
                    results.append(self._add("MEDIUM", "HTTP URL in .env", f"Non-HTTPS URL: {url}", "Replace with HTTPS URL", category="network"))

        try:
            from shopee_agent.config import load_config
            cfg = load_config()
            if cfg.redirect_url and str(cfg.redirect_url).startswith("http://"):
                results.append(self._add("HIGH", "Shopee redirect_url uses HTTP", f"{cfg.redirect_url}", "Use HTTPS for OAuth redirect URL", category="network"))
        except Exception:
            pass

        dashboard_path = self._base / "shopee_agent" / "dashboard.py"
        if dashboard_path.exists():
            content = dashboard_path.read_text(encoding="utf-8", errors="replace")
            if "auth" not in content.lower() and ("@app" in content or "FastAPI" in content):
                results.append(self._add("MEDIUM", "Dashboard may lack authentication", "dashboard.py doesn't mention auth", "Add authentication middleware to dashboard", category="network"))

        if not results:
            results.append(self._add("LOW", "HTTPS check passed", "No HTTP URLs found", "Always use HTTPS in production", category="network"))

        return results

    def generate_report(self) -> str:
        lines: list[str] = [
            "=" * 60,
            "Laura Security Audit Report",
            f"Generated: {datetime.now(UTC).isoformat()}",
            f"Base directory: {self._base}",
            "=" * 60,
            "",
        ]

        by_severity: dict[str, list[dict[str, Any]]] = {}
        for f in self._findings:
            by_severity.setdefault(f["severity"], []).append(f)

        for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
            items = by_severity.get(severity, [])
            if not items:
                continue
            lines.append(f"[{severity}] — {len(items)} finding(s)")
            lines.append("-" * 40)
            for item in items:
                lines.append(f"  {item['title']}")
                lines.append(f"  Detail: {item['detail']}")
                lines.append(f"  Recommendation: {item['recommendation']}")
                lines.append("")
            lines.append("")

        total = len(self._findings)
        lines.append(f"Total findings: {total}")
        critical = len(by_severity.get("CRITICAL", []))
        high = len(by_severity.get("HIGH", []))
        if critical or high:
            lines.append(f"ACTION REQUIRED: {critical} CRITICAL, {high} HIGH")
        else:
            lines.append("No critical or high-severity findings.")

        lines.append("=" * 60)
        return "\n".join(lines)


def handle_audit(args: Any) -> None:
    audit = SecurityAudit(base_dir=os.getenv("LAURA_BASE_DIR", "."))
    if args.quick:
        findings = audit.check_env_secrets()
        findings.extend(audit.check_api_keys_in_code())
    else:
        findings = audit.run_all()

    if args.report:
        print(audit.generate_report())
    else:
        print(json.dumps(findings, ensure_ascii=False, indent=2))


def build_parser(subparsers) -> None:
    audit_parser = subparsers.add_parser("audit", help="Run security audit on Laura installation")
    audit_parser.add_argument("--quick", action="store_true", help="Run only critical checks")
    audit_parser.add_argument("--report", action="store_true", help="Output detailed human-readable report")
