import responses

from telemetry import collector
from telemetry.config import ServiceConfig

SAMPLE_PROMETHEUS_TEXT = """
# HELP jvm_memory_used_bytes The amount of used memory
# TYPE jvm_memory_used_bytes gauge
jvm_memory_used_bytes{area="heap",id="G1 Eden Space"} 1.0E7
jvm_memory_used_bytes{area="heap",id="G1 Old Gen"} 2.0E7
jvm_memory_used_bytes{area="nonheap",id="Metaspace"} 5.0E6
# HELP jvm_memory_committed_bytes The amount of memory guaranteed to be available
# TYPE jvm_memory_committed_bytes gauge
jvm_memory_committed_bytes{area="heap",id="G1 Eden Space"} 4.0E7
jvm_memory_committed_bytes{area="heap",id="G1 Old Gen"} 4.0E7
# HELP jvm_memory_max_bytes The maximum amount of memory
# TYPE jvm_memory_max_bytes gauge
jvm_memory_max_bytes{area="heap",id="G1 Eden Space"} -1.0
jvm_memory_max_bytes{area="heap",id="G1 Old Gen"} 4.0E9
# HELP hikaricp_connections_active Active connections
# TYPE hikaricp_connections_active gauge
hikaricp_connections_active{pool="HikariPool-1"} 9.0
# HELP hikaricp_connections_idle Idle connections
# TYPE hikaricp_connections_idle gauge
hikaricp_connections_idle{pool="HikariPool-1"} 1.0
# HELP hikaricp_connections_pending Pending threads
# TYPE hikaricp_connections_pending gauge
hikaricp_connections_pending{pool="HikariPool-1"} 3.0
# HELP hikaricp_connections_acquire_seconds Connection acquire time
# TYPE hikaricp_connections_acquire_seconds summary
hikaricp_connections_acquire_seconds_count{pool="HikariPool-1"} 4.0
hikaricp_connections_acquire_seconds_sum{pool="HikariPool-1"} 0.008
# HELP http_server_requests_seconds
# TYPE http_server_requests_seconds summary
http_server_requests_seconds_count{method="POST",outcome="SUCCESS",status="200",uri="/api/ledger/debit"} 10.0
http_server_requests_seconds_sum{method="POST",outcome="SUCCESS",status="200",uri="/api/ledger/debit"} 0.5
http_server_requests_seconds_count{method="POST",outcome="CLIENT_ERROR",status="404",uri="/api/ledger/debit"} 2.0
http_server_requests_seconds_sum{method="POST",outcome="CLIENT_ERROR",status="404",uri="/api/ledger/debit"} 0.02
# HELP http_client_requests_seconds
# TYPE http_client_requests_seconds summary
http_client_requests_seconds_count{method="POST",outcome="SUCCESS",status="200",uri="/api/notifications/receipt"} 5.0
http_client_requests_seconds_sum{method="POST",outcome="SUCCESS",status="200",uri="/api/notifications/receipt"} 6.2
# HELP process_cpu_usage The recent cpu usage for the Java Virtual Machine process
# TYPE process_cpu_usage gauge
process_cpu_usage 0.15
# HELP system_cpu_usage The recent cpu usage for the whole system
# TYPE system_cpu_usage gauge
system_cpu_usage 0.42
"""


class TestParseMetrics:
    def test_extracts_heap_memory_only(self):
        metrics = collector.parse_metrics(SAMPLE_PROMETHEUS_TEXT)
        assert metrics["jvm_memory_used_bytes"] == 30_000_000.0
        assert metrics["jvm_memory_committed_bytes"] == 80_000_000.0

    def test_excludes_negative_max_memory_samples(self):
        metrics = collector.parse_metrics(SAMPLE_PROMETHEUS_TEXT)
        # -1 (G1 Eden's "no max") must be excluded, only the real 4e9 max counts
        assert metrics["jvm_memory_max_bytes"] == 4_000_000_000.0

    def test_extracts_hikaricp_pool_state(self):
        metrics = collector.parse_metrics(SAMPLE_PROMETHEUS_TEXT)
        assert metrics["hikaricp_connections_active"] == 9.0
        assert metrics["hikaricp_connections_idle"] == 1.0
        assert metrics["hikaricp_connections_pending"] == 3.0
        assert metrics["hikaricp_connections_acquire_seconds_avg"] == 0.002

    def test_extracts_http_server_request_counts_and_error_count(self):
        metrics = collector.parse_metrics(SAMPLE_PROMETHEUS_TEXT)
        assert metrics["http_server_requests_count"] == 12.0
        assert metrics["http_server_requests_error_count"] == 2.0
        assert round(metrics["http_server_requests_avg_duration_ms"], 2) == round((0.52 / 12) * 1000, 2)

    def test_extracts_http_client_request_metrics(self):
        metrics = collector.parse_metrics(SAMPLE_PROMETHEUS_TEXT)
        assert metrics["http_client_requests_count"] == 5.0
        assert metrics["http_client_requests_avg_duration_ms"] == 1240.0

    def test_extracts_cpu_usage(self):
        metrics = collector.parse_metrics(SAMPLE_PROMETHEUS_TEXT)
        assert metrics["process_cpu_usage"] == 0.15
        assert metrics["system_cpu_usage"] == 0.42

    def test_missing_families_are_none_not_errors(self):
        metrics = collector.parse_metrics("# no metrics at all\n")
        assert metrics["jvm_memory_used_bytes"] is None
        assert metrics["hikaricp_connections_active"] is None
        assert metrics["http_server_requests_count"] is None


HEALTH_UP = {"status": "UP", "components": {"diskSpace": {"status": "UP"}, "livenessState": {"status": "UP"}}}
FAULT_INACTIVE = {"faultActive": False, "message": "inactive"}


class TestCollectService:
    @responses.activate
    def test_healthy_service_produces_a_fully_populated_record(self):
        svc = ServiceConfig(name="auth-service", base_url="http://localhost:9999")
        responses.add(responses.GET, "http://localhost:9999/actuator/health", json=HEALTH_UP, status=200)
        responses.add(responses.GET, "http://localhost:9999/actuator/prometheus", body=SAMPLE_PROMETHEUS_TEXT, status=200)
        responses.add(responses.GET, "http://localhost:9999/fault-status", json=FAULT_INACTIVE, status=200)

        record = collector.collect_service(svc)

        assert record["service"] == "auth-service"
        assert record["collection_error"] is None
        assert record["health"]["status"] == "UP"
        assert record["health"]["components"]["diskSpace"] == "UP"
        assert record["metrics"]["hikaricp_connections_active"] == 9.0
        assert record["fault"]["faultActive"] is False
        assert record["correlation_id"]  # non-empty

    @responses.activate
    def test_unavailable_service_is_recorded_as_a_collection_error_not_raised(self):
        svc = ServiceConfig(name="ledger-service", base_url="http://localhost:9998")
        # Deliberately do not register any responses for this base URL - `responses` raises
        # ConnectionError for any unregistered request while active, simulating a down service.

        record = collector.collect_service(svc)

        assert record["service"] == "ledger-service"
        assert record["collection_error"] is not None
        assert "health" in record["collection_error"]
        assert record["health"] is None
        assert record["metrics"] is None
        assert record["fault"] is None

    @responses.activate
    def test_partial_failure_still_captures_what_succeeded(self):
        svc = ServiceConfig(name="payment-service", base_url="http://localhost:9997")
        responses.add(responses.GET, "http://localhost:9997/actuator/health", json=HEALTH_UP, status=200)
        # /actuator/prometheus and /fault-status deliberately unregistered -> those two fail

        record = collector.collect_service(svc)

        assert record["health"]["status"] == "UP"
        assert record["metrics"] is None
        assert record["fault"] is None
        assert "metrics" in record["collection_error"]
        assert "fault-status" in record["collection_error"]


class TestCollectCycleTolerance:
    @responses.activate
    def test_one_unavailable_service_does_not_stop_collection_of_the_others(self):
        healthy = ServiceConfig(name="healthy-service", base_url="http://localhost:9996")
        down = ServiceConfig(name="down-service", base_url="http://localhost:9995")
        responses.add(responses.GET, "http://localhost:9996/actuator/health", json=HEALTH_UP, status=200)
        responses.add(responses.GET, "http://localhost:9996/actuator/prometheus", body=SAMPLE_PROMETHEUS_TEXT, status=200)
        responses.add(responses.GET, "http://localhost:9996/fault-status", json=FAULT_INACTIVE, status=200)
        # down-service has no registered responses at all

        records = collector.collect_cycle([healthy, down])

        assert len(records) == 2
        healthy_record = next(r for r in records if r["service"] == "healthy-service")
        down_record = next(r for r in records if r["service"] == "down-service")
        assert healthy_record["collection_error"] is None
        assert healthy_record["health"]["status"] == "UP"
        assert down_record["collection_error"] is not None
