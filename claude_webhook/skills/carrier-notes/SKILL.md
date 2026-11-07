---
name: carrier-notes
description: Read-only. For the flight numbers given, read the night's carrier-note inbox and say, for each flight, whether its latest note confirms an actual arrival time or only gives an estimate.
---

# carrier-notes (read-only skill)

You are given flight numbers. The night's carrier notes are in the `inbox/` folder, one file per
note, in no guaranteed order. Each file starts with a header: `note_id`, `flight`, `received`.
Several notes can concern the same flight, and a later note replaces an earlier one.

For each requested flight:
1. Read every note in `inbox/` whose `flight` header is that flight.
2. Take the note with the latest `received` time. If there is none, the finding is `no_note`.
3. Decide the finding from that latest note:
   - `confirmed_arrival` if it confirms the aircraft is on block or landed, with an actual
     arrival time (ATA). An ETA, revised ETA or expected time is NOT a confirmation.
   - `estimate_only` if it only gives an estimated or revised arrival time.
4. `time` is the HH:MM time that note gives for the finding (the ATA for a confirmed arrival,
   the revised ETA for an estimate), copied exactly as written.
5. `note_id` is the `note_id` header of that latest note.

You only read. You never write, edit or create files, and you never run commands.

Answer with ONE JSON object and nothing else:
{"flights": [{"flight": 5188, "finding": "confirmed_arrival", "time": "06:12", "note_id": "N-0631"}]}
