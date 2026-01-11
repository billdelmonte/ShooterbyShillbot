# Shooter / ShillBot Engine (v0)

Twice-daily contest loop that rewards unique, high-impact shills with automated SOL payouts. Transparent scoring + settlement pipeline.

## Quick Start (Windows)

Use ExecutionPolicy bypass (no machine policy changes):
```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -Close -Serve
```

## Current Pipeline

1. **Ingest** registrations + shills (v2: Official X API integration)
   - Registrations: `#Shillbot-register [WALLET]` hashtag format
   - Shills: Search for `@shootercoinsol`, `$SHOOTER`, token mint
   - Rate limiting: 1 shill per minute per user
2. **Score** and close the latest window (2pm/11pm CT)
   - Automatically pulls official shills at window close
   - Applies rate limiting before scoring
3. **Write** public report in `/public` (`latest.json` + `history/<window_id>.json`)
4. **Payout** winners from treasury via Solana CLI (real transfers or DRY_RUN mode)

## Features (v2)

- ✅ **Real X/Twitter ingest**: Official X API (Twitter API v2)
  - Hashtag-based registration parsing (`#Shillbot-register`)
  - Search-based shill collection (mentions, ticker, mint)
  - Rate limiting: 1 shill per minute per user
  - Handles X API rate limits (180-450 requests per 15 min)
- ✅ **Interim vs Official pulls**:
  - Official pulls: Automatic at window close, stored in `shills` table
  - Interim pulls: Manual preview scoring, stored in `interim_shills` table, export to CSV
- ✅ **Treasury balance tracking**: Real Solana RPC snapshots for fees delta
- ✅ Scoring: engagement-weighted + originality + media bonus + volume dampening
- ✅ Window management: close at 2:00 PM and 11:00 PM Central
- ✅ Economics: 75% pot, 15% marketing, 10% dev; #1 gets 50% of pot
- ✅ **Marketing/Dev payouts**: Automatically sends 15% to marketing wallet and 10% to dev wallet
- ✅ Public reports: JSON output with winners, payouts, fees, balance metrics
- ✅ **Real payouts**: Actual SOL transfers via Solana CLI (configurable: DRY_RUN or real)
- ✅ **Token holding verification**: Filters out winners who don't hold minimum token amount at window close
- ✅ **Blacklist/Exclusion**: Filter out blacklisted handles and excluded tweets before scoring

## Commands

```bash
# Initialize database
python -m shillbot init-db

# Pull registrations (hourly job)
python -m shillbot ingest-registrations

# Official pull at window close (automatic)
python -m shillbot ingest --official --window-id 20260110-1400

# Interim/preview pull (manual)
python -m shillbot ingest --interim --since 2026-01-10T00:00:00Z --until 2026-01-10T14:00:00Z

# Export interim scoring to CSV
python -m shillbot export-interim

# Close window (automatically pulls official shills)
python -m shillbot close-once

# Serve public reports
python -m shillbot serve
```

## Configuration

**Environment Variables:**
```bash
# X/Twitter API
SHILLBOT_COIN_HANDLE=shootercoinsol          # @shootercoinsol
SHILLBOT_COIN_TICKER=SHOOTER                 # $SHOOTER
SHILLBOT_REGISTER_HASHTAG=Shillbot-register  # #Shillbot-register
SHILLBOT_TOKEN_MINT=...                      # Optional: coin mint address
SHILLBOT_X_API_BEARER_TOKEN=...              # Required: X API Bearer token (OAuth 2.0)

# Solana/Payouts
SHILLBOT_RPC_URL=https://api.mainnet-beta.solana.com  # Solana RPC URL (default: devnet)
SHILLBOT_TREASURY_PUBKEY=...                 # Treasury wallet pubkey (for balance tracking)
SHILLBOT_TREASURY_KEYPAIR_PATH=...          # Path to treasury keypair file (for real payouts)
SHILLBOT_DRY_RUN=true                       # true = DRY_RUN mode, false = real transfers
```

## VPS Deployment

For production deployment on a Linux VPS, see [deploy/README.md](deploy/README.md) for detailed instructions.

Quick setup:
```bash
# Run deployment script (automates setup)
./deploy/deploy.sh

# Or manually follow steps in deploy/README.md
```

The deployment includes:
- Systemd service for web server (serves `public/` directory)
- Systemd timer for hourly registration ingest
- Systemd timers for window close jobs (2:00 PM and 11:00 PM CT)

## Next Milestones

1. ✅ **Real ingest** - Complete (v2 spec)
2. ✅ **Real treasury balance** - Complete
3. ✅ **Real payouts** - Complete (configurable: DRY_RUN or real transfers)
4. ✅ **VPS deploy** - Complete (systemd services and timers)

See `spec.md` for full specification.