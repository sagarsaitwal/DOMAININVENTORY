"""Application entry point for Domain Asset Inventory & Renewal Manager.

Author: Sagar Saitwal
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from config import Settings
from excel_writer import ExcelWriter
from godaddy_api import GoDaddyAPI
from inventory_builder import CloudflareInventoryBuilder, GoDaddyInventoryBuilder
from logger import configure_logging
from models import InventoryResult
from providers.cloudflare import CloudflareProvider


def _run_cloudflare(settings, logger) -> InventoryResult | None:
    if not settings.cloudflare_api_token:
        print("[SKIPPED] Cloudflare: CLOUDFLARE_API_TOKEN not configured.")
        return None
    provider = CloudflareProvider(settings, logger)
    if not provider.authenticate():
        print("[FAILED] Cloudflare API authentication failed. See logs/inventory.log for details.")
        return None
    print("[OK] Cloudflare API Authentication")
    result = CloudflareInventoryBuilder(provider, settings, logger).build()
    print(f"[OK] Cloudflare: Retrieved {len(result.assets)} Zones")
    print(f"[OK] Cloudflare: Retrieved {result.dns_record_count} DNS Records")
    print(f"[OK] Cloudflare: Retrieved {len(result.certificates)} SSL Certificates")
    print(f"[OK] Cloudflare: Retrieved {len(result.services)} Purchased Services")
    return result


def _run_godaddy(settings, logger) -> InventoryResult | None:
    if not settings.godaddy_api_key or not settings.godaddy_api_secret:
        print("[SKIPPED] GoDaddy: GODADDY_API_KEY / GODADDY_API_SECRET not configured.")
        return None
    client = GoDaddyAPI(settings, logger)
    if not client.authenticate():
        print("[FAILED] GoDaddy API authentication failed. See logs/inventory.log for details.")
        return None
    print("[OK] GoDaddy API Authentication")
    result = GoDaddyInventoryBuilder(client, logger, settings.godaddy_max_workers).build()
    print(f"[OK] GoDaddy: Retrieved {len(result.assets)} Domains")
    print(f"[OK] GoDaddy: Retrieved {result.dns_record_count} DNS Records")
    return result


def main() -> int:
    """Build the combined Cloudflare + GoDaddy inventory and write its Excel report."""
    started = time.perf_counter()
    settings = Settings.from_environment()
    logger = configure_logging(settings.log_dir)
    print("\n-----------------------------------------")
    print("Domain Asset Inventory & Renewal Manager")
    print("-----------------------------------------\n")

    combined = InventoryResult()
    for runner in (_run_cloudflare, _run_godaddy):
        result = runner(settings, logger)
        if result is not None:
            combined.extend(result)

    if not combined.assets and not combined.failed_domains:
        print("\nNo providers were configured. Add CLOUDFLARE_API_TOKEN and/or GODADDY_API_KEY/SECRET to .env and run again.")
        return 2

    report_path = ExcelWriter(Path(settings.output_dir)).create_inventory(combined.assets, combined.certificates, combined.services, combined.failed_domains)
    print("\n[OK] Excel Generated\n")
    print(f"Output:\n{report_path}")
    print(f"\nDuration\n{time.perf_counter() - started:.1f} seconds")
    if combined.failed_domains:
        print(f"\nCompleted with {len(combined.failed_domains)} domain(s) containing retrieval errors.")
    logger.info("Inventory complete: domains=%s records=%s failed=%s", len(combined.assets), combined.dns_record_count, combined.failed_domains)
    return 0


if __name__ == "__main__":
    sys.exit(main())
