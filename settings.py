"""One configuration for every process (agent, Claude webhook, call page, internal API).

Values come from the environment; on a laptop they are also read from .env.local (or the file
named by MORNING_ENV_FILE), so the agent and the webhook always share the same WEBHOOK_SECRET.
On Ubuntu, systemd passes /etc/morning-brief/env to every unit.
"""
import hashlib, hmac, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("MORNING_ENV_FILE", ROOT / ".env.local"))
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "demo-webhook-secret").encode()


def sign(data: bytes) -> str:
    """Hex HMAC-SHA256 with WEBHOOK_SECRET. POST and DELETE sign the body; GET signs b"GET " + request id."""
    return hmac.new(WEBHOOK_SECRET, data, hashlib.sha256).hexdigest()


def signed(data: bytes, sig: str | None) -> bool:
    return bool(sig) and hmac.compare_digest(sign(data), sig)
