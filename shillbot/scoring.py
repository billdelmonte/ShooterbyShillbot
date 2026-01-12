from __future__ import annotations

import math
from typing import Dict, List, Tuple

from shillbot.models import Tweet

# Scoring constants
MIN_SCORE = 1.0
MAX_SCORE = 10.0
BASE_SCORE_RETWEET = 1.0
BASE_SCORE_ORIGINAL = 2.0
BASE_SCORE_QUOTE = 2.5
BASE_SCORE_RETWEET_WITH_THOUGHTS = 2.0


def score_tweet(t: Tweet) -> float:
    """
    Score a single tweet using clamped 1-10 system.
    
    Rules:
    - Retweets (without added thoughts): 1.0 (lowest)
    - Retweets (with added thoughts): 2.0 + bonuses
    - Quote tweets: 2.5 + bonuses (always have own thoughts)
    - Original tweets: 2.0 + bonuses
    
    Bonuses:
    - Media: images (+0.5), videos/gifs (+1.0-1.5)
    - Engagement: likes, replies (scaled with diminishing returns)
    - Retweeted: double bonus if tweet was retweeted by others
    - Impressions: bonus for views (if available)
    """
    # Base score based on tweet type
    if t.is_retweet and not t.has_original_text:
        # Pure retweet, no added thoughts - lowest score
        base = BASE_SCORE_RETWEET
    elif t.is_retweet and t.has_original_text:
        # Retweet with own thoughts - bonus for adding thoughts
        base = BASE_SCORE_RETWEET_WITH_THOUGHTS
    elif t.is_quote:
        # Quote tweet - always has own thoughts
        base = BASE_SCORE_QUOTE
    else:
        # Original tweet
        base = BASE_SCORE_ORIGINAL
    
    # Media bonus
    media_bonus = 0.0
    if t.has_media:
        if t.media_type in ["video", "animated_gif"]:
            media_bonus = 1.5
        elif t.media_type == "gif":
            media_bonus = 1.0
        elif t.media_type == "image":
            media_bonus = 0.5
        else:
            # Default media bonus (unknown type)
            media_bonus = 0.5
    
    # Engagement bonuses (scaled with diminishing returns)
    likes_bonus = min(math.log1p(t.like_count) * 0.5, 3.0)
    replies_bonus = min(math.log1p(t.reply_count) * 0.3, 2.0)
    quotes_bonus = min(math.log1p(t.quote_count) * 0.4, 2.0)
    
    # Double bonus if retweeted (scaled with diminishing returns)
    # This is a significant bonus for viral content
    retweeted_bonus = min(math.log1p(t.retweet_count) * 1.0, 3.0)
    
    # Impressions bonus (if available, otherwise 0)
    # Very small weight as requested
    impression_bonus = 0.0
    if t.view_count > 0:
        impression_bonus = min(math.log1p(t.view_count) * 0.1, 1.0)
    
    # Calculate total score
    score = base + media_bonus + likes_bonus + replies_bonus + quotes_bonus + retweeted_bonus + impression_bonus
    
    # Clamp score between 1 and 10
    return min(max(score, MIN_SCORE), MAX_SCORE)


def score_tweets(
    tweets: List[Tweet],
    followers_by_handle: Dict[str, int] | None = None,
) -> Dict[str, Tuple[str, float]]:
    """
    Score all tweets and return best score per handle.
    
    Args:
        tweets: List of tweets to score
        followers_by_handle: Optional follower counts (not used in new scoring, kept for compatibility)
        
    Returns:
        Dict mapping handle to (best_tweet_id, best_score)
    """
    if followers_by_handle is None:
        followers_by_handle = {}

    # Group tweets by handle
    by_handle: Dict[str, List[Tweet]] = {}
    for t in tweets:
        by_handle.setdefault(t.handle, []).append(t)

    # Score each tweet and keep best per handle
    best: Dict[str, Tuple[str, float]] = {}
    for handle, items in by_handle.items():
        for t in items:
            score = score_tweet(t)
            
            cur = best.get(handle)
            if cur is None or score > cur[1]:
                best[handle] = (t.tweet_id, float(score))

    return best
