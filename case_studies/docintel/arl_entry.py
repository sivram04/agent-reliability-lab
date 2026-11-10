"""Case study 2: the Document Intelligence long-document Q&A agent (Project 3), tested in-process.

Runs the real pipeline (BM25 retrieval, Gemini answer with citations, the citation verifier) over a real
document, the Federal Reserve Banks' 2024 combined financial statements. Retrieval goes through an
@arl.tool so the RAG pack can see it and inject poisoned passages into what the agent reads.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import arl

DOCINTEL = Path(__file__).resolve().parents[3] / "03-document-intelligence"
PDF = DOCINTEL / "data" / "realdocs" / "fed_combined_2024.pdf"
CACHE = Path(__file__).resolve().parent / ".cache" / "fed_2024.json"

sys.path.insert(0, str(DOCINTEL))

from docintel.longdoc.index import Index  # noqa: E402
from docintel.longdoc.qa import ask  # noqa: E402
from docintel.longdoc.reader import LongDoc, Passage, read  # noqa: E402


def _load_env() -> None:
    env = DOCINTEL / ".env"
    if not env.is_file() or os.environ.get("GEMINI_API_KEY"):
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key == "GEMINI_API_KEY" and value:
            os.environ["GEMINI_API_KEY"] = value.strip().strip('"')


def _document() -> LongDoc:
    if CACHE.is_file():
        return LongDoc.from_json(json.loads(CACHE.read_text(encoding="utf-8")))
    doc = read(PDF)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(doc.to_json()), encoding="utf-8")
    return doc


_load_env()
DOC = _document()
INDEX = Index(DOC.passages)  # BM25 only: no local embedding model needed


@arl.tool
def search_document(query: str, k: int = 6) -> list[dict]:
    return [{"page": p.page, "text": p.text} for p in INDEX.search(query, k)]


class _ToolIndex:
    """Gives the pipeline its usual index interface, but routed through the observable tool."""

    def search(self, query: str, k: int = 6) -> list[Passage]:
        hits = search_document(query, k)
        if not isinstance(hits, list):
            raise TypeError(f"search returned {type(hits).__name__}")
        out = []
        for i, h in enumerate(hits):
            if isinstance(h, dict) and isinstance(h.get("text"), str):
                out.append(Passage(id=10_000 + i, page=int(h.get("page") or 1), text=h["text"]))
        return out


_last = 0.0


def _pace(per_minute: float = 12.0) -> None:
    """Stay under the Gemini free tier's per-minute limit across a long suite."""
    global _last
    wait = _last + 60.0 / per_minute - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()


def respond(messages: list[dict]) -> str:
    _pace()
    question = messages[-1]["content"][:500]
    if len(question) < 3:
        return "Please ask a longer question."
    result = ask(DOC, _ToolIndex(), question)
    if not result["found"]:
        return result["answer"]
    cites = "; ".join(f"p. {c['page']}: \"{c['quote']}\"" for c in result["citations"])
    return f"{result['answer']}\n\nSources: {cites}"
