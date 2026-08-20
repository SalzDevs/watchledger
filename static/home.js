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

  // Demand capture for untracked queries (design brief #13).
  function addRequestCoverage(term) {
    const row = document.createElement("div");
    row.className = "sug-empty sug-request";
    row.appendChild(element("span", "sug-request-q", `“${term}” is not tracked yet.`));
    const requestBtn = document.createElement("button");
    requestBtn.type = "button";
    requestBtn.className = "btn btn-sm";
    requestBtn.textContent = "Request coverage";
    requestBtn.addEventListener("click", () => {
      const body = new URLSearchParams({ query: term });
      fetch("/api/request", { method: "POST", body })
        .then((res) => res.json())
        .then((data) => {
          if (data && data.ok) {
            row.replaceChildren(
              element("span", "sug-request-q",
                "Request recorded — we'll add this reference when coverage allows.")
            );
          } else {
            row.replaceChildren(
              element("span", "sug-request-q", "Could not record the request. Please try again.")
            );
          }
        })
        .catch(() => {
          row.replaceChildren(
            element("span", "sug-request-q", "Could not record the request. Please try again.")
          );
        });
    });
    const browse = document.createElement("a");
    browse.className = "btn btn-sm";
    browse.href = "/#developing";
    browse.textContent = "Browse similar tracked watches";
    row.append(document.createElement("br"), requestBtn, " ", browse);
    box.appendChild(row);
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
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
    } else if (term) {
      addRequestCoverage(term);
    } else {
      const empty = document.createElement("div");
      empty.className = "sug-empty";
      empty.textContent = "Start typing to search tracked references.";
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

  const focusSearch = document.querySelector("[data-focus-search]");
  if (focusSearch) {
    focusSearch.addEventListener("click", (event) => {
      event.preventDefault();
      input.focus();
    });
  }
})();