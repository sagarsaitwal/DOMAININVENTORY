"""Typed models shared by providers, inventory building, and reporting.

Author: Sagar Saitwal
"""

from dataclasses import dataclass, field
from datetime import date


@dataclass(slots=True)
class DNSRecord:
    name: str
    type: str
    content: str
    proxied: bool = False
    ttl: int | None = None
    priority: int | None = None
    comment: str = ""


@dataclass(slots=True)
class DomainAsset:
    domain: str
    source: str = ""
    zone_id: str = ""
    plan: str = ""
    status: str = ""
    ssl_mode: str = ""
    dnssec: str = ""
    nameservers: list[str] = field(default_factory=list)
    dns_records: list[DNSRecord] = field(default_factory=list)
    dns_record_count: int = 0
    registrar: str = ""
    expiry_date: date | None = None
    days_left: int | None = None
    auto_renew: bool | None = None
    privacy_protection: bool | None = None
    domain_lock: bool | None = None
    dns_provider: str = ""
    generated_on: str = ""
    account_name: str = ""
    zone_settings: dict[str, str] = field(default_factory=dict)
    health_score: int | None = None
    health_status: str = ""


@dataclass(slots=True)
class CertificateAsset:
    domain: str
    account_name: str = ""
    pack_id: str = ""
    certificate_id: str = ""
    certificate_type: str = ""
    status: str = ""
    issuer: str = ""
    hosts: list[str] = field(default_factory=list)
    expiry_date: date | None = None
    days_left: int | None = None


@dataclass(slots=True)
class ServiceAsset:
    account_id: str
    account_name: str = ""
    subscription_id: str = ""
    service_name: str = ""
    scope: str = ""
    status: str = ""
    renewal_date: date | None = None
    days_left: int | None = None
    frequency: str = ""
    price: float | None = None
    currency: str = ""


@dataclass(slots=True)
class RDAPData:
    registrar: str = ""
    expiry_date: date | None = None


@dataclass(slots=True)
class RenewalItem:
    """One expiring asset, normalised across domains, certificates, and services."""

    asset_type: str
    name: str
    detail: str = ""
    account: str = ""
    expires: date | None = None
    days_left: int | None = None
    handling: str = ""


@dataclass(slots=True)
class InventoryResult:
    assets: list[DomainAsset] = field(default_factory=list)
    certificates: list[CertificateAsset] = field(default_factory=list)
    services: list[ServiceAsset] = field(default_factory=list)
    failed_domains: list[str] = field(default_factory=list)

    @property
    def dns_record_count(self) -> int:
        return sum(asset.dns_record_count for asset in self.assets)

    def extend(self, other: "InventoryResult") -> None:
        """Fold another provider's results into this one."""
        self.assets.extend(other.assets)
        self.certificates.extend(other.certificates)
        self.services.extend(other.services)
        self.failed_domains.extend(other.failed_domains)
