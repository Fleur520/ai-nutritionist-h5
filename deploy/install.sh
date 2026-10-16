#!/usr/bin/env bash
# Execute on 172.16.10.3: sudo bash deploy/install.sh
set -Eeuo pipefail
TARGET="/data_1/ai-nutritionist-h5"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $(id -u) != 0 ]]; then echo '请使用 sudo bash deploy/install.sh' >&2; exit 1; fi
if ! command -v docker >/dev/null; then echo 'Docker 未安装，请先安装 Docker Engine。' >&2; exit 1; fi
if ! docker compose version >/dev/null 2>&1; then echo '需要 Docker Compose v2（docker compose）。' >&2; exit 1; fi
if ! ip -4 addr show | grep -q '172\.16\.10\.3/'; then
  echo '警告：本机网卡似乎没有 172.16.10.3；请检查 APP_BIND_IP，否则容器端口可能无法绑定。' >&2
fi
mkdir -p "$TARGET" "$TARGET/data/media"
if [[ "$SRC" != "$TARGET" ]]; then
    (cd "$SRC" && tar -cf - --exclude='./.env' --exclude='./data' --exclude='./.git' --exclude='./node_modules' --exclude='./frontend/dist' --exclude='__pycache__' --exclude='.pytest_cache' .) | (cd "$TARGET" && tar -xf -)
fi
if [[ ! -e "$TARGET/.env" ]]; then
  cp "$TARGET/.env.example" "$TARGET/.env"
  chmod 600 "$TARGET/.env"
  echo '首次部署已生成 .env；请设置 vLLM 地址、BiSheng 1.3.1 工作流 ID 后执行 sudo bash deploy/install.sh。'
  echo "配置路径：$TARGET/.env"
  exit 0
fi
chmod 600 "$TARGET/.env"
chown -R 10001:10001 "$TARGET/data"
chmod 755 "$TARGET/data" "$TARGET/data/media"
cd "$TARGET"
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build --remove-orphans
printf '\n已发起部署，检查：\n'
docker compose ps
printf '\n服务地址：http://172.16.10.3:18080\n部署目录：%s\n' "$TARGET"
