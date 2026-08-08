"""E2E real contra a API da Shopee (opt-in).

So roda quando LAURA_E2E_REAL=1 e as credenciais SHOPEE_* estao no ambiente
(no CI, injetadas via secrets). Fora disso o teste e pulado com `-rs` para
razao visivel.

Endpoints de LEITURA apenas: get_shop_info e get_item_list.
Nunca altera dados reais da loja.
"""

from __future__ import annotations

import os

import pytest

from shopee_agent.client import ShopeeClient
from shopee_agent.config import ShopeeConfig

pytestmark = pytest.mark.integration


def _e2e_enabled() -> bool:
    return os.getenv("LAURA_E2E_REAL", "").strip().lower() in ("1", "true", "yes")


def _read(name: str) -> str:
    return os.getenv(name, "").strip()


@pytest.fixture
def e2e_client() -> ShopeeClient:
    return ShopeeClient(
        ShopeeConfig(
            base_url=os.getenv("SHOPEE_BASE_URL", "https://partner.shopeemobile.com").rstrip("/"),
            partner_id=int(_read("SHOPEE_PARTNER_ID")),
            partner_key=_read("SHOPEE_PARTNER_KEY"),
            redirect_url=_read("SHOPEE_REDIRECT_URL") or "https://example.com/callback",
            default_shop_id=int(_read("SHOPEE_DEFAULT_SHOP_ID") or "0") or None,
            default_access_token=_read("SHOPEE_DEFAULT_ACCESS_TOKEN") or None,
            default_refresh_token=_read("SHOPEE_DEFAULT_REFRESH_TOKEN") or None,
        )
    )


@pytest.mark.skipif(not _e2e_enabled(), reason="LAURA_E2E_REAL nao definido (smoke real opt-in)")
class TestRealShopeeSmoke:
    """Validacao real (leitura) contra a Shopee Open Platform."""

    @pytest.fixture(autouse=True)
    def _guard_creds(self):
        missing = [
            name
            for name in (
                "SHOPEE_PARTNER_ID",
                "SHOPEE_PARTNER_KEY",
                "SHOPEE_DEFAULT_SHOP_ID",
                "SHOPEE_DEFAULT_ACCESS_TOKEN",
            )
            if not _read(name)
        ]
        if missing:
            pytest.skip(f"credenciais ausentes: {', '.join(missing)}")

    def test_shop_info_ok(self, e2e_client: ShopeeClient) -> None:
        resp = e2e_client.get_shop_info(
            access_token=_read("SHOPEE_DEFAULT_ACCESS_TOKEN"),
            shop_id=int(_read("SHOPEE_DEFAULT_SHOP_ID")),
        )
        assert resp.ok, f"get_shop_info falhou: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body.get("error") in (None, ""), f"erro da API: {body}"

    def test_item_list_ok(self, e2e_client: ShopeeClient) -> None:
        resp = e2e_client.get_item_list(
            access_token=_read("SHOPEE_DEFAULT_ACCESS_TOKEN"),
            shop_id=int(_read("SHOPEE_DEFAULT_SHOP_ID")),
            page_size=5,
            item_status="NORMAL",
        )
        assert resp.ok, f"get_item_list falhou: HTTP={resp.status_code} {resp.text}"
        body = resp.json()
        assert body.get("error") in (None, ""), f"erro da API: {body}"
        assert isinstance(body.get("response", {}).get("item", []), list)