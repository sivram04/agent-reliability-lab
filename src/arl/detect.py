"""`arl detect`: find the AI agent in a project and propose a target for it.

Static scan only: files are read as text, nothing is imported or run. Each candidate says which
framework it found, where, the target settings to use, why, and anything the user still has to do,
ranked by confidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", ".arl", ".venv", "venv", "env", "node_modules", "__pycache__", "site-packages", "dist",
             "build", ".tox", ".mypy_cache", ".pytest_cache", "tests", "test", "fixtures", "examples", "docs"}
LOW_PRIORITY = re.compile(r"(^|/)(bench|benchmarks?|scripts|mocks?|samples?|demo|notebooks?)(/|$)|mock_|_mock|fake",
                          re.I)
MAX_FILES = 3000
MAX_BYTES = 400_000

SDK_CALL = re.compile(r"\.(?:chat\.completions\.create|messages\.create|generate_content|completion)\(|"
                      r"urlopen|httpx\.|requests\.post")
CLIENT_MODULE = re.compile(r"(^|/)(llm|llms|client|clients|model|models|provider|providers)\.py$")
START_SERVER = "Start the server before checks; adjust the port if needed."
ROUTE_WORDS = re.compile(r"chat|completion|message|ask|agent|query|respond|research|invoke|run|generate", re.I)


@dataclass
class Candidate:
    framework: str
    adapter: str
    file: str
    symbol: str | None = None
    confidence: float = 0.5
    settings: dict = field(default_factory=dict)  # target fields beyond adapter
    reason: str = ""
    note: str = ""  # what the user still has to do

    @property
    def ready(self) -> bool:
        """Usable as-is, without writing code (an HTTP server only has to be started)."""
        return not self.note or self.note == START_SERVER

    def target(self, name: str = "my-agent") -> dict:
        return {"name": name, "version": "1", "adapter": self.adapter, **self.settings}


def _module(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if "src" in parts[:-1]:
        parts = parts[len(parts) - parts[::-1].index("src"):]  # src layout: import path starts after src/
    return ".".join(parts)


def _assigned(text: str, call: str) -> list[str]:
    """Module-level names assigned from a call: `name = Call(` or `name: T = Call(`."""
    return re.findall(rf"^(\w+)\s*(?::[^=\n]+)?=\s*(?:await\s+)?(?:{call})\s*\(", text, re.M)


# (framework, adapter, import pattern, call pattern for the agent object, confidence)
OBJECT_RULES = [
    ("OpenAI Agents SDK", "openai_agents", r"^\s*from agents import|^\s*import agents\b", r"Agent", 0.95),
    ("PydanticAI", "pydantic_ai", r"pydantic_ai", r"Agent", 0.95),
    ("LangGraph", "langgraph", r"langgraph", r"[\w.]+\.compile", 0.95),
    ("LangGraph prebuilt agent", "langgraph", r"langgraph", r"create_react_agent", 0.9),
    ("LangChain agent", "langchain", r"langchain", r"create_agent|create_\w+_agent|AgentExecutor", 0.85),
    ("CrewAI", "crewai", r"crewai", r"Crew", 0.9),
    ("LlamaIndex", "llamaindex", r"llama_index",
     r"FunctionAgent|ReActAgent|AgentWorkflow|[\w.]+\.as_chat_engine|[\w.]+\.as_agent", 0.85),
]


def _objects(rel: str, mod: str, text: str) -> list[Candidate]:
    out = []
    for framework, adapter, imp, call, conf in OBJECT_RULES:
        if not re.search(imp, text, re.M):
            continue
        if adapter == "pydantic_ai" and re.search(r"^\s*from agents import", text, re.M):
            continue
        for name in _assigned(text, call):
            out.append(Candidate(framework, adapter, rel, name, conf, {"entrypoint": f"{mod}:{name}"},
                                 f"`{name}` is a {framework} agent object"))
    return out


def _factories(rel: str, mod: str, text: str) -> list[Candidate]:
    """Graphs built inside a function: `def build(...): ... return g.compile(...)`."""
    out = []
    if "langgraph" not in text:
        return out
    for fname, params, body in re.findall(r"^def\s+(\w+)\s*\(([^)]*)\)[^:\n]*:\n((?:[ \t]+.*\n|[ \t]*\n)+)",
                                          text, re.M):
        if not re.search(r"return\s+[\w.]+\.compile\(", body):
            continue
        required = [p for p in (x.strip() for x in params.split(","))
                    if p and "=" not in p and not p.startswith(("*", "self"))]
        messages_state = bool(re.search(r"MessagesState|add_messages", text))
        if not required and messages_state:
            out.append(Candidate("LangGraph (factory)", "langgraph", rel, fname, 0.9,
                                 {"entrypoint": f"{mod}:{fname}"}, f"`{fname}()` returns a compiled graph"))
            continue
        why = []
        if required:
            why.append(f"it needs arguments ({', '.join(p.split(':')[0] for p in required)})")
        if not messages_state:
            why.append("its state is not a `messages` list")
        out.append(Candidate(
            "LangGraph (factory)", "python", rel, fname, 0.6, {"entrypoint": "arl_entry:respond"},
            f"`{fname}(...)` returns a compiled graph",
            f"Can't be called directly because {' and '.join(why)}. Write arl_entry.py with "
            f"`def respond(messages) -> str` that builds the graph with {fname}(...), puts the last user "
            "message into its state, invokes it and returns the answer text."))
    return out


def _mcp(rel: str, mod: str, text: str) -> list[Candidate]:
    if not re.search(r"FastMCP|MCPServer", text):
        return []
    tools = re.findall(r"@\w+\.tool\([^)]*\)\s*\n\s*(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)", text)
    chat = [t for t, params in tools if "messages" in params] or \
           [t for t, _ in tools if t in ("chat", "ask", "respond", "query")]
    if not chat:
        return []
    takes_messages = any("messages" in p for t, p in tools if t == chat[0])
    note = "" if takes_messages else (f"Tool `{chat[0]}` takes a single input, but the lab calls it with "
                                      "{\"messages\": [...]}; add a tool that accepts the conversation.")
    if not all(part.isidentifier() for part in mod.split(".")):
        note = (note + " " if note else "") + "Check the -m module path; run it from where the package imports."
    return [Candidate("MCP server", "mcp", rel, chat[0], 0.8 if takes_messages else 0.55,
                      {"command": ["{python}", "-m", mod], "tool": chat[0]}, f"MCP server with tool `{chat[0]}`",
                      note)]


def _routes(rel: str, text: str) -> list[Candidate]:
    out = []
    low = text.lower()
    rules = (("FastAPI", "fastapi", r"@\w+\.post\(\s*[\"']([^\"']+)[\"']", "8000"),
             ("Flask", "flask", r"@\w+\.route\(\s*[\"']([^\"']+)[\"'][^)]*POST", "5000"))
    for fw, lib, pat, port in rules:
        if lib not in low:
            continue
        for route in re.findall(pat, text):
            if not ROUTE_WORDS.search(route):
                continue
            openai_style = "completions" in route
            params = re.findall(r"\{(\w+)\}", route)
            note = START_SERVER
            if params:
                note += f" Replace the path parameter(s) {', '.join(params)} with a real value."
            if not openai_style:
                note += (" The lab sends {\"messages\": [...]} and reads an OpenAI-style or {\"content\": ...} "
                         "reply; if this route takes other fields, add a small route that does.")
            conf = (0.75 if openai_style else 0.6) - (0.2 if params else 0)
            out.append(Candidate(f"{fw} endpoint", "http", rel, route, conf, {"url": f"http://localhost:{port}{route}"},
                                 f"{fw} POST route `{route}`", note))
    return out


def _functions(rel: str, mod: str, text: str) -> list[Candidate]:
    out = []
    client_module = bool(CLIENT_MODULE.search(rel) and SDK_CALL.search(text))
    for name in re.findall(r"^(?:async\s+)?def\s+(\w+)\s*\(\s*messages\b", text, re.M):
        if name.startswith("_"):
            continue
        if client_module:
            out.append(Candidate("LLM client helper", "python", rel, name, 0.3, {"entrypoint": f"{mod}:{name}"},
                                 f"`def {name}(messages, ...)` in an LLM client module",
                                 "This looks like the raw model call, not your agent. Testing it skips your "
                                 "prompts, tools and guardrails; point the target at the agent instead."))
        else:
            out.append(Candidate("Python function", "python", rel, name, 0.7, {"entrypoint": f"{mod}:{name}"},
                                 f"`def {name}(messages, ...)`"))
    return out


def _scan_file(root: Path, path: Path, text: str) -> list[Candidate]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    mod = _module(root, path)
    out = _objects(rel, mod, text) + _factories(rel, mod, text) + _mcp(rel, mod, text) + _routes(rel, text) \
        + _functions(rel, mod, text)
    if not out and re.search(r"\b(?:openai|anthropic|google\.genai|google\.generativeai|litellm|ollama)\b", text) \
            and SDK_CALL.search(text):
        out.append(Candidate("LLM SDK calls", "python", rel, None, 0.4, {"entrypoint": f"{mod}:respond"},
                             "calls an LLM SDK directly",
                             f"Add `def respond(messages: list[dict]) -> str` in {rel} that runs your agent "
                             "on the conversation, or point the target at an existing function."))
    return out


def _files(root: Path):
    n = 0
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name not in SKIP_DIRS and not p.name.startswith("."):
                    stack.append(p)
            elif p.suffix == ".py":
                n += 1
                if n > MAX_FILES:
                    return
                yield p


def _js_hint(root: Path) -> list[Candidate]:
    pkg = root / "package.json"
    if not pkg.is_file():
        return []
    text = pkg.read_text(encoding="utf-8", errors="ignore")
    libs = [lib for lib in ("@openai/agents", "@langchain/langgraph", "langchain", "ai", "@mastra/core",
                            "@anthropic-ai/sdk", "openai", "@modelcontextprotocol/sdk") if f'"{lib}"' in text]
    if not libs:
        return []
    return [Candidate("JavaScript/TypeScript agent", "http", "package.json", None, 0.35,
                      {"url": "http://localhost:3000/api/chat"}, f"uses {', '.join(libs)}",
                      "Expose the agent over HTTP (POST {\"messages\": [...]}) and set the URL, "
                      "or serve it as an MCP server and use `adapter: mcp`.")]


def detect(root: Path = Path(".")) -> list[Candidate]:
    root = root.resolve()
    found: list[Candidate] = []
    for path in _files(root):
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        found += _scan_file(root, path, text)
    found += _js_hint(root)
    for c in found:
        if LOW_PRIORITY.search(c.file):
            c.confidence = round(c.confidence - 0.3, 2)

    def rank(c: Candidate) -> tuple:
        stem = Path(c.file).stem
        bonus = 0.05 if re.search(r"agent|bot|graph|app|main|server|crew|chain|desk", stem) else 0
        return (-(c.confidence + bonus), c.file, c.symbol or "")

    seen: set[tuple] = set()
    unique = []
    for c in sorted(found, key=rank):
        key = (c.adapter, c.file, c.symbol)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique
