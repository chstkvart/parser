import asyncio
import logging
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
