# WatchLedger — Security and Safe Rendering Implementation Guide

## What this document is for

This guide explains **exactly what to change** in the WatchLedger repository to make the website safe when it displays data from external watch-listing sources.

Follow the steps in order. Do not skip a step because the current data source appears trustworthy. A dealer name, listing title, image URL, or listing URL is **external input**. Treat it as hostile until the application has validated it.

This guide replaces the former visual design brief. It covers only **security and rendering safety**.

---

# 1. The problem, in plain English

WatchLedger downloads public data from an external API and displays it on its own website.

External values include:

- Watch titles
- Dealer names
- Condition text
- Box-and-papers text
- Materials
- Image URLs
- Original listing URLs
- Reference/model metadata

A bad data source, compromised dealer account, or malicious listing could return a title such as:

```html
<img src=x onerror="alert('Your website was hacked')">
```

or a listing link such as:

```text
javascript:alert(document.cookie)
```

The browser must display these values as **plain text**, never as executable HTML or JavaScript.

## The current dangerous areas

The current repository has three main rendering problems:

1. `src/report.py` creates the listing-analysis drawer with JavaScript `innerHTML` and external listing data.
2. `src/server.py` creates homepage search suggestions with JavaScript `innerHTML` and external reference data.
3. The application embeds external URLs into image and link attributes without first checking the URL scheme and destination.

There is also a related problem:

4. The HTML sends inline scripts and inline event handlers such as `onclick="..."`. This makes it difficult to add a strict Content Security Policy.

The solution is:

- Validate every URL.
- Escape every server-rendered text value.
- Never use `innerHTML` for source-provided data.
- Render browser UI with DOM nodes and `textContent`.
- Move JavaScript into external static files.
- Add browser security headers.
- Add tests that prove unsafe data stays harmless.

---

# 2. Definition of done

Do not call this work complete until every item below is true.

- [ ] A listing title containing `<script>alert(1)</script>` appears as visible text and does not run.
- [ ] A listing title containing `</script><script>alert(1)</script>` cannot break an embedded JSON data block.
- [ ] A dealer name containing HTML is displayed as text only.
- [ ] `javascript:`, `data:`, `file:`, and malformed URLs are never emitted as listing links or image sources.
- [ ] Listing details are rendered with `textContent`, not `innerHTML`.
- [ ] Homepage search suggestions are rendered with `textContent`, not `innerHTML`.
- [ ] JavaScript is loaded only from static files served by WatchLedger.
- [ ] There are no inline `onclick=`, `onerror=`, or source-data-derived inline scripts.
- [ ] The response has a Content Security Policy and standard security headers.
- [ ] SQLite errors are logged on the server but are not returned to visitors.
- [ ] Tests cover XSS, bad URLs, path traversal, and the drawer/search UI rendering rules.

---

# 3. Work in this order

Do the work in exactly this order:

1. Create URL and JSON safety helpers.
2. Validate data while building the database.
3. Stop putting complete listing JSON inside HTML attributes.
4. Move all inline browser code to static JavaScript files.
5. Replace `innerHTML` with safe DOM creation.
6. Add security headers and safer error handling.
7. Remove inline styles and inline event attributes.
8. Add tests.
9. Run the verification checklist.

Do not start with styling. Make the data safe first.

---

# 4. Add one central security helper module

## File to create

Create: `src/security.py`

Do not scatter URL validation and JSON escaping across multiple files. Put the rules in this one file so every page uses the same policy.

## Paste this code into `src/security.py`

```python
"""Security helpers for untrusted third-party listing data.

All data received from public APIs is untrusted. These helpers provide the
single approved way to put text, URLs, and JSON-derived values into HTML.
"""

from __future__ import annotations

import html
import json
from typing import Any
from urllib.parse import urlparse


# Start strict. Add a hostname only after verifying that it is a real source
# WatchLedger is willing to send visitors to.
ALLOWED_EXTERNAL_SCHEMES = {"https"}


def safe_text(value: Any) -> str:
    """Return a value that is safe to place inside HTML text or attributes."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def safe_external_url(value: Any) -> str:
    """Return an approved external HTTPS URL, or an empty string.

    Never return arbitrary strings to an href or src attribute.
    The empty string means: do not render that link or image.
    """
    if not isinstance(value, str):
        return ""

    value = value.strip()
    if not value or len(value) > 2_048:
        return ""

    try:
        parsed = urlparse(value)
    except ValueError:
        return ""

    # Reject relative URLs, javascript:, data:, file:, and malformed URLs.
    if parsed.scheme.lower() not in ALLOWED_EXTERNAL_SCHEMES:
        return ""
    if not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""

    return value


def safe_json_script(value: Any) -> str:
    """Serialize data safely for a <script type="application/json"> element.

    Escaping <, >, and & prevents a listing title containing </script> from
    terminating the script element and injecting executable markup.
    """
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return (
        encoded.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def safe_slug(value: str) -> str:
    """Allow only canonical WatchLedger slugs used in URL routing."""
    if not isinstance(value, str):
        return ""
    if len(value) > 160:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
    return value if value and all(char in allowed for char in value) else ""
```

## Important rules

- Only allow `https` initially.
- Do not allow `http` merely because a source currently uses it.
- Do not allow `data:` image URLs.
- Do not allow URLs with usernames/passwords such as `https://user:password@example.com`.
- Return an empty string for anything unsafe.
- When the result is empty, do not render the link/image.

---

# 5. Validate source data when the SQLite ledger is built

## File to change

Change: `src/build_db.py`

The database is the best place to reject obviously unsafe image and listing URLs. The report code should validate again before rendering; this is called **defence in depth**.

## Step 5.1 — import the helper

Near the other imports, add:

```python
from security import safe_external_url
```

## Step 5.2 — validate URLs before insertion

Find both places that insert listing data into the `listings` table:

- The normal per-reference listing insert.
- The exact-search listing insert.

Before each `cur.execute(...)`, calculate safe URLs:

```python
safe_image_url = safe_external_url(l.get("image_url"))
safe_detail_url = safe_external_url(l.get("detail_url"))
safe_buy_url = safe_external_url(l.get("buy_url"))
```

Then use those variables instead of the raw API values:

```python
safe_image_url,
safe_detail_url,
safe_buy_url,
```

Do this in **both** insert loops. Do not validate only the exact-search endpoint.

## Step 5.3 — validate reference and auction URLs too

For references and auction lots, validate external URLs before storing them:

```python
safe_external_url(r.get("url"))
safe_external_url(a.get("url"))
```

## Step 5.4 — keep raw payloads unchanged

Do **not** modify the JSON files under `data/raw`. They are meant to be the original evidence.

The raw payload can contain unsafe text because it is evidence, not HTML. The database and renderer are where safety must be enforced.

---

# 6. Stop storing full listing JSON in `data-listing` HTML attributes

## File to change

Change: `src/report.py`

The current listing row contains a large JSON blob in an HTML attribute:

```html
<tr data-listing='...'>
```

This mixes JSON, HTML escaping, browser dataset decoding, and third-party data in one fragile place.

## Replace it with this design

1. Each table row gets only a safe internal listing ID.
2. The page contains one safe JSON data block.
3. Browser JavaScript reads that data block and looks up a listing by ID.

### Step 6.1 — create a list of browser-safe listing records

Inside `build_report()`, before generating rows, create a dictionary:

```python
listing_data = {}
```

In `row_html()`, create a record using only values the drawer needs:

```python
listing_data[str(lid)] = {
    "id": str(lid),
    "title": title or "",
    "price": price,
    "condition": cond or "",
    "box_papers": bp or "",
    "year": year,
    "material": mat or "",
    "merchant": merchant or "",
    "image_url": safe_external_url(img),
    "listing_url": safe_external_url(buy or detail),
    "kind": kind,
    "pct": pct_label,
    "sub": sub,
    "range": f"{price_fmt(lo)} – {price_fmt(hi)}" if lo is not None else "",
}
```

Import the helpers at the top of `src/report.py`:

```python
from security import safe_external_url, safe_json_script, safe_text
```

### Step 6.2 — change table rows to use only an ID

Replace the current `data-listing='...'` attribute with:

```html
<tr class="lrow" data-listing-id="LISTING_ID">
```

The `LISTING_ID` value must be escaped with `safe_text()`.

Do not put remote listing title, seller name, URL, or JSON into a table attribute.

### Step 6.3 — return the listing map from `build_report()`

Add this to the returned report dictionary:

```python
"listing_data": listing_data,
```

### Step 6.4 — emit a non-executable JSON data block

In `render()`, just before the external JavaScript files, add:

```python
<script id="listing-data" type="application/json">{safe_json_script(d["listing_data"])}</script>
<script src="/static/report.js" defer></script>
```

This must use `type="application/json"`. The browser will not execute it as JavaScript.

Do not put `listing_data` in a normal inline `<script>`.

---

# 7. Replace the analysis drawer `innerHTML` implementation

## File to create

Create: `static/report.js`

## Why

This code is unsafe:

```javascript
body.innerHTML = `... ${d.title} ...`;
```

If `d.title` contains HTML, the browser parses it as HTML. Using `textContent` tells the browser: “this is text, not markup.”

## Paste this code into `static/report.js`

```javascript
(() => {
  "use strict";

  const dataNode = document.getElementById("listing-data");
  const drawer = document.getElementById("drawer");
  const drawerBody = document.getElementById("drawer-body");
  const mask = document.getElementById("dmask");
  const closeButton = document.getElementById("drawer-close");

  if (!dataNode || !drawer || !drawerBody || !mask || !closeButton) {
    return;
  }

  let listings = {};
  let previouslyFocusedElement = null;

  try {
    listings = JSON.parse(dataNode.textContent || "{}");
  } catch {
    console.error("WatchLedger: invalid listing data");
    return;
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function safeExternalUrl(value) {
    if (typeof value !== "string") return "";

    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : "";
    } catch {
      return "";
    }
  }

  function priceText(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 0,
    }).format(value);
  }

  function addDetailRow(table, label, value) {
    const row = document.createElement("tr");
    const labelCell = element("td", "", label);
    const valueCell = element("td", "", value || "—");
    row.append(labelCell, valueCell);
    table.appendChild(row);
  }

  function badgeClass(kind) {
    const allowed = new Set(["deal", "fair", "above", "over", "not_comp", "limited"]);
    return allowed.has(kind) ? kind : "not_comp";
  }

  function buildDrawer(listing) {
    drawerBody.replaceChildren();

    const imageUrl = safeExternalUrl(listing.image_url);
    if (imageUrl) {
      const image = document.createElement("img");
      image.className = "drawer-img";
      image.src = imageUrl;
      image.alt = listing.title ? `Listing photo: ${listing.title}` : "Listing photo";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      drawerBody.appendChild(image);
    }

    drawerBody.appendChild(element("h2", "drawer-brand", listing.title || "Watch listing"));
    drawerBody.appendChild(element("p", "drawer-price", priceText(listing.price)));

    const kind = badgeClass(listing.kind);
    const badge = element("div", `badge badge-${kind}`);
    badge.append(
      element("span", "pct", listing.pct || "—"),
      element("span", "sub", listing.sub || "Limited comparable data")
    );
    drawerBody.appendChild(badge);

    const explanation = element("section", `drawer-section tint-${kind}`);
    explanation.appendChild(element("h3", "", "Why this stands out"));

    let explanationText = "This listing does not have enough comparable data for a price classification.";
    if (kind === "deal") {
      explanationText = `This listing is below the observed comparable range of ${listing.range || "this reference"}.`;
    } else if (kind === "fair") {
      explanationText = `This listing is within the observed comparable range of ${listing.range || "this reference"}.`;
    } else if (kind === "above" || kind === "over") {
      explanationText = `This listing is above the observed comparable range of ${listing.range || "this reference"}.`;
    }

    explanation.appendChild(element("p", "", explanationText));
    drawerBody.appendChild(explanation);

    const details = element("section", "drawer-section");
    details.appendChild(element("h3", "", "Listing details"));
    const table = element("table", "kv");
    addDetailRow(table, "Condition", listing.condition);
    addDetailRow(table, "Year", listing.year ? String(listing.year) : "");
    addDetailRow(table, "Box & papers", listing.box_papers);
    addDetailRow(table, "Material", listing.material);
    addDetailRow(table, "Seller", listing.merchant);
    details.appendChild(table);
    drawerBody.appendChild(details);

    const listingUrl = safeExternalUrl(listing.listing_url);
    if (listingUrl) {
      const link = element("a", "btn btn-primary", "View original listing ↗");
      link.href = listingUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      drawerBody.appendChild(link);
    }
  }

  function openDrawer(listingId, trigger) {
    const listing = listings[String(listingId)];
    if (!listing) return;

    previouslyFocusedElement = trigger || document.activeElement;
    buildDrawer(listing);
    mask.classList.add("open");
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("drawer-open");
    closeButton.focus();
  }

  function closeDrawer() {
    mask.classList.remove("open");
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("drawer-open");

    if (previouslyFocusedElement && typeof previouslyFocusedElement.focus === "function") {
      previouslyFocusedElement.focus();
    }
  }

  function focusableElements() {
    return [...drawer.querySelectorAll(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter((node) => !node.hasAttribute("hidden"));
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-open-listing]");
    if (trigger) {
      openDrawer(trigger.dataset.openListing, trigger);
      return;
    }

    if (event.target === mask || event.target.closest("[data-close-drawer]")) {
      closeDrawer();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (!drawer.classList.contains("open")) return;

    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
      return;
    }

    if (event.key === "Tab") {
      const nodes = focusableElements();
      if (!nodes.length) return;

      const first = nodes[0];
      const last = nodes[nodes.length - 1];

      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
})();
```

## Change the drawer HTML in `src/report.py`

Replace inline `onclick` handlers with data attributes and accessible dialog attributes:

```html
<div class="drawer-mask" id="dmask" aria-hidden="true"></div>
<aside
  class="drawer"
  id="drawer"
  role="dialog"
  aria-modal="true"
  aria-labelledby="drawer-title"
  aria-hidden="true">
  <button
    id="drawer-close"
    class="drawer-close"
    type="button"
    data-close-drawer
    aria-label="Close listing analysis">×</button>
  <div id="drawer-body"></div>
</aside>
```

## Change each table action button

Replace:

```html
<button onclick="openDrawer(this)">View analysis</button>
```

with:

```html
<button
  class="btn btn-sm"
  type="button"
  data-open-listing="LISTING_ID">
  View analysis
</button>
```

Escape `LISTING_ID` with `safe_text()`.

---

# 8. Replace homepage search `innerHTML`

## File to create

Create: `static/home.js`

## File to change

Change: `src/server.py`

The homepage currently takes externally supplied reference names and image URLs and inserts them into a template assigned to `box.innerHTML`.

Replace this with safe DOM creation.

## Step 8.1 — emit safe search data

In `render_home()`, create a small list that contains only the required fields:

```python
search_data = [
    {
        "slug": safe_slug(s["slug"]),
        "brand": s["brand"] or "",
        "model": s["model"] or "",
        "ref": s["ref"] or "",
        "range": price_fmt(s["band_low"] or s["low"]) + " – " + price_fmt(s["band_high"] or s["high"]),
        "image_url": safe_external_url(s["image"]),
    }
    for s in stats
]
```

Import this at the top of `src/server.py`:

```python
from security import safe_external_url, safe_json_script, safe_slug, safe_text
```

Before the closing `</body>`, add:

```html
<script id="reference-data" type="application/json">SAFE_JSON_HERE</script>
<script src="/static/home.js" defer></script>
```

Use:

```python
safe_json_script(search_data)
```

Remove the existing inline homepage script completely.

## Step 8.2 — paste this into `static/home.js`

```javascript
(() => {
  "use strict";

  const input = document.getElementById("q");
  const box = document.getElementById("suggestions");
  const source = document.getElementById("reference-data");

  if (!input || !box || !source) return;

  let references = [];
  try {
    references = JSON.parse(source.textContent || "[]");
  } catch {
    console.error("WatchLedger: invalid reference search data");
    return;
  }

  function safeSlug(value) {
    return typeof value === "string" && /^[a-z0-9_-]{1,160}$/.test(value) ? value : "";
  }

  function safeImageUrl(value) {
    if (typeof value !== "string") return "";
    try {
      const url = new URL(value);
      return url.protocol === "https:" ? url.href : "";
    } catch {
      return "";
    }
  }

  function clearSuggestions() {
    box.replaceChildren();
  }

  function addSuggestion(reference) {
    const slug = safeSlug(reference.slug);
    if (!slug) return;

    const link = document.createElement("a");
    link.className = "sug-row";
    link.href = `/reference/${encodeURIComponent(slug)}`;

    const imageUrl = safeImageUrl(reference.image_url);
    if (imageUrl) {
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = "";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      link.appendChild(image);
    }

    const text = document.createElement("span");
    const title = document.createElement("span");
    title.className = "t";
    title.textContent = `${reference.brand || ""} ${reference.model || ""}`.trim();
    const subtitle = document.createElement("span");
    subtitle.className = "s";
    subtitle.textContent = `Ref ${reference.ref || "—"}`;
    text.append(title, document.createElement("br"), subtitle);

    const range = document.createElement("span");
    range.className = "r";
    range.textContent = reference.range || "—";

    link.append(text, range);
    box.appendChild(link);
  }

  function openSuggestions() {
    const term = input.value.trim().toLowerCase();
    const hits = references
      .filter((reference) => {
        const searchable = `${reference.brand || ""} ${reference.model || ""} ${reference.ref || ""}`.toLowerCase();
        return !term || searchable.includes(term);
      })
      .slice(0, 6);

    clearSuggestions();

    if (hits.length) {
      hits.forEach(addSuggestion);
    } else {
      const empty = document.createElement("div");
      empty.className = "sug-empty";
      empty.textContent = "No tracked reference matches. Try Rolex 126610LN.";
      box.appendChild(empty);
    }

    box.classList.add("open");
  }

  function closeSuggestions() {
    box.classList.remove("open");
  }

  input.addEventListener("input", openSuggestions);
  input.addEventListener("focus", openSuggestions);

  document.addEventListener("click", (event) => {
    if (!box.contains(event.target) && event.target !== input) {
      closeSuggestions();
    }
  });

  input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const first = box.querySelector(".sug-row");
    if (first) first.click();
  });

  document.querySelectorAll("[data-search-value]").forEach((button) => {
    button.addEventListener("click", () => {
      input.value = button.dataset.searchValue || "";
      openSuggestions();
      const first = box.querySelector(".sug-row");
      if (first) first.click();
    });
  });
})();
```

## Change homepage search chips

Replace inline data that relies on the old script with accessible button attributes:

```html
<button type="button" class="chip" data-search-value="Rolex 126610LN">Rolex 126610LN</button>
```

Do this for each chip.

---

# 9. Validate every server-rendered external URL

## Files to change

- `src/report.py`
- `src/server.py`

Use `safe_external_url()` before rendering:

- `<img src="...">`
- `<a href="...">`
- The hero image
- Market-card images
- Recent-list images
- Raw source URL links
- Original listing links
- Reference-page links
- Auction links, if shown later

## Correct rendering pattern

```python
image_url = safe_external_url(s["image"])
if image_url:
    image_html = (
        f'<img src="{safe_text(image_url)}" '
        f'alt="{safe_text(alt_text)}" loading="lazy" '
        f'referrerpolicy="no-referrer">'
    )
else:
    image_html = '<div class="image-placeholder" aria-hidden="true"></div>'
```

For external links:

```python
listing_url = safe_external_url(value)
if listing_url:
    link_html = (
        f'<a href="{safe_text(listing_url)}" target="_blank" '
        f'rel="noopener noreferrer">View original listing ↗</a>'
    )
else:
    link_html = ''
```

Never write this:

```python
f'<a href="{html.escape(value)}">'
```

HTML escaping prevents quote injection but does **not** make `javascript:` safe.

---

# 10. Add Content Security Policy and browser security headers

## File to change

Change: `src/server.py`

## Step 10.1 — add a header helper

Add this method inside the `Handler` class:

```python
def send_security_headers(self, content_type: str) -> None:
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    self.send_header("X-Frame-Options", "DENY")
    self.send_header("Cross-Origin-Opener-Policy", "same-origin")
    self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")

    if content_type.startswith("text/html"):
        self.send_header(
            "Content-Security-Policy",
            "; ".join([
                "default-src 'self'",
                "base-uri 'self'",
                "object-src 'none'",
                "frame-ancestors 'none'",
                "form-action 'self'",
                "script-src 'self'",
                "style-src 'self' https://fonts.googleapis.com",
                "font-src 'self' https://fonts.gstatic.com",
                "img-src 'self' https:",
                "connect-src 'self'",
                "upgrade-insecure-requests",
            ]),
        )
```

## Step 10.2 — call it in `send()`

In `send()`, call `self.send_security_headers(ctype)` after `send_response()` and before `end_headers()`.

```python
self.send_response(code)
self.send_header("Content-Type", ctype)
self.send_security_headers(ctype)
self.send_header("Content-Length", str(len(data)))
```

## Important

The CSP above will block inline `<script>` elements and inline `onclick` handlers. That is intentional. Do not weaken the CSP by adding `'unsafe-inline'` to `script-src`.

Move all JavaScript to `/static/home.js` and `/static/report.js` first.

## Fonts

The CSP shown allows Google Fonts. The more private and stricter final version is:

1. Download licensed font files.
2. Serve them from `/static/fonts/`.
3. Add `@font-face` in `static/style.css`.
4. Change `font-src` to `'self'`.
5. Remove Google Fonts `<link>` tags.

Do that after the initial security work is passing.

---

# 11. Remove inline event handlers and inline styles

## Why

Inline event handlers force the site to weaken CSP. Inline styles make it hard to adopt strict style policies later.

## Files to change

- `src/server.py`
- `src/report.py`
- `static/style.css`

## Replace these patterns

### Replace inline events

Bad:

```html
<button onclick="window.location='/'">⌕</button>
```

Good:

```html
<a class="nav-icon" href="/" aria-label="Search">⌕</a>
```

Bad:

```html
<button onclick="openDrawer(this)">View analysis</button>
```

Good:

```html
<button type="button" data-open-listing="LISTING_ID">View analysis</button>
```

### Replace inline styling

Bad:

```html
<p style="max-width:800px;margin:60px auto">...</p>
```

Good:

```html
<main class="narrow-page narrow-page-spaced">...</main>
```

Then add the CSS class in `static/style.css`.

### Dynamic range-bar widths

For range percentage positioning, only use server-calculated numeric values. Do not put source-provided strings in a `style` attribute.

Safe example:

```python
def percent(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))
```

Then format only the safe number:

```python
f'<div class="band" style="left:{left:.1f}%;width:{width:.1f}%"></div>'
```

Never do this:

```python
f'<div style="left:{raw_api_value}">'
```

---

# 12. Improve server error handling and request safety

## File to change

Change: `src/server.py`

## Step 12.1 — do not expose SQLite errors

Current behaviour returns the internal database error message to the visitor.

Replace:

```python
except sqlite3.Error as e:
    self.send(500, f"<pre>ledger error: {html.escape(str(e))}</pre>")
```

with:

```python
except sqlite3.Error:
    self.log_error("database request failed")
    self.send(500, "Internal server error")
```

For a proper HTML error page, render a fixed template that contains no exception text.

## Step 12.2 — validate report slugs

At the beginning of the `/reference/` and `/api/reference/` route branches:

```python
slug = safe_slug(slug)
if not slug:
    self.send(404, render_not_found("Unknown reference"))
    return
```

## Step 12.3 — do not expose raw-data browsing in public production by default

The raw-data browser is a great POC proof feature, but it is not automatically appropriate for public production.

Before public launch, choose one option:

### Option A — keep a public provenance viewer

- Show an approved summary of payload metadata.
- Remove irrelevant/unlicensed fields.
- Keep direct source attribution.
- Add a takedown/contact policy.

### Option B — keep raw payloads internal

- Remove `/raw/` from public routing.
- Keep an internal admin-only provenance viewer.
- Show visitors a report-level evidence summary instead.

Do not accidentally publish source fields, IDs, or data that violate a source agreement.

## Step 12.4 — use a production server

Do not deploy `http.server.ThreadingHTTPServer` directly to the internet.

For production:

- Place the application behind an HTTPS reverse proxy.
- Use a process manager.
- Configure timeouts.
- Add request-size limits.
- Add rate limiting at the proxy.
- Send logs to an error-monitoring service.

For this POC, keep the standard-library server for local use only.

---

# 13. Add safe image behaviour

External images are not harmless just because they are images. They can track users and degrade page performance.

## File to change

Change: `static/style.css` and all image rendering in Python/JavaScript.

## Required changes

Every external image should include:

```html
loading="lazy"
referrerpolicy="no-referrer"
```

Every listing image should have one of these alt strategies:

- Meaningful: `alt="Rolex Explorer II Polar listing photo"`
- Decorative/redundant: `alt=""`

Do not use an empty alt value if the image is the only visual identifier for a listing.

## Future improvement

Do not start by downloading/caching dealer photos without written permission. For now:

- Validate the source URL.
- Hotlink only where source terms permit.
- Use `referrerpolicy="no-referrer"`.
- Show a neutral placeholder if the image fails.

---

# 14. Add automated tests

## Files to create

Create:

```text
tests/
tests/test_security.py
tests/test_report_safety.py
tests/test_server_safety.py
requirements-dev.txt
```

Put this in `requirements-dev.txt`:

```text
pytest==8.3.5
```

## Test 1 — URL policy

Create `tests/test_security.py`:

```python
from src.security import safe_external_url, safe_json_script


def test_allows_https_url():
    assert safe_external_url("https://dealer.example/watch/123") == "https://dealer.example/watch/123"


def test_rejects_javascript_url():
    assert safe_external_url("javascript:alert(1)") == ""


def test_rejects_data_url():
    assert safe_external_url("data:text/html,<script>alert(1)</script>") == ""


def test_rejects_file_url():
    assert safe_external_url("file:///etc/passwd") == ""


def test_rejects_http_url():
    assert safe_external_url("http://dealer.example/watch/123") == ""


def test_json_script_cannot_be_terminated_by_listing_title():
    payload = {"title": "</script><script>alert(1)</script>"}
    encoded = safe_json_script(payload)
    assert "</script" not in encoded.lower()
    assert "\\u003c/script" in encoded.lower()
```

## Test 2 — report HTML must not contain unsafe URLs

Create `tests/test_report_safety.py` with a temporary SQLite database containing a deliberately hostile listing:

```python
# Pseudocode / test intent:
# 1. Insert a title containing <img src=x onerror=alert(1)>.
# 2. Insert buy_url = javascript:alert(1).
# 3. Build the report.
# 4. Assert the rendered report does not contain javascript:.
# 5. Assert the title is HTML-escaped in server HTML.
# 6. Assert the listing data appears only in type=application/json JSON,
#    where < becomes \u003c.
```

The exact fixture can be written after the security helpers exist. The test must cover the real renderer, not only helper functions.

## Test 3 — limited-data reports must not show valuation categories

```python
# Create four exact listings.
# Render the report.
# Assert "How to read this market" is not present.
# Assert "Why there is no market range yet" is present.
# Assert "Potential deal" is not present.
```

## Test 4 — related rows never enter exact tab

```python
# Create five exact rows and two related rows.
# Render the report.
# Assert the exact table contains only exact IDs.
# Assert the related table contains only related IDs.
```

## Test 5 — routes reject invalid slugs

Test paths such as:

```text
/reference/../../etc/passwd
/reference/<script>alert(1)</script>
/api/reference/javascript:alert(1)
```

Expected result: `404`, with no stack trace and no internal filesystem/database information.

---

# 15. Add a safe state-specific render path

## File to change

Change: `src/report.py`

Use separate functions instead of one large template with empty values.

Create these functions:

```python
def render_valid_market_summary(report: dict) -> str:
    """Render range, median, range bar, and valid classification explanation."""


def render_limited_data_summary(report: dict) -> str:
    """Render coverage explanation and next actions only."""


def render_valid_market_panel(report: dict) -> str:
    """Render deal/fair/above-market explanation only when a range exists."""


def render_limited_data_panel(report: dict) -> str:
    """Explain why no valuation labels are shown yet."""
```

Then in `render()`:

```python
if d["limited"]:
    summary = render_limited_data_summary(d)
    panel = render_limited_data_panel(d)
else:
    summary = render_valid_market_summary(d)
    panel = render_valid_market_panel(d)
```

This prevents accidental empty placeholders such as `Below —` from appearing again.

---

# 16. Manual verification checklist

Run these checks after the code is changed.

## Step 16.1 — install test tools

```text
python -m pip install -r requirements-dev.txt
```

## Step 16.2 — run automated tests

```text
python -m pytest -q
```

Do not continue if tests fail.

## Step 16.3 — rebuild the project

```text
make clean
make all
make serve
```

On Windows, if `make` is unavailable, run the equivalent Python commands:

```text
python src/fetch.py
python src/build_db.py
python src/report.py
python src/server.py
```

## Step 16.4 — inspect response headers

Open the site in a browser or use an HTTP client. Confirm the HTML response includes:

```text
Content-Security-Policy
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
X-Frame-Options: DENY
Cross-Origin-Opener-Policy: same-origin
Permissions-Policy
```

## Step 16.5 — test a hostile listing manually

Temporarily insert this into a local test fixture/database only:

```text
Title: </script><script>alert('xss')</script>
Seller: <img src=x onerror=alert('xss')>
Image URL: javascript:alert('xss')
Listing URL: data:text/html,<script>alert('xss')</script>
```

Expected result:

- No browser alert.
- No executable markup.
- Unsafe image does not render.
- Unsafe original-listing button does not render.
- Title/seller appear as harmless text where displayed.

## Step 16.6 — test keyboard interaction

1. Open a listing drawer with Enter or Space.
2. Press Tab repeatedly.
3. Confirm focus never escapes the drawer.
4. Press Escape.
5. Confirm the drawer closes.
6. Confirm focus returns to `View analysis`.

---

# 17. Things not to do

Do **not** do any of the following shortcuts:

- Do not use `innerHTML` because it is convenient.
- Do not add `'unsafe-inline'` to the CSP script policy.
- Do not trust upstream data because it is from a watch API.
- Do not treat `html.escape()` as URL validation.
- Do not allow every image/link URL just to avoid broken images.
- Do not publish raw source data publicly without checking data-source terms.
- Do not send exception text to visitors.
- Do not deploy the standard-library server directly to production.
- Do not mark this work done without hostile-data tests.

---

# 18. Expected final file changes

After completing this work, the repository should have these security-related changes:

```text
src/
  security.py                 NEW: text, URL, slug, JSON helpers
  build_db.py                 UPDATED: validate URLs before writing ledger rows
  report.py                   UPDATED: safe listing-data block, no inline handlers,
                               state-specific report panels
  server.py                   UPDATED: safe search-data block, safe URLs, headers,
                               generic server errors, slug validation

static/
  home.js                     NEW: safe search suggestions using DOM nodes
  report.js                   NEW: safe drawer, focus management, safe DOM creation
  style.css                   UPDATED: classes replacing inline styling; drawer state

tests/
  test_security.py            NEW: URL and JSON safety helpers
  test_report_safety.py       NEW: hostile listing/report behaviour
  test_server_safety.py       NEW: unsafe routes and headers

requirements-dev.txt          NEW: pytest development dependency
```

---

# Final standard

> WatchLedger must be able to display a malicious title, seller name, image URL, or listing URL from a third-party source without executing code, leaking internal information, weakening browser protections, or misleading users about the safety of external destinations.

Finish this guide before adding more sources, more pages, or more visual features.
