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
t = t.replace("__CHAIN_FIRST__", f"{chain['turns'][0]['first_audible_s']:.1f}")
t = t.replace("__CHAIN_SILENCE__", f"{chain['turns'][1]['first_audible_s']:.1f}")
assert "__" not in t.replace("__proto__", ""), "placeholder left"
assert chr(0x2014) not in t, "long dash found"
(ROOT / "site" / "index.html").write_text(t)
print("site/index.html written")
