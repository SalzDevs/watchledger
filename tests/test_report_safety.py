import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from src.report import build_report, render

SCHEMA = """
CREATE TABLE references_meta (
    slug TEXT PRIMARY KEY, brand TEXT, ref TEXT, model TEXT,
    case_material TEXT, url TEXT, source_url TEXT, fetched_at REAL
);
CREATE TABLE listings (
    id TEXT PRIMARY KEY, slug TEXT NOT NULL, title TEXT, price_usd REAL,
    currency TEXT, condition TEXT, box_papers TEXT, case_material TEXT,
    case_size_mm REAL, movement TEXT, year INTEGER, merchant_slug TEXT,
    merchant_name TEXT, available INTEGER, image_url TEXT, detail_url TEXT,
    buy_url TEXT, exact INTEGER DEFAULT 0, source_url TEXT, fetched_at REAL
);
CREATE TABLE auction_lots (
    slug TEXT PRIMARY KEY, brand TEXT, reference TEXT, model TEXT,
    case_material TEXT, hammer_usd REAL, year_sold INTEGER, venue TEXT,
    lot_url TEXT, ref_slug TEXT, source_url TEXT, fetched_at REAL
);
"""


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO references_meta VALUES (?,?,?,?,?,?,?,?)",
        ("hostile-ref", "Rolex", "126610LN", "Submariner", "Steel",
         "https://example.com/ref", "https://example.com/ref", 1700000000))
    yield conn
    conn.close()


def insert_listing(db, lid, slug, title, price, merchant, image_url, buy_url,
                   detail_url, cond="Excellent", bp="full_set", year=2024,
                   mat="Steel", avail=1, exact=1):
    db.execute(
        "INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lid, slug, title, price, "USD", cond, bp, mat, 41, None, year,
         "dealer", merchant, avail, image_url, detail_url, buy_url, exact,
         "https://example.com/src", 1700000000))


def build_and_render(db, slug="hostile-ref"):
    d = build_report(db, slug)
    assert d is not None
    return render(d)


def test_hostile_title_is_escaped_and_does_not_run(db):
    insert_listing(db, "l1", "hostile-ref", "<img src=x onerror=alert(1)>",
                   12000, "Good Dealer", None, None, None)
    html = build_and_render(db)
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_hostile_title_cannot_break_json_data_block(db):
    insert_listing(db, "l1", "hostile-ref", "</script><script>alert(1)</script>",
                   12000, "Good Dealer", None, None, None)
    html = build_and_render(db)
    block = re.search(r'<script id="listing-data" type="application/json">(.*?)</script>',
                      html, re.S)
    assert block, "listing-data block missing"
    assert "</script" not in block.group(1).lower()
    assert "\\u003c/script" in block.group(1)


def test_javascript_and_data_urls_never_emitted(db):
    insert_listing(db, "l1", "hostile-ref", "Hostile listing", 12000,
                   "<img src=x onerror=alert(1)>",
                   "javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
                   "https://example.com/detail")
    html = build_and_render(db)
    assert "javascript:" not in html
    assert "data:text/html" not in html
    # seller name is escaped text only
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    # the approved detail URL is still emitted (buy_url rejected, detail kept)
    assert "https://example.com/detail" in html


def test_http_image_url_is_dropped(db):
    insert_listing(db, "l1", "hostile-ref", "HTTP image listing", 12000,
                   "Good Dealer", "http://dealer.example/img.jpg", None, None)
    html = build_and_render(db)
    assert "http://dealer.example" not in html


def test_rows_use_ids_not_json_attributes(db):
    insert_listing(db, "l1", "hostile-ref", "Safe title", 12000, "Good Dealer",
                   None, None, None)
    html = build_and_render(db)
    assert 'data-listing=' not in html
    assert 'data-listing-id="l1"' in html
    assert 'data-open-listing="l1"' in html


def test_no_inline_handlers_or_inline_scripts(db):
    insert_listing(db, "l1", "hostile-ref", "Safe title", 12000, "Good Dealer",
                   None, None, None)
    html = build_and_render(db)
    assert "onclick=" not in html
    assert "onerror=" not in html
    assert '<script src="/static/report.js"' in html
    assert "<script>" not in html


def test_limited_data_report_has_no_valuation_categories(db):
    for i in range(4):
        insert_listing(db, f"l{i}", "hostile-ref", f"Listing {i}",
                       10000 + i * 500, "Dealer A", None, None, None)
    html = build_and_render(db)
    assert "How to read this market" not in html
    assert "Why there is no market range yet" in html
    assert "Potential deal" not in html


def test_valid_report_has_market_range_and_categories(db):
    for i in range(8):
        insert_listing(db, f"l{i}", "hostile-ref", f"Listing {i}",
                       10000 + i * 500, "Dealer A", None, None, None)
    html = build_and_render(db)
    assert "CURRENT OBSERVED MARKET RANGE" in html
    assert "How to read this market" in html
    assert "Potential deal" in html
    assert "Why there is no market range yet" not in html


def test_related_rows_never_enter_exact_tab(db):
    for i in range(5):
        insert_listing(db, f"e{i}", "hostile-ref", f"Exact {i}",
                       10000 + i * 500, "Dealer A", None, None, None)
    for i in range(2):
        insert_listing(db, f"r{i}", "hostile-ref", f"Related {i}",
                       5000 + i * 100, "Vintage Dealer", None, None, None,
                       exact=0)
    html = build_and_render(db)
    exact_tbl = re.search(r'<table class="listing-table" id="tbl-exact">(.*?)</table>',
                          html, re.S).group(1)
    related_tbl = re.search(r'<table class="listing-table hidden" id="tbl-related">(.*?)</table>',
                            html, re.S).group(1)
    exact_ids = set(re.findall(r'data-listing-id="(e\d)"', exact_tbl))
    related_ids = set(re.findall(r'data-listing-id="(r\d)"', related_tbl))
    assert exact_ids == {"e0", "e1", "e2", "e3", "e4"}
    assert related_ids == {"r0", "r1"}
    assert "r0" not in exact_tbl


def test_build_report_rejects_unknown_slug(db):
    assert build_report(db, "does-not-exist") is None