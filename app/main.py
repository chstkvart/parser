import asyncio
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.browser import BlockedError, manager
from app.matching import pick_best
from app.models import MarketplaceResult
from app.parsers import PARSERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await manager.close()


app = FastAPI(title="Поиск по маркетплейсам", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/marketplaces")
async def marketplaces():
    return [{"id": key, "name": module.NAME} for key, module in PARSERS.items()]


_LOOPBACK = {"127.0.0.1", "::1"}
_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    # X-Forwarded-For can be forged by clients, so honor it only when a trusted proxy sits in front of the app.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and (config.TRUST_PROXY or peer in _LOOPBACK):
        return forwarded.split(",")[0].strip()
    return peer


def _check_rate_limit(request: Request) -> None:
    now = time.monotonic()
    hits = _hits[_client_ip(request)]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= config.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(429, "Слишком много поисков подряд. Подождите минуту и попробуйте снова.")
    hits.append(now)


async def _run_unless_disconnected(request: Request, coro):
    """Cancels the parser when the user starts a new search, so abandoned searches don't hog the browser."""
    task = asyncio.ensure_future(coro)
    while not task.done():
        await asyncio.wait({task}, timeout=1)
        if not task.done() and await request.is_disconnected():
            task.cancel()
            raise asyncio.CancelledError
    return task.result()


@app.get("/api/search/{marketplace}", response_model=MarketplaceResult)
async def search(request: Request, marketplace: str, q: str = Query(..., min_length=2, max_length=200)):
    module = PARSERS.get(marketplace)
    if not module:
        raise HTTPException(404, "Неизвестный маркетплейс")
    _check_rate_limit(request)
    query = q.strip()
    result = MarketplaceResult(
        marketplace=marketplace,
        name=module.NAME,
        search_url=module.search_url(query),
        fetched_at=datetime.now(timezone.utc),
    )
    try:
        offers = await _run_unless_disconnected(
            request, asyncio.wait_for(module.search(query), timeout=config.PARSER_TIMEOUT)
        )
        result.fetched_at = datetime.now(timezone.utc)
        result.offer = pick_best(query, offers)
        if not result.offer:
            result.error = "Маркетплейс ничего не нашёл по этому запросу"
    except BlockedError as e:
        result.error = str(e)
    except asyncio.TimeoutError:
        result.error = "Сайт не ответил вовремя"
    except Exception as e:
        log.exception("%s failed", marketplace)
        result.error = f"Ошибка парсинга: {e}"
    return result
