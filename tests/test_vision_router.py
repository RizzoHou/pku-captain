"""VisionRouter — the keyword heuristic that auto-routes doc questions to Kimi."""

from __future__ import annotations

import pytest

from src.core.vision_router import VisionRouter


@pytest.mark.parametrize(
    "text",
    [
        "数学学院的培养方案是什么？",
        "毕业总学分要求是多少",
        "辅修双学位怎么修",
        "选课手册里通识课怎么算",
        "专业必修有哪些课",
    ],
)
def test_routes_doc_questions(text: str) -> None:
    assert VisionRouter().needs_doc_base(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "今天天气怎么样",
        "帮我查一下作业",
        "树洞有什么新消息",
        "现在几点了",
        "",
    ],
)
def test_ignores_non_doc_questions(text: str) -> None:
    # Generic study words (学分/课程/专业 alone) deliberately do not trigger, to
    # avoid resetting an ordinary chat onto Kimi.
    assert VisionRouter().needs_doc_base(text) is False


def test_bare_study_words_do_not_trigger() -> None:
    assert VisionRouter().needs_doc_base("这门课几学分") is False
    assert VisionRouter().needs_doc_base("我想选这门课") is False
