# VPS Deployment Guide

This guide walks you through deploying Shooter ShillBot on a Linux VPS using systemd services and timers.

## Prerequisites

- Linux VPS with systemd (Ubuntu 20.04+, Debian 10+, or similar)
- Python 3.8+ installed
- Solana CLI installed and in PATH
- Git (for cloning the repository)

## Initial Setup

### 1. Clone and Setup Project

```bash
# Clone repository
git clone <repository-url>
cd shillbot

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Initialize database
python -m shillbot init-db
```

### 2. Configure Environment Variables

Create a `.env` file in the project root:

```bash
cp .env.example .env
# Edit .env with your configuration
nano .env
```

Required environment variables:
- `SHILLBOT_X_API_BEARER_TOKEN` - X API Bearer token
- `SHILLBOT_TREASURY_PUBKEY` - Treasury wallet pubkey
- `SHILLBOT_TREASURY_KEYPAIR_PATH` - Path to treasury keypair file
- `SHILLBOT_RPC_URL` - Solana RPC URL
- `SHILLBOT_DRY_RUN` - Set to `false` for real payouts

See main `README.md` for full list of environment variables.

### 3. Install Systemd Services and Timers

Copy systemd files to your user systemd directory:

```bash
# Replace $USER with your username, or use ~ for home directory
USER_DIR=~/.config/systemd/user  # User services
# OR
USER_DIR=/etc/systemd/system     # System services (requires root)

mkdir -p $USER_DIR

# Copy service files
cp deploy/shillbot-serve.service $USER_DIR/
cp deploy/shillbot-ingest-hourly.service $USER_DIR/
cp deploy/shillbot-ingest-hourly.timer $USER_DIR/
cp deploy/shillbot-close-2pm.service $USER_DIR/
cp deploy/shillbot-close-2pm.timer $USER_DIR/
cp deploy/shillbot-close-11pm.service $USER_DIR/
cp deploy/shillbot-close-11pm.timer $USER_DIR/
```

### 4. Configure Service Paths

Edit the service files to match your setup:

```bash
# Replace %i with your username, or use full paths
# Edit these files:
nano ~/.config/systemd/user/shillbot-serve.service
nano ~/.config/systemd/user/shillbot-ingest-hourly.service
# ... etc

# Update paths:
# - WorkingDirectory: /home/YOUR_USERNAME/shillbot
# - EnvironmentFile: /home/YOUR_USERNAME/shillbot/.env
# - ExecStart: /home/YOUR_USERNAME/shillbot/.venv/bin/python
```

**Quick path replacement:**
```bash
# Replace YOUR_USERNAME with your actual username
sed -i 's|/home/%i/shillbot|/home/YOUR_USERNAME/shillbot|g' ~/.config/systemd/user/shillbot-*.service
sed -i 's|/home/%i/shillbot|/home/YOUR_USERNAME/shillbot|g' ~/.config/systemd/user/shillbot-*.timer
```

**Or use systemd user services with %i:**
- Services use `%i` which systemd replaces with the username
- For user services, this works automatically
- For system services, replace `%i` with your username

### 5. Reload Systemd and Enable Services

```bash
# Reload systemd configuration
systemctl --user daemon-reload
# OR if using system services:
# sudo systemctl daemon-reload

# Enable and start web server
systemctl --user enable shillbot-serve.service
systemctl --user start shillbot-serve.service

# Enable and start timers
systemctl --user enable shillbot-ingest-hourly.timer
systemctl --user start shillbot-ingest-hourly.timer

systemctl --user enable shillbot-close-2pm.timer
systemctl --user start shillbot-close-2pm.timer

systemctl --user enable shillbot-close-11pm.timer
systemctl --user start shillbot-close-11pm.timer
```

### 6. Enable User Services to Start on Boot (if using user services)

```bash
# Enable lingering for your user (allows user services to run at boot)
sudo loginctl enable-linger $USER
```

## Service Management

### Check Status

```bash
# Check service status
systemctl --user status shillbot-serve.service
systemctl --user status shillbot-ingest-hourly.service
systemctl --user status shillbot-close-2pm.service

# Check timer status
systemctl --user list-timers --all
systemctl --user status shillbot-ingest-hourly.timer
systemctl --user status shillbot-close-2pm.timer
systemctl --user status shillbot-close-11pm.timer
```

### View Logs

```bash
# View logs for a service
journalctl --user -u shillbot-serve.service -f
journalctl --user -u shillbot-ingest-hourly.service -f
journalctl --user -u shillbot-close-2pm.service -f

# View recent logs
journalctl --user -u shillbot-serve.service -n 100

# View logs since today
journalctl --user -u shillbot-serve.service --since today
```

### Restart Services

```bash
# Restart web server
systemctl --user restart shillbot-serve.service

# Manually trigger a service (useful for testing)
systemctl --user start shillbot-ingest-hourly.service
systemctl --user start shillbot-close-2pm.service
```

### Stop/Disable Services

```bash
# Stop web server
systemctl --user stop shillbot-serve.service
systemctl --user disable shillbot-serve.service

# Stop timers
systemctl --user stop shillbot-ingest-hourly.timer
systemctl --user disable shillbot-ingest-hourly.timer
```

## Scheduled Jobs

### Hourly Registration Ingest
- **Timer**: `shillbot-ingest-hourly.timer`
- **Runs**: Every hour (with 5-minute randomized delay)
- **Command**: `python -m shillbot ingest-registrations`

### Window Close at 2:00 PM CT
- **Timer**: `shillbot-close-2pm.timer`
- **Runs**: Daily at 2:00 PM Central Time
- **Command**: `python -m shillbot close-once`

### Window Close at 11:00 PM CT
- **Timer**: `shillbot-close-11pm.timer`
- **Runs**: Daily at 11:00 PM Central Time
- **Command**: `python -m shillbot close-once`

## Web Server

The web server serves the `public/` directory on port 8000 by default.

### Access
- Local: `http://localhost:8000`
- Remote: `http://YOUR_VPS_IP:8000`

### Reverse Proxy (Optional)

For production, consider using nginx or caddy as a reverse proxy:

```nginx
# nginx example
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Troubleshooting

### Service Won't Start

1. Check service status: `systemctl --user status shillbot-serve.service`
2. Check logs: `journalctl --user -u shillbot-serve.service -n 50`
3. Verify paths in service file match your setup
4. Verify `.env` file exists and has correct permissions
5. Test command manually: `.venv/bin/python -m shillbot serve`

### Timer Not Triggering

1. Check timer status: `systemctl --user list-timers --all`
2. Verify timer is enabled: `systemctl --user is-enabled shillbot-ingest-hourly.timer`
3. Check timezone: `timedatectl`
4. Manually trigger service to test: `systemctl --user start shillbot-ingest-hourly.service`

### Permission Errors

1. Verify file permissions on keypair file: `chmod 600 /path/to/keypair.json`
2. Verify user has access to project directory
3. Check `.env` file permissions: `chmod 600 .env`

### Python/Solana CLI Not Found

1. Verify virtual environment: `.venv/bin/python --version`
2. Verify Solana CLI in PATH: `which solana`
3. Add full paths in service files if needed

### Database Locked

SQLite uses WAL mode. If you see lock errors:
1. Check for other processes using the database
2. Restart services to release locks
3. Verify database file permissions

## Security Notes

- Keep `.env` file secure (chmod 600)
- Keep treasury keypair file secure (chmod 600)
- Use firewall to restrict web server access if needed
- Consider using system services (requires root) for better isolation
- Regularly update dependencies: `pip install --upgrade -r requirements.txt`

## Updates

To update the code:

```bash
# Pull latest code
git pull

# Update dependencies (if requirements.txt changed)
source .venv/bin/activate
pip install --upgrade -r requirements.txt

# Restart services
systemctl --user restart shillbot-serve.service
# Timers will continue running - no restart needed
```
