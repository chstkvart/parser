import os

HEADLESS = os.getenv("HEADLESS", "1") != "0"
# "chrome" uses the locally installed Google Chrome: marketplaces block Playwright's bundled Chromium much more often.
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "chrome")
# Marketplaces may reject non-Russian IPs, e.g. http://user:pass@host:port
PROXY_URL = os.getenv("PROXY_URL", "").strip()
PARSER_TIMEOUT = float(os.getenv("PARSER_TIMEOUT", "60"))
# Header in which the hosting's edge proxy puts the visitor IP, overwriting any client-sent value
# (Render: True-Client-IP from Cloudflare). Set only when the app is reachable exclusively through that proxy.
CLIENT_IP_HEADER = os.getenv("CLIENT_IP_HEADER", "").strip().lower()
MAX_BROWSER_PAGES = int(os.getenv("MAX_BROWSER_PAGES", "8"))
# Searches beyond this (running + waiting for a browser tab) are refused, so a flood from many IPs can't
# queue up work for minutes and starve everyone else.
MAX_PENDING_SEARCHES = int(os.getenv("MAX_PENDING_SEARCHES", str(MAX_BROWSER_PAGES * 4)))
# One search = one request per marketplace, so 40 requests ≈ 10 searches per minute from one visitor.
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "40"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
)
