"""Cloudflare implementation of the provider contract.

Author: Sagar Saitwal
"""

import logging

from cloudflare_api import CloudflareAPI
from config import Settings
from models import DNSRecord
from providers.base import DomainProvider


class CloudflareProvider(DomainProvider):
    name = "Cloudflare"

    def __init__(self, settings: Settings, logger: logging.Logger) -> None:
        self.client = CloudflareAPI(settings, logger)

    def authenticate(self) -> bool:
        return self.client.verify_token()

    def list_domains(self) -> list[dict]:
        return self.client.get_all_zones()

    def get_dns_records(self, domain_id: str) -> list[DNSRecord]:
        return self.client.get_dns_records(domain_id)

    def get_domain_security(self, domain_id: str) -> tuple[str, str, dict[str, str]]:
        return self.client.get_ssl_mode(domain_id), self.client.get_dnssec(domain_id), self.client.get_zone_settings(domain_id)

    def get_account_name(self, domain: dict) -> str:
        return domain.get("account", {}).get("name", "")

    def get_certificates(self, domain_id: str) -> list[dict]:
        return self.client.get_certificate_packs(domain_id)

    def get_account_services(self, account_id: str) -> list[dict]:
        return self.client.get_account_subscriptions(account_id)
