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

  // --- tabs: exact / related ---
  const tabButtons = document.querySelectorAll("#ltabs .tab");
  if (tabButtons.length) {
    tabButtons.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabButtons.forEach((x) => x.classList.remove("active"));
        tab.classList.add("active");
        const which = tab.dataset.tab;
        document.getElementById("tbl-exact").classList.toggle("hidden", which !== "exact");
        document.getElementById("tbl-related").classList.toggle("hidden", which !== "related");
      });
    });
  }

  // --- filters + sort, operating on the DOM rows (data-listing-id only) ---
  const rows = [...document.querySelectorAll("#tbl-exact .lrow")].map((row) => ({
    row,
    data: listings[row.dataset.listingId] || {},
  }));

  function applyFilters() {
    const cond = document.querySelector("[data-filter=condition]").value;
    const bp = document.querySelector("[data-filter=bp]").value;
    const avail = document.querySelector("[data-filter=avail]").value;
    const sort = document.getElementById("fsort").value;

    let visible = rows.filter((o) => o.data.kind !== "not_comp");
    visible = visible.filter((o) => !cond || (o.data.condition || "") === cond);
    visible = visible.filter((o) => !bp || (o.data.box_papers || "") === bp);
    visible = visible.filter((o) => avail === "" || (avail === "1" ? o.data.price != null : true));

    const order = { best: ["deal", "fair", "above", "over", "not_comp"], low: [], high: [] };
    if (sort === "low") visible.sort((a, b) => (a.data.price ?? 1e18) - (b.data.price ?? 1e18));
    else if (sort === "high") visible.sort((a, b) => (b.data.price ?? -1) - (a.data.price ?? -1));
    else visible.sort((a, b) => order.best.indexOf(a.data.kind) - order.best.indexOf(b.data.kind));

    const body = document.querySelector("#tbl-exact tbody");
    body.replaceChildren(...visible.map((o) => o.row));
  }

  const filterSelects = document.querySelectorAll("#lfilters select");
  filterSelects.forEach((select) => select.addEventListener("change", applyFilters));
})();