import json
from pathlib import Path

from src.core.announcement_history import AnnouncementHistoryStore


def test_announcement_history_store_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "announcement_history.json"
    store = AnnouncementHistoryStore(path)
    items = [
        {
            "id": "a1",
            "course": "程序设计实习",
            "title": "通知一",
            "url": "https://course.pku.edu.cn/notice/a1",
        }
    ]

    store.save(items)

    assert store.load() == items
    assert json.loads(path.read_text(encoding="utf-8")) == {"announcements": items}


def test_announcement_history_store_survives_bad_file(tmp_path: Path) -> None:
    path = tmp_path / "announcement_history.json"
    path.write_text("{not json", encoding="utf-8")

    assert AnnouncementHistoryStore(path).load() == []
