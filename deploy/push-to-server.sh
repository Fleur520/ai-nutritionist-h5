#!/usr/bin/env bash
# Run from a Linux/macOS computer with SSH access:
# bash deploy/push-to-server.sh <ssh_username> [172.16.10.3]
set -Eeuo pipefail
SSH_USER="${1:?需要用户名: bash deploy/push-to-server.sh <ssh_username> [172.16.10.3]}"
SSH_HOST="${2:-172.16.10.3}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${SSH_USER}@${SSH_HOST}"
TMP="/tmp/ai-nutritionist-h5-staging"
echo "上传项目到 ${REMOTE}，只传源码，不传 .env / 数据..."
ssh "$REMOTE" "mkdir -p '$TMP'"
(cd "$SRC" && tar -czf - --exclude='./.env' --exclude='./data' --exclude='./node_modules' \
   --exclude='./frontend/dist' --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' .) \
  | ssh "$REMOTE" "cat > '$TMP/source.tgz'"
ssh -tt "$REMOTE" "tar -xzf '$TMP/source.tgz' -C '$TMP' && sudo bash '$TMP/deploy/install.sh'"
echo '首次安装会初始化 /data_1/ai-nutritionist-h5/.env。填好真实 API 配置后，在服务器执行：'
echo 'sudo bash /data_1/ai-nutritionist-h5/deploy/install.sh'
