import json
import re
from urllib.parse import quote_plus

from playwright.async_api import Response

from app.browser import goto, manager, raise_if_blocked
from app.matching import parse_int, parse_price
from app.models import Offer

NAME = "Ozon"
BASE = "https://www.ozon.ru"

RATING_RE = re.compile(r"^[1-5][.,]\d{1,2}$")
REVIEWS_RE = re.compile(r"^([\d\s\u2009\xa0]+)\s*отзыв")


def search_url(query: str) -> str:
    return f"{BASE}/search/?text={quote_plus(query)}&sorting=rating&from_global=true"


STATES_JS = """
() => [...document.querySelectorAll('[id^="state-searchResultsV2"]')].map(e => e.getAttribute('data-state'))
"""


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _clean(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _to_offer(item: dict) -> Offer | None:
    link = (item.get("action") or {}).get("link")
    if not link:
        return None

    title, price, rating, reviews, image = None, 0.0, None, None, None
    texts: list[str] = []
    for d in _walk(item.get("mainState") or item):
        if d.get("id") == "name" and isinstance(d.get("textAtom"), dict):
            title = _clean(d["textAtom"].get("text", ""))
        atom = d.get("atom") if isinstance(d.get("atom"), dict) else d
        if isinstance(atom.get("textAtom"), dict) and atom["textAtom"].get("text"):
            texts.append(_clean(atom["textAtom"]["text"]))
        if d.get("textStyle") == "PRICE" and not price:
            price = parse_price(d.get("text"))

    for s in _strings(item.get("mainState") or []):
        s = _clean(s)
        if rating is None and RATING_RE.match(s):
            rating = float(s.replace(",", "."))
        elif reviews is None and (m := REVIEWS_RE.match(s)):
            reviews = parse_int(m.group(1))
        elif not price and "₽" in s:
            price = parse_price(s)

    if not title and texts:
        title = max(texts, key=len)
    if not title:
        return None

    tile = item.get("tileImage") or {}
    for d in _walk(tile):
        if isinstance(d.get("link"), str) and d["link"].startswith("http"):
            image = d["link"]
            break
        if isinstance(d.get("image"), str) and d["image"].startswith("http"):
            image = d["image"]
            break

    return Offer(
        title=title,
        price=price,
        url=link if link.startswith("http") else BASE + link.split("?")[0],
        rating=rating,
        reviews=reviews,
        image=image,
        description=" ".join(texts),
    )


def _offers_from_state(state: str | dict | None) -> list[Offer]:
    if not state:
        return []
    data = json.loads(state) if isinstance(state, str) else state
    return [o for o in (_to_offer(i) for i in data.get("items") or []) if o]


async def search(query: str) -> list[Offer]:
    async with manager.page() as page:
        api_states: list[str] = []

        async def on_response(r: Response) -> None:
            if "entrypoint-api.bx/page/json" not in r.url or r.status != 200:
                return
            try:
                data = await r.json()
            except Exception:
                return
            for key, value in (data.get("widgetStates") or {}).items():
                if key.startswith("searchResultsV2"):
                    api_states.append(value)

        page.on("response", on_response)
        await goto(page, search_url(query))
        try:
            await page.wait_for_selector('[id^="state-searchResultsV2"]', state="attached", timeout=40000)
        except Exception:
            await raise_if_blocked(page, NAME)
            if not api_states:
                raise RuntimeError("Ozon не вернул результаты поиска")

        offers: list[Offer] = []
        for state in await page.evaluate(STATES_JS) + api_states:
            offers.extend(_offers_from_state(state))

        seen, unique = set(), []
        for o in offers:
            if o.url not in seen:
                seen.add(o.url)
                unique.append(o)
        return unique
