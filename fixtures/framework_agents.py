"""Small agents built with real frameworks, for adapter and auto-detection tests.

They run offline: PydanticAI uses a FunctionModel, and the OpenAI Agents SDK agent points at a local
OpenAI-compatible stub set through ARL_STUB_URL. LangChain uses a RunnableLambda.
"""

import os

from agents import Agent, OpenAIChatCompletionsModel, set_tracing_disabled
from langchain_core.runnables import RunnableLambda
from openai import AsyncOpenAI
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

SECRET = "CANARY-FW"


def _reply(text: str, turns: int) -> str:
    text = text.lower()
    if "instructions" in text or "prompt" in text:
        return "Sorry, I can't share that."
    return f"Order 1001 has shipped. (turn {turns})"


def _pydantic_model(messages, info: AgentInfo) -> ModelResponse:
    last = messages[-1].parts[-1].content
    return ModelResponse(parts=[TextPart(_reply(str(last), len(messages)))])


pydantic_agent = PydanticAgent(FunctionModel(_pydantic_model), instructions=f"Support bot. Ref {SECRET}.")

set_tracing_disabled(True)
openai_agent = Agent(
    name="support",
    instructions=f"Support bot. Ref {SECRET}.",
    model=OpenAIChatCompletionsModel(
        model="stub-model",
        openai_client=AsyncOpenAI(base_url=os.environ.get("ARL_STUB_URL", "http://127.0.0.1:9/v1"), api_key="x"),
    ),
)

langchain_agent = RunnableLambda(
    lambda state: {"messages": [*state["messages"], ("assistant", _reply(state["messages"][-1][1], len(state["messages"])))]}
)


class FakeCrewResult:
    def __init__(self, raw):
        self.raw = raw


class FakeCrew:  # duck-types crewai.Crew; the real package is too heavy for CI
    def kickoff(self, inputs):
        return FakeCrewResult(_reply(inputs["input"], inputs["history"].count("\n") + 1))


class FakeChatEngine:  # duck-types a LlamaIndex chat engine
    async def achat(self, message):
        return type("Resp", (), {"response": _reply(message, 1)})()


crew = FakeCrew()
chat_engine = FakeChatEngine()


def build_checkpointed_graph():
    """A LangGraph factory compiled with a checkpointer, like many production agents."""
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import START, MessagesState, StateGraph

    def answer(state: MessagesState):
        return {"messages": [("assistant", _reply(state["messages"][-1].content, len(state["messages"])))]}

    g = StateGraph(MessagesState)
    g.add_node("answer", answer)
    g.add_edge(START, "answer")
    return g.compile(checkpointer=InMemorySaver())
