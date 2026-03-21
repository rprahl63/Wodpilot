#!/bin/bash
# WODpilot VPS Setup Script
# Run as root on a fresh Ubuntu 24.04 Hetzner CX21
# Usage: curl -fsSL https://raw.githubusercontent.com/OWNER/wodpilot/main/setup-vps.sh | bash

set -euo pipefail

echo "=== WODpilot VPS Setup ==="

# Update system
apt-get update && apt-get upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# Install Docker Compose plugin
apt-get install -y docker-compose-plugin

# Install UFW
apt-get install -y ufw
ufw --force enable
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
echo "UFW configured."

# Create app directory
mkdir -p /opt/wodpilot/data
cd /opt/wodpilot

# Create Docker network for Traefik
docker network create proxy 2>/dev/null || true

# Create acme.json for Traefik SSL
touch /opt/wodpilot/data/acme.json
chmod 600 /opt/wodpilot/data/acme.json

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "1. Copy your docker-compose.yml and .env to /opt/wodpilot/"
echo "2. Log in to GitHub Container Registry:"
echo "   echo \$GITHUB_TOKEN | docker login ghcr.io -u YOUR_USERNAME --password-stdin"
echo "3. Start the stack:"
echo "   cd /opt/wodpilot && docker compose pull && docker compose up -d"
echo ""
echo "4. Run the database migration in Supabase SQL editor:"
echo "   (Copy contents of db/migrations/001_initial.sql)"
