"""A fresh clone with one config file: the agent signs with the same secret the webhook checks, so
the webhook answers 202. No model is called (FAKE_CLAUDE_DELAY replaces Claude).
Run: .venv/bin/python tests/test_shared_config.py
"""
import json, os, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

env_file = Path(tempfile.mkstemp(prefix="env-")[1])
env_file.write_text("WEBHOOK_SECRET=change-me-in-a-fresh-clone\nWEBHOOK_PORT=8393\nFAKE_CLAUDE_DELAY=0.2\n")
env = {k: v for k, v in os.environ.items() if k not in ("WEBHOOK_SECRET", "WEBHOOK_PORT")}
env["MORNING_ENV_FILE"] = str(env_file)
p = subprocess.Popen([sys.executable, str(ROOT / "claude_webhook" / "server.py")], env=env)
time.sleep(1.2)
try:
    # sign exactly as the agent does, in a separate process that reads the same file
    sig_code = ("import sys,json; sys.path.insert(0, %r); from settings import sign; "
                "b=json.dumps({'skill':'carrier-notes','idempotency_key':'fresh','input':{'flights':[5188]}}).encode(); "
                "print(b.decode()); print(sign(b))") % str(ROOT)
    out = subprocess.run([sys.executable, "-c", sig_code], env=env, capture_output=True, text=True).stdout.splitlines()
    req = urllib.request.Request("http://127.0.0.1:8393/v1/requests", data=out[0].encode(), method="POST",
                                 headers={"X-Signature": out[1], "Content-Type": "application/json"})
    status = urllib.request.urlopen(req).status
    print(("PASS " if status == 202 else "FAIL ") + f"agent signature accepted by the webhook ({status})")
    sys.exit(0 if status == 202 else 1)
finally:
    p.terminate()
    env_file.unlink()
