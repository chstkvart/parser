import re

from app.models import Offer

SYNONYMS = {
    "айфон": "iphone",
    "айпад": "ipad",
    "макбук": "macbook",
    "аирподс": "airpods",
    "эирподс": "airpods",
    "эпл": "apple",
    "эппл": "apple",
    "самсунг": "samsung",
    "сяоми": "xiaomi",
    "ксиаоми": "xiaomi",
    "редми": "redmi",
    "хуавей": "huawei",
    "хонор": "honor",
    "поко": "poco",
    "дайсон": "dyson",
    "сони": "sony",
    "плейстейшн": "playstation",
    "пс5": "ps5",
}

# Dropped unless the query itself asks for an accessory, so "iphone 16" doesn't return a case for iPhone 16.
ACCESSORY_STEMS = (
    "чехол", "чехл", "стекл", "пленк", "кабел", "зарядн", "адаптер", "накладк", "бампер", "ремеш",
    "держател", "наклейк", "коробк", "муляж", "игрушк", "кейс", "защитн", "подставк", "брелок",
    "запчаст", "дисплейн", "шлейф", "корпус",
)
ACCESSORY_TITLE_WORDS = 3
MIN_PARTIAL_COVERAGE = 0.5
FALLBACK_TOP = 5

_WORD_RE = re.compile(r"[0-9a-zа-я]+")


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("ё", "е"))


def _query_tokens(query: str) -> list[str]:
    return [SYNONYMS.get(t, t) for t in tokenize(query)]


def _token_matches(token: str, words: set[str]) -> bool:
    if token in words:
        return True
    if token.isdigit():
        return False
    # Rough Russian morphology: "смартфоны" should match "смартфон".
    stem = token[: max(4, len(token) - 2)] if len(token) >= 5 else token
    return any(w.startswith(stem) for w in words)


def keyword_coverage(q_tokens: list[str], offer: Offer) -> float:
    """Share of query keywords found in the offer's title or description."""
    if not q_tokens:
        return 0.0
    words = set(tokenize(offer.title)) | set(tokenize(offer.description))
    return sum(_token_matches(t, words) for t in q_tokens) / len(q_tokens)


def _is_unwanted_accessory(q_tokens: list[str], offer: Offer) -> bool:
    if any(t.startswith(s) for t in q_tokens for s in ACCESSORY_STEMS):
        return False
    head = tokenize(offer.title)[:ACCESSORY_TITLE_WORDS]
    return any(w.startswith(s) for w in head for s in ACCESSORY_STEMS)


def _score(offer: Offer) -> float:
    # Bayesian average: 5.0 from 2 reviews must not beat 4.9 from 3000 reviews.
    prior_rating, prior_weight = 4.0, 30
    rating = offer.rating or 0.0
    reviews = offer.reviews or 0
    return (rating * reviews + prior_rating * prior_weight) / (reviews + prior_weight)


def _select_candidates(q_tokens: list[str], offers: list[Offer]) -> list[Offer]:
    """Strictest non-empty tier wins, so any query the marketplace itself answered still yields an offer."""
    coverage = [(o, keyword_coverage(q_tokens, o)) for o in offers]
    full = [o for o, c in coverage if c == 1.0]
    tiers = [
        [o for o in full if not _is_unwanted_accessory(q_tokens, o)],
        full,
    ]
    best_partial = max((c for _, c in coverage), default=0.0)
    if best_partial >= MIN_PARTIAL_COVERAGE:
        tiers.append([o for o, c in coverage if c == best_partial])
    # Keywords may be transliterated or misspelled; the marketplace's own top hits are then the best guess.
    tiers.append(offers[:FALLBACK_TOP])
    return next(t for t in tiers if t)


def pick_best(query: str, offers: list[Offer], top_n: int = 40) -> Offer | None:
    """`offers` must be in the marketplace's popularity order; picks the best-rated among the most popular matches."""
    offers = [o for o in offers if o.price > 0]
    if not offers:
        return None
    candidates = _select_candidates(_query_tokens(query), offers)[:top_n]
    ranked = sorted(enumerate(candidates), key=lambda p: (-_score(p[1]), p[0]))
    return ranked[0][1]


def parse_price(text: str | None) -> float:
    if not text:
        return 0.0
    digits = re.sub(r"[^\d,.]", "", text.replace("\u2009", "").replace("\xa0", "")).replace(",", ".")
    m = re.match(r"\d+(\.\d+)?", digits)
    return float(m.group(0)) if m else 0.0


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None
