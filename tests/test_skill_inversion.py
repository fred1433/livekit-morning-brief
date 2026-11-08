"""Runs the real Claude skill (claude -p, subscription) on the night's inbox, then on a swapped inbox
where the 06:12 confirmation belongs to the other flight. The recommendation must flip.
Run: .venv/bin/python tests/test_skill_inversion.py
"""
import asyncio, importlib, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "claude_webhook"))
sys.path.insert(0, str(ROOT / "agent"))


async def run(folder):
    os.environ["NOTES_DIR"] = str(ROOT / "claude_webhook" / "data" / folder)
    import server
    importlib.reload(server)
    t = time.time()
    raw = await server.run_claude([5188, 7745])
    res = server.validate([5188, 7745], raw)
    return res, time.time() - t


async def main():
    from agent import result_sentence
    ok = True
    expected = {
        "inbox": {5188: ("confirmed_arrival", "06:12", "N-0631"), 7745: ("estimate_only", "07:40", "N-0547")},
        "inbox_swapped": {5188: ("estimate_only", "07:40", "N-0547"), 7745: ("confirmed_arrival", "06:12", "N-0631")},
    }
    for folder, want in expected.items():
        res, s = await run(folder)
        sentence = result_sentence(res)
        got = {f["flight"]: (f["finding"], f["time"], f["note_id"]) for f in res["flights"]}
        good = got == want   # both flights, both findings, both times, both cited notes; a missing flight fails
        if not good:
            print("   expected", want, "\n   got     ", got)
        ok &= good
        print(("PASS " if good else "FAIL ") + f"{folder}: Claude took {s:.1f} s -> {sentence}")
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
