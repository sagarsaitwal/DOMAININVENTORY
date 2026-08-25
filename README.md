# Domain Asset Inventory & Renewal Manager

**Author:** Sagar Saitwal

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
- A Cloudflare API token (Zone Read, Zone Settings Read, DNS Read,
  SSL/Certificates Read, and optionally Billing Read for purchased services)
  and/or a GoDaddy API key/secret (with domain read access)

### Getting a Cloudflare API token

1. Log in to the [Cloudflare dashboard](https://dash.cloudflare.com/) →
   **My Profile → API Tokens → Create Token**.
2. Choose **Create Custom Token** and grant these permissions (read-only —
   the tool never writes):
   - `Zone → Zone → Read`
   - `Zone → Zone Settings → Read` *(covers `/settings/ssl`, `/dnssec`, and
     `/settings` — easy to miss, and the tool 403s without it even though
     everything else authenticates fine)*
   - `Zone → DNS → Read`
   - `Zone → SSL and Certificates → Read`
   - `Account → Billing → Read` *(optional — only needed for the Purchased
     Services sheet; omit it and that sheet will just be empty)*
3. Under **Zone Resources**, scope it to "All zones" (or specific zones/accounts
   you want inventoried), then **Continue to summary → Create Token**.
4. Copy the token immediately — Cloudflare shows it once — and put it in
   `.env` as `CLOUDFLARE_API_TOKEN`.

### Getting a GoDaddy API key/secret

1. Log in to the [GoDaddy Developer Portal](https://developer.godaddy.com/)
   with the same account that owns the domains.
2. Go to **API Keys → Create New API Key**.
3. Choose environment:
   - **Production** — real account data, use `GODADDY_API_BASE_URL=https://api.godaddy.com`.
   - **OTE (test/sandbox)** — fake test data only, use `GODADDY_API_BASE_URL=https://api.ote-godaddy.com`.
4. Name the key, create it, then copy the **Key** and **Secret** shown — the
   secret is also shown only once. Put them in `.env` as `GODADDY_API_KEY`
   and `GODADDY_API_SECRET`.
5. GoDaddy's Domains API requires the account to have an active/eligible
   domain portfolio; API access can take a short activation period on new
   developer accounts.

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

## What gets collected per provider

**Cloudflare** (zone/DNS-hosting side): every zone on the account, its plan
and status, full DNS record set (name, type, content, TTL, proxy status,
comment), SSL/TLS mode, DNSSEC status, zone feature flags (Brotli, IPv6,
HTTP/3, HSTS, etc.), SSL certificate packs with expiry, and — if Billing
Read is granted — account subscriptions and their renewal dates. Registrar
and domain expiry aren't exposed by Cloudflare's API, so they're enriched
via a best-effort public RDAP lookup per domain.

**GoDaddy** (registrar side): every domain in the account, its status,
expiration date, auto-renew flag, privacy protection flag, domain lock
flag, nameservers, and DNS records for domains using GoDaddy's own DNS
hosting. Domain lookups run concurrently (`GODADDY_MAX_WORKERS`, default 2)
so one slow domain doesn't stall the rest.

Both feed into the same `DomainAsset` model (tagged by `source`) so the
Domains, DNS Records, and Renewals sheets show every domain from either
provider side by side.

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

## Author

**Sagar Saitwal**
- LinkedIn: [www.linkedin.com/in/sagar-saitwal](https://www.linkedin.com/in/sagar-saitwal)
- GitHub: [https://github.com/sagarsaitwal/DOMAININVENTORY.git](https://github.com/sagarsaitwal/DOMAININVENTORY.git)
