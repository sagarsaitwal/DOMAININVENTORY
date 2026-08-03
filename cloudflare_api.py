"""Resilient Cloudflare v4 API client."""

import logging
from typing import Any

import requests
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Settings
from models import DNSRecord

truststore.inject_into_ssl()


class CloudflareAPI:
    BASE_URL = "https://api.cloudflare.com/client/v4"
    SETTING_KEYS = ("always_use_https", "min_tls_version", "tls_1_3", "http3", "hsts", "opportunistic_encryption", "brotli", "ipv6", "automatic_https_rewrites", "development_mode")

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.logger = logger
        self.timeout = settings.cloudflare_timeout_seconds
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {settings.cloudflare_api_token}", "Content-Type": "application/json"})
        retry = Retry(total=settings.cloudflare_retries, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.BASE_URL}{path}"
        self.logger.info("Cloudflare GET %s", path)
        response = self.session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success", False):
            errors = payload.get("errors", [])
            raise RuntimeError(f"Cloudflare API error: {errors}")
        return payload.get("result")

    def verify_token(self) -> bool:
        try:
            self._get("/user/tokens/verify")
            return True
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            self.logger.exception("Cloudflare authentication failed: %s", exc)
            return False

    def _paginated(self, path: str, per_page: int) -> list[dict]:
        results: list[dict] = []
        page = 1
        while True:
            batch = self._get(path, {"page": page, "per_page": per_page})
            if not batch:
                return results
            results.extend(batch)
            if len(batch) < per_page:
                return results
            page += 1

    def get_all_zones(self) -> list[dict]:
        return self._paginated("/zones", 50)

    def get_dns_records(self, zone_id: str) -> list[DNSRecord]:
        return [DNSRecord(name=item.get("name", ""), type=item.get("type", ""), content=item.get("content", ""), proxied=item.get("proxied", False), ttl=item.get("ttl"), priority=item.get("priority"), comment=item.get("comment") or "") for item in self._paginated(f"/zones/{zone_id}/dns_records", 100)]

    def get_ssl_mode(self, zone_id: str) -> str:
        result = self._get(f"/zones/{zone_id}/settings/ssl")
        return result.get("value", "") if result else ""

    def get_dnssec(self, zone_id: str) -> str:
        result = self._get(f"/zones/{zone_id}/dnssec")
        return result.get("status", "disabled") if result else "disabled"

    def get_zone_settings(self, zone_id: str) -> dict[str, str]:
        try:
            values = self._get(f"/zones/{zone_id}/settings") or []
            raw = {item.get("id"): str(item.get("value", "")) for item in values}
            return {key: raw.get(key, "") for key in self.SETTING_KEYS}
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            self.logger.warning("Could not retrieve settings for %s: %s", zone_id, exc)
            return {key: "" for key in self.SETTING_KEYS}

    def get_certificate_packs(self, zone_id: str) -> list[dict]:
        """Return SSL certificate packs, including certificate expiry dates."""
        return self._paginated(f"/zones/{zone_id}/ssl/certificate_packs", 50)

    def get_account_subscriptions(self, account_id: str) -> list[dict]:
        """Return billable account subscriptions and their next renewal dates."""
        return self._paginated(f"/accounts/{account_id}/subscriptions", 50)
