# Local Execution Guide

This guide covers running Shooter ShillBot locally with deterministic, on-demand execution. No background services or continuous uptime required.

## Manual Execution Workflow

### Initial Setup

```bash
# 1. Create virtual environment (if not already done)
python -m venv .venv

# 2. Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
# Copy .env.example to .env and edit with your settings
cp .env.example .env
# Edit .env file with your API keys, wallet addresses, etc.

# 5. Initialize database (first time only)
python -m shillbot init-db
```

### Daily Workflow

```bash
# 1. Pull new registrations (run when needed)
python -m shillbot ingest-registrations

# 2. Close window (run at window close times: 2pm/11pm CT)
# This automatically:
#   - Pulls official shills for the window
#   - Scores tweets
#   - Calculates payouts
#   - Sends SOL transfers (if DRY_RUN=false)
#   - Generates reports
python -m shillbot close-once

# 3. View reports (optional - run when needed)
python -m shillbot serve
# Open http://localhost:8000 in your browser
# Press Ctrl+C to stop the server
```

### Testing and Preview

```bash
# Preview scoring with interim pull
python -m shillbot ingest --interim --since 2026-01-10T00:00:00Z --until 2026-01-10T14:00:00Z

# Export interim scoring to CSV
python -m shillbot export-interim

# Force close a window (useful for testing)
python -m shillbot close-once --force
```

All commands are manual and on-demand. No automatic scheduling or background jobs required.

## Web Server (Optional)

The web server is **optional** and should be run manually when you want to view reports.

### Running the Server

```bash
# Start web server
python -m shillbot serve

# Server runs on http://localhost:8000
# Press Ctrl+C to stop
```

### When to Run

- After closing a window to view new reports
- To share reports with others (they can access via your IP if firewall allows)
- For testing report generation

### No Background Service Required

Unlike VPS deployment, there's no need for an always-on web server. Run it manually when you need to view reports, then stop it when done.

## Key Differences from VPS Deployment

| Aspect | Local Execution | VPS Deployment |
|--------|----------------|----------------|
| **Execution** | Manual, on-demand | Manual or automated (optional) |
| **Web Server** | Run manually when needed | Optional systemd service |
| **Scheduling** | None (all manual) | Optional (systemd timers) |
| **Uptime** | No continuous uptime needed | Optional server uptime |
| **Complexity** | Minimal - just run commands | Requires systemd setup (optional) |

## Troubleshooting

### Commands Not Found

**Issue:** `python -m shillbot` fails with "No module named shillbot"

**Solution:**
- Ensure virtual environment is activated
- Verify you're in the project root directory
- Reinstall dependencies: `pip install -r requirements.txt`

### Environment Variables Not Loading

**Issue:** Commands fail with missing configuration errors

**Solution:**
- Verify `.env` file exists in project root
- Check `.env` file has correct variable names (see `readme.md`)
- Ensure `.env` file is readable

### Database Errors

**Issue:** Database locked or schema errors

**Solution:**
- Ensure only one process is accessing the database at a time
- Reinitialize database: `python -m shillbot init-db` (backup first if needed)
- Check file permissions on `shillbot.sqlite3`

### Timezone Issues

**Issue:** Window close times don't match expected times

**Solution:**
- Verify `SHILLBOT_TIMEZONE` in `.env` matches your local timezone
- Check system timezone settings
- All commands are manual - no scheduling required

## Best Practices

1. **Run commands in sequence:** Don't run multiple instances of the same command simultaneously
2. **Check reports after close:** Always verify reports after closing a window
3. **Backup database:** Regularly backup `shillbot.sqlite3` before major operations
4. **Test on devnet first:** Use `SHILLBOT_DRY_RUN=true` and devnet RPC for testing
5. **Monitor results:** Check exports and reports after running commands
6. **Keep .env secure:** Never commit `.env` file to version control

## Next Steps

- See [readme.md](readme.md) for full command reference
- See [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md) for configuration details
- See [deploy/README.md](deploy/README.md) if you want to set up VPS deployment (optional)
