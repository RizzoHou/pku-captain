"""VisionRouter — decide whether a user turn needs the PKU document base.

The chat runs on DeepSeek by default, which is text-only and cannot read the
page images `doc_read` produces. When a question is about 培养方案 / 选课手册 /
辅修双学位 content, the GUI auto-switches to the vision-capable Kimi K2.6 brain
(in a fresh chat) so it can read the documents directly.

This v1 router is a curated-keyword heuristic: cheap, network-free (works
offline), and easy to defend at the roadshow. It deliberately keys on
doc-base-specific terms rather than broad words like 学分 / 课程 / 专业 so it does
not over-trigger and reset an ordinary chat. A flash-LLM confirmation pass is
the noted upgrade path.
"""

from __future__ import annotations

from typing import ClassVar


class VisionRouter:
    """Heuristic detector for questions that need the doc base (→ Kimi)."""

    # Doc-base-specific terms. Kept narrow on purpose: a false positive resets
    # the chat onto Kimi, so generic study words (学分/课程/专业) are excluded.
    TERMS: ClassVar[tuple[str, ...]] = (
        "培养方案",
        "培养计划",
        "教学计划",
        "培养目标",
        "选课手册",
        "辅修",
        "双学位",
        "双专业",
        "毕业总学分",
        "毕业要求",
        "毕业学分",
        "学分要求",
        "专业必修",
        "专业选修",
        "核心课程",
        "课程设置",
        "课程地图",
    )

    def needs_doc_base(self, text: str) -> bool:
        """True if `text` mentions a doc-base topic and should route to Kimi."""
        if not text:
            return False
        lowered = text.lower()
        return any(term in lowered for term in self.TERMS)
