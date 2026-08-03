"""Extensible provider contract for zone/DNS-hosting sources (e.g. Cloudflare)."""

from abc import ABC, abstractmethod

from models import DNSRecord


class DomainProvider(ABC):
    """Contract implemented by Cloudflare and future zone/DNS-hosting providers.

    Registrar-only providers (e.g. GoDaddy), which have no zones, SSL, or
    billing concepts, are integrated directly in inventory_builder.py instead
    of forcing them through this zone-shaped contract.
    """

    name: str

    @abstractmethod
    def authenticate(self) -> bool: ...

    @abstractmethod
    def list_domains(self) -> list[dict]: ...

    @abstractmethod
    def get_dns_records(self, domain_id: str) -> list[DNSRecord]: ...

    @abstractmethod
    def get_domain_security(self, domain_id: str) -> tuple[str, str, dict[str, str]]: ...

    @abstractmethod
    def get_account_name(self, domain: dict) -> str: ...

    @abstractmethod
    def get_certificates(self, domain_id: str) -> list[dict]: ...

    @abstractmethod
    def get_account_services(self, account_id: str) -> list[dict]: ...
