"""Fetch raw JSON payloads from the MEW public API into data/raw/.

Every payload is stored verbatim with a sidecar record of source URL and
fetch time. The raw files are the immutable source of truth; the SQLite
ledger is derived from them.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from config import RAW_DIR, TARGETS, MEW_BASE


def norm(x):
    return re.sub(r"[^a-z0-9]", "", (x or "").lower())


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "watchledger-poc/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_payload(kind, key, payload, source_url):
    os.makedirs(os.path.join(RAW_DIR, kind), exist_ok=True)
    safe = key.replace("/", "_").replace(" ", "_").lower()
    path = os.path.join(RAW_DIR, kind, f"{safe}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"source_url": source_url, "fetched_at": time.time(),
                   "payload": payload}, fh, indent=1)
    return path


def fetch_all():
    paths = {}

    print("== fetching reference index ==")
    refs = http_get(f"{MEW_BASE}/api/references?limit=1000")
    paths["reference_index"] = save_payload("index", "references", refs,
                                            f"{MEW_BASE}/api/references?limit=1000")

    print(f"== fetching {len(TARGETS)} target references ==", flush=True)
    resolved = {}
    for brand, ref in TARGETS:
        key = f"{brand} {ref}"
        try:
            r = http_get(f"{MEW_BASE}/api/references/resolve?q={urllib.parse.quote(ref)}")
        except Exception as exc:
            print(f"  ! {key}: resolve failed ({exc})", flush=True)
            continue
        target_n = norm(ref)
        matches = [m for m in (r.get("matches") or [])
                   if (m.get("brand") or "").lower() == brand.lower()
                   and (target_n in norm(m.get("ref"))
                        or norm(m.get("ref")) in target_n
                        or norm(m.get("ref")) == target_n)]
        if not matches:
            print(f"  - {key}: no brand+ref match", flush=True)
            continue
        slug = matches[0]["slug"]
        resolved[key] = slug
        try:
            detail = http_get(f"{MEW_BASE}/api/references/{slug}")
        except Exception as exc:
            print(f"  ! {key}: detail failed ({exc})", flush=True)
            continue
        p = save_payload("references", slug, detail,
                         f"{MEW_BASE}/api/references/{slug}")
        paths[slug] = p
        stats = detail.get("listing_stats") or {}
        print(f"  + {key} -> {slug} (listings: {stats.get('count', 0)}, "
              f"auction lots: {len(detail.get('auction_lots') or [])})", flush=True)

        # Exact-reference listings via the listing search endpoint.
        # The per-reference payload mixes in related/vintage listings; the
        # search endpoint returns genuine exact matches for the reference.
        ref_query = matches[0].get("ref") or ref
        try:
            hit = http_get(f"{MEW_BASE}/api/listings/search?q={urllib.parse.quote(ref_query)}")
        except Exception as exc:
            print(f"  ! {key}: exact search failed ({exc})", flush=True)
            continue
        items = hit.get("items") or []
        if items:
            exact = {"total": hit.get("total", len(items)), "items": items}
            save_payload("exact", slug, exact,
                         f"{MEW_BASE}/api/listings/search?q={urllib.parse.quote(ref_query)}")
            print(f"  = {key}: {len(items)} exact-match listings (total {hit.get('total', '?')})",
                  flush=True)
        else:
            print(f"  - {key}: no exact-match listings found", flush=True)

    # The auctions endpoint ignores page/offset params and always returns the
    # same first 250 lots; a single page is the full reachable dataset.
    print("== fetching auction dataset (single page, 250-lot cap) ==", flush=True)
    page = http_get(f"{MEW_BASE}/api/auctions?limit=250")
    all_lots = page.get("auction_lots") or []
    payload = {"total": len(all_lots), "auction_lots": all_lots}
    paths["auctions_full"] = save_payload("index", "auctions_full", payload,
                                          f"{MEW_BASE}/api/auctions (single page)")
    print(f"  + {len(all_lots)} auction lots", flush=True)

    with open(os.path.join(RAW_DIR, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"resolved": resolved, "fetched_at": time.time()}, fh, indent=1)
    return paths


if __name__ == "__main__":
    fetch_all()