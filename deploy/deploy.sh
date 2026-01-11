#!/bin/bash
# Shooter ShillBot Deployment Script
# Usage: ./deploy/deploy.sh [username]

set -e

# Get username (default to current user)
USERNAME=${1:-$USER}
PROJECT_DIR=$(cd "$(dirname "$0")/.." && pwd)
SERVICE_DIR="$HOME/.config/systemd/user"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}Shooter ShillBot Deployment Script${NC}"
echo "Username: $USERNAME"
echo "Project directory: $PROJECT_DIR"
echo "Service directory: $SERVICE_DIR"
echo ""

# Check if running as correct user
if [ "$USER" != "$USERNAME" ] && [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Must run as $USERNAME or root${NC}"
    exit 1
fi

# Create service directory
echo -e "${YELLOW}Creating service directory...${NC}"
mkdir -p "$SERVICE_DIR"

# Copy service files
echo -e "${YELLOW}Copying systemd service files...${NC}"
cp "$PROJECT_DIR/deploy/shillbot-serve.service" "$SERVICE_DIR/"
cp "$PROJECT_DIR/deploy/shillbot-ingest-hourly.service" "$SERVICE_DIR/"
cp "$PROJECT_DIR/deploy/shillbot-ingest-hourly.timer" "$SERVICE_DIR/"
cp "$PROJECT_DIR/deploy/shillbot-close-2pm.service" "$SERVICE_DIR/"
cp "$PROJECT_DIR/deploy/shillbot-close-2pm.timer" "$SERVICE_DIR/"
cp "$PROJECT_DIR/deploy/shillbot-close-11pm.service" "$SERVICE_DIR/"
cp "$PROJECT_DIR/deploy/shillbot-close-11pm.timer" "$SERVICE_DIR/"

# Replace paths in service files
echo -e "${YELLOW}Configuring service file paths...${NC}"
HOME_DIR=$(eval echo ~$USERNAME)
sed -i "s|/home/%i/shillbot|$PROJECT_DIR|g" "$SERVICE_DIR"/shillbot-*.service
sed -i "s|/home/%i/shillbot|$PROJECT_DIR|g" "$SERVICE_DIR"/shillbot-*.timer

# Reload systemd
echo -e "${YELLOW}Reloading systemd daemon...${NC}"
if [ "$EUID" -eq 0 ]; then
    systemctl daemon-reload
else
    systemctl --user daemon-reload
fi

# Enable and start services
echo -e "${YELLOW}Enabling and starting services...${NC}"
if [ "$EUID" -eq 0 ]; then
    SYSTEMCTL="systemctl"
else
    SYSTEMCTL="systemctl --user"
fi

# Enable web server
$SYSTEMCTL enable shillbot-serve.service
$SYSTEMCTL start shillbot-serve.service

# Enable timers
$SYSTEMCTL enable shillbot-ingest-hourly.timer
$SYSTEMCTL start shillbot-ingest-hourly.timer

$SYSTEMCTL enable shillbot-close-2pm.timer
$SYSTEMCTL start shillbot-close-2pm.timer

$SYSTEMCTL enable shillbot-close-11pm.timer
$SYSTEMCTL start shillbot-close-11pm.timer

# Enable lingering for user services
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}Enabling user service lingering (allows services to run at boot)...${NC}"
    sudo loginctl enable-linger "$USERNAME" 2>/dev/null || echo -e "${YELLOW}Note: Could not enable lingering. User services may not start at boot.${NC}"
fi

# Show status
echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""
echo "Service status:"
$SYSTEMCTL status shillbot-serve.service --no-pager -l || true

echo ""
echo "Timer status:"
$SYSTEMCTL list-timers --all --no-pager | grep shillbot || true

echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "1. Verify .env file is configured: $PROJECT_DIR/.env"
echo "2. Check service logs: $SYSTEMCTL logs -u shillbot-serve.service"
echo "3. Check timer logs: $SYSTEMCTL logs -u shillbot-ingest-hourly.timer"
echo "4. View all logs: journalctl $([ "$EUID" -ne 0 ] && echo '--user') -u shillbot-*"
