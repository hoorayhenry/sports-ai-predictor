#!/bin/bash
# =============================================================================
# Sports AI Predictor — EC2 One-Time Bootstrap
# Run on a fresh Ubuntu 22.04 instance:
#   ssh user@host "bash -s" < deploy/setup-ec2.sh
# =============================================================================
set -euo pipefail

echo "=== Sports AI Predictor — EC2 Bootstrap ==="

# ── System deps ───────────────────────────────────────────────────────
apt-get update -y && apt-get upgrade -y
apt-get install -y git curl unzip

# ── Docker ────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  curl -fsSL https://get.docker.com | sh
  usermod -aG docker "$SUDO_USER"
fi

# ── Docker Compose plugin ─────────────────────────────────────────────
if ! docker compose version &>/dev/null 2>&1; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

# ── AWS CLI (needed for ECR login) ────────────────────────────────────
if ! command -v aws &>/dev/null; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscli.zip
  unzip -q /tmp/awscli.zip -d /tmp/aws-install
  /tmp/aws-install/aws/install
  rm -rf /tmp/awscli.zip /tmp/aws-install
fi

# ── App directory ─────────────────────────────────────────────────────
mkdir -p /opt/sports-ai
chown "${SUDO_USER:-ubuntu}:${SUDO_USER:-ubuntu}" /opt/sports-ai

echo ""
echo "=== Bootstrap complete ==="
echo "Next: push to main → GitHub Actions builds ECR images and deploys here."
echo ""
echo "To manually deploy:"
echo "  cd /opt/sports-ai"
echo "  docker compose -f docker-compose.prod.yml up -d --scale backend=2"
