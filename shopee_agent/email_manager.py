from __future__ import annotations

import base64
import email
import imaplib
import json
import os
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import requests

from .gmail_oauth import GmailOAuthClient, load_gmail_credentials

GMAIL_IMAP = "imap.gmail.com"
GMAIL_SMTP = "smtp.gmail.com"

FULL_SCOPES = [
    "https://mail.google.com/",
]


@dataclass
class EmailMessage:
    uid: str
    subject: str
    sender: str
    date: str
    snippet: str
    body_plain: str
    body_html: str
    labels: list[str]


class EmailManager:
    def __init__(self, credentials_file: str | Path, token_file: str | Path):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.creds = load_gmail_credentials(self.credentials_file)
        self.oauth = GmailOAuthClient(self.creds)
        self._access_token: str | None = None
        self._refresh_token: str | None = None

    @classmethod
    def from_env(cls) -> EmailManager | None:
        creds_file = os.getenv("GMAIL_CREDENTIALS_FILE", "").strip()
        token_file = os.getenv("GMAIL_TOKEN_FILE", "secrets/gmail_token.json").strip()
        if not creds_file:
            return None
        return cls(creds_file, token_file)

    def _load_tokens(self) -> bool:
        path = Path(self.token_file)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._access_token = (data.get("access_token") or "").strip() or None
            self._refresh_token = (data.get("refresh_token") or "").strip() or None
            return bool(self._access_token)
        except Exception:
            return False

    def _save_tokens(self, token_data: dict[str, Any]) -> None:
        path = Path(self.token_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(token_data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._access_token = (token_data.get("access_token") or "").strip() or None
        self._refresh_token = (token_data.get("refresh_token") or "").strip() or None

    def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token
        if self._load_tokens():
            return self._access_token
        raise RuntimeError(
            "Token do Gmail nao configurado. "
            "Use 'laura email auth-url' para obter a URL de autorizacao, "
            "depois 'laura email auth-callback CODIGO' para finalizar."
        )

    def _refresh_if_needed(self) -> str:
        token = self._ensure_token()
        if not self._refresh_token:
            return token
        try:
            self.oauth.get_profile(token)
            return token
        except Exception:
            pass
        try:
            new = self.oauth.refresh_access_token(self._refresh_token)
            self._save_tokens(new)
            return self._access_token
        except Exception as exc:
            raise RuntimeError(f"Falha ao renovar token Gmail: {exc}") from exc

    def authorization_url(self) -> str:
        return self.oauth.authorization_url(scopes=FULL_SCOPES)

    def exchange_code(self, code: str) -> dict[str, Any]:
        data = self.oauth.exchange_code(code)
        self._save_tokens(data)
        return data

    def get_profile(self) -> dict[str, Any]:
        token = self._refresh_if_needed()
        return self.oauth.get_profile(token)

    # --- Gmail API (REST) ---

    def _gmail_api_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._refresh_if_needed()
        resp = requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _gmail_api_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        token = self._refresh_if_needed()
        resp = requests.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=20,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Gmail API error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def list_labels(self) -> list[dict[str, Any]]:
        data = self._gmail_api_get("labels")
        return data.get("labels", [])

    def list_messages(self, query: str = "", max_results: int = 20) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"maxResults": min(max_results, 50)}
        if query:
            params["q"] = query
        data = self._gmail_api_get("messages", params)
        return data.get("messages", [])

    def get_message(self, msg_id: str) -> dict[str, Any]:
        return self._gmail_api_get(f"messages/{msg_id}", {"format": "full"})

    def parse_message(self, raw: dict[str, Any]) -> EmailMessage:
        headers = {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        date = headers.get("date", "")
        labels = raw.get("labelIds", [])

        snippet = raw.get("snippet", "")
        body_plain = ""
        body_html = ""

        def _extract_parts(part: dict[str, Any]) -> None:
            nonlocal body_plain, body_html
            mime = part.get("mimeType", "")
            if mime == "text/plain" and part.get("body", {}).get("data"):
                body_plain = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            elif mime == "text/html" and part.get("body", {}).get("data"):
                body_html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
            for sub in part.get("parts", []):
                _extract_parts(sub)

        _extract_parts(raw.get("payload", {}))

        return EmailMessage(
            uid=raw.get("id", ""),
            subject=subject,
            sender=sender,
            date=date,
            snippet=snippet,
            body_plain=body_plain,
            body_html=body_html,
            labels=labels,
        )

    def search_otp_codes(self, sender: str = "", max_results: int = 10) -> list[dict[str, str]]:
        query_parts = ["subject:(código OR codigo OR verification OR OTP OR 2FA)"]
        if sender:
            query_parts.append(f"from:({sender})")
        query = " ".join(query_parts)
        msgs = self.list_messages(query=query, max_results=max_results)
        results = []
        for m in msgs:
            detail = self.get_message(m["id"])
            parsed = self.parse_message(detail)
            import re
            codes = re.findall(r"\b(\d{4,8})\b", parsed.body_plain + parsed.snippet)
            results.append({
                "id": parsed.uid,
                "from": parsed.sender,
                "subject": parsed.subject,
                "date": parsed.date,
                "snippet": parsed.snippet,
                "codes_found": codes[:3],
            })
        return results

    def send_email(self, to: str, subject: str, body: str, body_html: str = "") -> bool:
        self._refresh_if_needed()
        msg = MIMEMultipart("alternative")
        msg["From"] = "me"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if body_html:
            msg.attach(MIMEText(body_html, "html", "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        self._gmail_api_post("messages/send", {"raw": raw})
        return True

    def mark_as_read(self, msg_id: str) -> bool:
        self._gmail_api_post(f"messages/{msg_id}/modify", {"removeLabelIds": ["UNREAD"]})
        return True

    def trash_message(self, msg_id: str) -> bool:
        self._gmail_api_post(f"messages/{msg_id}/trash", {})
        return True

    def list_threads(self, query: str = "", max_results: int = 10) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"maxResults": min(max_results, 50)}
        if query:
            params["q"] = query
        data = self._gmail_api_get("threads", params)
        return data.get("threads", [])

    # --- IMAP (for real-time polling) ---

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        token = self._refresh_if_needed()
        conn = imaplib.IMAP4_SSL(GMAIL_IMAP)
        oauth_str = f"user=wordshop.suporte24h@gmail.com\1auth=Bearer {token}\1\1"
        conn.authenticate("XOAUTH2", lambda _: oauth_str.encode("utf-8"))
        conn.select("INBOX")
        return conn

    def fetch_unseen(self) -> list[EmailMessage]:
        conn = self._imap_connect()
        try:
            _, data = conn.search(None, "UNSEEN")
            results = []
            for num in data[0].split() if data[0] else []:
                _, msg_data = conn.fetch(num, "(RFC822)")
                if msg_data and msg_data[0]:
                    raw_email = email.message_from_bytes(msg_data[1])
                    subject = raw_email.get("Subject", "")
                    sender = raw_email.get("From", "")
                    date = raw_email.get("Date", "")
                    body_plain = ""
                    if raw_email.is_multipart():
                        for part in raw_email.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body_plain = part.get_payload(decode=True).decode("utf-8", errors="replace")
                                except Exception:
                                    pass
                                break
                    else:
                        try:
                            body_plain = raw_email.get_payload(decode=True).decode("utf-8", errors="replace")
                        except Exception:
                            pass
                    snippet = body_plain[:150].replace("\n", " ").strip()
                    results.append(EmailMessage(
                        uid=num.decode() if isinstance(num, bytes) else str(num),
                        subject=subject,
                        sender=sender,
                        date=date,
                        snippet=snippet,
                        body_plain=body_plain,
                        body_html="",
                        labels=[],
                    ))
            return results
        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass
