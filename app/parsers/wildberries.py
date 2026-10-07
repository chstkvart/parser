import asyncio
import logging
import math
import time
from urllib.parse import quote_plus

import httpx
from playwright.async_api import Page, Response

from app import config
from app.browser import goto, manager, raise_if_blocked
from app.models import Offer

log = logging.getLogger(__name__)

NAME = "Wildberries"
UPSTREAMS_URL = "https://cdn.wbbasket.ru/api/v3/upstreams"
WALLET_URL = "https://static-basket-01.wbbasket.ru/vol1/global-payment/default-payment.json"
SETTINGS_URL = "https://static-basket-01.wbbasket.ru/vol0/data/settings-front-v2-ru.json"
ROUTES_TTL = 3600

# (vol_from, vol_to, host) from WB's media route map; maps a product to the CDN host storing its photos.
_routes: list[tuple[int, int, str]] = []
_routes_loaded_at = 0.0
_wallet_rules_cache: tuple[float, float] | None = None
_wallet_loaded_at = 0.0


def search_url(query: str) -> str:
    return f"https://www.wildberries.ru/catalog/0/search.aspx?search={quote_plus(query)}&sort=popular"


IMAGES_JS = """
() => Object.fromEntries([...document.querySelectorAll('article[data-nm-id]')].map(a => {
  const img = a.querySelector('img');
  return [a.dataset.nmId, img ? (img.currentSrc || img.src) : null];
}))
"""


def _parse_routes(upstreams: dict) -> list[tuple[int, int, str]]:
    routes = []
    for section in upstreams.values():
        if not isinstance(section, dict):
            continue
        for route in section.get("mediabasket_route_map") or []:
            for h in route.get("hosts") or []:
                routes.append((h["vol_range_from"], h["vol_range_to"], h["host"]))
        if routes:
            break
    return routes


async def _ensure_routes(page: Page, upstreams_from_page: asyncio.Future) -> None:
    global _routes, _routes_loaded_at
    if _routes and time.time() - _routes_loaded_at < ROUTES_TTL:
        return
    try:
        data = await asyncio.wait_for(asyncio.shield(upstreams_from_page), timeout=3)
    except asyncio.TimeoutError:
        try:
            data = await page.evaluate(f"fetch('{UPSTREAMS_URL}').then(r => r.json())")
        except Exception as e:
            log.warning("WB upstreams unavailable: %s", e)
            return
    routes = _parse_routes(data)
    if routes:
        _routes, _routes_loaded_at = routes, time.time()


def _image_url(nm_id: int) -> str | None:
    vol, part = nm_id // 100000, nm_id // 1000
    host = next((h for lo, hi, h in _routes if lo <= vol <= hi), None)
    if not host:
        return None
    return f"https://{host}/vol{vol}/part{part}/{nm_id}/images/c516x688/1.webp"


def _to_offer(p: dict) -> Offer | None:
    sizes = p.get("sizes") or []
    price = next((s["price"]["product"] for s in sizes if s.get("price", {}).get("product")), 0)
    if not price:
        price = p.get("salePriceU") or 0
    if not price:
        return None
    chars = (p.get("meta") or {}).get("characteristics") or []
    description = " ".join(f"{c.get('name', '')} {' '.join(c.get('values', []))}" for c in chars)
    brand = p.get("brand") or ""
    return Offer(
        title=f"{brand} {p['name']}".strip() if brand and brand.lower() not in p["name"].lower() else p["name"],
        price=price / 100,
        url=f"https://www.wildberries.ru/catalog/{p['id']}/detail.aspx",
        rating=p.get("reviewRating") or p.get("rating") or None,
        reviews=p.get("feedbacks"),
        description=description,
    )


async def _wallet_rules() -> tuple[float, float] | None:
    """(discount %, max discounted price) of the anonymous WB Wallet — what a visitor without an account sees."""
    global _wallet_rules_cache, _wallet_loaded_at
    if _wallet_rules_cache is None or time.time() - _wallet_loaded_at > ROUTES_TTL:
        try:
            async with httpx.AsyncClient(headers={"User-Agent": config.USER_AGENT}, timeout=15) as client:
                payment = (await client.get(WALLET_URL)).json()
                settings = (await client.get(SETTINGS_URL)).json()
            anon = next(d for d in payment["data"] if d.get("is_active") and "Незалогин" in d.get("wc_type", ""))
            max_price = float(settings["variables"]["wlt1DiscountDisplayMaxPrice"])
            _wallet_rules_cache, _wallet_loaded_at = (float(anon["discount_value"]), max_price), time.time()
        except Exception as e:
            log.warning("WB wallet rules unavailable: %s", e)
            return None
    return _wallet_rules_cache


def _wallet_price(price: float, rules: tuple[float, float] | None) -> float | None:
    if not rules:
        return None
    percent, max_price = rules
    discounted = math.floor(price * (1 - percent / 100))
    # WB hides the wallet price when it exceeds the anonymous wallet's one-time payment limit.
    return discounted if discounted <= max_price else None


def _items(data: dict) -> list | None:
    return data.get("products") or (data.get("data") or {}).get("products")


async def search(query: str) -> list[Offer]:
    async with manager.page() as page:
        loop = asyncio.get_running_loop()
        products: asyncio.Future = loop.create_future()
        upstreams: asyncio.Future = loop.create_future()

        async def on_response(r: Response) -> None:
            if r.status != 200:
                return
            if r.url.startswith(UPSTREAMS_URL) and not upstreams.done():
                try:
                    data = await r.json()
                except Exception:
                    return
                if not upstreams.done():
                    upstreams.set_result(data)
                return
            if products.done() or "/search" not in r.url or "resultset=catalog" not in r.url:
                return
            try:
                data = await r.json()
            except Exception:
                return
            items = _items(data)
            if items is not None and not products.done():
                products.set_result(items)

        page.on("response", on_response)
        await goto(page, search_url(query))
        try:
            items = await asyncio.wait_for(asyncio.shield(products), timeout=20)
        except asyncio.TimeoutError:
            # WB's antibot check occasionally hangs; a reload usually passes it.
            await goto(page, search_url(query))
            try:
                items = await asyncio.wait_for(products, timeout=25)
            except asyncio.TimeoutError:
                await raise_if_blocked(page, NAME)
                raise RuntimeError("Wildberries не вернул результаты поиска")

        await _ensure_routes(page, upstreams)
        try:
            images = await page.evaluate(IMAGES_JS)
        except Exception:
            images = {}
        wallet_rules = await _wallet_rules()

        offers = []
        for p in items:
            offer = _to_offer(p)
            if offer:
                offer.image = _image_url(p["id"]) or images.get(str(p["id"]))
                wallet_price = _wallet_price(offer.price, wallet_rules)
                if wallet_price is not None:
                    # WB shows the WB Wallet price as the headline price, the regular one next to it.
                    offer.price_regular = offer.price
                    offer.price = wallet_price
                offers.append(offer)
        return offers
