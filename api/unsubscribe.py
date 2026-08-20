"""Vercel Python function: GET /unsubscribe?token=...

Deletes the user's watchlist entries from Vercel Blob. Stdlib only;
Vercel's Python runtime wraps this WSGI app (exported as `app`).
"""

import json
import os
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


def blob_delete(pathname):
    req = urllib.request.Request(
        _url(pathname), method="DELETE",
        headers={"Authorization": "Bearer " + TOKEN})
    with urllib.request.urlopen(req) as resp:
        return resp.status


def read_index():
    try:
        return json.loads(blob_get("watchledger/index.json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    except Exception:
        return {}


def write_index(index):
    blob_put("watchledger/index.json", json.dumps(index))


def respond(start_response, status, body, ctype="text/html; charset=utf-8"):
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
    query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
    token = (query.get("token", [""])[0] or "").strip()

    if not TOKEN:
        return respond(start_response, "503 Service Unavailable",
                       "<h1>Tracking unavailable</h1><p>This deployment has "
                       "not been configured for alerts.</p>")

    if not token:
        return respond(start_response, "400 Bad Request",
                       "<h1>Missing token</h1>")

    index = read_index()
    email_hash = None
    for h, t in index.items():
        if t == token:
            email_hash = h
            break

    if not email_hash:
        return respond(start_response, "404 Not Found",
                       "<h1>Not found</h1><p>This unsubscribe link is not "
                       "valid or has already been used.</p>")

    try:
        blob_delete("watchledger/users/" + token + ".json")
        index.pop(email_hash, None)
        write_index(index)
    except Exception:
        return respond(start_response, "503 Service Unavailable",
                       "<h1>Could not unsubscribe</h1><p>Please try again.</p>")

    return respond(start_response, "200 OK",
                   "<h1>You are unsubscribed</h1><p>You will no longer "
                   "receive watchledger alerts. You can resubscribe from "
                   "any watch page.</p>")
