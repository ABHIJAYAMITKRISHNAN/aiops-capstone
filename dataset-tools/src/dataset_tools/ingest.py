"""Loads the raw JSONL Week 5 produced (telemetry/data/*.jsonl) without modifying it.

Reads directly from telemetry/data/ - Week 5's raw output is treated as immutable; nothing here
ever writes back to that directory or duplicates it elsewhere in the repo.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from . import config


def _read_jsonl_glob(directory: Path, prefix: str) -> list[dict]:
    records: list[dict] = []
    if not directory.exists():
        return records
    for path in sorted(directory.glob(f"{prefix}_*.jsonl")):
        with open(path, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Malformed JSONL at {path}:{line_no}: {exc}") from exc
    return records


def load_events(directory: Path = config.TELEMETRY_DATA_DIR) -> list[dict]:
    return sorted(_read_jsonl_glob(directory, "events"), key=lambda r: r["timestamp"])


def load_telemetry(directory: Path = config.TELEMETRY_DATA_DIR) -> list[dict]:
    return sorted(_read_jsonl_glob(directory, "telemetry"), key=lambda r: r["timestamp"])


def load_payment_probes(directory: Path = config.TELEMETRY_DATA_DIR) -> list[dict]:
    return sorted(_read_jsonl_glob(directory, "payment_probes"), key=lambda r: r["timestamp"])


def write_jsonl(records: Iterable[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
