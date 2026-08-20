import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from src.report import build_report, render
from conftest import insert_listing, insert_ref, run_pipeline


def build_and_render(db, slug="hostile-ref"):
    run_pipeline(db, slug)
    d = build_report(db, slug)
    assert d is not None
    return render(d)


def test_hostile_title_is_escaped_and_does_not_run(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "<img src=x onerror=alert(1)>",
                   12000, "Good Dealer", None, None, None)
    html = build_and_render(db)
    assert "<img src=x onerror=alert(1)>" not in html
    # The raw source title now lives only in the JSON data block (drawer).
    block = re.search(r'<script id="listing-data" type="application/json">(.*?)</script>',
                      html, re.S)
    assert block
    assert "\\u003cimg src=x onerror=alert(1)\\u003e" in block.group(1)


def test_hostile_title_cannot_break_json_data_block(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "</script><script>alert(1)</script>",
                   12000, "Good Dealer", None, None, None)
    html = build_and_render(db)
    block = re.search(r'<script id="listing-data" type="application/json">(.*?)</script>',
                      html, re.S)
    assert block, "listing-data block missing"
    assert "</script" not in block.group(1).lower()
    assert "\\u003c/script" in block.group(1)


def test_javascript_and_data_urls_never_emitted(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "Hostile listing", 12000,
                   "<img src=x onerror=alert(1)>",
                   "javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
                   "https://example.com/detail")
    html = build_and_render(db)
    assert "javascript:" not in html
    assert "data:text/html" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "https://example.com/detail" in html


def test_http_image_url_is_dropped(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "HTTP image listing", 12000,
                   "Good Dealer", "http://dealer.example/img.jpg", None, None)
    html = build_and_render(db)
    assert "http://dealer.example" not in html


def test_rows_use_ids_not_json_attributes(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "Safe title", 12000, "Good Dealer",
                   None, None, None)
    html = build_and_render(db)
    assert 'data-listing=' not in html
    assert 'data-listing-id="l1"' in html
    assert 'data-open-listing="l1"' in html


def test_no_inline_handlers_or_inline_scripts(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "Safe title", 12000, "Good Dealer",
                   None, None, None)
    html = build_and_render(db)
    assert "onclick=" not in html
    assert "onerror=" not in html
    assert '<script src="/static/report.js"' in html
    assert "<script>" not in html


def test_limited_data_report_has_no_valuation_categories(db):
    insert_ref(db)
    for i in range(4):
        insert_listing(db, f"l{i}", "hostile-ref", f"Listing {i}",
                       10000 + i * 500, f"Dealer {i}", None, None, None)
    html = build_and_render(db)
    assert "How to read this market" not in html
    assert "Why there is no market range yet" in html
    assert "Potential deal" not in html


def test_valid_report_has_market_range_and_categories(db):
    insert_ref(db)
    for i in range(8):
        insert_listing(db, f"l{i}", "hostile-ref", f"Listing {i}",
                       10000 + i * 500, f"Dealer {i}", None, None, None)
    html = build_and_render(db)
    assert "CURRENT OBSERVED MARKET RANGE" in html
    assert "How to read this market" in html
    assert "Potential deal" in html
    assert "Why there is no market range yet" not in html
    assert "Eligibility gates" in html


def test_related_rows_never_enter_exact_tab(db):
    insert_ref(db)
    for i in range(8):
        insert_listing(db, f"e{i}", "hostile-ref", f"Exact {i}",
                       10000 + i * 500, f"Dealer {i}", None, None, None)
    for i in range(2):
        insert_listing(db, f"r{i}", "hostile-ref", f"Related {i}",
                       5000 + i * 100, "Vintage Dealer", None, None, None,
                       exact=0)
    html = build_and_render(db)
    exact_tbl = re.search(r'<table class="listing-table" id="tbl-exact">(.*?)</table>',
                          html, re.S).group(1)
    related_tbl = re.search(r'<table class="listing-table" id="tbl-related">(.*?)</table>',
                            html, re.S).group(1)
    exact_ids = set(re.findall(r'data-listing-id="(e\d)"', exact_tbl))
    related_ids = set(re.findall(r'data-listing-id="(r\d)"', related_tbl))
    assert exact_ids == {"e0", "e1", "e2", "e3", "e4", "e5", "e6", "e7"}
    assert related_ids == {"r0", "r1"}
    assert "r0" not in exact_tbl


def test_variant_rows_never_enter_exact_tab(db):
    insert_ref(db)
    for i in range(8):
        insert_listing(db, f"e{i}", "hostile-ref", f"Exact {i}",
                       10000 + i * 500, f"Dealer {i}", None, None, None)
    for i in range(2):
        insert_listing(db, f"v{i}", "hostile-ref", f"Variant {i}",
                       9000 + i * 100, "Gold Dealer", None, None, None,
                       mat="Yellow Gold")
    html = build_and_render(db)
    exact_tbl = re.search(r'<table class="listing-table" id="tbl-exact">(.*?)</table>',
                          html, re.S).group(1)
    variant_tbl = re.search(r'<table class="listing-table" id="tbl-variant">(.*?)</table>',
                            html, re.S).group(1)
    assert set(re.findall(r'data-listing-id="(e\d)"', exact_tbl)) == \
        {f"e{i}" for i in range(8)}
    assert set(re.findall(r'data-listing-id="(v\d)"', variant_tbl)) == {"v0", "v1"}
    assert "v0" not in exact_tbl


def test_deduped_rows_show_one_row_per_cluster(db):
    insert_ref(db)
    # two listings from the same source listing id -> same cluster
    insert_listing(db, "dup1", "hostile-ref", "Duplicated 1", 10000,
                   "Dealer A", None, "https://example.com/watch/x", None)
    insert_listing(db, "dup2", "hostile-ref", "Duplicated 2", 10100,
                   "Dealer A", None, "https://example.com/watch/x", None)
    for i in range(2, 9):
        insert_listing(db, f"l{i}", "hostile-ref", f"Listing {i}",
                       10000 + i * 100, f"Dealer {i}", None, None, None)
    html = build_and_render(db)
    exact_tbl = re.search(r'<table class="listing-table" id="tbl-exact">(.*?)</table>',
                          html, re.S).group(1)
    ids = set(re.findall(r'data-listing-id="(dup\d|l\d)"', exact_tbl))
    # 1 cluster for the dup pair + 7 unique = 8 rows; only one of dup1/dup2
    assert len(ids) == 8
    assert not ({"dup1", "dup2"} <= ids)
    assert "deduplicated" in html


def test_outlier_exclusion_is_documented(db):
    insert_ref(db)
    for i in range(8):
        insert_listing(db, f"l{i}", "hostile-ref", f"Listing {i}",
                       10000 + i * 500, f"Dealer {i}", None, None, None)
    insert_listing(db, "l99", "hostile-ref", "Crazy outlier", 500000,
                   "Outlier Dealer", None, None, None)
    html = build_and_render(db)
    assert "Outliers excluded by robust MAD filter" in html


def test_match_reasons_surface_in_drawer_data(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "A bracelet listing", 12000,
                   "Parts Dealer", None, None, None)
    insert_listing(db, "l2", "hostile-ref", "A normal watch", 13000,
                   "Dealer A", None, None, None)
    run_pipeline(db, "hostile-ref")
    d = build_report(db, "hostile-ref")
    data = d["listing_data"]
    assert data["l1"]["match_level"] == "rejected"
    assert data["l2"]["match_level"] == "exact_configuration"


def test_build_report_rejects_unknown_slug(db):
    insert_ref(db)
    assert build_report(db, "does-not-exist") is None