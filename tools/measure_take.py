"""Turns a filmed take (events.json from film_call.py) and the webhook log into the timeline and
the delays shown on the page. Every number comes from a logged event; nothing is typed in.
Usage: python tools/measure_take.py TAKE_DIR WEBHOOK_LOG OUT_JSON
"""
import json, subprocess, sys
from pathlib import Path

if len(sys.argv) < 4:
    sys.exit("Usage: python tools/measure_take.py TAKE_DIR WEBHOOK_LOG OUT_JSON")
take, wlog, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
d = json.loads((take / "events.json").read_text())
frames, ev = d["frames"], d["events"]
v0 = frames[0]                                  # video time 0, wall clock (s)
vt = lambda wall_s: round(wall_s - v0, 2)
scene = Path(__file__).resolve().parent.parent / "web" / "static" / "scene"


def trailing_silence(name):
    r = subprocess.run(["ffmpeg", "-i", str(scene / f"{name}.wav"), "-af", "silencedetect=noise=-40dB:d=0.1", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    starts = [float(l.split("silence_start: ")[1]) for l in r.splitlines() if "silence_start" in l]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(scene / f"{name}.wav")], capture_output=True, text=True).stdout)
    return max(0.0, dur - starts[-1]) if starts else 0.0


rows, turns = [], []
on = [e for e in ev if e["type"] == "agent_audio_on"]
off = [e for e in ev if e["type"] == "agent_audio_off"]
agent_tr = [e for e in ev if e["type"] == "transcript" and e["who"] == "agent"]
prev = 0
for tr in agent_tr:
    seg_on = [e for e in on if prev < e["t"] <= tr["t"]]
    seg_off = [e for e in off if prev < e["t"] <= tr["t"] + 300]
    if seg_on:
        rows.append({"who": "agent", "start": vt(seg_on[0]["t"] / 1000), "end": vt(seg_off[-1]["at"] / 1000) if seg_off else vt(tr["t"] / 1000),
                     "text": tr["text"].strip()})
    prev = tr["t"]
clips = {e["name"]: e for e in ev if e["type"] == "clip_start"}
ends = {e["name"]: e for e in ev if e["type"] == "clip_end"}
for name, c in clips.items():
    sil = trailing_silence(name)
    speech_end = ends[name]["t"] / 1000 - sil
    rows.append({"who": "caller", "start": vt(c["t"] / 1000), "end": vt(speech_end), "text": c["text"]})
    first = next(e for e in on if e["t"] / 1000 > speech_end)
    turns.append({"caller": c["text"], "end_of_speech": vt(speech_end),
                  "first_audible_s": round(first["t"] / 1000 - speech_end, 2)})
rows.sort(key=lambda r: r["start"])

w = [json.loads(l) for l in wlog.read_text().splitlines()]
acc = [x for x in w if x["event"] == "accepted" and v0 < x["t"] < frames[-1]][-1]
done = next(x for x in w if x["event"] == "done" and x["request_id"] == acc["request_id"])
spoken = next(e for e in on if e["t"] / 1000 > done["t"])
busy_until = max((e["at"] / 1000 for e in off if e["t"] / 1000 > done["t"] and e["t"] < spoken["t"]), default=None)
webhook = {"request_id": acc["request_id"], "sent": vt(acc["t"]), "returned": vt(done["t"]),
           "seconds": round(done["t"] - acc["t"], 2), "result": done["result"],
           "result_audible_after_return_s": round(spoken["t"] / 1000 - done["t"], 2),
           "agent_was_speaking_until": vt(busy_until) if busy_until else None,
           "result_audible_after_agent_finished_s": round(spoken["t"] / 1000 - busy_until, 2) if busy_until else None}
# Q1's useful answer: the first agent row that names the flights
q1 = turns[0]
ans = next(r for r in rows if r["who"] == "agent" and r["start"] > q1["end_of_speech"] and ("eighty" in r["text"] or "5188" in r["text"]))
q1["answer_audible_s"] = round(ans["start"] - q1["end_of_speech"], 2)
out.write_text(json.dumps({"video_duration_s": vt(frames[-1]), "rows": rows, "turns": turns, "webhook": webhook}, indent=1))
print(json.dumps({"turns": turns, "webhook": {k: v for k, v in webhook.items() if k != "result"}}, indent=1))
