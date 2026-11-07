"""The agent can only read: the internal API answers 405 to every write method, and the agent
exposes no tool that writes. Run: .venv/bin/python tests/test_read_only.py
"""
import asyncio, os, subprocess, sys, time
from pathlib import Path
import aiohttp

ROOT = Path(__file__).resolve().parent.parent


async def main():
    ok = True
    env = dict(os.environ, MOCK_API_PORT="8391")
    p = subprocess.Popen([sys.executable, str(ROOT / "mock_api" / "server.py")], env=env)
    time.sleep(1.2)
    try:
        auth = {"Authorization": "Bearer demo-read-only-token"}
        async with aiohttp.ClientSession() as http:
            async with http.get("http://127.0.0.1:8391/v1/flights", headers=auth) as r:
                good = r.status == 200 and (await r.json())["count"] == 6
                ok &= good
                print(("PASS " if good else "FAIL ") + "GET /v1/flights returns the six flights")
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                async with http.request(method, "http://127.0.0.1:8391/v1/flights/5188", headers=auth,
                                        json={"arrival_actual_at": "2026-11-09T06:12:00+01:00"}) as r:
                    good = r.status == 405
                    ok &= good
                    print(("PASS " if good else "FAIL ") + f"{method} /v1/flights/5188 refused ({r.status})")
    finally:
        p.terminate()
    sys.path.insert(0, str(ROOT / "agent"))
    from agent import MorningBrief
    names = sorted(n for n, v in vars(MorningBrief).items() if type(v).__name__.endswith("FunctionTool"))
    good = names == ["check_carrier_notes", "list_arrivals"]
    ok &= good
    print(("PASS " if good else "FAIL ") + f"agent tools are read-only: {names}")
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
