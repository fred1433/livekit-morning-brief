"""Film one real call on the mobile call page (390 px), with the pre-recorded caller lines.

Usage: python tools/film_call.py http://127.0.0.1:8303/?film=1 OUT_DIR

The caller's four lines are pre-recorded clips played into the published microphone track.
Everything the agent says is produced live during the call. Nothing is edited out: the
script only waits for the agent to finish before playing the next line, so the silences in
the film are the real ones. Output: frames + timestamps, the mixed call audio, events.json,
then call.mp4 (frames and audio on the same wall clock).
"""
import asyncio, base64, json, subprocess, sys, time
from pathlib import Path
from playwright.async_api import async_playwright

if len(sys.argv) < 3:
    sys.exit("Usage: python tools/film_call.py CALL_PAGE_URL?film=1 OUT_DIR")
URL, OUT = sys.argv[1], Path(sys.argv[2])
SCENE = [
    ("caller1", "Morning. Which Amsterdam arrivals still need checking?"),
    ("caller2", "Can you check the carrier notes for those two?"),
    ("caller3", "Does an estimate count?"),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frames").mkdir(exist_ok=True)
    frames = []
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"])
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        page = await ctx.new_page()
        page.on("console", lambda m: print("console:", m.text) if m.type in ("error", "warning") else None)
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")
        await page.evaluate("document.fonts.ready")
        cdp = await ctx.new_cdp_session(page)

        def on_frame(params):
            i = len(frames)
            (OUT / "frames" / f"{i:05d}.jpg").write_bytes(base64.b64decode(params["data"]))
            frames.append(params["metadata"]["timestamp"])
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": 780, "maxHeight": 1688})
        await asyncio.sleep(1.2)

        async def events():
            return await page.evaluate("window.__ev")

        async def wait_event(type_, after, timeout):
            t_end = time.time() + timeout
            while time.time() < t_end:
                for e in await events():
                    if e["type"] == type_ and e["t"] / 1000 >= after:
                        return e
                await asyncio.sleep(0.05)
            return None

        async def wait_transcript(after, pattern, timeout):
            import re
            t_end = time.time() + timeout
            while time.time() < t_end:
                for e in await events():
                    if e["type"] == "transcript" and e["who"] == "agent" and e["t"] / 1000 >= after and re.search(pattern, e["text"], re.I):
                        return e
                await asyncio.sleep(0.1)
            return None

        async def wait_agent_turn(after, timeout=25, quiet=1.5):
            on = await wait_event("agent_audio_on", after, timeout)
            if not on:
                print("no agent audio after", after)
                return None
            while True:
                await asyncio.sleep(0.1)
                speaking = await page.evaluate("window.__agentOn()")
                evs = await events()
                offs = [e for e in evs if e["type"] == "agent_audio_off" and e["t"] >= on["t"]]
                if not speaking and offs and time.time() - offs[-1]["at"] / 1000 > quiet:
                    return offs[-1]

        await page.click("#call")
        t_click = time.time()
        await wait_event("connected", t_click, 20)
        await wait_agent_turn(t_click, timeout=20)          # greeting
        await asyncio.sleep(0.6)
        # line 1: wait for the actual answer (with the flight numbers), not the "checking" filler
        t = time.time()
        await page.evaluate("([n, x]) => window.__playClip(n, x)", list(SCENE[0]))
        ans = await wait_transcript(t, r"eighty|fifty|seventy|5188|7745", 30)
        await wait_agent_turn(ans["t"] / 1000 - 15, timeout=5, quiet=0.8) if ans else None
        await asyncio.sleep(0.3)
        # line 2: ask for the Claude check; wait for the acknowledgement(s), then ask something else
        t = time.time()
        await page.evaluate("([n, x]) => window.__playClip(n, x)", list(SCENE[1]))
        run = await wait_event("ui_check_running", t, 14)
        if not run:
            print("ABORT: the agent did not start the Claude check")
            await page.click("#call")
            await asyncio.sleep(1)
            sys.exit(2)
        await wait_agent_turn(t, timeout=20, quiet=0.8)
        if run:
            nxt = await wait_event("agent_audio_on", time.time() - 0.3, 1.2)
            if nxt:
                await wait_agent_turn(nxt["t"] / 1000 - 0.1, timeout=8, quiet=0.7)
        # the KB question, asked while the Claude check is still running
        t = time.time()
        await page.evaluate("([n, x]) => window.__playClip(n, x)", list(SCENE[2]))
        # the agent answers it, then delivers the Claude result on its own, unprompted
        res = await wait_transcript(t, r"follow up|06:12|six twelve|six-twelve", 50)
        if not res:
            print("WARN: no spoken result")
        await wait_agent_turn(t, timeout=5, quiet=1.0)
        await asyncio.sleep(1.0)
        audio_b64 = await page.evaluate("window.__stopRecording()")
        await page.click("#call")
        await asyncio.sleep(1.5)
        await cdp.send("Page.stopScreencast")
        evs = await events()
        await page.screenshot(path=str(OUT / "last.png"))
        await b.close()
    (OUT / "call.webm").write_bytes(base64.b64decode(audio_b64))
    (OUT / "events.json").write_text(json.dumps({"frames": frames, "events": evs}, indent=1))
    # build the video: each frame lasts until the next one, on the wall clock
    lst = []
    for i, ts in enumerate(frames):
        dur = (frames[i + 1] - ts) if i + 1 < len(frames) else 0.5
        lst += [f"file 'frames/{i:05d}.jpg'", f"duration {max(dur, 0.001):.4f}"]
    lst.append(f"file 'frames/{len(frames) - 1:05d}.jpg'")
    (OUT / "frames.txt").write_text("\n".join(lst) + "\n")
    rec = next(e["t"] for e in evs if e["type"] == "recorder_start") / 1000
    offset = rec - frames[0]
    print(f"frames={len(frames)} span={frames[-1] - frames[0]:.1f}s audio_offset={offset:.3f}s")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(OUT / "frames.txt"),
                    "-itsoffset", f"{offset:.3f}", "-i", str(OUT / "call.webm"),
                    "-map", "0:v", "-map", "1:a", "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "20",
                    "-preset", "slow", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(OUT / "call.mp4")],
                   check=True)


asyncio.run(main())
