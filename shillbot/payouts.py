from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional, Tuple

from shillbot.models import Payout


LAMPORTS_PER_SOL = 1_000_000_000


def sol_to_lamports(sol: float) -> int:
    return int(sol * LAMPORTS_PER_SOL)


def lamports_to_sol(lamports: int) -> float:
    return lamports / LAMPORTS_PER_SOL


@dataclass(frozen=True)
class SolanaCLIPayer:
    keypair_path: str
    rpc_url: str
    dry_run: bool

    def transfer_sol(self, to_wallet: str, sol: float) -> Tuple[str, Optional[str]]:
        if self.dry_run:
            return ("DRY_RUN", None)

        cmd = [
            "solana",
            "transfer",
            to_wallet,
            str(sol),
            "--from",
            self.keypair_path,
            "--url",
            self.rpc_url,
            "--allow-unfunded-recipient",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"solana transfer failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

        sig = None
        for line in proc.stdout.splitlines():
            if "Signature:" in line:
                sig = line.split("Signature:", 1)[1].strip()
                break
        return ("SENT", sig)


# Hard-coded payout percentages for ranks 1-10 (IMMUTABLE)
PAYOUT_PERCENTAGES = [0.30, 0.15, 0.10, 0.10, 0.10, 0.05, 0.05, 0.05, 0.05, 0.05]
TOP_N_PAYOUTS = 10


def compute_payout_plan(
    window_id: str,
    pot_lamports: int,
    ranked_winners: List[Tuple[str, str, float]],  # (handle, wallet, score)
    min_payout_lamports: int,
) -> List[Tuple[str, int, str, str, float, float, int]]:
    """
    Compute payout plan using fixed top-10 percentages.
    Returns list of (window_id, rank, handle, wallet, score, percentage, amount_lamports).
    Does NOT write to database - caller handles persistence.
    Pure function with no side effects.
    """
    plan: List[Tuple[str, int, str, str, float, float, int]] = []
    
    if pot_lamports <= 0:
        return plan
    
    # Take only top 10
    ranked = ranked_winners[:TOP_N_PAYOUTS]
    if not ranked:
        return plan
    
    # Apply fixed percentages for each rank
    for rank_idx, (handle, wallet, score) in enumerate(ranked, start=1):
        if rank_idx > TOP_N_PAYOUTS:
            break
        
        percentage = PAYOUT_PERCENTAGES[rank_idx - 1]
        amount_lamports = int(pot_lamports * percentage)
        
        # Only include if meets minimum payout threshold
        if amount_lamports >= min_payout_lamports:
            plan.append((window_id, rank_idx, handle, wallet, score, percentage, amount_lamports))
    
    return plan


# Keep old function for backward compatibility (deprecated)
def allocate_payouts(
    pot_lamports: int,
    winners: List[Tuple[str, str, float]],
    top_n: int,
    min_payout_lamports: int,
    payout_bins: List[Tuple[int, int, float]],
) -> List[Payout]:
    """Deprecated: Use compute_payout_plan instead. Kept for backward compatibility."""
    payouts: List[Payout] = []
    if pot_lamports <= 0:
        return payouts

    ranked = winners[:top_n]
    if not ranked:
        return payouts

    # Winner gets 50%
    winner_lamports = int(pot_lamports * 0.50)
    _, wallet0, _ = ranked[0]
    if winner_lamports >= min_payout_lamports:
        payouts.append(Payout(wallet=wallet0, lamports=winner_lamports, status="PENDING", signature=None))

    # Remaining 50% by bins (must sum to 0.50)
    for start, end, share in payout_bins:
        start_idx = start - 1
        end_idx = min(end - 1, len(ranked) - 1)
        if start_idx > end_idx:
            continue

        pool = int(pot_lamports * share)
        count = (end_idx - start_idx) + 1
        if count <= 0 or pool <= 0:
            continue

        each = int(pool / count)
        for i in range(start_idx, end_idx + 1):
            _, wallet, _ = ranked[i]
            if each >= min_payout_lamports:
                payouts.append(Payout(wallet=wallet, lamports=each, status="PENDING", signature=None))

    # Merge duplicates (if any)
    merged: dict[str, int] = {}
    for p in payouts:
        merged[p.wallet] = merged.get(p.wallet, 0) + p.lamports

    out: List[Payout] = []
    for w, lam in merged.items():
        if lam >= min_payout_lamports:
            out.append(Payout(wallet=w, lamports=lam, status="PENDING", signature=None))
    return out
