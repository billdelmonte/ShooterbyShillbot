#!/usr/bin/env python3
"""Quick script to view registration and shill results from database."""

import sqlite3
import sys
from pathlib import Path

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

db_path = Path("shillbot.sqlite3")
if not db_path.exists():
    print(f"Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

print("=" * 80)
print("REGISTRATIONS")
print("=" * 80)
regs = conn.execute(
    "SELECT handle, wallet, registered_at_utc FROM registrations ORDER BY registered_at_utc DESC LIMIT 20"
).fetchall()
print(f"Total registrations: {len(regs)}")
for r in regs:
    print(f"  @{r['handle']}: {r['wallet']} ({r['registered_at_utc']})")

print("\n" + "=" * 80)
print("SHILLS (Final - used for scoring)")
print("=" * 80)
shills = conn.execute(
    "SELECT tweet_id, handle, created_at_utc, text, like_count, retweet_count FROM shills ORDER BY created_at_utc DESC LIMIT 20"
).fetchall()
print(f"Total shills: {len(shills)}")
for s in shills:
    text_preview = s['text'][:60] + "..." if len(s['text']) > 60 else s['text']
    print(f"  @{s['handle']}: {text_preview}")
    print(f"    Likes: {s['like_count']}, RTs: {s['retweet_count']} | {s['created_at_utc']}")
    print(f"    Tweet ID: {s['tweet_id']}")
    print()

print("=" * 80)
print("SHILLS (Interim - preview only)")
print("=" * 80)
interim = conn.execute(
    "SELECT tweet_id, handle, created_at_utc, text, like_count, retweet_count FROM interim_shills ORDER BY created_at_utc DESC LIMIT 20"
).fetchall()
print(f"Total interim shills: {len(interim)}")
for i in interim:
    text_preview = i['text'][:60] + "..." if len(i['text']) > 60 else i['text']
    print(f"  @{i['handle']}: {text_preview}")
    print(f"    Likes: {i['like_count']}, RTs: {i['retweet_count']} | {i['created_at_utc']}")
    print(f"    Tweet ID: {i['tweet_id']}")
    print()

print("=" * 80)
print("INTERIM SCORES")
print("=" * 80)
scores = conn.execute(
    "SELECT handle, tweet_id, score, rank, scored_at_utc FROM interim_scores ORDER BY rank ASC LIMIT 20"
).fetchall()
print(f"Total interim scores: {len(scores)}")
for s in scores:
    print(f"  {s['rank']:2d}. @{s['handle']:20s} | Score: {s['score']:6.2f} | Tweet: {s['tweet_id']}")
    print(f"      Scored at: {s['scored_at_utc']}")
print()

conn.close()
