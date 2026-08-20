"""Vercel Python function: POST /api/request.

Records a coverage request for an untracked watch query (demand capture).
Persists to Vercel Blob as watchledger/requests.json — a simple demand queue.
Stdlib only; Vercel's Python runtime wraps this WSGI app (exported as `app`).
"""

import json
import os
import time
import urllib.error
import urllib.request
import urllib.parse

BLOB_BASE = "https://blob.vercel-storage.com"
TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")


def _url(pathname):
    return BLOB_BASE + "/" + pathname


def blob_get(pathname):
    req = urllib.request.Request(
        _url(pathname), headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8")


def blob_put(pathname, data):
    req = urllib.request.Request(
        _url(pathname), data=data.encode("utf-8"), method="PUT",
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status


def read_requests():
    try:
        return json.loads(blob_get("watchledger/requests.json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    except Exception:
        return []


def respond(start_response, status, body, ctype="application/json; charset=utf-8"):
    data = body.encode("utf-8")
    start_response(status, [
        ("Content-Type", ctype),
        ("Content-Length", str(len(data))),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("X-Frame-Options", "DENY"),
        ("Cache-Control", "no-store"),
    ])
    return [data]


def app(environ, start_response):
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(length).decode("utf-8") if length else ""
    params = urllib.parse.parse_qs(body)

    query = (params.get("query", [""])[0] or "").strip()[:200]

    if not TOKEN:
        return respond(start_response, "503 Service Unavailable",
                       json.dumps({"error": "tracking is not configured"}))

    if not query:
        return respond(start_response, "400 Bad Request",
                       json.dumps({"error": "query required"}))

    try:
        requests = read_requests()
        requests.append({"query": query, "requested_at": time.time()})
        blob_put("watchledger/requests.json", json.dumps(requests))
    except Exception:
        return respond(start_response, "503 Service Unavailable",
                       json.dumps({"error": "could not persist request"}))

    return respond(start_response, "200 OK",
                   json.dumps({"ok": True, "query": query}))