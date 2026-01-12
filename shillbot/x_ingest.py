from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from shillbot.models import Tweet
from shillbot.validation import extract_solana_pubkey, is_valid_solana_pubkey
from shillbot.x_api import XAPIClient


@dataclass(frozen=True)
class XIngestor:
    client: XAPIClient
    handle: str
    coin_handle: str
    coin_ticker: str
    token_mint: Optional[str]
    register_hashtag: str

    def parse_registration_hashtag(self, tweet_text: str) -> Optional[str]:
        """
        Parse registration hashtag format: #Shillbot-register [WALLET]
        Returns wallet address if found and valid, None otherwise.
        """
        # Look for the hashtag (case-insensitive)
        pattern = re.compile(
            rf"#{re.escape(self.register_hashtag)}\s+(\S+)", re.IGNORECASE
        )
        match = pattern.search(tweet_text)
        if not match:
            return None

        wallet_candidate = match.group(1).strip()
        # Remove any trailing punctuation
        wallet_candidate = wallet_candidate.rstrip(".,;:!?()[]{}")

        if is_valid_solana_pubkey(wallet_candidate):
            return wallet_candidate
        return None

    def scrape_registrations(self) -> List[Tuple[str, str]]:
        """
        Search for #Shillbot-register hashtag tweets and extract wallet registrations.
        Returns list of (handle, wallet) tuples.
        Most recent registration per handle wins (handled by DB PRIMARY KEY).
        """
        if not self.client.bearer_token:
            return []

        try:
            # Search for hashtag (exclude retweets)
            query = f"#{self.register_hashtag} -is:retweet"
            raw_tweets = self.client.search_tweets(query, max_results=100)
            
            registrations: List[Tuple[str, str]] = []

            for raw in raw_tweets:
                parsed = self.client.parse_tweet(raw)
                if not parsed:
                    continue

                handle = parsed["handle"]
                text = parsed["text"]
                wallet = self.parse_registration_hashtag(text)

                if wallet:
                    registrations.append((handle, wallet))

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
        - Contains $SHOOTER, $SHILLBOT, or $SHILL (case-insensitive)
        - Contains token mint address (substring)
        - Mentions @shootercoinsol or @shillbot
        - Is a retweet (detected in parsed tweet data)
        """
        if not parsed:
            return False
        
        text_lower = parsed.get("text", "").lower()
        handle_lower = parsed.get("handle", "").lower()
        
        # Check cashtags
        cashtags = ["$shooter", "$shillbot", "$shill"]
        for cashtag in cashtags:
            if cashtag in text_lower:
                return True
        
        # Check token mint address (substring match)
        if self.token_mint and self.token_mint.lower() in text_lower:
            return True
        
        # Check mentions
        mentions = [self.coin_handle.lower(), "shillbot"]
        for mention in mentions:
            if f"@{mention}" in text_lower or mention in handle_lower:
                return True
        
        # Check if retweet (retweets are included)
        if parsed.get("is_retweet", False):
            return True
        
        return False

    def collect_shill_tweets(
        self, since_utc: str, until_utc: str
    ) -> List[Tweet]:
        """
        Collect shill tweets using broad keyword search, then filter precisely in Python.
        
        Uses simple keyword search to avoid 400 errors, then filters for:
        - $SHOOTER, $SHILLBOT, $SHILL cashtags
        - @shootercoinsol mentions
        - Token mint address (if configured)
        - Retweets (included)
        """
        if not self.client.bearer_token:
            return []

        all_tweets: List[dict] = []
        seen_ids: set[str] = set()

        # Simple keyword query to avoid 400 errors
        # Do NOT use complex OR chains, do NOT exclude retweets
        query = f"{self.coin_ticker} shillbot @{self.coin_handle}"

        try:
            # X API expects ISO 8601 format (YYYY-MM-DDTHH:mm:ssZ)
            # Convert since_utc and until_utc to X API format
            start_time = since_utc.replace("+00:00", "Z").replace(" ", "T")
            if not start_time.endswith("Z"):
                # Ensure Z suffix
                if "+" in start_time:
                    start_time = start_time.split("+")[0] + "Z"
                else:
                    start_time = start_time + "Z"
            
            end_time = until_utc.replace("+00:00", "Z").replace(" ", "T")
            if not end_time.endswith("Z"):
                if "+" in end_time:
                    end_time = end_time.split("+")[0] + "Z"
                else:
                    end_time = end_time + "Z"

            raw_tweets = self.client.search_tweets(
                query=query,
                start_time=start_time,
                end_time=end_time,
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

        except Exception as e:
            print(f"WARNING: Failed to search shill tweets: {e}")

        # Convert to Tweet objects (already filtered by time window by API)
        tweets: List[Tweet] = []
        since_dt = datetime.fromisoformat(since_utc.replace("Z", "+00:00"))
        until_dt = datetime.fromisoformat(until_utc.replace("Z", "+00:00"))

        for parsed in all_tweets:
            try:
                # Parse created_at_utc (X API returns ISO format)
                created_str = parsed["created_at_utc"]
                try:
                    created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue

                # Double-check time window (API should filter, but verify)
                if since_dt <= created_dt < until_dt:
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
        """Legacy method - kept for compatibility."""
        since_utc = f"{since_ymd}T00:00:00Z"
        until_utc = f"{until_ymd}T23:59:59Z"
        tweets = self.collect_shill_tweets(since_utc, until_utc)
        return [t.tweet_id for t in tweets]

    def fetch_tweet(self, tweet_id: str) -> Optional[Tweet]:
        """Legacy method - kept for compatibility."""
        return None

    def scrape_signup_replies_for_wallets(self, signup_tweet_id: str) -> List[Tuple[str, str]]:
        """Legacy method - replaced by scrape_registrations() for hashtag-based registration."""
        return []
