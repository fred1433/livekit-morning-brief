#!/usr/bin/env bash
# Install the morning brief agent on Ubuntu 24.04 as systemd services. Run as root from the repo:
#   sudo deploy/install-ubuntu.sh
# Then put your keys in /etc/morning-brief/env (see deploy/env.example) and restart every unit
# that reads it:  sudo systemctl restart 'morning-brief-*'
# The Claude webhook unit is installed but only enabled where the claude CLI is logged in:
#   sudo systemctl enable --now morning-brief-webhook
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
id morningbrief >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/morningbrief --shell /usr/sbin/nologin morningbrief
apt-get update -qq && apt-get install -y -qq python3-venv curl rsync >/dev/null
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh >/dev/null
mkdir -p /opt/morning-brief /etc/morning-brief
rsync -a --delete --exclude .venv --exclude .git --exclude logs --exclude '*.jsonl' --exclude .env.local "$SRC/" /opt/morning-brief/
[ -f /etc/morning-brief/env ] || install -m 600 -o morningbrief "$SRC/deploy/env.example" /etc/morning-brief/env
cd /opt/morning-brief
[ -d .venv ] || uv venv -q -p 3.12 .venv
uv pip install -q -p .venv/bin/python -r requirements.txt
.venv/bin/python agent/agent.py download-files >/dev/null 2>&1 || true
chown -R morningbrief: /opt/morning-brief
install -m 644 deploy/morning-brief-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable morning-brief-api morning-brief-web morning-brief-agent
# restart everything that reads the env file, so new code and new keys are picked up on a re-run
systemctl restart morning-brief-api morning-brief-web morning-brief-agent
systemctl is-enabled --quiet morning-brief-webhook && systemctl restart morning-brief-webhook || true
systemctl --no-pager --lines=0 status morning-brief-agent | head -5
