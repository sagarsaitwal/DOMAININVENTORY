# Domain Asset Inventory & Renewal Manager

A read-only CLI tool that inventories domains, DNS records, SSL certificates,
and renewal dates across **Cloudflare** and **GoDaddy**, and produces a single
color-coded Excel report so nothing expires unnoticed.

Merged from two standalone tools (CloudflareInventory, GoDaddyInventory) into
one codebase with a shared core (config, logging, renewal urgency bands,
Excel writer) and one builder per provider.

## Features

- **Multi-provider** — runs Cloudflare and/or GoDaddy in the same pass; either
  can be left unconfigured and is skipped automatically.
- **Renewal-first reporting** — every domain, SSL certificate, and Cloudflare
  billing subscription is ranked into one urgency-banded list (Expired →
  Expiring → Critical → ... → Healthy), colour-coded in Excel.
- **Read-only** — no credentials are ever used to modify DNS, zones, or
  domains; only GET requests are made.
- **Resilient** — a failed lookup for one domain/zone never aborts the run;
  it's recorded in the report as a retrieval failure instead.
- **RDAP enrichment** — Cloudflare zones are enriched with registrar/expiry
  data via RDAP, since Cloudflare's own API doesn't expose it.

## Requirements

- Python 3.12+
- A Cloudflare API token (Zone Read, DNS Read, SSL/Certificates Read, and
  optionally Billing Read for purchased services) and/or a GoDaddy API
  key/secret (with domain read access)

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in whichever provider(s) you use
```

`.env` is git-ignored. Either provider block can be left blank — `main.py`
skips any provider that isn't configured and runs whichever ones are.

## Run

```bash
python main.py
```

Produces a single timestamped workbook in `output/`, e.g.
`output/Domain_Inventory_20260803_184307.xlsx`, covering both providers:

| Sheet | Contents |
|---|---|
| **Renewals** | Every domain, SSL certificate, and Cloudflare service in one urgency-ranked list |
| **Domains** | Combined domain inventory with a `Source` column (Cloudflare / GoDaddy) and the union of both providers' fields |
| **DNS Records** | Combined DNS records across both providers |
| **SSL & Security** | Cloudflare zone SSL/TLS settings |
| **SSL Certificates** | Cloudflare certificate packs and expiry |
| **Purchased Services** | Cloudflare account billing subscriptions and renewal dates |
| **Zone Settings** | Cloudflare zone feature flags (Brotli, IPv6, HTTP/3, etc.) |
| **Dashboard** | Headline metrics, distributions, and a top-domains-by-DNS-records chart |

Logs are written to `logs/inventory.log` (also git-ignored).

## Project layout

```
main.py                entry point — runs each configured provider, merges results
config.py              environment-backed Settings (both providers + shared)
models.py              shared dataclasses (DomainAsset is a superset of both providers' fields, tagged by `source`)
renewal.py             single source of truth for urgency bands/wording; provider-agnostic
inventory_builder.py   CloudflareInventoryBuilder + GoDaddyInventoryBuilder, both producing an InventoryResult
providers/             Cloudflare's provider abstraction (DomainProvider contract)
cloudflare_api.py       raw Cloudflare v4 API client
godaddy_api.py          raw GoDaddy API client
rdap_lookup.py          best-effort RDAP enrichment for Cloudflare zones
excel_writer.py         the combined workbook writer
test_renewal.py         unit tests for renewal policy and the Renewals sheet
```

GoDaddy is registrar-only (no zones, SSL, or billing concepts), so it's wired
directly into `inventory_builder.py` rather than forced through Cloudflare's
zone-shaped `DomainProvider` contract.

## Testing

```bash
pytest
```

## Notes

- Never commit `.env` — it holds live API credentials.
- Renewal urgency bands, wording, and Excel colours are defined once in
  `renewal.py` and reused everywhere; change them there, not per-sheet.
