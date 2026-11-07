#!/usr/bin/env bash
# Install the morning brief agent on Ubuntu 24.04 as systemd services. Run as root from the repo:
#   sudo deploy/install-ubuntu.sh
# Then put your keys in /etc/morning-brief/env (see deploy/env.example) and:
#   sudo systemctl restart morning-brief-agent
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
systemctl restart morning-brief-api morning-brief-web morning-brief-agent   # picks up new code on a re-run
systemctl --no-pager --lines=0 status morning-brief-agent | head -5
