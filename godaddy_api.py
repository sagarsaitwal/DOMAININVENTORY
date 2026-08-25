"""Resilient read-only client for GoDaddy Domains and DNS APIs.

Author: Sagar Saitwal
"""

import logging
from datetime import datetime
from typing import Any

import requests
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Settings
from models import DNSRecord

truststore.inject_into_ssl()


class GoDaddyAPI:
    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.base_url, self.timeout, self.logger = settings.godaddy_api_base_url, settings.godaddy_timeout_seconds, logger
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"sso-key {settings.godaddy_api_key}:{settings.godaddy_api_secret}", "Accept": "application/json"})
        retries = Retry(total=settings.godaddy_retries, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",), raise_on_status=False)
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.logger.info("GoDaddy GET %s", path)
        response = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def authenticate(self) -> bool:
        try:
            self.list_domains()
            return True
        except (requests.RequestException, ValueError) as exc:
            self.logger.exception("GoDaddy authentication failed: %s", exc)
            return False

    def list_domains(self) -> list[dict]:
        domains, offset, limit = [], 0, 100
        while True:
            page = self._get("/v1/domains", {"limit": limit, "offset": offset})
            if not page:
                return domains
            domains.extend(page)
            if len(page) < limit:
                return domains
            offset += limit

    def get_domain(self, domain: str) -> dict:
        return self._get(f"/v1/domains/{domain}")

    def get_dns_records(self, domain: str) -> list[DNSRecord]:
        try:
            records = self._get(f"/v1/domains/{domain}/records")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                self.logger.info("No GoDaddy-managed DNS zone for %s", domain)
                return []
            raise
        return [DNSRecord(name=item.get("name", "@"), type=item.get("type", ""), content=item.get("data", ""), ttl=item.get("ttl"), priority=item.get("priority")) for item in records]

    @staticmethod
    def parse_date(value: str | None):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date() if value else None
