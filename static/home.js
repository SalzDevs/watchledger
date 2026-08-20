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

  const focusSearch = document.querySelector("[data-focus-search]");
  if (focusSearch) {
    focusSearch.addEventListener("click", (event) => {
      event.preventDefault();
      input.focus();
    });
  }
})();