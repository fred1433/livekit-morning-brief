"""Replays the four webhook cases against a real webhook server (Claude replaced by a fixed delay):
success, duplicate, deadline passed, caller hung up. Also checks the signature and the skill list.
Run: .venv/bin/python tests/test_contract.py
"""
import asyncio, hashlib, hmac, json, os, subprocess, sys, time
from pathlib import Path
import aiohttp

ROOT = Path(__file__).resolve().parent.parent
SECRET = b"test-secret"


def sign(b): return hmac.new(SECRET, b, hashlib.sha256).hexdigest()


async def post(http, url, payload):
    b = json.dumps(payload).encode()
    async with http.post(url + "/v1/requests", data=b, headers={"X-Signature": sign(b)}) as r:
        return r.status, await r.json()


def server(port, delay, deadline, log):
    env = dict(os.environ, WEBHOOK_SECRET=SECRET.decode(), WEBHOOK_PORT=str(port), FAKE_CLAUDE_DELAY=str(delay),
               WEBHOOK_DEADLINE_S=str(deadline), WEBHOOK_LOG=str(log))
    p = subprocess.Popen([sys.executable, str(ROOT / "claude_webhook" / "server.py")], env=env)
    time.sleep(1.2)
    return p


async def main():
    log = Path("/tmp") / f"webhook_contract_{os.getpid()}.jsonl"
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))

    p = server(8392, delay=1.0, deadline=3.0, log=log)
    url = "http://127.0.0.1:8392"
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(force_close=True)) as http:
            # bad signature
            async with http.post(url + "/v1/requests", data=b'{"skill":"carrier-notes"}', headers={"X-Signature": "00"}) as r:
                check("unsigned request refused", r.status == 401, r.status)
            # unknown skill: only the one predefined skill runs
            s, j = await post(http, url, {"skill": "update-arrival", "input": {"flights": [1]}})
            check("unknown skill refused", s == 404, j)
            # 1. success
            t0 = time.time()
            s, j = await post(http, url, {"skill": "carrier-notes", "idempotency_key": "room-a:5188,7745", "input": {"flights": [5188, 7745]}})
            check("success: 202 + request_id", s == 202 and j["request_id"].startswith("req_"), j)
            rid = j["request_id"]
            # 2. duplicate while running: same id, no second run
            s2, j2 = await post(http, url, {"skill": "carrier-notes", "idempotency_key": "room-a:5188,7745", "input": {"flights": [5188, 7745]}})
            check("duplicate: 200, same request_id", s2 == 200 and j2["request_id"] == rid and j2["duplicate"], j2)
            async with http.get(f"{url}/v1/requests/{rid}", params={"wait": "10"}) as r:
                res = await r.json()
            check("success: long-poll returns done", res["status"] == "done" and time.time() - t0 < 3, res["status"])
            # 3. deadline passed
            p.terminate(); p.wait()
            p = server(8392, delay=5.0, deadline=1.5, log=log)
            s, j = await post(http, url, {"skill": "carrier-notes", "idempotency_key": "room-b", "input": {"flights": [5188]}})
            async with http.get(f"{url}/v1/requests/{j['request_id']}", params={"wait": "10"}) as r:
                res = await r.json()
            check("deadline: status expired", res["status"] == "expired", res)
            # 4. caller hung up while Claude works: closed as abandoned, late result logged, never returned
            p.terminate(); p.wait()
            p = server(8392, delay=1.5, deadline=10, log=log)
            s, j = await post(http, url, {"skill": "carrier-notes", "idempotency_key": "room-c", "input": {"flights": [7745]}})
            rid = j["request_id"]
            b = b"{}"
            async with http.delete(f"{url}/v1/requests/{rid}", data=b, headers={"X-Signature": sign(b)}) as r:
                d = await r.json()
            check("hang-up: request closed as abandoned", d["status"] == "abandoned", d)
            await asyncio.sleep(2.2)
            async with http.get(f"{url}/v1/requests/{rid}") as r:
                res = await r.json()
            check("hang-up: late result never delivered", res["status"] == "abandoned" and "result" not in res, res)
            events = [json.loads(l)["event"] for l in log.read_text().splitlines()]
            check("hang-up: late result logged", "late_result_discarded" in events)
    finally:
        p.terminate()
        log.unlink(missing_ok=True)
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
