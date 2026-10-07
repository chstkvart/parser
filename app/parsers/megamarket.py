import asyncio
from urllib.parse import quote

from playwright.async_api import Response

from app.browser import goto, manager, raise_if_blocked
from app.models import Offer

NAME = "Мегамаркет"
BASE = "https://megamarket.ru"


def search_url(query: str) -> str:
    # Default sorting on Megamarket is "по популярности".
    return f"{BASE}/catalog/?q={quote(query)}"


def _num(*values) -> float | None:
    for v in values:
        if isinstance(v, (int, float)) and v:
            return float(v)
    return None


def _to_offer(item: dict) -> Offer | None:
    goods = item.get("goods") or {}
    title = goods.get("title") or item.get("title")
    price = _num(item.get("finalPrice"), item.get("price"), (item.get("priceRange") or {}).get("min"))
    url = goods.get("webUrl") or item.get("webUrl")
    if not (title and price and url):
        return None
    description = " ".join(
        str(a.get("value", "")) for a in goods.get("attributes") or [] if isinstance(a, dict)
    ) or str(goods.get("description") or "")
    image = goods.get("titleImage") or (goods.get("images") or [None])[0]
    reviews = item.get("reviewCount") or goods.get("reviewCount") or item.get("reviewsCount")
    return Offer(
        title=title,
        price=price,
        url=url if url.startswith("http") else BASE + url,
        rating=_num(item.get("rating"), goods.get("rating")),
        reviews=int(reviews) if reviews else None,
        image=image if isinstance(image, str) else None,
        description=description,
    )


async def search(query: str) -> list[Offer]:
    async with manager.page() as page:
        loop = asyncio.get_running_loop()
        result: asyncio.Future = loop.create_future()

        async def on_response(r: Response) -> None:
            if result.done() or "catalog/search" not in r.url or r.status != 200:
                return
            try:
                data = await r.json()
            except Exception:
                return
            if isinstance(data.get("items"), list) and not result.done():
                result.set_result(data["items"])

        page.on("response", on_response)
        await goto(page, search_url(query))
        try:
            items = await asyncio.wait_for(result, timeout=40)
        except asyncio.TimeoutError:
            await raise_if_blocked(page, NAME)
            raise RuntimeError("Мегамаркет не вернул результаты поиска")
        return [o for o in (_to_offer(i) for i in items) if o]
