import os
import re
import sqlite3
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import http.server

import pytest

import config
import server as server_mod

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
def live_server(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO references_meta VALUES (?,?,?,?,?,?,?,?)",
        ("rolex-submariner-126610ln", "Rolex", "126610LN", "Submariner",
         "Steel", "https://example.com/ref", "https://example.com/src",
         1700000000))
    for i in range(8):
        conn.execute(
            "INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"l{i}", "rolex-submariner-126610ln", f"Listing {i}",
             10000 + i * 500, "USD", "Excellent", "full_set", "Steel",
             41, None, 2024, "dealer", "Dealer A", 1, None, None, None,
             1, "https://example.com/src", 1700000000))
    conn.commit()
    conn.close()

    monkeypatch.setattr(server_mod, "DB_PATH", str(db_path))
    monkeypatch.setattr(config, "DB_PATH", str(db_path))

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    yield base
    httpd.shutdown()


def get(base, path):
    return urllib.request.urlopen(base + path)


def get_status(base, path):
    try:
        with get(base, path) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def test_security_headers_present(live_server):
    with get(live_server, "/") as resp:
        headers = dict(resp.headers)
    assert headers.get("Content-Security-Policy", "").startswith("default-src 'self'")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "Permissions-Policy" in headers


def test_csp_blocks_inline_scripts(live_server):
    with get(live_server, "/") as resp:
        body = resp.read().decode("utf-8")
    assert "<script>" not in body
    assert "<script src=" in body
    assert "onclick=" not in body


def test_homepage_search_data_is_safe_json_block(live_server):
    with get(live_server, "/") as resp:
        body = resp.read().decode("utf-8")
    block = re.search(r'<script id="reference-data" type="application/json">(.*?)</script>',
                      body, re.S)
    assert block is not None


def test_report_page_uses_external_js(live_server):
    with get(live_server, "/reference/rolex-submariner-126610ln") as resp:
        body = resp.read().decode("utf-8")
    assert '<script src="/static/report.js" defer></script>' in body
    assert "<script>" not in body


def test_traversal_slug_returns_404(live_server):
    assert get_status(live_server, "/reference/../../etc/passwd") == 404
    assert get_status(live_server, "/reference/%2e%2e/%2e%2e/etc/passwd") == 404


def test_markup_slug_returns_404(live_server):
    assert get_status(live_server, "/reference/%3Cscript%3Ealert(1)%3C/script%3E") == 404


def test_javascript_api_slug_returns_404(live_server):
    assert get_status(live_server, "/api/reference/javascript:alert(1)") == 404


def test_unknown_slug_returns_404_without_stack_trace(live_server):
    status = get_status(live_server, "/reference/rolex-gmt-126710blro")
    assert status == 404


def test_unknown_path_returns_404(live_server):
    assert get_status(live_server, "/no/such/path") == 404


def test_static_js_served(live_server):
    with get(live_server, "/static/report.js") as resp:
        body = resp.read().decode("utf-8")
    assert "textContent" in body
    assert "innerHTML" not in body
    with get(live_server, "/static/home.js") as resp:
        body = resp.read().decode("utf-8")
    assert "textContent" in body
    assert "innerHTML" not in body


def test_api_returns_valid_json(live_server):
    import json as jsonlib
    with get(live_server, "/api/reference/rolex-submariner-126610ln") as resp:
        data = jsonlib.load(resp)
    assert data["n_exact"] == 8
    assert data["limited"] is False