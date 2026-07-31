from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

GMAIL_SCOPES = [
    "https://mail.google.com/",
]


@dataclass(frozen=True)
class GmailCredentials:
    client_id: str
    client_secret: str
    auth_uri: str
    token_uri: str
    redirect_uri: str


class GmailOAuthError(RuntimeError):
    pass


def load_gmail_credentials(credentials_file: str | Path) -> GmailCredentials:
    path = Path(credentials_file)
    if not path.exists():
        raise GmailOAuthError(f"Credencial do Gmail nao encontrada: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    installed = payload.get("installed") or payload.get("web")
    if not isinstance(installed, dict):
        raise GmailOAuthError("Arquivo de credenciais do Gmail invalido: missing installed/web block")

    client_id = str(installed.get("client_id", "")).strip()
    client_secret = str(installed.get("client_secret", "")).strip()
    auth_uri = str(installed.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")).strip()
    token_uri = str(installed.get("token_uri", "https://oauth2.googleapis.com/token")).strip()
    redirect_uris = installed.get("redirect_uris", [])
    redirect_uri = str(redirect_uris[0] if isinstance(redirect_uris, list) and redirect_uris else "http://localhost").strip()

    if not client_id or not client_secret:
        raise GmailOAuthError("Arquivo de credenciais do Gmail incompleto: client_id/client_secret ausentes")

    return GmailCredentials(
        client_id=client_id,
        client_secret=client_secret,
        auth_uri=auth_uri,
        token_uri=token_uri,
        redirect_uri=redirect_uri,
    )


class GmailOAuthClient:
    def __init__(self, credentials: GmailCredentials):
        self.credentials = credentials

    @classmethod
    def from_file(cls, credentials_file: str | Path) -> GmailOAuthClient:
        return cls(load_gmail_credentials(credentials_file))

    def authorization_url(self, *, state: str | None = None, scopes: list[str] | None = None) -> str:
        params: dict[str, str] = {
            "client_id": self.credentials.client_id,
            "redirect_uri": self.credentials.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes or GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{self.credentials.auth_uri}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        response = requests.post(
            self.credentials.token_uri,
            data={
                "code": code,
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "redirect_uri": self.credentials.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise GmailOAuthError(f"Falha ao trocar code por token: {response.status_code} {response.text[:200]}")
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = requests.post(
            self.credentials.token_uri,
            data={
                "refresh_token": refresh_token,
                "client_id": self.credentials.client_id,
                "client_secret": self.credentials.client_secret,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise GmailOAuthError(f"Falha ao renovar token do Gmail: {response.status_code} {response.text[:200]}")
        return response.json()

    def get_profile(self, access_token: str) -> dict[str, Any]:
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if response.status_code >= 400:
            raise GmailOAuthError(f"Falha ao obter profile do Gmail: {response.status_code} {response.text[:200]}")
        return response.json()

    def list_labels(self, access_token: str) -> dict[str, Any]:
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/labels",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if response.status_code >= 400:
            raise GmailOAuthError(f"Falha ao listar labels do Gmail: {response.status_code} {response.text[:200]}")
        return response.json()
