"""Interactive setup wizard for Laura — first-time configuration."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"

# ── ANSI helpers ────────────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[91m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_BLUE = "\033[94m"
_MAGENTA = "\033[95m"
_CYAN = "\033[96m"


def _ok(text: str) -> str:
    return f"{_GREEN}{text}{_RESET}"


def _warn(text: str) -> str:
    return f"{_YELLOW}{text}{_RESET}"


def _err(text: str) -> str:
    return f"{_RED}{text}{_RESET}"


def _info(text: str) -> str:
    return f"{_CYAN}{text}{_RESET}"


def _bold(text: str) -> str:
    return f"{_BOLD}{text}{_RESET}"


def _dim(text: str) -> str:
    return f"{_DIM}{text}{_RESET}"


def _mask(value: str, visible: int = 4) -> str:
    if not value:
        return "(empty)"
    if len(value) <= visible:
        return "*" * (len(value) - 1) + value[-1]
    return "*" * (len(value) - visible) + value[-visible:]


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    if default:
        label = f"{label} [{default}]"
    label = f"{_CYAN}>>>{_RESET} {label}: "
    while True:
        raw = input(label).strip()
        if raw:
            return raw
        if default:
            return default


def _prompt_required(label: str, secret: bool = False, validator: callable = None) -> str:
    while True:
        raw = input(f"{_CYAN}>>>{_RESET} {label}: ").strip()
        if not raw:
            print(f"  {_err('This value is required.')}")
            continue
        if validator and not validator(raw):
            print(f"  {_err('Invalid value.')}")
            continue
        return raw


def _confirm(label: str, default: bool = True) -> bool:
    suffix = " [Y/n]" if default else " [y/N]"
    raw = input(f"{_CYAN}>>>{_RESET} {label}{suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes", "s", "sim")


def _heading(text: str) -> None:
    width = shutil.get_terminal_size((80, 20)).columns
    print()
    print(f"{_BOLD}{_BLUE}{'═' * width}{_RESET}")
    print(f"{_BOLD}{_BLUE}  {text}{_RESET}")
    print(f"{_BOLD}{_BLUE}{'═' * width}{_RESET}")
    print()


def _step(current: int, total: int, label: str) -> None:
    print(f"\n{_BOLD}{_MAGENTA}[{current}/{total}]{_RESET} {_bold(label)}")


# ── Wizard ──────────────────────────────────────────────────────────────────


class SetupWizard:
    """Interactive setup wizard for Laura — first-time configuration."""

    TOTAL_STEPS = 6

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def run(self) -> bool:
        """Run the full wizard flow. Returns True on success."""
        self.welcome()
        issues = self.check_prerequisites()
        if issues:
            print(f"\n  {_err('Prerequisites not met:')}")
            for i in issues:
                print(f"    {_err('✗')} {i}")
            if not _confirm("Continue anyway?", default=False):
                print(f"\n  {_warn('Setup aborted.')}")
                return False

        print(f"\n  {_ok('All prerequisites satisfied.')}")
        self._config["shopee"] = self.configure_shopee()
        self._config["llm"] = self.configure_llm()
        self._config["telegram"] = self.configure_telegram()
        self._config["dashboard"] = self.configure_dashboard()
        self._config["env"] = self._detect_existing_env()

        print()
        self.test_connection()
        self.save_config(self._config)
        self.show_summary(self._config)
        self.next_steps()
        print(f"\n  {_ok('Setup complete! Run `laura daemon` to start.')}")
        return True

    def welcome(self) -> None:
        """Show ASCII art logo and welcome message."""
        shutil.get_terminal_size((80, 20)).columns
        logo = textwrap.dedent(f"""\
        {_BOLD}{_CYAN}
        ╔══════════════════════════════════════════════════════════════╗
        ║                                                              ║
        ║           ██╗      █████╗ ██╗   ██╗██████╗  █████╗          ║
        ║           ██║     ██╔══██╗██║   ██║██╔══██╗██╔══██╗         ║
        ║           ██║     ███████║██║   ██║██████╔╝███████║         ║
        ║           ██║     ██╔══██║██║   ██║██╔══██╗██╔══██║         ║
        ║           ███████╗██║  ██║╚██████╔╝██║  ██║██║  ██║         ║
        ║           ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║
        ║                                                              ║
        ║              Autonomous Shopee Seller Agent                   ║
        ║                   ✦  Setup Wizard  ✦                         ║
        ╚══════════════════════════════════════════════════════════════╝
        {_RESET}""")
        print(logo)
        print(f"  {_bold('Welcome to Laura!')}")
        print(f"  This wizard will help you configure Laura in {_bold('6 quick steps')}.")
        print(f"  You'll need your {_bold('Shopee API credentials')} handy.")
        print()

    def check_prerequisites(self) -> list[str]:
        """Check Python version, Ollama, disk space. Returns list of issues."""
        issues: list[str] = []
        _step(1, self.TOTAL_STEPS, "Checking prerequisites")

        # Python version
        py = sys.version_info
        if py.major < 3 or (py.major == 3 and py.minor < 10):
            issues.append(f"Python >= 3.10 required (found {py.major}.{py.minor})")
        else:
            print(f"  {_ok('✓')} Python {py.major}.{py.minor}.{py.micro}")

        # dotenv
        try:
            import dotenv  # noqa: F401
            print(f"  {_ok('✓')} python-dotenv available")
        except ImportError:
            issues.append("python-dotenv not installed (pip install python-dotenv)")

        # Ollama
        try:
            result = subprocess.run(
                ["ollama", "--version"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                ver = result.stdout.strip() or result.stderr.strip()
                print(f"  {_ok('✓')} Ollama {ver}")
            else:
                issues.append("Ollama not responding. Install from https://ollama.ai")
        except FileNotFoundError:
            issues.append("Ollama not found. Install from https://ollama.ai")
        except subprocess.TimeoutExpired:
            issues.append("Ollama timed out")

        # Disk space
        try:
            usage = shutil.disk_usage(BASE_DIR)
            free_gb = usage.free / (1024 ** 3)
            if free_gb < 0.5:
                issues.append(f"Low disk space: {free_gb:.1f} GB free (minimum 0.5 GB)")
            else:
                print(f"  {_ok('✓')} Disk space: {free_gb:.1f} GB free")
        except Exception:
            pass

        # Internet connectivity (basic)
        try:
            import urllib.request
            urllib.request.urlopen("https://httpbin.org/get", timeout=5)
            print(f"  {_ok('✓')} Internet connectivity")
        except Exception:
            issues.append("No internet connectivity detected")

        return issues

    def configure_shopee(self) -> dict:
        """Prompt for Shopee API credentials. Returns dict with keys."""
        _step(2, self.TOTAL_STEPS, "Shopee API Configuration")
        print(f"  {_dim('Get these from https://partner.shopeemobile.com')}")
        print()

        partner_id = _prompt_required(
            "Partner ID (numeric)",
            validator=lambda v: v.isdigit(),
        )
        partner_key = _prompt_required(
            "Partner Key (SHA256 hex)",
            validator=lambda v: len(v) >= 32,
        )
        access_token = _prompt_required(
            "Access Token (from OAuth redirect)",
        )
        shop_id = _prompt(
            "Default Shop ID (numeric, optional)",
            default="",
        )

        return {
            "partner_id": int(partner_id),
            "partner_key": partner_key,
            "access_token": access_token,
            "shop_id": int(shop_id) if shop_id.isdigit() else 0,
        }

    def configure_llm(self) -> str:
        """Choose local (Ollama) or remote (ChatGPT/Claude). Returns model key."""
        _step(3, self.TOTAL_STEPS, "LLM Configuration")
        print(f"  {_dim('Laura needs a language model for analysis and decisions.')}")
        print()

        if _confirm("Use local Ollama (free, recommended)?", default=True):
            model = _prompt("Ollama model", default="tinyllama")
            self._config.setdefault("env", {})["LAURA_LLM_MODEL"] = model
            print(f"  {_ok('Local model selected:')} {_bold(model)}")
            return "local"
        else:
            print(f"  {_warn('Remote LLM selected. API costs may apply.')}")
            provider = _prompt("Provider (openai / anthropic)", default="openai").strip().lower()
            api_key = _prompt_required("API Key")
            if provider == "anthropic":
                self._config.setdefault("env", {})["ANTHROPIC_API_KEY"] = api_key
            else:
                self._config.setdefault("env", {})["OPENAI_API_KEY"] = api_key
            self._config.setdefault("env", {})["LAURA_ALLOW_PAID_LLM"] = "1"
            return f"remote:{provider}"

    def configure_telegram(self) -> str:
        """Optional Telegram bot token."""
        _step(4, self.TOTAL_STEPS, "Telegram Bot (optional)")
        print(f"  {_dim('Get a token from @BotFather on Telegram.')}")
        print(f"  {_dim('Leave empty to skip Telegram notifications.')}")

        token = _prompt("Bot token", default="")
        if token:
            self._config.setdefault("env", {})["TELEGRAM_BOT_TOKEN"] = token
            chat_id = _prompt("Chat ID (optional)", default="")
            if chat_id:
                self._config.setdefault("env", {})["TELEGRAM_CHAT_ID"] = chat_id
            print(f"  {_ok('Telegram configured.')}")
        else:
            print(f"  {_dim('Telegram notifications disabled.')}")
        return token

    def configure_dashboard(self) -> dict:
        """Configure dashboard port and API key."""
        _step(5, self.TOTAL_STEPS, "Dashboard Configuration")
        print(f"  {_dim('Laura includes a web dashboard for monitoring.')}")

        host = _prompt("Host", default="0.0.0.0")
        port_str = _prompt("Port", default="8888")
        try:
            port = int(port_str)
        except ValueError:
            port = 8888

        api_key = _prompt(
            "API Key (leave empty for auto-generate)",
            default="",
        )
        if not api_key:
            import secrets
            api_key = secrets.token_hex(16)
            print(f"  {_dim('Auto-generated API key:')} {_bold(api_key)}")

        config = {"host": host, "port": port, "api_key": api_key}
        self._config.setdefault("env", {}).update({
            "DASHBOARD_HOST": host,
            "DASHBOARD_PORT": str(port),
            "DASHBOARD_API_KEY": api_key,
        })
        return config

    def test_connection(self) -> dict:
        """Test Shopee API connection. Returns result dict."""
        _step(6, self.TOTAL_STEPS, "Testing Shopee API Connection")
        shopee = self._config.get("shopee", {})
        if not shopee.get("partner_id"):
            print(f"  {_warn('No Shopee credentials configured; skipping test.')}")
            return {"success": False, "error": "No credentials"}

        base_url = (
            "https://partner.shopeemobile.com"
            if str(shopee["partner_id"]).startswith("2")
            else "https://partner.test.shopeemobile.com"
        )

        import hashlib
        import time

        timestamp = int(time.time())
        partner_id = shopee["partner_id"]
        partner_key = shopee["partner_key"]
        access_token = shopee.get("access_token", "")
        shop_id = shopee.get("shop_id", 0)

        raw = f"{partner_id}{base_url}/api/v2/shop/get_shop_info{timestamp}{access_token}{shop_id}{partner_key}"
        sign = hashlib.sha256(raw.encode("utf-8")).hexdigest()

        import requests

        try:
            resp = requests.post(
                f"{base_url}/api/v2/shop/get_shop_info",
                json={"partner_id": partner_id, "shop_id": shop_id},
                headers={
                    "Authorization": f"SHA256 Credential={partner_id}/{timestamp}/{sign}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            data = resp.json()
            if resp.ok and data.get("error") == 0:
                shop_name = (
                    data.get("response", {}).get("shop_name", "Unknown")
                )
                print(f"  {_ok('✓')} Connected to Shopee API")
                print(f"  {_ok('✓')} Shop: {_bold(shop_name)}")
                return {"success": True, "shop_name": shop_name}
            else:
                msg = data.get("message", data.get("error", "Unknown error"))
                print(f"  {_warn(f'API test: {msg}')}")
                if _confirm("Save config anyway?", default=True):
                    return {"success": False, "error": msg}
                return {"success": False, "error": msg}
        except Exception as exc:
            print(f"  {_warn(f'Connection failed: {exc}')}")
            if _confirm("Save config anyway?", default=True):
                return {"success": False, "error": str(exc)}
            return {"success": False, "error": str(exc)}

    def save_config(self, config: dict) -> bool:
        """Write configuration to .env file. Returns True on success."""
        env = {}
        env.update(config.get("env", {}))

        shopee = config.get("shopee", {})
        if shopee:
            env["SHOPEE_PARTNER_ID"] = str(shopee.get("partner_id", ""))
            env["SHOPEE_PARTNER_KEY_SHA256"] = shopee.get("partner_key", "")
            env["SHOPEE_DEFAULT_ACCESS_TOKEN"] = shopee.get("access_token", "")
            if shopee.get("shop_id"):
                env["SHOPEE_DEFAULT_SHOP_ID"] = str(shopee["shop_id"])

        lines = [
            "# =============================================================================",
            "# Laura — Auto-generated by setup wizard",
            f"# Generated: {__import__('datetime').datetime.now().isoformat()}",
            "# =============================================================================",
            "",
        ]

        for key in sorted(env):
            value = env[key]
            if value is None:
                continue
            lines.append(f"{key}={value}")

        lines.append("")

        try:
            ENV_FILE.write_text("\n".join(lines), encoding="utf-8")
            print(f"\n  {_ok('✓')} Configuration saved to {ENV_FILE}")
            return True
        except OSError as exc:
            print(f"\n  {_err(f'Failed to write .env: {exc}')}")
            return False

    def show_summary(self, config: dict) -> None:
        """Display configured values with masked secrets."""
        print()
        _heading("Configuration Summary")

        def row(label: str, value: str, secret: bool = False) -> None:
            display = _mask(value) if secret else (value or _dim("not set"))
            print(f"  {_bold(f'{label:.<30}')} {display}")

        shopee = config.get("shopee", {})
        row("Shopee Partner ID", str(shopee.get("partner_id", "")), secret=False)
        row("Shopee Partner Key", shopee.get("partner_key", ""), secret=True)
        row("Access Token", shopee.get("access_token", ""), secret=True)
        row("Shop ID", str(shopee.get("shop_id", "")))

        llm = config.get("llm", "local")
        row("LLM Provider", llm)

        telegram = config.get("telegram", "")
        row("Telegram Bot", "configured" if telegram else "disabled", secret=False)

        dash = config.get("dashboard", {})
        row("Dashboard Host", dash.get("host", "0.0.0.0"))
        row("Dashboard Port", str(dash.get("port", 8888)))
        row("Dashboard API Key", dash.get("api_key", ""), secret=True)

    def next_steps(self) -> None:
        """Show next steps after setup."""
        print()
        _heading("Next Steps")
        steps = [
            ("Run Laura", "laura daemon"),
            ("Open Dashboard", "laura dashboard"),
            ("Check Ollama", "laura ollama-status"),
            ("View Skills", "laura skill-list"),
            ("Run GOAP Planner", "laura skill-goap-plan"),
            ("Daily Report", "laura report-generate"),
            ("Full Docs", "laura --help"),
        ]
        for label, cmd in steps:
            print(f"  {_ok('→')} {_bold(f'{label}:')}  ")
            print(f"    $ {_info(cmd)}")
        print()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _detect_existing_env(self) -> dict:
        """Read any existing .env values to preserve them."""
        env: dict[str, str] = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
        return env


# ── Quick check (non-interactive) ───────────────────────────────────────────


def quick_check() -> int:
    """Run prerequisite checks only (--check mode). Returns 0 if all ok."""
    wiz = SetupWizard()
    issues = wiz.check_prerequisites()
    if issues:
        print(f"\n{_err(f'{len(issues)} issue(s) found:')}")
        for i in issues:
            print(f"  {_err('✗')} {i}")
        return 1
    print(f"\n{_ok('All checks passed.')}")
    return 0


# ── Quick setup (env-var driven) ────────────────────────────────────────────


def quick_setup() -> int:
    """Non-interactive setup using existing env vars (--quick mode)."""
    wiz = SetupWizard()
    wiz.welcome()

    required = {
        "SHOPEE_PARTNER_ID": "Partner ID",
        "SHOPEE_PARTNER_KEY_SHA256": "Partner Key",
        "SHOPEE_DEFAULT_ACCESS_TOKEN": "Access Token",
    }

    missing = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"{_err('Missing required env vars for --quick:')}")
        for k in missing:
            print(f"  {_err('✗')} {k}")
        return 1

    partner_id = os.getenv("SHOPEE_PARTNER_ID", "0")
    wiz._config["shopee"] = {
        "partner_id": int(partner_id) if partner_id.isdigit() else 0,
        "partner_key": os.getenv("SHOPEE_PARTNER_KEY_SHA256", ""),
        "access_token": os.getenv("SHOPEE_DEFAULT_ACCESS_TOKEN", ""),
        "shop_id": int(os.getenv("SHOPEE_DEFAULT_SHOP_ID", "0") or "0"),
    }
    wiz._config["llm"] = "local"
    wiz._config["telegram"] = os.getenv("TELEGRAM_BOT_TOKEN", "")
    wiz._config["dashboard"] = {
        "host": os.getenv("DASHBOARD_HOST", "0.0.0.0"),
        "port": int(os.getenv("DASHBOARD_PORT", "8888")),
        "api_key": os.getenv("DASHBOARD_API_KEY", ""),
    }

    # Re-read existing env to preserve them
    wiz._config["env"] = wiz._detect_existing_env()

    # Merge env vars over discovered
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DASHBOARD_API_KEY",
              "LAURA_LLM_MODEL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
              "LAURA_ALLOW_PAID_LLM"):
        v = os.getenv(k)
        if v:
            wiz._config.setdefault("env", {})[k] = v

    wiz.test_connection()
    wiz.save_config(wiz._config)
    wiz.show_summary(wiz._config)
    wiz.next_steps()
    print(f"\n  {_ok('Quick setup complete!')}")
    return 0


# ── CLI entry point ─────────────────────────────────────────────────────────


def build_parser(subparsers) -> None:
    """Add the ``laura setup`` subcommand tree to *subparsers*."""
    setup_parser = subparsers.add_parser(
        "setup",
        help="Interactive first-time setup wizard",
        description="Guided configuration of Shopee API, LLM, Telegram, and dashboard.",
    )
    setup_parser.add_argument(
        "--quick",
        action="store_true",
        help="Non-interactive: use env vars without prompts",
    )
    setup_parser.add_argument(
        "--check",
        action="store_true",
        help="Only check prerequisites, do not configure",
    )


def handle_setup(args, client=None, cfg=None) -> int:
    """Entry point for ``laura setup``."""
    if args.check:
        return quick_check()
    if args.quick:
        return quick_setup()
    wiz = SetupWizard()
    return 0 if wiz.run() else 1


if __name__ == "__main__":
    raise SystemExit(SetupWizard().run() is True)
