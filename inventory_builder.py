"""Orchestrates provider data into a unified, reportable inventory."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone

from config import Settings
from godaddy_api import GoDaddyAPI
from models import CertificateAsset, DomainAsset, InventoryResult, ServiceAsset
from providers.base import DomainProvider
from rdap_lookup import RDAPLookup


class CloudflareInventoryBuilder:
    """Builds zone-based inventory (DNS, SSL, DNSSEC, certificates, billing) from Cloudflare."""

    def __init__(self, provider: DomainProvider, settings: Settings, logger: logging.Logger) -> None:
        self.provider, self.logger = provider, logger
        self.rdap = RDAPLookup(settings.rdap_timeout_seconds, logger)

    def build(self) -> InventoryResult:
        result = InventoryResult()
        try:
            zones = self.provider.list_domains()
        except Exception as exc:
            self.logger.exception("Unable to list domains: %s", exc)
            return result
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        accounts: dict[str, str] = {}
        for zone in zones:
            domain = zone.get("name", zone.get("id", "unknown"))
            try:
                records = self.provider.get_dns_records(zone["id"])
                ssl_mode, dnssec, zone_settings = self.provider.get_domain_security(zone["id"])
                rdap = self.rdap.lookup(domain)
                days_left = (rdap.expiry_date - date.today()).days if rdap.expiry_date else None
                asset = DomainAsset(domain=domain, source=self.provider.name, zone_id=zone["id"], plan=zone.get("plan", {}).get("name", ""), status=zone.get("status", ""), ssl_mode=ssl_mode, dnssec=dnssec, nameservers=zone.get("name_servers", []), dns_records=records, dns_record_count=len(records), registrar=rdap.registrar, expiry_date=rdap.expiry_date, days_left=days_left, dns_provider=self.provider.name, generated_on=stamp, account_name=self.provider.get_account_name(zone), zone_settings=zone_settings)
                asset.health_score, asset.health_status = self._health(asset)
                result.assets.append(asset)
                account = zone.get("account", {})
                if account.get("id"):
                    accounts[account["id"]] = account.get("name", "")
                result.certificates.extend(self._certificate_assets(domain, asset.account_name, zone["id"]))
            except Exception as exc:
                self.logger.exception("Failed to process %s: %s", domain, exc)
                result.failed_domains.append(domain)
        for account_id, account_name in accounts.items():
            result.services.extend(self._service_assets(account_id, account_name))
        return result

    def _certificate_assets(self, domain: str, account_name: str, zone_id: str) -> list[CertificateAsset]:
        try:
            packs = self.provider.get_certificates(zone_id)
        except Exception as exc:
            self.logger.warning("Could not retrieve SSL certificates for %s: %s", domain, exc)
            return []
        assets: list[CertificateAsset] = []
        for pack in packs:
            for certificate in pack.get("certificates", []):
                expiry_date = self._parse_api_date(certificate.get("expires_on"))
                assets.append(CertificateAsset(domain=domain, account_name=account_name, pack_id=pack.get("id", ""), certificate_id=certificate.get("id", ""), certificate_type=pack.get("type", ""), status=certificate.get("status", pack.get("status", "")), issuer=certificate.get("issuer", ""), hosts=certificate.get("hosts", pack.get("hosts", [])), expiry_date=expiry_date, days_left=(expiry_date - date.today()).days if expiry_date else None))
        return assets

    def _service_assets(self, account_id: str, account_name: str) -> list[ServiceAsset]:
        try:
            subscriptions = self.provider.get_account_services(account_id)
        except Exception as exc:
            self.logger.warning("Could not retrieve subscriptions for account %s: %s", account_name or account_id, exc)
            return []
        assets: list[ServiceAsset] = []
        for subscription in subscriptions:
            rate_plan = subscription.get("rate_plan") or {}
            renewal_date = self._parse_api_date(subscription.get("current_period_end"))
            assets.append(ServiceAsset(account_id=account_id, account_name=account_name, subscription_id=subscription.get("id", ""), service_name=rate_plan.get("public_name") or rate_plan.get("id", "Subscription"), scope=rate_plan.get("scope", ""), status=subscription.get("state", ""), renewal_date=renewal_date, days_left=(renewal_date - date.today()).days if renewal_date else None, frequency=subscription.get("frequency", ""), price=subscription.get("price"), currency=subscription.get("currency") or rate_plan.get("currency", "")))
        return assets

    @staticmethod
    def _parse_api_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    @staticmethod
    def _health(asset: DomainAsset) -> tuple[int, str]:
        score = 0
        score += 35 if asset.ssl_mode.lower() == "strict" else 0
        score += 25 if asset.dnssec.lower() == "active" else 0
        score += 20 if asset.days_left is None or asset.days_left > 30 else 0
        score += 20 if any(record.proxied for record in asset.dns_records) else 0
        return score, "Good" if score >= 80 else "Needs Attention" if score >= 50 else "At Risk"


class GoDaddyInventoryBuilder:
    """Builds registrar-based inventory (expiry, lock, privacy, auto-renew) from GoDaddy."""

    def __init__(self, client: GoDaddyAPI, logger: logging.Logger, max_workers: int = 2) -> None:
        self.client, self.logger = client, logger
        self.max_workers = max(1, max_workers)

    def build(self) -> InventoryResult:
        result = InventoryResult()
        try:
            summaries = self.client.list_domains()
        except Exception as exc:
            self.logger.exception("Unable to list GoDaddy domains: %s", exc)
            return result
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="godaddy") as executor:
            futures = {executor.submit(self._build_asset, summary, stamp): summary.get("domain", "unknown") for summary in summaries}
            for future in as_completed(futures):
                domain = futures[future]
                try:
                    result.assets.append(future.result())
                except Exception as exc:
                    self.logger.exception("Failed to collect %s: %s", domain, exc)
                    result.failed_domains.append(domain)
        result.assets.sort(key=lambda asset: asset.domain)
        return result

    def _build_asset(self, summary: dict, stamp: str) -> DomainAsset:
        """Collect one domain independently so a failed lookup never stops others."""
        domain = summary.get("domain", "unknown")
        detail = self.client.get_domain(domain)
        expiration = self.client.parse_date(detail.get("expires"))
        records = self.client.get_dns_records(domain)
        nameservers = detail.get("nameServers") or []
        return DomainAsset(domain=domain, source="GoDaddy", status=detail.get("status", ""), registrar="GoDaddy", expiry_date=expiration, days_left=(expiration - date.today()).days if expiration else None, auto_renew=detail.get("renewAuto"), privacy_protection=detail.get("privacy"), domain_lock=detail.get("locked"), nameservers=nameservers, dns_provider="GoDaddy" if nameservers else "", dns_records=records, dns_record_count=len(records), generated_on=stamp)
