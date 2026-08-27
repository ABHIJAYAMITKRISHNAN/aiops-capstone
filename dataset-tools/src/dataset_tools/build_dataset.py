"""Assembles the full incident dataset: reconstructs real incidents from telemetry/data/,
generates deterministic synthetic incidents to reach the target count, assigns sequential
incident IDs, writes the combined dataset, performs the Memory/Evaluation split, and writes the
split manifest.

This is the one place real and synthetic incidents are merged - kept as a single, auditable
function rather than scattering the merge logic across callers.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import config, ingest, incidents as incidents_mod, reconstruct, split, synthetic_model

log = logging.getLogger("dataset_tools.build_dataset")

# Real incidents per fault type is whatever telemetry/data/ actually contains (grows as more
# live experiments are run - see generate.py). Synthetic incidents top each fault type up to
# this target so every fault type ends with the same total count.
TARGET_PER_FAULT_TYPE = 17  # 17 * 4 fault types = 68 incidents, within the 60-80 target range


def reconstruct_real_incidents() -> list[dict]:
    events = ingest.load_events()
    telemetry = ingest.load_telemetry()
    probes = ingest.load_payment_probes()

    experiments = reconstruct.group_experiments(events)
    real_incidents = []
    skipped = 0
    for exp in experiments:
        incident = incidents_mod.build_incident_from_experiment(exp, telemetry, probes, incident_id="__pending__")
        if incident is None:
            skipped += 1
            continue
        real_incidents.append(incident)

    if skipped:
        log.warning("Skipped %d experiment(s) with incomplete fault inject/reset data", skipped)
    log.info("Reconstructed %d real incidents from telemetry/data/", len(real_incidents))
    return real_incidents


def top_up_with_synthetic(real_incidents: list[dict], target_per_fault: int = TARGET_PER_FAULT_TYPE) -> list[dict]:
    real_by_fault: dict[str, int] = {}
    for inc in real_incidents:
        real_by_fault[inc["fault_type"]] = real_by_fault.get(inc["fault_type"], 0) + 1

    synthetic: list[dict] = []
    base_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for fault_type in config.FAULT_TYPES:
        have = real_by_fault.get(fault_type, 0)
        need = max(0, target_per_fault - have)
        if need > 0:
            batch = synthetic_model.generate_synthetic_batch(fault_type, need, base_seed=config.SPLIT_SEED, base_start=base_start)
            synthetic.extend(batch)
        log.info("fault_type=%s: %d real + %d synthetic = %d total", fault_type, have, need, have + need)

    return synthetic


def assign_incident_ids(incidents: list[dict]) -> list[dict]:
    """Deterministic ID assignment: sort by (fault_type, data_source, start_time) so the same
    input set always produces the same IDs regardless of dict/list construction order."""
    ordered = sorted(incidents, key=lambda inc: (inc["fault_type"], inc["data_source"], inc["start_time"]))
    for i, incident in enumerate(ordered, start=1):
        incident["incident_id"] = f"inc-{i:04d}"
        # description/summary/postmortem_text were generated before the final ID was known (real
        # incidents used a placeholder "__pending__", synthetic ones used None) - regenerate them
        # now from the same pure function so the persisted text embeds the real, final ID.
        incident.update(incidents_mod.generate_descriptions(incident))
    return ordered


def build(target_per_fault: int = TARGET_PER_FAULT_TYPE, out_dir: Optional[Path] = None) -> dict:
    real = reconstruct_real_incidents()
    synthetic = top_up_with_synthetic(real, target_per_fault)
    all_incidents = assign_incident_ids(real + synthetic)

    ingest.write_jsonl(all_incidents, config.ALL_INCIDENTS_FILE if out_dir is None else out_dir / "all_incidents.jsonl")

    memory, evaluation = split.stratified_split(all_incidents)
    ingest.write_jsonl(memory, config.MEMORY_INCIDENTS_FILE if out_dir is None else out_dir / "memory_incidents.jsonl")
    ingest.write_jsonl(evaluation, config.EVALUATION_INCIDENTS_FILE if out_dir is None else out_dir / "evaluation_incidents.jsonl")

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "total_incidents": len(all_incidents),
        "real_incidents": sum(1 for i in all_incidents if i["data_source"] == "real"),
        "synthetic_incidents": sum(1 for i in all_incidents if i["data_source"] == "synthetic"),
        "split": split.split_summary(memory, evaluation),
        "memory_incident_ids": sorted(i["incident_id"] for i in memory),
        "evaluation_incident_ids": sorted(i["incident_id"] for i in evaluation),
    }
    manifest_path = config.SPLIT_MANIFEST_FILE if out_dir is None else out_dir / "split_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    log.info("Dataset built: %d total (%d real, %d synthetic). Memory=%d Evaluation=%d",
              manifest["total_incidents"], manifest["real_incidents"], manifest["synthetic_incidents"],
              manifest["split"]["memory_count"], manifest["split"]["evaluation_count"])
    return manifest


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    result = build()
    print(json.dumps(result, indent=2))
