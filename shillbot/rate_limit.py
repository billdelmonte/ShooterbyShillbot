from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import List

from shillbot.models import Tweet


def truncate_to_minute(iso_str: str) -> str:
    """
    Truncate ISO datetime string to minute precision.
    Example: '2026-01-10T14:23:45.123456+00:00' -> '2026-01-10T14:23:00+00:00'
    """
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        truncated = dt.replace(second=0, microsecond=0)
        return truncated.isoformat()
    except (ValueError, AttributeError):
        # If parsing fails, return original (shouldn't happen with valid ISO strings)
        return iso_str


def apply_rate_limit(tweets: List[Tweet]) -> List[Tweet]:
    """
    Apply rate limiting: only 1 shill per minute per user.
    For multiple tweets in the same minute, keep the first one chronologically.
    
    Args:
        tweets: List of tweets to filter
        
    Returns:
        Filtered list with at most one tweet per handle per minute
    """
    if not tweets:
        return []

    # Group by (handle, minute_truncated(created_at_utc))
    groups: dict[tuple[str, str], List[Tweet]] = defaultdict(list)

    for tweet in tweets:
        minute_key = truncate_to_minute(tweet.created_at_utc)
        groups[(tweet.handle, minute_key)].append(tweet)

    # For each group, sort chronologically and take first
    filtered: List[Tweet] = []
    for (handle, minute), group_tweets in groups.items():
        # Sort by created_at_utc (ascending = oldest first)
        sorted_group = sorted(group_tweets, key=lambda t: t.created_at_utc)
        filtered.append(sorted_group[0])

    return filtered
