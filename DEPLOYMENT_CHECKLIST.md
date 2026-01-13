# Deployment Checklist

## Local Execution (Primary)

This project is designed for **local execution** by default. See [LOCAL_EXECUTION.md](LOCAL_EXECUTION.md) for the complete local execution guide.

### Quick Start

1. **Setup:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   cp .env.example .env
   # Edit .env with your configuration
   python -m shillbot init-db
   ```

2. **Daily Workflow:**
   ```bash
   # Pull registrations (run when needed)
   python -m shillbot ingest-registrations
   
   # Close window (run at window close times: 2pm/11pm CT)
   python -m shillbot close-once
   
   # View reports (optional, run when needed)
   python -m shillbot serve
   ```

All commands are manual and on-demand. No automatic scheduling required.

See [LOCAL_EXECUTION.md](LOCAL_EXECUTION.md) for detailed local execution instructions.

---

## Optional: VPS Deployment

VPS deployment is **optional** and only needed if you want continuous, automated execution on a remote server. For local execution, see the section above.

---

## Environment Variables (.env file)

### Required for Production

```bash
# X/Twitter API (REQUIRED)
SHILLBOT_X_API_BEARER_TOKEN=your_bearer_token_here

# Solana Configuration (REQUIRED for real payouts)
SHILLBOT_RPC_URL=https://api.mainnet-beta.solana.com
SHILLBOT_TREASURY_PUBKEY=your_treasury_wallet_pubkey
SHILLBOT_TREASURY_KEYPAIR_PATH=/path/to/treasury/keypair.json
SHILLBOT_DRY_RUN=false  # Set to false for real payouts

# Marketing and Dev Wallets (REQUIRED if using marketing/dev payouts)
SHILLBOT_MARKETING_WALLET=your_marketing_wallet_address
SHILLBOT_DEV_WALLET=your_dev_wallet_address
```

### Optional Configuration

```bash
# Token Verification (OPTIONAL - only if you want to verify token holding)
SHILLBOT_TOKEN_MINT=your_token_mint_address
SHILLBOT_MIN_TOKEN_AMOUNT=1000000  # Minimum token amount (in token's native units)

# Coin Information (OPTIONAL - defaults provided)
SHILLBOT_COIN_HANDLE=shootercoinsol
SHILLBOT_COIN_TICKER=SHOOTER
SHILLBOT_REGISTER_HASHTAG=Shillbot-register

# Timezone and Basic Settings (OPTIONAL - defaults provided)
SHILLBOT_TIMEZONE=America/Chicago
SHILLBOT_HANDLE=ShooterShillBot
SHILLBOT_DB_PATH=shillbot.sqlite3
SHILLBOT_PUBLIC_DIR=public
SHILLBOT_CLOSE_TIMES=14:00,23:00

# Economics (OPTIONAL - defaults: 75% pot, 15% marketing, 10% dev)
SHILLBOT_POT_SHARE=0.75
SHILLBOT_MARKETING_SHARE=0.15
SHILLBOT_DEV_SHARE=0.10
SHILLBOT_MIN_PAYOUT_SOL=0.001
SHILLBOT_TOP_N=20
SHILLBOT_PAYOUT_BINS=2-5:0.25,6-10:0.15,11-20:0.10
```

## Wallet Addresses Needed

### Required Wallets

1. **Treasury Wallet** (`SHILLBOT_TREASURY_PUBKEY` and `SHILLBOT_TREASURY_KEYPAIR_PATH`)
   - This is the wallet that holds the SOL for payouts
   - The keypair file is used to sign transactions
   - Must have sufficient SOL balance for payouts
   - Get pubkey with: `solana-keygen pubkey <keypair_path>`

2. **Marketing Wallet** (`SHILLBOT_MARKETING_WALLET`)
   - Receives 15% of fees each window
   - Any valid Solana wallet address

3. **Dev Wallet** (`SHILLBOT_DEV_WALLET`)
   - Receives 10% of fees each window
   - Any valid Solana wallet address

### Optional Wallets

- **Token Mint Address** (`SHILLBOT_TOKEN_MINT`)
  - Only needed if you want to verify token holding
  - The SPL token mint address for your token

## Pre-Deployment Testing

### 1. Test on Devnet First

**Create test keypair and wallets:**
```bash
# Create test treasury keypair
solana-keygen new --outfile test-treasury.json

# Get pubkey
solana-keygen pubkey test-treasury.json

# Fund treasury on devnet
solana airdrop 10 $(solana-keygen pubkey test-treasury.json) --url devnet

# Create test marketing/dev wallets (or use existing addresses)
# You can use any valid Solana address
```

**Configure .env for devnet testing:**
```bash
SHILLBOT_RPC_URL=https://api.devnet.solana.com
SHILLBOT_TREASURY_PUBKEY=<pubkey_from_keypair>
SHILLBOT_TREASURY_KEYPAIR_PATH=test-treasury.json
SHILLBOT_MARKETING_WALLET=<test_marketing_wallet>
SHILLBOT_DEV_WALLET=<test_dev_wallet>
SHILLBOT_DRY_RUN=false  # Test with real devnet transfers
```

### 2. Run Test Scripts

```bash
# Test payout system
python test_payouts.py

# Test ingest system
python test_ingest.py

# Test X API
python test_x_api.py
```

### 3. Manual Testing

```bash
# Initialize database
python -m shillbot init-db

# Test registration ingest
python -m shillbot ingest-registrations

# Seed test data (optional)
python seed_test_data.py

# Test window close with real payouts (devnet)
python -m shillbot close-once --force

# Check reports
cat public/latest.json
```

### 4. Verify on Devnet Explorer

- Check transaction signatures in reports
- Verify transactions on: https://explorer.solana.com/?cluster=devnet
- Verify marketing/dev wallet received payouts
- Verify winner wallets received payouts

## Optional: VPS Production Deployment

**Note:** This section is for optional VPS deployment. For local execution, see the "Local Execution" section above.

### 1. Final Checklist

- [ ] X API Bearer Token configured
- [ ] Treasury wallet keypair created and secured
- [ ] Treasury wallet funded with sufficient SOL
- [ ] Marketing wallet address configured
- [ ] Dev wallet address configured
- [ ] RPC URL set to mainnet (`https://api.mainnet-beta.solana.com`)
- [ ] `SHILLBOT_DRY_RUN=false` for real payouts
- [ ] Token verification configured (if needed)
- [ ] Database initialized
- [ ] All tests passed on devnet

### 2. Security Checklist

- [ ] Treasury keypair file permissions: `chmod 600 treasury-keypair.json`
- [ ] .env file permissions: `chmod 600 .env`
- [ ] Keypair file backed up securely
- [ ] .env file not committed to git (check .gitignore)
- [ ] VPS firewall configured (if applicable)
- [ ] Keypair file stored securely on VPS

### 3. Deployment Steps

**On VPS:**

```bash
# 1. Clone repository
git clone <repository-url>
cd shillbot

# 2. Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# 4. Create .env file
nano .env  # Add all required variables

# 5. Secure .env file
chmod 600 .env

# 6. Copy treasury keypair to VPS (secure transfer)
# scp treasury-keypair.json user@vps:/path/to/shillbot/

# 7. Secure keypair file
chmod 600 treasury-keypair.json

# 8. Initialize database
python -m shillbot init-db

# 9. Test imports
python -c "from shillbot.config import load_settings; s = load_settings(); print('Config OK')"

# 10. Deploy systemd services (see deploy/README.md)
./deploy/deploy.sh

# OR manually:
cp deploy/*.service ~/.config/systemd/user/
cp deploy/*.timer ~/.config/systemd/user/
# Edit paths in service files
systemctl --user daemon-reload
systemctl --user enable shillbot-serve.service
systemctl --user enable shillbot-ingest-hourly.timer
systemctl --user enable shillbot-close-2pm.timer
systemctl --user enable shillbot-close-11pm.timer
systemctl --user start shillbot-serve.service
systemctl --user start shillbot-ingest-hourly.timer
systemctl --user start shillbot-close-2pm.timer
systemctl --user start shillbot-close-11pm.timer

# 11. Check status
systemctl --user status shillbot-serve.service
systemctl --user list-timers
```

## Testing Checklist

### Before Production

- [ ] All tests pass on devnet
- [ ] Window close works correctly
- [ ] Marketing/dev payouts sent successfully
- [ ] Winner payouts sent successfully
- [ ] Token verification works (if enabled)
- [ ] Blacklist/exclusion works (if used)
- [ ] Reports generated correctly
- [ ] Transactions visible on explorer
- [ ] Database schema correct
- [ ] All commands tested manually

### After VPS Production Deployment (Optional)

- [ ] Web server accessible (port 8000) if using systemd service
- [ ] Systemd timers enabled (optional - all commands can be run manually)
- [ ] Logs showing no errors
- [ ] First window close successful
- [ ] Payouts sent successfully
- [ ] Reports accessible via web server

**Note:** For local execution, these checks are not applicable. See [LOCAL_EXECUTION.md](LOCAL_EXECUTION.md) for local execution verification steps.

## Troubleshooting

### Common Issues

1. **Payouts not sending:**
   - Check `SHILLBOT_DRY_RUN=false`
   - Check treasury keypair path is correct
   - Check treasury wallet has sufficient balance
   - Check logs: `journalctl --user -u shillbot-close-2pm.service`

2. **Token verification failing:**
   - Verify token mint address is correct
   - Check RPC endpoint supports `getTokenAccountsByOwner`
   - Check minimum token amount is in token's native units (not lamports)

3. **Marketing/Dev payouts not sending:**
   - Check wallet addresses are configured
   - Check wallet addresses are valid Solana addresses
   - Check logs for error messages

4. **Services not starting (VPS only):**
   - Check paths in systemd service files
   - Check .env file exists and is readable
   - Check Python virtual environment is correct
   - Check logs: `journalctl --user -u shillbot-serve.service`

5. **Local execution issues:**
   - See [LOCAL_EXECUTION.md](LOCAL_EXECUTION.md) troubleshooting section
   - Verify virtual environment is activated
   - Check .env file configuration
   - Ensure database is initialized: `python -m shillbot init-db`

## Notes

- All wallet addresses must be valid Solana addresses (Base58 encoded, 32-44 characters)
- Treasury keypair file must be readable by the user running the services
- Marketing and dev wallets can be the same address (but probably shouldn't be)
- Token mint address must be a valid SPL token mint
- Minimum token amount is in token's native units (check token decimals)
- Use mainnet RPC URL for production: `https://api.mainnet-beta.solana.com`
- Consider using a dedicated RPC provider for better rate limits
