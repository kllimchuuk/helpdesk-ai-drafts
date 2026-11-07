# Report: measured runs

Measured on 2026-11-07 on the owner's laptop (macOS, Docker Desktop) in keyless mode, the default with no `.env`: every draft sends a real request to the provider with a placeholder key, gets `401`, and waits until a random 5-30 s has passed (I8). Each run used a separate compose project with a fresh database (`COMPOSE_PROJECT_NAME=helpdesk-measure`), so the numbers contain only the run's own tickets. Every figure below comes from the simulator output, `/api/stats`, the mock's `/_debug/deliveries` or a `psql` query on that database; the commands are given with each run.

## Summary

| Invariant | Result | Run |
|---|---|---|
| I1 webhook fast while the LLM is slow | p50 10.4 ms, p95 16.1 ms, max 143.0 ms over 630 requests (target: p95 below 200 ms) | 1 |
| I2 one row per `event_id` | 500 events, 630 requests (50 events sent as 3 simultaneous copies), 500 `accepted`, 130 `duplicate`, 0 dedupe errors | 1 |
| I3 acknowledged tickets survive a crash | worker and API killed with `kill -9` while 20 tickets were generating and 21 waiting; all 60 reached `draft_ready` 136 s after the restart | 2 |
| I4 at most 60 provider calls a minute | at most 55 calls in any 60 s window, 512 calls in total | 1 |
| I5 a crashed worker never strands a ticket | in run 2, 20 tickets were drafted by a second attempt after their lease expired; in run 1, 12 generations were taken over after the laptop slept (see the incident) | 1, 2 |
| I6 no reply sent twice by our retries | 0 duplicate deliveries at a mock that ignores `Idempotency-Key` with 20 % `503`, 5 % timeouts and 10 % hang-after-store: 466 deliveries, 466 unique; worker killed during 10 hanging sends: all 10 `send_unknown`, 10 deliveries, 0 duplicates | 1, 3 |
| I7 transitions happen once | covered by tests only (`test_concurrent_approves_succeed_exactly_once`, `test_twenty_simultaneous_approves_send_exactly_once`) | - |
| I8 keyless mode behaves like the keyed one | all 500 drafts in run 1 came from the keyless path (512 `keyless` rows in `llm_calls`, `401` from the provider in the worker log) and went through the same send path | 1 |
| I9 daily cap | covered by tests only (`LLM_DAILY_CALL_CAP=3`, S3) | - |

## Run 1: 500 events over 10 minutes with a chaotic helpdesk

```bash
export COMPOSE_PROJECT_NAME=helpdesk-measure DB_HOST_PORT=5435
export HONOR_IDEMPOTENCY_KEY=false FAIL_5XX_RATE=0.2 TIMEOUT_RATE=0.05 \
       HANG_AFTER_STORE_RATE=0.1 HANG_SECONDS=40 SEED=11
docker compose up -d --build
docker compose run --rm simulator --events 500 --duration 600 \
  --duplicate-rate 0.1 --concurrent-duplicates 3 --approve --seed 7
```

Simulator output (started 15:45:57 UTC, finished 16:00:07 UTC):

```
events sent:        500 (630 webhook requests with duplicates)
webhook latency ms: p50 10.4, p95 16.1, max 143.0
responses:          {'accepted': 500, 'duplicate': 130}
dedupe errors:      0
approved by run:    500
drained after:      37.4 s after the last webhook
final statuses:     {'sent': 416, 'send_unknown': 84}
mock deliveries:    {'total': 466, 'unique': 466, 'duplicates': 0, 'deduplicated_requests': 0, 'duplicate_keys': []}
```

From the database after the run:

- `send_unknown`: 81 with `ReadTimeout` (the helpdesk timed out or stored and hung), 3 with `lease_expired` (see the incident).
- The 466 stored deliveries are the 416 `sent` tickets plus 50 of the `send_unknown` ones, which the mock stored before hanging. The other 34 `send_unknown` tickets were never stored (timeouts without a store). The operator cannot tell these apart without looking at the helpdesk, which is the reason they are parked (SPEC §9).
- `llm_calls`: 512 rows, all `keyless`, from 15:45:59 to 15:59:30 UTC. The largest number of rows in any 60 s window is 55, the configured limit (query: a self-join counting rows with `called_at` in `[t, t + 60 s)` for every row).
- `gen_attempts`: 488 tickets drafted on the first attempt, 12 on the second.

**Incident: the laptop slept for 197 s during the run.** `pmset -g log` shows `Entering Sleep state due to 'Idle Sleep'` at 15:49:20 UTC and a wake at 15:52:37 UTC; the backend log has a 196 s gap between webhooks at the same time, so the whole Docker VM was paused. When it woke, the database clock had moved past the leases of everything in flight. The service did what it should: 12 generations were taken over by a new attempt (hence 512 provider calls for 500 drafts), and the 3 sends in flight were parked as `send_unknown` instead of being sent again; the late answers of the paused tasks were dropped by the attempt fencing ("Lease lost, result dropped" in the worker log). The latency and drain figures are not affected because the simulator was paused too. Runs 2 and 3 were started under `caffeinate -i`.

## Run 2: kill the worker and the API during generation (I3, I5)

```bash
export COMPOSE_PROJECT_NAME=helpdesk-measure DB_HOST_PORT=5435
docker compose down -v && docker compose up -d
docker compose run --rm simulator --events 60 --duration 20 --duplicate-rate 0 \
  --seed 3 --drain-timeout 0
sleep 8
docker kill -s KILL helpdesk-measure-worker-1 helpdesk-measure-backend-1
sleep 5
docker compose up -d backend worker
# then poll /api/stats until nothing is received or generating
```

- At the kill (16:02:06 UTC): 21 `received`, 20 `generating`, 19 `draft_ready` of 60 accepted events.
- 136 s after the restart: 60 `draft_ready`, nothing else. The 120 s lease of the killed worker had to expire before its 20 tickets could be taken again.
- `gen_attempts`: 40 tickets with 1, 20 with 2, matching the 20 that were generating at the kill.
- Webhook latency for the 60 events: p50 10.1 ms, p95 13.4 ms, max 121.8 ms.

## Run 3: kill the worker during sends (I6)

On the database of run 2, with a mock that stores every reply and then hangs for 25 s (below the 30 s send deadline) and ignores `Idempotency-Key`:

```bash
HANG_AFTER_STORE_RATE=1 HANG_SECONDS=25 HONOR_IDEMPOTENCY_KEY=false \
  docker compose up -d mock-helpdesk
curl -s -X POST localhost:8090/_debug/reset
# approve 10 draft_ready tickets through POST /api/tickets/{id}/approve, wait 4 s
docker kill -s KILL helpdesk-measure-worker-1
docker compose up -d worker
```

- At the kill: 10 `sending`; the mock had stored 10 replies.
- 116 s after the restart: all 10 `send_unknown` with `lease_expired: the worker stopped during the send`, `send_attempts` 1. The mock still counted 10 deliveries, 10 unique, 0 duplicates: nothing was sent again.

## What these runs do not show

- The provider was never called with a real key, so structured output, refusals and real latency of Claude are covered only by tests with a mocked transport (S3).
- I7 and I9 were not exercised by the simulator; their tests are listed above.
- The runs used one worker. Several workers sharing the database are covered by tests (`test_two_workers_draft_every_ticket_exactly_once`, the limiter's I4 test with 5 workers).
- SPEC §12 words I1 as "a fake LLM sleeping 30 s"; keyless mode sleeps a random 5-30 s per draft, which keeps the worker busy for the whole run but is not a constant 30 s.
- The numbers come from one laptop and one run each; they show the invariants hold, not capacity.
