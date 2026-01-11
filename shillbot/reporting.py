from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from shillbot.models import Payout, ScoredEntry, Tweet


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def write_report(public_dir: str, window_id: str, report: Dict[str, Any]) -> str:
    ensure_dir(public_dir)
    ensure_dir(os.path.join(public_dir, "history"))

    latest_path = os.path.join(public_dir, "latest.json")
    hist_path = os.path.join(public_dir, "history", f"{window_id}.json")

    payload = json.dumps(report, indent=2, sort_keys=True)
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(payload)
    with open(hist_path, "w", encoding="utf-8") as f:
        f.write(payload)

    return latest_path


def build_report(
    window_id: str,
    fees_in_lamports: int,
    start_balance_lamports: int | None,
    end_balance_lamports: int | None,
    current_treasury_balance_lamports: int | None,
    lifetime_total_fees_lamports: int,
    scored: List[ScoredEntry],
    payouts: List[Payout],
    notes: List[str],
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "window_id": window_id,
        "generated_at_utc": utc_now_iso(),
        "fees_in_lamports": int(fees_in_lamports),
        "fees_in_sol": float(fees_in_lamports) / 1_000_000_000,
        "winners": [asdict(x) for x in scored],
        "payouts": [asdict(p) for p in payouts],
        "notes": notes,
    }

    # Treasury balance tracking
    if start_balance_lamports is not None:
        report["start_balance_lamports"] = int(start_balance_lamports)
        report["start_balance_sol"] = float(start_balance_lamports) / 1_000_000_000

    if end_balance_lamports is not None:
        report["end_balance_lamports"] = int(end_balance_lamports)
        report["end_balance_sol"] = float(end_balance_lamports) / 1_000_000_000

    if current_treasury_balance_lamports is not None:
        report["current_treasury_balance_lamports"] = int(current_treasury_balance_lamports)
        report["current_treasury_balance_sol"] = float(current_treasury_balance_lamports) / 1_000_000_000

    report["window_delta_lamports"] = int(fees_in_lamports)
    report["window_delta_sol"] = float(fees_in_lamports) / 1_000_000_000

    report["lifetime_total_fees_lamports"] = int(lifetime_total_fees_lamports)
    report["lifetime_total_fees_sol"] = float(lifetime_total_fees_lamports) / 1_000_000_000

    return report


def export_interim_scoring_csv(
    interim_shills: List[Tweet],
    scored: Dict[str, Tuple[str, float]],
    output_path: str,
) -> str:
    """
    Export interim/preview scoring results to CSV.
    
    Args:
        interim_shills: List of tweets from interim_shills table
        scored: Dict mapping handle -> (tweet_id, score)
        output_path: Full path to output CSV file
        
    Returns:
        Path to created CSV file
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Create ranked list
    ranked: List[Tuple[str, str, float, int]] = []
    for handle, (tweet_id, score) in scored.items():
        ranked.append((handle, tweet_id, score, 0))  # rank will be set below
    ranked.sort(key=lambda x: x[2], reverse=True)

    # Assign ranks
    for i, (handle, tweet_id, score, _) in enumerate(ranked, start=1):
        ranked[i - 1] = (handle, tweet_id, score, i)

    # Create tweet lookup
    tweet_by_id: Dict[str, Tweet] = {t.tweet_id: t for t in interim_shills}

    # Write CSV
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rank",
            "handle",
            "tweet_id",
            "text",
            "created_at_utc",
            "score",
            "like_count",
            "retweet_count",
            "quote_count",
            "reply_count",
            "view_count",
            "has_media",
            "media_type",
        ])

        for handle, tweet_id, score, rank in ranked:
            tweet = tweet_by_id.get(tweet_id)
            if not tweet:
                continue

            writer.writerow([
                rank,
                handle,
                tweet_id,
                tweet.text,
                tweet.created_at_utc,
                f"{score:.6f}",
                tweet.like_count,
                tweet.retweet_count,
                tweet.quote_count,
                tweet.reply_count,
                tweet.view_count,
                "Yes" if tweet.has_media else "No",
                tweet.media_type,
            ])

    return output_path
