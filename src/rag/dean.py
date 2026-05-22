"""DeanSource — PKU Dean's Office (教务部) notices.

PKU's Dean's Office (https://dean.pku.edu.cn) publishes notices as
server-rendered HTML with no stable public JSON or RSS feed. Per the
"Implementation notes" of `docs/tasks/001_source_subclasses.md`, this
Source reads a fixed JSON snapshot checked into the repo
(`data/dean_notices.json`); the captain wires a live fetcher later.
The `fetch()` shape stays unchanged, so swapping in a real fetcher is
a drop-in replacement — and a network failure there should raise or
return empty rather than be folded into a Chunk.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

from .source import Chunk, Source

_DEFAULT_DATA_PATH = Path(__file__).with_name("data") / "dean_notices.json"


class DeanSource(Source):
    name: ClassVar[str] = "pku_dean"
    refresh_interval: ClassVar[int] = 3600  # ~1h — notices change slowly

    def __init__(self, data_path: Path | None = None) -> None:
        self._data_path = data_path or _DEFAULT_DATA_PATH

    def fetch(self) -> list[Chunk]:
        """Return one Chunk per Dean's Office notice."""
        raw = json.loads(self._data_path.read_text(encoding="utf-8"))
        chunks: list[Chunk] = []
        for notice in raw.get("notices", []):
            title = notice.get("title", "")
            body = notice.get("body", "")
            text = f"{title}\n\n{body}".strip() if body else title
            chunks.append(
                Chunk(
                    source_name=self.name,
                    identifier=notice["id"],
                    text=text,
                    metadata={
                        "title": title,
                        "url": notice.get("url"),
                        "publish_date": notice.get("publish_date"),
                        "category": notice.get("category"),
                    },
                )
            )
        return chunks
