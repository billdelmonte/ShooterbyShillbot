from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests


@dataclass(frozen=True)
class XAPIClient:
    bearer_token: str
    timeout_s: int = 30

    BASE_URL = "https://api.twitter.com/2"

    def _get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make GET request with Bearer token authentication."""
        headers = {"Authorization": f"Bearer {self.bearer_token}"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=self.timeout_s)
            
            # Handle rate limiting (HTTP 429)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 900))  # Default to 15 minutes
                print(f"Rate limited. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                # Retry once
                resp = requests.get(url, headers=headers, params=params, timeout=self.timeout_s)
            
            # Step 4: Log RAW X API error body before raising
            if resp.status_code >= 400:
                print("=" * 80)
                print("X API ERROR - RAW RESPONSE:")
                print("=" * 80)
                print(f"HTTP Status: {resp.status_code}")
                print(f"URL: {resp.url}")
                print(f"Request Params: {params}")
                print(f"Response Headers: {dict(resp.headers)}")
                print(f"Response Text (first 2000 chars):")
                print(resp.text[:2000])
                try:
                    error_json = resp.json()
                    print(f"Response JSON:")
                    print(json.dumps(error_json, indent=2))
                except (ValueError, json.JSONDecodeError):
                    print("(Response is not valid JSON)")
                print("=" * 80)
            
            resp.raise_for_status()
            
            try:
                return resp.json()
            except ValueError as e:
                raise RuntimeError(
                    f"X API returned invalid JSON (status {resp.status_code}): {resp.text[:200]}"
                ) from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"X API request failed: {e}") from e

    def search_tweets(
        self,
        query: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_results: int = 100,
        since_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search recent tweets using X API v2.
        
        Args:
            query: Search query (hashtags, mentions, keywords, etc.)
            start_time: ISO 8601 datetime (YYYY-MM-DDTHH:mm:ssZ) - inclusive
            end_time: ISO 8601 datetime (YYYY-MM-DDTHH:mm:ssZ) - exclusive
            max_results: Max tweets to return (10-100, default 100)
            since_id: Return tweets newer than this tweet ID
            
        Returns:
            List of tweet objects with user data merged
        """
        url = f"{self.BASE_URL}/tweets/search/recent"
        
        params: Dict[str, Any] = {
            "query": query,
            "max_results": min(max_results, 100),  # API max is 100
            "tweet.fields": "id,text,created_at,author_id,public_metrics,attachments,referenced_tweets",
            "user.fields": "id,username,name",
            "expansions": "author_id",
        }
        
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if since_id:
            params["since_id"] = since_id

        all_tweets: List[Dict[str, Any]] = []
        next_token: Optional[str] = None
        
        # Handle pagination (max 100 tweets per request, up to max_results total)
        while len(all_tweets) < max_results:
            # Create fresh params dict for this iteration
            request_params = params.copy()
            if next_token:
                request_params["next_token"] = next_token
            
            try:
                data = self._get(url, request_params)
                
                tweets = data.get("data", [])
                if not tweets:
                    break
                
                users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
                
                # Merge user data into tweets
                for tweet in tweets:
                    author_id = tweet.get("author_id")
                    if author_id and author_id in users:
                        tweet["_user"] = users[author_id]
                    all_tweets.append(tweet)
                
                # Check for next page
                meta = data.get("meta", {})
                next_token = meta.get("next_token")
                if not next_token or len(all_tweets) >= max_results:
                    break
                    
            except Exception as e:
                print(f"WARNING: Error during pagination: {e}")
                break
        
        return all_tweets[:max_results]

    def parse_tweet(self, raw_tweet: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse X API v2 tweet response to our standardized format.
        
        Args:
            raw_tweet: Tweet object from X API (with _user field merged)
            
        Returns:
            Parsed tweet dict or None if invalid
        """
        try:
            tweet_id = str(raw_tweet.get("id", ""))
            if not tweet_id:
                return None

            user = raw_tweet.get("_user", {})
            handle = user.get("username", "").lstrip("@")
            if not handle:
                return None

            text = raw_tweet.get("text", "")
            created_at = raw_tweet.get("created_at", "")

            # Detect if tweet is a retweet or quote
            referenced = raw_tweet.get("referenced_tweets", [])
            is_retweet = any(ref.get("type") == "retweeted" for ref in referenced)
            is_quote = any(ref.get("type") == "quoted" for ref in referenced)
            
            # Heuristic: Check if retweet has added original text
            # Pure retweets typically start with "RT @user:" or just have minimal text
            has_original_text = False
            if is_retweet:
                # Check if text has substantial content beyond "RT @user:"
                text_lower = text.lower().strip()
                # Remove common RT patterns
                rt_patterns = [
                    r"^rt\s+@\w+:\s*",
                    r"^rt\s+@\w+\s+",
                ]
                cleaned_text = text_lower
                for pattern in rt_patterns:
                    cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)
                # If substantial text remains after removing RT pattern, has original thoughts
                has_original_text = len(cleaned_text.strip()) > 20
            elif is_quote:
                # Quote tweets always have original text
                has_original_text = True

            # Extract engagement metrics
            metrics = raw_tweet.get("public_metrics", {})
            like_count = int(metrics.get("like_count", 0))
            retweet_count = int(metrics.get("retweet_count", 0))
            reply_count = int(metrics.get("reply_count", 0))
            quote_count = int(metrics.get("quote_count", 0))
            # View/impression count not available in public_metrics for free tier
            # Try non_public_metrics if available, otherwise default to 0
            non_public_metrics = raw_tweet.get("non_public_metrics", {})
            view_count = int(non_public_metrics.get("impression_count", 0))
            if view_count == 0:
                view_count = int(metrics.get("impression_count", 0))

            # Check for media
            attachments = raw_tweet.get("attachments", {})
            media_keys = attachments.get("media_keys", [])
            has_media = len(media_keys) > 0
            # Default media type (could be enhanced with media lookup via includes.media)
            media_type = "" if not has_media else "image"

            return {
                "tweet_id": tweet_id,
                "handle": handle,
                "created_at_utc": created_at,
                "text": text,
                "like_count": like_count,
                "retweet_count": retweet_count,
                "quote_count": quote_count,
                "reply_count": reply_count,
                "view_count": view_count,
                "has_media": has_media,
                "media_type": media_type,
                "is_retweet": is_retweet,
                "is_quote": is_quote,
                "has_original_text": has_original_text,
            }
        except (KeyError, ValueError, TypeError):
            return None
