# Morning brief voice agent (LiveKit Agents, Ubuntu, Claude webhook)

A voice agent you call from a phone browser for a quick morning brief. It reads a read-only
internal API, answers from a small knowledge base, and hands slower work to a Claude skill
through a webhook. While Claude works, the call goes on: the caller can ask something else,
and the agent gives Claude's result as soon as it is back.

Recorded call and measured delays: https://theaipipe.com/demos/livekit-morning-brief/

**All data is fictional**: six overnight arrivals in a 07:00 snapshot, and a night's inbox of
nine carrier notes. Nothing comes from a real company system.

## Run it on a laptop (one command)

Needs Python 3.12 with [uv](https://docs.astral.sh/uv/), a LiveKit Cloud project, an OpenAI API
key, and the `claude` CLI logged in on a Claude plan (the webhook runs `claude -p`).

```bash
cp deploy/env.example .env.local      # fill LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, OPENAI_API_KEY
./start.sh                            # internal API :8301, Claude webhook :8302, call page :8303, agent worker
```

Open http://127.0.0.1:8303 and press "Start the brief". Try: "Which Amsterdam arrivals still
need checking?", then "Can you check the carrier notes for those two?", then, while Claude
works, "Does an estimate count?".

## What is where

| Piece | File | Change it |
|---|---|---|
| Voice agent (LiveKit Agents 1.8) | `agent/agent.py` | tools are the `@function_tool` methods |
| Prompt | `agent/prompt.md` | edit, then restart |
| Voice, models | environment: `VOICE`, `BACKEND_MODEL`, `PIPELINE`, `CHAIN_STT`, `CHAIN_LLM`, `CHAIN_TTS` | edit the env file, then restart |
| Knowledge base | `knowledge/*.md` | add or edit Markdown; loaded into the agent at the start of each call |
| Internal API (fictional, GET only) | `mock_api/server.py`, `mock_api/data/snapshot.json` | point `INTERNAL_API_URL` at your API with a read-only token |
| Webhook in front of Claude | `claude_webhook/server.py` | one skill: `claude_webhook/skills/carrier-notes/SKILL.md` |
| Mobile call page + token endpoint | `web/index.html`, `web/server.py` | |
| Ubuntu install, systemd units | `deploy/` | |

Restart after a change: `./start.sh` again on a laptop, or on Ubuntu
`sudo systemctl restart morning-brief-agent` (logs: `journalctl -u morning-brief-agent -f`).

## Ubuntu server, survives a restart

```bash
sudo deploy/install-ubuntu.sh                 # user, venv, three systemd units, enabled at boot
sudo nano /etc/morning-brief/env              # keys and URLs, see deploy/env.example
sudo systemctl restart morning-brief-agent
```

The agent only opens outbound connections (to LiveKit Cloud, OpenAI, your API and the Claude
webhook). `proof/ubuntu_reboot.txt` is the reboot check on an Ubuntu 24.04 VM: boot id before and
after `sudo systemctl reboot`, the agent started by systemd and registered with LiveKit Cloud
without anyone logging in. The recorded call on the demo page was made right after that reboot. For phones, put the
call page behind your reverse proxy with HTTPS (browsers only give the microphone to HTTPS pages).

## The Claude webhook contract

The agent calls the webhook; Claude runs one predefined, read-only skill; the result comes back.

| Step | Request | Answer |
|---|---|---|
| Start | `POST /v1/requests` with `{"skill": "carrier-notes", "idempotency_key": "...", "input": {"flights": [5188, 7745]}}`, header `X-Signature` = hex HMAC-SHA256 of the body | `202 {"request_id", "status": "running", "deadline_s"}` |
| Duplicate | same `idempotency_key` again | `200`, same `request_id`, `"duplicate": true`, no second run; the result is not spoken twice |
| Result | `GET /v1/requests/{id}?wait=25` (long-poll) | `{"status": "done", "result", "seconds"}`, or `running` |
| Deadline passed | Claude not done after `WEBHOOK_DEADLINE_S` (45 s) | `{"status": "expired"}`; the agent says it could not get the notes and that nothing changed |
| Caller hung up | `DELETE /v1/requests/{id}` (signed), sent by the agent on hang-up | `{"status": "abandoned"}`; a late result is logged and never spoken |

Why long-poll and not a callback: the agent runs on a server that opens no inbound port, and each
call is its own process. A callback would need a public endpoint routed to the right call.

Claude runs as `claude -p` with only the `Read` and `Glob` tools, in a throwaway copy of the skill
folder: there is no path that writes. Claude chooses the note and the finding; the code then
checks that the note is that flight's latest note and that it contains the quoted time (next to
ATA or on-block wording for an arrival), and writes the sentence the agent speaks. To plug in your
own Claude setup, keep the three endpoints, or change `check_carrier_notes` in `agent/agent.py`.

## Read-only

The internal API answers 405 to POST, PUT, PATCH and DELETE, and the agent has two tools:
`list_arrivals` and `check_carrier_notes`. On a real call, asked "Mark fifty-one eighty-eight as
arrived at six twelve", the agent said: "I can only read. Someone on the team needs to record
that arrival in the ops system." (`proof/refusal_call.json`).

## Which voice stack, measured

Same three questions, same fictional data, one recorded call each, delays from the end of the
caller's speech to the first agent sound in the caller's browser (`proof/*_measures.json`):

| | First words back, three turns | Useful answer to the first question | While Claude worked (10 to 13 s) |
|---|---|---|---|
| **OpenAI `gpt-live-1`** (full duplex, tools delegated to `gpt-5.6-luna`), default here | 2.4 s, 2.5 s, 2.3 s | 6.3 s | said "Checking.", answered the next question, then gave the result unprompted |
| STT, LLM, TTS chain on LiveKit Inference (`deepgram/flux-general-en`, `google/gemma-4-31b-it`, `cartesia/sonic-3.5`), default settings | 9.0 s, 17.4 s, 7.2 s | 9.0 s | silent until the tool returned |

The chain can be tuned (preemptive generation, LiveKit async tools that report progress), and is
one setting away: `PIPELINE=chain`. gpt-live-1 is billed by OpenAI per session minute plus the
backend model's tokens. Building and filming this demo used about 25 minutes of gpt-live-1 calls.

`gpt-live-1` is not deterministic: in 5 of the 14 calls filmed while building this, it did not
start the Claude check on the first ask. The film on the demo page is one call, shown uncut.

## Tests

```bash
.venv/bin/python tests/test_contract.py         # webhook: success, duplicate, deadline passed, caller hung up
.venv/bin/python tests/test_validator.py        # seven plausible wrong answers from Claude rejected, the right one kept
.venv/bin/python tests/test_read_only.py        # writes refused by the API, no write tool in the agent
.venv/bin/python tests/test_skill_inversion.py  # real claude -p: move the 06:12 confirmation, the answer flips
```

## Filming a call yourself

Install Playwright once (`uv pip install -p .venv/bin/python playwright && .venv/bin/playwright install chromium`),
then, with the stack running: `.venv/bin/python tools/film_call.py "http://127.0.0.1:8303/?film=1" out/`. The caller's lines are pre-recorded clips in `web/static/scene/`; everything the
agent says is produced live. `tools/measure_take.py` turns the take into the timeline and delays,
`tools/build_site.py` builds the demo page from those files.
