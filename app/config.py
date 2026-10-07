import os

HEADLESS = os.getenv("HEADLESS", "1") != "0"
# "chrome" uses the locally installed Google Chrome: marketplaces block Playwright's bundled Chromium much more often.
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")
# Ozon and Megamarket reject non-Russian IPs, e.g. http://user:pass@host:port
PROXY_URL = os.getenv("PROXY_URL", "").strip()
PARSER_TIMEOUT = float(os.getenv("PARSER_TIMEOUT", "60"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
)
