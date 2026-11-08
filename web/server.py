"""Serves the mobile call page and issues LiveKit tokens that dispatch the morning-brief agent.

Each token opens a call that costs model minutes, so /api/token is guarded: set CALL_PAGE_KEY and
share the page as https://your-host/?key=THAT_KEY (the page sends the key with its token request).
Without CALL_PAGE_KEY the endpoint only answers requests from this machine (127.0.0.1). Every
client is also limited to TOKENS_PER_HOUR tokens (default 20).
"""
import hmac, os, sys, time, uuid
from collections import defaultdict, deque
from pathlib import Path
from aiohttp import web
from livekit import api

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import settings  # noqa: E402,F401  (loads .env.local on a laptop; systemd passes the env on Ubuntu)

AGENT_NAME = os.environ.get("AGENT_NAME", "morning-brief")
CALL_PAGE_KEY = os.environ.get("CALL_PAGE_KEY", "")
TOKENS_PER_HOUR = int(os.environ.get("TOKENS_PER_HOUR", "20"))
_issued: dict[str, deque] = defaultdict(deque)


async def token(request):
    client = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()
    if CALL_PAGE_KEY:
        if not hmac.compare_digest(request.headers.get("X-Call-Key", ""), CALL_PAGE_KEY):
            return web.json_response({"error": "This page needs its key: open the link you were given."}, status=403)
    elif request.remote not in ("127.0.0.1", "::1") or "X-Forwarded-For" in request.headers:
        return web.json_response({"error": "Set CALL_PAGE_KEY to open calls from other machines."}, status=403)
    q = _issued[client]
    now = time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= TOKENS_PER_HOUR:
        return web.json_response({"error": "Too many calls from this address in the last hour."}, status=429)
    q.append(now)
    room = "brief-" + uuid.uuid4().hex[:8]
    ident = "caller-" + uuid.uuid4().hex[:6]
    jwt = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
           .with_identity(ident).with_name("Caller")
           .with_grants(api.VideoGrants(room_join=True, room=room))
           .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=AGENT_NAME)]))
           .to_jwt())
    return web.json_response({"url": os.environ["LIVEKIT_URL"], "token": jwt, "room": room})


async def index(request):
    return web.FileResponse(ROOT / "index.html")


def app():
    a = web.Application()
    a.router.add_post("/api/token", token)
    a.router.add_get("/", index)
    a.router.add_static("/static/", ROOT / "static")
    return a


if __name__ == "__main__":
    web.run_app(app(), host=os.environ.get("WEB_HOST", "127.0.0.1"), port=int(os.environ.get("WEB_PORT", "8303")), print=None)
