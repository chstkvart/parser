import html
from urllib.parse import quote_plus

from app.browser import goto, manager, raise_if_blocked
from app.matching import parse_int, parse_price
from app.models import Offer

NAME = "Яндекс Маркет"
BASE = "https://market.yandex.ru"


def search_url(query: str) -> str:
    # Default sorting on Yandex Market is "по популярности".
    return f"{BASE}/search?text={quote_plus(query)}"


SNIPPETS_JS = r"""
() => {
  const out = [];
  for (const t of document.querySelectorAll('[data-auto="snippet-title"]')) {
    let card = t;
    for (let i = 0; i < 15 && card; i++) {
      card = card.parentElement;
      if (card && card.querySelector('[data-auto="snippet-price-current"]')) break;
    }
    if (!card) continue;
    const link = t.closest('a');
    const price = card.querySelector('[data-auto="snippet-price-current"]');
    const rev = card.querySelector('[data-auto="reviews"]');
    const img = card.querySelector('img');
    const props = [...card.querySelectorAll('span')].map(s => s.textContent).join(' ').slice(0, 1000);
    out.push({
      title: t.getAttribute('title') || t.textContent,
      href: link ? link.getAttribute('href') : null,
      price: price ? price.textContent : null,
      rating: rev && rev.querySelector('.ds-rating__value') ? rev.querySelector('.ds-rating__value').textContent : null,
      reviews: rev ? rev.textContent : null,
      image: img ? (img.currentSrc || img.src) : null,
      description: props,
    });
  }
  return out;
}
"""


def _reviews_count(text: str | None) -> int | None:
    # "4.9 (149) · 307 купили" -> 149
    if not text or "(" not in text:
        return None
    return parse_int(text.split("(", 1)[1].split(")", 1)[0])


async def search(query: str) -> list[Offer]:
    async with manager.page() as page:
        await goto(page, search_url(query))
        try:
            await page.wait_for_selector('[data-auto="snippet-title"]', timeout=40000)
        except Exception:
            await raise_if_blocked(page, NAME)
            raise RuntimeError("Яндекс Маркет не вернул результаты поиска")

        for _ in range(4):
            await page.mouse.wheel(0, 2500)
            await page.wait_for_timeout(700)

        raw = await page.evaluate(SNIPPETS_JS)
        offers, seen = [], set()
        for r in raw:
            if not r["href"] or r["href"] in seen:
                continue
            seen.add(r["href"])
            href = r["href"] if r["href"].startswith("http") else BASE + r["href"]
            rating = parse_price(r["rating"]) or None
            offers.append(
                Offer(
                    title=html.unescape(r["title"]).replace("\xa0", " ").strip(),
                    price=parse_price(r["price"]),
                    url=href,
                    rating=rating,
                    reviews=_reviews_count(r["reviews"]),
                    image=r["image"],
                    description=r["description"],
                )
            )
        # Sponsored snippets are ads, not popularity; use them only if nothing else was found.
        organic = [o for o in offers if "sponsored=1" not in o.url]
        return organic or offers
