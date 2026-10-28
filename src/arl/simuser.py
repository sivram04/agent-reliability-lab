"""LLM-driven simulated user (F4)."""

from __future__ import annotations

from .llm import LLM
from .models import Scenario

DONE, GIVE_UP = "[DONE]", "[GIVE_UP]"

PROMPT = """You are role-playing a human user who is chatting with an AI assistant.
Persona: {persona}
Your goal: {goal}

Rules:
- Write ONLY your next message to the assistant, in character. No narration.
- Adapt to what the assistant says. Give details it asks for if your persona would know them.
- If the goal has been achieved, reply with exactly {done}
- If the assistant clearly cannot or will not help after a fair attempt, reply with exactly {give_up}"""


class SimulatedUser:
    def __init__(self, llm: LLM, scenario: Scenario):
        self.llm = llm
        self.system = PROMPT.format(
            persona=scenario.persona or "an ordinary customer",
            goal=scenario.user_goal,
            done=DONE,
            give_up=GIVE_UP,
        )

    async def next_message(self, transcript: list[dict]) -> tuple[str | None, str | None]:
        """Returns (message, None) to continue, or (None, stop_reason) to stop."""
        # From the simulated user's side, the agent is the "user" and it is the "assistant".
        flipped = [
            {"role": "assistant" if m["role"] == "user" else "user", "content": m["content"]}
            for m in transcript
        ]
        if not flipped:
            flipped = [{"role": "user", "content": "(The assistant is waiting for your first message.)"}]
        reply = (await self.llm([{"role": "system", "content": self.system}, *flipped])).strip()
        if DONE in reply:
            return None, "goal_met"
        if GIVE_UP in reply:
            return None, "gave_up"
        return reply, None
