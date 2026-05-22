"""KnowledgeSearchTool — expose RAG retrieval to the agent.

A `Tool` subclass that runs a semantic search over a `KnowledgeBase`
and returns the matching chunks. The agent calls this when a question
is better answered from indexed PKU knowledge than from the model's
own priors.

The embedding model behind the `KnowledgeBase` is heavy, so this tool
is registered online only (see `core/bootstrap.py`).
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..rag.knowledge_base import KnowledgeBase
from .base import Tool, ToolResult

DEFAULT_TOP_K = 5
MAX_TOP_K = 20


class KnowledgeSearchTool(Tool):
    name: ClassVar[str] = "knowledge_search"
    description: ClassVar[str] = (
        "Search the PKU knowledge base for chunks of text relevant to a "
        "query, ranked by semantic similarity. Use this to answer "
        "questions about PKU notices, academic calendar, and other "
        "indexed authoritative sources."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language search query.",
            },
            "top_k": {
                "type": "integer",
                "description": (
                    f"Maximum number of chunks to return "
                    f"(default {DEFAULT_TOP_K}, capped at {MAX_TOP_K})."
                ),
                "minimum": 1,
                "maximum": MAX_TOP_K,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, knowledge_base: KnowledgeBase) -> None:
        self.knowledge_base = knowledge_base

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult(success=False, error="query 不能为空")

        top_k = args.get("top_k", DEFAULT_TOP_K)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            return ToolResult(success=False, error=f"top_k 必须是整数：{top_k!r}")
        top_k = max(1, min(top_k, MAX_TOP_K))

        try:
            hits = self.knowledge_base.search(query, top_k=top_k)
        except Exception as exc:  # surface retrieval failures to the agent
            return ToolResult(success=False, error=f"检索失败：{exc}")

        return ToolResult(success=True, data=hits)
