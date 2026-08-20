"""Vercel Python function: GET /confirm?token=...

Completes double opt-in for tracking. Confirms the user's email and marks
the watchlist as active in Vercel Blob. Stdlib only; Vercel's Python
runtime wraps this WSGI app (exported as `app`).
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


def read_index():
    try:
        return json.loads(blob_get("watchledger/index.json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    except Exception:
        return {}


def read_user(token):
    try:
        return json.loads(blob_get("watchledger/users/" + token + ".json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


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
    found = None
    for h, t in index.items():
        if t == token:
            found = h
            break

    if not found:
        return respond(start_response, "404 Not Found",
                       "<h1>Not found</h1><p>This confirmation link is not "
                       "valid or has already been used.</p>")

    user = read_user(token)
    if user is None:
        return respond(start_response, "404 Not Found",
                       "<h1>Not found</h1><p>This confirmation link is not "
                       "valid or has already been used.</p>")

    user["confirmed"] = True
    user.pop("confirm_token", None)
    try:
        blob_put("watchledger/users/" + token + ".json", json.dumps(user))
    except Exception:
        return respond(start_response, "503 Service Unavailable",
                       "<h1>Could not confirm</h1><p>Please try again.</p>")

    return respond(start_response, "200 OK",
                   "<h1>You are tracking this watch</h1><p>Your alert "
                   "preferences are confirmed. One-click unsubscribe is "
                   "available in every email.</p>")