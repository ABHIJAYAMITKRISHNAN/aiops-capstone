"""Runs additional real, live controlled-fault experiments against the actual running services,
reusing Week 5's telemetry.experiment.run_experiment() unchanged (aside from the optional
inject_body parameter added there this week - see telemetry/experiment.py).

This module does not itself compute any incident data - it only drives the real system. Incident
reconstruction happens afterwards, in incidents.py, from whatever raw JSONL this produces.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # repo root, so `import telemetry` resolves

from telemetry import experiment as telemetry_experiment  # noqa: E402

log = logging.getLogger("dataset_tools.generate")

# (baseline_seconds, fault_seconds, recovery_seconds, interval_seconds) - deliberately varied
# per run so the resulting real incidents differ in phase duration and sample density, while
# staying short enough that generating several of these live is practical.
TIMING_VARIANTS = [
    (10, 15, 10, 2),
    (15, 10, 15, 3),
    (8, 20, 8, 2),
]

# notification-latency specific: vary the injected delay itself (via the existing, already-safe
# /inject-latency optional body) - includes one value (3000ms) *below* payment-service's ~5000ms
# client timeout, which produces a different (SENT-but-slow, not FAILED) real outcome than the
# other runs, for genuine behavioral variety rather than just timing noise.
NOTIFICATION_DELAY_VARIANTS = [3000, 8000, 10000]


def run_additional_real_experiments(runs_per_fault: int = 3, data_dir=None) -> None:
    """Runs `runs_per_fault` additional live experiments for each of the four faults, on top of
    whatever real experiments already exist in telemetry/data/ from Week 5. Safe to call multiple
    times - each run is independent and always resets the fault before returning."""
    faults = sorted(telemetry_experiment.FAULTS.keys())
    for fault_name in faults:
        for i in range(runs_per_fault):
            baseline_s, fault_s, recovery_s, interval_s = TIMING_VARIANTS[i % len(TIMING_VARIANTS)]
            inject_body = None
            if fault_name == "notification-latency":
                inject_body = {"delayMs": NOTIFICATION_DELAY_VARIANTS[i % len(NOTIFICATION_DELAY_VARIANTS)]}

            log.info("Running additional real experiment %d/%d for '%s' (baseline=%ss fault=%ss recovery=%ss interval=%ss body=%s)",
                      i + 1, runs_per_fault, fault_name, baseline_s, fault_s, recovery_s, interval_s, inject_body)
            telemetry_experiment.run_experiment(
                fault_name,
                baseline_seconds=baseline_s,
                fault_seconds=fault_s,
                recovery_seconds=recovery_s,
                interval=interval_s,
                data_dir=data_dir,
                inject_body=inject_body,
            )
            time.sleep(1)  # brief pause between experiments so file-rotation timestamps never collide


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    run_additional_real_experiments()
