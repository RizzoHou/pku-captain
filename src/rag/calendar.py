"""CalendarSource — PKU academic calendar (校历).

PKU publishes the academic calendar as an HTML page / image with no
stable public data interface. Per the "Implementation notes" of
`docs/tasks/001_source_subclasses.md`, this Source reads a fixed JSON
snapshot checked into the repo (`data/academic_calendar.json`); the
captain wires a live fetcher later. The `fetch()` shape stays
unchanged, so swapping in a real fetcher is a drop-in replacement —
and a network failure there should raise or return empty rather than
be folded into a Chunk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from .source import Chunk, Source

_DEFAULT_DATA_PATH = Path(__file__).with_name("data") / "academic_calendar.json"


class CalendarSource(Source):
    name: ClassVar[str] = "pku_calendar"
    refresh_interval: ClassVar[int] = 24 * 3600  # ~24h — the calendar is static

    def __init__(self, data_path: Path | None = None) -> None:
        self._data_path = data_path or _DEFAULT_DATA_PATH

    def fetch(self) -> list[Chunk]:
        """Return one Chunk per academic-calendar event."""
        raw = json.loads(self._data_path.read_text(encoding="utf-8"))
        academic_year = raw.get("academic_year")
        term = raw.get("term")
        chunks: list[Chunk] = []
        for event in raw.get("events", []):
            name = event.get("name", "")
            note = event.get("note", "")
            date = event.get("date")
            start = event.get("start")
            end = event.get("end")
            if date:
                when = date
            elif start and end:
                when = f"{start} ~ {end}"
            else:
                when = start or end or ""
            header = f"{name}（{when}）" if when else name
            text = f"{header}\n{note}".strip() if note else header
            metadata: dict[str, object] = {
                "name": name,
                "type": event.get("type"),
                "academic_year": academic_year,
                "term": term,
            }
            if date:
                metadata["date"] = date
            if start:
                metadata["start"] = start
            if end:
                metadata["end"] = end
            chunks.append(
                Chunk(
                    source_name=self.name,
                    identifier=event["id"],
                    text=text,
                    metadata=metadata,
                )
            )
        return chunks
