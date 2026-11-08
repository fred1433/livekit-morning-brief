"""Morning brief voice agent (LiveKit Agents 1.8).

Brain: OpenAI gpt-live-1 (full duplex) by default, with tools delegated to an explicit backend
model. Alternative: --pipeline chain, a STT -> LLM -> TTS chain on LiveKit Inference.
Everything the agent reads is fictional demo data. See README for where to change things.
"""
import asyncio, json, logging, os, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, cli, function_tool

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from settings import sign  # noqa: E402  (reads .env.local or the systemd env file, shared with the webhook)

logger = logging.getLogger("livekit.agents.morning_brief")
AMS = ZoneInfo("Europe/Amsterdam")

# ---- settings (all overridable by environment variables) -------------------------------------
PIPELINE = os.environ.get("PIPELINE", "live")  # "live" (gpt-live-1) or "chain" (LiveKit Inference)
VOICE = os.environ.get("VOICE", "marin")  # gpt-live voices: beacon cedar cinder marin stone vesper
BACKEND_MODEL = os.environ.get("BACKEND_MODEL", "gpt-5.6-luna")  # model the delegated tool work runs on
BACKEND_REASONING = os.environ.get("BACKEND_REASONING", "low")
CHAIN_STT = os.environ.get("CHAIN_STT", "deepgram/flux-general-en")
CHAIN_LLM = os.environ.get("CHAIN_LLM", "google/gemma-4-31b-it")
CHAIN_TTS = os.environ.get("CHAIN_TTS", "cartesia/sonic-3.5")
INTERNAL_API = os.environ.get("INTERNAL_API_URL", "http://127.0.0.1:8301")
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "demo-read-only-token")
WEBHOOK_URL = os.environ.get("CLAUDE_WEBHOOK_URL", "http://127.0.0.1:8302")
WEBHOOK_DEADLINE_S = float(os.environ.get("WEBHOOK_DEADLINE_S", "45"))
KB_DIR = Path(os.environ.get("KB_DIR", ROOT / "knowledge"))
PROMPT = (ROOT / "agent" / "prompt.md").read_text()
BACKEND_INSTRUCTIONS = ("You run tools for a voice agent on a phone call. Call the right tool at once. Then reply in one "
                        "short spoken sentence, with the exact flight numbers and times the tool returned.")
EVENT_LOG = Path(os.environ.get("AGENT_EVENT_LOG", ROOT / "agent_events.jsonl"))
AGENT_NAME = os.environ.get("AGENT_NAME", "morning-brief")


def log(event: str, **kw):
    with EVENT_LOG.open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 3), "event": event, **kw}) + "\n")


def hhmm(ts: str | None) -> str | None:
    """HH:MM in Amsterdam time, whatever offset the API uses."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(AMS).strftime("%H:%M") if ts else None


def boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def knowledge_text() -> str:
    """The small knowledge base: every Markdown file in knowledge/, loaded at call start."""
    return "\n\n".join(p.read_text() for p in sorted(KB_DIR.glob("*.md")))


def follow_up(result: dict) -> list[int]:
    return [f["flight"] for f in result["flights"] if f["finding"] != "confirmed_arrival"]


def result_sentence(result: dict) -> str:
    """Builds the result sentence in code from the validated findings. The voice model is told to
    read it word for word; no model writes a flight number or a time here."""
    order = sorted(result["flights"], key=lambda f: f["finding"] != "confirmed_arrival")
    parts = []
    for f in order:
        n, t = f["flight"], f["time"]
        if f["finding"] == "confirmed_arrival":
            parts.append(f"The carrier confirmed {n}'s arrival at {t}.")
        elif f["finding"] == "estimate_only":
            parts.append(f"{n} only has an estimate, {t}.")
        elif f["finding"] == "no_note":
            parts.append(f"{n} has no carrier note.")
        else:
            parts.append(f"I could not verify the note for {n}.")
    follow = follow_up(result)
    if len(follow) == 1 and order[-1]["flight"] == follow[0]:
        parts.append("That's the one to follow up.")
    elif follow:
        parts.append(f"Follow up on {' and '.join(map(str, follow))}.")
    return " ".join(parts)


class MorningBrief(Agent):
    def __init__(self, ctx: JobContext, http: aiohttp.ClientSession):
        super().__init__(instructions=PROMPT + "\n\n# Knowledge base\n\n" + knowledge_text())
        self.ctx, self.http = ctx, http
        self.pending: dict[str, asyncio.Task] = {}

    async def ui(self, **attrs):
        try:
            await self.ctx.room.local_participant.set_attributes({k: json.dumps(v) for k, v in attrs.items()})
        except Exception as e:  # noqa: BLE001
            log("ui_error", error=str(e))

    @function_tool
    async def list_arrivals(self, context: RunContext, only_missing_actual_arrival: bool = False) -> dict:
        """Read the overnight arrivals at Amsterdam (AMS) from the internal API (read-only).

        Args:
            only_missing_actual_arrival: True to return only flights with no actual arrival time recorded.
        """
        t0 = time.time()
        async with self.http.get(f"{INTERNAL_API}/v1/flights", params={"port_of_arrival": "AMS"},
                                 headers={"Authorization": f"Bearer {INTERNAL_API_TOKEN}"}) as r:
            data = await r.json()
        rows = data["flights"]
        missing = [f["number"] for f in rows if not f["arrival_actual_at"]]
        log("tool", name="list_arrivals", ms=round((time.time() - t0) * 1000), missing=missing)
        await self.ui(board=[{"n": f["number"], "from": f["departure_airport"], "sched": hhmm(f["arrival_scheduled_at"]),
                              "est": hhmm(f["arrival_estimated_at"]), "actual": hhmm(f["arrival_actual_at"])} for f in rows],
                      focus=missing)
        if only_missing_actual_arrival:
            rows = [f for f in rows if not f["arrival_actual_at"]]
        return {"snapshot": "fictional demo snapshot, 07:00 Amsterdam", "flights_expected_since_midnight": len(data["flights"]),
                "flights_without_actual_arrival": missing,
                "flights": [{"number": f["number"], "from": f["departure_airport"], "scheduled": hhmm(f["arrival_scheduled_at"]),
                             "estimated": hhmm(f["arrival_estimated_at"]), "actual": hhmm(f["arrival_actual_at"])} for f in rows]}

    @function_tool
    async def check_carrier_notes(self, context: RunContext, flight_numbers: list[int]) -> str:
        """Ask the team's Claude skill to read the night's carrier notes for these flights. Read-only.
        It takes ten seconds or more; the conversation goes on while it runs.

        Args:
            flight_numbers: the flight numbers the caller wants checked.
        """
        flights = sorted({int(n) for n in flight_numbers})[:6]
        key = f"{self.ctx.room.name}:{','.join(map(str, flights))}"
        body = json.dumps({"skill": "carrier-notes", "idempotency_key": key, "input": {"flights": flights},
                           "room": self.ctx.room.name}).encode()
        t_send = time.time()
        try:
            async with self.http.post(f"{WEBHOOK_URL}/v1/requests", data=body,
                                      headers={"X-Signature": sign(body), "Content-Type": "application/json"}) as r:
                status = r.status
                ack = await r.json() if r.content_type == "application/json" else {}
        except aiohttp.ClientError as e:
            log("webhook_unreachable", error=str(e)[:200])
            return "The Claude skill cannot be reached. Tell the caller you could not start the check."
        rid = ack.get("request_id") if status in (200, 202) else None
        log("webhook_sent", request_id=rid, http=status, flights=flights, duplicate=ack.get("duplicate", False))
        if not rid:
            return "The Claude skill refused the request. Tell the caller you could not start the check."
        if not ack.get("duplicate"):
            await self.ui(check={"state": "running", "flights": flights, "started": t_send})
        self.pending[rid] = asyncio.current_task()
        res = {"status": "running"}
        try:
            # 202 + request_id, then a bounded long-poll: the server opens no inbound port for a callback
            give_up = t_send + WEBHOOK_DEADLINE_S + 30
            while res.get("status") == "running" and time.time() < give_up:
                try:
                    async with self.http.get(f"{WEBHOOK_URL}/v1/requests/{rid}", params={"wait": "25"},
                                             headers={"X-Signature": sign(b"GET " + rid.encode())}) as r:
                        if r.status == 404:
                            res = {"status": "lost"}      # the webhook restarted and forgot the request
                        elif r.status != 200:
                            res = {"status": "failed", "error": f"HTTP {r.status}"}
                        else:
                            res = await r.json()
                except aiohttp.ClientError as e:
                    res = {"status": "failed", "error": str(e)[:200]}
            if res.get("status") == "running":
                res = {"status": "expired"}
        finally:
            self.pending.pop(rid, None)
        t_back = time.time()
        state = res.get("status", "failed")
        log("webhook_returned", request_id=rid, status=state, seconds=round(t_back - t_send, 2),
            duplicate=ack.get("duplicate", False))
        if state != "done":
            await self.ui(check={"state": state, "flights": flights, "started": t_send})
            if state == "expired":
                return ("The carrier-notes check did not come back in time. Tell the caller you could not get the "
                        "carrier notes in time, that nothing was changed, and that they can ask again.")
            return ("The carrier-notes check failed on the Claude side. Tell the caller the check failed, that "
                    "nothing was changed, and that they can ask again.")
        if ack.get("duplicate"):
            return "This check was already answered earlier in the call. Say only: 'That's the result I gave you.'"
        sentence = result_sentence(res["result"])
        await self.ui(check={"state": "done", "flights": flights, "started": t_send, "seconds": round(t_back - t_send, 1),
                             "result": res["result"]["flights"]})
        log("result_handed_to_voice", request_id=rid, sentence=sentence)
        return f"Claude's result is back. Tell the caller now, reading these exact words: \"{sentence}\""

    async def cancel_pending(self):
        for rid, task in list(self.pending.items()):
            task.cancel()
            body = b"{}"  # the caller hung up: close the request so a late result is logged, never spoken
            try:
                async with self.http.delete(f"{WEBHOOK_URL}/v1/requests/{rid}", data=body,
                                            headers={"X-Signature": sign(body)}) as r:
                    log("webhook_cancelled_on_hangup", request_id=rid, http=r.status)
            except Exception as e:  # noqa: BLE001
                log("cancel_error", request_id=rid, error=str(e))


def build_session() -> AgentSession:
    if PIPELINE == "live":
        from livekit.plugins import openai
        return AgentSession(llm=openai.realtime.GPTLiveModel(voice=VOICE, responses_options={
            "model": BACKEND_MODEL, "instructions": BACKEND_INSTRUCTIONS,
            "reasoning": {"effort": BACKEND_REASONING}, "text": {"verbosity": "low"}}))
    from livekit.plugins import silero
    return AgentSession(stt=CHAIN_STT, llm=CHAIN_LLM, tts=CHAIN_TTS, vad=silero.VAD.load(), turn_detection="stt")


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext):
    http = aiohttp.ClientSession()
    agent = MorningBrief(ctx, http)
    session = build_session()
    t_start = time.time()
    log("call_start", room=ctx.room.name, pipeline=PIPELINE, backend=BACKEND_MODEL if PIPELINE == "live" else CHAIN_LLM,
        boot_id=boot_id())
    # one timestamped journal line per call, tied to the boot it ran in (journalctl -u morning-brief-agent)
    logger.info(f"call started room={ctx.room.name} boot_id={boot_id()}")

    @session.on("metrics_collected")
    def _m(ev):
        try:
            log("metrics", data=ev.metrics.model_dump(mode="json", exclude_none=True))
        except Exception:  # noqa: BLE001
            pass

    @session.on("conversation_item_added")
    def _c(ev):
        item = ev.item
        if getattr(item, "role", None) in ("user", "assistant"):
            log("transcript", role=item.role, text=item.text_content)

    async def on_shutdown():
        await agent.cancel_pending()
        log("call_end", room=ctx.room.name, seconds=round(time.time() - t_start, 1))
        await http.close()

    ctx.add_shutdown_callback(on_shutdown)
    await session.start(agent=agent, room=ctx.room)
    await agent.ui(board=[], focus=[], check={"state": "idle"})
    session.generate_reply(instructions="Say exactly: 'Ready for the 07:00 arrivals brief.' Nothing else.")


if __name__ == "__main__":
    cli.run_app(server)
