from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from shillbot.config import load_settings
from shillbot.db import DB, connect, init_db, get_last_window_end_balance, get_lifetime_total_fees_lamports
from shillbot.models import Payout, ScoredEntry, Tweet
from shillbot.payouts import allocate_payouts, lamports_to_sol, sol_to_lamports, SolanaCLIPayer
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


def cmd_ingest(
    interim: bool = False,
    official: bool = False,
    window_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> None:
    """
    Ingest shill tweets.
    
    --interim: Preview pull, stored in interim_shills table, can be exported to CSV
    --official: Official pull at window close, stored in shills table, used for final scoring
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

    # Determine time window
    if official and window_id:
        # Parse window_id to get time bounds
        # Format: YYYYMMDD-HHMM
        try:
            date_part, time_part = window_id.split("-")
            year = int(date_part[0:4])
            month = int(date_part[4:6])
            day = int(date_part[6:8])
            hour = int(time_part[0:2])
            minute = int(time_part[2:4])
            end_local = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(s.timezone))
            start_local, end_local = _window_bounds(end_local, s.close_times)
            since_utc = _utc_iso(start_local)
            until_utc = _utc_iso(end_local)
        except (ValueError, IndexError) as e:
            print(f"ERROR: Invalid window_id format: {window_id}")
            return
    elif since and until:
        since_utc = since
        until_utc = until
    else:
        # Default: last 24 hours for interim, or use window bounds
        if interim:
            until_dt = _now_local(s.timezone)
            since_dt = until_dt - timedelta(hours=24)
            since_utc = _utc_iso(since_dt)
            until_utc = _utc_iso(until_dt)
        else:
            print("ERROR: Must specify --window-id for official pulls or --since/--until for interim")
            return

    # Collect shill tweets
    print(f"Collecting shill tweets from {since_utc} to {until_utc}...")
    tweets = ingestor.collect_shill_tweets(since_utc, until_utc)
    print(f"Found {len(tweets)} raw tweets")

    # Apply rate limiting
    tweets = apply_rate_limit(tweets)
    print(f"After rate limiting (1 per minute per user): {len(tweets)} tweets")

    # Store in appropriate table
    with connect(db) as conn:
        pulled_at = datetime.now(timezone.utc).isoformat()
        table_name = "interim_shills" if interim else "shills"

        stored = 0
        for tweet in tweets:
            try:
                if interim:
                    conn.execute(
                        """INSERT OR REPLACE INTO interim_shills
                        (tweet_id, handle, created_at_utc, text, like_count, retweet_count,
                         quote_count, reply_count, view_count, has_media, media_type, pulled_at_utc)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                            pulled_at,
                        ),
                    )
                else:
                    conn.execute(
                        """INSERT OR REPLACE INTO shills
                        (tweet_id, handle, created_at_utc, text, like_count, retweet_count,
                         quote_count, reply_count, view_count, has_media, media_type)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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

        print(f"OK: Stored {stored} tweets in {table_name} table")
        if interim:
            print("Note: Interim pulls are for preview only, not used in final scoring")


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

    print("Scraping registrations from #Shillbot-register hashtag...")
    registrations = ingestor.scrape_registrations()
    print(f"Found {len(registrations)} registrations")

    with connect(db) as conn:
        stored = 0
        now_utc = datetime.now(timezone.utc).isoformat()
        for handle, wallet in registrations:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO registrations (handle, wallet, registered_at_utc) VALUES (?,?,?)",
                    (handle, wallet, now_utc),
                )
                stored += 1
            except Exception as e:
                print(f"WARNING: Failed to store registration for {handle}: {e}")

        print(f"OK: Stored {stored} registrations (most recent per handle wins)")


def cmd_export_interim(csv_only: bool = True) -> None:
    """Export interim/preview scoring to CSV."""
    s = load_settings()
    db = DB(s.db_path)

    with connect(db) as conn:
        rows = conn.execute("SELECT * FROM interim_shills ORDER BY created_at_utc DESC").fetchall()

        if not rows:
            print("No interim shills found")
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

        # Get registrations for wallet mapping
        regs = conn.execute("SELECT handle, wallet FROM registrations").fetchall()
        wallet_by_handle = {r["handle"]: r["wallet"] for r in regs}
        tweets = [t for t in tweets if t.handle in wallet_by_handle]

        # Score tweets
        best = score_tweets(tweets=tweets)

        # Export to CSV
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        csv_path = os.path.join(s.public_dir, "exports", f"interim_{timestamp}.csv")
        export_interim_scoring_csv(tweets, best, csv_path)

        print(f"OK: Exported {len(best)} scored tweets to {csv_path}")


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

        regs = conn.execute("SELECT handle, wallet FROM registrations").fetchall()
        wallet_by_handle = {r["handle"]: r["wallet"] for r in regs}
        tweets = [t for t in tweets if t.handle in wallet_by_handle]

        best = score_tweets(tweets=tweets)
        ranked = []
        for handle, (tweet_id, score) in best.items():
            ranked.append((handle, wallet_by_handle[handle], score, tweet_id))
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

        scored_entries: list[ScoredEntry] = []
        for i, (handle, wallet, score, tweet_id) in enumerate(ranked[: s.top_n], start=1):
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
        
        payouts_alloc = allocate_payouts(
            pot_lamports=pot_lamports,
            winners=[(h, w, sc) for (h, w, sc, _) in ranked],
            top_n=s.top_n,
            min_payout_lamports=sol_to_lamports(s.min_payout_sol),
            payout_bins=s.payout_bins,
        )

        # Initialize payer if we have a keypair path and are not in dry run mode
        payer: Optional[SolanaCLIPayer] = None
        if s.treasury_keypair_path and not s.dry_run:
            if not os.path.exists(s.treasury_keypair_path):
                notes.append(f"WARNING: treasury_keypair_path does not exist: {s.treasury_keypair_path}, using DRY_RUN")
            else:
                payer = SolanaCLIPayer(
                    keypair_path=s.treasury_keypair_path,
                    rpc_url=s.rpc_url,
                    dry_run=False,
                )

        sent: list[Payout] = []
        for p in payouts_alloc:
            status = "DRY_RUN"
            signature: Optional[str] = None
            
            if payer is not None:
                # Real transfer
                try:
                    sol_amount = lamports_to_sol(p.lamports)
                    transfer_status, tx_sig = payer.transfer_sol(to_wallet=p.wallet, sol=sol_amount)
                    status = transfer_status
                    signature = tx_sig
                    if status == "SENT" and signature:
                        notes.append(f"Sent {sol_amount:.9f} SOL to {p.wallet} (sig: {signature})")
                    else:
                        notes.append(f"WARNING: Transfer to {p.wallet} returned status: {status}")
                except Exception as e:
                    status = "FAILED"
                    notes.append(f"ERROR: Failed to send {lamports_to_sol(p.lamports):.9f} SOL to {p.wallet}: {e}")
            else:
                # DRY_RUN mode (no payer or dry_run=True)
                if s.dry_run:
                    notes.append(f"DRY_RUN: Would send {lamports_to_sol(p.lamports):.9f} SOL to {p.wallet}")
                else:
                    notes.append(f"SKIPPED: No treasury_keypair_path configured, would send {lamports_to_sol(p.lamports):.9f} SOL to {p.wallet}")
            
            sent_p = Payout(wallet=p.wallet, lamports=p.lamports, status=status, signature=signature)
            sent.append(sent_p)
            conn.execute(
                "INSERT OR REPLACE INTO payouts(window_id, wallet, lamports, status, signature) VALUES(?,?,?,?,?)",
                (win_id, sent_p.wallet, int(sent_p.lamports), sent_p.status, sent_p.signature),
            )

        # Send marketing wallet payout
        if s.marketing_wallet and marketing_lamports > 0:
            marketing_status = "DRY_RUN"
            marketing_signature: Optional[str] = None
            
            if payer is not None:
                try:
                    marketing_sol = lamports_to_sol(marketing_lamports)
                    transfer_status, tx_sig = payer.transfer_sol(to_wallet=s.marketing_wallet, sol=marketing_sol)
                    marketing_status = transfer_status
                    marketing_signature = tx_sig
                    if marketing_status == "SENT" and marketing_signature:
                        notes.append(f"Sent {marketing_sol:.9f} SOL to marketing wallet {s.marketing_wallet} (sig: {marketing_signature})")
                    else:
                        notes.append(f"WARNING: Marketing wallet transfer returned status: {marketing_status}")
                except Exception as e:
                    marketing_status = "FAILED"
                    notes.append(f"ERROR: Failed to send {lamports_to_sol(marketing_lamports):.9f} SOL to marketing wallet: {e}")
            else:
                if s.dry_run:
                    notes.append(f"DRY_RUN: Would send {lamports_to_sol(marketing_lamports):.9f} SOL to marketing wallet {s.marketing_wallet}")
            
            marketing_payout = Payout(wallet=s.marketing_wallet, lamports=marketing_lamports, status=marketing_status, signature=marketing_signature)
            sent.append(marketing_payout)
            conn.execute(
                "INSERT OR REPLACE INTO payouts(window_id, wallet, lamports, status, signature) VALUES(?,?,?,?,?)",
                (win_id, marketing_payout.wallet, int(marketing_payout.lamports), marketing_payout.status, marketing_payout.signature),
            )

        # Send dev wallet payout
        if s.dev_wallet and dev_lamports > 0:
            dev_status = "DRY_RUN"
            dev_signature: Optional[str] = None
            
            if payer is not None:
                try:
                    dev_sol = lamports_to_sol(dev_lamports)
                    transfer_status, tx_sig = payer.transfer_sol(to_wallet=s.dev_wallet, sol=dev_sol)
                    dev_status = transfer_status
                    dev_signature = tx_sig
                    if dev_status == "SENT" and dev_signature:
                        notes.append(f"Sent {dev_sol:.9f} SOL to dev wallet {s.dev_wallet} (sig: {dev_signature})")
                    else:
                        notes.append(f"WARNING: Dev wallet transfer returned status: {dev_status}")
                except Exception as e:
                    dev_status = "FAILED"
                    notes.append(f"ERROR: Failed to send {lamports_to_sol(dev_lamports):.9f} SOL to dev wallet: {e}")
            else:
                if s.dry_run:
                    notes.append(f"DRY_RUN: Would send {lamports_to_sol(dev_lamports):.9f} SOL to dev wallet {s.dev_wallet}")
            
            dev_payout = Payout(wallet=s.dev_wallet, lamports=dev_lamports, status=dev_status, signature=dev_signature)
            sent.append(dev_payout)
            conn.execute(
                "INSERT OR REPLACE INTO payouts(window_id, wallet, lamports, status, signature) VALUES(?,?,?,?,?)",
                (win_id, dev_payout.wallet, int(dev_payout.lamports), dev_payout.status, dev_payout.signature),
            )

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
                f"payout_mode={'DRY_RUN' if (payer is None or s.dry_run) else 'REAL'}",
                f"window_local={start_local.isoformat()}..{end_local.isoformat()}",
                f"pot_lamports={pot_lamports}",
                f"top_n={s.top_n}",
            ],
        )
        latest_path = write_report(s.public_dir, win_id, report)

    print(f"OK: closed window {win_id}")
    print(f"Report: {latest_path}")
    
    # Count payouts by status
    status_counts: dict[str, int] = {}
    for p in sent:
        status_counts[p.status] = status_counts.get(p.status, 0) + 1
    
    status_summary = ", ".join(f"{count} {status}" for status, count in sorted(status_counts.items()))
    print(f"Payouts: {len(sent)} total ({status_summary})")


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

    sub.add_parser("ingest-registrations")

    p_close = sub.add_parser("close-once")
    p_close.add_argument("--force", action="store_true")

    p_export = sub.add_parser("export-interim")
    p_export.add_argument("--csv", action="store_true", default=True, help="Export to CSV (default)")

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
    if args.cmd == "ingest-registrations":
        cmd_ingest_registrations()
        return
    if args.cmd == "close-once":
        cmd_close_once(force=bool(args.force))
        return
    if args.cmd == "export-interim":
        cmd_export_interim(csv_only=bool(getattr(args, "csv", True)))
        return
    if args.cmd == "serve":
        cmd_serve()
        return

    raise SystemExit("Unknown command")
