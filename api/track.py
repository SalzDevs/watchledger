"""Vercel Python function: POST /api/track.

Adds a watch to a user's watchlist with alert preferences (double opt-in:
the user is stored unconfirmed until they hit /confirm?token=...). Persists
to Vercel Blob (free tier) as:
  watchledger/index.json            {email_hash: token}
  watchledger/users/<token>.json    {email, confirmed, alerts, items}

Stdlib only; Vercel's Python runtime wraps this WSGI app (exported as `app`).
"""

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request
import urllib.parse

BLOB_BASE = "https://blob.vercel-storage.com"
TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN", "")

ALLOWED_SLUG_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789-")
ALERT_TYPES = {"new_listing", "below_typical", "range_change", "coverage_ready"}


def slug_ok(slug):
    if not slug or len(slug) > 80:
        return False
    return all(c in ALLOWED_SLUG_CHARS for c in slug)


def email_ok(email):
    if not email or len(email) > 254:
        return False
    return "@" in email and "." in email.split("@")[-1]


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


def read_user(token):
    try:
        return json.loads(blob_get("watchledger/users/" + token + ".json"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except Exception:
        return None


def write_user(token, data):
    blob_put("watchledger/users/" + token + ".json", json.dumps(data))


def respond(start_response, status, body, ctype="application/json; charset=utf-8"):
    data = body.encode("utf-8") if isinstance(body, str) else body
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

    action = params.get("action", [""])[0]
    email = (params.get("email", [""])[0] or "").strip().lower()
    slug = (params.get("slug", [""])[0] or "").strip().lower()
    alerts = [a for a in params.get("alerts", []) if a in ALERT_TYPES]
    if not alerts:
        alerts = ["new_listing"]

    if not TOKEN:
        return respond(start_response, "503 Service Unavailable",
                       json.dumps({"error": "tracking is not configured"}))

    if action != "track" or not email_ok(email) or not slug_ok(slug):
        return respond(start_response, "400 Bad Request",
                       json.dumps({"error": "email and slug required"}))

    index = read_index()
    email_hash = hashlib.sha256(email.encode()).hexdigest()
    token = index.get(email_hash)
    if not token:
        token = secrets.token_hex(16)
        index[email_hash] = token

    user = read_user(token) or {"email": email, "items": []}
    user["email"] = email
    user.setdefault("confirmed", False)
    user.setdefault("alerts", {})
    user["alerts"][slug] = alerts
    items = user.get("items", [])
    if not any(item.get("slug") == slug for item in items):
        items.append({"slug": slug, "created_at": time.time()})
        user["items"] = items
    confirm_token = hashlib.sha256(
        (token + slug + "confirm" + secrets.token_hex(8)).encode()).hexdigest()
    user["confirm_token"] = confirm_token

    try:
        write_user(token, user)
        blob_put("watchledger/index.json", json.dumps(index))
    except Exception:
        return respond(start_response, "503 Service Unavailable",
                       json.dumps({"error": "could not persist watchlist"}))

    return respond(start_response, "200 OK", json.dumps({
        "ok": True, "slug": slug, "alerts": alerts,
        "confirm_url": "/confirm?token=" + confirm_token,
    }))
