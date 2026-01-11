from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS registrations (
  handle TEXT PRIMARY KEY,
  wallet TEXT NOT NULL,
  registered_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shills (
  tweet_id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  text TEXT NOT NULL,
  like_count INTEGER NOT NULL,
  retweet_count INTEGER NOT NULL,
  quote_count INTEGER NOT NULL,
  reply_count INTEGER NOT NULL,
  view_count INTEGER NOT NULL,
  has_media INTEGER NOT NULL,
  media_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS windows (
  window_id TEXT PRIMARY KEY,
  start_utc TEXT NOT NULL,
  end_utc TEXT NOT NULL,
  closed_at_utc TEXT,
  fees_in_lamports INTEGER DEFAULT 0,
  start_balance_lamports INTEGER,
  end_balance_lamports INTEGER
);

CREATE TABLE IF NOT EXISTS scores (
  window_id TEXT NOT NULL,
  handle TEXT NOT NULL,
  tweet_id TEXT NOT NULL,
  score REAL NOT NULL,
  rank INTEGER NOT NULL,
  PRIMARY KEY (window_id, handle)
);

CREATE TABLE IF NOT EXISTS payouts (
  window_id TEXT NOT NULL,
  wallet TEXT NOT NULL,
  lamports INTEGER NOT NULL,
  status TEXT NOT NULL,
  signature TEXT,
  PRIMARY KEY (window_id, wallet)
);

CREATE TABLE IF NOT EXISTS blacklist_handles (
  handle TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS excluded_tweets (
  tweet_id TEXT PRIMARY KEY,
  reason TEXT NOT NULL,
  created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS treasury_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  taken_at_utc TEXT NOT NULL,
  lamports INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS interim_shills (
  tweet_id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  created_at_utc TEXT NOT NULL,
  text TEXT NOT NULL,
  like_count INTEGER NOT NULL,
  retweet_count INTEGER NOT NULL,
  quote_count INTEGER NOT NULL,
  reply_count INTEGER NOT NULL,
  view_count INTEGER NOT NULL,
  has_media INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  pulled_at_utc TEXT NOT NULL
);
"""
 

@dataclass(frozen=True)
class DB:
    path: str


@contextmanager
def connect(db: DB) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db.path)
    try:
        conn.row_factory = sqlite3.Row
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db: DB) -> None:
    with connect(db) as conn:
        conn.executescript(SCHEMA)
        # Migration: add balance columns if they don't exist
        try:
            conn.execute("ALTER TABLE windows ADD COLUMN start_balance_lamports INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE windows ADD COLUMN end_balance_lamports INTEGER")
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migration: create interim_shills table if it doesn't exist
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interim_shills (
                  tweet_id TEXT PRIMARY KEY,
                  handle TEXT NOT NULL,
                  created_at_utc TEXT NOT NULL,
                  text TEXT NOT NULL,
                  like_count INTEGER NOT NULL,
                  retweet_count INTEGER NOT NULL,
                  quote_count INTEGER NOT NULL,
                  reply_count INTEGER NOT NULL,
                  view_count INTEGER NOT NULL,
                  has_media INTEGER NOT NULL,
                  media_type TEXT NOT NULL,
                  pulled_at_utc TEXT NOT NULL
                )
            """)
        except sqlite3.OperationalError:
            pass  # Table already exists


def get_last_snapshot_lamports(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute(
        "SELECT lamports FROM treasury_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return int(row["lamports"]) if row else None


def get_lifetime_total_fees_lamports(conn: sqlite3.Connection) -> int:
    """Sum of all fees_in_lamports from closed windows."""
    row = conn.execute(
        "SELECT COALESCE(SUM(fees_in_lamports), 0) AS total FROM windows WHERE closed_at_utc IS NOT NULL"
    ).fetchone()
    return int(row["total"]) if row else 0


def get_last_window_end_balance(conn: sqlite3.Connection) -> Optional[int]:
    """Get end_balance_lamports from the most recently closed window."""
    row = conn.execute(
        "SELECT end_balance_lamports FROM windows WHERE closed_at_utc IS NOT NULL AND end_balance_lamports IS NOT NULL ORDER BY closed_at_utc DESC LIMIT 1"
    ).fetchone()
    return int(row["end_balance_lamports"]) if row and row["end_balance_lamports"] is not None else None
