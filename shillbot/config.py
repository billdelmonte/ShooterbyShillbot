from __future__ import annotations

from dataclasses import dataclass
from dotenv import load_dotenv
import os
from typing import List, Optional, Tuple


def _getenv(name: str, default: Optional[str] = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise ValueError(f"Missing required env var: {name}")
    return val


def _getenv_bool(name: str, default: str = "false") -> bool:
    return _getenv(name, default).strip().lower() in {"1", "true", "yes", "y"}


def _getenv_float(name: str, default: str) -> float:
    return float(_getenv(name, default))


def _getenv_int(name: str, default: str) -> int:
    return int(_getenv(name, default))


def _parse_csv_times(s: str) -> List[str]:
    items = [x.strip() for x in s.split(",") if x.strip()]
    if not items:
        raise ValueError("SHILLBOT_CLOSE_TIMES must have at least one time (e.g. 14:00,23:00)")
    for t in items:
        if len(t) != 5 or t[2] != ":":
            raise ValueError(f"Invalid time format: {t} (expected HH:MM)")
    return items


def _parse_bins(s: str) -> List[Tuple[int, int, float]]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    out: List[Tuple[int, int, float]] = []
    for p in parts:
        range_part, share_part = p.split(":")
        a, b = range_part.split("-")
        out.append((int(a), int(b), float(share_part)))
    return out


# Solana RPC URL (mainnet)
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

# Dry run mode (False = execute real transactions)
DRY_RUN = False


def validate_rpc_url(rpc_url: str) -> None:
    """Hard fail if devnet is detected in RPC URL."""
    if "devnet" in rpc_url.lower():
        raise RuntimeError("FATAL: Devnet RPC configured. Refusing to run.")

# Insider handles excluded from payouts (still ingested, scored, exported)
INSIDER_HANDLES = {
    "shootercoinsol",
    "billdelmonte",
}


@dataclass(frozen=True)
class Settings:
    timezone: str
    handle: str
    signup_tweet_id: str
    db_path: str
    public_dir: str

    x_api_bearer_token: str

    close_times: List[str]

    pot_share: float
    marketing_share: float
    dev_share: float

    min_payout_sol: float
    top_n: int
    payout_bins: List[Tuple[int, int, float]]

    rpc_url: str
    treasury_pubkey: str
    treasury_keypair_path: str
    marketing_wallet: str
    dev_wallet: str
    sweep_ops: bool

    token_mint: str
    min_token_amount: int

    dry_run: bool
    max_payouts_per_close: int

    coin_handle: str
    coin_ticker: str
    register_hashtag: str


def load_settings() -> Settings:
    load_dotenv()

    timezone = _getenv("SHILLBOT_TIMEZONE", "America/Chicago")
    handle = _getenv("SHILLBOT_HANDLE", "ShooterShillBot").lstrip("@")
    signup_tweet_id = _getenv("SHILLBOT_SIGNUP_TWEET_ID", "").strip()
    db_path = _getenv("SHILLBOT_DB_PATH", "shillbot.sqlite3")
    public_dir = _getenv("SHILLBOT_PUBLIC_DIR", "public")

    x_api_bearer_token = _getenv("SHILLBOT_X_API_BEARER_TOKEN", "").strip()

    close_times = _parse_csv_times(_getenv("SHILLBOT_CLOSE_TIMES", "14:00,23:00"))

    pot_share = _getenv_float("SHILLBOT_POT_SHARE", "0.75")
    marketing_share = _getenv_float("SHILLBOT_MARKETING_SHARE", "0.15")
    dev_share = _getenv_float("SHILLBOT_DEV_SHARE", "0.10")

    min_payout_sol = _getenv_float("SHILLBOT_MIN_PAYOUT_SOL", "0.001")
    top_n = _getenv_int("SHILLBOT_TOP_N", "20")
    payout_bins = _parse_bins(_getenv("SHILLBOT_PAYOUT_BINS", "2-5:0.25,6-10:0.15,11-20:0.10"))

    # Use mainnet RPC URL (with validation to prevent devnet)
    rpc_url = _getenv("SHILLBOT_RPC_URL", SOLANA_RPC_URL)
    
    # Hard fail if devnet is detected
    validate_rpc_url(rpc_url)
    treasury_pubkey = _getenv("SHILLBOT_TREASURY_PUBKEY", "").strip()
    treasury_keypair_path = "reward_wallet.json"
    print(f"using treasury keypair: {treasury_keypair_path}")
    marketing_wallet = _getenv("SHILLBOT_MARKETING_WALLET", "").strip()
    dev_wallet = _getenv("SHILLBOT_DEV_WALLET", "").strip()
    sweep_ops = _getenv_bool("SHILLBOT_SWEEP_OPS", "false")

    token_mint = _getenv("SHILLBOT_TOKEN_MINT", "").strip()
    min_token_amount = _getenv_int("SHILLBOT_MIN_TOKEN_AMOUNT", "0")

    # Default to False (execute real transactions), but allow env var override
    dry_run = _getenv_bool("SHILLBOT_DRY_RUN", "false")
    max_payouts_per_close = _getenv_int("SHILLBOT_MAX_PAYOUTS_PER_CLOSE", "25")

    coin_handle = _getenv("SHILLBOT_COIN_HANDLE", "shootercoinsol").lstrip("@")
    coin_ticker = _getenv("SHILLBOT_COIN_TICKER", "SHOOTER").lstrip("$")
    register_hashtag = _getenv("SHILLBOT_REGISTER_HASHTAG", "shillbotregister").lstrip("#")

    if abs((pot_share + marketing_share + dev_share) - 1.0) > 1e-9:
        raise ValueError("POT + MARKETING + DEV shares must sum to 1.0")

    if abs(sum(x[2] for x in payout_bins) - 0.50) > 1e-6:
        raise ValueError("SHILLBOT_PAYOUT_BINS shares must sum to 0.50 (winner already gets 0.50).")

    return Settings(
        timezone=timezone,
        handle=handle,
        signup_tweet_id=signup_tweet_id,
        db_path=db_path,
        public_dir=public_dir,
        x_api_bearer_token=x_api_bearer_token,
        close_times=close_times,
        pot_share=pot_share,
        marketing_share=marketing_share,
        dev_share=dev_share,
        min_payout_sol=min_payout_sol,
        top_n=top_n,
        payout_bins=payout_bins,
        rpc_url=rpc_url,
        treasury_pubkey=treasury_pubkey,
        treasury_keypair_path=treasury_keypair_path,
        marketing_wallet=marketing_wallet,
        dev_wallet=dev_wallet,
        sweep_ops=sweep_ops,
        token_mint=token_mint,
        min_token_amount=min_token_amount,
        dry_run=dry_run,
        max_payouts_per_close=max_payouts_per_close,
        coin_handle=coin_handle,
        coin_ticker=coin_ticker,
        register_hashtag=register_hashtag,
    )
