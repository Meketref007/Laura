"""Tests for the Shopee endpoint catalog."""

import pytest
from shopee_agent.endpoints import (
    ENDPOINT_CATALOG,
    ENDPOINT_FAMILIES,
    get_endpoints_by_family,
    search_endpoints,
    list_families,
    list_endpoint_families,
)


def test_endpoint_catalog_size():
    assert len(ENDPOINT_CATALOG) >= 100


def test_get_endpoints_by_family():
    auth_eps = get_endpoints_by_family("Auth")
    assert len(auth_eps) >= 2
    names = [ep["name"] for ep in auth_eps]
    assert "exchange_code_for_token" in names
    assert "refresh_token" in names
    assert get_endpoints_by_family("NonExistent") == []


def test_search_endpoints():
    results = search_endpoints("order")
    assert len(results) >= 1
    for ep in results:
        assert "order" in ep["name"].lower() or "order" in ep["description"].lower()


def test_list_families():
    families = list_families()
    assert "Auth" in families
    assert "Product" in families
    assert "Order" in families
    assert len(families) >= 15


def test_endpoint_families_consistency():
    all_families_in_catalog = set(ep["family"] for ep in ENDPOINT_CATALOG)
    assert set(ENDPOINT_FAMILIES.keys()) == all_families_in_catalog
    total_in_families = sum(len(v) for v in ENDPOINT_FAMILIES.values())
    assert total_in_families == len(ENDPOINT_CATALOG)
    from shopee_agent.endpoints import FAMILY_DESCRIPTIONS
    for family in all_families_in_catalog:
        assert family in FAMILY_DESCRIPTIONS, f"Missing description for {family}"
