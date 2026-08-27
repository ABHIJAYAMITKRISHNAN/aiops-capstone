"""Deterministic, stratified Memory/Evaluation split.

Stratified by fault_type so both sets contain a proportional share of all four fault types
(CLAUDE.md's dataset rule asks for "reasonable coverage of all four fault types in both sets").
Uses a fixed, documented seed (config.SPLIT_SEED) so re-running this against the same input
incident list always produces byte-identical Memory/Evaluation assignment - required for academic
reproducibility (CLAUDE.md rule 23).
"""
from __future__ import annotations

import random

from . import config


def stratified_split(incidents: list[dict], memory_fraction: float = config.MEMORY_FRACTION,
                      seed: int = config.SPLIT_SEED) -> tuple[list[dict], list[dict]]:
    by_fault: dict[str, list[dict]] = {}
    for incident in incidents:
        by_fault.setdefault(incident["fault_type"], []).append(incident)

    memory: list[dict] = []
    evaluation: list[dict] = []

    for fault_type in sorted(by_fault):  # sorted() so grouping order never depends on input order
        group = sorted(by_fault[fault_type], key=lambda inc: inc["incident_id"])  # deterministic order
        rng = random.Random(f"{seed}:{fault_type}")  # per-fault-type sub-seed derived from the one documented seed
        shuffled = group[:]
        rng.shuffle(shuffled)

        n_memory = round(len(shuffled) * memory_fraction)
        memory.extend(shuffled[:n_memory])
        evaluation.extend(shuffled[n_memory:])

    return memory, evaluation


def split_summary(memory: list[dict], evaluation: list[dict]) -> dict:
    def counts(incidents: list[dict]) -> dict:
        result: dict[str, int] = {}
        for inc in incidents:
            result[inc["fault_type"]] = result.get(inc["fault_type"], 0) + 1
        return result

    return {
        "memory_count": len(memory),
        "evaluation_count": len(evaluation),
        "memory_by_fault_type": counts(memory),
        "evaluation_by_fault_type": counts(evaluation),
        "seed": config.SPLIT_SEED,
    }
