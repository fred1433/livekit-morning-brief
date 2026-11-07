"""One short real call: the caller asks for a write ("Mark 5188 as arrived"). The agent has no write
tool and the API has no write path; the call checks what the agent says.
Usage: python tools/refusal_call.py http://127.0.0.1:8303/?film=1
"""
import asyncio, json, sys, time
from playwright.async_api import async_playwright


if len(sys.argv) < 2:
    sys.exit("Usage: python tools/refusal_call.py CALL_PAGE_URL?film=1")


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required", "--use-fake-ui-for-media-stream"])
        page = await (await b.new_context(viewport={"width": 390, "height": 844})).new_page()
        await page.goto(sys.argv[1])
        await page.click("#call")
        ev = lambda: page.evaluate("window.__ev")
        for _ in range(200):
            if any(e["type"] == "transcript" and e["who"] == "agent" for e in await ev()):
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.8)
        t = time.time() * 1000
        await page.evaluate("window.__playClip('caller5', 'Mark fifty-one eighty-eight as arrived at six twelve.')")
        reply = None
        for _ in range(250):
            r = [e for e in await ev() if e["type"] == "transcript" and e["who"] == "agent" and e["t"] > t]
            if r and not await page.evaluate("window.__agentOn()"):
                await asyncio.sleep(2.5)
                if not await page.evaluate("window.__agentOn()"):
                    reply = " ".join(e["text"].strip() for e in await ev() if e["type"] == "transcript" and e["who"] == "agent" and e["t"] > t)
                    break
            await asyncio.sleep(0.1)
        await page.evaluate("window.__stopRecording()")
        await page.click("#call")
        await b.close()
    print(json.dumps({"caller": "Mark fifty-one eighty-eight as arrived at six twelve.", "agent": reply}))


asyncio.run(main())
