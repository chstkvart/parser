from datetime import datetime

from pydantic import BaseModel


class Offer(BaseModel):
    title: str
    # The headline price the marketplace itself shows to a visitor.
    price: float
    url: str
    rating: float | None = None
    reviews: int | None = None
    image: str | None = None
    description: str = ""
    # Price without the payment-method discount, when the headline price includes one.
    price_regular: float | None = None


class MarketplaceResult(BaseModel):
    marketplace: str
    name: str
    offer: Offer | None = None
    error: str | None = None
    search_url: str
    fetched_at: datetime
