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


app = FastAPI(title="Поиск по маркетплейсам", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' https: data:; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/marketplaces")
async def marketplaces():
    return [{"id": key, "name": module.NAME} for key, module in PARSERS.items()]


_LOOPBACK = {"127.0.0.1", "::1"}
_WINDOW = 60.0
_hits: dict[str, deque[float]] = defaultdict(deque)
_last_sweep = 0.0
_pending = 0


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if config.CLIENT_IP_HEADER:
        return request.headers.get(config.CLIENT_IP_HEADER, "").strip() or peer
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer in _LOOPBACK:
        # A local reverse proxy appends the address it saw; earlier entries come from the client and can be forged.
        return forwarded.split(",")[-1].strip() or peer
    return peer


def _sweep_idle(now: float) -> None:
    global _last_sweep
    if now - _last_sweep < _WINDOW:
        return
    _last_sweep = now
    for ip in [ip for ip, hits in _hits.items() if not hits or now - hits[-1] > _WINDOW]:
        del _hits[ip]


def _check_rate_limit(request: Request) -> None:
    now = time.monotonic()
    _sweep_idle(now)
    hits = _hits[_client_ip(request)]
    while hits and now - hits[0] > _WINDOW:
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
    global _pending
    if _pending >= config.MAX_PENDING_SEARCHES:
        raise HTTPException(503, "Сейчас слишком много поисков. Попробуйте через минуту.")
    _pending += 1
    try:
        return await _search(request, marketplace, module, q.strip())
    finally:
        _pending -= 1


async def _search(request: Request, marketplace: str, module, query: str) -> MarketplaceResult:
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
    except Exception:
        # Playwright errors carry call logs with URLs and selectors; they stay in the server log only.
        log.exception("%s failed", marketplace)
        result.error = "Не удалось получить данные с маркетплейса. Попробуйте ещё раз."
    return result
