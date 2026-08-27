"""Orchestrates a NORMAL -> FAULT -> RECOVERY telemetry experiment against one of the four
controlled faults, reusing the same Collector loop as continuous collection (collector.py) so the
resulting dataset is directly comparable to any other collection run.

Runs the collector in a background thread for the whole experiment duration, and at the scheduled
offsets calls the target service's inject/reset fault endpoints, writing a lightweight event
marker to events_<date>.jsonl each time. Week 6 can precisely reconstruct the four phases
(NORMAL / FAULT_INTRODUCTION / FAULT_ACTIVE / RECOVERY) by joining telemetry.jsonl's per-service
`fault.faultActive` field against these event timestamps - see README.md for the exact recipe.
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import requests

from . import config
from .collector import Collector
from .storage import JsonlWriter
from .util import now_iso

log = logging.getLogger("telemetry.experiment")

FAULTS = {
    "auth-key-error": {
        "service": "auth-service",
        "inject_path": "/inject-auth-key-error",
        "reset_path": "/reset-auth-key",
    },
    "memory-leak": {
        "service": "payment-service",
        "inject_path": "/inject-memory-leak",
        "reset_path": "/reset-memory-leak",
    },
    "db-lock": {
        "service": "ledger-service",
        "inject_path": "/inject-db-lock",
        "reset_path": "/reset-db-lock",
    },
    "notification-latency": {
        "service": "notification-service",
        "inject_path": "/inject-latency",
        "reset_path": "/reset-latency",
    },
}


def _service_url(name: str) -> str:
    return next(s.base_url for s in config.SERVICES if s.name == name)


def _call(base_url: str, path: str, json_body: Optional[dict] = None) -> dict:
    resp = requests.post(f"{base_url}{path}", json=json_body, timeout=config.HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json()


def run_experiment(
    fault_name: str,
    baseline_seconds: float = 30,
    fault_seconds: float = 30,
    recovery_seconds: float = 30,
    interval: Optional[float] = None,
    data_dir: Optional[Path] = None,
    inject_body: Optional[dict] = None,
) -> None:
    if fault_name not in FAULTS:
        raise ValueError(f"Unknown fault '{fault_name}'. Choose one of: {', '.join(sorted(FAULTS))}")

    fault = FAULTS[fault_name]
    base_url = _service_url(fault["service"])
    total_duration = baseline_seconds + fault_seconds + recovery_seconds

    resolved_data_dir = data_dir if data_dir is not None else config.DATA_DIR
    events = JsonlWriter(resolved_data_dir, "events")

    collector = Collector(interval=interval, probe_payment=True, data_dir=resolved_data_dir)
    # install_signal_handlers=False: signal.signal() only works in the main thread, and this
    # collector instance runs in a background thread for the duration of the experiment.
    collector_thread = threading.Thread(
        target=collector.run,
        kwargs={"duration": total_duration, "install_signal_handlers": False},
        daemon=True,
    )

    events.write({
        "timestamp": now_iso(), "event": "EXPERIMENT_START", "fault": fault_name,
        "service": fault["service"],
        "plan": {"baseline_seconds": baseline_seconds, "fault_seconds": fault_seconds, "recovery_seconds": recovery_seconds},
    })
    log.info(
        "Starting experiment '%s': baseline=%ss fault=%ss recovery=%ss (interval=%ss)",
        fault_name, baseline_seconds, fault_seconds, recovery_seconds, collector.interval,
    )

    collector_thread.start()

    time.sleep(baseline_seconds)
    try:
        result = _call(base_url, fault["inject_path"], json_body=inject_body)
        events.write({"timestamp": now_iso(), "event": "FAULT_INJECTED", "fault": fault_name,
                       "service": fault["service"], "response": result})
        log.info("Fault injected: %s", result)
    except Exception as exc:  # noqa: BLE001
        events.write({"timestamp": now_iso(), "event": "FAULT_INJECT_FAILED", "fault": fault_name,
                       "service": fault["service"], "error": str(exc)})
        log.error("Failed to inject fault: %s", exc)

    time.sleep(fault_seconds)
    try:
        result = _call(base_url, fault["reset_path"])
        events.write({"timestamp": now_iso(), "event": "FAULT_RESET", "fault": fault_name,
                       "service": fault["service"], "response": result})
        log.info("Fault reset: %s", result)
    except Exception as exc:  # noqa: BLE001
        events.write({"timestamp": now_iso(), "event": "FAULT_RESET_FAILED", "fault": fault_name,
                       "service": fault["service"], "error": str(exc)})
        log.error("Failed to reset fault: %s", exc)

    # auth-key-error specifically needs the probe's cached token dropped after reset, so the
    # recovery-phase probes go back to using a token minted under the restored key rather than
    # continuing to reuse a still-cached (now valid-again, but coincidentally so) old token.
    if fault_name == "auth-key-error":
        collector._payment_probe.force_new_token()  # noqa: SLF001 - same module, deliberate internal use

    time.sleep(recovery_seconds)
    collector_thread.join(timeout=10)
    events.write({"timestamp": now_iso(), "event": "EXPERIMENT_END", "fault": fault_name, "service": fault["service"]})
    events.close()
    log.info("Experiment '%s' complete. Data written under %s", fault_name, resolved_data_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a NORMAL -> FAULT -> RECOVERY telemetry experiment")
    parser.add_argument("fault", choices=sorted(FAULTS.keys()))
    parser.add_argument("--baseline-seconds", type=float, default=30)
    parser.add_argument("--fault-seconds", type=float, default=30)
    parser.add_argument("--recovery-seconds", type=float, default=30)
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--data-dir", type=str, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

    data_dir = Path(args.data_dir) if args.data_dir else None
    run_experiment(
        args.fault,
        baseline_seconds=args.baseline_seconds,
        fault_seconds=args.fault_seconds,
        recovery_seconds=args.recovery_seconds,
        interval=args.interval,
        data_dir=data_dir,
    )


if __name__ == "__main__":
    main()
