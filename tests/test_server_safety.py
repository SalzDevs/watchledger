import json as jsonlib
import os
import re
import sqlite3
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import http.server

import pytest

import config
import server as server_mod
from conftest import insert_listing, insert_ref, run_pipeline
from src.schema import SCHEMA


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    db_path = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    insert_ref(conn, slug="rolex-submariner-126610ln", ref="126610LN",
               model="Submariner")
    for i in range(8):
        insert_listing(conn, f"l{i}", "rolex-submariner-126610ln",
                       f"Listing {i}", 10000 + i * 500, f"Dealer {i}")
    run_pipeline(conn, slug="rolex-submariner-126610ln", ref="126610LN",
                 model="Submariner")
    insert_ref(conn, slug="rolex-explorer-ii-226570-polar", ref="226570",
               model="Explorer II", material="Steel")
    for i in range(2):
        insert_listing(conn, f"e{i}", "rolex-explorer-ii-226570-polar",
                       f"Explorer {i}", 10500 + i * 500, f"Dealer {i}")
    run_pipeline(conn, slug="rolex-explorer-ii-226570-polar", ref="226570",
                 model="Explorer II", material="Steel")
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


def post(base, path, data):
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(base + path, data=body)
    return urllib.request.urlopen(req)


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
    assert "upgrade-insecure-requests" not in headers.get("Content-Security-Policy", "")
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
    with get(live_server, "/api/reference/rolex-submariner-126610ln.json") as resp:
        data = jsonlib.load(resp)
    assert data["n_exact"] == 8
    assert data["valid"] is True
    # 8 listings -> Medium coverage, so overall can never exceed Medium.
    assert data["confidence_state"] == "Medium"


def test_api_requires_existing_slug(live_server):
    assert get_status(live_server, "/api/reference/no-such-ref.json") == 404


def test_sources_page_renders(live_server):
    with get(live_server, "/sources") as resp:
        body = resp.read().decode("utf-8")
    assert "Data sources" in body
    assert "mostexpensivewatches.net" in body


def test_track_endpoint_requires_email_and_slug(live_server):
    status = get_status(live_server, "/api/track")
    assert status == 405


def test_track_endpoint_persists_watchlist(live_server, tmp_path, monkeypatch):
    db_path = tmp_path / "watch.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    insert_ref(conn, slug="rolex-submariner-126610ln", ref="126610LN",
               model="Submariner")
    insert_listing(conn, "l0", "rolex-submariner-126610ln", "Listing 0",
                   10000, "Dealer 0")
    run_pipeline(conn, slug="rolex-submariner-126610ln", ref="126610LN",
                 model="Submariner")
    conn.commit()

    monkeypatch.setattr(server_mod, "DB_PATH", str(db_path))
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), server_mod.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_port}"

    resp = post(base, "/api/track",
                {"action": "track", "email": "buyer@example.com",
                 "slug": "rolex-submariner-126610ln"})
    assert resp.status == 200
    data = jsonlib.load(resp)
    assert data["ok"] is True

    conn2 = sqlite3.connect(db_path)
    users = conn2.execute("SELECT email FROM watch_users").fetchall()
    items = conn2.execute("SELECT reference_slug FROM watchlist_item").fetchall()
    conn2.close()
    assert users == [("buyer@example.com",)]
    assert items == [("rolex-submariner-126610ln",)]
    httpd.shutdown()


def test_unsubscribe_endpoint_deactivates(live_server):
    import sqlite3 as _sq
    db_path = server_mod.DB_PATH
    conn = _sq.connect(db_path)
    conn.execute("INSERT INTO watch_users (id, email, unsubscribe_token, "
                 "created_at) VALUES ('u@x.com','u@x.com','tok123',1)")
    conn.execute("INSERT INTO watchlist_item (id, user_id, reference_slug, "
                 "created_at, active) VALUES ('w1','u@x.com','slug-x',1,1)")
    conn.commit()
    conn.close()

    with get(live_server, "/unsubscribe?token=tok123") as resp:
        body = resp.read().decode("utf-8")
    assert "You are unsubscribed" in body

    conn = _sq.connect(db_path)
    items = conn.execute("SELECT COUNT(*) FROM watchlist_item").fetchone()[0]
    conn.close()
    assert items == 0


def test_bad_unsubscribe_token_returns_404(live_server):
    assert get_status(live_server, "/unsubscribe?token=nope") == 404