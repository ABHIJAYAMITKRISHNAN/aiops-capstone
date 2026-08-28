# Weeks 7-8 — AI Intelligence Foundation, RCA, RAG, and Remediation Proposals

Week 7: anomaly detection (Isolation Forest), a local LLM interpretation step (Ollama), and a
LangGraph workflow. Week 8 extends that same workflow with an RCA agent, RAG retrieval against
Week 6's ChromaDB Memory collection, and a deterministic remediation-proposal generator - Week 8
**never executes anything**; see "Week 8 architecture" below.

## Architecture

```
ai-orchestration/
├── src/ai_orchestration/
│   ├── config.py              paths, env vars, per-service feature schema, IF hyperparameters
│   ├── anomaly/                (Week 7)
│   │   ├── models.py           FeatureVector, ModelMetadata, AnomalyResult dataclasses
│   │   ├── feature_extractor.py  raw telemetry -> FeatureVector; Memory-eligible baseline selection
│   │   ├── detector.py          AnomalyDetector: train/save/load/score, one per service
│   │   └── train.py             CLI: trains + persists all 4 services' detectors
│   ├── llm/                    (Week 7, extended Week 8)
│   │   ├── models.py            AnomalyInterpretation dataclass
│   │   ├── ollama_client.py      thin REST client (no SDK), availability check, timeouts
│   │   ├── prompts.py            interpretation prompt (Week 7) + RCA narrative prompt (Week 8)
│   │   └── interpret.py           orchestrates client+prompt, graceful degradation
│   ├── rag/                    (Week 8) - RAG retrieval against Week 6's ChromaDB
│   │   ├── models.py            RetrievedIncident, RetrievalResult (Pydantic)
│   │   └── retriever.py          query construction + dataset_tools.chroma_store.query_similar()
│   ├── rca/                    (Week 8) - root cause analysis
│   │   ├── models.py            MetricAnomaly, RCAEvidence, RootCauseAnalysis (Pydantic)
│   │   ├── signatures.py         deterministic fault-signature matching (documented thresholds)
│   │   └── analyzer.py           ties signatures + RAG + optional LLM narrative together
│   ├── remediation/            (Week 8) - proposals only, never executes
│   │   ├── models.py            RemediationProposal (Pydantic)
│   │   └── proposer.py           deterministic fault_type -> action mapping, no LLM involved
│   └── graph/
│       ├── state.py              WorkflowState (explicit TypedDict)
│       └── workflow.py            the LangGraph itself - see "The graph" below
├── tests/                      90 pytest tests (see "Testing")
├── models/                     trained IsolationForest + metadata per service (gitignored, generated)
├── requirements.txt
└── pyproject.toml
```

Reuses Week 5/6 code directly (`telemetry`, `dataset_tools`) via the same `sys.path` insertion
pattern `dataset-tools/src/dataset_tools/generate.py` already established - no duplication of
JSONL loading, phase-reconstruction, or ChromaDB setup logic. `rag/retriever.py` calls
`dataset_tools.chroma_store.query_similar()` directly rather than opening a second collection.

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
  |             |
  |     retrieve_similar_incidents (ChromaDB, Memory-set only)
  |             |
  |     root_cause_analysis (deterministic signature match + RAG cross-check + optional LLM narrative)
  |             |
  |     propose_remediation (deterministic - no LLM, never executes)
   \           /
     finalize
        |
       END
```

Built with real LangGraph (`langgraph.graph.StateGraph`), explicit typed state
(`graph/state.py`'s `WorkflowState`), and a real conditional edge
(`add_conditional_edges` on `_route_after_detection`) - not a fake linear stand-in. **The LLM is
only ever invoked on the anomaly branch, and RAG/RCA/remediation only ever run on the anomaly
branch too** - a normal reading never calls Ollama, never queries ChromaDB, and never produces an
RCA or remediation proposal (verified in `tests/test_workflow.py::test_workflow_normal_path_never_calls_llm`,
which asserts the mock LLM client is never called *and* that a `retrieve_similar_incidents` spy
that raises on any call is never triggered).

`build_graph(detectors, ollama_client)` takes both dependencies as parameters rather than
constructing them internally - models are loaded once (`load_all_detectors()`) and reused across
every `graph.invoke()` call, and tests can inject fakes/mocks for both.

The final `result` dict (present on every path, not just the anomaly one) contains:
`correlation_id`, `incident_id`, `service`, `timestamp`, `decision`, `telemetry_evidence` (the raw
metrics/fault/collection_error), the full `anomaly_result`, `llm_interpretation` (Week 7),
`retrieval`, `root_cause_analysis`, `remediation_proposal` (Week 8 - all three `None` on the
normal/insufficient_data/no_model paths), and `limitations` (plain-text notes for any degraded
condition across the whole pipeline).

## Week 8 architecture: RCA, RAG, and remediation proposals

### RCA design (`rca/`)

`RootCauseAnalysis` (Pydantic, `rca/models.py`) is never solely reliant on free-form LLM text.
Precedence, deliberately in this order:

1. **Deterministic fault-signature matching** (`rca/signatures.py`) always runs first and always
   wins when it matches. Each of the four known faults has one documented "primary metric" and
   threshold (reusing `dataset_tools.incidents._primary_metric_key` - Week 6's own mapping, not
   re-derived), with every threshold traceable to a real, documented value (`OBSERVED_BASELINE_RANGES`
   for JVM memory, empirically-verified real baselines of 0 for HikariCP/error counts, a value well
   below the real `client_timeout_ms` for notification latency). This is exactly what distinguishes
   symptom from root cause for the two cross-service faults: `auth-key-error`'s and
   `notification-latency`'s signatures are both keyed to **payment-service's own telemetry**
   (where the symptom is measured) but resolve to **auth-service**/**notification-service** as
   `suspected_root_cause_service` via `dataset_tools.config.FAULT_SERVICE_MAP` (reused, not
   duplicated) - see `tests/test_signatures.py` and `tests/test_rca_analyzer.py` for the explicit
   symptom-vs-root-cause assertions.
2. **RAG-retrieved incidents can only raise/lower confidence, never override step 1.** If
   retrieved incidents' `fault_type` metadata agrees with the signature match, confidence rises to
   `"high"`. If they disagree, the signature's conclusion is kept and the disagreement is recorded
   in `evidence_summary` (`determination_method="metric_signature+rag_disagreement"`) - "the agent
   must not blindly trust retrieved incidents" per the Week 8 spec. When no signature matched at
   all, the single closest retrieved incident is used as a *low-confidence* suggestion instead
   (`"rag_only"`); with neither a signature match nor useful retrieval, `suspected_fault_type` is
   `None` and the root cause defaults to the symptom-visible service itself
   (`"fallback_unknown"`) - never a fabricated guess.
3. **The LLM only narrates the conclusion already reached by 1-2** - it is never asked to
   determine the root cause, and its response schema has no field for one (see
   `llm/prompts.py::build_rca_reasoning_prompt`, which explicitly instructs "you are NOT being
   asked to determine the root cause yourself"). Its two-key JSON response
   (`observed_evidence`/`inference`) implements the "OBSERVED EVIDENCE / INFERENCE" split the spec
   asks for; there is no `recommendation` key at all, because remediation is never LLM-authored
   (see below). Degrades identically to Week 7's `interpret_anomaly()` - unavailable/timeout/
   malformed JSON all just leave `llm_reasoning=None`, never an exception, and never change the
   deterministic conclusion (verified: `test_llm_reasoning_is_none_when_ollama_unavailable`
   explicitly asserts `suspected_root_cause_service` is unaffected).

### RAG design (`rag/`)

`rag/retriever.py` calls `dataset_tools.chroma_store.query_similar()` directly - no second
ChromaDB collection, no re-embedding. `build_query_text()` builds a natural-language-style query
(deliberately similar in shape to the postmortem prose actually indexed) from the anomaly's
service, its most notable metric values, and Week 7's `llm_interpretation.abnormal_summary` when
available. Results become typed `RetrievedIncident`s (incident ID, distance, fault type, root
cause/symptom service, severity, data source, and a postmortem excerpt) inside a `RetrievalResult`
with an explicit `status` (`"retrieved"` / `"empty"` / `"collection_unavailable"`) - never a bare
exception reaching the graph.

### Remediation design (`remediation/`)

`remediation/proposer.py` is **100% deterministic Python - no LLM call at all**. This is
deliberate: the project's own rules already say to prefer deterministic structured data over
free-form AI output, and remediation is exactly the place where that matters most. A
`RemediationProposal` (Pydantic, `remediation/models.py`) is returned for every anomaly, with
`requires_human_approval: Literal[True] = True` - a type-level guarantee (Pydantic rejects any
attempt to construct one with `False`), citing CLAUDE.md's permanent rule 21. **Nothing in this
module calls Kubernetes, a fault-injection endpoint, or any other side-effecting API** - a
`RemediationProposal` is inert data (`tests/test_remediation_proposer.py::test_proposal_has_no_executable_side_effects`
checks it exposes no `execute`/`run`/`apply`/`invoke_*`-named attribute at all). Fault-name lookup
templates exist for the four known faults, but are only used when the RCA's own `confidence` is at
least `"medium"` - a `"low"`-confidence RCA (regardless of which `fault_type` was merely suspected)
always falls back to a generic, low-risk `"investigate_manually"` proposal instead, per "do not
hardcode the final answer solely based on fault names."

## How Week 8 feeds Week 9

- `build_graph()` + `load_all_detectors()` are still the entry points; the `result` dict (now
  including `retrieval`, `root_cause_analysis`, `remediation_proposal`) is Week 9's input.
- Week 9 adds mandatory human approval and Streamlit around the `remediation_proposal` this graph
  already produces - nothing here needs to change for that; `requires_human_approval` is already
  always `True` at the type level, so Week 9's approval gate has a guaranteed non-optional signal
  to gate on.
- `incident_id` and `correlation_id` are threaded through every node's state, ready for Week 9/10
  to write investigation outcomes back for future incident retrieval (CLAUDE.md's roadmap item for
  Week 10 - "feedback write-back").
- `retrieval.incidents` already carries each historical incident's own outcome fields where
  present in the incident schema, ready for a future week to compare "did the same remediation
  work last time" without any retrieval-layer changes.

## Running a local investigation

Requires: a trained model per service (`python -m ai_orchestration.anomaly.train`), a built
ChromaDB Memory collection (`cd dataset-tools && python -m dataset_tools.chroma_store`), and
optionally a running Ollama server (`ollama serve`, model pulled) - the pipeline still produces a
full, deterministic result without Ollama, just with `llm_interpretation`/`llm_reasoning` set to
`None`/`"llm_unavailable"`.

```python
from ai_orchestration.graph.workflow import build_graph, load_all_detectors
from ai_orchestration.llm.ollama_client import OllamaClient

graph = build_graph(load_all_detectors(), OllamaClient())

raw_record = {...}  # one record exactly as telemetry/collector.py's collect_service() produces
final_state = graph.invoke({"raw_record": raw_record, "incident_id": None})
print(final_state["result"])  # decision, anomaly_result, retrieval, root_cause_analysis, remediation_proposal
```

## Testing

```bash
cd ai-orchestration && source .venv/bin/activate && python -m pytest tests/ -v
```

90 tests (44 from Week 7 + 46 new this week), mocking Ollama (`responses` for the HTTP client,
`unittest.mock.MagicMock` for higher-level tests) and using a real, isolated local ChromaDB
(`tmp_path`-scoped, same pattern as `dataset-tools/tests/test_chroma_store.py`) for RAG tests -
never the project's real Memory collection, and requiring no running Kubernetes cluster, payment
system, or Ollama server:

- `test_feature_extractor.py` (8), `test_baseline_selection.py` (4), `test_detector.py` (10),
  `test_ollama_client.py` (10), `test_interpret.py` (7) - unchanged from Week 7.
- `test_signatures.py` (9, new) - each of the four faults' signature match, including the two
  symptom-vs-root-cause cross-service cases, ranking multiple simultaneous matches, and documented
  baseline references.
- `test_rca_analyzer.py` (12, new) - all four faults' end-to-end RCA identification, RAG
  agreement/disagreement behavior, `rag_only`/`fallback_unknown` fallback, and LLM
  narrative graceful degradation.
- `test_rag_retriever.py` (9, new) - real isolated-ChromaDB retrieval, Evaluation-incident
  exclusion (both "never built into the collection" and "even if a match somehow returned one,
  filtered before reaching RCA"), empty/no-result, and malformed-match handling.
- `test_remediation_proposer.py` (13, new) - a proposal for each of the four faults, the
  low-confidence fallback, Pydantic validation of risk/action-category/`requires_human_approval`,
  and the no-executable-attributes check.
- `test_workflow.py` (7, 2 new + 5 extended) - normal path still reaches none of Week 8's new
  nodes; anomaly path reaches RCA, retrieval, and remediation; Ollama-unavailable degrades the
  whole extended pipeline gracefully (RCA/remediation still populate, just without a narrative);
  RAG agreement raises RCA confidence to `"high"` end-to-end through the compiled graph.

Also re-run as part of Week 8 verification: all 19 Week 5 telemetry tests, all 42 Week 6
dataset-tools tests, all 47 Java tests - all still pass unmodified.

## Live verification performed

Against the real Kubernetes deployment (Colima + Minikube) and a real local Ollama server.

**Week 7** (repeated this week to confirm no regression): trained all 4 services' Isolation
Forests (`python -m ai_orchestration.anomaly.train`); confirmed Ollama + `llama3.2:1b` available;
ran a full `graph.invoke()` against a deliberately extreme record with a live Ollama server
(anomaly correctly flagged, LLM interpretation returned); triggered a live memory-leak experiment
and confirmed anomaly scores tracked real memory growth.

**Week 8, this week:**

1. Confirmed Kubernetes healthy (6/6 pods) and all four faults inactive before starting.
2. Ran a **brand-new live `notification-latency` experiment**. Among its FAULT_ACTIVE-phase
   telemetry, one record (`http_client_requests_avg_duration_ms=74.5ms`) was flagged anomalous by
   the trained detector; running it through the full graph correctly reached `interpret` →
   `retrieve_similar_incidents` → `root_cause_analysis` → `propose_remediation`. **This run
   surfaced a genuine, honestly-reported finding**: the RCA's signature match picked
   `"auth-key-error"` instead of `"notification-latency"`, because `http_server_requests_error_count`
   had accumulated to `22` over this long-running session (the same cumulative-counter behavior
   Week 7 already documented) - `22` cleared the auth-key-error threshold by a much larger margin
   (44x) than this record's `http_client_requests_avg_duration_ms=74.5ms` cleared
   notification-latency's threshold (it didn't clear it at all - 74.5 is below the 500ms
   threshold). RAG retrieval correctly found real/synthetic `memory-leak` Memory incidents
   (semantically close given the JVM metrics in the query), and the RCA's own logic correctly
   recognized the disagreement and did *not* blindly follow retrieval
   (`determination_method="metric_signature+rag_disagreement"`) - but the underlying signature
   match itself was still wrong, for the reason above. See "Known limitations" for what this means
   and the reasonable fix direction (not implemented this week).
3. Ran a **brand-new live `db-lock` experiment** (a clean resource-fault case, since
   `hikaricp_connections_active` is a gauge, not a cumulative counter). A FAULT_ACTIVE record
   (`hikaricp_connections_active=9.0`) was flagged anomalous; the full pipeline produced a
   **correct, clean result end-to-end**: `suspected_fault_type="db-lock"`,
   `suspected_root_cause_service="ledger-service"` (matches `symptom_service` - both correctly
   ledger-service, a same-service fault), 3/3 retrieved incidents agreed
   (`determination_method="metric_signature+rag_agreement"`, `confidence="high"`), and the
   remediation proposal correctly targeted `ledger-service` with `action_category="release_resources"`,
   `requires_human_approval=True`. The LLM's narrative text was imperfect in places (a 1B-parameter
   model summarizing "9.0" as "5 raw JDBC connections" in one sentence) - an honest limitation of
   using a very small local model for narration, not a pipeline defect, since the narrative field
   never feeds back into the deterministic conclusion.
4. Verified (both experiments): every retrieved incident ID (`inc-0037`, `inc-0042`, `inc-0044`,
   `inc-0022`, `inc-0032`, `inc-0029`) is present in `memory_incidents.jsonl` and absent from
   `evaluation_incidents.jsonl` - no Evaluation incident was ever retrieved or used as context.
5. Confirmed no remediation action was executed: `RemediationProposal` objects were only ever
   constructed and printed/inspected; the only fault-injection API calls made during this
   verification were the experiment orchestrator's own scripted inject/reset calls (Week 5's
   `telemetry.experiment`), not anything triggered by a proposal.
6. Confirmed all four faults inactive after testing, and the full payment flow (login → payment →
   ledger debit → notification) still works end-to-end via a live HTTP call.

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
- The graph currently processes one telemetry record at a time (matches how Week 8 calls it - once
  per anomaly candidate) rather than a batch/stream - batching wasn't needed for this week's scope.
- **RCA signature matching inherits Week 7's cumulative-counter limitation, and this week's live
  verification directly demonstrated the consequence**: `auth-key-error`'s and `db-lock`-adjacent
  signature checks against `http_server_requests_error_count` compare an absolute cumulative value
  to a fixed threshold, so a long-running session with several unrelated faults tested earlier can
  leave that counter elevated long after the fault that caused it is over, making a *different*,
  currently-active fault's RCA misattribute to `auth-key-error` (observed live this week - see
  "Live verification performed"). The gauge-based signatures (`hikaricp_connections_active`,
  `jvm_memory_used_bytes`) don't have this problem, since gauges reflect current state, not a
  lifetime total. Reasonable fix direction for a future week: compute error-count and
  request-count signatures from a windowed delta (e.g. the difference between this record and the
  same service's telemetry a fixed number of cycles earlier) rather than the raw cumulative value
  - not implemented this week, consistent with Week 7's decision to leave the same underlying
  counter-vs-rate issue as documented future work rather than redesigning the metric schema
  mid-week.
- The RCA's optional LLM narrative uses the same small `llama3.2:1b` model as Week 7's
  interpretation step; live verification showed it can summarize numeric evidence imprecisely
  (e.g. restating "9.0" as "5" in one sentence of a db-lock narrative). This never affects the
  deterministic conclusion (`suspected_root_cause_service`, `confidence`,
  `determination_method`), only the free-text `llm_reasoning` field, and is an expected tradeoff
  of using a 1.2B-parameter model rather than a larger one (see "Ollama integration" above for why
  this model was chosen for this machine).
- Remediation proposal templates exist for the four already-known controlled faults; a genuinely
  novel anomaly (one that matches no signature and finds no useful retrieval evidence) correctly
  falls back to a generic, low-risk `"investigate_manually"` proposal rather than a specific
  action - this is intentional, not a gap to fill by guessing.
