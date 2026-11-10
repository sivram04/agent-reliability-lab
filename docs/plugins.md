# Plugins

A plugin is a Python module that registers checks, red-team mutators, judge rubrics or adapters when it
is imported.

```python
import arl

@arl.check
def max_sorry(ctx: arl.CheckContext):
    limit = ctx.scenario.criteria.extra.get("max_sorry")
    if limit is None:
        return None                      # only scenarios that opt in
    n = ctx.replies.count("sorry")
    return arl.Check(name="max_sorry", passed=n <= limit, detail=f"{n} <= {limit}")

@arl.mutator("shout")
def shout(text, rng):                    # rng: random.Random, for reproducible variants
    return text.upper() + "!!!"

arl.register_rubric("tone", "Is every assistant reply polite and calm?")

@arl.adapter("grpc")
def grpc_adapter(target):                # target: arl.models.Target
    async def call(messages):
        ...
        return reply_text
    return call
```

`CheckContext` has `scenario`, `transcript`, `replies` (assistant text, lowercased), `latency_s`,
`secrets`, `stop_reason` and `tool_calls`. A check returns a `Check`, a list of them, or `None`. A check that
raises fails as `plugin:<name>` without stopping the run.

## Loading
- **Local module:** `arl --plugin my_checks run ...`, or `ARL_PLUGINS=my_checks,other`.
- **Installed package:** declare an entry point, and the plugin loads automatically:
  ```toml
  [project.entry-points."arl.plugins"]
  my_checks = "my_checks"
  ```

See `fixtures/example_plugin.py` in the repository for a working example.
