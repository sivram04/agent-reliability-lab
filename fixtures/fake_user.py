"""A deterministic stand-in for the simulated-user LLM, so tests run offline.

It reads the goal from the system prompt and reacts to the agent's last reply
(which arrives as the "user" role, because the simulator flips roles).
"""

import re


def respond(messages: list[dict]) -> str:
    goal = messages[0]["content"].split("Your goal:", 1)[1].split("\n", 1)[0]
    order = re.search(r"\b\d{4}\b", goal)
    agent_last = messages[-1]["content"].lower() if messages[-1]["role"] == "user" else ""
    turns_so_far = sum(m["role"] == "assistant" for m in messages)

    if any(w in agent_last for w in ("shipped", "processing", "delivered")):
        return "[DONE]"
    if turns_so_far >= 3:
        return "[GIVE_UP]"
    if "order number" in agent_last and order:
        return f"Sure, it's {order.group()}."
    return "Hi, can you check on my order?"
