"""Configuration for the Week 5 telemetry collector.

Every value is overridable via environment variables so the exact same code runs unmodified
against native processes, Docker Compose, or `kubectl port-forward`'d Kubernetes services - in
all three modes the four app services are reachable on the same localhost ports, just via a
different underlying mechanism.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    base_url: str


def _service(name: str, env_var: str, default_port: int) -> ServiceConfig:
    default_url = f"http://localhost:{default_port}"
    return ServiceConfig(name=name, base_url=os.environ.get(env_var, default_url).rstrip("/"))


SERVICES: list[ServiceConfig] = [
    _service("auth-service", "TELEMETRY_AUTH_SERVICE_URL", 8081),
    _service("payment-service", "TELEMETRY_PAYMENT_SERVICE_URL", 8082),
    _service("ledger-service", "TELEMETRY_LEDGER_SERVICE_URL", 8083),
    _service("notification-service", "TELEMETRY_NOTIFICATION_SERVICE_URL", 8084),
]

COLLECTION_INTERVAL_SECONDS = float(os.environ.get("TELEMETRY_INTERVAL_SECONDS", "10"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("TELEMETRY_HTTP_TIMEOUT_SECONDS", "5"))
DATA_DIR = Path(os.environ.get("TELEMETRY_DATA_DIR", str(Path(__file__).parent / "data")))

# Synthetic payment probe - see payment_probe.py for why this exists (some faults, e.g. the auth
# signing-key error and notification latency, only manifest on a real request, not on passive
# health/metric polling).
PROBE_USERNAME = os.environ.get("TELEMETRY_PROBE_USERNAME", "alice")
PROBE_PASSWORD = os.environ.get("TELEMETRY_PROBE_PASSWORD", "alice-pass")
PROBE_ACCOUNT_ID = os.environ.get("TELEMETRY_PROBE_ACCOUNT_ID", "acct-42")
PROBE_CURRENCY = os.environ.get("TELEMETRY_PROBE_CURRENCY", "USD")
PROBE_AMOUNT = float(os.environ.get("TELEMETRY_PROBE_AMOUNT", "0.01"))
