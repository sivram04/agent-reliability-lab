"""`arl detect` and `arl init --adapter auto` on small synthetic projects, one per framework."""

import textwrap

import pytest
import yaml
from typer.testing import CliRunner

from arl.cli import app
from arl.detect import detect
from arl.init import scaffold
from arl.models import Target

PROJECTS = {
    "openai_agents": ("src/shop/agent.py", """
        from agents import Agent, Runner
        support = Agent(name="support", instructions="Help customers.")
    """, "shop.agent:support"),
    "pydantic_ai": ("bot.py", """
        from pydantic_ai import Agent
        agent: Agent = Agent("openai:gpt-4o-mini", instructions="Be helpful.")
    """, "bot:agent"),
    "langgraph": ("app/graph.py", """
        from langgraph.graph import StateGraph, MessagesState
        builder = StateGraph(MessagesState)
        graph = builder.compile()
    """, "app.graph:graph"),
    "crewai": ("crew.py", """
        from crewai import Agent, Crew, Task
        crew = Crew(agents=[], tasks=[])
    """, "crew:crew"),
    "llamaindex": ("rag.py", """
        from llama_index.core import VectorStoreIndex
        index = VectorStoreIndex([])
        chat_engine = index.as_chat_engine()
    """, "rag:chat_engine"),
    "langchain": ("chain.py", """
        from langchain.agents import create_agent
        agent = create_agent("openai:gpt-4o-mini", tools=[])
    """, "chain:agent"),
}


def _project(tmp_path, files: dict[str, str]):
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))
    return tmp_path


@pytest.mark.parametrize("adapter", sorted(PROJECTS))
def test_detects_each_framework(tmp_path, adapter):
    rel, body, entry = PROJECTS[adapter]
    best = detect(_project(tmp_path, {rel: body}))[0]
    assert best.adapter == adapter and best.settings["entrypoint"] == entry and best.ready


def test_factory_needing_arguments_asks_for_a_wrapper(tmp_path):
    _project(tmp_path, {"desk.py": """
        from langgraph.graph import StateGraph
        def build_desk(llm, tools):
            g = StateGraph(dict)
            return g.compile()
    """})
    best = detect(tmp_path)[0]
    assert best.adapter == "python" and not best.ready and "llm, tools" in best.note
    written = dict((p.name, s) for p, s in scaffold(tmp_path, detected=best, ci=False))
    assert written["arl_entry.py"] == "created"
    assert Target.load(tmp_path / "arl" / "target.yaml").entrypoint == "arl_entry:respond"


def test_llm_helper_ranks_below_the_agent(tmp_path):
    _project(tmp_path, {
        "pkg/llm.py": """
            import openai
            def chat(messages):
                return openai.chat.completions.create(model="m", messages=messages)
        """,
        "pkg/bot.py": """
            def respond(messages):
                return "hi"
        """})
    found = detect(tmp_path)
    assert found[0].settings["entrypoint"] == "pkg.bot:respond"
    helper = next(c for c in found if c.framework == "LLM client helper")
    assert not helper.ready


def test_routes_mcp_and_skipped_dirs(tmp_path):
    _project(tmp_path, {
        "api.py": """
            from fastapi import FastAPI
            app = FastAPI()
            @app.post("/v1/chat/completions")
            def chat(body: dict): ...
            @app.post("/reports/{rid}/ask")
            def ask(rid: str): ...
        """,
        "server.py": """
            from mcp.server.mcpserver import MCPServer
            server = MCPServer("x")
            @server.tool()
            def chat(messages: list[dict]) -> str: ...
        """,
        ".venv/lib/agents_copy.py": "from agents import Agent\nx = Agent(name='n')\n",
        "tests/test_bot.py": "def respond(messages): ...\n",
    })
    found = detect(tmp_path)
    files = {c.file for c in found}
    assert not any(f.startswith((".venv", "tests")) for f in files)
    openai_route = next(c for c in found if c.symbol == "/v1/chat/completions")
    param_route = next(c for c in found if c.symbol == "/reports/{rid}/ask")
    mcp = next(c for c in found if c.adapter == "mcp")
    assert openai_route.ready and not param_route.ready and "rid" in param_route.note
    assert mcp.ready and mcp.settings == {"command": ["{python}", "-m", "server"], "tool": "chat"}


def test_init_auto_writes_a_loadable_target(tmp_path):
    rel, body, entry = PROJECTS["pydantic_ai"]
    _project(tmp_path, {rel: body})
    res = CliRunner().invoke(app, ["init", str(tmp_path), "--no-ci"])
    assert res.exit_code == 0 and "Found PydanticAI" in res.output
    target = Target.load(tmp_path / "arl" / "target.yaml")
    assert target.adapter == "pydantic_ai" and target.entrypoint == entry and target.secrets
    raw = (tmp_path / "arl" / "target.yaml").read_text()
    assert raw.startswith("# Detected: PydanticAI") and yaml.safe_load(raw)


def test_empty_project_falls_back_to_template(tmp_path):
    res = CliRunner().invoke(app, ["init", str(tmp_path), "--no-ci"])
    assert res.exit_code == 0 and "No agent found" in res.output
    assert Target.load(tmp_path / "arl" / "target.yaml").adapter == "http"
