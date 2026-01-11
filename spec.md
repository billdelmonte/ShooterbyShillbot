# Shooter (by Shillbot Engine) - One-Pager Spec

v0 planning snapshot - Jan 2026 - Owner hub: Hodlcap.io

## What it is

Shooter is a memecoin + twice-daily contest loop that rewards unique, high-impact shills with automated SOL payouts. The Shillbot Engine is a deterministic scoring + settlement pipeline built to be transparent, auditable, and hard to game.

## Core rules

**Windows:** close at 2:00 PM and 11:00 PM Central (scored + settled at close).

**Signup:** user registers a wallet by tweeting `#Shillbot-register [WALLET]` (hashtag format).

**Eligibility:** must shill during the window, still hold token at close, not blacklisted/excluded.

**Anti-gaming:** materially different shills required; spam/spoof can be manually excluded; high-volume gets extra scrutiny.

**Winners:** top 20 per window; min payout 0.001 SOL; payouts are airdropped (no claiming).

## Economics

Creator fees split per window: 75% pot, 15% marketing wallet, 10% dev wallet.

Pot distribution: Rank #1 gets 50% of the pot; remaining pot flows down ranks 2-20 on a tunable curve.

## Scoring (transparent + tunable)

**Engagement:** likes/reposts/quotes/replies/views (weighted).

**Originality:** near-duplicates penalized heavily; unique content wins.

**Media bonus:** image/gif/video boosts.

**Fairness controls:** volume dampening; anti-streak cap for repeat #1 winners (configurable).

## Public outputs

Each window writes a public report: `public/latest.json` + `public/history/<window_id>.json`.

Dashboard metrics: current winners, pot size, total rewards to date, payout records (planned vs executed).

## Tech (v0 → v1)

**Runtime:** Python on a small VPS (cron/systemd). State: SQLite.

**Ingest:** Official X API (Twitter API v2) for X data:
  - Registrations: Search `#Shillbot-register` hashtag (hourly)
  - Shills: Search `@shootercoinsol`, `$SHOOTER`, token mint (2x/day at window close)
  - Rate limiting: 1 shill per minute per user
  - API rate limits: 180-450 requests per 15 min (tier dependent)
  - Interim vs Official: Preview pulls (interim_shills) vs final scoring (shills)

**On-chain:** Solana RPC to read treasury balance delta and send SOL transfers (devnet first, then mainnet).

**Web:** Hodlcap.io as hub; each project has /about (build/record) + /live (output dashboard).
