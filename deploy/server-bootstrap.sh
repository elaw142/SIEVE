#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/sieve
REPO_URL=https://github.com/elaw142/SIEVE.git

if ! command -v git >/dev/null 2>&1; then
  sudo dnf install -y git
fi

if ! command -v docker >/dev/null 2>&1; then
  sudo dnf install -y docker
  sudo systemctl enable --now docker
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose plugin is required. Install docker-compose-plugin before continuing." >&2
  exit 1
fi

if ! docker network inspect web >/dev/null 2>&1; then
  docker network create web
fi

sudo mkdir -p "$APP_DIR"
sudo chown "$USER:$USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
cp -n .env.example .env
echo "Edit $APP_DIR/.env with Spotify credentials, then run: docker compose up -d --build"
