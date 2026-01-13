from __future__ import annotations

import argparse
import csv
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from shillbot.config import load_settings, SOLANA_RPC_URL, validate_rpc_url
from shillbot.db import DB, connect, init_db, get_last_window_end_balance, get_lifetime_total_fees_lamports, backfill_registration_status
from shillbot.models import Payout, ScoredEntry, Tweet
from shillbot.payouts import allocate_payouts, compute_payout_plan, lamports_to_sol, sol_to_lamports
from shillbot.solana_payer import SolanaCLIPayer
from shillbot.rate_limit import apply_rate_limit
from shillbot.reporting import build_report, export_interim_scoring_csv, write_report
from shillbot.scoring import score_tweets
from shillbot.solana_rpc import SolanaRPC
from shillbot.x_api import XAPIClient
from shillbot.x_ingest import XIngestor


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_hhmm(s: str) -> tuple[int, int]:
    s = s.strip()
    return int(s[0:2]), int(s[3:5])


def _now_local(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def _most_recent_close(now_local: datetime, close_times: list[str]) -> datetime:
    candidates: list[datetime] = []
    for t in close_times:
        hh, mm = _parse_hhmm(t)
        today = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        candidates.append(today)
        candidates.append(today - timedelta(days=1))
    past = [c for c in candidates if c <= now_local]
    return max(past)


def _window_id(end_local: datetime) -> str:
    return end_local.strftime("%Y%m%d-%H%M")


def _window_bounds(end_local: datetime, close_times: list[str]) -> tuple[datetime, datetime]:
    end = end_local.replace(second=0, microsecond=0)
    for mins in range(1, 24 * 60 + 1):
        cand = end - timedelta(minutes=mins)
        for t in close_times:
            hh, mm = _parse_hhmm(t)
            if cand.hour == hh and cand.minute == mm:
                return cand, end
    return end - timedelta(hours=12), end


def _get_mock_fees_lamports() -> int | None:
    v = os.getenv("SHILLBOT_MOCK_FEES_SOL", "").strip()
    if not v:
        return None
    try:
        sol = float(v)
    except ValueError:
        return None
    if sol < 0:
        return None
    return sol_to_lamports(sol)


def cmd_init_db() -> None:
    s = load_settings()
    init_db(DB(s.db_path))
    print(f"OK: initialized DB at {s.db_path}")


def cmd_ingest_shills() -> None:
    """
    Ingest shill tweets from X API.
    All shills go into shills table (cumulative, append-only).
    """
    s = load_settings()
    db = DB(s.db_path)

    if not s.x_api_bearer_token:
        print("WARNING: SHILLBOT_X_API_BEARER_TOKEN not set, skipping ingest")
        return

    client = XAPIClient(bearer_token=s.x_api_bearer_token, timeout_s=30)
    ingestor = XIngestor(
        client=client,
        handle=s.handle,
        coin_handle=s.coin_handle,
        coin_ticker=s.coin_ticker,
        token_mint=s.token_mint if s.token_mint else None,
        register_hashtag=s.register_hashtag,
    )

    # Collect shill tweets (hard-limited to last 24 hours internally)
    print("Collecting shill tweets from last 24 hours (hard-limited)...")
    tweets = ingestor.collect_shill_tweets()
    print(f"Found {len(tweets)} tweets after filtering")

    # Apply rate limiting
    tweets = apply_rate_limit(tweets)
    print(f"After rate limiting (1 per minute per user): {len(tweets)} tweets")

    # Store in shills table (cumulative, append-only)
    with connect(db) as conn:
        stored = 0
        for tweet in tweets:
            try:
                # INSERT OR IGNORE enforces uniqueness by tweet_id (cumulative, no duplicates)
                conn.execute(
                    """INSERT OR IGNORE INTO shills
                    (tweet_id, handle, created_at_utc, text, like_count, retweet_count,
                     quote_count, reply_count, view_count, has_media, media_type, is_registered)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
                    (
                        tweet.tweet_id,
                        tweet.handle,
                        tweet.created_at_utc,
                        tweet.text,
                        tweet.like_count,
                        tweet.retweet_count,
                        tweet.quote_count,
                        tweet.reply_count,
                        tweet.view_count,
                        1 if tweet.has_media else 0,
                        tweet.media_type,
                    ),
                )
                stored += 1
            except Exception as e:
                print(f"WARNING: Failed to store tweet {tweet.tweet_id}: {e}")

        # Backfill registration status (retroactively marks all past tweets)
        backfill_registration_status(conn)
        
        print(f"OK: Stored {stored} tweets in shills table")
        print("OK: Updated is_registered status for all shills")


def cmd_ingest(
    interim: bool = False,
    official: bool = False,
    window_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> None:
    """
    DEPRECATED: Use 'ingest-shills' instead.
    Kept for backward compatibility - routes to ingest-shills.
    """
    print("WARNING: 'ingest' command is deprecated. Use 'ingest-shills' instead.")
    cmd_ingest_shills()


def cmd_ingest_registrations() -> None:
    """Pull and store wallet registrations from #Shillbot-register hashtag."""
    s = load_settings()
    db = DB(s.db_path)

    if not s.x_api_bearer_token:
        print("WARNING: SHILLBOT_X_API_BEARER_TOKEN not set, skipping registration ingest")
        return

    client = XAPIClient(bearer_token=s.x_api_bearer_token, timeout_s=30)
    ingestor = XIngestor(
        client=client,
        handle=s.handle,
        coin_handle=s.coin_handle,
        coin_ticker=s.coin_ticker,
        token_mint=s.token_mint if s.token_mint else None,
        register_hashtag=s.register_hashtag,
    )

    print(f"Scraping registrations from #{s.register_hashtag} hashtag...")
    registrations = ingestor.scrape_registrations()
    print(f"Found {len(registrations)} registrations")

    with connect(db) as conn:
        stored = 0
        now_utc = datetime.now(timezone.utc).isoformat()
        for handle, wallet in registrations:
            try:
                # Always insert, even if wallet is "N/A"
                conn.execute(
                    "INSERT OR REPLACE INTO registrations (handle, wallet, registered_at_utc) VALUES (?,?,?)",
                    (handle, wallet, now_utc),
                )
                stored += 1
            except Exception as e:
                # Never crash on malformed data
                print(f"WARNING: Failed to store registration for {handle}: {e}")

        # Backfill registration status (retroactively marks all past tweets)
        backfill_registration_status(conn)
        
        print(f"OK: Stored {stored} registrations (most recent per handle wins)")
        print("OK: Updated is_registered status for all shills")


def cmd_export_interim(csv_only: bool = True) -> None:
    """
    Export interim/preview scoring to CSV.
    Uses JOIN query to include is_registered computed field.
    Exports ALL interim shills with scores and registration status.
    """
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        # Step 5: Use JOIN query with computed is_registered field
        # This includes ALL interim shills, not just scored ones
        query = """
            SELECT
              i.tweet_id,
              i.handle,
              i.text,
              i.created_at_utc,
              i.like_count,
              i.retweet_count,
              i.quote_count,
              i.reply_count,
              i.view_count,
              i.has_media,
              i.media_type,
              s.score,
              s.rank,
              CASE
                WHEN r.handle IS NOT NULL THEN 1
                ELSE 0
              END AS is_registered
            FROM interim_shills i
            LEFT JOIN interim_scores s ON i.tweet_id = s.tweet_id
            LEFT JOIN registrations r ON LOWER(i.handle) = LOWER(r.handle)
            ORDER BY i.created_at_utc ASC
        """
        
        rows = conn.execute(query).fetchall()

        if not rows:
            print("No interim shills found")
            return

        # Export to CSV
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(s.public_dir, "exports", f"interim_{timestamp}.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "tweet_id",
                "handle",
                "text",
                "created_at_utc",
                "score",
                "rank",
                "is_registered",
                "like_count",
                "retweet_count",
                "quote_count",
                "reply_count",
                "view_count",
                "has_media",
                "media_type",
            ])

            for row in rows:
                writer.writerow([
                    row["tweet_id"],
                    row["handle"],
                    row["text"],
                    row["created_at_utc"],
                    f"{row['score']:.6f}" if row["score"] is not None else "",
                    row["rank"] if row["rank"] is not None else "",
                    row["is_registered"],
                    row["like_count"],
                    row["retweet_count"],
                    row["quote_count"],
                    row["reply_count"],
                    row["view_count"],
                    "Yes" if row["has_media"] else "No",
                    row["media_type"],
                ])

        scored_count = sum(1 for r in rows if r["score"] is not None)
        registered_count = sum(1 for r in rows if r["is_registered"] == 1)
        print(f"OK: Exported {len(rows)} interim shills to {csv_path}")
        print(f"  - {scored_count} with scores")
        print(f"  - {registered_count} registered")


def cmd_export_all() -> None:
    """
    Export all core tables to CSV files in a timestamped folder.
    Exports: registrations, interim_shills, shills, interim_scores, payout_plan, payout_transactions.
    Creates one timestamped folder per run with stable filenames inside.
    """
    s = load_settings()
    db = DB(s.db_path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    exports_base_dir = os.path.join(s.public_dir, "exports")
    os.makedirs(exports_base_dir, exist_ok=True)
    
    # Create timestamped folder for this export run
    snapshot_dir = os.path.join(exports_base_dir, timestamp)
    os.makedirs(snapshot_dir, exist_ok=True)

    with connect(db) as conn:
        # Helper function to export a table
        def export_table(table_name: str, filename: str, order_by: str = None, add_insider_column: bool = False) -> int:
            """Export a table to CSV. Returns row_count."""
            # Check if table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if not cursor.fetchone():
                # Table doesn't exist, create empty CSV with headers from schema
                csv_path = os.path.join(snapshot_dir, filename)
                with open(csv_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    # Try to get columns from schema, or use empty list
                    try:
                        cursor = conn.execute(f"PRAGMA table_info({table_name})")
                        columns = [col[1] for col in cursor.fetchall()]
                        if add_insider_column:
                            columns.append("is_insider")
                        if columns:
                            writer.writerow(columns)
                    except:
                        pass  # Table doesn't exist, empty CSV
                return 0
            
            query = f"SELECT * FROM {table_name}"
            if order_by:
                query += f" ORDER BY {order_by}"
            rows = conn.execute(query).fetchall()
            
            if not rows:
                # Get column names from table schema
                cursor = conn.execute(f"PRAGMA table_info({table_name})")
                columns = [col[1] for col in cursor.fetchall()]
            else:
                columns = list(rows[0].keys())
            
            # Add is_insider column if requested
            if add_insider_column:
                from shillbot.config import INSIDER_HANDLES
                columns.append("is_insider")
            
            csv_path = os.path.join(snapshot_dir, filename)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                for row in rows:
                    if add_insider_column:
                        # Build row data excluding is_insider column
                        row_data = [row[col] for col in columns if col != "is_insider"]
                        # Compute is_insider for this row
                        handle = row["handle"] if "handle" in row.keys() else ""
                        is_insider = 1 if handle.lower() in INSIDER_HANDLES else 0
                        row_data.append(is_insider)
                    else:
                        row_data = [row[col] for col in columns]
                    writer.writerow(row_data)
            
            return len(rows)

        # Export canonical tables only (no interim tables)
        results = []
        
        # 1. registrations
        count = export_table("registrations", "registrations.csv", "registered_at_utc ASC")
        results.append(("registrations", count))
        
        # 2. shills (includes is_registered, score, and is_insider columns)
        count = export_table("shills", "shills.csv", "created_at_utc ASC", add_insider_column=True)
        results.append(("shills", count))
        
        # 3. payout_plan
        count = export_table("payout_plan", "payout_plan.csv", "window_id ASC, rank ASC")
        results.append(("payout_plan", count))
        
        # 4. payout_transactions
        count = export_table("payout_transactions", "payout_transactions.csv", "window_id ASC, sent_at_utc ASC")
        results.append(("payout_transactions", count))
        
        # Print summary
        print(f"Export snapshot: {snapshot_dir}/")
        for table_name, count in results:
            print(f"  OK {table_name} ({count} rows)")


def cmd_score() -> None:
    """
    Score all shills in the shills table.
    Updates score column in shills table for all tweets.
    Scores ALL shills (no registration filter).
    Registration status is updated retroactively.
    """
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        # Read all shills
        rows = conn.execute("SELECT * FROM shills ORDER BY created_at_utc DESC").fetchall()

        if not rows:
            print("No shills found")
            return

        tweets: List[Tweet] = []
        for r in rows:
            tweets.append(
                Tweet(
                    tweet_id=r["tweet_id"],
                    handle=r["handle"],
                    created_at_utc=r["created_at_utc"],
                    text=r["text"],
                    like_count=int(r["like_count"]),
                    retweet_count=int(r["retweet_count"]),
                    quote_count=int(r["quote_count"]),
                    reply_count=int(r["reply_count"]),
                    view_count=int(r["view_count"]),
                    has_media=bool(r["has_media"]),
                    media_type=r["media_type"],
                    # New fields default to False for backward compatibility with DB
                    is_retweet=r.get("is_retweet", False) if "is_retweet" in r else False,
                    is_quote=r.get("is_quote", False) if "is_quote" in r else False,
                    has_original_text=r.get("has_original_text", False) if "has_original_text" in r else False,
                )
            )

        # Apply rate limiting (same as close-once)
        tweets = apply_rate_limit(tweets)
        print(f"After rate limiting (1 per minute per user): {len(tweets)} tweets")

        # Score ALL shills (no registration filter)
        if not tweets:
            print("No tweets to score")
            return

        # Score tweets using same logic as close-once
        best = score_tweets(tweets=tweets)

        # Store scores in shills table
        scored_count = 0
        for handle, (tweet_id, score) in best.items():
            conn.execute(
                "UPDATE shills SET score = ? WHERE tweet_id = ?",
                (float(score), tweet_id)
            )
            scored_count += 1

        # Backfill registration status (retroactively marks all past tweets)
        backfill_registration_status(conn)

        print(f"OK: Scored {scored_count} shills")
        print("OK: Updated is_registered status for all shills")

        # Print ranked summary (top 10)
        ranked = []
        for handle, (tweet_id, score) in best.items():
            ranked.append((handle, tweet_id, score))
        ranked.sort(key=lambda x: x[2], reverse=True)

        print("\n" + "=" * 80)
        print("TOP SHILLS (Ranked by Score)")
        print("=" * 80)
        for i, (handle, tweet_id, score) in enumerate(ranked[:10], start=1):
            tweet = next((t for t in tweets if t.tweet_id == tweet_id), None)
            text_preview = tweet.text[:60] + "..." if tweet and len(tweet.text) > 60 else (tweet.text if tweet else "")
            print(f"{i:2d}. @{handle:20s} | Score: {score:6.2f} | {text_preview}")
        if len(ranked) > 10:
            print(f"... and {len(ranked) - 10} more")
        print("=" * 80)


def cmd_compute_payouts() -> None:
    """
    Compute payout plan from current scored shills (no window required).
    Reads current ranked results from shills table, calculates payouts using fixed top-10 percentages,
    and writes to payout_plan table. NO SOL MOVEMENT - pure calculation only.
    """
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        # Query shills table: only registered users, ordered by score DESC
        # This guarantees payout_plan is populated with registered users only
        shill_rows = conn.execute(
            """SELECT handle, score, tweet_id
               FROM shills
               WHERE is_registered = 1 AND score IS NOT NULL
               ORDER BY score DESC""",
        ).fetchall()
        
        if not shill_rows:
            print("No registered shills with scores found")
            return
        
        # Get wallet mappings from registrations
        regs = conn.execute("SELECT handle, wallet FROM registrations").fetchall()
        wallet_by_handle = {r["handle"]: r["wallet"] for r in regs}
        
        # Filter out insider handles (excluded from payouts)
        from shillbot.config import INSIDER_HANDLES
        eligible_rows = [
            row for row in shill_rows
            if row["handle"].lower() not in INSIDER_HANDLES
        ]
        
        if not eligible_rows:
            print("No eligible shills found (all are insiders)")
            return
        
        # Build ranked winners list: (handle, wallet, score)
        # Take top 10 after insider exclusion
        ranked_winners: List[Tuple[str, str, float]] = []
        for row in eligible_rows[:10]:
            handle = row["handle"]
            wallet = wallet_by_handle.get(handle)
            if wallet:
                ranked_winners.append((handle, wallet, float(row["score"])))
        
        if not ranked_winners:
            print("No registered wallets found")
            return
        
        # Get current treasury balance via RPC
        try:
            rpc = SolanaRPC(url=s.rpc_url, timeout_s=20)
            treasury_balance = rpc.get_balance_lamports(s.treasury_pubkey)
        except Exception as e:
            raise SystemExit(f"ERROR: Failed to get treasury balance: {e}")
        
        # Calculate distributable amount (treasury - 0.1 SOL reserve)
        reserve_sol = 0.1
        reserve_lamports = sol_to_lamports(reserve_sol)
        distributable_lamports = max(0, treasury_balance - reserve_lamports)
        
        # Calculate pot (100% of distributable - no share split)
        pot_lamports = distributable_lamports
        
        print(f"Treasury balance: {lamports_to_sol(treasury_balance):.9f} SOL")
        print(f"Reserve (gas): {reserve_sol} SOL ({reserve_lamports} lamports)")
        print(f"Distributable: {lamports_to_sol(distributable_lamports):.9f} SOL")
        print(f"Pot (for winners – 100% of distributable): {lamports_to_sol(pot_lamports):.9f} SOL ({pot_lamports} lamports)")
        
        # Use "CURRENT" as window_id for global/current payouts
        window_id = "CURRENT"
        
        # Compute payout plan
        min_payout_lamports = sol_to_lamports(s.min_payout_sol)
        plan = compute_payout_plan(
            window_id=window_id,
            pot_lamports=pot_lamports,
            ranked_winners=ranked_winners,
            min_payout_lamports=min_payout_lamports,
        )
        
        if not plan:
            print("No payouts to plan (pot too small or no eligible winners)")
            return
        
        # Clear old payout plan entries for this window_id (to remove insiders that were previously included)
        conn.execute("DELETE FROM payout_plan WHERE window_id=?", (window_id,))
        
        # Write to payout_plan table (INSERT for idempotency - we cleared old entries above)
        created_at_utc = datetime.now(timezone.utc).isoformat()
        stored = 0
        total_lamports = 0
        
        for window_id_val, rank, handle, wallet, score, percentage, amount_lamports in plan:
            conn.execute(
                """INSERT OR REPLACE INTO payout_plan
                   (window_id, rank, handle, wallet, score, percentage, amount_lamports, created_at_utc)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (window_id_val, rank, handle, wallet, score, percentage, amount_lamports, created_at_utc),
            )
            stored += 1
            total_lamports += amount_lamports
        
        print(f"\nOK: Stored {stored} payout plans for window {window_id}")
        print(f"Total payout amount: {lamports_to_sol(total_lamports):.9f} SOL ({total_lamports} lamports)")


def cmd_preview_payouts(window_id: str = "CURRENT") -> None:
    """
    Step 2a: Preview planned payouts for a window.
    Reads from payout_plan table and displays formatted table.
    """
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        rows = conn.execute(
            """SELECT rank, handle, wallet, score, percentage, amount_lamports
               FROM payout_plan
               WHERE window_id=?
               ORDER BY rank ASC""",
            (window_id,)
        ).fetchall()

        if not rows:
            print(f"No payout plan found for window {window_id}")
            print("Run 'compute-payouts' first")
            return

        print(f"\nPayout Plan for Window: {window_id}")
        print("=" * 100)
        print(f"{'Rank':<6} {'Handle':<20} {'Wallet':<45} {'%':<8} {'Amount (SOL)':<15} {'Score':<10}")
        print("-" * 100)

        total_lamports = 0
        for row in rows:
            rank = row["rank"]
            handle = row["handle"]
            wallet = row["wallet"]
            percentage = row["percentage"]
            amount_lamports = int(row["amount_lamports"])
            score = row["score"]
            
            amount_sol = lamports_to_sol(amount_lamports)
            total_lamports += amount_lamports
            
            wallet_short = wallet[:8] + "..." + wallet[-8:] if len(wallet) > 20 else wallet
            print(f"{rank:<6} @{handle:<19} {wallet_short:<45} {percentage*100:>6.1f}% {amount_sol:>14.9f} {score:>9.2f}")

        print("-" * 100)
        print(f"{'TOTAL':<6} {'':<20} {'':<45} {'100.0%':<8} {lamports_to_sol(total_lamports):>14.9f} {'':<10}")
        print("=" * 100)


def cmd_export_payouts(window_id: str = "CURRENT") -> None:
    """
    Step 2b: Export planned payouts to CSV.
    Reads from payout_plan table only (no recomputation).
    """
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        rows = conn.execute(
            """SELECT rank, handle, wallet, score, percentage, amount_lamports
               FROM payout_plan
               WHERE window_id=?
               ORDER BY rank ASC""",
            (window_id,)
        ).fetchall()

        if not rows:
            print(f"No payout plan found for window {window_id}")
            print("Run 'compute-payouts' first")
            return

        # Export to CSV
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        exports_dir = os.path.join(s.public_dir, "exports")
        os.makedirs(exports_dir, exist_ok=True)
        csv_path = os.path.join(exports_dir, f"payouts_{window_id}_{timestamp}.csv")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank",
                "handle",
                "wallet",
                "score",
                "percentage",
                "amount_lamports",
                "amount_sol",
            ])

            for row in rows:
                amount_lamports = int(row["amount_lamports"])
                amount_sol = lamports_to_sol(amount_lamports)
                writer.writerow([
                    row["rank"],
                    row["handle"],
                    row["wallet"],
                    f"{row['score']:.6f}",
                    f"{row['percentage']:.6f}",
                    amount_lamports,
                    f"{amount_sol:.9f}",
                ])

        print(f"OK: Exported {len(rows)} payout plans to {csv_path}")


def cmd_execute_payouts(window_id: str = "CURRENT") -> None:
    """
    Step 3: Execute planned payouts for a window.
    Reads from payout_plan, skips already-executed payouts, sends SOL transfers,
    and records in payout_transactions table.
    """
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        # Read payout plan
        plan_rows = conn.execute(
            """SELECT rank, handle, wallet, amount_lamports
               FROM payout_plan
               WHERE window_id=?
               ORDER BY rank ASC""",
            (window_id,)
        ).fetchall()

        if not plan_rows:
            print(f"No payout plan found for window {window_id}")
            print("Run 'compute-payouts' first")
            return

        # Check which payouts have already been executed
        executed_rows = conn.execute(
            "SELECT wallet FROM payout_transactions WHERE window_id=?",
            (window_id,)
        ).fetchall()
        executed_wallets = {row["wallet"] for row in executed_rows}

        # Filter out already-executed payouts
        pending = [row for row in plan_rows if row["wallet"] not in executed_wallets]

        if not pending:
            print(f"All payouts for window {window_id} have already been executed")
            return

        print(f"Found {len(pending)} pending payouts (out of {len(plan_rows)} total)")
        if executed_wallets:
            print(f"Skipping {len(executed_wallets)} already-executed payouts")

        # Initialize payer - fail hard if keypair is missing
        if not s.treasury_keypair_path:
            raise RuntimeError("FATAL: treasury_keypair_path is not set")

        if not os.path.exists(s.treasury_keypair_path):
            raise RuntimeError(f"FATAL: treasury keypair not found at {s.treasury_keypair_path}")

        payer = SolanaCLIPayer(
            keypair_path=s.treasury_keypair_path,
            rpc_url=s.rpc_url,
        )

        # Execute payouts
        sent_count = 0
        failed_count = 0
        sent_at_utc = datetime.now(timezone.utc).isoformat()

        for row in pending:
            wallet = row["wallet"]
            amount_lamports = int(row["amount_lamports"])
            amount_sol = lamports_to_sol(amount_lamports)
            handle = row["handle"]
            rank = row["rank"]

            tx_signature: Optional[str] = None

            try:
                transfer_status, tx_sig = payer.transfer_sol(to_wallet=wallet, sol=amount_sol)
                status = transfer_status
                tx_signature = tx_sig
                if status == "SENT" and tx_signature:
                    print(f"Sent {amount_sol:.9f} SOL to @{handle} (rank {rank}, wallet {wallet[:8]}...) - sig: {tx_signature}")
                    sent_count += 1
                else:
                    print(f"WARNING: Transfer to @{handle} returned status: {status}")
                    failed_count += 1
            except Exception as e:
                print(f"ERROR: Failed to send {amount_sol:.9f} SOL to @{handle}: {e}")
                failed_count += 1

            # Record in payout_transactions
            conn.execute(
                """INSERT OR REPLACE INTO payout_transactions
                   (window_id, wallet, amount_lamports, tx_signature, sent_at_utc)
                   VALUES (?,?,?,?,?)""",
                (window_id, wallet, amount_lamports, tx_signature, sent_at_utc),
            )

        print(f"\nOK: Executed payouts for window {window_id}")
        print(f"  - Sent: {sent_count}")
        print(f"  - Failed: {failed_count}")
        print(f"  - Already executed: {len(executed_wallets)}")


def cmd_close_once(force: bool = False) -> None:
    s = load_settings()
    db = DB(s.db_path)

    now_local = _now_local(s.timezone)
    end_local = _most_recent_close(now_local, s.close_times)
    start_local, end_local = _window_bounds(end_local, s.close_times)
    win_id = _window_id(end_local)

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    notes: list[str] = []
    with connect(db) as conn:
        existing = conn.execute("SELECT window_id, closed_at_utc FROM windows WHERE window_id=?", (win_id,)).fetchone()
        if existing and existing["closed_at_utc"] and not force:
            print(f"SKIP: window {win_id} already closed at {existing['closed_at_utc']}")
            return

        # Get or create window record
        window_row = conn.execute("SELECT window_id, start_balance_lamports FROM windows WHERE window_id=?", (win_id,)).fetchone()
        if window_row is None:
            conn.execute(
                "INSERT INTO windows(window_id, start_utc, end_utc) VALUES(?,?,?)",
                (win_id, _utc_iso(start_utc), _utc_iso(end_utc)),
            )
            window_row = conn.execute("SELECT window_id, start_balance_lamports FROM windows WHERE window_id=?", (win_id,)).fetchone()

        # Determine start balance: use existing start_balance if set, else use last window's end_balance, else take snapshot
        start_balance: int | None = None
        if window_row and window_row["start_balance_lamports"] is not None:
            start_balance = int(window_row["start_balance_lamports"])
            notes.append(f"start_balance_sol={start_balance/1_000_000_000:.6f} (from window record)")
        else:
            # Try to use last window's end_balance as start_balance
            last_end_bal = get_last_window_end_balance(conn)
            if last_end_bal is not None:
                start_balance = last_end_bal
                notes.append(f"start_balance_sol={start_balance/1_000_000_000:.6f} (from previous window end)")
            else:
                # First window: take snapshot now as start_balance (if treasury_pubkey is set)
                if s.treasury_pubkey:
                    try:
                        rpc = SolanaRPC(url=s.rpc_url, timeout_s=20)
                        start_balance = rpc.get_balance_lamports(s.treasury_pubkey)
                        notes.append(f"start_balance_sol={start_balance/1_000_000_000:.6f} (snapshot at window open)")
                    except Exception as e:
                        notes.append(f"WARNING: failed to read start_balance from Solana RPC: {e}")
                        start_balance = 0
                else:
                    start_balance = 0
                    notes.append("WARNING: SHILLBOT_TREASURY_PUBKEY not set, using start_balance=0")

            # Store start_balance
            conn.execute(
                "UPDATE windows SET start_balance_lamports=? WHERE window_id=?",
                (start_balance, win_id),
            )
            conn.execute(
                "INSERT INTO treasury_snapshots(taken_at_utc, lamports) VALUES(?,?)",
                (_utc_iso(start_utc), start_balance),
            )

        # At window close: take snapshot for end_balance
        if s.treasury_pubkey:
            try:
                rpc = SolanaRPC(url=s.rpc_url, timeout_s=20)
                end_balance = rpc.get_balance_lamports(s.treasury_pubkey)
                notes.append(f"end_balance_sol={end_balance/1_000_000_000:.6f} (snapshot at window close)")
            except Exception as e:
                notes.append(f"ERROR: failed to read end_balance from Solana RPC: {e}")
                # Fallback: use mock if available, else use start_balance
                mock = _get_mock_fees_lamports()
                if mock is not None:
                    end_balance = start_balance + mock
                    notes.append(f"end_balance_sol={end_balance/1_000_000_000:.6f} (computed from mock_fees)")
                else:
                    end_balance = start_balance
                    notes.append(f"WARNING: end_balance equals start_balance (RPC failed, no mock)")
        else:
            # No treasury_pubkey: use mock if available, else use start_balance
            mock = _get_mock_fees_lamports()
            if mock is not None:
                end_balance = start_balance + mock
                notes.append(f"end_balance_sol={end_balance/1_000_000_000:.6f} (computed from mock_fees, no treasury_pubkey)")
            else:
                end_balance = start_balance
                notes.append("WARNING: SHILLBOT_TREASURY_PUBKEY not set, end_balance equals start_balance (no mock)")

        # Store end_balance snapshot
        conn.execute(
            "INSERT INTO treasury_snapshots(taken_at_utc, lamports) VALUES(?,?)",
            (datetime.now(timezone.utc).isoformat(), end_balance),
        )

        # Compute fees_in: end_balance - start_balance
        # (Note: if real payouts were sent, they reduce end_balance, so fees_in is still correct)
        fees_in = end_balance - start_balance
        if fees_in < 0:
            notes.append(f"WARNING: negative fees_in={fees_in} (balance decreased, possibly due to payouts or withdrawals)")

        conn.execute(
            "UPDATE windows SET closed_at_utc=?, fees_in_lamports=?, end_balance_lamports=? WHERE window_id=?",
            (datetime.now(timezone.utc).isoformat(), int(fees_in), int(end_balance), win_id),
        )

        # Automatically pull official shills for this window if X API is configured
        if s.x_api_bearer_token:
            print(f"Pulling official shills for window {win_id}...")
            try:
                cmd_ingest(official=True, window_id=win_id)
            except Exception as e:
                notes.append(f"WARNING: Failed to pull official shills: {e}")

        rows = conn.execute(
            "SELECT * FROM shills WHERE created_at_utc >= ? AND created_at_utc < ?",
            (_utc_iso(start_utc), _utc_iso(end_utc)),
        ).fetchall()

        tweets: list[Tweet] = []
        for r in rows:
            tweets.append(
                Tweet(
                    tweet_id=r["tweet_id"],
                    handle=r["handle"],
                    created_at_utc=r["created_at_utc"],
                    text=r["text"],
                    like_count=int(r["like_count"]),
                    retweet_count=int(r["retweet_count"]),
                    quote_count=int(r["quote_count"]),
                    reply_count=int(r["reply_count"]),
                    view_count=int(r["view_count"]),
                    has_media=bool(r["has_media"]),
                    media_type=r["media_type"],
                    # New fields default to False for backward compatibility with DB
                    is_retweet=r.get("is_retweet", False) if "is_retweet" in r else False,
                    is_quote=r.get("is_quote", False) if "is_quote" in r else False,
                    has_original_text=r.get("has_original_text", False) if "has_original_text" in r else False,
                )
            )

        # Apply rate limiting (1 per minute per user)
        tweets = apply_rate_limit(tweets)
        notes.append(f"After rate limiting: {len(tweets)} tweets")

        # Filter out excluded tweets
        excluded_rows = conn.execute("SELECT tweet_id FROM excluded_tweets").fetchall()
        excluded_tweet_ids = {r["tweet_id"] for r in excluded_rows}
        tweets_before_exclude = len(tweets)
        tweets = [t for t in tweets if t.tweet_id not in excluded_tweet_ids]
        if tweets_before_exclude != len(tweets):
            notes.append(f"Excluded {tweets_before_exclude - len(tweets)} tweets (excluded_tweets table)")

        # Filter out blacklisted handles
        blacklist_rows = conn.execute("SELECT handle FROM blacklist_handles").fetchall()
        blacklisted_handles = {r["handle"] for r in blacklist_rows}
        tweets_before_blacklist = len(tweets)
        tweets = [t for t in tweets if t.handle not in blacklisted_handles]
        if tweets_before_blacklist != len(tweets):
            notes.append(f"Excluded {tweets_before_blacklist - len(tweets)} tweets (blacklisted handles)")

        # Score ALL shills (no registration filter)
        # Registration status is stored in is_registered column, used later for payouts
        best = score_tweets(tweets=tweets)
        
        # Store scores in shills table
        for handle, (tweet_id, score) in best.items():
            conn.execute(
                "UPDATE shills SET score = ? WHERE tweet_id = ?",
                (float(score), tweet_id)
            )
        
        # Backfill registration status (retroactively marks all past tweets)
        backfill_registration_status(conn)
        
        # Get wallet mappings for ranked list (only for registered users)
        regs = conn.execute("SELECT handle, wallet FROM registrations").fetchall()
        wallet_by_handle = {r["handle"]: r["wallet"] for r in regs}
        
        # Build ranked list from scored tweets (for reporting)
        ranked = []
        for handle, (tweet_id, score) in best.items():
            wallet = wallet_by_handle.get(handle)
            if wallet:  # Only include registered users in ranked list for reporting
                ranked.append((handle, wallet, score, tweet_id))
        ranked.sort(key=lambda x: x[2], reverse=True)

        # Filter out wallets that don't hold minimum token amount (if token verification is enabled)
        if s.token_mint and s.min_token_amount > 0:
            try:
                rpc = SolanaRPC(url=s.rpc_url, timeout_s=20)
                ranked_before_token_check = len(ranked)
                ranked_filtered = []
                for handle, wallet, score, tweet_id in ranked:
                    try:
                        token_balance = rpc.get_token_balance(wallet, s.token_mint)
                        if token_balance >= s.min_token_amount:
                            ranked_filtered.append((handle, wallet, score, tweet_id))
                        else:
                            notes.append(f"Excluded {handle} (wallet {wallet[:8]}...): token balance {token_balance} < min {s.min_token_amount}")
                    except Exception as e:
                        # If token balance check fails, include the wallet (don't exclude on error)
                        notes.append(f"WARNING: Token balance check failed for {handle} ({wallet[:8]}...): {e}, including anyway")
                        ranked_filtered.append((handle, wallet, score, tweet_id))
                
                ranked = ranked_filtered
                if ranked_before_token_check != len(ranked):
                    notes.append(f"Token verification: {ranked_before_token_check - len(ranked)} wallets excluded (below min {s.min_token_amount})")
            except Exception as e:
                notes.append(f"WARNING: Token balance verification failed: {e}, continuing without verification")

        # Store scores in shills table (already done above) and scores table (for window reporting)
        scored_entries: list[ScoredEntry] = []
        for i, (handle, wallet, score, tweet_id) in enumerate(ranked[: s.top_n], start=1):
            # Store in scores table for window-specific reporting
            conn.execute(
                "INSERT OR REPLACE INTO scores(window_id, handle, tweet_id, score, rank) VALUES(?,?,?,?,?)",
                (win_id, handle, tweet_id, float(score), int(i)),
            )
            scored_entries.append(
                ScoredEntry(handle=handle, tweet_id=tweet_id, wallet=wallet, score=float(score), rank=i)
            )

        # Reserve 0.1 SOL for gas (keep in treasury)
        reserve_sol = 0.1
        reserve_lamports = sol_to_lamports(reserve_sol)
        
        # Calculate distributable amount (fees minus reserve, but don't go negative)
        distributable_lamports = max(0, fees_in - reserve_lamports)
        
        # Apply shares to distributable amount (not total fees)
        pot_lamports = int(distributable_lamports * s.pot_share)
        marketing_lamports = int(distributable_lamports * s.marketing_share)
        dev_lamports = int(distributable_lamports * s.dev_share)
        
        # Note about reserve
        if fees_in > reserve_lamports:
            notes.append(f"Reserved {reserve_sol} SOL ({reserve_lamports} lamports) for gas, distributed {distributable_lamports} lamports")
        else:
            notes.append(f"WARNING: fees_in ({fees_in} lamports) less than reserve ({reserve_lamports} lamports), no distribution")
        
        # Step 1: Compute payout plan (NO SOL MOVEMENT)
        # This replaces the old allocate_payouts + execute logic
        notes.append("Payout plan computed (use 'execute-payouts' command to send SOL)")
        try:
            cmd_compute_payouts(win_id)
        except Exception as e:
            notes.append(f"WARNING: Failed to compute payout plan: {e}")

        # Read planned payouts for report (empty list if compute failed)
        sent: list[Payout] = []
        plan_rows = conn.execute(
            "SELECT wallet, amount_lamports FROM payout_plan WHERE window_id=?",
            (win_id,)
        ).fetchall()
        for row in plan_rows:
            sent.append(Payout(
                wallet=row["wallet"],
                lamports=int(row["amount_lamports"]),
                status="PLANNED",
                signature=None
            ))

        lifetime_total_fees = get_lifetime_total_fees_lamports(conn)

        report = build_report(
            window_id=win_id,
            fees_in_lamports=int(fees_in),
            start_balance_lamports=start_balance,
            end_balance_lamports=end_balance,
            current_treasury_balance_lamports=end_balance,
            lifetime_total_fees_lamports=lifetime_total_fees,
            scored=scored_entries,
            payouts=sent,
            notes=notes
            + [
                "v0_note: fees_in computed from Solana balance snapshots.",
                "payout_mode=PLANNED (use 'execute-payouts' command to send SOL)",
                f"window_local={start_local.isoformat()}..{end_local.isoformat()}",
                f"pot_lamports={pot_lamports}",
                f"top_n={s.top_n}",
            ],
        )
        latest_path = write_report(s.public_dir, win_id, report)

    print(f"OK: closed window {win_id}")
    print(f"Report: {latest_path}")
    print(f"Payout plan computed: {len(sent)} payouts planned")
    print(f"  Run 'python -m shillbot preview-payouts' to view plan")
    print(f"  Run 'python -m shillbot execute-payouts' to send SOL")


def cmd_serve() -> None:
    s = load_settings()
    import http.server
    import socketserver

    os.makedirs(s.public_dir, exist_ok=True)
    os.chdir(s.public_dir)

    port = 8000
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"Serving {s.public_dir} at http://localhost:{port}")
        httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(prog="shillbot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db")

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("--interim", action="store_true", help="Interim/preview pull (stored in interim_shills)")
    p_ingest.add_argument("--official", action="store_true", help="Official pull at window close (stored in shills)")
    p_ingest.add_argument("--window-id", type=str, help="Window ID for official pulls (format: YYYYMMDD-HHMM)")
    p_ingest.add_argument("--since", type=str, help="Start time for interim pulls (ISO format)")
    p_ingest.add_argument("--until", type=str, help="End time for interim pulls (ISO format)")

    sub.add_parser("ingest-shills", help="Ingest shill tweets from X API (all go to shills table)")
    sub.add_parser("ingest-registrations", help="Ingest registrations from X API")

    p_close = sub.add_parser("close-once")
    p_close.add_argument("--force", action="store_true")

    p_export = sub.add_parser("export-interim")
    p_export.add_argument("--csv", action="store_true", default=True, help="Export to CSV (default)")

    sub.add_parser("export-all", help="Export all data: registrations, interim shills, and official shills")

    p_score = sub.add_parser("score", help="Score all shills (updates score column in shills table)")
    p_score.add_argument("--interim", action="store_true", help="DEPRECATED: Use 'score' without flags")

    p_compute = sub.add_parser("compute-payouts", help="Compute payout plan from current scored shills (no window required)")

    p_preview = sub.add_parser("preview-payouts", help="Preview payout plan (defaults to CURRENT)")
    p_preview.add_argument("--window-id", type=str, default="CURRENT", help="Window ID (default: CURRENT)")

    p_export_payouts = sub.add_parser("export-payouts", help="Export payout plan to CSV (defaults to CURRENT)")
    p_export_payouts.add_argument("--window-id", type=str, default="CURRENT", help="Window ID (default: CURRENT)")

    p_execute = sub.add_parser("execute-payouts", help="Execute payout plan (defaults to CURRENT)")
    p_execute.add_argument("--window-id", type=str, default="CURRENT", help="Window ID (default: CURRENT)")

    sub.add_parser("serve")

    args = parser.parse_args()

    if args.cmd == "init-db":
        cmd_init_db()
        return
    if args.cmd == "ingest":
        cmd_ingest(
            interim=bool(args.interim),
            official=bool(args.official),
            window_id=getattr(args, "window_id", None),
            since=getattr(args, "since", None),
            until=getattr(args, "until", None),
        )
        return
    if args.cmd == "ingest-shills":
        cmd_ingest_shills()
        return
    if args.cmd == "ingest-registrations":
        cmd_ingest_registrations()
        return
    if args.cmd == "close-once":
        cmd_close_once(force=bool(args.force))
        return
    if args.cmd == "export-interim":
        cmd_export_interim(csv_only=bool(getattr(args, "csv", True)))
        return
    if args.cmd == "export-all":
        cmd_export_all()
        return
    if args.cmd == "score":
        if getattr(args, "interim", False):
            print("WARNING: --interim flag is deprecated. Scoring all shills.")
        cmd_score()
        return
    if args.cmd == "compute-payouts":
        cmd_compute_payouts()
        return
    if args.cmd == "preview-payouts":
        cmd_preview_payouts(window_id=str(args.window_id))
        return
    if args.cmd == "export-payouts":
        cmd_export_payouts(window_id=str(args.window_id))
        return
    if args.cmd == "execute-payouts":
        cmd_execute_payouts(window_id=str(args.window_id))
        return
    if args.cmd == "serve":
        cmd_serve()
        return

    raise SystemExit("Unknown command")
