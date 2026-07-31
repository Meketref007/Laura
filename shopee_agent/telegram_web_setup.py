from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

COOKIES_FILE = "secrets/telegram_web_cookies.json"
CONFIG_FILE = "secrets/telegram_setup.json"


def _log(msg: str) -> None:
    print(f"  [Telegram Setup] {msg}")


class TelegramWebSetup:
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self.cdp_url = cdp_url
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._bot_token: str | None = None

    async def connect(self) -> bool:
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        try:
            self._browser = await self._playwright.chromium.connect_over_cdp(self.cdp_url)
            _log("Conectado ao Brave!")
            return True
        except Exception as e:
            _log(f"Erro: {e}")
            return False

    async def find_telegram(self) -> bool:
        if not self._browser:
            return False
        for ctx in self._browser.contexts:
            for page in ctx.pages:
                if "web.telegram.org" in page.url:
                    self._context = ctx
                    self._page = page
                    _log(f"Aba Telegram: {page.url}")
                    return True
        _log("Aba Telegram nao encontrada")
        return False

    async def save_cookies(self) -> None:
        if not self._context:
            return
        cookies = await self._context.cookies()
        Path(COOKIES_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(COOKIES_FILE).write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
        _log(f"{len(cookies)} cookies salvos")

    def get_token_from_config(self) -> str | None:
        path = Path(CONFIG_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return (data.get("bot_token") or "").strip() or None
            except Exception:
                pass
        return None

    def save_token(self, token: str) -> None:
        self._bot_token = token
        Path(CONFIG_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(CONFIG_FILE).write_text(
            json.dumps({"bot_token": token, "setup_complete": True}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _log("Token salvo!")

    async def run(self) -> dict[str, Any]:
        result = {"success": False, "bot_token": None, "configured": False}

        if not await self.connect():
            result["error"] = "Nao conectou no Brave (porta 9222)"
            return result

        if not await self.find_telegram():
            result["error"] = "Abra web.telegram.org no Brave primeiro"
            return result

        await self.save_cookies()
        _log("Cookies do Telegram salvos!")

        token_env = os.getenv("LAURA_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
        if token_env:
            self._bot_token = token_env
            result["bot_token"] = token_env
            result["configured"] = True
            result["success"] = True
            _log(f"Token ja configurado: {token_env[:10]}...")
            return result

        saved_token = self.get_token_from_config()
        if saved_token:
            self._bot_token = saved_token
            result["bot_token"] = saved_token
            result["configured"] = True
            result["success"] = True
            _log("Token carregado do arquivo")
            return result

        _log("Token nao encontrado no .env nem no arquivo de config.")
        result["success"] = True
        result["needs_token"] = True
        return result


def run() -> dict[str, Any]:
    s = TelegramWebSetup()
    r = asyncio.run(s.run())
    if r.get("needs_token"):
        print("\n" + "=" * 55)
        print("Para finalizar a configuracao:")
        print("1. Va no BotFather no Telegram Web")
        print("2. Envie /mybots, clique no seu bot, depois API Token")
        print("3. Copie o token e execute:")
        print("   laura telegram-setup-token SEU_TOKEN_AQUI")
        print("=" * 55)
    return r


def save_token_command(token: str) -> None:
    s = TelegramWebSetup()
    s.save_token(token)
    print("Token salvo! Agora execute: laura telegram-bot")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "save-token":
        save_token_command(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        run()
