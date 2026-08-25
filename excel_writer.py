"""Professional Excel workbook generation for combined inventory results.

Author: Sagar Saitwal
"""

from collections import Counter
from datetime import datetime
from pathlib import Path

import xlsxwriter

import renewal
from models import CertificateAsset, DomainAsset, InventoryResult, ServiceAsset


def _yes_no(value: bool | None) -> str:
    return "Yes" if value is True else "No" if value is False else ""


class ExcelWriter:
    RENEWALS_HEADER_ROW = 16
    RENEWALS_COLUMNS = ["Asset Type", "Name", "Detail", "Account", "Expires", "Countdown", "Days Left", "Renewal Status", "Recommended Action", "Renewal Handling"]

    def __init__(self, output_folder: Path) -> None:
        self.output_folder = output_folder

    def create_inventory(self, assets: list[DomainAsset], certificates: list[CertificateAsset] | None = None, services: list[ServiceAsset] | None = None, failed_domains: list[str] | None = None) -> Path:
        certificates, services = certificates or [], services or []
        self.output_folder.mkdir(parents=True, exist_ok=True)
        filename = f"Domain_Inventory_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        path = self.output_folder / filename
        workbook = xlsxwriter.Workbook(path)
        header = workbook.add_format({"bold": True, "bg_color": "#1F4E78", "font_color": "#FFFFFF", "border": 1, "align": "center", "valign": "vcenter"})
        cell = workbook.add_format({"border": 1, "valign": "top"})
        date_cell = workbook.add_format({"border": 1, "num_format": "yyyy-mm-dd"})
        items = renewal.items_from(InventoryResult(assets=assets, certificates=certificates, services=services, failed_domains=failed_domains or []))
        self._renewals(workbook, items, header, cell)
        self._domains(workbook, assets, header, cell, date_cell)
        self._records(workbook, assets, header, cell)
        self._security(workbook, assets, header, cell)
        self._certificates(workbook, certificates, header, cell, date_cell)
        self._services(workbook, services, header, cell, date_cell)
        self._settings(workbook, assets, header, cell)
        self._dashboard(workbook, assets, certificates, services, header, cell)
        workbook.close()
        return path

    @staticmethod
    def _table(sheet, headers, header, rows, widths, start_row=0):
        sheet.write_row(start_row, 0, headers, header)
        sheet.freeze_panes(start_row + 1, 0)
        for index, width in enumerate(widths): sheet.set_column(index, index, width)
        if rows: sheet.autofilter(start_row, 0, start_row + rows, len(headers) - 1)

    def _renewal_summary(self, wb, sheet, summary, header):
        sheet.write(0, 0, "Renewal Overview", wb.add_format({"bold": True, "font_size": 16}))
        sheet.write_row(1, 0, ["Generated", datetime.now().isoformat(timespec="seconds")])
        sheet.write_row(3, 0, ["Renewal Status", *[f"{kind}s" for kind in renewal.SUMMARY_TYPES], "Total"], header)
        bands = {band.label: band for band in renewal.BANDS}
        for offset, (label, counts, total) in enumerate(summary.band_rows):
            band = bands[label]
            swatch = wb.add_format({"bg_color": band.bg_colour, "font_color": band.font_colour, "border": 1})
            sheet.write_row(4 + offset, 0, [band.range_label, *counts, total], swatch)
        totals = wb.add_format({"bold": True, "border": 1, "top": 2})
        sheet.write_row(13, 0, ["Total", *[count for _, count in summary.type_totals], summary.total], totals)
        soonest = f"{summary.soonest_domain} ({summary.soonest_countdown})" if summary.soonest_domain else "No domain expiry date available"
        sheet.write_row(14, 0, ["Soonest domain expiry", soonest], wb.add_format({"bold": True}))

    def _renewals(self, wb, items, header, cell):
        sheet = wb.add_worksheet("Renewals")
        summary = renewal.summarise(items)
        self._renewal_summary(wb, sheet, summary, header)
        start = self.RENEWALS_HEADER_ROW
        self._table(sheet, self.RENEWALS_COLUMNS, header, len(items), [16, 32, 30, 22, 14, 16, 11, 20, 52, 26], start)
        sheet.freeze_panes(start + 1, 2)
        date_cell = wb.add_format({"border": 1, "num_format": "dd mmm yyyy"})
        formats = {band.label: wb.add_format({"bg_color": band.bg_colour, "font_color": band.font_colour, "border": 1, "valign": "top"}) for band in renewal.BANDS}
        for offset, item in enumerate(items):
            row = start + 1 + offset
            failed = item.asset_type == renewal.FAILED
            status, action = (renewal.FAILED_STATUS, renewal.FAILED_ACTION) if failed else renewal.guidance(item.days_left, item.asset_type)
            # Conditional formatting cannot test a blank Days Left, so rows without
            # one carry their band format directly. See Band.formula.
            plain = cell if item.days_left is not None and not failed else formats["Expired" if failed else renewal.band_for(item.days_left).label]
            values = [item.asset_type, item.name, item.detail, item.account, item.expires, renewal.countdown(item.days_left) if not failed else "", item.days_left, status, action, item.handling]
            for col, value in enumerate(values):
                if col == 4 and value: sheet.write_datetime(row, col, datetime.combine(value, datetime.min.time()), date_cell if plain is cell else plain)
                else: sheet.write(row, col, value if value is not None else "", plain)
        if not items: return
        last = start + len(items)
        for band in renewal.CF_BANDS:
            fmt = wb.add_format({"bg_color": band.bg_colour, "font_color": band.font_colour})
            sheet.conditional_format(start + 1, 0, last, len(self.RENEWALS_COLUMNS) - 1, {"type": "formula", "criteria": band.formula(f"$G{start + 2}"), "format": fmt})

    def _domains(self, wb, assets, header, cell, date_cell):
        sheet = wb.add_worksheet("Domains")
        columns = ["Domain", "Source", "Zone ID", "Plan", "Status", "Registrar", "Expiry Date", "Days Left", "SSL Mode", "DNSSEC", "Auto Renew", "Privacy Protection", "Domain Lock", "DNS Provider", "Nameservers", "DNS Record Count", "Generated On", "Account", "Health Score", "Health Status"]
        self._table(sheet, columns, header, len(assets), [30, 13, 34, 15, 14, 24, 14, 11, 13, 13, 12, 17, 13, 16, 38, 16, 24, 22, 13, 18])
        for row, asset in enumerate(assets, 1):
            values = [asset.domain, asset.source, asset.zone_id, asset.plan, asset.status, asset.registrar, asset.expiry_date, asset.days_left, asset.ssl_mode, asset.dnssec, _yes_no(asset.auto_renew), _yes_no(asset.privacy_protection), _yes_no(asset.domain_lock), asset.dns_provider, ", ".join(asset.nameservers), asset.dns_record_count, asset.generated_on, asset.account_name, asset.health_score, asset.health_status]
            for col, value in enumerate(values): sheet.write_datetime(row, col, datetime.combine(value, datetime.min.time()), date_cell) if col == 6 and value else sheet.write(row, col, value if value is not None else "", cell)

    def _records(self, wb, assets, header, cell):
        sheet = wb.add_worksheet("DNS Records")
        self._table(sheet, ["Domain", "Source", "Record Name", "Type", "Content", "TTL", "Proxy Status", "Priority", "Comment"], header, sum(len(a.dns_records) for a in assets), [28, 13, 35, 12, 55, 11, 14, 11, 30])
        row = 1
        for asset in assets:
            for record in asset.dns_records:
                sheet.write_row(row, 0, [asset.domain, asset.source, record.name, record.type, record.content, "Auto" if record.ttl == 1 else record.ttl, "Yes" if record.proxied else "No", record.priority, record.comment], cell); row += 1

    def _security(self, wb, assets, header, cell):
        sheet = wb.add_worksheet("SSL & Security")
        keys = [("always_use_https", "Always HTTPS"), ("min_tls_version", "Minimum TLS"), ("tls_1_3", "TLS 1.3"), ("http3", "HTTP/3"), ("hsts", "HSTS"), ("opportunistic_encryption", "Opportunistic Encryption")]
        self._table(sheet, ["Domain", "SSL Mode", *[label for _, label in keys]], header, len(assets), [30, 14, 16, 16, 13, 13, 18, 27])
        for row, asset in enumerate(assets, 1): sheet.write_row(row, 0, [asset.domain, asset.ssl_mode, *[asset.zone_settings.get(key, "") for key, _ in keys]], cell)

    def _certificates(self, wb, certificates, header, cell, date_cell):
        sheet = wb.add_worksheet("SSL Certificates")
        columns = ["Domain", "Account", "Certificate Type", "Status", "Issuer", "Hosts", "Expiry Date", "Days Left", "Certificate Pack ID", "Certificate ID"]
        self._table(sheet, columns, header, len(certificates), [30, 22, 18, 18, 22, 48, 14, 11, 34, 34])
        for row, certificate in enumerate(certificates, 1):
            values = [certificate.domain, certificate.account_name, certificate.certificate_type, certificate.status, certificate.issuer, ", ".join(certificate.hosts), certificate.expiry_date, certificate.days_left, certificate.pack_id, certificate.certificate_id]
            for col, value in enumerate(values): sheet.write_datetime(row, col, datetime.combine(value, datetime.min.time()), date_cell) if col == 6 and value else sheet.write(row, col, value if value is not None else "", cell)

    def _services(self, wb, services, header, cell, date_cell):
        sheet = wb.add_worksheet("Purchased Services")
        columns = ["Account", "Service", "Scope", "Status", "Renewal Date", "Days Left", "Renewal Frequency", "Price", "Currency", "Subscription ID"]
        self._table(sheet, columns, header, len(services), [24, 32, 15, 18, 14, 11, 20, 12, 12, 34])
        for row, service in enumerate(services, 1):
            values = [service.account_name or service.account_id, service.service_name, service.scope, service.status, service.renewal_date, service.days_left, service.frequency, service.price, service.currency, service.subscription_id]
            for col, value in enumerate(values): sheet.write_datetime(row, col, datetime.combine(value, datetime.min.time()), date_cell) if col == 4 and value else sheet.write(row, col, value if value is not None else "", cell)

    def _settings(self, wb, assets, header, cell):
        sheet = wb.add_worksheet("Zone Settings")
        keys = [("brotli", "Brotli"), ("ipv6", "IPv6"), ("http3", "HTTP3"), ("always_use_https", "Always HTTPS"), ("tls_1_3", "TLS 1.3"), ("min_tls_version", "Min TLS"), ("automatic_https_rewrites", "Automatic HTTPS Rewrites"), ("development_mode", "Development Mode")]
        self._table(sheet, ["Domain", *[label for _, label in keys]], header, len(assets), [30, 12, 12, 12, 16, 13, 13, 29, 20])
        for row, asset in enumerate(assets, 1): sheet.write_row(row, 0, [asset.domain, *[asset.zone_settings.get(key, "") for key, _ in keys]], cell)

    def _dashboard(self, wb, assets, certificates, services, header, cell):
        sheet = wb.add_worksheet("Dashboard")
        sheet.write("A1", "Domain Inventory Dashboard", wb.add_format({"bold": True, "font_size": 16}))
        sheet.write_row("A3", ["Metric", "Value"], header)
        metrics = [("Total Domains", len(assets)), ("Total DNS Records", sum(a.dns_record_count for a in assets)), ("SSL Certificates", len(certificates)), ("Purchased Services", len(services)), ("Generation Timestamp", datetime.now().isoformat(timespec="seconds"))]
        for row, item in enumerate(metrics, 3): sheet.write_row(row, 0, item, cell)
        distributions = [("Source Distribution", Counter(a.source or "Unknown" for a in assets)), ("SSL Distribution", Counter(a.ssl_mode or "Unknown" for a in assets)), ("DNSSEC Distribution", Counter(a.dnssec or "Unknown" for a in assets)), ("Plan Distribution", Counter(a.plan or "Unknown" for a in assets))]
        col = 4
        for title, counts in distributions:
            sheet.write(2, col, title, header); sheet.write(2, col + 1, "Count", header)
            for row, (label, count) in enumerate(counts.items(), 3): sheet.write_row(row, col, [label, count], cell)
            col += 3
        sheet.write_row("A9", ["Top Domains by DNS Records", "Record Count"], header)
        for row, asset in enumerate(sorted(assets, key=lambda a: a.dns_record_count, reverse=True)[:10], 9): sheet.write_row(row, 0, [asset.domain, asset.dns_record_count], cell)
        sheet.set_column("A:A", 32); sheet.set_column("B:B", 20); sheet.set_column("E:M", 22)
        if not assets: return
        chart = wb.add_chart({"type": "column"})
        chart.add_series({"name": "DNS Records", "categories": ["Dashboard", 9, 0, min(18, 8 + len(assets)), 0], "values": ["Dashboard", 9, 1, min(18, 8 + len(assets)), 1]})
        chart.set_title({"name": "Top Domains by DNS Records"}); chart.set_legend({"none": True}); sheet.insert_chart("E10", chart)
