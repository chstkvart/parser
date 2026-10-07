import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from app import config

log = logging.getLogger(__name__)

BLOCK_MARKERS = (
    "Доступ ограничен",
    "похожи на автоматические",
    "Подозрительная активность",
    "Похоже, нет соединения",
    "Вы не робот",
    "showcaptcha",
)


class BlockedError(Exception):
    pass


def _proxy_settings() -> dict | None:
    if not config.PROXY_URL:
        return None
    u = urlparse(config.PROXY_URL)
    proxy = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
    if u.username:
        proxy["username"] = u.username
        proxy["password"] = u.password or ""
    return proxy


class BrowserManager:
    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self) -> Browser:
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return self._browser
            if not self._pw:
                self._pw = await async_playwright().start()
            kwargs = dict(
                headless=config.HEADLESS,
                args=["--disable-blink-features=AutomationControlled"],
                proxy=_proxy_settings(),
            )
            try:
                self._browser = await self._pw.chromium.launch(channel=config.BROWSER_CHANNEL or None, **kwargs)
            except Exception:
                log.warning("Browser channel %r unavailable, falling back to bundled Chromium", config.BROWSER_CHANNEL)
                self._browser = await self._pw.chromium.launch(**kwargs)
            return self._browser

    @asynccontextmanager
    async def page(self):
        browser = await self._ensure_browser()
        context: BrowserContext = await browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            user_agent=config.USER_AGENT,
            viewport={"width": 1440, "height": 900},
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page: Page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = None
        self._pw = None


manager = BrowserManager()


async def goto(page: Page, url: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        # Antibot challenges reload the page mid-navigation; the caller waits for content anyway.
        log.debug("goto %s: %s", url, e)


async def raise_if_blocked(page: Page, site: str) -> None:
    try:
        text = (await page.title()) + " " + (await page.inner_text("body", timeout=3000))[:3000]
    except Exception:
        return
    if any(m.lower() in text.lower() for m in BLOCK_MARKERS) or "showcaptcha" in page.url:
        hint = "" if config.PROXY_URL else " Скорее всего, нужен российский IP — укажите прокси в PROXY_URL."
        raise BlockedError(f"{site} заблокировал запрос (антибот/капча).{hint}")
