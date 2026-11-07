"""Webhook in front of Claude: runs ONE predefined read-only skill and hands the result back.

Contract (see README, "Webhook contract"):
  POST   /v1/requests            -> 202 {request_id, status: "running", deadline_s}
                                    same idempotency_key again -> 200, same request_id, no second run
  GET    /v1/requests/{id}?wait=N -> long-poll; 200 {status: running|done|failed|expired|abandoned, ...}
  DELETE /v1/requests/{id}        -> the caller hung up: the request is closed as "abandoned";
                                    if Claude finishes later, the result is logged and never spoken
Every POST/DELETE carries X-Signature: hex HMAC-SHA256 of the raw body with WEBHOOK_SECRET.

The voice agent only makes outbound calls (POST, then long-poll), so the Ubuntu server that runs
it opens no inbound port. Claude runs as `claude -p` with the Read and Glob tools only, inside a
throwaway copy of the skill folder: there is no path that writes to a record.
"""
import asyncio, hashlib, hmac, json, os, re, shutil, tempfile, time, uuid
from pathlib import Path
from aiohttp import web

ROOT = Path(__file__).parent
SECRET = os.environ.get("WEBHOOK_SECRET", "demo-webhook-secret").encode()
NOTES_DIR = Path(os.environ.get("NOTES_DIR", ROOT / "data" / "inbox"))
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "sonnet")
DEADLINE_S = float(os.environ.get("WEBHOOK_DEADLINE_S", "45"))
# for the contract tests: replace Claude by a fixed delay + canned answer
FAKE_CLAUDE_DELAY = os.environ.get("FAKE_CLAUDE_DELAY")
LOG = Path(os.environ.get("WEBHOOK_LOG", ROOT / "webhook_log.jsonl"))
SKILLS = {"carrier-notes": ROOT / "skills" / "carrier-notes" / "SKILL.md"}

REQUESTS: dict[str, dict] = {}
BY_KEY: dict[str, str] = {}


def log(event: str, **kw):
    rec = {"t": round(time.time(), 3), "event": event, **kw}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def signed(body: bytes, sig: str | None) -> bool:
    good = hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    return bool(sig) and hmac.compare_digest(good, sig)


def validate(flights: list[int], raw: str) -> dict:
    """Keep only what the notes support. Claude picks a finding and a note; the code checks that
    the note exists, belongs to that flight, is that flight's latest note, and contains the time
    Claude quotes (next to an ATA / on-block wording for a confirmed arrival)."""
    m = re.search(r"\{.*\}", raw, re.S)
    data = json.loads(m.group(0)) if m else {}
    notes = {}
    latest: dict[int, tuple[str, str]] = {}
    for p in NOTES_DIR.glob("*.txt"):
        txt = p.read_text()
        nid = re.search(r"note_id:\s*(\S+)", txt)
        fl = re.search(r"flight:\s*(\d+)", txt)
        rec = re.search(r"received:\s*([\d-]+ \d\d:\d\d)", txt)
        if nid and fl and rec:
            f = int(fl.group(1))
            notes[nid.group(1)] = {"flight": f, "text": txt}
            if f not in latest or rec.group(1) > latest[f][0]:
                latest[f] = (rec.group(1), nid.group(1))
    out = []
    for item in data.get("flights", []):
        try:
            flight = int(item.get("flight"))
        except (TypeError, ValueError):
            continue
        if flight not in flights:
            continue
        finding, t, nid = item.get("finding"), str(item.get("time") or ""), item.get("note_id")
        note = notes.get(nid)
        if finding == "no_note":
            ok = flight not in latest
        else:
            body = note["text"].split("\n\n", 1)[-1] if note else ""
            ok = (finding in ("confirmed_arrival", "estimate_only") and note is not None and
                  note["flight"] == flight and latest.get(flight, ("", ""))[1] == nid and
                  bool(re.fullmatch(r"\d\d:\d\d", t)) and t in body)
        if finding == "confirmed_arrival" and ok:
            ok = bool(re.search(r"(ATA|on block|landed)[^\n]{0,40}" + re.escape(t) + r"|" + re.escape(t) +
                                r"[^\n]{0,20}(ATA|on block|landed)", body, re.I))
        if finding == "estimate_only" and ok:
            ok = bool(re.search(r"(ETA|estimate)[^\n]{0,30}" + re.escape(t), body, re.I))
        out.append({"flight": flight, "finding": finding if ok else "unverified",
                    "time": t if ok and finding != "no_note" else None, "note_id": nid if ok else None})
    seen = {o["flight"] for o in out}
    out += [{"flight": f, "finding": "unverified", "time": None, "note_id": None} for f in flights if f not in seen]
    return {"flights": sorted(out, key=lambda o: flights.index(o["flight"]))}


async def run_claude(flights: list[int]) -> str:
    if FAKE_CLAUDE_DELAY is not None:
        await asyncio.sleep(float(FAKE_CLAUDE_DELAY))
        return json.dumps({"flights": [{"flight": f, "finding": "no_note", "time": None, "note_id": None} for f in flights]})
    work = Path(tempfile.mkdtemp(prefix="skill-"))
    try:
        shutil.copy(SKILLS["carrier-notes"], work / "SKILL.md")
        shutil.copytree(NOTES_DIR, work / "inbox")
        prompt = (f"Run the carrier-notes skill described in ./SKILL.md for flights "
                  f"{', '.join(map(str, flights))}. Follow it exactly. Answer with the JSON object only.")
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # subscription only, never an API key
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN, "-p", prompt, "--tools", "Read,Glob", "--setting-sources", "project",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence",
            "--output-format", "json", "--model", CLAUDE_MODEL,
            cwd=work, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await proc.communicate()
        except asyncio.CancelledError:
            proc.kill()
            raise
        if proc.returncode != 0:
            raise RuntimeError(err.decode()[-300:])
        return json.loads(out)["result"]
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def worker(rid: str):
    req = REQUESTS[rid]
    try:
        raw = await asyncio.wait_for(run_claude(req["flights"]), timeout=DEADLINE_S)
        result = validate(req["flights"], raw)
        req["finished_at"] = time.time()
        if req["status"] == "abandoned":
            log("late_result_discarded", request_id=rid, result=result)
        else:
            req.update(status="done", result=result)
            log("done", request_id=rid, seconds=round(req["finished_at"] - req["created_at"], 2), result=result)
    except asyncio.TimeoutError:
        if req["status"] != "abandoned":
            req.update(status="expired")
        log("expired", request_id=rid, deadline_s=DEADLINE_S)
    except Exception as e:  # noqa: BLE001
        if req["status"] != "abandoned":
            req.update(status="failed", error=str(e)[:200])
        log("failed", request_id=rid, error=str(e)[:200])
    finally:
        req["event"].set()


async def create(request):
    body = await request.read()
    if not signed(body, request.headers.get("X-Signature")):
        return web.json_response({"error": "bad_signature"}, status=401)
    p = json.loads(body)
    if p.get("skill") not in SKILLS:
        return web.json_response({"error": "unknown_skill", "allowed": list(SKILLS)}, status=404)
    key = str(p.get("idempotency_key") or "")
    if key and key in BY_KEY:
        rid = BY_KEY[key]
        log("duplicate", request_id=rid, idempotency_key=key)
        return web.json_response({"request_id": rid, "status": REQUESTS[rid]["status"], "duplicate": True}, status=200)
    try:
        flights = [int(f) for f in p["input"]["flights"]][:6]
    except (KeyError, TypeError, ValueError):
        return web.json_response({"error": "bad_input"}, status=400)
    rid = "req_" + uuid.uuid4().hex[:10]
    REQUESTS[rid] = {"status": "running", "flights": flights, "created_at": time.time(), "event": asyncio.Event(),
                     "room": p.get("room")}
    if key:
        BY_KEY[key] = rid
    log("accepted", request_id=rid, flights=flights, room=p.get("room"))
    REQUESTS[rid]["task"] = asyncio.create_task(worker(rid))
    return web.json_response({"request_id": rid, "status": "running", "deadline_s": DEADLINE_S}, status=202)


def public(rid: str) -> dict:
    r = REQUESTS[rid]
    out = {"request_id": rid, "status": r["status"]}
    if r["status"] == "done":
        out["result"] = r["result"]
        out["seconds"] = round(r["finished_at"] - r["created_at"], 2)
    if r["status"] == "failed":
        out["error"] = r.get("error")
    return out


async def poll(request):
    rid = request.match_info["rid"]
    if rid not in REQUESTS:
        return web.json_response({"error": "not_found"}, status=404)
    wait = min(float(request.query.get("wait", "0")), 30.0)
    if REQUESTS[rid]["status"] == "running" and wait > 0:
        try:
            await asyncio.wait_for(REQUESTS[rid]["event"].wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass
    out = public(rid)
    if out["status"] != "running":
        log("returned", request_id=rid, status=out["status"])
    return web.json_response(out)


async def cancel(request):
    rid = request.match_info["rid"]
    body = await request.read()
    if not signed(body, request.headers.get("X-Signature")):
        return web.json_response({"error": "bad_signature"}, status=401)
    if rid not in REQUESTS:
        return web.json_response({"error": "not_found"}, status=404)
    r = REQUESTS[rid]
    if r["status"] == "running":
        r["status"] = "abandoned"
        log("abandoned", request_id=rid)
    return web.json_response(public(rid))


async def health(request):
    return web.json_response({"ok": True, "skills": list(SKILLS)})


def app():
    a = web.Application()
    a.router.add_post("/v1/requests", create)
    a.router.add_get("/v1/requests/{rid}", poll)
    a.router.add_delete("/v1/requests/{rid}", cancel)
    a.router.add_get("/healthz", health)
    return a


if __name__ == "__main__":
    web.run_app(app(), host=os.environ.get("WEBHOOK_HOST", "127.0.0.1"), port=int(os.environ.get("WEBHOOK_PORT", "8302")), print=None)
