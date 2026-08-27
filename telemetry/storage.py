"""Append-only, daily-rotating JSONL writer.

Bounded memory: every record is serialized and written to disk immediately - nothing is ever
buffered in memory across cycles, so long-running collection cannot accumulate unbounded RAM
usage. Bounded disk growth: a new file is started each UTC calendar day, so a single file can
never grow without limit across a long-running collection session; old files are plain JSONL and
can be archived/deleted independently.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TextIO


class JsonlWriter:
    def __init__(self, directory: Path, prefix: str):
        self._directory = Path(directory)
        self._prefix = prefix
        self._directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._current_date: Optional[str] = None
        self._file: Optional[TextIO] = None

    def _path_for(self, date_str: str) -> Path:
        return self._directory / f"{self._prefix}_{date_str}.jsonl"

    def write(self, record: dict) -> None:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if date_str != self._current_date or self._file is None:
                self._rotate(date_str)
            self._file.write(json.dumps(record, default=str) + "\n")
            self._file.flush()

    def _rotate(self, date_str: str) -> None:
        if self._file is not None:
            self._file.close()
        self._current_date = date_str
        self._file = open(self._path_for(date_str), "a", encoding="utf-8")

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
