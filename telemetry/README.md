# Week 5 — Automated Telemetry Capture

A standalone Python tool that continuously collects operational evidence (health, curated
Prometheus metrics, fault state, and synthetic end-to-end payment attempts) from the four
existing microservices and writes it to structured, timestamped JSONL files — the raw material
Week 6 will turn into a labeled incident dataset.

## Why Python, not another Spring Boot service

Weeks 6–12 (dataset tooling, ChromaDB, LangGraph, Isolation Forest, Ollama, RAG, evaluation) are
all Python. Writing the telemetry format in Python now avoids a double translation later, and a
periodic HTTP-polling loop doesn't need a JVM's startup cost, DI container, or another
Dockerfile/Kubernetes Deployment added to the existing topology. The only Java-side change was
adding one read-only `GET /fault-status` endpoint per service (see "Fault state" below) — no
Spring service, dependency, or existing endpoint was touched.

## Architecture

```
telemetry/
├── config.py         service URLs + tunables, all overridable via env vars
├── util.py           now_iso(), new_correlation_id()
├── storage.py         JsonlWriter - append-only, daily-rotating, flush-per-record
├── payment_probe.py   synthetic login+payment probe (see "Why a payment probe" below)
├── collector.py       health/metrics/fault-status fetchers, Prometheus parsing, Collector class
├── experiment.py      NORMAL -> FAULT -> RECOVERY orchestrator, built on Collector
├── tests/              pytest suite (19 tests, HTTP mocked via `responses`)
├── requirements.txt
└── data/               output directory (gitignored - generated, not source)
```

`collector.py` is intentionally the only place that talks to the four services for regular
telemetry; `experiment.py` reuses it rather than re-implementing polling.

### Why a payment probe

Two of the four controlled faults only manifest on a real request — passive `/actuator/health` +
`/actuator/prometheus` polling alone never observes them:

- **auth-key-error**: breaks JWT *validation*, which only happens when a token is actually used.
- **notification-latency**: only adds delay to an actual `POST /api/notifications/receipt` call.

(The other two — **memory-leak** and **db-pool-exhaustion** — *do* show up passively in
`jvm_memory_used_bytes` and `hikaricp_connections_*` respectively.)

So the collector also performs a real login + payment on every cycle (`payment_probe.py`) and
records the outcome (status, duration, `notificationStatus`). The probe **caches its JWT and
reuses it** across cycles rather than logging in fresh every time — deliberately, because a
freshly-issued token always validates against whichever signing key is *currently* active. Only a
token obtained *before* the auth-key-error fault fires will actually fail once the key is
swapped, exactly like a real already-logged-in user would experience it.

## Fault state — the one Java-side change

The four existing fault controllers (`AuthFaultController`, `MemoryLeakFaultController`,
`DbLockFaultController`, `LatencyFaultController`) only had `POST /inject-*` / `POST /reset-*`
before Week 5 — no way to *read* fault state without changing it. Each now also exposes:

```
GET /fault-status
```

returning the same read-only fields the POST endpoints already returned (e.g.
`{"faultActive": bool, ...}`), using each fault service's existing getters
(`isEnabled()`/`isFaultActive()`/`getHeldConnectionCount()`/etc.). **No fault behavior changed** —
these are pure reads, exposed on all four services, no secrets included (auth-service's endpoint
never returns the JWT key, active or original).

## Data schema

Three JSONL streams, one file per UTC calendar day per stream (`<prefix>_YYYY-MM-DD.jsonl`), so a
long-running collector can never grow one file without bound.

### `telemetry_<date>.jsonl` — one record per service per collection cycle

```json
{
  "timestamp": "2026-08-27T18:35:23.816013+00:00",
  "service": "notification-service",
  "correlation_id": "b2e1...",
  "health": {
    "status": "UP",
    "components": {"diskSpace": "UP", "livenessState": "UP", "readinessState": "UP", "ping": "UP"}
  },
  "metrics": {
    "jvm_memory_used_bytes": 40814800.0,
    "jvm_memory_committed_bytes": 83886080.0,
    "jvm_memory_max_bytes": 4294967296.0,
    "hikaricp_connections_active": null,
    "hikaricp_connections_idle": null,
    "hikaricp_connections_pending": null,
    "hikaricp_connections_acquire_seconds_avg": null,
    "http_server_requests_count": 12.0,
    "http_server_requests_error_count": 0.0,
    "http_server_requests_avg_duration_ms": 43.3,
    "http_client_requests_count": null,
    "http_client_requests_avg_duration_ms": null,
    "process_cpu_usage": 0.0021,
    "system_cpu_usage": 0.17
  },
  "fault": {"faultActive": true, "delayMs": 6000, "message": "Notification latency fault is active."},
  "collection_error": null
}
```

`hikaricp_*` fields are only ever populated for ledger-service; `http_client_requests_*` only for
payment-service (the only service that makes outbound calls) — `null` elsewhere is expected, not
a bug. `collection_error` is a string (never raises) when a service couldn't be reached; the
`health`/`metrics`/`fault` fields for whichever call(s) failed stay `null`.

### `payment_probes_<date>.jsonl` — one record per synthetic transaction

```json
{
  "timestamp": "2026-08-27T18:35:23.826662+00:00",
  "type": "payment_probe",
  "correlation_id": "9f3a...",
  "success": true,
  "stage": "payment",
  "http_status": 200,
  "duration_ms": 5026.1,
  "payment_status": "ACCEPTED",
  "notification_status": "FAILED",
  "ledger_transaction_id": "820d6304-...",
  "error": null
}
```

### `events_<date>.jsonl` — written only by `experiment.py`, marks fault transitions

```json
{"timestamp": "2026-08-27T18:35:23.774414+00:00", "event": "FAULT_INJECTED", "fault": "notification-latency", "service": "notification-service", "response": {"faultActive": true, "delayMs": 6000, "message": "..."}}
```

Events: `EXPERIMENT_START`, `FAULT_INJECTED` (or `FAULT_INJECT_FAILED`), `FAULT_RESET` (or
`FAULT_RESET_FAILED`), `EXPERIMENT_END`.

### Why curated, not a raw Prometheus dump

Each `/actuator/prometheus` scrape exposes 100+ metric families, most irrelevant to the four
fault scenarios and to future RCA use. `parse_metrics()` extracts a fixed, documented set chosen
because each one directly evidences a specific fault (see the code comments in `collector.py` for
the fault→metric mapping) or is a broadly useful general signal (CPU, overall error rate). This
keeps records small, consistent across services, and immediately loadable into pandas without a
separate wide-to-long reshape step.

### Correlation with existing logs

Every collector HTTP call (health, metrics, fault-status) carries a freshly generated
`X-Correlation-Id`, which every service already reads/echoes/logs (Week 1's convention,
unchanged). The ID is recorded on the telemetry row, so `grep <correlation_id> logs` on any
service pinpoints exactly the request behind any specific row. No new tracing mechanism was
built — this is the existing `X-Correlation-Id` architecture, just also captured on the
collector's own outbound side.

## Configuration

All via environment variables (defaults shown), so the identical code runs unmodified against
native processes, Docker Compose, or `kubectl port-forward`'d Kubernetes services:

| Variable | Default | Purpose |
|---|---|---|
| `TELEMETRY_AUTH_SERVICE_URL` | `http://localhost:8081` | |
| `TELEMETRY_PAYMENT_SERVICE_URL` | `http://localhost:8082` | |
| `TELEMETRY_LEDGER_SERVICE_URL` | `http://localhost:8083` | |
| `TELEMETRY_NOTIFICATION_SERVICE_URL` | `http://localhost:8084` | |
| `TELEMETRY_INTERVAL_SECONDS` | `10` | seconds between collection cycles |
| `TELEMETRY_HTTP_TIMEOUT_SECONDS` | `5` | per-request timeout (payment probe uses 3x this) |
| `TELEMETRY_DATA_DIR` | `telemetry/data` | output directory |
| `TELEMETRY_PROBE_USERNAME` / `_PASSWORD` | `alice` / `alice-pass` | probe login credentials |
| `TELEMETRY_PROBE_ACCOUNT_ID` / `_CURRENCY` / `_AMOUNT` | `acct-42` / `USD` / `0.01` | probe payment body |

CLI flags (`collector.py`/`experiment.py`) override the interval/data-dir env vars per-run; see
below.

## Running the collector

```bash
cd telemetry
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Continuous, until Ctrl+C:
python -m telemetry.collector

# Bounded run, custom interval, disable the payment probe:
python -m telemetry.collector --interval 5 --duration 120 --no-probe
```

Run from the repository root (`python -m telemetry.collector`, not `python telemetry/collector.py`
— the module uses relative imports).

**Against Kubernetes**, port-forward the four services first, then point the env vars at the
forwarded ports:

```bash
kubectl port-forward svc/auth-service 18081:8081 &
kubectl port-forward svc/payment-service 18082:8082 &
kubectl port-forward svc/ledger-service 18083:8083 &
kubectl port-forward svc/notification-service 18084:8084 &

TELEMETRY_AUTH_SERVICE_URL=http://localhost:18081 \
TELEMETRY_PAYMENT_SERVICE_URL=http://localhost:18082 \
TELEMETRY_LEDGER_SERVICE_URL=http://localhost:18083 \
TELEMETRY_NOTIFICATION_SERVICE_URL=http://localhost:18084 \
python -m telemetry.collector
```

No code changes needed for any of the three deployment modes.

## Running a NORMAL → FAULT → RECOVERY experiment

```bash
python -m telemetry.experiment notification-latency \
  --baseline-seconds 30 --fault-seconds 30 --recovery-seconds 30 --interval 5
```

`fault` is one of `auth-key-error`, `memory-leak`, `db-lock`, `notification-latency`. This starts
the collector, waits `baseline-seconds`, injects the fault, waits `fault-seconds`, resets it,
waits `recovery-seconds`, then stops — writing continuous telemetry the whole time plus event
markers at each transition.

**Reconstructing the four phases in Week 6**: join `telemetry_<date>.jsonl` (per-service
`fault.faultActive`) or `payment_probes_<date>.jsonl` (`notification_status`/`success`/
`duration_ms`) against `events_<date>.jsonl`'s `FAULT_INJECTED`/`FAULT_RESET` timestamps:

- `timestamp < FAULT_INJECTED` → **NORMAL**
- `FAULT_INJECTED <= timestamp <` (first row where `fault.faultActive` flips `true`) → **FAULT_INTRODUCTION** (brief; usually one cycle)
- `fault.faultActive == true` → **FAULT_ACTIVE**
- `FAULT_RESET <= timestamp` (until `fault.faultActive` settles back to `false`) → **RECOVERY**

This was verified live for all four faults in this session — see the Week 5 final report for the
actual numbers (e.g. notification-latency: probe duration ~15ms baseline → ~5020ms during the
fault → ~15ms after reset, with `fault.faultActive` flipping in exact sync with the
`FAULT_INJECTED`/`FAULT_RESET` event timestamps).

## Tests

```bash
cd telemetry && source .venv/bin/activate
python -m pytest tests/ -v
```

19 tests: Prometheus metric extraction (including the summary-metric parsing subtlety - see code
comments), `collect_service`/`collect_cycle` fault tolerance (one service down doesn't stop the
others, never raises), `JsonlWriter` rotation/serialization, and `PaymentProbe` token-caching
behavior.

## Design constraints honored

- **Bounded memory**: `JsonlWriter` never buffers records — each is serialized and flushed to
  disk immediately.
- **Bounded disk growth**: daily file rotation; old files can be archived/deleted independently.
- **Tolerates partial failure**: each service polled in its own try/except; a down service
  produces a `collection_error` string, never an exception that stops the cycle.
- **Clean shutdown**: `SIGINT`/`SIGTERM` set a stop flag checked between cycles; the current cycle
  finishes and all writers are flushed/closed before exit. Shutdown latency is therefore bounded
  by one collection cycle (typically a few seconds at the default 10s interval), not instant —
  see the Week 5 final report's "Known limitations" for the measured behavior.
- **No secrets exposed**: `/fault-status` never returns key material.
- **No unnecessary infrastructure**: no Kafka/Elasticsearch/cloud DB — plain JSONL files, matching
  what Week 6 (pandas/ChromaDB) needs to load directly.

## How this feeds Week 6

Week 6 ("Incident dataset, Memory/Evaluation split, ChromaDB") reads these three JSONL streams,
joins them by timestamp/correlation ID per the phase-reconstruction recipe above, and turns each
NORMAL→FAULT→RECOVERY experiment into one labeled incident record (root-cause service, symptom
service, metric deltas, textual postmortem) — split into the Memory set (~20, embedded into
ChromaDB) and the Evaluation set (~40–60, held out, per `CLAUDE.md`'s hard "evaluation incidents
must never enter RAG memory" rule). The curated telemetry schema here was designed specifically
so that split and embedding step doesn't need to touch a single Java service again.
