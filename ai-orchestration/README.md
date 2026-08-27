# Week 7 — AI Intelligence Foundation

Anomaly detection (Isolation Forest), a local LLM interpretation step (Ollama), and a LangGraph
workflow that ties them together - the foundation Week 8's RCA and remediation agents build on.

## Architecture

```
ai-orchestration/
├── src/ai_orchestration/
│   ├── config.py              paths, env vars, per-service feature schema, IF hyperparameters
│   ├── anomaly/
│   │   ├── models.py           FeatureVector, ModelMetadata, AnomalyResult dataclasses
│   │   ├── feature_extractor.py  raw telemetry -> FeatureVector; Memory-eligible baseline selection
│   │   ├── detector.py          AnomalyDetector: train/save/load/score, one per service
│   │   └── train.py             CLI: trains + persists all 4 services' detectors
│   ├── llm/
│   │   ├── models.py            AnomalyInterpretation dataclass
│   │   ├── ollama_client.py      thin REST client (no SDK), availability check, timeouts
│   │   ├── prompts.py            builds the evidence-only interpretation prompt
│   │   └── interpret.py           orchestrates client+prompt, graceful degradation
│   └── graph/
│       ├── state.py              WorkflowState (explicit TypedDict)
│       └── workflow.py            the LangGraph itself - see "The graph" below
├── tests/                      44 pytest tests (see "Testing")
├── models/                     trained IsolationForest + metadata per service (gitignored, generated)
├── requirements.txt
└── pyproject.toml
```

Reuses Week 5/6 code directly (`telemetry`, `dataset_tools`) via the same `sys.path` insertion
pattern `dataset-tools/src/dataset_tools/generate.py` already established - no duplication of
JSONL loading or phase-reconstruction logic.

## Feature schema

One ordered feature list **per service**, not one shared list - some curated telemetry metrics are
only meaningful for specific services (verified against real telemetry, same standard
`dataset-tools/config.py`'s `FAULT_SERVICE_MAP` uses):

| feature | auth-service | payment-service | ledger-service | notification-service |
|---|:---:|:---:|:---:|:---:|
| jvm_memory_used/committed/max_bytes | ✓ | ✓ | ✓ | ✓ |
| http_server_requests_count/error_count/avg_duration_ms | ✓ | ✓ | ✓ | ✓ |
| process_cpu_usage / system_cpu_usage | ✓ | ✓ | ✓ | ✓ |
| http_client_requests_count/avg_duration_ms | | ✓ | | |
| hikaricp_connections_active/idle/pending/acquire_seconds_avg | | | ✓ | |

`http_client_*` only applies to payment-service (the only service that makes outbound calls);
`hikaricp_*` only applies to ledger-service (the only service with a DB connection pool) - see
`telemetry/collector.py`'s `parse_metrics()` comments. Training one Isolation Forest per service
on only its own applicable features avoids treating "always None for this service" as a
signal, and lets each service have its own baseline distribution (JVM baseline ranges differ
significantly by service).

`extract_features(record)` returns `None` (never a fabricated/imputed vector) when the service is
unknown, metrics collection failed that cycle, or any of that service's *own applicable* metrics
is missing - handled identically at training and inference time, so the two can never disagree
about what counts as valid.

## Training data: Memory-eligible baseline telemetry only

**Never trains on Evaluation-set incidents; the separation is enforced in code, not just
documented** (same shape as `dataset-tools/chroma_store.py`'s ChromaDB leakage prevention):

- `feature_extractor.load_memory_eligible_baseline_records()` reads incidents from **only**
  `dataset-tools/data/memory/memory_incidents.jsonl` - the Evaluation file is never opened by
  anything that feeds training, and there is no `evaluation_incidents` parameter on this function
  at all (impossible to point it there by construction).
- Only **real** incidents' `experiment_id` are used to find eligible raw experiments (synthetic
  incidents have no raw telemetry behind them - they're generated dicts, see
  `dataset-tools/synthetic_model.py` - so they can never contribute a training row).
- Within an eligible experiment, only **NORMAL and RECOVERY** phase telemetry is used (both
  represent non-faulty system behavior; RECOVERY = fault already reset).
- See `tests/test_baseline_selection.py` for the regression tests proving this (only
  Memory-associated experiments contribute records; synthetic incidents contribute none;
  experiments absent from Memory contribute nothing; FAULT_ACTIVE-phase telemetry is excluded
  even from otherwise-eligible experiments).

Right now this yields **42-45 training samples per service**, from the 4 real experiments that
happen to have landed in the Memory set (out of 16 real experiments total, 20/68 incidents in
Memory) - see "Known limitations" below for what this small sample size means in practice.

## Model training and persistence

```bash
cd ai-orchestration
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .

python -m ai_orchestration.anomaly.train
```

One `IsolationForest` per service, saved to `models/<service>/model.joblib` +
`models/<service>/metadata.json`. Metadata records: feature schema version, ordered feature names,
every hyperparameter used, training timestamp, sample count, and the exact list of source
experiment IDs (an audit trail - see `ModelMetadata`).

**Reproducible configuration** - all env-overridable, defaults in `config.py`:

| variable | default | meaning |
|---|---|---|
| `AI_ORCHESTRATION_IF_N_ESTIMATORS` | `100` | Isolation Forest tree count |
| `AI_ORCHESTRATION_IF_CONTAMINATION` | `0.1` | expected anomaly fraction (see below for why not `"auto"`) |
| `AI_ORCHESTRATION_IF_RANDOM_STATE` | `42` | reproducibility, matches the project's existing seed convention |
| `AI_ORCHESTRATION_IF_MAX_SAMPLES` | `auto` | sklearn's per-tree subsample size |
| `AI_ORCHESTRATION_ANOMALY_THRESHOLD` | `0.0` | configurable decision boundary on top of the trained model, without retraining |

**Feature-schema compatibility is checked, not assumed**: `AnomalyDetector.load()` compares the
persisted model's `feature_schema_version` + `feature_names` against the currently configured
schema and raises `FeatureSchemaMismatchError` if they differ - a schema change (e.g. a new metric
added to a service in a future week) makes old models refuse to load rather than silently
misaligning feature columns and producing a meaningless prediction.

## Inference

`AnomalyDetector.score(feature_vector)` returns an `AnomalyResult` with (at minimum, per Week 7's
spec): `timestamp`, `service`, `anomaly_score`, `is_anomaly`, `relevant_feature_values` (the actual
metric values that produced the score), and `model_version`/`feature_schema_version`. `status` is
one of `"scored"`, `"insufficient_data"` (no valid feature vector could be built), or `"no_model"`
(no trained detector for that service) - the caller always gets a structured result, never an
exception, for these expected non-error conditions.

`anomaly_score = -decision_function(x)` (sklearn's own convention is inverted so *higher* here
means *more anomalous*, matching the intuitive meaning of the field name); `is_anomaly = score >
threshold`, threshold configurable per above.

## Ollama integration

No cloud API, no SDK - `llm/ollama_client.py` talks to Ollama's local REST API
(`http://localhost:11434` by default) directly via `requests`.

| variable | default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_MODEL` | `llama3.2:1b` (see below) |
| `OLLAMA_TIMEOUT_SECONDS` | `30` |

**Model choice**: CLAUDE.md names `llama3.1:8b` as the project's initial candidate local model.
This development machine had only ~8.8GB free disk at the start of Week 7, and `llama3.1:8b`'s
model blob alone is ~4.7GB - risky to pull outright. `llama3.2:1b` (1.3GB) was installed and used
for all live verification instead, and is the configured default. To switch to the originally
named model once disk space allows:
```bash
ollama pull llama3.1:8b
export OLLAMA_MODEL=llama3.1:8b
```
No other code change is needed - the model name is the only thing that changes.

**Graceful degradation, not a hard dependency**: `OllamaClient.is_available()` (GET `/api/tags`,
3s timeout) is checked before every interpretation attempt; `generate()` raises
`OllamaUnavailableError` on any connection error or timeout, which `interpret.py` catches and
turns into a structured `AnomalyInterpretation(status="llm_unavailable", ...)` - never an
exception that would crash the graph. Malformed/incomplete JSON from the model is handled the same
way (`status="llm_error"`). **The LLM never executes anything** - Week 7 only ever produces a
structured interpretation; no remediation action is taken based on it (per the explicit Week 7
scope boundary - that's Week 8+).

**Only real evidence goes into the prompt** (`llm/prompts.py`): the exact `service`, `timestamp`,
`anomaly_score`, `threshold`, and `relevant_feature_values` from the `AnomalyResult` that already
went through the Isolation Forest - nothing invented, and the prompt explicitly instructs the
model not to reference any metric not listed.

### Setup used for live verification

```bash
brew install ollama
ollama serve &                 # or: brew services start ollama
ollama pull llama3.2:1b
```

## The graph

```
raw telemetry record
        |
  extract_features
        |
  detect_anomaly
        |
    (decision)
   /          \
normal       anomaly
  |             |
  |        interpret (Ollama)
   \           /
     finalize
        |
       END
```

Built with real LangGraph (`langgraph.graph.StateGraph`), explicit typed state
(`graph/state.py`'s `WorkflowState`), and a real conditional edge
(`add_conditional_edges` on `_route_after_detection`) - not a fake linear stand-in. **The LLM is
only ever invoked on the anomaly branch** - a normal reading never calls Ollama (verified in
`tests/test_workflow.py::test_workflow_normal_path_never_calls_llm`, which asserts the mock client
is never called).

`build_graph(detectors, ollama_client)` takes both dependencies as parameters rather than
constructing them internally - models are loaded once (`load_all_detectors()`) and reused across
every `graph.invoke()` call, and tests can inject fakes/mocks for both.

The final `result` dict (present on every path, not just the anomaly one) contains:
`correlation_id`, `incident_id` (caller-supplied, for Week 8 to correlate against), `service`,
`timestamp`, `decision`, `telemetry_evidence` (the raw metrics/fault/collection_error), the full
`anomaly_result`, `llm_interpretation` (`None` on the normal path), and `limitations` (plain-text
notes for any degraded condition - insufficient data, no model, LLM unavailable/error).

## How Week 7 feeds Week 8

- `build_graph()` + `load_all_detectors()` are the entry points Week 8's orchestrator calls per
  telemetry record; the `result` dict is Week 8's input.
- The graph is deliberately not more than this. Week 8 adds nodes **after** the `anomaly` branch:

  ```
  ... detect_anomaly -> (anomaly) -> RCA Agent -> RAG Retrieval -> Remediation Proposal -> ...
  ```

  It can do this by adding new nodes and re-wiring the edge currently going `interpret -> finalize`
  to `interpret -> rca_agent -> rag_retrieval -> remediation_proposal -> finalize`, without
  touching `extract_features`, `detect_anomaly`, or the routing logic upstream of it.
- RAG retrieval already has its data ready: `dataset-tools/chroma`'s `incident_memory` collection
  (Memory-set incidents only, built in Week 6) is what Week 8's RAG Retrieval node will query -
  Week 7 doesn't touch or duplicate it, keeping ChromaDB access exactly where Week 6 put it.
- `incident_id` is already threaded through the whole graph's state and final result, ready for
  Week 8 to attach retrieved incidents and a remediation proposal to.

## Testing

```bash
cd ai-orchestration && source .venv/bin/activate && python -m pytest tests/ -v
```

44 tests, mocking Ollama (`responses` for the HTTP client, `unittest.mock.MagicMock` for the
higher-level `interpret_anomaly()`/graph tests) and requiring no running Kubernetes cluster,
payment system, or Ollama server:

- `test_feature_extractor.py` (8) - feature extraction; missing/non-applicable metrics never
  treated as errors.
- `test_baseline_selection.py` (4) - Memory/Evaluation training-data separation.
- `test_detector.py` (10) - training, inference, save/load round-trip, feature-schema mismatch
  detection, normal-telemetry scoring, extreme/fault-like-telemetry scoring.
- `test_ollama_client.py` (10) + `test_interpret.py` (7) - availability, timeouts, connection
  errors, malformed/incomplete JSON, graceful degradation end-to-end.
- `test_workflow.py` (5) - LangGraph normal path (never calls the LLM), anomaly path (calls the
  LLM, includes its interpretation), Ollama-unavailable-on-the-anomaly-path degradation,
  insufficient-data path, no-model path.

Also re-run as part of Week 7 verification: all 19 Week 5 telemetry tests, all 42 Week 6
dataset-tools tests, all 47 Java tests - all still pass unmodified.

## Live verification performed

Against the real Kubernetes deployment (Colima + Minikube) and a real local Ollama server:

1. Trained all 4 services' Isolation Forests on real Memory-eligible telemetry (42-45 samples
   each) - `python -m ai_orchestration.anomaly.train`.
2. Installed Ollama via Homebrew, pulled `llama3.2:1b` (1.3GB - chosen for this machine's ~8.8GB
   free disk; see "Ollama integration" above), started the server, confirmed
   `OllamaClient.is_available()` and `.has_model()` both return `True`.
3. Ran a full `graph.invoke()` end-to-end against a deliberately extreme synthetic record with a
   live Ollama server: correctly routed to the anomaly branch, correctly called Ollama (7.3s
   round-trip), got back a structured, schema-valid `AnomalyInterpretation` (`status="interpreted"`,
   confidence self-reported as `"low"` by the small model - a reasonable, honest self-assessment
   given the limited context it was given, not a wrong answer).
4. Confirmed all 4 faults inactive, ran a **new, live** memory-leak experiment
   (baseline=15s/fault=20s/recovery=15s) against the real system, collected fresh telemetry, and
   scored every record through the trained payment-service detector: anomaly scores trended upward
   as `jvm_memory_used_bytes` climbed through the fault window (23MB→108MB), with the later
   fault-active samples correctly flagged `is_anomaly=True`, and flagging correctly persisted into
   the RECOVERY phase's early samples too (memory stays elevated immediately after reset - matches
   Week 5/6's documented "reset stops new allocation but doesn't force immediate GC" behavior).
5. Confirmed the full payment flow (login → payment → ledger debit → notification) still works
   end-to-end via a live HTTP call, and all 4 faults are inactive after testing.

## Known limitations

- **Training sample size is small** (42-45 real samples per service, from only the 4 real
  experiments currently in the Memory set) - this is a direct, disclosed consequence of Week 6's
  dataset still being early-stage (68 total incidents, 16 real). Live verification against the
  real dataset showed detection is **reliable for clearly extreme/large deviations** (verified in
  both the automated tests and the live Ollama end-to-end check) but **inconsistent for some real,
  moderate fault instances** - e.g. scoring the actual recorded FAULT_ACTIVE windows of the
  Evaluation-set memory-leak and db-lock experiments did not always separate cleanly from NORMAL
  windows at the default threshold. This should improve as more real experiments are run in future
  weeks and the Memory-eligible training set grows.
- **`http_server_requests_count`/`error_count` are cumulative Prometheus counters**, not
  per-interval rates - their absolute value reflects the whole service session's history, not just
  the current window, which makes them a weaker anomaly-detection feature than a delta/rate would
  be (live investigation during this week directly confirmed this: an error counter observed at
  value 5 in one experiment was later found at value 0 in a subsequent experiment despite the
  request counter continuing to climb, indicating the underlying Prometheus/Micrometer counter
  series had reset independently of the request counter - most likely due to per-tag meter
  eviction after inactivity, not a service restart, since Kubernetes reported 0 pod restarts
  throughout). Converting these to rate-of-change features is a reasonable direction for a future
  week, not implemented here (out of Week 7's scope).
- `ISOLATION_FOREST_CONTAMINATION`'s default was changed from sklearn's `"auto"` to an explicit
  `0.1` after live testing showed `"auto"`'s fixed `-0.5` score offset - tuned for much larger
  datasets - flagged nearly all real telemetry (both normal and fault) as anomalous on this small
  dataset. `0.1` is a more conventional, defensible default for a small-sample setting, not a
  value tuned to make any specific fault example pass.
- The graph currently processes one telemetry record at a time (matches how Week 8 will likely
  call it - once per anomaly candidate) rather than a batch/stream - batching wasn't needed for
  this week's scope.
