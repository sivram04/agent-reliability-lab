"""The good fixture agent as a one-node LangGraph graph."""

from langgraph.graph import START, MessagesState, StateGraph

from fixtures.agents import good_agent


def _respond(state: MessagesState) -> dict:
    messages = [
        {"role": "user" if m.type == "human" else "assistant", "content": m.content}
        for m in state["messages"]
    ]
    return {"messages": [{"role": "assistant", "content": good_agent(messages)}]}


_builder = StateGraph(MessagesState)
_builder.add_node("respond", _respond)
_builder.add_edge(START, "respond")
graph = _builder.compile()
