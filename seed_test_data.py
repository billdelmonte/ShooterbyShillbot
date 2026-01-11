from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from shillbot.config import load_settings


DB_PATH = "shillbot.sqlite3"


def parse_hhmm(s: str) -> tuple[int, int]:
    s = s.strip()
    return int(s[0:2]), int(s[3:5])


def most_recent_close(now_local: datetime, close_times: list[str]) -> datetime:
    candidates: list[datetime] = []
    for t in close_times:
        hh, mm = parse_hhmm(t)
        today = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        candidates.append(today)
        candidates.append(today - timedelta(days=1))
    past = [c for c in candidates if c <= now_local]
    return max(past)


def window_bounds(end_local: datetime, close_times: list[str]) -> tuple[datetime, datetime]:
    end = end_local.replace(second=0, microsecond=0)
    # Walk backwards until we hit the previous configured close time
    for mins in range(1, 24 * 60 + 1):
        cand = end - timedelta(minutes=mins)
        for t in close_times:
            hh, mm = parse_hhmm(t)
            if cand.hour == hh and cand.minute == mm:
                return cand, end
    # Fallback: 12h window
    return end - timedelta(hours=12), end


def main() -> None:
    s = load_settings()
    tz = ZoneInfo(s.timezone)

    now_local = datetime.now(tz)
    end_local = most_recent_close(now_local, s.close_times)
    start_local, end_local = window_bounds(end_local, s.close_times)

    # Choose a timestamp safely inside the window (10 minutes before window end)
    created_utc = (end_local - timedelta(minutes=10)).astimezone(timezone.utc).isoformat()

    conn = sqlite3.connect(DB_PATH)

    # Make sure registration exists
    conn.execute(
        "INSERT OR REPLACE INTO registrations(handle, wallet, registered_at_utc) VALUES(?,?,?)",
        ("william_test", "C4RmBaZJdXBJZsGxnRsjSrpfxAt6hz9BiBEVYpeMcCnD", created_utc),
    )

    # Insert a tweet that is guaranteed to be inside the active window
    conn.execute(
        """INSERT OR REPLACE INTO shills(
          tweet_id, handle, created_at_utc, text,
          like_count, retweet_count, quote_count, reply_count, view_count,
          has_media, media_type
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            "tweet_001",
            "william_test",
            created_utc,
            "Shooter is live. Go back to your shanties. $SHOOTER",
            12,
            3,
            1,
            2,
            2500,
            1,
            "image",
        ),
    )

    conn.commit()
    conn.close()

    print("OK: seeded test data")
    print(f"window_local: {start_local.isoformat()} .. {end_local.isoformat()}")
    print(f"tweet_created_at_utc: {created_utc}")


if __name__ == "__main__":
    main()
