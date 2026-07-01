"""Tests for PlibClient.search_all auto-pagination (no network).

These build a client without touching the network or ~/.cache by constructing
it via __new__ and stubbing the single-page .search with fabricated pages.
"""

from __future__ import annotations

from plib_cli.client import PlibClient
from plib_cli.models import SearchPage, SearchResult


def _result(i: int) -> SearchResult:
    return SearchResult(
        id=i,
        title=f"m{i}",
        type=None,
        description=None,
        course=None,
        department=None,
        semester=None,
        uploader=None,
        date=None,
        downloads=None,
        views=None,
        favorites=None,
        url=f"https://pkuhub.cn/material/{i}",
    )


def _client_with_pages(pages: dict[int, list[int]], total: int | None) -> PlibClient:
    """A bare client whose .search returns canned pages keyed by page number."""
    client = PlibClient.__new__(PlibClient)

    def fake_search(query, *, type=None, time=None, sort="relevance", page=1):
        ids = pages.get(page, [])
        return SearchPage(
            query=query,
            page=page,
            total=total,
            results=[_result(i) for i in ids],
        )

    client.search = fake_search  # instance attr → not bound, no self passed
    return client


def test_search_all_aggregates_and_dedups() -> None:
    # 44 across 5 pages; page 3 repeats one id from page 2 (site ordering drift).
    pages = {
        1: list(range(1, 11)),
        2: list(range(11, 21)),
        3: [20] + list(range(21, 30)),  # 20 is a duplicate of page 2's last id
        4: list(range(30, 40)),
        5: list(range(40, 44)),
    }
    client = _client_with_pages(pages, total=44)
    page = client.search_all("q")
    ids = [r.id for r in page.results]
    assert len(ids) == len(set(ids))  # deduped
    assert page.total == 44
    assert page.page == 1
    # 10+10+9(after dedup)+10+4 = 43 unique; count below total flags the dupe.
    assert len(page.results) == 43


def test_search_all_respects_limit_and_stops_early() -> None:
    calls = []
    pages = {p: list(range(p * 100, p * 100 + 10)) for p in range(1, 6)}
    client = _client_with_pages(pages, total=44)
    inner = client.search

    def counting(query, **kw):
        calls.append(kw.get("page", 1))
        return inner(query, **kw)

    client.search = counting
    page = client.search_all("q", limit=15)
    assert len(page.results) == 15
    assert calls == [1, 2]  # stopped after the limit was satisfied


def test_search_all_stops_on_empty_page_when_total_unknown() -> None:
    pages = {1: [1, 2, 3], 2: [4, 5], 3: []}
    client = _client_with_pages(pages, total=None)
    page = client.search_all("q")
    assert [r.id for r in page.results] == [1, 2, 3, 4, 5]
    assert page.total is None


def test_search_all_stops_on_all_duplicate_page() -> None:
    # Site ignores the page param and serves page 1 forever.
    pages = {p: [1, 2, 3] for p in range(1, 60)}
    client = _client_with_pages(pages, total=None)
    page = client.search_all("q")
    assert [r.id for r in page.results] == [1, 2, 3]
