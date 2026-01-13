from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from shillbot.models import Tweet
from shillbot.utils import extract_solana_address
from shillbot.x_api import XAPIClient


@dataclass(frozen=True)
class XIngestor:
    client: XAPIClient
    handle: str
    coin_handle: str
    coin_ticker: str
    token_mint: Optional[str]
    register_hashtag: str

    def has_registration_hashtag(self, tweet_text: str) -> bool:
        """
        Check if tweet contains the registration hashtag (case-insensitive).
        Returns True if hashtag is present, False otherwise.
        """
        # Look for the hashtag (case-insensitive)
        pattern = re.compile(
            rf"#{re.escape(self.register_hashtag)}\b", re.IGNORECASE
        )
        return bool(pattern.search(tweet_text))

    def scrape_registrations(self) -> List[Tuple[str, str]]:
        """
        Search for #shillbotregister hashtag tweets and extract wallet registrations.
        Returns list of (handle, wallet) tuples.
        Wallet can be anywhere in the tweet text.
        If hashtag exists but no valid SOL address found, wallet = 'N/A'.
        Most recent registration per handle wins (handled by DB PRIMARY KEY).
        """
        if not self.client.bearer_token:
            return []

        try:
            # Search for hashtag (exclude retweets)
            # Add # dynamically (config value has no #)
            query = f"#{self.register_hashtag} -is:retweet"
            raw_tweets = self.client.search_tweets(query, max_results=100)
            
            registrations: List[Tuple[str, str]] = []

            for raw in raw_tweets:
                try:
                    parsed = self.client.parse_tweet(raw)
                    if not parsed:
                        continue

                    handle = parsed.get("handle", "unknown")
                    text = parsed.get("text", "")
                    tweet_id = parsed.get("tweet_id", "unknown")
                    
                    # Check if hashtag is present
                    if not self.has_registration_hashtag(text):
                        continue
                    
                    # Extract Solana address from anywhere in the tweet
                    wallet = extract_solana_address(text)
                    if not wallet:
                        wallet = "N/A"
                    
                    registrations.append((handle, wallet))
                except Exception as e:
                    # Never crash on malformed tweets
                    tweet_id = raw.get("id", "unknown") if isinstance(raw, dict) else "unknown"
                    print(f"WARNING: Failed to process registration tweet {tweet_id}: {e}")
                    continue

            return registrations
        except Exception as e:
            # Log error but don't crash
            print(f"WARNING: Failed to scrape registrations: {e}")
            return []

    def _is_shill_tweet(self, parsed: dict) -> bool:
        """
        Filter tweets in Python to check if they match shill criteria.
        Case-insensitive substring matching.
        
        Matches if ANY of:
        - Mentions @shootercoinsol
        - Contains $shooter (case-insensitive)
        - Contains $shillbot (case-insensitive)
        - Contains token mint address (6iWeEmh5G7u8ERXBPn2y3CgKttDoDm7GDCc1368Upump or configured)
        """
        if not parsed:
            return False
        
        text_lower = parsed.get("text", "").lower()
        
        # Condition 1: Mentions @shootercoinsol
        if f"@{self.coin_handle.lower()}" in text_lower:
            return True
        
        # Condition 2: Contains $shooter (case-insensitive)
        if "$shooter" in text_lower:
            return True
        
        # Condition 3: Contains $shillbot (case-insensitive)
        if "$shillbot" in text_lower:
            return True
        
        # Condition 4: Contains token mint address
        # Check configured token_mint first, fallback to hardcoded address
        token_mint_to_check = self.token_mint or "6iWeEmh5G7u8ERXBPn2y3CgKttDoDm7GDCc1368Upump"
        if token_mint_to_check.lower() in text_lower:
            return True
        
        return False

    def collect_shill_tweets(self) -> List[Tweet]:
        """
        Collect shill tweets from last 24 hours using simplified query.
        
        Hard-limited to 24 hours to avoid X API window violations.
        Uses single keyword query ($SHOOTER) with fallback to shorter windows if needed.
        """
        if not self.client.bearer_token:
            return []

        from datetime import timedelta, timezone
        
        # Step 1: Hard-set time window to last 24 hours (canonical rule)
        # X API requires end_time to be at least 10 seconds in the past
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        end_time_utc = now_utc - timedelta(seconds=10)  # 10 seconds in past to satisfy API
        start_time_utc = end_time_utc - timedelta(hours=24)
        
        # Format for X API (ISO 8601 with Z suffix)
        end_time = end_time_utc.isoformat().replace("+00:00", "Z")
        start_time = start_time_utc.isoformat().replace("+00:00", "Z")

        # Step 2: Simplified query - use mention instead of cashtag (cashtag not available in API tier)
        # Try mention first, fallback to plain keyword if needed
        query = f"@{self.coin_handle}"  # e.g., "@shootercoinsol"

        # Step 3: Fallback window shrinking (24h -> 6h -> 1h)
        windows_to_try = [
            (24, start_time, end_time, "24 hours"),
            (6, (now_utc - timedelta(hours=6)).isoformat().replace("+00:00", "Z"), end_time, "6 hours"),
            (1, (now_utc - timedelta(hours=1)).isoformat().replace("+00:00", "Z"), end_time, "1 hour"),
        ]

        all_tweets: List[dict] = []
        seen_ids: set[str] = set()

        for hours, try_start, try_end, window_desc in windows_to_try:
            try:
                print(f"Attempting pull with {window_desc} window...")
                raw_tweets = self.client.search_tweets(
                    query=query,
                    start_time=try_start,
                    end_time=try_end,
                    max_results=100,
                )

                # Parse, filter, and deduplicate
                for raw in raw_tweets:
                    parsed = self.client.parse_tweet(raw)
                    if parsed and parsed["tweet_id"] not in seen_ids:
                        # Filter in Python after API pull
                        if self._is_shill_tweet(parsed):
                            all_tweets.append(parsed)
                            seen_ids.add(parsed["tweet_id"])

                # If we got results (even if empty), the query worked - break
                print(f"Successfully pulled {len(raw_tweets)} raw tweets with {window_desc} window")
                break

            except Exception as e:
                print(f"WARNING: Failed with {window_desc} window: {e}")
                if hours == 1:
                    # Last attempt failed, re-raise to surface error
                    raise
                # Continue to next smaller window
                continue

        # Convert to Tweet objects
        tweets: List[Tweet] = []
        since_dt = start_time_utc
        until_dt = end_time_utc

        for parsed in all_tweets:
            try:
                # Parse created_at_utc (X API returns ISO format)
                created_str = parsed["created_at_utc"]
                try:
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                # Double-check time window (API should filter, but verify)
                # Accept tweets from the last 24 hours regardless of which window succeeded
                if created_dt >= start_time_utc:
                    tweet = Tweet(
                        tweet_id=parsed["tweet_id"],
                        handle=parsed["handle"],
                        created_at_utc=created_dt.isoformat(),
                        text=parsed["text"],
                        like_count=parsed["like_count"],
                        retweet_count=parsed["retweet_count"],
                        quote_count=parsed["quote_count"],
                        reply_count=parsed["reply_count"],
                        view_count=parsed["view_count"],
                        has_media=parsed["has_media"],
                        media_type=parsed["media_type"],
                        is_retweet=parsed.get("is_retweet", False),
                        is_quote=parsed.get("is_quote", False),
                        has_original_text=parsed.get("has_original_text", False),
                    )
                    tweets.append(tweet)
            except (KeyError, ValueError) as e:
                # Skip malformed tweets
                continue

        return tweets

    def discover_tweet_ids(self, since_ymd: str, until_ymd: str) -> List[str]:
        """Legacy method - kept for compatibility. Uses hard-limited 24h window."""
        tweets = self.collect_shill_tweets()
        return [t.tweet_id for t in tweets]

    def fetch_tweet(self, tweet_id: str) -> Optional[Tweet]:
        """Legacy method - kept for compatibility."""
        return None

    def scrape_signup_replies_for_wallets(self, signup_tweet_id: str) -> List[Tuple[str, str]]:
        """Legacy method - replaced by scrape_registrations() for hashtag-based registration."""
        return []
