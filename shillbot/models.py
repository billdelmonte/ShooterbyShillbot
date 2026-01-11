from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Tweet:
    tweet_id: str
    handle: str
    created_at_utc: str
    text: str
    like_count: int
    retweet_count: int
    quote_count: int
    reply_count: int
    view_count: int
    has_media: bool
    media_type: str


@dataclass(frozen=True)
class ScoredEntry:
    handle: str
    tweet_id: str
    wallet: str
    score: float
    rank: int


@dataclass(frozen=True)
class Payout:
    wallet: str
    lamports: int
    status: str
    signature: Optional[str]
