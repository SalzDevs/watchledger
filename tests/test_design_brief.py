"""Tests for the design-brief improvement report (design.md, 2026 revision).

Covers: invalid ranges never shown for limited/zero states, overall
confidence never exceeds its weakest dimension, likely-duplicate clustering,
exclusion reasons, state-specific evidence, canonical titles, price
positions, related relevance groups, SEO fundamentals, and tracking alerts.
"""

import json as jsonlib
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import market
import server as server_mod
from src.report import build_report, render
from conftest import insert_listing, insert_ref, run_pipeline
from test_server_safety import live_server


def build_and_render(db, slug="hostile-ref"):
    run_pipeline(db, slug)
    d = build_report(db, slug)
    assert d is not None
    return d, render(d)


def many_listings(db, n, slug="hostile-ref", prefix="Listing", base=10000,
                  step=500):
    for i in range(n):
        insert_listing(db, f"{prefix}{i}", slug, f"{prefix} {i}",
                       base + i * step, f"Dealer {i}")


# --- design brief #1: never show an invalid range ---------------------------

def test_limited_report_api_never_exposes_published_range(db):
    insert_ref(db)
    many_listings(db, 4)  # only 4 clusters -> limited
    d, _ = build_and_render(db)
    assert d["valid"] is False
    assert d["band_lo"] is None
    assert d["band_hi"] is None
    assert d["listing_median"] is None


def test_limited_page_has_no_deal_fair_above_language(db):
    insert_ref(db)
    many_listings(db, 4)
    d, html = build_and_render(db)
    assert "MARKET COVERAGE DEVELOPING" in html
    assert "No published range yet" in html
    assert "Potential deal" not in html
    assert "Fair price" not in html
    assert "High above market" not in html


def test_limited_page_keeps_raw_spread_only_in_evidence(db):
    insert_ref(db)
    many_listings(db, 4)
    d, html = build_and_render(db)
    spread = re.search(
        r'Observed asking prices span \$([\d,]+)–\$([\d,]+)\.\s*'
        r'This is <b>not a published market range</b>', html)
    assert spread, "raw spread must live in evidence with a disclaimer"


# --- design brief #2: overall confidence = weakest dimension ----------------

def test_overall_confidence_never_exceeds_weakest_dimension(db):
    insert_ref(db)
    many_listings(db, 8)  # coverage Medium (8), diversity High (8)
    d, _ = build_and_render(db)
    assert d["valid"] is True
    assert d["coverage"] == "Medium"
    assert d["diversity"] == "High"
    assert d["freshness_dim"] == "High"
    # overall must be the *weakest* dimension, i.e. Medium, never High
    assert d["confidence_state"] == "Medium"


def test_high_confidence_requires_high_coverage(db):
    insert_ref(db)
    # 21 listings, 21 dealers, all fresh -> every dimension High
    many_listings(db, 21, prefix="L", base=10000, step=100)
    d, _ = build_and_render(db)
    assert d["coverage"] == "High"
    assert d["diversity"] == "High"
    assert d["freshness_dim"] == "High"
    assert d["confidence_state"] == "High"


# --- design brief #3: likely-duplicate clustering ---------------------------

def test_likely_duplicates_share_cluster(db):
    insert_ref(db)
    # Two rows: same dealer, same config, near-identical price, same title.
    for i in range(2):
        insert_listing(db, f"dup{i}", "hostile-ref", "Rolex Submariner 126610LN",
                       12000 + i * 50, "Dealer A", None, None, None)
    # A third row from the same dealer but clearly different price.
    insert_listing(db, "diff", "hostile-ref", "Rolex Submariner 126610LN",
                   9000, "Dealer A", None, None, None)
    run_pipeline(db, "hostile-ref")
    db.commit()
    clusters = db.execute(
        "SELECT listing_cluster_id, COUNT(*) FROM listings "
        "GROUP BY listing_cluster_id ORDER BY 2 DESC").fetchall()
    assert len(clusters) == 2, clusters  # dup pair + distinct row
    basis = db.execute(
        "SELECT cluster_confidence, cluster_basis FROM listing_cluster "
        "WHERE id IN (SELECT listing_cluster_id FROM listings "
        "WHERE id IN ('dup0','dup1'))").fetchall()
    assert all(b[0] < 1.0 for b in basis)
    assert any("signals" in (b[1] or "") for b in basis)


def test_likely_duplicate_evidence_surfaces(db):
    insert_ref(db)
    insert_listing(db, "dup0", "hostile-ref", "Rolex Submariner 126610LN",
                   12000, "Dealer A", None, None, None)
    insert_listing(db, "dup1", "hostile-ref", "Rolex Submariner 126610LN",
                   12050, "Dealer A", None, None, None)
    many_listings(db, 6, prefix="L", base=11000, step=200)
    d, html = build_and_render(db)
    assert "likely duplicates" in html


# --- design brief #4: related relevance ranking -----------------------------

def test_related_rows_ranked_into_relevance_groups(db):
    insert_ref(db, slug="tudor-ref", ref="M79030N", model="Black Bay 58",
               material="Steel")
    insert_listing(db, "e0", "tudor-ref", "Black Bay 58", 10000,
                   "Dealer 0")
    insert_listing(db, "r1", "tudor-ref", "Tudor Black Bay 58 ref M79030N",
                   9000, "Dealer 1", exact=0)
    insert_listing(db, "r2", "tudor-ref", "Tudor Vintage Submariner 79090",
                   7000, "Dealer 2", exact=0, mat="Yellow Gold")
    d, html = build_and_render(db, slug="tudor-ref")
    assert "Closest alternatives" in html
    assert "Historical alternatives" in html
    assert "Other variants" not in html or "Tudor Vintage" not in html


# --- design brief #5: configuration explanation -----------------------------

def test_selected_configuration_shown(db):
    insert_ref(db, ref="5712/1A", model="Nautilus", material="Steel")
    insert_listing(db, "l1", "hostile-ref", "Nautilus 5712/1A", 100000,
                   "Dealer A")
    insert_listing(db, "v1", "hostile-ref", "Nautilus 5712/1R", 120000,
                   "Gold Dealer", mat="Yellow Gold")
    d, html = build_and_render(db)
    assert "SELECTED CONFIGURATION" in html
    assert "Yellow Gold configuration; excluded from" in html


# --- design brief #6: canonical titles --------------------------------------

def test_canonical_title_not_raw_source_title(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref",
                   "Rolex Rolex Submariner | REF. 126610LN | Box & Papers | 2024",
                   12000, "Dealer A", None, None, None)
    d, html = build_and_render(db)
    listing = d["listing_data"]["l1"]
    assert "Rolex Submariner" in listing["title"]
    assert "126610LN" in listing["title"] or "126610LN" in listing["subtitle"]
    # raw title only in the drawer payload
    assert listing["raw_title"].startswith("Rolex Rolex Submariner")
    # strip the JSON drawer block, then the raw title must not appear
    # anywhere in the visible page
    json_block = re.search(r'<script id="listing-data" '
                           r'type="application/json">(.*?)</script>',
                           html, re.S)
    assert json_block, "listing-data block not found"
    visible = html.replace(json_block.group(0), "")
    assert "Rolex Rolex Submariner | REF." not in visible
    assert "Box &amp; Papers | 2024" not in visible


# --- design brief #7: price position for every valid listing ----------------

def test_fair_rows_show_relative_position(db):
    insert_ref(db)
    many_listings(db, 8)
    d, html = build_and_render(db)
    listing = d["listing_data"]["Listing3"]  # 11500 vs typical ~12500
    assert "% below typical" in listing["pct"] or "% above typical" in listing["pct"]


# --- design brief #8: state-specific evidence -------------------------------

def test_evidence_state_specific(db):
    insert_ref(db)
    insert_listing(db, "l1", "hostile-ref", "A listing", 12000,
                   "Dealer A", None, None, None)
    d0, html0 = build_and_render(db)  # one listing -> limited
    assert "CURRENT MARKET COVERAGE" in html0
    assert "EVIDENCE BEHIND THIS RANGE" not in html0

    # zero-data reference
    insert_ref(db, slug="zero-ref", ref="99999", model="Zero Watch",
               material="Steel")
    insert_listing(db, "z1", "zero-ref", "Zero Watch", None, "Dealer Z",
                   exact=0)
    d1, html1 = build_and_render(db, slug="zero-ref")
    assert "CURRENT TRACKING STATUS" in html1
    assert "broader related listings available" in html1


def test_observed_not_active_language(db):
    insert_ref(db)
    many_listings(db, 8)
    d, html = build_and_render(db)
    assert "observed" in html.lower()
    assert "active listings" not in html.lower().replace("activate", "")


# --- design brief #10: exclusion reasons ------------------------------------

def test_excluded_reason_in_drawer_data(db):
    insert_ref(db)
    insert_listing(db, "parts", "hostile-ref", "A bracelet listing", 12000,
                   "Parts Dealer", None, None, None)
    insert_listing(db, "l2", "hostile-ref", "A normal watch", 13000,
                   "Dealer A", None, None, None)
    d, _ = build_and_render(db)
    assert d["listing_data"]["parts"]["exclusion_reason"]
    assert d["listing_data"]["l2"]["exclusion_reason"] == ""


# --- design brief #18: SEO fundamentals -------------------------------------

def test_report_has_canonical_meta_and_jsonld(db):
    insert_ref(db)
    many_listings(db, 8)
    d, html = build_and_render(db)
    assert 'rel="canonical" href="/reference/hostile-ref"' in html
    assert 'name="description"' in html
    assert 'property="og:title"' in html
    assert 'application/ld+json' in html
    assert "AggregateOffer" in html


# --- design brief #9: tracking alert preferences ----------------------------

def test_track_accepts_alert_preference_types(live_server):
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode([
        ("action", "track"), ("email", "alerts@example.com"),
        ("slug", "rolex-submariner-126610ln"),
        ("alerts", "new_listing"), ("alerts", "range_change"),
    ]).encode()
    req = urllib.request.Request(live_server + "/api/track", data=body)
    with urllib.request.urlopen(req) as resp:
        data = jsonlib.load(resp)
    assert data["ok"] is True
    assert "new_listing" in data["alerts"]
    assert "range_change" in data["alerts"]
    assert data["confirm_url"].startswith("/confirm?token=")


def test_confirm_endpoint_flips_confirmed(db, live_server):
    import sqlite3 as _sq
    import urllib.request

    db_path = server_mod.DB_PATH
    conn = _sq.connect(db_path)
    conn.execute("INSERT INTO watch_users (id, email, unsubscribe_token, "
                 "confirm_token, confirmed, created_at) "
                 "VALUES ('c@x.com','c@x.com','tok1','conf1',0,1)")
    conn.commit()
    conn.close()

    with urllib.request.urlopen(live_server + "/confirm?token=conf1") as resp:
        body = resp.read().decode("utf-8")
    assert "You are tracking this watch" in body

    conn = _sq.connect(db_path)
    confirmed = conn.execute(
        "SELECT confirmed FROM watch_users WHERE email='c@x.com'").fetchone()[0]
    conn.close()
    assert confirmed == 1


def test_bad_confirm_token_returns_404(live_server):
    import urllib.error
    try:
        urllib.request.urlopen(live_server + "/confirm?token=nope")
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_methodology_page_renders(live_server):
    with urllib.request.urlopen(live_server + "/methodology") as resp:
        body = resp.read().decode("utf-8")
    assert "Minimum gates for a published range" in body
    assert "asking prices" in body.lower()


def test_robots_and_sitemap_serve(live_server):
    import urllib.request
    with urllib.request.urlopen(live_server + "/robots.txt") as resp:
        body = resp.read().decode("utf-8")
    assert "Sitemap:" in body
    with urllib.request.urlopen(live_server + "/sitemap.xml") as resp:
        body = resp.read().decode("utf-8")
    assert "rolex-submariner-126610ln" in body
    assert "/methodology" in body


# --- design brief #13: demand capture ---------------------------------------

def test_request_coverage_endpoint_records_query(live_server):
    import urllib.parse
    import urllib.request
    body = urllib.parse.urlencode({"query": "Rolex 16610"}).encode()
    req = urllib.request.Request(live_server + "/api/request", data=body)
    with urllib.request.urlopen(req) as resp:
        data = jsonlib.load(resp)
    assert data["ok"] is True
    assert data["query"] == "Rolex 16610"


def test_homepage_split_published_and_developing(live_server):
    with urllib.request.urlopen(live_server + "/") as resp:
        body = resp.read().decode("utf-8")
    assert "PUBLISHED MARKET RANGES" in body
    assert "COVERAGE DEVELOPING" in body
    assert "discovery-filters" in body