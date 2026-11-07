"""Plausible wrong answers from Claude must not reach the caller. The validator keeps a finding only
if the cited note is that flight's latest note and contains the quoted time with the right wording.
Run: .venv/bin/python tests/test_validator.py
"""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
os.environ["NOTES_DIR"] = str(ROOT / "claude_webhook" / "data" / "inbox")
sys.path.insert(0, str(ROOT / "claude_webhook"))
from server import validate  # noqa: E402

F = [5188, 7745]
cases = {
    "correct answer kept": ([{"flight": 5188, "finding": "confirmed_arrival", "time": "06:12", "note_id": "N-0631"},
                             {"flight": 7745, "finding": "estimate_only", "time": "07:40", "note_id": "N-7745-x"}],
                            {5188: "confirmed_arrival", 7745: "unverified"}),
    "both right": ([{"flight": 5188, "finding": "confirmed_arrival", "time": "06:12", "note_id": "N-0631"},
                    {"flight": 7745, "finding": "estimate_only", "time": "07:40", "note_id": "N-0547"}],
                   {5188: "confirmed_arrival", 7745: "estimate_only"}),
    "06:12 lent to the other flight": ([{"flight": 7745, "finding": "confirmed_arrival", "time": "06:12", "note_id": "N-0631"}],
                                       {7745: "unverified", 5188: "unverified"}),
    "stale note (older ETA) cited": ([{"flight": 7745, "finding": "estimate_only", "time": "06:40", "note_id": "N-0436"}],
                                     {7745: "unverified", 5188: "unverified"}),
    "estimate presented as arrival": ([{"flight": 7745, "finding": "confirmed_arrival", "time": "07:40", "note_id": "N-0547"}],
                                      {7745: "unverified", 5188: "unverified"}),
    "time from elsewhere (05:58)": ([{"flight": 5188, "finding": "confirmed_arrival", "time": "05:58", "note_id": "N-0631"}],
                                    {5188: "unverified", 7745: "unverified"}),
    "flight not asked for is dropped": ([{"flight": 4127, "finding": "confirmed_arrival", "time": "01:48", "note_id": "N-0152"}],
                                        {5188: "unverified", 7745: "unverified"}),
    "no_note claimed while a note exists": ([{"flight": 5188, "finding": "no_note", "time": None, "note_id": None}],
                                            {5188: "unverified", 7745: "unverified"}),
}
ok = True
for name, (claude, expect) in cases.items():
    got = {f["flight"]: f["finding"] for f in validate(F, json.dumps({"flights": claude}))["flights"]}
    good = got == expect
    ok &= good
    print(("PASS " if good else "FAIL ") + name + ("" if good else f"  got {got}"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
