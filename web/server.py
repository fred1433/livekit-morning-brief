"""Serves the mobile call page and issues LiveKit tokens that dispatch the morning-brief agent."""
import os, uuid
from pathlib import Path
from aiohttp import web
from livekit import api

ROOT = Path(__file__).resolve().parent
for line in (ROOT.parent / ".env.local").read_text().splitlines() if (ROOT.parent / ".env.local").exists() else []:
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
AGENT_NAME = os.environ.get("AGENT_NAME", "morning-brief")


async def token(request):
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
