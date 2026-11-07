# Morning arrivals brief: house rules (FICTIONAL, written for this demo)

## What counts as arrived
A flight counts as arrived only when it has a confirmed arrival: arrival_actual_at is set,
or a carrier note confirms the on-block time (ATA). An estimate (arrival_estimated_at, ETA,
revised ETA) never counts as an arrival, however recent it is.

## Which flights need checking
At the 07:00 snapshot, every flight scheduled to arrive at the port since midnight that has no
arrival_actual_at needs checking.

## Who to follow up with
A flight that still has only an estimate after the carrier notes are checked is followed up with
the carrier's handling desk. A flight confirmed by a carrier note only needs its arrival time
recorded by the ops team.

## What the agent may do
The agent reads data. It never changes a record: it cannot mark a flight as arrived, edit a time
or send a message to a carrier. Changes are made by a person in the ops system.

## Snapshot time
The brief reads a snapshot taken at 07:00 Amsterdam time. Times are local Amsterdam time.
