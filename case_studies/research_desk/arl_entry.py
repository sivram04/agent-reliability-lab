"""Case study 3: the AI Research Desk (Project 2), a LangGraph multi-agent analyst, tested in-process.

Runs the real desk (planner, fundamentals, risk, transcript, quant, bull, bear, critic, writer) over its real
SEC filing index, with the human-in-the-loop pauses switched off so each question runs to a report.
Filing search goes through an @arl.tool so the lab sees what the agents retrieve and can poison it.
Run from the research desk's repo root with its virtualenv (it needs that project's data and packages).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import arl

DESK = Path(__file__).resolve().parents[3] / "02-ai-research-desk"
sys.path.insert(0, str(DESK / "src"))

from research_desk.agents.desk import Tools, build_desk  # noqa: E402
from research_desk.api import Backend  # noqa: E402
from research_desk.llm import chat  # noqa: E402
from research_desk.retrieval.index import Filters  # noqa: E402

TICKER = "AAPL"
AS_OF = "2025-06-30"
_backend = Backend(data=DESK / "data", fetch_releases=False)


@arl.tool
def search_filings(query: str, as_of: str, ticker: str, k: int = 8) -> list:
    return _backend.idx.search(query, Filters(date.fromisoformat(as_of), (ticker,)), k=k)


def _llm(system: str, user: str) -> str:
    return chat([{"role": "system", "content": system}, {"role": "user", "content": user}])


_tools = Tools(search=lambda q, as_of, ticker, k: search_filings(q, as_of, ticker, k),
               facts=_backend.facts, graph=_backend.graph, memory=None, releases=None,
               human_in_loop=False)
DESK_GRAPH = build_desk(_llm, _tools)


def respond(messages: list[dict]) -> str:
    question = messages[-1]["content"][:1000]
    out = DESK_GRAPH.invoke({"question": question, "ticker": TICKER, "as_of": AS_OF, "user": "arl"},
                            {"configurable": {"thread_id": f"arl-{abs(hash(question))}"}})
    return out.get("report") or "(no report)"
