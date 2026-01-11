from __future__ import annotations

import math
import re
from typing import Dict, List, Tuple

from shillbot.models import Tweet


_WORD_RE = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> List[str]:
    return _WORD_RE.findall(text.lower())


def jaccard(a: List[str], b: List[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def engagement_score(t: Tweet) -> float:
    raw = (
        1.0 * t.like_count
        + 2.0 * t.retweet_count
        + 2.0 * t.quote_count
        + 0.5 * t.reply_count
        + 0.0002 * t.view_count
    )
    return min(math.log1p(max(0.0, raw)), 10.0)


def originality_multiplier(t: Tweet, others: List[Tweet]) -> float:
    tokens = tokenize(t.text)
    if not tokens:
        return 0.2

    best_sim = 0.0
    for o in others:
        if o.tweet_id == t.tweet_id:
            continue
        best_sim = max(best_sim, jaccard(tokens, tokenize(o.text)))

    if best_sim >= 0.90:
        return 0.10
    if best_sim >= 0.85:
        return 0.25
    if best_sim >= 0.75:
        return 0.60
    return 1.00


def media_bonus(t: Tweet) -> float:
    if not t.has_media:
        return 0.0
    if t.media_type == "video":
        return 0.40
    if t.media_type == "gif":
        return 0.25
    if t.media_type == "image":
        return 0.20
    return 0.10


def score_tweets(
    tweets: List[Tweet],
    followers_by_handle: Dict[str, int] | None = None,
) -> Dict[str, Tuple[str, float]]:
    if followers_by_handle is None:
        followers_by_handle = {}

    by_handle: Dict[str, List[Tweet]] = {}
    for t in tweets:
        by_handle.setdefault(t.handle, []).append(t)

    best: Dict[str, Tuple[str, float]] = {}
    for handle, items in by_handle.items():
        for t in items:
            e = engagement_score(t)
            o = originality_multiplier(t, tweets)
            m = media_bonus(t)
            extras = max(0, len(items) - 2)
            v_mult = 1.0 / (1.0 + 0.35 * extras)
            score = (e + 0.15 * m) * o * v_mult

            cur = best.get(handle)
            if cur is None or score > cur[1]:
                best[handle] = (t.tweet_id, float(score))

    return best
