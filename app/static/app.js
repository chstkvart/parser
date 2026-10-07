const form = document.getElementById("search-form");
const input = document.getElementById("query");
const resultsEl = document.getElementById("results");
const summaryEl = document.getElementById("summary");
const disclaimerEl = document.getElementById("disclaimer");

const priceFmt = new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", maximumFractionDigits: 0 });
let marketplaces = [];
let searchId = 0;
let currentAbort = null;

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function header(m) {
  return `<div class="market"><span class="dot ${m.id}"></span>${escapeHtml(m.name)}</div>`;
}

function renderLoading(m) {
  return `${header(m)}<div class="loading"><div class="spinner"></div>Ищем…</div>`;
}

function renderResult(m, r) {
  if (!r.offer) {
    return `${header(m)}<div class="error">${escapeHtml(r.error || "Ничего не найдено")}<br><br>
      <a href="${escapeHtml(r.search_url)}" target="_blank" rel="noopener">Открыть поиск на сайте →</a></div>`;
  }
  const o = r.offer;
  const rating = o.rating ? `★ ${o.rating.toFixed(1)}` : "★ нет оценок";
  const reviews = o.reviews ? ` · ${o.reviews.toLocaleString("ru-RU")} оценок` : "";
  const hasRegular = o.price_regular && o.price_regular > o.price;
  const label = hasRegular ? `<div class="price-label">с WB Кошельком</div>` : "";
  const regular = hasRegular ? `<div class="price-regular">${priceFmt.format(o.price_regular)} без кошелька</div>` : "";
  return `
    <span class="badge" hidden>Дешевле всего</span>
    ${header(m)}
    <a class="image" href="${escapeHtml(o.url)}" target="_blank" rel="noopener">
      ${o.image ? `<img src="${escapeHtml(o.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}
    </a>
    <a class="title" href="${escapeHtml(o.url)}" target="_blank" rel="noopener">${escapeHtml(o.title)}</a>
    <div class="meta">${rating}${reviews}</div>
    <div class="price">${priceFmt.format(o.price)}</div>
    ${label}
    ${regular}
    <div class="fetched">Цена на ${fetchedTime(r)}</div>`;
}

function fetchedTime(r) {
  return new Date(r.fetched_at).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function highlightCheapest(results) {
  const priced = Object.entries(results).filter(([, r]) => r && r.offer);
  document.querySelectorAll(".card").forEach((c) => {
    c.classList.remove("cheapest");
    const badge = c.querySelector(".badge");
    if (badge) badge.hidden = true;
  });
  if (!priced.length) return;
  const min = Math.min(...priced.map(([, r]) => r.offer.price));
  for (const [id, r] of priced) {
    if (r.offer.price !== min) continue;
    const card = document.getElementById(`card-${id}`);
    card.classList.add("cheapest");
    card.querySelector(".badge").hidden = false;
  }
}

function renderSummary(results, done) {
  const priced = Object.values(results).filter((r) => r && r.offer);
  if (!done || !priced.length) {
    summaryEl.hidden = true;
    return;
  }
  const best = priced.reduce((a, b) => (b.offer.price < a.offer.price ? b : a));
  const worst = priced.reduce((a, b) => (b.offer.price > a.offer.price ? b : a));
  const diff = worst.offer.price - best.offer.price;
  summaryEl.innerHTML = `Дешевле всего на <b>${escapeHtml(best.name)}</b> — ${priceFmt.format(best.offer.price)}` +
    (diff > 0 ? `, экономия до ${priceFmt.format(diff)}` : "");
  summaryEl.hidden = false;
}

async function search(query) {
  const id = ++searchId;
  if (currentAbort) currentAbort.abort();
  const abort = new AbortController();
  currentAbort = abort;
  const results = {};
  summaryEl.hidden = true;
  disclaimerEl.hidden = false;
  resultsEl.innerHTML = marketplaces.map((m) => `<article class="card" id="card-${m.id}">${renderLoading(m)}</article>`).join("");

  await Promise.all(marketplaces.map(async (m) => {
    let r;
    try {
      const resp = await fetch(`/api/search/${m.id}?q=${encodeURIComponent(query)}`, { signal: abort.signal });
      if (resp.ok) {
        r = await resp.json();
      } else {
        const detail = await resp.json().then((d) => d.detail).catch(() => null);
        r = { error: typeof detail === "string" ? detail : `Ошибка сервера (${resp.status})`, search_url: "#" };
      }
    } catch (e) {
      if (abort.signal.aborted) return;
      r = { error: "Сервер недоступен", search_url: "#" };
    }
    if (id !== searchId) return;
    results[m.id] = r;
    document.getElementById(`card-${m.id}`).innerHTML = renderResult(m, r);
    highlightCheapest(results);
  }));

  if (id !== searchId) return;
  currentAbort = null;
  renderSummary(results, true);
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const q = input.value.trim();
  if (q.length < 2) return;
  search(q);
});

(async () => {
  marketplaces = await (await fetch("/api/marketplaces")).json();
  if (location.search) history.replaceState(null, "", location.pathname);
})();

// Browsers restore typed text on reload and on back/forward navigation; the page must start clean.
window.addEventListener("pageshow", () => {
  input.value = "";
});
