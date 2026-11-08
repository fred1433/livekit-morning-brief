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

The webhook, the agent and the call page all read `.env.local`, so they share one
`WEBHOOK_SECRET`. Open http://127.0.0.1:8303 and press "Start the brief". Try: "Which Amsterdam arrivals still
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
sudo deploy/install-ubuntu.sh                 # user, venv, systemd units for agent, API and call page, enabled at boot
sudo nano /etc/morning-brief/env              # keys and URLs, see deploy/env.example
sudo systemctl restart 'morning-brief-*'      # every unit that reads the env file
```

The Claude webhook needs the `claude` CLI logged in on a Claude plan. If that is this server,
`sudo systemctl enable --now morning-brief-webhook`; otherwise run `claude_webhook/server.py` on
your Claude host and set `CLAUDE_WEBHOOK_URL` and the same `WEBHOOK_SECRET` on both sides. In the
recorded call, the webhook ran on another machine (the builder's Mac, standing in for the team's
Claude setup); the agent, the API and the call page ran as systemd units on the Ubuntu VM.

The agent only opens outbound connections (to LiveKit Cloud, OpenAI, your API and the Claude
webhook). `proof/ubuntu_reboot.txt` is the reboot check on an Ubuntu 24.04 VM: boot id before and
after `sudo systemctl reboot`, the units started by systemd, the agent registered with LiveKit
Cloud without anyone logging in, and the agent's journal line for the filmed call, with its
boot id. The recorded call on the demo page was made right after that reboot. For phones, put the
call page behind your reverse proxy with HTTPS (browsers only give the microphone to HTTPS pages).

Every call costs model minutes, so `/api/token` is guarded. Set `CALL_PAGE_KEY` and share the
page as `https://your-host/?key=THAT_KEY`; without a key, only the server itself can start calls.
`TOKENS_PER_HOUR` (default 20) caps calls per address. For more than a team demo, put the page
behind your own login.

## The Claude webhook contract

The agent calls the webhook; Claude runs one predefined, read-only skill; the result comes back.

| Step | Request | Answer |
|---|---|---|
| Start | `POST /v1/requests` with `{"skill": "carrier-notes", "idempotency_key": "...", "input": {"flights": [...]}}`, header `X-Signature` = hex HMAC-SHA256 of the body | `202 {"request_id", "status": "running", "deadline_s"}` |
| Duplicate | same `idempotency_key` again | `200`, same `request_id`, `"duplicate": true`, no second run; the result is not spoken twice |
| Result | `GET /v1/requests/{id}?wait=25` (long-poll), `X-Signature` = HMAC of `GET <request_id>` | `{"status": "done", "result", "seconds"}`, or `running`; `404` if the webhook restarted and forgot the id |
| Deadline passed | Claude not done after `WEBHOOK_DEADLINE_S` (45 s) | `{"status": "expired"}`; the agent says it could not get the notes in time, that nothing changed, and that the caller can ask again |
| Claude failed | `claude -p` exits with an error | `{"status": "failed"}`; the agent says the check failed (not that it timed out) |
| Ask again | same `idempotency_key` after `expired`, `failed` or `abandoned` | the key is freed, so a new request runs |
| Caller hung up | `DELETE /v1/requests/{id}` (signed), sent by the agent on hang-up | `{"status": "abandoned"}`; a late result is logged and never spoken |

Why long-poll and not a callback: the agent runs on a server that opens no inbound port, and each
call is its own process. A callback would need a public endpoint routed to the right call.

Claude runs as `claude -p` with only the `Read` and `Glob` tools, in a throwaway copy of the skill
folder: there is no path that writes. Claude chooses the note and the finding; the code then
checks that the note is that flight's latest note, that it contains the quoted time, and, for an
arrival, that the line giving the time says on block, landed or ATA without denying it ("No
confirmed ATA, 07:40 is only an estimate" is rejected). Two different answers for one flight are
both dropped. The code then writes the sentence, and the voice model is told to read it word for
word. The agent's long-poll is bounded (deadline plus 30 s), and every HTTP status is checked. To plug in your
own Claude setup, keep the three endpoints, or change `check_carrier_notes` in `agent/agent.py`.

## Read-only

The internal API answers 405 to POST, PUT, PATCH and DELETE, and the agent has two tools:
`list_arrivals` and `check_carrier_notes`. On a real call, asked "Mark fifty-one eighty-eight as
arrived at six twelve", the agent said: "I can only read. Someone on the team needs to record
that arrival in the ops system." (`proof/refusal_call.json`).

## Which voice stack, measured

One recorded call each, same fictional data, delays from the end of the caller's speech to the
first agent sound in the caller's browser (`proof/*_measures.json`, built by `tools/measure_take.py`):

| | First words back, three turns | Useful answer to the first question | Asking for the carrier notes |
|---|---|---|---|
| **OpenAI `gpt-live-1`** (full duplex, tools delegated to `gpt-5.6-luna`), default here | 2.6 s, 3.0 s, 2.6 s | 6.1 s | "Checking the carrier notes now." after 3.0 s; answered the estimate question while Claude worked (12.7 s); the result was read out 18.7 s after the caller asked, without being asked again |
| This repository with `PIPELINE=chain` (LiveKit Inference: `deepgram/flux-general-en`, `google/gemma-4-31b-it`, `cartesia/sonic-3.5`; end of turn from the STT; the Claude tool blocks the turn) | 9.0 s, 17.4 s, 7.2 s | 9.0 s | silent for 17.4 s, 13.0 s of it Claude |

The chain figures measure our chain setup on one call, not chains in general: the speech-to-text
connection dropped and reconnected during that call, the tool blocked the turn, and the estimate
question came after the result. A fair comparison needs an asynchronous tool (LiveKit async tools)
and the question asked at the same moment. gpt-live-1 is billed by OpenAI per session minute plus
the backend model's tokens. Building and filming this demo used about 27 minutes of gpt-live-1 calls.

`gpt-live-1` is not deterministic: in 6 of the 15 development calls before the filmed one, the
Claude check did not start on the first request (`proof/reliability.json`). The prompt now makes
the call to `check_carrier_notes` mandatory; in the filmed call it started on the first request.
The film on the demo page is that one call, shown uncut.

## Tests

```bash
.venv/bin/python tests/test_contract.py         # webhook: success, duplicate, deadline passed then asked again, unknown id, caller hung up
.venv/bin/python tests/test_validator.py        # plausible wrong answers from Claude rejected (denied arrival, duplicate flight...), the right one kept
.venv/bin/python tests/test_shared_config.py    # a fresh clone: agent and webhook share one secret, the webhook answers 202 (no model call)
.venv/bin/python tests/test_read_only.py        # writes refused by the API, no write tool in the agent
.venv/bin/python tests/test_skill_inversion.py  # real claude -p: both flights, findings, times and cited notes; swapped inbox flips them
```

## Filming a call yourself

Install Playwright once (`uv pip install -p .venv/bin/python playwright && .venv/bin/playwright install chromium`),
then, with the stack running: `.venv/bin/python tools/film_call.py "http://127.0.0.1:8303/?film=1" out/`. The caller's lines are pre-recorded clips in `web/static/scene/`; everything the
agent says is produced live. `tools/measure_take.py` turns the take into the timeline and delays,
`tools/build_site.py` builds the demo page from those files.
