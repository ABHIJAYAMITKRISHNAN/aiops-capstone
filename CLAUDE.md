# AIOps Self-Healing Microservices Platform — Project Rules

Academic capstone project. This file records the **permanent, standing rules**
for how work on this repository must be done. These rules apply across every
session and every week of the project unless the user explicitly changes them.

## What this project is

An AIOps platform that monitors a microservices payment application, detects
anomalies, performs RAG-augmented root cause analysis with a local LLM,
proposes remediation, validates it with deterministic safety rules, requires
mandatory human approval, executes approved actions against Kubernetes, and
records outcomes for future incident retrieval. A single-agent LLM baseline
is built separately for comparison, and both are evaluated on a held-out
incident set.

## Intended final structure

```
/
├── auth-service/
├── payment-service/
├── ledger-service/
├── notification-service/
├── ai-orchestration/
├── dataset-tools/
├── docs/
├── k8s/
├── docker-compose.yml
├── README.md
└── CLAUDE.md
```

Not all components exist yet — they are built incrementally per the weekly
roadmap below.

## Weekly roadmap

1. Auth + Payment services, JWT, Correlation IDs
2. Ledger + Notification, PostgreSQL, full synchronous chain
3. Docker, Docker Compose, Kubernetes, Minikube
4. Actuator, Prometheus, fault injection
5. Automated telemetry capture
6. Incident dataset, Memory/Evaluation split, ChromaDB
7. LangGraph, Isolation Forest, Ollama
8. RCA Agent, RAG, Remediation Agent
9. Safety Validator, mandatory Human Approval, Streamlit
10. Kubernetes execution, feedback write-back, full pipeline
11. Single-Agent baseline
12. Full evaluation
13–15. Paper, results, documentation, demo

## Permanent development rules

1. Implement incrementally.
2. Never implement future weeks unless explicitly requested.
3. Inspect existing code before modifying it.
4. Preserve working functionality.
5. Do not unnecessarily rewrite the architecture.
6. Do not hardcode secrets in source code.
7. Use configuration properties and environment variables.
8. Keep services independently deployable.
9. Use clean, understandable code.
10. Prefer simple solutions over unnecessary abstraction.
11. Add meaningful logging.
12. Do not expose raw stack traces through APIs.
13. Build after significant changes.
14. Run tests when available.
15. Fix errors caused by your changes.
16. Never claim something was tested if it was not actually tested.
17. Clearly distinguish verified behavior from unverified instructions.
18. Fault injection must be disabled by default.
19. Fault injection must be resettable or recoverable.
20. Safety validation must remain deterministic.
21. Human approval must remain mandatory.
22. Never allow Evaluation Set incidents into RAG memory.
23. Maintain reproducibility for academic evaluation.
24. Do not silently change project requirements.
25. Do not automatically push code to GitHub.
26. Do not implement anything outside the currently requested week.

## Correlation ID convention

Every microservice supports `X-Correlation-Id`:

1. Read `X-Correlation-Id` from incoming requests.
2. Generate a UUID if missing.
3. Store it in SLF4J MDC under the key `correlationId`.
4. Include it in logs.
5. Return it in the HTTP response.
6. Propagate it to downstream service calls.
7. Remove it from MDC in a `finally` block.

## Fault injection (implemented from Week 4 onward)

Four controlled faults, each disabled by default and resettable:

1. **Auth key error** — Auth Service JWT key intentionally changed → JWT
   validation fails.
2. **Memory leak** — Payment Service intentionally retains memory → JVM
   memory usage increases, may eventually crash.
3. **DB connection pool exhaustion** — Ledger Service deliberately holds
   DB connections (HikariCP `maximum-pool-size: 10`) → new transactions
   eventually fail/time out.
4. **Notification latency** — Notification Service adds ~6s delay →
   Payment Service (which waits synchronously) experiences latency/timeout.
   Symptom appears in Payment Service; actual root cause is Notification
   Service — the RCA system must eventually identify Notification as root
   cause.

## Dataset rule (critical)

Controlled fault injection generates ~60–80 incidents, split into:

- **Memory set** (~20 incidents) — used for RAG.
- **Evaluation set** (~40–60 incidents) — used only for evaluation.

**Evaluation incidents must never enter RAG memory.** This is a hard
constraint on every week that touches the dataset or ChromaDB.

## Local LLM

The project uses a self-hosted local LLM via Ollama (initial candidate:
`llama3.1:8b`). Do not design the system around OpenAI/Anthropic APIs.

## Current status

Week 4 complete (2026-08-27): Actuator + Prometheus + all four controlled
faults implemented and verified on native processes, Docker Compose, and
real Kubernetes. All four services expose `/actuator/{health,info,metrics,
prometheus}` (`spring-boot-starter-actuator` + `micrometer-registry-
prometheus`), plus `/actuator/health/{liveness,readiness}` used by new
Kubernetes readiness/liveness probes on all four app Deployments (generous
delays — 15s/30s — chosen from observed real startup times, no restart
loops seen). Payment Service's outbound `WebClient` calls now use Spring
Boot's auto-configured, metrics-instrumented `WebClient.Builder` instead of
the static one, so outbound calls to auth/ledger/notification show up as
`http_client_requests_seconds` too. Prometheus itself runs in-cluster
(`k8s/prometheus-config.yaml` + `k8s/prometheus.yaml`, ClusterIP only,
never exposed publicly) scraping all four services; all four targets
confirmed `up`. Docker Compose healthchecks added using `curl` (already
present in the `eclipse-temurin:17-jre-jammy` base image — no Dockerfile
change needed).

Four controlled faults, each disabled by default, resettable, and
demonstrated live end-to-end (native + Kubernetes + Compose): (1)
**auth-key-error** (`POST /inject-auth-key-error` / `/reset-auth-key` on
auth-service) — a new `JwtSigningKeyProvider` holds a mutable active key
(never a second hardcoded secret) that `JwtService` reads on every
sign/verify; injecting swaps in a random 512-bit key so old tokens fail
with a clean signature mismatch. (2) **memory-leak** (`/inject-memory-leak`
/ `/reset-memory-leak` on payment-service) — a `@Scheduled` task retains
byte[] chunks up to a hard-capped `max-total-bytes` (default 200MB); reset
clears the list for GC. (3) **db-pool-exhaustion**
(`/inject-db-lock` / `/reset-db-lock` on ledger-service) — holds raw JDBC
connections from the existing `DataSource` (bypassing JPA entirely),
clamped to `maximumPoolSize - 1` so it can never fully exhaust the pool or
block its own reset; verified via HikariCP metrics showing real contention
(111 pending threads under a 300-request burst) rather than a real DB
deadlock. (4) **notification-latency** (`/inject-latency` /
`/reset-latency` on notification-service) — sleeps before responding;
the *existing* `app.notification-service.timeout-ms` (5000ms, from Week 2)
was already sufficient to produce the intended Payment-side timeout
against the fault's default 6000ms delay, so no new timeout code was
needed on the Payment side. Confirmed live: ledger transaction stays
committed even when the notification call times out.

Found and fixed one non-trivial infra bug this week: `minikube image load`
can silently keep a stale image under an existing tag — confirmed by
comparing image digests between Colima's daemon and Minikube's internal
daemon. Fix going forward: scale affected deployments to 0, force-remove
the stale tag from Minikube's daemon (`minikube ssh -- docker rmi -f
<image>`), reload, then scale back up — applied successfully for all four
services' Week 4 rebuild. Waiting for explicit instruction to begin Week 5
(automated telemetry capture).
