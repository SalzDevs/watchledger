"""Build a fully static deployment of watchledger into out/.

Vercel free (Hobby) can serve the site as pure static files: the homepage,
every reference report, the raw payloads, and the deterministic JSON API.
The only dynamic endpoints (tracking, unsubscribe) are separate serverless
functions under api/ (see api/track.py and api/unsubscribe.py).

Everything here is deterministic: build_db and report run the same pipeline
used by `make db report`.
"""

import json
import os
import shutil
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import build_db
import report as report_mod
import server as server_mod
from config import DB_PATH, RAW_DIR, REPORTS_DIR, STATIC_DIR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "out")


def main():
    build_db.main()
    report_mod.main()

    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "reports"))
    os.makedirs(os.path.join(OUT, "api-json", "reference"))
    os.makedirs(os.path.join(OUT, "raw"))

    shutil.copytree(STATIC_DIR, os.path.join(OUT, "static"))

    for root, _dirs, files in os.walk(RAW_DIR):
        rel = os.path.relpath(root, RAW_DIR)
        dst = os.path.join(OUT, "raw", rel)
        os.makedirs(dst, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(dst, f))

    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    stats = server_mod.index_stats(db)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(server_mod.render_home(stats))
    with open(os.path.join(OUT, "api-json", "references.json"), "w",
              encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, default=str)

    for slug in sorted(os.listdir(REPORTS_DIR)):
        if not slug.endswith(".html"):
            continue
        name = slug[:-5]
        shutil.copy2(os.path.join(REPORTS_DIR, slug),
                     os.path.join(OUT, "reports", slug))
        d = report_mod.build_report(db, name)
        if d:
            with open(os.path.join(OUT, "api-json", "reference",
                                   f"{name}.json"), "w", encoding="utf-8") as fh:
                json.dump(d, fh, indent=2, default=str)

    with open(os.path.join(OUT, "raw", "index.html"), "w", encoding="utf-8") as fh:
        fh.write(server_mod.render_raw_index())
    db.close()

    n_html = len([f for f in os.listdir(os.path.join(OUT, "reports"))
                  if f.endswith(".html")])
    n_api = len(os.listdir(os.path.join(OUT, "api-json", "reference")))
    print(f"site built: {n_html} reports, {n_api} api json files")


if __name__ == "__main__":
    main()