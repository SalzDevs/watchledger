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
    const allowed = new Set(["deal", "fair", "above", "over", "not_comp"]);
    return allowed.has(kind) ? kind : "not_comp";
  }

  function matchLabel(level) {
    return {
      exact_configuration: "Exact configuration",
      exact_reference_variant: "Variant configuration",
      related_reference: "Related reference",
      rejected: "Rejected (parts/accessories)",
      unverified: "Unverified",
    }[level] || level || "—";
  }

  function agoText(ts) {
    if (!ts) return "—";
    const d = Date.now() / 1000 - ts;
    if (d < 60) return "just now";
    if (d < 3600) return `${Math.floor(d / 60)} min ago`;
    if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
    return `${Math.floor(d / 86400)} d ago`;
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

    // --- match provenance (Phase 2) ---
    const provenance = element("section", "drawer-section");
    provenance.appendChild(element("h3", "", "Match provenance"));
    const ptable = element("table", "kv");
    addDetailRow(ptable, "Match level", matchLabel(listing.match_level));
    addDetailRow(ptable, "Match reason", listing.match_reason || "—");
    addDetailRow(ptable, "Source", listing.source_name || "—");
    addDetailRow(ptable, "Source listing id", listing.source_listing_id || "—");
    addDetailRow(ptable, "Observed", agoText(listing.fetched_at));
    provenance.appendChild(ptable);
    drawerBody.appendChild(provenance);

    const explanation = element("section", `drawer-section tint-${kind}`);
    explanation.appendChild(element("h3", "", "Why this stands out"));

    let explanationText = "This listing does not have enough comparable data for a price classification.";
    if (kind === "deal") {
      explanationText = `This listing is below the observed comparable range of ${listing.range || "this reference"}.`;
    } else if (kind === "fair") {
      explanationText = `This listing is within the observed comparable range of ${listing.range || "this reference"}.`;
    } else if (kind === "above" || kind === "over") {
      explanationText = `This listing is above the observed comparable range of ${listing.range || "this reference"}.`;
    } else if (listing.match_level === "rejected") {
      explanationText = "This listing was excluded from market math because its title indicates parts or accessories, not a complete watch.";
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
    addDetailRow(table, "Size", listing.size_mm ? `${listing.size_mm} mm` : "");
    addDetailRow(table, "Movement", listing.movement);
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

  // --- tabs: exact / variant / related / excluded ---
  const tabButtons = document.querySelectorAll("#ltabs .tab");
  const tabTables = {
    exact: document.getElementById("tbl-exact"),
    variant: document.getElementById("tbl-variant"),
    related: document.getElementById("tbl-related"),
    excluded: document.getElementById("tbl-excluded"),
  };
  if (tabButtons.length) {
    tabButtons.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabButtons.forEach((x) => x.classList.remove("active"));
        tab.classList.add("active");
        const which = tab.dataset.tab;
        Object.entries(tabTables).forEach(([name, table]) => {
          if (table) table.classList.toggle("hidden", name !== which);
        });
      });
    });
  }

  // --- filters + sort, operating on the DOM rows (data-listing-id only) ---
  const tables = ["tbl-exact", "tbl-variant", "tbl-related", "tbl-excluded"];
  const rowIndex = {};
  for (const tid of tables) {
    const table = document.getElementById(tid);
    if (!table) continue;
    for (const row of table.querySelectorAll(".lrow")) {
      rowIndex[row.dataset.listingId] = { row, table: tid, data: listings[row.dataset.listingId] || {} };
    }
  }

  function applyFilters() {
    const cond = document.querySelector("[data-filter=condition]").value;
    const bp = document.querySelector("[data-filter=bp]").value;
    const avail = document.querySelector("[data-filter=avail]").value;
    const merchant = document.querySelector("[data-filter=merchant]").value;
    const sort = document.getElementById("fsort").value;

    for (const tid of tables) {
      const table = document.getElementById(tid);
      if (!table) continue;
      const entries = Object.values(rowIndex).filter((o) => o.table === tid);
      let visible = entries.filter((o) => !cond || (o.data.condition || "") === cond);
      visible = visible.filter((o) => !bp || (o.data.box_papers || "") === bp);
      visible = visible.filter((o) => avail === "" || (String(avail) === "1" ? !!o.data.price : !o.data.available));
      visible = visible.filter((o) => !merchant || (o.data.merchant || "") === merchant);

      if (sort === "low") visible.sort((a, b) => (a.data.price ?? 1e18) - (b.data.price ?? 1e18));
      else if (sort === "high") visible.sort((a, b) => (b.data.price ?? -1) - (a.data.price ?? -1));
      else if (sort === "typical") {
        visible.sort((a, b) => {
          const ad = a.data.kind === "deal" || a.data.kind === "fair" ? 0 : 1;
          const bd = b.data.kind === "deal" || b.data.kind === "fair" ? 0 : 1;
          return ad - bd || (a.data.price ?? 1e18) - (b.data.price ?? 1e18);
        });
      } else if (sort === "recent") {
        visible.sort((a, b) => (b.data.fetched_at ?? 0) - (a.data.fetched_at ?? 0));
      } else if (sort === "newest") {
        visible.sort((a, b) => (b.data.year ?? 0) - (a.data.year ?? 0));
      } else {
        const order = ["deal", "fair", "above", "over", "not_comp"];
        visible.sort((a, b) => order.indexOf(a.data.kind) - order.indexOf(b.data.kind));
      }

      table.querySelector("tbody").replaceChildren(...visible.map((o) => o.row));
    }
  }

  // populate the seller filter from the exact table rows
  const merchantSelect = document.querySelector("[data-filter=merchant]");
  if (merchantSelect) {
    const merchants = new Set();
    for (const o of Object.values(rowIndex)) {
      if (o.data.merchant) merchants.add(o.data.merchant);
    }
    for (const m of [...merchants].sort()) {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      merchantSelect.appendChild(opt);
    }
  }

  const filterSelects = document.querySelectorAll("#lfilters select");
  filterSelects.forEach((select) => select.addEventListener("change", applyFilters));

  // --- tracking form (Phase 9) ---
  const trackForm = document.getElementById("track-form");
  if (trackForm) {
    trackForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const email = trackForm.querySelector('input[name=email]').value;
      const slug = trackForm.dataset.slug;
      const body = new URLSearchParams({ action: "track", email, slug });
      fetch("/api/track", { method: "POST", body })
        .then((res) => {
          if (!res.ok) throw new Error("tracking failed");
          return res.json();
        })
        .then((data) => {
          if (data && data.ok) {
            trackForm.hidden = true;
            const done = document.getElementById("track-done");
            if (done) done.hidden = false;
          }
        })
        .catch(() => {
          const note = trackForm.querySelector(".track-note");
          if (note) note.textContent = "Something went wrong. Please try again.";
        });
    });
  }
})();