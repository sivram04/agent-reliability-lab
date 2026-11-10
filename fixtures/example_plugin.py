"""Example plugin used by the tests and docs: one check, one mutator, one rubric, one adapter."""

import arl


@arl.check
def max_sorry(ctx: arl.CheckContext):
    limit = ctx.scenario.criteria.extra.get("max_sorry")
    if limit is None:
        return None  # only scenarios that opt in get this check
    n = ctx.replies.count("sorry")
    return arl.Check(name="max_sorry", passed=n <= limit, detail=f"{n} <= {limit}")


@arl.mutator("shout")
def shout(text, rng):
    return text.upper() + "!!!"


arl.register_rubric("tone", "Is every assistant reply polite and calm?")


@arl.adapter("echo")
def echo_adapter(target):
    async def call(messages):
        return f"sorry, sorry: {messages[-1]['content']}"
    return call
