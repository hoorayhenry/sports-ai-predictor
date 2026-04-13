#!/bin/bash
# =============================================================================
# Sports AI Predictor — AWS EC2 Provisioner
# Run this LOCALLY to create the EC2 instance and deploy the app.
# Reads credentials from environment variables — never hardcoded.
# =============================================================================
set -euo pipefail

# ── Required env vars ─────────────────────────────────────────────────
: "${AWS_ACCESS_KEY_ID:?Set AWS_ACCESS_KEY_ID}"
: "${AWS_SECRET_ACCESS_KEY:?Set AWS_SECRET_ACCESS_KEY}"
: "${AWS_REGION:=us-east-1}"
: "${KEY_PAIR_NAME:?Set KEY_PAIR_NAME (your EC2 key pair name)}"
: "${APP_REPO:?Set APP_REPO (git clone URL or leave blank to rsync)}"

# Optional
INSTANCE_TYPE="${INSTANCE_TYPE:-t3.medium}"
DOMAIN="${DOMAIN:-}"
AMI_ID="${AMI_ID:-ami-0c7217cdde317cfec}"  # Ubuntu 22.04 LTS us-east-1

echo "=== Provisioning EC2 instance ==="
echo "  Region:        $AWS_REGION"
echo "  Instance type: $INSTANCE_TYPE"
echo "  Key pair:      $KEY_PAIR_NAME"

# ── Install AWS CLI if needed ─────────────────────────────────────────
if ! command -v aws &>/dev/null; then
  echo "Installing AWS CLI..."
  curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
  unzip -q awscliv2.zip && ./aws/install && rm -rf aws awscliv2.zip
fi

export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_DEFAULT_REGION="$AWS_REGION"

# ── Security group ────────────────────────────────────────────────────
SG_NAME="sportsai-sg"
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=$SG_NAME" \
  --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo "None")

if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
  echo "Creating security group..."
  SG_ID=$(aws ec2 create-security-group \
    --group-name "$SG_NAME" \
    --description "Sports AI Predictor" \
    --query "GroupId" --output text)

  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
    --ip-permissions \
    '[{"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]},
      {"IpProtocol":"tcp","FromPort":80,"ToPort":80,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]},
      {"IpProtocol":"tcp","FromPort":443,"ToPort":443,"IpRanges":[{"CidrIp":"0.0.0.0/0"}]}]'
  echo "  Security group: $SG_ID"
fi

# ── Launch instance ───────────────────────────────────────────────────
echo "Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_PAIR_NAME" \
  --security-group-ids "$SG_ID" \
  --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=sports-ai-predictor}]' \
  --query "Instances[0].InstanceId" --output text)

echo "  Instance ID: $INSTANCE_ID"
echo "  Waiting for instance to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text)

echo "  Public IP: $PUBLIC_IP"

# ── Allocate + associate Elastic IP ──────────────────────────────────
echo "Allocating Elastic IP..."
ALLOC_ID=$(aws ec2 allocate-address --domain vpc --query "AllocationId" --output text)
aws ec2 associate-address --instance-id "$INSTANCE_ID" --allocation-id "$ALLOC_ID" > /dev/null
EIP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC_ID" \
  --query "Addresses[0].PublicIp" --output text)
echo "  Elastic IP: $EIP"

# ── Wait for SSH ──────────────────────────────────────────────────────
echo "Waiting for SSH to be available..."
for i in $(seq 1 30); do
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "ubuntu@$EIP" "echo ok" &>/dev/null && break || sleep 10
done

# ── Copy app code ─────────────────────────────────────────────────────
echo "Copying application code..."
ssh -o StrictHostKeyChecking=no "ubuntu@$EIP" "sudo mkdir -p /opt/sports-ai && sudo chown ubuntu:ubuntu /opt/sports-ai"

if [ -n "$APP_REPO" ]; then
  ssh "ubuntu@$EIP" "git clone $APP_REPO /opt/sports-ai"
else
  # rsync local directory
  rsync -az --exclude='backend/venv' --exclude='frontend/node_modules' \
    --exclude='backend/__pycache__' --exclude='*.pyc' \
    --exclude='backend/sports_ai.db' \
    "$(dirname "$(realpath "$0")")/../" "ubuntu@$EIP:/opt/sports-ai/"
fi

# ── Copy .env ─────────────────────────────────────────────────────────
echo "Copying .env..."
scp "$(dirname "$(realpath "$0")")/../backend/.env" "ubuntu@$EIP:/opt/sports-ai/backend/.env"

# ── Run setup script on server ────────────────────────────────────────
echo "Running server setup (this takes ~10 minutes for data download + training)..."
ssh "ubuntu@$EIP" "DOMAIN='$DOMAIN' sudo -E bash /opt/sports-ai/deploy/setup-ec2.sh"

echo ""
echo "============================================"
echo "  Deployment complete!"
echo "  URL:  http://$EIP"
if [ -n "$DOMAIN" ]; then
  echo "  Site: https://$DOMAIN (after DNS points to $EIP)"
fi
echo "  SSH:  ssh ubuntu@$EIP"
echo "============================================"

# Save instance info
cat > "$(dirname "$(realpath "$0")")/instance.txt" << INFO
INSTANCE_ID=$INSTANCE_ID
PUBLIC_IP=$EIP
ALLOC_ID=$ALLOC_ID
REGION=$AWS_REGION
INFO
echo "Instance details saved to deploy/instance.txt"
