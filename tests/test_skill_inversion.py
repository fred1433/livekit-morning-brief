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
    from agent import follow_up, result_sentence
    ok = True
    for folder, follow in (("inbox", 7745), ("inbox_swapped", 5188)):
        res, s = await run(folder)
        sentence = result_sentence(res)
        good = follow_up(res) == [follow] and sentence.endswith("That's the one to follow up.")
        ok &= good
        print(("PASS " if good else "FAIL ") + f"{folder}: Claude took {s:.1f} s -> {sentence}")
    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
