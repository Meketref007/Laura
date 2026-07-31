from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

from .api_usage_tracker import get_api_tracker
from .auth import sign_request, unix_timestamp
from .circuit_breaker import CircuitBreakerOpen, get_circuit_breaker_manager
from .config import ShopeeConfig
from .logger import debug, warning
from .logger import error as log_error
from .rate_limit import wait_for_rate_limit
from .retry import RETRY_NETWORK, retry
from .secrets_rotation import get_rotation_manager
from .tracing import get_trace_headers, get_tracer


@dataclass
class ShopeeResponse:
    status_code: int
    data: dict[str, Any]


def _record_api_usage(endpoint: str, status: int, elapsed: float) -> None:
    """Record API usage without ever breaking the API call itself."""
    try:
        get_api_tracker().record(endpoint, status=status, latency_ms=elapsed * 1000)
    except Exception:
        pass


class ShopeeClient:
    def __init__(self, config: ShopeeConfig, timeout_seconds: int = 30) -> None:
        self.config = config
        self.timeout_seconds = timeout_seconds

        # Register default tokens for lifecycle management
        rotation_manager = get_rotation_manager()
        if config.default_access_token:
            rotation_manager.register_token(
                "access_token",
                config.default_access_token,
                shop_id=config.default_shop_id
            )
        if config.default_refresh_token:
            rotation_manager.register_token(
                "refresh_token",
                config.default_refresh_token,
                shop_id=config.default_shop_id
            )

    def _request(
        self,
        path: str,
        method: str,
        *,
        payload: dict[str, Any] | None = None,
        form_data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        access_token: str | None = None,
        shop_id: int | None = None,
    ) -> ShopeeResponse:
        # Initialize distributed tracing
        tracer = get_tracer()
        trace_context = tracer.start_trace(
            endpoint=path,
            operation=f"{method} {path}"
        )

        start_time = time.time()
        debug("API request starting", method=method, path=path, shop_id=shop_id,
              correlation_id=trace_context.correlation_id)

        # Check circuit breaker before attempting request
        breaker_manager = get_circuit_breaker_manager()
        try:
            breaker = breaker_manager.get_or_create(path)
            # Verify circuit is not OPEN
            if breaker.state.value == "OPEN":
                elapsed_since_opened = time.time() - breaker.opened_at if breaker.opened_at else 0
                if elapsed_since_opened < breaker.config.timeout_seconds:
                    raise CircuitBreakerOpen(
                        f"Circuit breaker OPEN for {path} "
                        f"(opened {elapsed_since_opened:.0f}s ago, retry in {breaker.config.timeout_seconds - elapsed_since_opened:.0f}s)"
                    )
        except CircuitBreakerOpen as e:
            log_error("Request rejected by circuit breaker", path=path, error=str(e)[:100])
            tracer.end_span(trace_context, error=str(e)[:100])
            raise

        # Check rate limit - wait up to 10 seconds if needed
        if not wait_for_rate_limit(path, timeout_seconds=10.0):
            warning("Rate limit timeout", path=path, method=method)

        ts = unix_timestamp()
        sign = sign_request(
            partner_id=self.config.partner_id,
            partner_key=self.config.partner_key,
            path=path,
            timestamp=ts,
            access_token=access_token,
            shop_id=shop_id,
        )
        params: dict[str, Any] = {
            "partner_id": self.config.partner_id,
            "timestamp": ts,
            "sign": sign,
        }
        if access_token:
            params["access_token"] = access_token
        if shop_id is not None:
            params["shop_id"] = shop_id

        if query_params:
            params.update(query_params)

        # Add trace headers for request propagation
        trace_headers = get_trace_headers()

        request_kwargs: dict[str, Any] = {
            "params": params,
            "timeout": self.timeout_seconds,
            "headers": trace_headers,
        }
        upper_method = method.upper()
        if files is not None:
            request_kwargs["data"] = form_data or {}
            request_kwargs["files"] = files
        elif form_data is not None:
            request_kwargs["data"] = form_data
        elif upper_method != "GET":
            request_kwargs["json"] = payload

        try:
            response = requests.request(
                upper_method,
                f"{self.config.base_url}{path}",
                **request_kwargs,
            )
        except requests.RequestException as exc:
            elapsed = time.time() - start_time
            log_error("API request network error", method=method, path=path, elapsed_ms=int(elapsed*1000), error=str(exc))
            _record_api_usage(path, 0, elapsed)
            tracer.end_span(trace_context, error=str(exc)[:100])
            # Record failure in circuit breaker
            try:
                breaker = breaker_manager.get_or_create(path)
                breaker._record_failure()
            except Exception:
                pass  # Don't fail if circuit breaker update fails
            raise

        elapsed = time.time() - start_time
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # Record failure in circuit breaker
            try:
                breaker = breaker_manager.get_or_create(path)
                if response.status_code >= 500:  # Only count server errors
                    breaker._record_failure()
            except Exception:
                pass  # Don't fail if circuit breaker update fails

            # Muitos endpoints da Shopee retornam detalhes estruturados em JSON
            # mesmo com status HTTP de erro (4xx/5xx). Preservamos esses dados
            # para que a CLI trate e exiba mensagens consistentes.
            try:
                data = response.json()
                log_error("API request HTTP error", method=method, path=path, status_code=response.status_code, elapsed_ms=int(elapsed*1000))
            except Exception:
                log_error("API request HTTP error (no JSON)", method=method, path=path, status_code=response.status_code, elapsed_ms=int(elapsed*1000), body=response.text[:200])
                tracer.end_span(trace_context, error="HTTP %d" % response.status_code, status_code=response.status_code)
                _record_api_usage(path, response.status_code, elapsed)
                raise RuntimeError(
                    f"Shopee API error {response.status_code} on {path}: {response.text}"
                ) from exc
            tracer.end_span(trace_context, status_code=response.status_code)
            _record_api_usage(path, response.status_code, elapsed)
            return ShopeeResponse(status_code=response.status_code, data=data)

        # Record success in circuit breaker
        try:
            breaker = breaker_manager.get_or_create(path)
            breaker._record_success()
        except Exception:
            pass  # Don't fail if circuit breaker update fails

        data = response.json()
        debug("API request completed", method=method, path=path, status_code=response.status_code, elapsed_ms=int(elapsed*1000))
        _record_api_usage(path, response.status_code, elapsed)
        tracer.end_span(trace_context, status_code=response.status_code)
        return ShopeeResponse(status_code=response.status_code, data=data)

    @retry(config=RETRY_NETWORK, context="Shopee API endpoint call")
    def call_endpoint(
        self,
        path: str,
        method: str = "GET",
        *,
        payload: dict[str, Any] | None = None,
        query_params: dict[str, Any] | None = None,
        access_token: str | None = None,
        shop_id: int | None = None,
    ) -> ShopeeResponse:
        return self._request(
            path,
            method,
            payload=payload,
            query_params=query_params,
            access_token=access_token,
            shop_id=shop_id,
        )

    @retry(config=RETRY_NETWORK, context="Token exchange")
    def exchange_code_for_token(self, code: str, shop_id: int) -> ShopeeResponse:
        return self._request(
            "/api/v2/auth/token/get",
            "POST",
            payload={
                "code": code,
                "shop_id": shop_id,
                "partner_id": self.config.partner_id,
            },
        )

    @retry(config=RETRY_NETWORK, context="Token refresh")
    def refresh_token(self, refresh_token: str, shop_id: int) -> ShopeeResponse:
        return self._request(
            "/api/v2/auth/access_token/get",
            "POST",
            payload={
                "refresh_token": refresh_token,
                "shop_id": shop_id,
                "partner_id": self.config.partner_id,
            },
        )

    def get_shop_info(self, access_token: str, shop_id: int) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop/get_shop_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_item_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        offset: int = 0,
        page_size: int = 50,
        item_status: str = "NORMAL",
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "offset": offset,
                "page_size": page_size,
                "item_status": item_status,
            },
        )

    def get_item_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "item_id": item_id,
            },
        )

    def get_item_base_info(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_base_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "item_id": item_id,
            },
        )

    def get_item_variations(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_variations",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "item_id": item_id,
            },
        )

    def update_item_stock(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        stock: int,
        variation_id: int | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {
            "item_id": item_id,
            "stock": stock,
        }
        if variation_id is not None:
            payload["variation_id"] = variation_id

        return self._request(
            "/api/v2/product/update_stock",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_item_price(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        current_price: float,
        variation_id: int | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {
            "item_id": item_id,
            "current_price": current_price,
        }
        if variation_id is not None:
            payload["variation_id"] = variation_id

        return self._request(
            "/api/v2/product/update_price",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def send_chat_message(
        self,
        *,
        access_token: str,
        shop_id: int,
        buyer_id: str,
        message: str,
    ) -> ShopeeResponse:
        payload = {
            "buyer_id": buyer_id,
            "message": message,
        }
        return self._request(
            "/api/v2/chat/send_message",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_order_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        time_from: int,
        time_to: int,
        time_range_field: str = "create_time",
        page_size: int = 50,
        cursor: str = "",
        order_status: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {
            "time_range_field": time_range_field,
            "time_from": time_from,
            "time_to": time_to,
            "page_size": page_size,
        }
        if cursor:
            query["cursor"] = cursor
        if order_status:
            query["order_status"] = order_status

        return self._request(
            "/api/v2/order/get_order_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_order_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/order/get_order_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "order_sn_list": order_sn,
            },
        )

    def get_logistics_channel_list(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/logistics/get_channel_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_logistics_info(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        package_number: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"order_sn": order_sn}
        if package_number:
            query["package_number"] = package_number

        return self._request(
            "/api/v2/logistics/get_logistics_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_tracking_number(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        package_number: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"order_sn": order_sn}
        if package_number:
            query["package_number"] = package_number

        return self._request(
            "/api/v2/logistics/get_tracking_number",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def ship_order(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        logistics_channel_id: int | None = None,
        package_number: str | None = None,
        tracking_number: str | None = None,
        ship_time: int | None = None,
    ) -> ShopeeResponse:
        """Marcar pedido como enviado (shipping)."""
        payload: dict[str, Any] = {"order_sn": order_sn}
        if logistics_channel_id is not None:
            payload["logistics_channel_id"] = logistics_channel_id
        if package_number is not None:
            payload["package_number"] = package_number
        if tracking_number is not None:
            payload["tracking_number"] = tracking_number
        if ship_time is not None:
            payload["ship_time"] = ship_time

        return self._request(
            "/api/v2/logistics/ship_order",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )



    def get_escrow_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/get_escrow_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "order_sn": order_sn,
            },
        )

    def get_discount_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        discount_status: str = "all",
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/discount/get_discount_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "discount_status": discount_status,
            },
        )

    def get_voucher_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        status: str = "all",
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/voucher/get_voucher_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "status": status,
            },
        )

    def get_bundle_deal_list(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/bundle_deal/get_bundle_deal_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_add_on_deal_list(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/add_on_deal/get_add_on_deal_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def init_video_upload(
        self,
        *,
        access_token: str,
        shop_id: int,
        file_size: int,
        file_md5: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/media_space/init_video_upload",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload={
                "file_size": file_size,
                "file_md5": file_md5,
            },
        )

    def get_video_upload_result(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_upload_id: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/media_space/get_video_upload_result",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "video_upload_id": video_upload_id,
            },
        )

    def upload_video_part(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_upload_id: str,
        part_seq: int,
        content_md5: str,
        file_name: str,
        part_content: bytes,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/media_space/upload_video_part",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            form_data={
                "video_upload_id": video_upload_id,
                "part_seq": str(part_seq),
                "content_md5": content_md5,
            },
            files={
                "part_content": (file_name, part_content),
            },
        )

    def complete_video_upload(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_upload_id: str,
        part_seq_list: list[int],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/media_space/complete_video_upload",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload={
                "video_upload_id": video_upload_id,
                "part_seq_list": part_seq_list,
            },
        )

    # =====================================================================
    # REFUND MANAGEMENT ENDPOINTS
    # =====================================================================

    def get_return_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        time_from: int,
        time_to: int,
        page_size: int = 50,
        cursor: str = "",
        return_status: str = "",
    ) -> ShopeeResponse:
        """Listar devoluções/reembolsos."""
        query: dict[str, Any] = {
            "time_from": time_from,
            "time_to": time_to,
            "page_size": page_size,
        }
        if cursor:
            query["cursor"] = cursor
        if return_status:
            query["return_status"] = return_status

        return self._request(
            "/api/v2/returns/get_return_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_return_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        return_sn: str,
    ) -> ShopeeResponse:
        """Obter detalhes de uma devolução."""
        return self._request(
            "/api/v2/returns/get_return_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "return_sn": return_sn,
            },
        )

    def confirm_return(
        self,
        *,
        access_token: str,
        shop_id: int,
        return_sn: str,
        status: str,
    ) -> ShopeeResponse:
        """Confirmar/Processar devolução."""
        return self._request(
            "/api/v2/returns/confirm_return",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload={
                "return_sn": return_sn,
                "status": status,  # MERCHANT_ACCEPTED, MERCHANT_REJECTED
            },
        )

    def dispute_return(
        self,
        *,
        access_token: str,
        shop_id: int,
        return_sn: str,
        dispute_reason: str,
        evidence_image_urls: list[str] | None = None,
    ) -> ShopeeResponse:
        """Contestar uma devolução."""
        payload: dict[str, Any] = {
            "return_sn": return_sn,
            "dispute_reason": dispute_reason,
        }
        if evidence_image_urls:
            payload["evidence_image_urls"] = evidence_image_urls

        return self._request(
            "/api/v2/returns/dispute_return",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload=payload,
        )

    # =====================================================================
    # ADS MANAGEMENT (partial, prioritized)
    # =====================================================================

    def create_campaign(
        self,
        *,
        access_token: str,
        shop_id: int,
        campaign_name: str,
        budget: float | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {"campaign_name": campaign_name}
        if budget is not None:
            payload["budget"] = budget
        if start_time is not None:
            payload["start_time"] = start_time
        if end_time is not None:
            payload["end_time"] = end_time
        if extra:
            payload.update(extra)

        return self._request(
            "/api/v2/ads/create_campaign",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_campaign(
        self,
        *,
        access_token: str,
        shop_id: int,
        campaign_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"campaign_id": campaign_id}
        payload.update(updates)
        return self._request(
            "/api/v2/ads/update_campaign",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def create_ad_group(
        self,
        *,
        access_token: str,
        shop_id: int,
        campaign_id: int,
        ad_group_name: str,
        extra: dict[str, Any] | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {"campaign_id": campaign_id, "ad_group_name": ad_group_name}
        if extra:
            payload.update(extra)
        return self._request(
            "/api/v2/ads/create_ad_group",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_ad_group(
        self,
        *,
        access_token: str,
        shop_id: int,
        ad_group_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"ad_group_id": ad_group_id}
        payload.update(updates)
        return self._request(
            "/api/v2/ads/update_ad_group",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_ad_report(
        self,
        *,
        access_token: str,
        shop_id: int,
        report_type: str,
        time_from: int,
        time_to: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query = {
            "report_type": report_type,
            "time_from": time_from,
            "time_to": time_to,
            "page_size": page_size,
        }
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/ads/get_ad_report",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_campaign_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/ads/get_campaign_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # ACCOUNT HEALTH
    # =====================================================================

    def get_shop_performance(
        self,
        *,
        access_token: str,
        shop_id: int,
        time_from: int,
        time_to: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/account_health/get_shop_performance",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "time_from": time_from,
                "time_to": time_to,
            },
        )

    def get_item_performance(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        time_from: int,
        time_to: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_performance",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "item_id": item_id,
                "time_from": time_from,
                "time_to": time_to,
            },
        )

    # =====================================================================
    # SHOP FLASH SALE
    # =====================================================================

    def add_flash_sale(
        self,
        *,
        access_token: str,
        shop_id: int,
        flash_sale_name: str,
        start_time: int,
        end_time: int,
        items: list[dict[str, Any]],
    ) -> ShopeeResponse:
        payload = {
            "flash_sale_name": flash_sale_name,
            "start_time": start_time,
            "end_time": end_time,
            "items": items,
        }
        return self._request(
            "/api/v2/shop_flash_sale/add_flash_sale",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_flash_sale(
        self,
        *,
        access_token: str,
        shop_id: int,
        flash_sale_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"flash_sale_id": flash_sale_id}
        payload.update(updates)
        return self._request(
            "/api/v2/shop_flash_sale/update_flash_sale",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_flash_sale_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/shop_flash_sale/get_flash_sale_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # CHAT / MESSAGING
    # =====================================================================

    def get_chat_history(
        self,
        *,
        access_token: str,
        shop_id: int,
        conversation_id: str,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query = {"conversation_id": conversation_id, "page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/chat/get_history",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # TOP PICKS
    # =====================================================================

    def add_top_picks(
        self,
        *,
        access_token: str,
        shop_id: int,
        title: str,
        items: list[dict[str, Any]],
    ) -> ShopeeResponse:
        payload = {"title": title, "items": items}
        return self._request(
            "/api/v2/top_picks/add_top_picks",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_top_picks(
        self,
        *,
        access_token: str,
        shop_id: int,
        top_picks_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"top_picks_id": top_picks_id}
        payload.update(updates)
        return self._request(
            "/api/v2/top_picks/update_top_picks",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_top_picks_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/top_picks/get_top_picks_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # ACCOUNT HEALTH — COMPLETO
    # =====================================================================

    def get_penalty_point_history(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 10,
        page_no: int = 1,
        violation_type: int | None = None,
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size, "page_no": page_no}
        if violation_type is not None:
            query["violation_type"] = violation_type
        return self._request(
            "/api/v2/account_health/get_penalty_point_history",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_punishment_history(
        self,
        *,
        access_token: str,
        shop_id: int,
        punishment_status: int = 1,
        page_size: int = 10,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/account_health/get_punishment_history",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "punishment_status": punishment_status,
                "page_size": page_size,
                "page_no": page_no,
            },
        )

    def get_listings_with_issues(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 10,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/account_health/get_listings_with_issues",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"page_size": page_size, "page_no": page_no},
        )

    def get_late_orders(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 10,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/account_health/get_late_orders",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_metric_source_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        metric_id: int,
        page_size: int = 10,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/account_health/get_metric_source_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "metric_id": metric_id,
                "page_size": page_size,
                "page_no": page_no,
            },
        )

    # =====================================================================
    # PAYMENT — COMPLETO
    # =====================================================================

    def get_escrow_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        release_time_from: int,
        release_time_to: int,
        page_size: int = 40,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/get_escrow_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "release_time_from": release_time_from,
                "release_time_to": release_time_to,
                "page_size": page_size,
                "page_no": page_no,
            },
        )

    def get_escrow_detail_batch(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn_list: list[str],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/get_escrow_detail_batch",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload={"order_sn_list": order_sn_list},
        )

    def get_wallet_transaction_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        create_time_from: int,
        create_time_to: int,
        page_size: int = 40,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/get_wallet_transaction_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "create_time_from": create_time_from,
                "create_time_to": create_time_to,
                "page_size": page_size,
                "page_no": page_no,
            },
        )

    def generate_income_report(
        self,
        *,
        access_token: str,
        shop_id: int,
        start_time: int,
        end_time: int,
        currency: str = "BRL",
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/generate_income_report",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload={
                "start_time": start_time,
                "end_time": end_time,
                "currency": currency,
            },
        )

    def get_income_report(
        self,
        *,
        access_token: str,
        shop_id: int,
        income_report_id: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/get_income_report",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"income_report_id": income_report_id},
        )

    def get_payout_info(
        self,
        *,
        access_token: str,
        shop_id: int,
        payout_time_from: int,
        payout_time_to: int,
        page_size: int = 40,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/payment/get_payout_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "payout_time_from": payout_time_from,
                "payout_time_to": payout_time_to,
                "page_size": page_size,
                "page_no": page_no,
            },
        )

    # =====================================================================
    # SHOP — COMPLETO
    # =====================================================================

    def update_shop_profile(
        self,
        *,
        access_token: str,
        shop_id: int,
        shop_name: str | None = None,
        shop_logo: str | None = None,
        description: str | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {}
        if shop_name is not None:
            payload["shop_name"] = shop_name
        if shop_logo is not None:
            payload["shop_logo"] = shop_logo
        if description is not None:
            payload["description"] = description
        return self._request(
            "/api/v2/shop/update_profile",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_warehouse_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        warehouse_type: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop/get_warehouse_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"warehouse_type": warehouse_type},
        )

    def get_shop_notification(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 10,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/shop/get_shop_notification",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_authorised_reseller_brand(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_no: int = 1,
        page_size: int = 10,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop/get_authorised_reseller_brand",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"page_no": page_no, "page_size": page_size},
        )

    def get_shop_holiday_mode(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop/get_shop_holiday_mode",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def set_shop_holiday_mode(
        self,
        *,
        access_token: str,
        shop_id: int,
        holiday_mode_on: bool,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop/set_shop_holiday_mode",
            "POST",
            access_token=access_token,
            shop_id=shop_id,
            payload={"holiday_mode_on": holiday_mode_on},
        )

    def get_br_shop_onboarding_info(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop/get_br_shop_onboarding_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # PRODUCT — COMPLETO
    # =====================================================================

    def add_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_name: str,
        description: str,
        category_id: int,
        price: float,
        stock: int,
        weight: float | None = None,
        image_id_list: list[str] | None = None,
        logistic_info: list[dict[str, Any]] | None = None,
        attribute_list: list[dict[str, Any]] | None = None,
        dimension: dict[str, Any] | None = None,
        item_sku: str | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {
            "item_name": item_name,
            "description": description,
            "category_id": category_id,
            "price": price,
            "stock": stock,
        }
        if weight is not None:
            payload["weight"] = weight
        if image_id_list is not None:
            payload["image"] = {"image_id_list": image_id_list}
        if logistic_info is not None:
            payload["logistic_info"] = logistic_info
        if attribute_list is not None:
            payload["attribute_list"] = attribute_list
        if dimension is not None:
            payload["dimension"] = dimension
        if item_sku is not None:
            payload["item_sku"] = item_sku
        return self._request(
            "/api/v2/product/add_item",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        item_name: str | None = None,
        description: str | None = None,
        price: float | None = None,
        stock: int | None = None,
        image_id_list: list[str] | None = None,
        attribute_list: list[dict[str, Any]] | None = None,
        item_sku: str | None = None,
        days_to_ship: int | None = None,
        is_pre_order: bool | None = None,
        category_id: int | None = None,
        brand: dict[str, Any] | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {"item_id": item_id}
        if item_name is not None:
            payload["item_name"] = item_name
        if description is not None:
            payload["description"] = description
        if price is not None:
            payload["price"] = price
        if stock is not None:
            payload["stock"] = stock
        if image_id_list is not None:
            payload["image"] = {"image_id_list": image_id_list}
        if attribute_list is not None:
            payload["attribute_list"] = attribute_list
        if item_sku is not None:
            payload["item_sku"] = item_sku
        if category_id is not None:
            payload["category_id"] = category_id
        if brand is not None:
            payload["brand"] = brand
        if days_to_ship is not None or is_pre_order is not None:
            pre_order: dict[str, Any] = {}
            if days_to_ship is not None:
                pre_order["days_to_ship"] = days_to_ship
            if is_pre_order is not None:
                pre_order["is_pre_order"] = is_pre_order
            payload["pre_order"] = pre_order
        return self._request(
            "/api/v2/product/update_item",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def delete_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/delete_item",
            "POST",
            payload={"item_id": item_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    def unlist_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        unlist: bool = True,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/unlist_item",
            "POST",
            payload={"item_id": item_id, "unlist": unlist},
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_category(
        self,
        *,
        access_token: str,
        shop_id: int,
        language: str = "pt-br",
        parent_category_id: int | None = None,
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"language": language}
        if parent_category_id is not None:
            query["parent_category_id"] = parent_category_id
        return self._request(
            "/api/v2/product/get_category",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_attribute_tree(
        self,
        *,
        access_token: str,
        shop_id: int,
        category_id: int,
        language: str = "pt-br",
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_attribute_tree",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"category_id": category_id, "language": language},
        )

    def get_brand_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        category_id: int,
        offset: int = 0,
        page_size: int = 50,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_brand_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "category_id": category_id,
                "offset": offset,
                "page_size": page_size,
            },
        )

    def get_comment(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        page_size: int = 20,
        comment_id: int = 0,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_comment",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "item_id": item_id,
                "page_size": page_size,
                "comment_id": comment_id,
            },
        )

    def reply_comment(
        self,
        *,
        access_token: str,
        shop_id: int,
        comment_id: int,
        comment: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/reply_comment",
            "POST",
            payload={"comment_id": comment_id, "comment": comment},
            access_token=access_token,
            shop_id=shop_id,
        )

    def boost_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id_list: list[int],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/boost_item",
            "POST",
            payload={"item_id_list": item_id_list},
            access_token=access_token,
            shop_id=shop_id,
        )

    def search_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_name: str,
        offset: int = 0,
        page_size: int = 20,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/search_item",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={
                "item_name": item_name,
                "offset": offset,
                "page_size": page_size,
            },
        )

    def get_item_extra_info(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id_list: list[int],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_extra_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"item_id_list": ",".join(str(i) for i in item_id_list)},
        )

    def get_item_limit(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_limit",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_item_promotion(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id_list: list[int],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_promotion",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"item_id_list": ",".join(str(i) for i in item_id_list)},
        )

    def get_item_violation_info(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/product/get_item_violation_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"item_id": item_id},
        )

    # =====================================================================
    # VOUCHER — COMPLETO
    # =====================================================================

    def add_voucher(
        self,
        *,
        access_token: str,
        shop_id: int,
        voucher_name: str,
        voucher_type: int,
        value: float,
        usage_quantity: int,
        start_time: int,
        end_time: int,
        min_spend: float | None = None,
        discount_percentage: float | None = None,
        cap: float | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {
            "voucher_name": voucher_name,
            "voucher_type": voucher_type,
            "value": value,
            "usage_quantity": usage_quantity,
            "start_time": start_time,
            "end_time": end_time,
        }
        if min_spend is not None:
            payload["min_spend"] = min_spend
        if discount_percentage is not None:
            payload["discount_percentage"] = discount_percentage
        if cap is not None:
            payload["cap"] = cap
        return self._request(
            "/api/v2/voucher/add_voucher",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_voucher(
        self,
        *,
        access_token: str,
        shop_id: int,
        voucher_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"voucher_id": voucher_id}
        payload.update(updates)
        return self._request(
            "/api/v2/voucher/update_voucher",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def delete_voucher(
        self,
        *,
        access_token: str,
        shop_id: int,
        voucher_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/voucher/delete_voucher",
            "POST",
            payload={"voucher_id": voucher_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # DISCOUNT — COMPLETO
    # =====================================================================

    def add_discount(
        self,
        *,
        access_token: str,
        shop_id: int,
        discount_name: str,
        start_time: int,
        end_time: int,
        items: list[dict[str, Any]],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/discount/add_discount",
            "POST",
            payload={
                "discount_name": discount_name,
                "start_time": start_time,
                "end_time": end_time,
                "items": items,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_discount(
        self,
        *,
        access_token: str,
        shop_id: int,
        discount_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"discount_id": discount_id}
        payload.update(updates)
        return self._request(
            "/api/v2/discount/update_discount",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def add_discount_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        discount_id: int,
        item_list: list[dict[str, Any]],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/discount/add_discount_item",
            "POST",
            payload={"discount_id": discount_id, "item_list": item_list},
            access_token=access_token,
            shop_id=shop_id,
        )

    def remove_discount_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        discount_id: int,
        item_id_list: list[int],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/discount/remove_discount_item",
            "POST",
            payload={"discount_id": discount_id, "item_id_list": item_id_list},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # BUNDLE DEAL — COMPLETO
    # =====================================================================

    def add_bundle_deal(
        self,
        *,
        access_token: str,
        shop_id: int,
        bundle_name: str,
        start_time: int,
        end_time: int,
        items: list[dict[str, Any]],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/bundle_deal/add_bundle_deal",
            "POST",
            payload={
                "bundle_name": bundle_name,
                "start_time": start_time,
                "end_time": end_time,
                "items": items,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_bundle_deal(
        self,
        *,
        access_token: str,
        shop_id: int,
        bundle_deal_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"bundle_deal_id": bundle_deal_id}
        payload.update(updates)
        return self._request(
            "/api/v2/bundle_deal/update_bundle_deal",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def delete_bundle_deal(
        self,
        *,
        access_token: str,
        shop_id: int,
        bundle_deal_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/bundle_deal/delete_bundle_deal",
            "POST",
            payload={"bundle_deal_id": bundle_deal_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # ADD-ON DEAL — COMPLETO
    # =====================================================================

    def add_add_on_deal(
        self,
        *,
        access_token: str,
        shop_id: int,
        add_on_deal_name: str,
        start_time: int,
        end_time: int,
        items: list[dict[str, Any]],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/add_on_deal/add_add_on_deal",
            "POST",
            payload={
                "add_on_deal_name": add_on_deal_name,
                "start_time": start_time,
                "end_time": end_time,
                "items": items,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_add_on_deal(
        self,
        *,
        access_token: str,
        shop_id: int,
        add_on_deal_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"add_on_deal_id": add_on_deal_id}
        payload.update(updates)
        return self._request(
            "/api/v2/add_on_deal/update_add_on_deal",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # CHAT — COMPLETO
    # =====================================================================

    def get_conversation_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/chat/get_conversation_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def pin_conversation(
        self,
        *,
        access_token: str,
        shop_id: int,
        conversation_id: str,
        pin: bool = True,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/chat/pin_conversation",
            "POST",
            payload={"conversation_id": conversation_id, "pin": pin},
            access_token=access_token,
            shop_id=shop_id,
        )

    def read_conversation(
        self,
        *,
        access_token: str,
        shop_id: int,
        conversation_id: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/chat/read_conversation",
            "POST",
            payload={"conversation_id": conversation_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # AMS (AFFILIATE MARKETING SOLUTIONS)
    # =====================================================================

    def get_ams_campaign_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/ams/get_campaign_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def get_ams_report(
        self,
        *,
        access_token: str,
        shop_id: int,
        report_type: str,
        time_from: int,
        time_to: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {
            "report_type": report_type,
            "time_from": time_from,
            "time_to": time_to,
            "page_size": page_size,
        }
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/ams/get_report",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # PUSH (WEBHOOKS)
    # =====================================================================

    def get_push_config(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/push/get_push_config",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def set_push_config(
        self,
        *,
        access_token: str,
        shop_id: int,
        callback_url: str,
        interest_list: list[str] | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {"callback_url": callback_url}
        if interest_list is not None:
            payload["interest_list"] = interest_list
        return self._request(
            "/api/v2/push/set_push_config",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # MERCHANT
    # =====================================================================

    def get_merchant_info(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/merchant/get_merchant_info",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_shop_list_by_merchant(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/merchant/get_shop_list_by_merchant",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # FIRST MILE LOGISTICS
    # =====================================================================

    def get_first_mile_tracking_number(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/first_mile/get_tracking_number",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"order_sn": order_sn},
        )

    def get_first_mile_waybill(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/first_mile/get_waybill",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"order_sn": order_sn},
        )

    # =====================================================================
    # LIVESTREAM
    # =====================================================================

    def create_livestream_session(
        self,
        *,
        access_token: str,
        shop_id: int,
        session_name: str,
        start_time: int,
        end_time: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/livestream/create_session",
            "POST",
            payload={
                "session_name": session_name,
                "start_time": start_time,
                "end_time": end_time,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_livestream_session_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/livestream/get_session_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # VIDEO
    # =====================================================================

    def get_video_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/video/get_video_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def delete_video(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/video/delete_video",
            "POST",
            payload={"video_id": video_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # FBS (FULFILLMENT BY SHOPEE)
    # =====================================================================

    def get_fbs_order_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/fbs/get_order_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # MEDIA — UPLOAD IMAGE
    # =====================================================================

    def upload_image(
        self,
        *,
        access_token: str,
        shop_id: int,
        image_url: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/media/upload_image",
            "POST",
            payload={"image_url": image_url},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # FOLLOW PRIZE
    # =====================================================================

    def add_follow_prize(
        self,
        *,
        access_token: str,
        shop_id: int,
        follow_prize_name: str,
        start_time: int,
        end_time: int,
        items: list[dict[str, Any]],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/follow_prize/add_follow_prize",
            "POST",
            payload={
                "follow_prize_name": follow_prize_name,
                "start_time": start_time,
                "end_time": end_time,
                "items": items,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_follow_prize(
        self,
        *,
        access_token: str,
        shop_id: int,
        follow_prize_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"follow_prize_id": follow_prize_id}
        payload.update(updates)
        return self._request(
            "/api/v2/follow_prize/update_follow_prize",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_follow_prize_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/follow_prize/get_follow_prize_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def delete_follow_prize(
        self,
        *,
        access_token: str,
        shop_id: int,
        follow_prize_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/follow_prize/delete_follow_prize",
            "POST",
            payload={"follow_prize_id": follow_prize_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # SHOP CATEGORY
    # =====================================================================

    def add_shop_category(
        self,
        *,
        access_token: str,
        shop_id: int,
        category_name: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop_category/add_shop_category",
            "POST",
            payload={"category_name": category_name},
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_shop_category(
        self,
        *,
        access_token: str,
        shop_id: int,
        category_id: int,
        category_name: str | None = None,
        sort_weight: int | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {"category_id": category_id}
        if category_name is not None:
            payload["category_name"] = category_name
        if sort_weight is not None:
            payload["sort_weight"] = sort_weight
        return self._request(
            "/api/v2/shop_category/update_shop_category",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def delete_shop_category(
        self,
        *,
        access_token: str,
        shop_id: int,
        category_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/shop_category/delete_shop_category",
            "POST",
            payload={"category_id": category_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_shop_category_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/shop_category/get_shop_category_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    # =====================================================================
    # PUBLIC (NO AUTH)
    # =====================================================================

    def get_shops_by_partner(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        page_no: int = 1,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/public/get_shops_by_partner",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"page_size": page_size, "page_no": page_no},
        )

    def get_public_categories(
        self,
        *,
        language: str = "pt-br",
        version: int = 2,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/public/get_category",
            "GET",
            query_params={"language": language, "version": version},
        )

    # =====================================================================
    # ORDER — COMPLETO
    # =====================================================================

    def split_order(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        package_list: list[dict[str, Any]],
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/order/split_order",
            "POST",
            payload={"order_sn": order_sn, "package_list": package_list},
            access_token=access_token,
            shop_id=shop_id,
        )

    def cancel_order(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        cancel_reason: str,
        item_list: list[dict[str, Any]] | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {
            "order_sn": order_sn,
            "cancel_reason": cancel_reason,
        }
        if item_list is not None:
            payload["item_list"] = item_list
        return self._request(
            "/api/v2/order/cancel_order",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_order_address(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/order/get_order_address",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"order_sn": order_sn},
        )

    # =====================================================================
    # LOGISTICS — COMPLETO
    # =====================================================================

    def get_shipping_parameter(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/logistics/get_shipping_parameter",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"order_sn": order_sn},
        )

    def get_tracking_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/logistics/get_tracking_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"order_sn": order_sn},
        )

    def get_waybill(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        package_number: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/logistics/get_waybill",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"order_sn": order_sn, "package_number": package_number},
        )

    def get_address_list(
        self,
        *,
        access_token: str,
        shop_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/logistics/get_address_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # FBS — COMPLETO
    # =====================================================================

    def confirm_fbs_order(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/fbs/confirm_order",
            "POST",
            payload={"order_sn": order_sn},
            access_token=access_token,
            shop_id=shop_id,
        )

    def ship_fbs_order(
        self,
        *,
        access_token: str,
        shop_id: int,
        order_sn: str,
        tracking_number: str,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/fbs/ship_order",
            "POST",
            payload={"order_sn": order_sn, "tracking_number": tracking_number},
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # LIVESTREAM — COMPLETO
    # =====================================================================

    def update_livestream_session(
        self,
        *,
        access_token: str,
        shop_id: int,
        session_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"session_id": session_id}
        payload.update(updates)
        return self._request(
            "/api/v2/livestream/update_session",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def delete_livestream_session(
        self,
        *,
        access_token: str,
        shop_id: int,
        session_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/livestream/delete_session",
            "POST",
            payload={"session_id": session_id},
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_livestream_session_metrics(
        self,
        *,
        access_token: str,
        shop_id: int,
        session_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/livestream/get_session_metrics",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"session_id": session_id},
        )

    # =====================================================================
    # VIDEO — COMPLETO
    # =====================================================================

    def post_video(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_name: str,
        video_url: str,
        video_description: str = "",
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {
            "video_name": video_name,
            "video_url": video_url,
        }
        if video_description:
            payload["video_description"] = video_description
        return self._request(
            "/api/v2/video/post_video",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_video(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"video_id": video_id}
        payload.update(updates)
        return self._request(
            "/api/v2/video/update_video",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_video_analytics(
        self,
        *,
        access_token: str,
        shop_id: int,
        video_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/video/get_video_analytics",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"video_id": video_id},
        )

    # =====================================================================
    # AMS — COMPLETO
    # =====================================================================

    def create_ams_campaign(
        self,
        *,
        access_token: str,
        shop_id: int,
        campaign_name: str,
        budget: float,
        start_time: int,
        end_time: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/ams/create_campaign",
            "POST",
            payload={
                "campaign_name": campaign_name,
                "budget": budget,
                "start_time": start_time,
                "end_time": end_time,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def update_ams_campaign(
        self,
        *,
        access_token: str,
        shop_id: int,
        campaign_id: int,
        updates: dict[str, Any],
    ) -> ShopeeResponse:
        payload = {"campaign_id": campaign_id}
        payload.update(updates)
        return self._request(
            "/api/v2/ams/update_campaign",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # SBS (SHOPEE BUSINESS SERVICES / WAREHOUSE)
    # =====================================================================

    def get_sbs_inventory(
        self,
        *,
        access_token: str,
        shop_id: int,
        page_size: int = 50,
        cursor: str = "",
    ) -> ShopeeResponse:
        query: dict[str, Any] = {"page_size": page_size}
        if cursor:
            query["cursor"] = cursor
        return self._request(
            "/api/v2/sbs/get_inventory",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params=query,
        )

    def update_sbs_inventory(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        model_id: int | None = None,
        quantity: int = 0,
    ) -> ShopeeResponse:
        payload: dict[str, Any] = {"item_id": item_id, "quantity": quantity}
        if model_id is not None:
            payload["model_id"] = model_id
        return self._request(
            "/api/v2/sbs/update_inventory",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    # =====================================================================
    # GLOBAL PRODUCT
    # =====================================================================

    def get_global_item_list(
        self,
        *,
        access_token: str,
        shop_id: int,
        offset: int = 0,
        page_size: int = 50,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/global_product/get_global_item_list",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"offset": offset, "page_size": page_size},
        )

    def add_global_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_name: str,
        description: str,
        category_id: int,
        price: float,
        stock: int,
        weight: float,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/global_product/add_global_item",
            "POST",
            payload={
                "item_name": item_name,
                "description": description,
                "category_id": category_id,
                "price": price,
                "stock": stock,
                "weight": weight,
            },
            access_token=access_token,
            shop_id=shop_id,
        )

    def get_global_item_detail(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/global_product/get_global_item_detail",
            "GET",
            access_token=access_token,
            shop_id=shop_id,
            query_params={"item_id": item_id},
        )

    def update_global_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
        item_name: str | None = None,
        description: str | None = None,
        price: float | None = None,
        stock: int | None = None,
        weight: float | None = None,
    ) -> ShopeeResponse:
        payload: dict[str, object] = {"item_id": item_id}
        if item_name is not None:
            payload["item_name"] = item_name
        if description is not None:
            payload["description"] = description
        if price is not None:
            payload["price"] = price
        if stock is not None:
            payload["stock"] = stock
        if weight is not None:
            payload["weight"] = weight
        return self._request(
            "/api/v2/global_product/update_global_item",
            "POST",
            payload=payload,
            access_token=access_token,
            shop_id=shop_id,
        )

    def delete_global_item(
        self,
        *,
        access_token: str,
        shop_id: int,
        item_id: int,
    ) -> ShopeeResponse:
        return self._request(
            "/api/v2/global_product/delete_global_item",
            "POST",
            payload={"item_id": item_id},
            access_token=access_token,
            shop_id=shop_id,
        )
