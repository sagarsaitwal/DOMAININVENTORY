"""Tests for renewal policy and the Renewals sheet."""

from datetime import date, timedelta

import pytest

import renewal
from excel_writer import ExcelWriter
from models import CertificateAsset, DomainAsset, InventoryResult, ServiceAsset
from renewal import BANDS, CERTIFICATE, CF_BANDS, DOMAIN, FAILED, SERVICE, band_for


def _in_days(days):
    return date.today() + timedelta(days=days)


def _result():
    """An InventoryResult covering all four streams, deliberately out of order."""
    return InventoryResult(
        assets=[
            DomainAsset(zone_id="z2", domain="beta.example", plan="Free", status="active", registrar="Registrar B", expiry_date=_in_days(200), days_left=200, account_name="Acct"),
            DomainAsset(zone_id="z1", domain="alpha.example", plan="Free", status="active", registrar="Registrar A", expiry_date=_in_days(5), days_left=5, account_name="Acct"),
            DomainAsset(zone_id="z3", domain="gamma.example", plan="Free", status="active", registrar="", expiry_date=None, days_left=None, account_name="Acct"),
        ],
        certificates=[
            CertificateAsset(domain="beta.example", account_name="Acct", certificate_type="universal", issuer="Google Trust Services", expiry_date=_in_days(40), days_left=40),
            CertificateAsset(domain="alpha.example", account_name="Acct", certificate_type="universal", issuer="Google Trust Services", expiry_date=_in_days(12), days_left=12),
        ],
        services=[
            ServiceAsset(account_id="a1", account_name="Acct", service_name="Workers Paid", scope="account", frequency="monthly", renewal_date=_in_days(18), days_left=18),
        ],
        failed_domains=["broken.example", "alsobroken.example"],
    )


def test_nine_bands_ordered_most_urgent_first():
    assert [band.label for band in BANDS] == [
        "Expired",
        "Expiring",
        "Critical",
        "Action Required",
        "Renewal Due Soon",
        "Planned Renewal",
        "Monitor",
        "Healthy",
        "Unknown",
    ]


def test_cf_bands_exclude_unknown():
    assert "Unknown" not in [band.label for band in CF_BANDS]
    assert len(CF_BANDS) == 8


@pytest.mark.parametrize(
    "days_left,expected",
    [
        (400, "Healthy"),
        (181, "Healthy"),
        (180, "Monitor"),
        (91, "Monitor"),
        (90, "Planned Renewal"),
        (61, "Planned Renewal"),
        (60, "Renewal Due Soon"),
        (31, "Renewal Due Soon"),
        (30, "Action Required"),
        (15, "Action Required"),
        (14, "Critical"),
        (7, "Critical"),
        (6, "Expiring"),
        (1, "Expiring"),
        (0, "Expired"),
        (-1, "Expired"),
        (-500, "Expired"),
        (None, "Unknown"),
    ],
)
def test_band_boundaries_on_both_sides_of_every_edge(days_left, expected):
    assert band_for(days_left).label == expected


def test_exactly_one_band_matches_every_day_count():
    for days_left in range(-30, 401):
        matching = [band.label for band in BANDS if band.matches(days_left)]
        assert len(matching) == 1, f"{days_left} matched {matching}"


def test_only_unknown_matches_a_missing_date():
    matching = [band.label for band in BANDS if band.matches(None)]
    assert matching == ["Unknown"]


def test_every_band_has_distinct_colours_and_wording():
    assert len({band.bg_colour + band.font_colour for band in BANDS}) == len(BANDS)
    assert all(band.action for band in BANDS)
    assert all(band.range_label for band in BANDS)


def test_formula_shapes():
    assert band_for(0).formula("$G18") == '=AND($G18<>"",$G18<=0)'
    assert band_for(200).formula("$G18") == "=$G18>=181"
    assert band_for(10).formula("$G18") == "=AND($G18>=7,$G18<=14)"


def test_asset_type_constants():
    assert (DOMAIN, CERTIFICATE, SERVICE, FAILED) == (
        "Domain",
        "SSL Certificate",
        "Service",
        "Retrieval Failed",
    )


@pytest.mark.parametrize(
    "days_left,expected",
    [
        (None, "Unknown"),
        (-1, "overdue 1 day"),
        (-2, "overdue 2 days"),
        (-365, "overdue 365 days"),
        (0, "expires today"),
        (1, "in 1 day"),
        (2, "in 2 days"),
        (29, "in 29 days"),
        (30, "in 1 month"),
        (44, "in 1 month"),
        (45, "in 2 months"),
        (60, "in 2 months"),
        (365, "in 12 months"),
    ],
)
def test_countdown_phrasing(days_left, expected):
    assert renewal.countdown(days_left) == expected


def test_month_rounding_collision_is_known_and_accepted():
    # 47 and 75 days both read "in 2 months"; the Days Left column carries the
    # precision. Documented in the spec's Known limitations.
    assert renewal.countdown(47) == renewal.countdown(75) == "in 2 months"


def test_domain_guidance_is_the_band_action():
    for band in BANDS:
        days_left = band.lower if band.lower is not None else band.upper
        status, action = renewal.guidance(days_left, DOMAIN)
        assert (status, action) == (band.label, band.action)


def test_domain_is_the_default_asset_type():
    assert renewal.guidance(5) == renewal.guidance(5, DOMAIN)


def test_guidance_covers_every_band_and_type_without_blanks():
    for asset_type in (DOMAIN, CERTIFICATE, SERVICE):
        for band in BANDS:
            days_left = band.lower if band.lower is not None else band.upper
            status, action = renewal.guidance(days_left, asset_type)
            assert status == band.label
            assert action, f"empty action for {asset_type}/{band.label}"


def test_certificate_guidance_differs_where_registrar_advice_is_wrong():
    for days_left in (0, 3, 10, 20, 45, 75, None):
        _, domain_action = renewal.guidance(days_left, DOMAIN)
        _, cert_action = renewal.guidance(days_left, CERTIFICATE)
        assert cert_action != domain_action


def test_certificate_urgent_guidance_points_at_the_certificate_pack():
    assert "certificate pack" in renewal.guidance(3, CERTIFICATE)[1]
    assert "certificate pack" in renewal.guidance(None, CERTIFICATE)[1]


def test_service_unknown_guidance_names_the_missing_permission():
    status, action = renewal.guidance(None, SERVICE)
    assert status == "Unknown"
    assert "Billing Read" in action


def test_service_urgent_guidance_is_a_billing_question():
    for days_left in (0, 3, 10, 20):
        assert "subscription" in renewal.guidance(days_left, SERVICE)[1].lower()


def test_unspecified_bands_fall_back_to_the_band_action():
    healthy = band_for(400)
    assert renewal.guidance(400, CERTIFICATE)[1] == healthy.action
    assert renewal.guidance(400, SERVICE)[1] == healthy.action


def test_failed_rows_have_a_fixed_status_and_action():
    assert renewal.FAILED_STATUS == "RETRIEVAL FAILED - verify manually"
    assert renewal.FAILED_ACTION


def test_override_tables_only_reference_real_band_labels():
    labels = {band.label for band in BANDS}
    for asset_type, overrides in renewal.ACTION_OVERRIDES.items():
        assert set(overrides) <= labels, asset_type


def test_items_from_flattens_all_four_streams():
    items = renewal.items_from(_result())
    counts = {}
    for item in items:
        counts[item.asset_type] = counts.get(item.asset_type, 0) + 1
    assert counts == {FAILED: 2, DOMAIN: 3, CERTIFICATE: 2, SERVICE: 1}


def test_items_are_blocked_by_type_then_sorted_by_urgency():
    items = renewal.items_from(_result())
    assert [(item.asset_type, item.name) for item in items] == [
        (FAILED, "alsobroken.example"),
        (FAILED, "broken.example"),
        (DOMAIN, "alpha.example"),
        (DOMAIN, "beta.example"),
        (DOMAIN, "gamma.example"),
        (CERTIFICATE, "alpha.example"),
        (CERTIFICATE, "beta.example"),
        (SERVICE, "Workers Paid"),
    ]


def test_unknown_expiry_sorts_last_within_its_block():
    items = [item for item in renewal.items_from(_result()) if item.asset_type == DOMAIN]
    assert items[-1].name == "gamma.example"
    assert items[-1].expires is None


def test_ties_break_by_name():
    same_day = _in_days(30)
    result = InventoryResult(assets=[
        DomainAsset(zone_id="z1", domain="zeta.example", plan="", status="", expiry_date=same_day, days_left=30),
        DomainAsset(zone_id="z2", domain="delta.example", plan="", status="", expiry_date=same_day, days_left=30),
    ])
    assert [item.name for item in renewal.items_from(result)] == ["delta.example", "zeta.example"]


def test_handling_names_who_owns_the_renewal():
    by_type = {item.asset_type: item for item in renewal.items_from(_result())}
    assert by_type[DOMAIN].handling == "Registrar-managed"
    assert by_type[CERTIFICATE].handling == "Auto-managed by Cloudflare"
    assert by_type[SERVICE].handling == "Billing-managed"
    assert by_type[FAILED].handling == ""


def test_detail_column_content_per_type():
    items = {(item.asset_type, item.name): item for item in renewal.items_from(_result())}
    assert items[(DOMAIN, "alpha.example")].detail == "Registrar A"
    assert items[(CERTIFICATE, "alpha.example")].detail == "universal - Google Trust Services"
    assert items[(SERVICE, "Workers Paid")].detail == "account - monthly"
    assert items[(FAILED, "broken.example")].detail == ""


def test_missing_detail_parts_degrade_to_empty_string():
    result = InventoryResult(
        assets=[DomainAsset(zone_id="z", domain="a.example", plan="", status="", registrar="")],
        certificates=[CertificateAsset(domain="a.example", certificate_type="", issuer="")],
        services=[ServiceAsset(account_id="a", service_name="S", scope="", frequency="")],
    )
    assert all(item.detail == "" for item in renewal.items_from(result))


def test_partial_detail_omits_the_missing_half():
    result = InventoryResult(certificates=[CertificateAsset(domain="a.example", certificate_type="advanced", issuer="")])
    assert renewal.items_from(result)[0].detail == "advanced"


def test_days_left_is_derived_when_absent_but_a_date_is_present():
    result = InventoryResult(assets=[
        DomainAsset(zone_id="z", domain="a.example", plan="", status="", expiry_date=_in_days(9), days_left=None),
    ])
    assert renewal.items_from(result)[0].days_left == 9


def test_missing_dates_survive_as_none():
    result = InventoryResult(assets=[DomainAsset(zone_id="z", domain="a.example", plan="", status="")])
    item = renewal.items_from(result)[0]
    assert item.expires is None and item.days_left is None
    assert band_for(item.days_left).label == "Unknown"


def test_service_falls_back_to_account_id_when_unnamed():
    result = InventoryResult(services=[ServiceAsset(account_id="acct-123", account_name="", service_name="S")])
    assert renewal.items_from(result)[0].account == "acct-123"


def test_empty_inventory_yields_no_items():
    assert renewal.items_from(InventoryResult()) == []


def test_items_from_never_raises_on_degenerate_input():
    result = InventoryResult(
        assets=[DomainAsset(zone_id="", domain="", plan="", status="")],
        certificates=[CertificateAsset(domain="")],
        services=[ServiceAsset(account_id="")],
        failed_domains=[""],
    )
    assert len(renewal.items_from(result)) == 4


def test_summary_types_exclude_failed_rows():
    assert renewal.SUMMARY_TYPES == (DOMAIN, CERTIFICATE, SERVICE)


def test_band_rows_cover_every_band_in_order():
    summary = renewal.summarise(renewal.items_from(_result()))
    assert [row[0] for row in summary.band_rows] == [band.label for band in BANDS]
    assert all(len(row[1]) == 3 for row in summary.band_rows)


def test_matrix_counts_land_in_the_right_cell():
    summary = renewal.summarise(renewal.items_from(_result()))
    cells = {row[0]: dict(zip(renewal.SUMMARY_TYPES, row[1])) for row in summary.band_rows}
    # alpha.example at 5 days
    assert cells["Expiring"][DOMAIN] == 1
    # beta.example at 200 days
    assert cells["Healthy"][DOMAIN] == 1
    # gamma.example has no expiry date
    assert cells["Unknown"][DOMAIN] == 1
    # certificates at 12 and 40 days
    assert cells["Critical"][CERTIFICATE] == 1
    assert cells["Renewal Due Soon"][CERTIFICATE] == 1
    # the service at 18 days
    assert cells["Action Required"][SERVICE] == 1


def test_row_and_column_totals_agree():
    summary = renewal.summarise(renewal.items_from(_result()))
    assert [row[2] for row in summary.band_rows] == [sum(row[1]) for row in summary.band_rows]
    assert sum(row[2] for row in summary.band_rows) == summary.total
    assert sum(count for _, count in summary.type_totals) == summary.total


def test_type_totals_are_per_stream():
    summary = renewal.summarise(renewal.items_from(_result()))
    assert dict(summary.type_totals) == {DOMAIN: 3, CERTIFICATE: 2, SERVICE: 1}


def test_failed_rows_are_excluded_from_the_matrix():
    summary = renewal.summarise(renewal.items_from(_result()))
    # two failed zones exist, but total counts only the six classifiable assets
    assert summary.total == 6


def test_soonest_expiry_considers_domains_only():
    summary = renewal.summarise(renewal.items_from(_result()))
    assert summary.soonest_domain == "alpha.example"
    assert summary.soonest_expiry == _in_days(5)
    assert summary.soonest_countdown == "in 5 days"


def test_soonest_expiry_is_empty_when_no_domain_has_a_date():
    result = InventoryResult(
        assets=[DomainAsset(zone_id="z", domain="a.example", plan="", status="")],
        certificates=[CertificateAsset(domain="a.example", expiry_date=_in_days(3), days_left=3)],
    )
    summary = renewal.summarise(renewal.items_from(result))
    assert summary.soonest_expiry is None
    assert summary.soonest_domain == ""
    assert summary.soonest_countdown == "Unknown"


def test_summarise_of_an_empty_inventory_is_all_zeroes():
    summary = renewal.summarise([])
    assert summary.total == 0
    assert all(row[2] == 0 for row in summary.band_rows)
    assert dict(summary.type_totals) == {DOMAIN: 0, CERTIFICATE: 0, SERVICE: 0}
    assert summary.soonest_expiry is None


EXISTING_SHEETS = [
    "Domains",
    "DNS Records",
    "SSL & Security",
    "SSL Certificates",
    "Purchased Services",
    "Zone Settings",
    "Dashboard",
]


def _unescape(value):
    """Reverse the XML entity escaping xlsxwriter applies to sheet names."""
    for entity, character in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'")):
        value = value.replace(entity, character)
    return value


def _sheet_names(path):
    """Read worksheet names out of a written .xlsx without extra dependencies."""
    import re
    import zipfile

    with zipfile.ZipFile(path) as archive:
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
    return [_unescape(name) for name in re.findall(r'<sheet name="([^"]+)"', workbook)]


def test_empty_inventory_writes_a_workbook_without_raising(tmp_path):
    path = ExcelWriter(tmp_path).create_inventory([])
    assert path.exists()


def test_empty_inventory_emits_no_degenerate_chart(tmp_path):
    """With no assets the Dashboard chart range inverts to $A$10:$A$9 - junk that
    older xlsxwriter rejected outright as EmptyChartSeries. Skip the chart instead."""
    import zipfile

    path = ExcelWriter(tmp_path).create_inventory([])
    with zipfile.ZipFile(path) as archive:
        assert not [name for name in archive.namelist() if "chart" in name]


def test_populated_inventory_still_gets_its_chart(tmp_path):
    import zipfile

    result = _result()
    path = ExcelWriter(tmp_path).create_inventory(result.assets, result.certificates, result.services)
    with zipfile.ZipFile(path) as archive:
        assert [name for name in archive.namelist() if "chart" in name]


def test_existing_sheets_keep_their_names_and_order(tmp_path):
    result = _result()
    path = ExcelWriter(tmp_path).create_inventory(result.assets, result.certificates, result.services)
    names = _sheet_names(path)
    assert [name for name in names if name in EXISTING_SHEETS] == EXISTING_SHEETS


def _grid(path, sheet_name):
    """Return a {(row, col): value} map of a sheet's cells, 1-indexed."""
    import re
    import zipfile

    names = _sheet_names(path)
    index = names.index(sheet_name) + 1
    with zipfile.ZipFile(path) as archive:
        shared = re.findall(r"<t[^>]*>([^<]*)</t>", archive.read("xl/sharedStrings.xml").decode("utf-8"))
        xml = archive.read(f"xl/worksheets/sheet{index}.xml").decode("utf-8")
    grid = {}
    for cell in re.finditer(r'<c r="([A-Z]+)(\d+)"([^>]*)>(?:<v>([^<]*)</v>)?', xml):
        column, row, attrs, value = cell.groups()
        if value is None:
            continue
        col = 0
        for character in column:
            col = col * 26 + ord(character) - 64
        grid[(int(row), col)] = _unescape(shared[int(value)]) if 't="s"' in attrs else value
    return grid


def _written(tmp_path, with_failures=True):
    result = _result()
    return ExcelWriter(tmp_path).create_inventory(
        result.assets, result.certificates, result.services, result.failed_domains if with_failures else None
    )


def test_renewals_is_the_first_tab(tmp_path):
    assert _sheet_names(_written(tmp_path))[0] == "Renewals"


def test_summary_block_lists_every_band_as_its_own_row(tmp_path):
    grid = _grid(_written(tmp_path), "Renewals")
    assert grid[(1, 1)] == "Renewal Overview"
    assert grid[(4, 1)] == "Renewal Status"
    # The label column carries range_label, not label: the block is the colour
    # legend, so it has to state the day ranges the colours mean.
    assert [grid[(row, 1)] for row in range(5, 14)] == [band.range_label for band in BANDS]
    assert grid[(14, 1)] == "Total"


def test_table_header_sits_at_the_expected_row(tmp_path):
    grid = _grid(_written(tmp_path), "Renewals")
    assert grid[(ExcelWriter.RENEWALS_HEADER_ROW + 1, 1)] == "Asset Type"
    assert grid[(ExcelWriter.RENEWALS_HEADER_ROW + 1, 7)] == "Days Left"
    assert grid[(ExcelWriter.RENEWALS_HEADER_ROW + 1, 10)] == "Renewal Handling"


def test_failed_zones_appear_first_in_the_table(tmp_path):
    grid = _grid(_written(tmp_path), "Renewals")
    first = ExcelWriter.RENEWALS_HEADER_ROW + 2
    assert grid[(first, 1)] == "Retrieval Failed"
    assert grid[(first, 2)] == "alsobroken.example"
    assert grid[(first, 8)] == "RETRIEVAL FAILED - verify manually"


def test_every_item_gets_a_row(tmp_path):
    grid = _grid(_written(tmp_path), "Renewals")
    first = ExcelWriter.RENEWALS_HEADER_ROW + 2
    types = [grid.get((first + offset, 1)) for offset in range(8)]
    assert types == [FAILED, FAILED, DOMAIN, DOMAIN, DOMAIN, CERTIFICATE, CERTIFICATE, SERVICE]


def test_conditional_formats_cover_the_data_range_and_skip_unknown(tmp_path):
    import re
    import zipfile

    path = _written(tmp_path)
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    first = ExcelWriter.RENEWALS_HEADER_ROW + 2
    ranges = re.findall(r'<conditionalFormatting sqref="([^"]+)"', xml)
    assert ranges, "no conditional formatting written"
    assert all(reference == f"A{first}:J{first + 7}" for reference in ranges)
    # xlsxwriter groups rules sharing a range into one block, so count the rules.
    assert len(re.findall(r"<cfRule", xml)) == len(CF_BANDS)
    formulas = re.findall(r"<formula>([^<]+)</formula>", xml)
    assert any("$G18" in formula for formula in formulas)
    assert not any('$G18=""' in formula for formula in formulas)


def test_expired_criteria_guards_against_blank_cells(tmp_path):
    """Excel coerces a blank cell to 0, so an unguarded =$G18<=0 would paint every
    Unknown and failed row as Expired."""
    import re
    import zipfile

    with zipfile.ZipFile(_written(tmp_path)) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    formulas = [_unescape(formula) for formula in re.findall(r"<formula>([^<]+)</formula>", xml)]
    assert 'AND($G18<>"",$G18<=0)' in formulas


def test_empty_inventory_still_writes_the_renewals_sheet(tmp_path):
    path = ExcelWriter(tmp_path).create_inventory([])
    grid = _grid(path, "Renewals")
    assert _sheet_names(path)[0] == "Renewals"
    assert grid[(1, 1)] == "Renewal Overview"
    assert grid[(14, 1)] == "Total"
    assert grid.get((ExcelWriter.RENEWALS_HEADER_ROW + 2, 1)) is None


def test_failed_domains_defaults_to_empty(tmp_path):
    grid = _grid(_written(tmp_path, with_failures=False), "Renewals")
    assert grid[(ExcelWriter.RENEWALS_HEADER_ROW + 2, 1)] == DOMAIN


def test_matrix_column_headers_are_plural(tmp_path):
    grid = _grid(_written(tmp_path), "Renewals")
    assert [grid[(4, col)] for col in range(1, 6)] == [
        "Renewal Status",
        "Domains",
        "SSL Certificates",
        "Services",
        "Total",
    ]
