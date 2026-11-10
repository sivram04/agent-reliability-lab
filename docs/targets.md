# Targets

A target YAML describes the agent under test.

```yaml
name: support-bot
version: "2.3"             # shows up in reports and comparisons
adapter: http              # python | http | langgraph | mcp | a plugin adapter
secrets: ["CANARY-123"]    # must never appear in a reply
prices:                    # optional, USD per million tokens, for cost estimates
  gpt-4o-mini: {input: 0.15, output: 0.60}
```

## python
```yaml
adapter: python
entrypoint: my_package.agent:respond   # fn(messages: list[dict]) -> str, sync or async
```
In-process agents can mark tools with `@arl.tool`, which makes tool calls observable and lets scenarios
inject faults into them:
```python
import arl

@arl.tool
def get_order(order_id: str) -> dict: ...
```

## http
```yaml
adapter: http
url: http://localhost:8000/v1/chat/completions
model: my-model                     # sent as "model" (OpenAI-compatible endpoints)
system_prompt: You are ... CANARY-123 ...
headers: {Authorization: "Bearer ${MY_KEY}"}   # ${VAR} is read from the environment
block_types: [guardrail_blocked]    # error types that mean "refused by guardrails"
max_retries: 4                      # 429 / 5xx
timeout_s: 60
```
The body is `{"messages": [...]}`. Responses may be OpenAI-style (`choices[0].message.content`, with
`usage` recorded for token accounting) or `{"content": "..."}`.

## langgraph
```yaml
adapter: langgraph
entrypoint: my_package.graph:graph   # compiled graph with a `messages` state key
```

## mcp
```yaml
adapter: mcp
command: ["{python}", "-m", "my_package.server"]   # stdio server; {python} = current interpreter
tool: chat                                          # takes {"messages": [...]}, returns text
```

!!! note
    Only in-process Python agents expose `@arl.tool` calls. HTTP and MCP agents are black boxes:
    tool-call checks and fault injection do not apply to them.
