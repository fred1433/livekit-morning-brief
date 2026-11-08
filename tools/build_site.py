"""Builds site/index.html from site/template.html and the measured files. No number is typed by hand."""
import html, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
t = (ROOT / "page" / "template.html").read_text()
call = json.loads((ROOT / "proof" / "live_call_measures.json").read_text())
chain = json.loads((ROOT / "proof" / "chain_call_measures.json").read_text())
inbox = ROOT / "claude_webhook" / "data" / "inbox"
t = t.replace("__CALL_JSON__", json.dumps(call))
t = t.replace("__NOTE_5188__", html.escape((inbox / "0631_N-0631.txt").read_text().strip()))
t = t.replace("__NOTE_7745__", html.escape((inbox / "0547_N-0547.txt").read_text().strip()))
t = t.replace("__CHAIN_JSON__", json.dumps({"turns": chain["turns"], "webhook": {"seconds": chain["webhook"]["seconds"]}}))
dur = call["video_duration_s"]
t = t.replace("__DURATION__", f"{int(dur // 60)}:{int(round(dur % 60)):02d}")
ask = call["carrier_check_asked_at"]
t = t.replace("__JUMP__", f"{int(ask // 60)}:{int(ask % 60):02d}")
rel = json.loads((ROOT / "proof" / "reliability.json").read_text())
t = t.replace("__RELIABILITY__", html.escape(rel["sentence"]))
assert "__" not in t.replace("__proto__", ""), "placeholder left"
assert chr(0x2014) not in t, "long dash found"
(ROOT / "site" / "index.html").write_text(t)
# poster: the board with the six flights and the two missing times, before the Claude check
import subprocess
at = (call.get("board_shown_at") or 20) + 2.0
subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(ROOT / "site" / "call.mp4"), "-frames:v", "1",
                "-q:v", "3", str(ROOT / "site" / "poster.jpg")], check=True)
print("site/index.html written")
