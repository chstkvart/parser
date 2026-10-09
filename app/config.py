import os

HEADLESS = os.getenv("HEADLESS", "1") != "0"
# "chrome" uses the locally installed Google Chrome: marketplaces block Playwright's bundled Chromium much more often.
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")
# Marketplaces may reject non-Russian IPs, e.g. http://user:pass@host:port
PROXY_URL = os.getenv("PROXY_URL", "").strip()
PARSER_TIMEOUT = float(os.getenv("PARSER_TIMEOUT", "60"))
# Set to 1 only when the app is reachable exclusively through a hosting proxy that sets X-Forwarded-For.
TRUST_PROXY = os.getenv("TRUST_PROXY", "0") == "1"
MAX_BROWSER_PAGES = int(os.getenv("MAX_BROWSER_PAGES", "8"))
# One search = one request per marketplace, so 40 requests ≈ 10 searches per minute from one visitor.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "40"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
)
