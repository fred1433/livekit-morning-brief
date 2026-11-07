"""Fictional read-only "internal API" for the demo.

It serves a frozen 07:00 snapshot of overnight arrivals. Only GET exists: any write
method answers 405, so even a misbehaving client cannot change a record.
Flight fields: arrival_scheduled_at, arrival_estimated_at, arrival_actual_at. The data is invented.
"""
import json, os
from pathlib import Path
from aiohttp import web

DATA = Path(os.environ.get("SNAPSHOT_FILE", Path(__file__).parent / "data" / "snapshot.json"))
TOKEN = os.environ.get("INTERNAL_API_TOKEN", "demo-read-only-token")


def load():
    return json.loads(DATA.read_text())


@web.middleware
async def guard(request, handler):
    if request.method not in ("GET", "HEAD"):
        return web.json_response({"error": "read_only", "detail": "this API exposes no write path"}, status=405)
    if request.headers.get("Authorization") != f"Bearer {TOKEN}":
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def flights(request):
    snap = load()
    port = request.query.get("port_of_arrival", "AMS").upper()
    rows = [f for f in snap["flights"] if f["port_of_arrival"] == port]
    if request.query.get("missing_actual") == "true":
        rows = [f for f in rows if not f["arrival_actual_at"]]
    return web.json_response({"snapshot_at": snap["snapshot_at"], "window_start": snap["window_start"],
                              "port_of_arrival": port, "count": len(rows), "flights": rows,
                              "_notice": snap["_notice"]})


async def flight(request):
    n = int(request.match_info["number"])
    for f in load()["flights"]:
        if f["number"] == n:
            return web.json_response(f)
    return web.json_response({"error": "not_found"}, status=404)


async def health(request):
    return web.json_response({"ok": True})


def app():
    a = web.Application(middlewares=[guard])
    a.router.add_get("/v1/flights", flights)
    a.router.add_get("/v1/flights/{number}", flight)
    a.router.add_get("/healthz", health)
    # every other method on these paths falls through to the 405 guard
    a.router.add_route("*", "/v1/{tail:.*}", flights)
    return a


if __name__ == "__main__":
    web.run_app(app(), host=os.environ.get("MOCK_API_HOST", "127.0.0.1"), port=int(os.environ.get("MOCK_API_PORT", "8301")), print=None)
