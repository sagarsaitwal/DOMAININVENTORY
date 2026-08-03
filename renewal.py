"""Renewal policy: the single source of truth for urgency bands, wording, and ordering."""

from dataclasses import dataclass
from datetime import date

from models import InventoryResult, RenewalItem

DAYS_PER_MONTH = 30

DOMAIN = "Domain"
CERTIFICATE = "SSL Certificate"
SERVICE = "Service"
FAILED = "Retrieval Failed"


@dataclass(frozen=True, slots=True)
class Band:
    """One urgency band. `lower`/`upper` are inclusive; None means unbounded."""

    label: str
    range_label: str
    action: str
    lower: int | None
    upper: int | None
    bg_colour: str
    font_colour: str

    def matches(self, days_left: int | None) -> bool:
        if days_left is None:
            return self.lower is None and self.upper is None
        if self.lower is None and self.upper is None:
            return False
        if self.lower is not None and days_left < self.lower:
            return False
        if self.upper is not None and days_left > self.upper:
            return False
        return True

    def formula(self, cell: str) -> str:
        """Excel conditional-format criteria testing `cell` against this band.

        The `<>""` guard on the open-ended lower band matters: Excel coerces an
        empty cell to 0, so an unguarded `=$G18<=0` would paint every blank
        Days Left row as Expired. Rows with no day count are formatted directly
        instead, and are excluded from conditional formatting via CF_BANDS.
        """
        if self.lower is None and self.upper is None:
            return f'={cell}=""'
        if self.lower is None:
            return f'=AND({cell}<>"",{cell}<={self.upper})'
        if self.upper is None:
            return f"={cell}>={self.lower}"
        return f"=AND({cell}>={self.lower},{cell}<={self.upper})"


# Ordered most urgent first, so the summary block reads top-down by severity.
BANDS: tuple[Band, ...] = (
    Band("Expired", "Expired (0 or past)", "Service disruption risk", None, 0, "#000000", "#FF0000"),
    Band("Expiring", "Expiring (1-6 days)", "Immediate action required", 1, 6, "#C00000", "#FFFFFF"),
    Band("Critical", "Critical (7-14 days)", "Escalate to IT Manager / Domain Owner", 7, 14, "#FFC7CE", "#9C0006"),
    Band("Action Required", "Action Required (15-30)", "Owner should verify renewal immediately", 15, 30, "#F4B183", "#843C0C"),
    Band("Renewal Due Soon", "Renewal Due Soon (31-60)", "Confirm auto-renew or initiate renewal", 31, 60, "#FCE4D6", "#C65911"),
    Band("Planned Renewal", "Planned Renewal (61-90)", "Verify registrar, budget, and ownership", 61, 90, "#FFF2CC", "#7F6000"),
    Band("Monitor", "Monitor (91-180)", "Review during quarterly asset audit", 91, 180, "#E2F0D9", "#375623"),
    Band("Healthy", "Healthy (181+ days)", "No action required", 181, None, "#C6EFCE", "#006100"),
    Band("Unknown", "Unknown expiry", "Verify the domain expiry date with the registrar", None, None, "#D9D9D9", "#3F3F3F"),
)

# Bands eligible for Excel conditional formatting. Unknown is excluded because it
# is defined by an absent value, which no numeric criteria can test reliably.
CF_BANDS: tuple[Band, ...] = tuple(band for band in BANDS if band.label != "Unknown")


def band_for(days_left: int | None) -> Band:
    return next(band for band in BANDS if band.matches(days_left))


def countdown(days_left: int | None) -> str:
    """Phrase a day count the way a person reads it."""
    if days_left is None:
        return "Unknown"
    if days_left < 0:
        overdue = abs(days_left)
        return f"overdue {overdue} {'day' if overdue == 1 else 'days'}"
    if days_left == 0:
        return "expires today"
    if days_left < DAYS_PER_MONTH:
        return f"in {days_left} {'day' if days_left == 1 else 'days'}"
    months = round(days_left / DAYS_PER_MONTH)
    return f"in {months} {'month' if months == 1 else 'months'}"


FAILED_STATUS = "RETRIEVAL FAILED - verify manually"
FAILED_ACTION = "Re-run the inventory; if it keeps failing, verify this asset with its provider"

# Band.action is the domain wording and the default. These override it only where
# registrar advice would be wrong or actively misleading for another asset type.
ACTION_OVERRIDES: dict[str, dict[str, str]] = {
    CERTIFICATE: {
        "Expired": "Certificate has lapsed - check the certificate pack in Cloudflare",
        "Expiring": "Cloudflare should have reissued - investigate the certificate pack",
        "Critical": "Cloudflare should have reissued - investigate the certificate pack",
        "Action Required": "Reissue is expected shortly; confirm the certificate pack is active",
        "Renewal Due Soon": "No action required; Cloudflare reissues at about 30 days",
        "Planned Renewal": "No action required; Cloudflare reissues at about 30 days",
        "Unknown": "Certificate expiry unavailable; check the certificate pack status",
    },
    SERVICE: {
        "Expired": "Subscription has lapsed - confirm billing status in Cloudflare",
        "Expiring": "Confirm the subscription renews or that budget is approved",
        "Critical": "Confirm the subscription renews or that budget is approved",
        "Action Required": "Confirm the subscription renews or that budget is approved",
        "Renewal Due Soon": "Confirm the subscription renews on schedule",
        "Planned Renewal": "Review the subscription against next period's budget",
        "Unknown": "Renewal date unavailable; requires Billing Read on the API token",
    },
}


def guidance(days_left: int | None, asset_type: str = DOMAIN) -> tuple[str, str]:
    """Return the (status, recommended action) pair for a day count and asset type."""
    band = band_for(days_left)
    return band.label, ACTION_OVERRIDES.get(asset_type, {}).get(band.label, band.action)


TYPE_RANK: dict[str, int] = {FAILED: 0, DOMAIN: 1, CERTIFICATE: 2, SERVICE: 3}

HANDLING: dict[str, str] = {
    DOMAIN: "Registrar-managed",
    CERTIFICATE: "Auto-managed by Cloudflare",
    SERVICE: "Billing-managed",
    FAILED: "",
}


def _detail(*parts: str) -> str:
    """Join the populated parts of a Detail cell, degrading to an empty string."""
    return " - ".join(part for part in parts if part)


def _days_left(expires: date | None, days_left: int | None) -> int | None:
    """Prefer the stored count; derive it when only a date survived."""
    if days_left is not None:
        return days_left
    return (expires - date.today()).days if expires else None


def sort_key(item: RenewalItem) -> tuple[int, bool, date, str]:
    """Block by asset type, then soonest expiry first, unknown last, ties by name."""
    return (
        TYPE_RANK.get(item.asset_type, len(TYPE_RANK)),
        item.expires is None,
        item.expires or date.max,
        item.name,
    )


def items_from(result: InventoryResult) -> list[RenewalItem]:
    """Flatten every expiring asset into one ordered list. Never raises."""
    items = [RenewalItem(asset_type=FAILED, name=name, handling=HANDLING[FAILED]) for name in result.failed_domains]
    items += [
        RenewalItem(
            asset_type=DOMAIN,
            name=asset.domain,
            detail=_detail(asset.registrar),
            account=asset.account_name or asset.source,
            expires=asset.expiry_date,
            days_left=_days_left(asset.expiry_date, asset.days_left),
            handling=HANDLING[DOMAIN],
        )
        for asset in result.assets
    ]
    items += [
        RenewalItem(
            asset_type=CERTIFICATE,
            name=certificate.domain,
            detail=_detail(certificate.certificate_type, certificate.issuer),
            account=certificate.account_name,
            expires=certificate.expiry_date,
            days_left=_days_left(certificate.expiry_date, certificate.days_left),
            handling=HANDLING[CERTIFICATE],
        )
        for certificate in result.certificates
    ]
    items += [
        RenewalItem(
            asset_type=SERVICE,
            name=service.service_name,
            detail=_detail(service.scope, service.frequency),
            account=service.account_name or service.account_id,
            expires=service.renewal_date,
            days_left=_days_left(service.renewal_date, service.days_left),
            handling=HANDLING[SERVICE],
        )
        for service in result.services
    ]
    return sorted(items, key=sort_key)


SUMMARY_TYPES: tuple[str, ...] = (DOMAIN, CERTIFICATE, SERVICE)


@dataclass(frozen=True, slots=True)
class RenewalSummary:
    """The band x asset-type matrix, its totals, and the headline domain risk."""

    total: int
    type_totals: tuple[tuple[str, int], ...]
    band_rows: tuple[tuple[str, tuple[int, ...], int], ...]
    soonest_expiry: date | None
    soonest_domain: str
    soonest_countdown: str


def summarise(items: list[RenewalItem]) -> RenewalSummary:
    """Count items per band and asset type. Retrieval failures are not classifiable."""
    counts = {band.label: dict.fromkeys(SUMMARY_TYPES, 0) for band in BANDS}
    for item in items:
        if item.asset_type in SUMMARY_TYPES:
            counts[band_for(item.days_left).label][item.asset_type] += 1
    band_rows = tuple(
        (band.label, tuple(counts[band.label][kind] for kind in SUMMARY_TYPES), sum(counts[band.label].values()))
        for band in BANDS
    )
    type_totals = tuple((kind, sum(counts[band.label][kind] for band in BANDS)) for kind in SUMMARY_TYPES)
    dated = [item for item in items if item.asset_type == DOMAIN and item.expires]
    soonest = min(dated, key=lambda item: item.expires) if dated else None
    return RenewalSummary(
        total=sum(count for _, count in type_totals),
        type_totals=type_totals,
        band_rows=band_rows,
        soonest_expiry=soonest.expires if soonest else None,
        soonest_domain=soonest.name if soonest else "",
        soonest_countdown=countdown(soonest.days_left if soonest else None),
    )
